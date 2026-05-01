"""Proactive triggers — Agentic OS Primitive 5.

Two ways an agentic agent fires *without* a chat turn:

  • @proactive(cron="0 9 * * *", per_user=True) — Celery beat
    schedules a periodic task that invokes the agent. Per-user
    iteration is handled by the runtime, so the agent author just
    declares the cron and writes a single-user run_proactive.

  • @on_event("github.push", "stripe.checkout.completed", ...) —
    incoming webhook is signature-verified, decoded, and routed
    to every agent that registered for the event name.

Both paths converge on `dispatch_proactive_run()` which:

  1. Builds a deterministic idempotency_key from the trigger
     source + provider-supplied id (Celery scheduled-for minute,
     GitHub X-GitHub-Delivery, Stripe event.id).
  2. Inserts an `agent_proactive_runs` audit row with that key.
     The partial unique index does the de-dup; on collision we
     log + return the existing row id without re-invoking the
     agent.
  3. Calls `call_agent` with a fresh `CallChain.start_root` so
     proactive runs are first-class in the call graph.
  4. Updates the audit row with status + duration.

Three principles, baked in (mirrored in conventions doc for D9):

  1. Webhook signature verification is non-negotiable. Every
     handler verifies before touching an agent.
  2. Idempotency keys are wired end-to-end. The DB column added in
     D1 stops being decoration; duplicate deliveries collapse to
     a single audit row.
  3. Beat ordering matters. Decorators register at import time;
     `register_proactive_schedules(celery_app)` merges them into
     `celery_app.conf.beat_schedule` and MUST be called before
     Celery beat constructs its scheduler. The intended call site
     is `app/core/celery_app.py` — see the registration comment
     there.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.primitives import metrics
from app.agents.primitives.communication import CallChain, call_agent
from app.core.config import settings
from app.models.agent_proactive_run import AgentProactiveRun

log = structlog.get_logger().bind(layer="proactive")


# ── Errors ──────────────────────────────────────────────────────────


class ProactiveError(RuntimeError):
    """Base class for proactive-trigger failures."""


class WebhookSignatureError(ProactiveError):
    """Raised when an incoming webhook fails HMAC verification.

    Routes that catch this map it to HTTP 401. Never log the
    request body when raising — the body content is what the
    attacker would be probing.
    """


class WebhookFormatError(ProactiveError):
    """Raised when a webhook payload is missing fields we need to
    build an idempotency key (delivery id, event id, etc.)."""


# ── Decorator-driven registries ─────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ProactiveSchedule:
    """One entry registered by @proactive.

    `agent_name` is the AgenticBaseAgent name we'll dispatch to
    (D7). `cron` is the standard Celery cron string ("M H D M W").
    `per_user` toggles whether the runtime fans out across active
    students (each gets its own audit row + agent invocation) or
    runs once per cron tick.
    """

    agent_name: str
    cron: str
    per_user: bool
    payload_factory: Callable[[uuid.UUID | None], dict[str, Any]] | None
    description: str


@dataclass(frozen=True, slots=True)
class WebhookSubscription:
    """One entry registered by @on_event."""

    agent_name: str
    event_name: str  # e.g. "github.push" | "stripe.checkout.session.completed"
    payload_factory: Callable[[dict[str, Any]], dict[str, Any]] | None


_proactive_schedules: list[ProactiveSchedule] = []
_event_subscriptions: dict[str, list[WebhookSubscription]] = {}


def proactive(
    *,
    agent_name: str,
    cron: str,
    per_user: bool = False,
    description: str = "",
    payload_factory: Callable[[uuid.UUID | None], dict[str, Any]] | None = None,
) -> Callable[[type], type]:
    """Decorator to register a Celery-beat-driven proactive schedule.

    Usage from inside an AgenticBaseAgent module (D7):

        @register_agentic
        @proactive(
            agent_name="engagement_watchdog",
            cron="0 9 * * *",
            per_user=True,
            description="Daily morning sweep for slipping students.",
        )
        class EngagementWatchdog(AgenticBaseAgent):
            ...

    The decorator returns the class unchanged — the side effect is
    appending a ProactiveSchedule to the module-level list. That
    list is read by `register_proactive_schedules(celery_app)`
    when Celery beat boots.

    Decorators run at agent module import time, so you MUST import
    the agent modules BEFORE constructing the beat scheduler. The
    intended call order is documented in `register_proactive_schedules`.
    """

    def decorator(cls: type) -> type:
        _proactive_schedules.append(
            ProactiveSchedule(
                agent_name=agent_name,
                cron=cron,
                per_user=per_user,
                payload_factory=payload_factory,
                description=description or cls.__doc__ or "",
            )
        )
        log.info(
            "proactive.schedule.registered",
            agent=agent_name,
            cron=cron,
            per_user=per_user,
        )
        return cls

    return decorator


def on_event(
    *event_names: str,
    agent_name: str,
    payload_factory: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> Callable[[type], type]:
    """Decorator to register a webhook-event subscription.

    Multiple events can be passed positionally; the agent receives
    each separately. Event names are dotted strings: "github.push",
    "stripe.checkout.session.completed", etc.

    `payload_factory` lets the registration step transform the raw
    webhook body into the shape the agent expects. Default: pass
    the body through unchanged.
    """

    def decorator(cls: type) -> type:
        for event in event_names:
            _event_subscriptions.setdefault(event, []).append(
                WebhookSubscription(
                    agent_name=agent_name,
                    event_name=event,
                    payload_factory=payload_factory,
                )
            )
            # NOTE: structlog uses the first positional as the
            # `event` key already, so we must NOT pass a kwarg named
            # `event` — it collides. Renamed to event_name for the
            # log line; the registered subscription still stores it
            # under `event_name` matching the dataclass field.
            log.info(
                "proactive.event.registered",
                agent=agent_name,
                event_name=event,
            )
        return cls

    return decorator


def list_schedules() -> list[ProactiveSchedule]:
    """Snapshot of registered cron schedules. Called by the Celery
    beat init helper."""
    return list(_proactive_schedules)


def list_subscriptions(event_name: str | None = None) -> list[WebhookSubscription]:
    """Snapshot of registered webhook subscriptions, optionally
    filtered to one event."""
    if event_name is None:
        return [s for subs in _event_subscriptions.values() for s in subs]
    return list(_event_subscriptions.get(event_name, []))


def clear_proactive_registry() -> None:
    """Test helper — clears both decorator-driven registries.

    Production never calls this. Tests use it between cases so
    decorator state doesn't leak across the suite.
    """
    _proactive_schedules.clear()
    _event_subscriptions.clear()


# ── Webhook signature verification ──────────────────────────────────
#
# These are deliberately separate from the ones in
# `app/api/v1/routes/webhooks.py` (which the legacy chat-stack
# stripe/github flows use). The legacy implementation reads
# settings.github_token (a PAT, not a webhook secret) — kept as-is
# to avoid breaking changes in D6. New code uses these helpers,
# which read the dedicated `github_webhook_secret` setting.


def verify_github_signature(*, body: bytes, signature_header: str) -> None:
    """Verify GitHub's X-Hub-Signature-256 header (HMAC-SHA256).

    Raises WebhookSignatureError on any failure. Uses
    `hmac.compare_digest` for constant-time comparison so an attacker
    cannot infer the secret via timing.

    The empty-secret case is treated as a hard reject: an environment
    that hasn't configured `github_webhook_secret` MUST NOT accept
    GitHub webhooks. The previous webhook handler chose the opposite
    (silently skip verification when the secret is empty); that
    pattern is unsafe for a primitive that lands new agent traffic.
    """
    secret = (settings.github_webhook_secret or "").strip()
    if not secret:
        raise WebhookSignatureError(
            "github_webhook_secret is not configured; "
            "GitHub webhooks are rejected"
        )
    if not signature_header or not signature_header.startswith("sha256="):
        raise WebhookSignatureError(
            "missing or malformed X-Hub-Signature-256 header"
        )
    expected = (
        "sha256="
        + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    )
    if not hmac.compare_digest(expected, signature_header):
        raise WebhookSignatureError("github webhook signature mismatch")


def verify_stripe_signature(
    *,
    body: bytes,
    signature_header: str,
    tolerance_seconds: int = 300,
    now_unix: float | None = None,
) -> None:
    """Verify Stripe's `Stripe-Signature` header.

    Header format: `t=<timestamp>,v1=<signature>[,v0=...]`.
    HMAC payload: `f"{timestamp}.{body}"`. Algorithm: SHA-256.

    Also enforces a `tolerance_seconds` replay window: a delivery
    older than that is rejected. Default 300s mirrors Stripe's docs.

    `now_unix` is injectable for deterministic tests.
    """
    secret = (settings.stripe_webhook_secret or "").strip()
    if not secret:
        raise WebhookSignatureError(
            "stripe_webhook_secret is not configured; "
            "Stripe webhooks are rejected"
        )
    if not signature_header:
        raise WebhookSignatureError("missing Stripe-Signature header")
    parts: dict[str, str] = {}
    for chunk in signature_header.split(","):
        if "=" in chunk:
            k, v = chunk.split("=", 1)
            parts[k.strip()] = v.strip()
    timestamp = parts.get("t", "")
    v1 = parts.get("v1", "")
    if not timestamp or not v1:
        raise WebhookSignatureError("malformed Stripe signature header")
    # Replay window.
    try:
        ts_int = int(timestamp)
    except ValueError as exc:
        raise WebhookSignatureError("Stripe timestamp not an int") from exc
    current = float(now_unix) if now_unix is not None else time.time()
    if abs(current - ts_int) > tolerance_seconds:
        raise WebhookSignatureError(
            f"stripe timestamp outside tolerance ({tolerance_seconds}s)"
        )
    payload = f"{timestamp}.{body.decode('utf-8', errors='replace')}"
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, v1):
        raise WebhookSignatureError("stripe signature mismatch")


# ── Idempotency key construction ────────────────────────────────────


def cron_idempotency_key(
    agent_name: str,
    cron: str,
    *,
    scheduled_for: datetime | None = None,
    user_id: uuid.UUID | None = None,
) -> str:
    """Deterministic key for a cron-fired proactive run.

    Format: `cron:{agent}:{cron_expr}:{minute_bucket}[:{user}]`
    where minute_bucket is the UTC minute floor of `scheduled_for`.
    A Celery retry after the same minute boundary collides with the
    original key and is rejected by the partial unique index — exactly
    the de-dup we want.
    """
    when = scheduled_for or datetime.now(UTC)
    bucket = when.strftime("%Y%m%dT%H%M")  # minute precision UTC
    base = f"cron:{agent_name}:{cron}:{bucket}"
    if user_id is not None:
        base = f"{base}:{user_id}"
    return base


def webhook_idempotency_key(
    *,
    source: Literal["github", "stripe", "custom"],
    delivery_id: str,
    agent_name: str,
) -> str:
    """Deterministic key for a webhook-fired proactive run.

    `delivery_id`:
      • GitHub: `X-GitHub-Delivery` header (UUID)
      • Stripe: `event.id` from the parsed payload
      • custom: caller-supplied opaque string

    The agent_name is included so two agents reacting to the same
    delivery each get their own audit row (one per (delivery, agent)
    pair). Without this, fan-out webhooks would share a key and only
    the first agent's run would land.
    """
    return f"webhook:{source}:{delivery_id}:{agent_name}"


# ── Dispatcher ──────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ProactiveDispatchResult:
    """What `dispatch_proactive_run` returns.

    `deduped=True` means the idempotency key collided — the run did
    NOT execute again; we returned the existing audit row's id.
    Use this to short-circuit any side effects in the caller.
    """

    audit_id: uuid.UUID
    deduped: bool
    status: str  # 'ok' | 'error' | 'skipped'
    error: str | None = None
    duration_ms: int = 0


async def dispatch_proactive_run(
    *,
    session: AsyncSession,
    agent_name: str,
    trigger_source: str,  # 'cron' | 'webhook:github' | 'webhook:stripe'
    trigger_key: str,     # cron expr or event name — stored verbatim
    idempotency_key: str,
    payload: dict[str, Any] | None = None,
    user_id: uuid.UUID | None = None,
) -> ProactiveDispatchResult:
    """Run an agent on behalf of a proactive trigger.

    Idempotency:
      • We INSERT an audit row with the provided `idempotency_key`.
      • The partial unique index on `agent_proactive_runs(idempotency_key)
        WHERE idempotency_key IS NOT NULL` makes a duplicate INSERT
        raise IntegrityError. We catch it, look up the existing row,
        and return `deduped=True` without re-invoking the agent.
      • Idempotency_key MUST be non-NULL for automated callers. NULL
        skips the unique guard — ad-hoc / one-off use only.

    Status transitions:
      • Initial INSERT writes status='queued'.
      • On successful agent run: UPDATE status='ok', duration_ms=…
      • On failure: UPDATE status='error', error_message=…

    `call_agent` is invoked with a fresh `CallChain.start_root` so
    proactive flows are first-class in the call graph.
    """
    # Step 1: INSERT ... ON CONFLICT DO NOTHING.
    #
    # Using `pg_insert(...).on_conflict_do_nothing(...)` lets us
    # detect a duplicate idempotency_key without raising an
    # IntegrityError — the alternative (catch + rollback) would
    # also discard whatever the surrounding test/transaction had
    # set on the connection (e.g. the per-test schema's
    # search_path), which breaks downstream operations.
    #
    # The `RETURNING id` clause yields the inserted row's id on
    # success, NULL on conflict. Combined with a follow-up SELECT,
    # we get the audit row's id either way in two SQL statements
    # without a transaction abort.
    new_id = uuid.uuid4()
    insert_stmt = (
        pg_insert(AgentProactiveRun)
        .values(
            id=new_id,
            agent_name=agent_name,
            trigger_source=trigger_source,
            trigger_key=trigger_key,
            user_id=user_id,
            payload=payload or {},
            status="queued",
            idempotency_key=idempotency_key,
        )
        # Partial unique index — must repeat the index's WHERE
        # predicate so Postgres can match the exact index. Without
        # `index_where`, asyncpg raises:
        #   "there is no unique or exclusion constraint matching the
        #    ON CONFLICT specification"
        # because a partial-unique index doesn't satisfy ON CONFLICT
        # (col) without the predicate.
        .on_conflict_do_nothing(
            index_elements=["idempotency_key"],
            index_where=AgentProactiveRun.idempotency_key.is_not(None),
        )
        .returning(AgentProactiveRun.id)
    )
    result = await session.execute(insert_stmt)
    inserted_id = result.scalar_one_or_none()

    if inserted_id is None:
        # Duplicate key — look up the existing row and return it.
        existing = await session.execute(
            select(AgentProactiveRun).where(
                AgentProactiveRun.idempotency_key == idempotency_key
            )
        )
        row = existing.scalar_one()
        log.info(
            "proactive.deduped",
            agent=agent_name,
            trigger_source=trigger_source,
            idempotency_key=idempotency_key,
            existing_id=str(row.id),
        )
        return ProactiveDispatchResult(
            audit_id=row.id,
            deduped=True,
            status=row.status,
        )

    audit_id = inserted_id

    # Step 2: invoke the agent. Fresh root chain — proactive runs
    # are first-class roots, not nested calls.
    start = time.monotonic()
    chain = CallChain.start_root(
        caller=f"proactive:{trigger_source}",
        user_id=user_id,
    )
    try:
        result = await call_agent(
            agent_name,
            payload=payload or {},
            session=session,
            chain=chain,
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        status = "ok" if result.status == "ok" else "error"
        error_message = (
            None if result.status == "ok"
            else (result.error or f"agent returned status={result.status}")
        )
    except Exception as exc:  # noqa: BLE001 - we want to record any failure
        duration_ms = int((time.monotonic() - start) * 1000)
        status = "error"
        error_message = f"{type(exc).__name__}: {exc}"
        log.warning(
            "proactive.dispatch.exception",
            agent=agent_name,
            trigger_source=trigger_source,
            error=error_message,
        )

    # Step 3: update audit row.
    await session.execute(
        update(AgentProactiveRun)
        .where(AgentProactiveRun.id == audit_id)
        .values(
            status=status,
            error_message=error_message,
            duration_ms=duration_ms,
        )
    )
    log.info(
        "proactive.dispatch.complete",
        agent=agent_name,
        trigger_source=trigger_source,
        status=status,
        duration_ms=duration_ms,
        audit_id=str(audit_id),
    )
    return ProactiveDispatchResult(
        audit_id=audit_id,
        deduped=False,
        status=status,
        error=error_message,
        duration_ms=duration_ms,
    )


# ── Webhook routing ─────────────────────────────────────────────────


async def route_webhook(
    *,
    session: AsyncSession,
    source: Literal["github", "stripe", "custom"],
    event_name: str,
    delivery_id: str,
    payload: dict[str, Any],
) -> list[ProactiveDispatchResult]:
    """Fan-out a verified webhook payload to every subscribed agent.

    Caller (the FastAPI route) MUST verify the signature before
    invoking this. Reaching this function with an unverified body
    is a security bug.

    Returns one ProactiveDispatchResult per subscribed agent. If
    no agent is subscribed for `event_name`, returns an empty list
    and logs `proactive.webhook.unrouted` so unhandled events surface
    in observability.
    """
    subs = list_subscriptions(event_name)
    if not subs:
        # Same structlog kwarg-collision avoidance as @on_event
        # registration: don't pass `event=...` because structlog
        # already uses that key for the message string.
        log.info(
            "proactive.webhook.unrouted",
            source=source,
            event_name=event_name,
            delivery_id=delivery_id,
        )
        return []

    results: list[ProactiveDispatchResult] = []
    for sub in subs:
        agent_payload = (
            sub.payload_factory(payload)
            if sub.payload_factory is not None
            else payload
        )
        idem_key = webhook_idempotency_key(
            source=source,
            delivery_id=delivery_id,
            agent_name=sub.agent_name,
        )
        result = await dispatch_proactive_run(
            session=session,
            agent_name=sub.agent_name,
            trigger_source=f"webhook:{source}",
            trigger_key=event_name,
            idempotency_key=idem_key,
            payload=agent_payload,
        )
        results.append(result)
    return results


# ── Celery beat registration ────────────────────────────────────────


# Standard Celery task name. Beat schedules constructed by
# `register_proactive_schedules` all point at this single task; the
# task body looks up the schedule by `agent_name` at runtime so
# we don't have to register one Celery task per agent.
PROACTIVE_TASK_NAME = "app.agents.primitives.proactive.run_proactive_task"


def register_proactive_schedules(
    celery_app: Any,
    *,
    schedules: Iterable[ProactiveSchedule] | None = None,
) -> int:
    """Merge decorator-registered cron schedules into Celery beat.

    Call sequence required:

        # 1. Import the agent modules so @proactive decorators run.
        from app.agents.primitives import ensure_tools_loaded
        from app.agents.registry import _ensure_registered  # legacy bridge
        ensure_tools_loaded()
        _ensure_registered()           # imports legacy + new agentic modules

        # 2. Now beat_schedule has the schedule names available.
        register_proactive_schedules(celery_app)

    Beat reads `celery_app.conf.beat_schedule` once at scheduler
    boot. Anything registered after that is invisible until the
    next beat restart. Intent is: build celery_app, import agent
    modules, call this — in that order — at module top of
    `app/core/celery_app.py`.

    Returns the number of schedules merged.
    """
    schedules_list = list(schedules) if schedules is not None else list_schedules()
    if not schedules_list:
        log.info("proactive.beat_register.empty")
        return 0

    from celery.schedules import crontab

    merged = dict(getattr(celery_app.conf, "beat_schedule", {}) or {})
    count = 0
    for sched in schedules_list:
        # Convert "M H D M W" → crontab(minute=, hour=, day_of_month=,
        # month_of_year=, day_of_week=). Accept '*' as the wildcard
        # passthrough.
        try:
            ct = _parse_cron(sched.cron)
        except ValueError as exc:
            log.warning(
                "proactive.beat_register.bad_cron",
                agent=sched.agent_name,
                cron=sched.cron,
                error=str(exc),
            )
            continue
        # The beat-schedule key needs to be unique across the app.
        # Prefix to avoid collisions with legacy schedules.
        key = f"agentic:{sched.agent_name}:{sched.cron.replace(' ', '_')}"
        merged[key] = {
            "task": PROACTIVE_TASK_NAME,
            "schedule": crontab(**ct),
            "args": (sched.agent_name, sched.cron, sched.per_user),
            "options": {"expires": 60 * 5},  # don't queue past 5min
        }
        count += 1
    celery_app.conf.beat_schedule = merged
    log.info("proactive.beat_register.merged", count=count, total=len(merged))
    return count


def _parse_cron(expr: str) -> dict[str, str]:
    """Parse "M H D M W" into kwargs for celery.schedules.crontab.

    We don't accept extended cron syntax (no @hourly, no /N steps);
    the simple 5-field form is enough for proactive flows. Reject
    anything we can't model so silent acceptance can't hide bugs.
    """
    fields = expr.strip().split()
    if len(fields) != 5:
        raise ValueError(
            f"cron expression must have 5 fields, got {len(fields)}: {expr!r}"
        )
    minute, hour, dom, month, dow = fields
    return {
        "minute": minute,
        "hour": hour,
        "day_of_month": dom,
        "month_of_year": month,
        "day_of_week": dow,
    }


__all__ = [
    "PROACTIVE_TASK_NAME",
    "ProactiveDispatchResult",
    "ProactiveError",
    "ProactiveSchedule",
    "WebhookFormatError",
    "WebhookSignatureError",
    "WebhookSubscription",
    "clear_proactive_registry",
    "cron_idempotency_key",
    "dispatch_proactive_run",
    "list_schedules",
    "list_subscriptions",
    "on_event",
    "proactive",
    "register_proactive_schedules",
    "route_webhook",
    "verify_github_signature",
    "verify_stripe_signature",
    "webhook_idempotency_key",
]
