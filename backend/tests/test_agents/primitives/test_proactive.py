"""Proactive triggers — beat registry, webhook routing, sig verify,
idempotency.

The webhook signature tests are pure — no DB. The dispatch +
idempotency tests use the per-test schema fixture; they create the
`agent_proactive_runs` and `agent_call_chain` tables on demand.

Mock agentic agents (registered via `register_agentic`) stand in for
AgenticBaseAgent (D7). Each test that touches dispatch wires its
own mock.
"""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.primitives import (
    AgentCallResult,
    CallChain,
    WebhookSignatureError,
    clear_agentic_registry,
    clear_proactive_registry,
    cron_idempotency_key,
    dispatch_proactive_run,
    list_schedules,
    list_subscriptions,
    on_event,
    proactive,
    register_agentic,
    register_proactive_schedules,
    route_webhook,
    verify_github_signature,
    verify_stripe_signature,
    webhook_idempotency_key,
)


pytestmark = pytest.mark.asyncio


# ── Fixtures ────────────────────────────────────────────────────────


@pytest_asyncio.fixture(autouse=True)
async def _reset_registries(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[None, None]:
    """Each test starts with empty agentic + proactive registries.

    Webhook secrets default to fixed test values so tests don't have
    to set them per-case. Tests that want a missing-secret path
    monkeypatch them back to "".
    """
    clear_agentic_registry()
    clear_proactive_registry()
    monkeypatch.setattr(
        "app.core.config.settings.github_webhook_secret",
        "test-github-secret",
        raising=False,
    )
    monkeypatch.setattr(
        "app.core.config.settings.stripe_webhook_secret",
        "test-stripe-secret",
        raising=False,
    )
    yield
    clear_agentic_registry()
    clear_proactive_registry()


@pytest_asyncio.fixture
async def proactive_tables(pg_session: AsyncSession) -> AsyncSession:
    """Create the tables proactive dispatch writes to + the call-chain
    table call_agent uses on the same per-test schema."""
    await pg_session.execute(
        sql_text(
            """
            CREATE TABLE IF NOT EXISTS agent_proactive_runs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                agent_name TEXT NOT NULL,
                trigger_source TEXT NOT NULL,
                trigger_key TEXT NOT NULL,
                user_id UUID,
                payload JSONB,
                status TEXT NOT NULL,
                error_message TEXT,
                duration_ms INT,
                idempotency_key TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT agent_proactive_runs_status_chk CHECK (
                    status IN ('queued','ok','error','skipped')
                )
            )
            """
        )
    )
    await pg_session.execute(
        sql_text(
            "CREATE UNIQUE INDEX IF NOT EXISTS agent_proactive_runs_idemp_uidx "
            "ON agent_proactive_runs (idempotency_key) "
            "WHERE idempotency_key IS NOT NULL"
        )
    )
    await pg_session.execute(
        sql_text(
            """
            CREATE TABLE IF NOT EXISTS agent_call_chain (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                root_id UUID NOT NULL,
                parent_id UUID,
                caller_agent TEXT,
                callee_agent TEXT NOT NULL,
                depth INT NOT NULL DEFAULT 0,
                payload JSONB,
                result JSONB,
                status TEXT NOT NULL,
                user_id UUID,
                duration_ms INT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT agent_call_chain_status_chk CHECK (
                    status IN ('ok','error','cycle','depth_exceeded')
                ),
                CONSTRAINT agent_call_chain_depth_nonneg CHECK (depth >= 0)
            )
            """
        )
    )
    await pg_session.commit()
    return pg_session


# ── Mock agentic callee ─────────────────────────────────────────────


@dataclass
class _MockCallee:
    """Same shape as the AgenticCallee protocol — registered via
    register_agentic so call_agent can dispatch to it."""

    name: str
    output: dict[str, Any]
    allowed_callers: tuple[str, ...] = ()
    allowed_callees: tuple[str, ...] = ()
    invocations: list[Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.invocations = []

    async def run_agentic(self, payload: Any, chain: CallChain) -> AgentCallResult:
        self.invocations.append(payload)
        return AgentCallResult(
            callee=self.name,
            output=self.output,
            status="ok",
            duration_ms=0,
        )


# ── Signature verification: GitHub ─────────────────────────────────


def _gh_sig(secret: str, body: bytes) -> str:
    """Helper — produce the value of an X-Hub-Signature-256 header."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def test_github_signature_valid_passes() -> None:
    body = b'{"action":"push"}'
    sig = _gh_sig("test-github-secret", body)
    # Should not raise.
    verify_github_signature(body=body, signature_header=sig)


async def test_github_signature_wrong_secret_raises() -> None:
    body = b'{"action":"push"}'
    sig = _gh_sig("not-the-real-secret", body)
    with pytest.raises(WebhookSignatureError, match="signature mismatch"):
        verify_github_signature(body=body, signature_header=sig)


async def test_github_signature_missing_header_raises() -> None:
    with pytest.raises(WebhookSignatureError, match="missing or malformed"):
        verify_github_signature(body=b"x", signature_header="")


async def test_github_signature_unsigned_request_raises_when_secret_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty secret env config must REJECT every request, not allow
    them. The alternative (silently skip when unconfigured) is the
    behaviour the legacy webhook code shipped — and it's the trap
    the new primitive deliberately doesn't fall into."""
    monkeypatch.setattr(
        "app.core.config.settings.github_webhook_secret", "", raising=False
    )
    body = b'{"x":1}'
    with pytest.raises(WebhookSignatureError, match="not configured"):
        verify_github_signature(body=body, signature_header=_gh_sig("anything", body))


async def test_github_signature_tampered_body_raises() -> None:
    """A man-in-the-middle that flips a byte must trip the check."""
    body = b'{"clean":"true"}'
    sig = _gh_sig("test-github-secret", body)
    tampered = b'{"clean":"FALSE"}'
    with pytest.raises(WebhookSignatureError):
        verify_github_signature(body=tampered, signature_header=sig)


# ── Signature verification: Stripe ─────────────────────────────────


def _stripe_sig(secret: str, body: bytes, ts: int) -> str:
    payload = f"{ts}.{body.decode()}"
    digest = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


async def test_stripe_signature_valid_passes() -> None:
    body = b'{"id":"evt_1"}'
    ts = int(time.time())
    sig = _stripe_sig("test-stripe-secret", body, ts)
    verify_stripe_signature(body=body, signature_header=sig, now_unix=float(ts))


async def test_stripe_signature_outside_tolerance_raises() -> None:
    body = b'{"id":"evt_1"}'
    ts = int(time.time())
    sig = _stripe_sig("test-stripe-secret", body, ts)
    with pytest.raises(WebhookSignatureError, match="tolerance"):
        verify_stripe_signature(
            body=body,
            signature_header=sig,
            tolerance_seconds=60,
            now_unix=float(ts + 3600),  # an hour later
        )


async def test_stripe_signature_malformed_header_raises() -> None:
    with pytest.raises(WebhookSignatureError, match="malformed"):
        verify_stripe_signature(body=b"x", signature_header="garbage")


async def test_stripe_signature_missing_secret_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.core.config.settings.stripe_webhook_secret", "", raising=False
    )
    body = b"x"
    with pytest.raises(WebhookSignatureError, match="not configured"):
        verify_stripe_signature(
            body=body,
            signature_header=_stripe_sig("anything", body, int(time.time())),
        )


# ── Idempotency key construction ────────────────────────────────────


async def test_cron_idempotency_key_is_minute_bucketed() -> None:
    """Same minute → same key. Different minute → different key."""
    from datetime import datetime, UTC

    when_a = datetime(2026, 5, 2, 9, 0, 30, tzinfo=UTC)
    when_b = datetime(2026, 5, 2, 9, 0, 59, tzinfo=UTC)
    when_c = datetime(2026, 5, 2, 9, 1, 0, tzinfo=UTC)

    a = cron_idempotency_key("watchdog", "0 9 * * *", scheduled_for=when_a)
    b = cron_idempotency_key("watchdog", "0 9 * * *", scheduled_for=when_b)
    c = cron_idempotency_key("watchdog", "0 9 * * *", scheduled_for=when_c)
    assert a == b
    assert a != c


async def test_cron_idempotency_key_includes_user_when_per_user() -> None:
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    base = cron_idempotency_key("coach", "0 9 * * *")
    a = cron_idempotency_key("coach", "0 9 * * *", user_id=user_a)
    b = cron_idempotency_key("coach", "0 9 * * *", user_id=user_b)
    # Per-user keys differ between users and from the base key.
    assert a != b
    assert a != base


async def test_webhook_idempotency_key_includes_agent() -> None:
    """Same delivery_id but different agents → different keys, so
    fan-out webhooks each land their own audit row."""
    a = webhook_idempotency_key(
        source="github", delivery_id="abc", agent_name="agent_x"
    )
    b = webhook_idempotency_key(
        source="github", delivery_id="abc", agent_name="agent_y"
    )
    assert a != b


# ── dispatch_proactive_run ──────────────────────────────────────────


async def test_dispatch_writes_audit_row_and_invokes_agent(
    proactive_tables: AsyncSession,
) -> None:
    callee = _MockCallee(name="watchdog", output={"hello": "world"})
    register_agentic(callee)

    result = await dispatch_proactive_run(
        session=proactive_tables,
        agent_name="watchdog",
        trigger_source="cron",
        trigger_key="0 9 * * *",
        idempotency_key="cron:watchdog:0 9 * * *:20260502T0900",
        payload={"why": "test"},
    )
    assert result.deduped is False
    assert result.status == "ok"
    assert callee.invocations == [{"why": "test"}]

    raw = await proactive_tables.execute(
        sql_text(
            "SELECT agent_name, status, idempotency_key, payload "
            "FROM agent_proactive_runs"
        )
    )
    rows = raw.all()
    assert len(rows) == 1
    assert rows[0][0] == "watchdog"
    assert rows[0][1] == "ok"


async def test_dispatch_records_error_when_agent_unregistered(
    proactive_tables: AsyncSession,
) -> None:
    """If the named agent isn't registered, dispatch still writes
    the audit row with status='error' and surfaces the failure to
    the caller — proactive runs never raise."""
    result = await dispatch_proactive_run(
        session=proactive_tables,
        agent_name="phantom_agent",
        trigger_source="cron",
        trigger_key="@daily",
        idempotency_key="cron:phantom:@daily:20260502T0900",
        payload={},
    )
    assert result.status == "error"
    assert "phantom_agent" in (result.error or "").lower() or \
           "agentnotfound" in (result.error or "").lower()
    raw = await proactive_tables.execute(
        sql_text("SELECT status FROM agent_proactive_runs")
    )
    assert raw.scalar_one() == "error"


# ── Idempotency: duplicate delivery → ONE audit row ────────────────


async def test_duplicate_idempotency_key_dedupes_to_single_row(
    proactive_tables: AsyncSession,
) -> None:
    """The directive: a duplicate webhook delivery results in
    exactly one agent_proactive_runs row. The DB partial unique
    index does the work; the application catches IntegrityError
    and returns the existing row's id with deduped=True."""
    callee = _MockCallee(name="content_ingest", output={"ok": True})
    register_agentic(callee)

    key = "webhook:github:abc-123:content_ingest"
    payload = {"event": "push", "sha": "deadbeef"}

    first = await dispatch_proactive_run(
        session=proactive_tables,
        agent_name="content_ingest",
        trigger_source="webhook:github",
        trigger_key="github.push",
        idempotency_key=key,
        payload=payload,
    )
    second = await dispatch_proactive_run(
        session=proactive_tables,
        agent_name="content_ingest",
        trigger_source="webhook:github",
        trigger_key="github.push",
        idempotency_key=key,
        payload=payload,
    )
    assert first.deduped is False
    assert second.deduped is True
    assert second.audit_id == first.audit_id

    raw = await proactive_tables.execute(
        sql_text("SELECT count(*) FROM agent_proactive_runs")
    )
    assert raw.scalar_one() == 1
    # And the agent must have been invoked exactly once (not on the
    # dedup path).
    assert len(callee.invocations) == 1


# ── Webhook routing fan-out ─────────────────────────────────────────


async def test_route_webhook_dispatches_to_subscribed_agents(
    proactive_tables: AsyncSession,
) -> None:
    """Two agents subscribe to github.push; one webhook → two audit
    rows + two agent invocations, each with its own idempotency key."""
    a = _MockCallee(name="agent_a", output={})
    b = _MockCallee(name="agent_b", output={})
    register_agentic(a)
    register_agentic(b)

    @on_event("github.push", agent_name="agent_a")
    class _A:
        pass

    @on_event("github.push", agent_name="agent_b")
    class _B:
        pass

    results = await route_webhook(
        session=proactive_tables,
        source="github",
        event_name="github.push",
        delivery_id="evt-001",
        payload={"repo": "x"},
    )
    assert len(results) == 2
    assert all(r.status == "ok" for r in results)

    raw = await proactive_tables.execute(
        sql_text(
            "SELECT agent_name, idempotency_key FROM agent_proactive_runs "
            "ORDER BY agent_name"
        )
    )
    rows = raw.all()
    # One audit row per agent with distinct idempotency keys.
    assert {r[0] for r in rows} == {"agent_a", "agent_b"}
    assert len({r[1] for r in rows}) == 2


async def test_route_webhook_unrouted_event_returns_empty(
    proactive_tables: AsyncSession,
) -> None:
    """Event with zero subscribers → empty result list, no audit
    rows, no agent invocations. Logged as `proactive.webhook.unrouted`."""
    results = await route_webhook(
        session=proactive_tables,
        source="github",
        event_name="github.never_subscribed",
        delivery_id="evt-x",
        payload={},
    )
    assert results == []
    raw = await proactive_tables.execute(
        sql_text("SELECT count(*) FROM agent_proactive_runs")
    )
    assert raw.scalar_one() == 0


async def test_duplicate_webhook_delivery_dedupes_per_agent(
    proactive_tables: AsyncSession,
) -> None:
    """Re-firing the same webhook (same delivery_id) collapses to
    one row per subscribed agent. The directive: 'duplicate webhook
    delivery results in exactly one agent_proactive_runs row.'
    With two subscribed agents we get two rows total — one per
    agent — but the second delivery adds zero new rows."""
    a = _MockCallee(name="agent_a", output={})
    b = _MockCallee(name="agent_b", output={})
    register_agentic(a)
    register_agentic(b)

    @on_event("github.push", agent_name="agent_a")
    class _A:
        pass

    @on_event("github.push", agent_name="agent_b")
    class _B:
        pass

    # First delivery.
    first = await route_webhook(
        session=proactive_tables,
        source="github",
        event_name="github.push",
        delivery_id="evt-redelivered",
        payload={"sha": "abc"},
    )
    assert all(not r.deduped for r in first)

    # Second delivery, same id → all dedupe.
    second = await route_webhook(
        session=proactive_tables,
        source="github",
        event_name="github.push",
        delivery_id="evt-redelivered",
        payload={"sha": "abc"},
    )
    assert all(r.deduped for r in second)

    raw = await proactive_tables.execute(
        sql_text("SELECT count(*) FROM agent_proactive_runs")
    )
    assert raw.scalar_one() == 2  # two subscribed agents, one row each
    # Each agent invoked exactly once across the two deliveries.
    assert len(a.invocations) == 1
    assert len(b.invocations) == 1


# ── Decorator registration ──────────────────────────────────────────


async def test_proactive_decorator_registers_schedule() -> None:
    """The decorator side-effect-appends to the module list. Reading
    `list_schedules()` after the decorator runs returns the entry."""

    @proactive(
        agent_name="learning_coach",
        cron="0 9 * * *",
        per_user=True,
        description="Daily check on student progress.",
    )
    class _Coach:
        pass

    schedules = list_schedules()
    assert len(schedules) == 1
    assert schedules[0].agent_name == "learning_coach"
    assert schedules[0].cron == "0 9 * * *"
    assert schedules[0].per_user is True


async def test_on_event_decorator_registers_subscription() -> None:
    @on_event(
        "github.push", "github.pull_request",
        agent_name="code_mentor",
    )
    class _Mentor:
        pass

    push_subs = list_subscriptions("github.push")
    pr_subs = list_subscriptions("github.pull_request")
    assert len(push_subs) == 1
    assert push_subs[0].agent_name == "code_mentor"
    assert len(pr_subs) == 1
    assert pr_subs[0].agent_name == "code_mentor"


async def test_clear_proactive_registry_empties_both() -> None:
    @proactive(agent_name="x", cron="* * * * *")
    class _X:
        pass

    @on_event("y", agent_name="x")
    class _Y:
        pass

    assert list_schedules() and list_subscriptions("y")
    clear_proactive_registry()
    assert list_schedules() == []
    assert list_subscriptions("y") == []


# ── Beat schedule registration ──────────────────────────────────────


async def test_register_proactive_schedules_merges_into_celery() -> None:
    """The directive: decorator-registered schedules MUST land in
    `celery_app.conf.beat_schedule` after `register_proactive_schedules`
    runs. Beat reads that dict at scheduler boot; anything we miss
    is invisible until restart."""

    @proactive(agent_name="watchdog", cron="0 9 * * *")
    class _W:
        pass

    @proactive(agent_name="reviewer", cron="*/15 * * * *")
    class _R:
        pass

    @dataclass
    class _FakeConf:
        beat_schedule: dict[str, Any] = None  # type: ignore[assignment]

    @dataclass
    class _FakeCelery:
        conf: _FakeConf

    fake_celery = _FakeCelery(conf=_FakeConf(beat_schedule={"existing_legacy": {}}))
    count = register_proactive_schedules(fake_celery)

    assert count == 2
    keys = set(fake_celery.conf.beat_schedule.keys())
    # Existing entries are preserved.
    assert "existing_legacy" in keys
    # Each registered schedule lands as `agentic:{agent}:{cron}`.
    assert any(k.startswith("agentic:watchdog:") for k in keys)
    assert any(k.startswith("agentic:reviewer:") for k in keys)


async def test_register_proactive_skips_invalid_cron() -> None:
    """Bad cron strings are logged + skipped — do NOT crash boot."""

    @proactive(agent_name="bad", cron="not a real cron")
    class _Bad:
        pass

    @dataclass
    class _FakeConf:
        beat_schedule: dict[str, Any] = None  # type: ignore[assignment]

    @dataclass
    class _FakeCelery:
        conf: _FakeConf

    fake_celery = _FakeCelery(conf=_FakeConf(beat_schedule={}))
    count = register_proactive_schedules(fake_celery)
    assert count == 0  # skipped, not raised
    assert fake_celery.conf.beat_schedule == {}
