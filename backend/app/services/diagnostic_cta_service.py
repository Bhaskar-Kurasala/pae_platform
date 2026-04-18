"""Diagnostic opt-in CTA (P3 3B #4).

The prerequisite diagnostic itself is already shipped (P1-A-3). This
ticket adds an explicit CTA on onboarding step 4 whose decision we log
so product can measure opt-in vs dismiss vs snooze rates.

Pure helper validates the decision string; async writer persists it to
`agent_actions` so we get join-against-user telemetry for free.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_action import AgentAction

_VALID_DECISIONS = frozenset({"opted_in", "dismissed", "snoozed"})
_AGENT_NAME = "diagnostic_cta"
_ACTION_TYPE = "cta_decision"


def normalize_decision(raw: str) -> str:
    """Return the canonical decision string or raise ValueError.

    Accept/strip whitespace and lowercase so clients that send "Opted In"
    or "opted-in" don't break the API.
    """
    cleaned = (raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if cleaned not in _VALID_DECISIONS:
        raise ValueError(
            f"Unknown diagnostic CTA decision: {raw!r}. "
            f"Valid: {sorted(_VALID_DECISIONS)}"
        )
    return cleaned


async def record_cta_decision(
    db: AsyncSession, *, user_id: UUID, decision: str, note: str | None = None
) -> AgentAction:
    normalized = normalize_decision(decision)
    row = AgentAction(
        agent_name=_AGENT_NAME,
        student_id=user_id,
        action_type=_ACTION_TYPE,
        input_data={"decision": normalized, "note": note},
        output_data=None,
        status="completed",
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


__all__ = [
    "normalize_decision",
    "record_cta_decision",
]
