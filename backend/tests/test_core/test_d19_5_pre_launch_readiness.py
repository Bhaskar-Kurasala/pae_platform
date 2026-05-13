"""D19.5 — pre-launch readiness smoke suite.

8 functional-shape tests verifying the D19.1+D19.2+D19.3 substrate
works end-to-end in the canonical environment. Gate-keeping
deliverable, not authoring — every test exercises a load-bearing
path the cohort-1 launch depends on.

Per D-A: D19.5 is verification-only. These tests don't introduce
new substrate; they assert against existing substrate. If any
test fails, the failure is a launch-blocker (a real substrate
regression OR a real gap), not a test bug.

Per D-B: staging-equivalent = canonical Linux/Docker environment
(playwright-runner image + docker-compose.playwright.yml overlay).
The same path D19.1 CP5 + D19.2 + D19.3 closure verification used.
Production-identical staging (Fly + Honeycomb + DNS + Stripe test
mode) is deferred to launch-day work.
"""

from __future__ import annotations

import base64
import json
import re
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
import structlog
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


_REPO_ROOT = Path(__file__).resolve().parents[3]
_FOLLOWUPS_DIR = _REPO_ROOT / "docs" / "followups"


# ---------------------------------------------------------------------------
# (a) /health endpoint returns 200
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d19_5_health_endpoint_returns_200() -> None:
    """The UptimeRobot monitor (D19.2 Alert 2) hits /health every 5
    minutes. If this contract drifts, the uptime alert silently fires
    forever or never fires correctly. Load-bearing for the alert
    pipeline.
    """
    from app.api.v1.routes.health import router as health_router

    app = FastAPI()
    app.include_router(health_router)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/health")
    assert resp.status_code == 200, (
        f"D19.2 Alert 2 (uptime) depends on /health → 200; "
        f"got {resp.status_code}"
    )
    body = resp.json()
    assert body.get("status") == "ok", (
        f"/health body shape contract: status='ok'; got {body!r}"
    )
    # version field is part of the health response contract (per
    # backend/app/api/v1/routes/health.py HealthResponse model).
    assert "version" in body, (
        f"/health body shape contract: includes 'version' field; "
        f"got {body!r}"
    )


# ---------------------------------------------------------------------------
# (b) /metrics endpoint returns 200 with auth, 401/503 without
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d19_5_metrics_endpoint_requires_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The /metrics endpoint scrapes 15 canonical D19.1 CP2 metrics
    and must be auth-gated (an unauth'd /metrics is a non-trivial
    information disclosure surface). Verifies fail-closed default +
    basic-auth gating + exposition-format response.
    """
    from app.api.v1.routes.metrics import router as metrics_router

    app = FastAPI()
    app.include_router(metrics_router)

    # Fail-closed: env unset → 503 (D19.1 CP2 contract).
    monkeypatch.delenv("METRICS_USERNAME", raising=False)
    monkeypatch.delenv("METRICS_PASSWORD", raising=False)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/metrics")
    assert resp.status_code == 503, (
        f"D19.1 CP2 fail-closed: /metrics with no env → 503; "
        f"got {resp.status_code} — this is a SECURITY regression"
    )

    # With creds configured: no auth header → 401 + WWW-Authenticate.
    monkeypatch.setenv("METRICS_USERNAME", "scrape")
    monkeypatch.setenv("METRICS_PASSWORD", "secret")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/metrics")
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate", "").lower().startswith("basic")

    # With valid auth → 200 + prometheus exposition + canonical metrics.
    raw = base64.b64encode(b"scrape:secret").decode()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get(
            "/metrics", headers={"Authorization": f"Basic {raw}"}
        )
    assert resp.status_code == 200
    body = resp.text
    # Spot-check 4 of the 15 D-D canonical metrics across pillars.
    for metric in (
        "aicareeros_api_requests",
        "aicareeros_agent_invocations",
        "aicareeros_agent_cost_inr",
        "aicareeros_auth_events",
    ):
        assert metric in body, (
            f"D19.1 CP2 canonical metric {metric!r} missing from "
            f"/metrics exposition — substrate regression"
        )
    assert "# HELP" in body
    assert "# TYPE" in body


# ---------------------------------------------------------------------------
# (c) Per-student cost ceiling blocks at-or-above threshold
# (d) Per-student cost ceiling allows below threshold
# ---------------------------------------------------------------------------


def _make_entitlement_ctx(
    user_id: uuid.UUID, *, cost_remaining: Decimal, cost_used: Decimal
) -> Any:
    """Helper: build an EntitlementContext with the cost-budget
    fields populated to drive the orchestrator's ceiling check
    deterministically. Avoids hitting the matview by passing the
    pre-computed context."""
    from datetime import UTC, datetime

    from app.schemas.entitlement import (
        ActiveEntitlement,
        EntitlementContext,
        RateLimitState,
    )

    return EntitlementContext(
        user_id=user_id,
        active_entitlements=[
            ActiveEntitlement(
                entitlement_id=uuid.uuid4(),
                user_id=user_id,
                course_id=uuid.uuid4(),
                course_slug="d19-5-smoke",
                source="purchase",
                granted_at=datetime.now(UTC),
                expires_at=None,
                tier="standard",
                metadata={},
            )
        ],
        free_tier=None,
        effective_tier="standard",
        cost_budget_remaining_today_inr=cost_remaining,
        cost_budget_used_today_inr=cost_used,
        rate_limit_state=RateLimitState(
            burst_remaining=10,
            burst_window_resets_at=datetime.now(UTC),
            hourly_remaining=100,
            hourly_window_resets_at=datetime.now(UTC),
        ),
    )


@pytest.mark.asyncio
async def test_d19_5_per_student_ceiling_blocks_at_threshold() -> None:
    """D19.2 D-B: at/over daily cost ceiling, the orchestrator
    short-circuits with graceful-degradation BEFORE dispatching to
    the supervisor (no LLM cost spent on a user who's already over).
    Load-bearing for runway-protection at cohort-1.
    """
    from app.services.agentic_orchestrator import (
        AgenticOrchestratorService,
        OrchestratorResult,
    )

    user_id = uuid.uuid4()
    ctx = _make_entitlement_ctx(
        user_id, cost_remaining=Decimal("0"), cost_used=Decimal("100")
    )

    svc = AgenticOrchestratorService(supervisor=AsyncMock())
    svc._record_ceiling_hit = AsyncMock()  # type: ignore[method-assign]

    result = await svc.process_request(
        db=AsyncMock(),
        student_id=user_id,
        actor_id=user_id,
        actor_role="student",
        user_message="hi",
        attachments=None,
        conversation_id=None,
        entitlement_ctx=ctx,
    )
    assert isinstance(result, OrchestratorResult)
    assert result.blocked is True, (
        "D19.2 D-B regression: ceiling at threshold did NOT block"
    )
    assert result.block_reason == "daily_cost_ceiling_hit"
    # The user-facing message is the calm canonical D-B wording.
    assert "today's usage limit" in result.response_text.lower()
    # Cohort-event recording was triggered (best-effort path).
    svc._record_ceiling_hit.assert_awaited_once()
    # No agent was invoked.
    assert result.target_agent is None
    assert result.cost_inr == Decimal("0")


@pytest.mark.asyncio
async def test_d19_5_per_student_ceiling_allows_below_threshold() -> None:
    """When cost_remaining > 0, the orchestrator proceeds past the
    ceiling check to the safety scan + supervisor dispatch path. Per
    D-A constraint (cost ~₹0 for D19.5), we don't actually invoke an
    agent — we mock the safety gate to block on a sentinel verdict,
    which produces a deterministic non-ceiling-hit OrchestratorResult.
    """
    from app.schemas.safety import SafetyVerdict
    from app.services.agentic_orchestrator import (
        AgenticOrchestratorService,
        OrchestratorResult,
    )

    user_id = uuid.uuid4()
    ctx = _make_entitlement_ctx(
        user_id, cost_remaining=Decimal("100"), cost_used=Decimal("0")
    )

    # Mock the safety gate to block on a known sentinel — this proves
    # the orchestrator advanced PAST the ceiling check (otherwise the
    # block_reason would be daily_cost_ceiling_hit, not safety_input).
    mock_gate = AsyncMock()
    mock_gate.scan_input = AsyncMock(
        return_value=SafetyVerdict(
            decision="block",
            findings=[],
            severity_max="high",
            scan_duration_ms=1,
            user_facing_message="(test sentinel — safety block)",
        )
    )

    svc = AgenticOrchestratorService(
        supervisor=AsyncMock(), safety_gate=mock_gate
    )
    svc._record_ceiling_hit = AsyncMock()  # type: ignore[method-assign]

    result = await svc.process_request(
        db=AsyncMock(),
        student_id=user_id,
        actor_id=user_id,
        actor_role="student",
        user_message="hi",
        attachments=None,
        conversation_id=None,
        entitlement_ctx=ctx,
    )
    assert isinstance(result, OrchestratorResult)
    # Block reason is the safety sentinel, NOT the ceiling. Proves
    # the orchestrator advanced past the ceiling check.
    assert result.block_reason != "daily_cost_ceiling_hit", (
        "D19.2 regression: ceiling check fired when remaining > 0"
    )
    # Ceiling-hit cohort event was NOT recorded.
    svc._record_ceiling_hit.assert_not_awaited()


# ---------------------------------------------------------------------------
# (e) Graceful-failure envelope shape on agent / route error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d19_5_graceful_failure_envelope_shape_on_error() -> None:
    """D19.2 D-C: every unhandled error returns the canonical
    envelope { user_message, trace_id, request_id }. Frontend's
    GracefulFailureMessage component reads this shape; drift means
    every agent-invocation failure surface displays a broken UX.
    """
    from app.core.exception_handler import unhandled_exception_handler
    from app.core.request_id import RequestIDMiddleware

    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    @app.get("/d19_5_force_boom")
    async def boom() -> dict[str, str]:
        raise RuntimeError("d19.5 smoke — simulated agent failure")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/d19_5_force_boom")
    assert resp.status_code == 500
    body = resp.json()
    err = body["error"]
    # D-C wording: canonical "try again" user_message — frontend
    # GracefulFailureMessage renders this verbatim.
    assert "user_message" in err, (
        "D-C envelope regression: missing user_message field"
    )
    assert "try again" in err["user_message"].lower()
    # trace_id present and W3C 32-hex.
    assert "trace_id" in err, (
        "D19.2 CP1.5 regression: trace_id missing from envelope"
    )
    assert isinstance(err["trace_id"], str) and len(err["trace_id"]) == 32
    # request_id preserved for backwards compatibility.
    assert "request_id" in err
    # No internals leaked.
    assert "RuntimeError" not in resp.text
    assert "simulated agent failure" not in resp.text
    assert "Traceback" not in resp.text


# ---------------------------------------------------------------------------
# (f) Sentry / correlation-ID flow during a logged error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d19_5_correlation_ids_flow_to_log_context_mid_request() -> None:
    """D19.2 D-C + D19.1 CP1: when an error is logged mid-request, the
    structlog event_dict carries request_id + trace_id (Sentry's
    breadcrumb bridge reads these on its way to the Sentry vault).

    We verify the structlog substrate (not Sentry SDK directly, since
    Sentry is no-op without DSN in CI). The structlog → Sentry bridge
    is a wire-format adapter; verifying structlog carries the IDs
    verifies Sentry receives them too.
    """
    from app.core.request_id import RequestIDMiddleware

    captured: dict[str, Any] = {}

    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    log = structlog.get_logger("d19-5-smoke")

    @app.get("/d19_5_emit")
    async def emit() -> dict[str, Any]:
        log.warning("d19_5.simulated_error")
        ctx = structlog.contextvars.get_contextvars() or {}
        captured.clear()
        captured.update(ctx)
        return {"ok": True}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/d19_5_emit")
    assert resp.status_code == 200

    # Correlation IDs bound to contextvars during the request.
    assert "request_id" in captured, (
        "D19.1 CP1 regression: request_id not bound to contextvars"
    )
    assert "trace_id" in captured, (
        "D19.1 CP1 regression: trace_id not bound to contextvars"
    )
    assert len(captured["trace_id"]) == 32  # W3C 32-hex
    # These are exactly the keys Sentry's structlog integration picks up
    # for breadcrumb tagging — verified at D19.1 CP1.6.d.


# ---------------------------------------------------------------------------
# (g) Cost dashboard JSON validates (non-regression of D19.3 schema)
# ---------------------------------------------------------------------------


def test_d19_5_cost_dashboard_json_validates() -> None:
    """D19.3 CP1.2: cost.json schema extended with placeholder + db_query
    panel types. Non-regression check — re-asserts the dashboard parses,
    has the canonical fields, and includes the founder-glance panels.

    The full discipline pass lives in test_d19_cp4_dashboards.py; this
    is the D19.5 explicit-named-as-launch-readiness gate.
    """
    # Bind path through the same lookup helper test_d19_cp4_dashboards uses,
    # so this test runs whether the runner has /docs bind-mounted or the
    # repo-root resolution is used.
    candidates = [
        Path("/docs/operations/dashboards/cost.json"),
        _REPO_ROOT / "docs" / "operations" / "dashboards" / "cost.json",
    ]
    cost_path = next((c for c in candidates if c.exists()), None)
    assert cost_path is not None, (
        f"cost.json not found in any of: {candidates}"
    )
    data = json.loads(cost_path.read_text(encoding="utf-8"))
    assert data["id"] == "cost"
    assert data["owner"], "D-F: cost dashboard must have an owner"
    panels = data["panels"]
    panel_ids = [p["id"] for p in panels]

    # The 3 D19.3 founder-glance panels MUST be present (load-bearing
    # for the daily founder review ritual).
    for required_id in (
        "todays-burn-vs-expected",
        "students-near-or-at-ceiling",
        "ceiling-hits-today",
    ):
        assert required_id in panel_ids, (
            f"D19.3 founder-glance panel {required_id!r} missing from cost.json"
        )

    # The cohort-attribution placeholder MUST be present (deferral
    # documented in-dashboard per D-B).
    placeholders = [p for p in panels if p.get("panel_type") == "placeholder"]
    assert placeholders, (
        "D19.3 D-B regression: per-cohort-attribution-placeholder panel missing"
    )
    assert any("placeholder_reason" in p for p in placeholders), (
        "Placeholder panels must carry placeholder_reason"
    )


# ---------------------------------------------------------------------------
# (h) Two follow-up docs exist with concrete triggers
# ---------------------------------------------------------------------------


def _load_followup(name: str) -> str:
    """Locate a follow-up doc under the bind-mount or repo-root path."""
    candidates = [
        Path("/docs/followups") / name,
        _FOLLOWUPS_DIR / name,
    ]
    for c in candidates:
        if c.exists():
            return c.read_text(encoding="utf-8")
    raise AssertionError(
        f"follow-up doc {name!r} not found in any of: {candidates}"
    )


def test_d19_5_provider_attribution_followup_exists_with_triggers() -> None:
    """D19.3 CP1.3 registered this with 3 concrete triggers. The
    discipline of 'concrete triggers, not vague future work' is
    load-bearing for the architect's next-pass criteria."""
    text = _load_followup("provider-level-cost-attribution-via-gen-ai-otel.md")
    assert "Re-evaluation trigger" in text or "trigger" in text.lower()
    # Three concrete trigger conditions per D19.3 CP1.3.
    triggers = re.findall(r"^\s*\d+\.\s+\*\*", text, flags=re.MULTILINE)
    assert len(triggers) >= 3, (
        f"D19.3 CP1.3 contract: ≥3 concrete triggers; found {len(triggers)}"
    )


def test_d19_5_cohort_membership_followup_exists_with_triggers() -> None:
    """D19.3 CP1.4 registered this with 3 concrete triggers + 3
    options. Architecturally important: the deferral is what makes
    the eventual decision empirically-informed rather than
    speculative."""
    text = _load_followup("cohort-membership-modeling.md")
    assert "Re-evaluation trigger" in text or "trigger" in text.lower()
    triggers = re.findall(r"^\s*\d+\.\s+\*\*", text, flags=re.MULTILINE)
    assert len(triggers) >= 3, (
        f"D19.3 CP1.4 contract: ≥3 concrete triggers; found {len(triggers)}"
    )
    # The three options (FK / derived view / level_slug proxy) named
    # explicitly so future-architect knows the decision surface.
    assert "Option (a)" in text
    assert "Option (b)" in text
    assert "Option (c)" in text
