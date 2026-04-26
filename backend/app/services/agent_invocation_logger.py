"""Dual-write helper for the agent_invocation_log migration window.

During the dual-write window every cost-bearing LLM call is logged to BOTH
the legacy per-agent table (mock_cost_log, generation_logs) and the new
unified agent_invocation_log. The legacy tables remain authoritative for
read paths until a parallel-read gate proves parity for 100 consecutive
checks; only then do callers flip their reads to the new table.

**Sunset target for the dual-write window: 2026-05-09.** After flip,
follow-up migrations drop the cost columns on generation_logs and the
mock_cost_log table itself.

This module exposes two surfaces:

1. ``log_invocation(...)`` — the dual-write writer. Callers in mock and
   resume services call this on every cost-bearing event. It writes only
   the new table; the legacy write happens at the call site (so we don't
   reorder the legacy commit semantics).
2. ``record_parity_check(...)`` — durable gate update. Increments the
   consecutive-agreement counter on a match; resets it and stores the
   diverging payload on a mismatch; flips ``flipped=true`` once the
   threshold is hit. Read paths consult ``has_flipped(...)`` to decide
   which source to trust.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_invocation_log import (
    STATUS_CAP_EXCEEDED,
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    AgentInvocationLog,
)
from app.models.migration_gate import MigrationGate

log = structlog.get_logger()

# Once this many consecutive parity checks agree, the gate flips and
# read paths start trusting agent_invocation_log directly. Resets on
# any divergence.
AGREEMENT_THRESHOLD = 100

_VALID_STATUSES = (STATUS_SUCCEEDED, STATUS_FAILED, STATUS_CAP_EXCEEDED)


async def log_invocation(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    source: str,
    source_id: str | uuid.UUID | None,
    sub_agent: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    cost_inr: float,
    status: str,
    latency_ms: int | None = None,
    error_message: str | None = None,
) -> None:
    """Write one row to agent_invocation_log.

    Caller is responsible for the legacy write (we do not invert legacy
    commit semantics). This function only adds — the surrounding
    transaction commits when the caller's existing flow commits.

    Failures here are logged and swallowed so the dual-write never breaks
    the primary path. The legacy table remains the source of truth during
    the migration window, so a missed agent_invocation_log row degrades
    parity tracking but does not lose data.
    """
    if status not in _VALID_STATUSES:
        log.warning(
            "agent_invocation_logger.invalid_status",
            status=status,
            source=source,
        )
        return
    try:
        db.add(
            AgentInvocationLog(
                user_id=user_id,
                source=source,
                source_id=str(source_id) if source_id is not None else None,
                sub_agent=sub_agent,
                model=model,
                tokens_in=int(tokens_in or 0),
                tokens_out=int(tokens_out or 0),
                cost_inr=float(cost_inr or 0.0),
                latency_ms=latency_ms,
                status=status,
                error_message=error_message[:512] if error_message else None,
            )
        )
        await db.flush()
    except Exception as exc:  # noqa: BLE001 — never break the primary path
        log.warning(
            "agent_invocation_logger.write_failed",
            source=source,
            sub_agent=sub_agent,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Parallel-read gate
# ---------------------------------------------------------------------------


async def has_flipped(db: AsyncSession, *, gate_name: str) -> bool:
    """Return True once the gate has flipped to read from the new source."""
    row = (
        await db.execute(
            select(MigrationGate).where(MigrationGate.name == gate_name)
        )
    ).scalar_one_or_none()
    return bool(row and row.flipped)


async def record_parity_check(
    db: AsyncSession,
    *,
    gate_name: str,
    legacy_value: Any,
    new_value: Any,
    context: dict[str, Any] | None = None,
) -> bool:
    """Update the named gate based on whether legacy and new agree.

    Returns True on agreement, False on divergence. Side effects:

    * On agreement: increment consecutive_agreements + total_checks. If
      consecutive_agreements reaches AGREEMENT_THRESHOLD, set flipped=true.
    * On divergence: increment total_checks + total_divergences, reset
      consecutive_agreements to 0, persist a structured payload describing
      the diverging values for later audit. Emit a structured log so the
      divergence is visible in real time.

    This function never raises — telemetry failures must not break the
    request path. If the gate row is missing (shouldn't happen post-0040,
    but might in tests that skip the migration), it logs and returns the
    agreement boolean without touching state.
    """
    agree = legacy_value == new_value

    try:
        row = (
            await db.execute(
                select(MigrationGate).where(MigrationGate.name == gate_name)
            )
        ).scalar_one_or_none()
        if row is None:
            log.warning(
                "agent_invocation_logger.gate_missing", gate_name=gate_name
            )
            return agree

        now = datetime.now(UTC)
        if agree:
            new_count = row.consecutive_agreements + 1
            flipped = row.flipped or new_count >= AGREEMENT_THRESHOLD
            await db.execute(
                update(MigrationGate)
                .where(MigrationGate.name == gate_name)
                .values(
                    consecutive_agreements=new_count,
                    total_checks=row.total_checks + 1,
                    flipped=flipped,
                    updated_at=now,
                )
            )
            if flipped and not row.flipped:
                log.info(
                    "agent_invocation_logger.gate_flipped",
                    gate_name=gate_name,
                    after_checks=row.total_checks + 1,
                )
        else:
            payload = {
                "legacy": _coerce_json(legacy_value),
                "new": _coerce_json(new_value),
                "context": context or {},
                "at": now.isoformat(),
            }
            await db.execute(
                update(MigrationGate)
                .where(MigrationGate.name == gate_name)
                .values(
                    consecutive_agreements=0,
                    total_checks=row.total_checks + 1,
                    total_divergences=row.total_divergences + 1,
                    last_divergence_payload=payload,
                    updated_at=now,
                )
            )
            log.warning(
                "agent_invocation_logger.parity_divergence",
                gate_name=gate_name,
                legacy=payload["legacy"],
                new=payload["new"],
                context=payload["context"],
            )
        await db.flush()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "agent_invocation_logger.gate_update_failed",
            gate_name=gate_name,
            error=str(exc),
        )

    return agree


def _coerce_json(v: Any) -> Any:
    if isinstance(v, (str, int, float, bool, type(None))):
        return v
    if isinstance(v, (list, tuple)):
        return [_coerce_json(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _coerce_json(x) for k, x in v.items()}
    return str(v)
