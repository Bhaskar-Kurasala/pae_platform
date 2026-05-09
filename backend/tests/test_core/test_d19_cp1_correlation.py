"""D19.1 CP1 — correlation-ID smoke tests.

Four tests cover the four scope items in the CP1 closure deliverables:

  a. Request-scope binding — RequestIDMiddleware binds request_id and
     a W3C-format trace_id derived from the same UUID4 bytes.
  b. Celery propagation value-equality — a task enqueued mid-request
     observes the same trace_id inside the worker (eager-mode).
  c. Auth-path binding — get_current_user binds user_id; an
     unauthenticated request does not.
  d. Sentry compatibility — a logged warning during a request appears
     as a Sentry breadcrumb carrying the correlation IDs without
     leaking redacted fields.

We use anyio (asyncio backend) per the rest of the suite. The Celery
test sets task_always_eager=True so the worker runs in-process — no
broker / worker required.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
import structlog
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.celery_logging import (
    CorrelatedTask,
    _bind_task_context,
    _unbind_task_context,
)
from app.core.request_id import (
    REQUEST_ID_HEADER,
    RequestIDMiddleware,
    _parse_traceparent,
    _trace_id_from_uuid,
)

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Helper: capture-the-context test endpoint
# ---------------------------------------------------------------------------


def _build_capture_app() -> tuple[FastAPI, dict[str, Any]]:
    """Build a minimal FastAPI app whose only route reads the structlog
    contextvars at request time and stuffs them into a captured dict."""
    captured: dict[str, Any] = {}

    router = APIRouter()

    @router.get("/__capture_ctx")
    async def capture_ctx() -> dict[str, Any]:
        # Snapshot the contextvars exactly as bound by the middleware.
        ctx = structlog.contextvars.get_contextvars() or {}
        captured.clear()
        captured.update(ctx)
        return {"ok": True}

    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    app.include_router(router)
    return app, captured


# ---------------------------------------------------------------------------
# (a) Request-scope binding
# ---------------------------------------------------------------------------


_HEX32_RE = re.compile(r"^[0-9a-f]{32}$")
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


async def test_request_id_and_trace_id_bound_in_context() -> None:
    """Mid-request, both request_id (UUID) and trace_id (32-hex) are
    bound to structlog contextvars; trace_id is derived from request_id
    so they share the same underlying identity."""
    app, captured = _build_capture_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/__capture_ctx")
    assert resp.status_code == 200

    request_id = captured.get("request_id")
    trace_id = captured.get("trace_id")

    assert isinstance(request_id, str) and _UUID_RE.match(request_id), (
        f"request_id absent or not UUID-shaped: {request_id!r}"
    )
    assert isinstance(trace_id, str) and _HEX32_RE.match(trace_id), (
        f"trace_id absent or not 32-hex: {trace_id!r}"
    )
    # Single-source-of-truth derivation: trace_id == request_id with
    # the dashes stripped.
    assert trace_id == request_id.replace("-", ""), (
        "trace_id should be derived from request_id's hex bytes"
    )


async def test_traceparent_header_adopted_when_well_formed() -> None:
    """If a caller supplies a W3C traceparent, the trace_id portion is
    adopted (CP1.1.c defensive read). The request_id is independent of
    traceparent and stays UUID4 so existing X-Request-ID semantics hold."""
    app, captured = _build_capture_app()

    incoming_trace = "0af7651916cd43dd8448eb211c80319c"
    traceparent = f"00-{incoming_trace}-b7ad6b7169203331-01"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get(
            "/__capture_ctx", headers={"traceparent": traceparent}
        )
    assert resp.status_code == 200
    assert captured.get("trace_id") == incoming_trace


def test_traceparent_parser_rejects_malformed_values() -> None:
    """Defensive parser: malformed traceparent → None, never raises."""
    assert _parse_traceparent(None) is None
    assert _parse_traceparent("") is None
    assert _parse_traceparent("garbage") is None
    # All-zeros trace-id is invalid per W3C spec.
    assert _parse_traceparent(
        "00-" + "0" * 32 + "-" + "1" * 16 + "-01"
    ) is None
    # Wrong field count.
    assert _parse_traceparent("00-abc-def") is None


def test_trace_id_from_uuid_matches_hex() -> None:
    """trace_id derivation is just uuid.hex — a single line of code we
    pin so a future refactor can't change the contract."""
    import uuid

    u = uuid.UUID("12345678-1234-1234-1234-123456789abc")
    assert _trace_id_from_uuid(u) == "12345678123412341234123456789abc"


# ---------------------------------------------------------------------------
# (b) Celery propagation value-equality (Q4 refinement)
# ---------------------------------------------------------------------------


async def test_celery_task_observes_same_trace_id_as_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A task enqueued mid-request observes the *same* trace_id value
    inside the worker. Eager-mode runs the task in-process, but the
    apply_async / prerun / postrun pipeline is identical to the broker
    path, so this exercises the contract that matters for CP2-CP5."""
    from celery import Celery

    # Local Celery app so we don't touch the platform's main broker.
    # task_cls MUST be passed at construction — Celery binds the task
    # base class then, not from .conf afterwards.
    cap_app = Celery(
        "d19-cp1-test",
        broker="memory://",
        backend="cache+memory://",
        task_cls=CorrelatedTask,
    )
    cap_app.conf.task_always_eager = True
    cap_app.conf.task_eager_propagates = True
    cap_app.conf.task_serializer = "json"
    cap_app.conf.accept_content = ["json"]

    # Connect prerun/postrun for THIS app instance — the global signal
    # connection in celery_logging.py also fires (it's app-agnostic).
    captured: dict[str, Any] = {}

    @cap_app.task(name="d19_cp1_capture")
    def capture_in_task() -> dict[str, Any]:
        ctx = structlog.contextvars.get_contextvars() or {}
        captured.clear()
        captured.update(ctx)
        return dict(ctx)

    # Simulate a request context: bind a trace_id and request_id, then
    # enqueue. The CorrelatedTask.apply_async should ship them via
    # headers; the global task_prerun handler should rebind them in
    # the eager-mode "worker".
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        request_id="11111111-1111-1111-1111-111111111111",
        trace_id="11111111111111111111111111111111",
        user_id="user-abc",
    )
    try:
        capture_in_task.delay()
    finally:
        structlog.contextvars.clear_contextvars()

    # Value equality across the boundary — Q4 contract.
    assert captured.get("trace_id") == "11111111111111111111111111111111"
    assert captured.get("request_id") == "11111111-1111-1111-1111-111111111111"
    assert captured.get("user_id") == "user-abc"
    # And no stray trace_origin tag, because we *did* have an upstream.
    assert "trace_origin" not in captured


async def test_celery_task_without_upstream_gets_fresh_trace_id() -> None:
    """Beat-scheduled / CLI-invoked tasks have no upstream context.
    The prerun handler mints a fresh trace_id and tags
    trace_origin="task" so a log query can distinguish the two paths."""

    # Simulate a task object with empty headers (no upstream).
    class _FakeRequest:
        headers: dict[str, Any] = {}

    class _FakeTask:
        request = _FakeRequest()

    # Make sure no leftover context from prior tests.
    structlog.contextvars.clear_contextvars()
    _bind_task_context(task=_FakeTask())
    try:
        ctx = structlog.contextvars.get_contextvars()
        assert ctx.get("trace_origin") == "task"
        assert isinstance(ctx.get("trace_id"), str)
        assert _HEX32_RE.match(ctx["trace_id"])
        # No request_id when upstream is absent — that absence is the
        # signal an operator greps for.
        assert "request_id" not in ctx
    finally:
        _unbind_task_context(task=_FakeTask())


# ---------------------------------------------------------------------------
# (c) Auth-path binding
# ---------------------------------------------------------------------------


async def test_unauthenticated_request_does_not_bind_user_id() -> None:
    """A health-check (no auth dep) only binds request_id + trace_id."""
    app, captured = _build_capture_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        await ac.get("/__capture_ctx")

    assert "user_id" not in captured
    assert "request_id" in captured
    assert "trace_id" in captured


async def test_authenticated_dep_binds_user_id() -> None:
    """A route depending on a user-resolving fn binds user_id into
    contextvars so subsequent log lines carry it. We don't exercise
    the real JWT path here (that's covered by test_security.py); we
    exercise the *binding contract* introduced by CP1.2a."""
    captured: dict[str, Any] = {}

    async def fake_get_current_user() -> dict[str, str]:
        # Mirror security.get_current_user's binding behaviour.
        structlog.contextvars.bind_contextvars(user_id="auth-user-42")
        return {"id": "auth-user-42"}

    from fastapi import Depends

    router = APIRouter()

    @router.get("/__authed")
    async def authed_route(
        user: dict[str, str] = Depends(fake_get_current_user),
    ) -> dict[str, Any]:
        ctx = structlog.contextvars.get_contextvars() or {}
        captured.clear()
        captured.update(ctx)
        return {"ok": True}

    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    app.include_router(router)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/__authed")

    assert resp.status_code == 200
    assert captured.get("user_id") == "auth-user-42"
    assert "request_id" in captured
    assert "trace_id" in captured


# ---------------------------------------------------------------------------
# (d) Sentry compatibility
# ---------------------------------------------------------------------------


async def test_log_calls_during_request_carry_correlation_ids(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Log lines emitted mid-request carry request_id + trace_id in the
    JSON output. This is the *mechanism* the Sentry breadcrumb bridge
    consumes (sentry's structlog integration reads the same event dict),
    so verifying the structlog output verifies the Sentry path
    transitively without needing a live Sentry SDK in the test env.

    The Sentry _REDACT_USER_KEYS audit (CP1.2d) confirmed the redaction
    surface stays correct: structlog only binds ID-shaped fields
    (request_id, trace_id, user_id, agent_id), none of which match the
    redacted PII allowlist (email, username, ip_address, full_name)."""
    from app.core.logging import configure_logging

    configure_logging(level="INFO")
    log = structlog.get_logger("d19-cp1-test")

    captured: dict[str, Any] = {}

    router = APIRouter()

    @router.get("/__emit")
    async def emit_route() -> dict[str, Any]:
        log.warning("d19_cp1.test_emit", extra_field="visible")
        ctx = structlog.contextvars.get_contextvars() or {}
        captured.clear()
        captured.update(ctx)
        return {"ok": True}

    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    app.include_router(router)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        await ac.get("/__emit")

    out = capsys.readouterr().out
    # The warning line should include both correlation IDs.
    assert "d19_cp1.test_emit" in out
    assert captured["request_id"] in out
    assert captured["trace_id"] in out
    # No PII allowlist field should appear — CP1 doesn't bind any of
    # them, but the assertion documents the contract for future
    # binders.
    for redacted_key in ("email", "username", "ip_address", "full_name"):
        assert f'"{redacted_key}":' not in out, (
            f"PII field '{redacted_key}' leaked into structlog output"
        )
