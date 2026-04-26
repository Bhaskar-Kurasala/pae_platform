"""Memory surface for the readiness diagnostic.

What memory does in this product:

  * On the FIRST agent message of a returning student's session, the
    interviewer references the prior diagnosis warmly ("Last time the
    gap was X — looks like you've moved on it. Where are you at today?").
    Without this, the diagnostic feels like a generic chatbot. With it,
    the agent feels like a coach who knows the student. That's the moat.

  * The verdict generator (commit 7) reads `prior_verdict_summaries` so
    the new verdict can acknowledge progress against named gaps.

What memory does NOT do here:

  * It is NOT a vector store / semantic memory. The MVP uses the
    structured ``recent_verdict_summaries`` already on the snapshot
    payload + a small overlap check against the current snapshot's
    open-weakness list. Vector memory is Phase 2 if and when this
    feature has retention worth investing further in.

  * It does NOT quote the student's prior conversation text. We only
    surface verdicts (already user-facing) and gap concepts (slugs).
    Quoting prior turns at the student would feel surveillance-like —
    that risk is called out in the spec.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mock_interview import MockWeaknessLedger
from app.models.readiness import (
    DIAGNOSTIC_STATUS_COMPLETED,
    ReadinessDiagnosticSession,
    ReadinessVerdict,
)
from app.services.student_snapshot_service import StudentSnapshot

log = structlog.get_logger()


async def build_prior_session_hint(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    snapshot: StudentSnapshot,
) -> str | None:
    """Return a short string the interviewer can reference on turn 1.

    Returns None when this is the student's first session OR when the
    prior verdict didn't surface any actionable gap concepts (so there's
    nothing meaningful to reference — defaulting to a "fresh" opener is
    better than reaching for a vague memory).
    """
    prior = await _load_last_completed_verdict(db, user_id=user_id)
    if prior is None:
        return None

    prior_verdict, prior_session = prior

    # Pull the gap concepts the prior verdict named.
    gap_ids = [
        e.get("evidence_id")
        for e in (prior_verdict.evidence or [])
        if isinstance(e, dict) and e.get("kind") == "gap" and e.get("evidence_id")
    ]
    if not gap_ids:
        return None

    # Cross-reference with currently-open MockWeaknessLedger entries —
    # anything still open is a gap that has NOT been closed since. The
    # snapshot already exposes open weaknesses as bare concept slugs.
    open_concepts: set[str] = {
        str(w["concept"])
        for w in snapshot.payload.get("open_weaknesses", [])
        if isinstance(w, dict) and w.get("concept")
    }
    resolved_recent: set[str] = set(
        snapshot.payload.get("weaknesses_resolved_recent") or []
    )

    closed: list[str] = []
    still_open: list[str] = []
    for gid in gap_ids:
        if not isinstance(gid, str):
            continue
        # Match either "weakness:foo" or bare "foo".
        bare = gid[len("weakness:"):] if gid.startswith("weakness:") else gid
        if bare in resolved_recent:
            closed.append(bare)
        elif bare in open_concepts:
            still_open.append(bare)
        # If the gap concept doesn't appear in either list, we cannot
        # tell from data whether it's closed — leave it out of the hint
        # rather than guess.

    if not closed and not still_open:
        return None

    # Compose a short hint. Always forward-looking. No reproachful
    # phrasing per spec.
    parts: list[str] = []
    if closed:
        if len(closed) == 1:
            parts.append(f"Looks like you've closed the {closed[0]} gap.")
        else:
            parts.append(
                f"Looks like you've closed gaps in {', '.join(closed[:3])}."
            )
    if still_open:
        if len(still_open) == 1:
            parts.append(
                f"Last time the gap was {still_open[0]}, and it's still open."
            )
        else:
            parts.append(
                f"Last time the open gaps were {', '.join(still_open[:3])}."
            )

    log.info(
        "readiness_memory.hint_built",
        user_id=str(user_id),
        prior_session_id=str(prior_session.id),
        closed=closed,
        still_open=still_open,
    )
    return " ".join(parts)


async def list_past_diagnoses(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Lightweight history for the "view past diagnoses" surface.

    Joins sessions to their verdicts where present. Returns oldest-last
    so the UI can render newest-first naturally.
    """
    rows = (
        await db.execute(
            select(ReadinessDiagnosticSession, ReadinessVerdict)
            .outerjoin(
                ReadinessVerdict,
                ReadinessVerdict.id == ReadinessDiagnosticSession.verdict_id,
            )
            .where(ReadinessDiagnosticSession.user_id == user_id)
            .order_by(desc(ReadinessDiagnosticSession.started_at))
            .limit(limit)
        )
    ).all()
    out: list[dict[str, Any]] = []
    for session, verdict in rows:
        out.append(
            {
                "session_id": session.id,
                "started_at": session.started_at,
                "completed_at": session.completed_at,
                "headline": verdict.headline if verdict else None,
                "next_action_label": (
                    verdict.next_action_label if verdict else None
                ),
                "next_action_intent": (
                    verdict.next_action_intent if verdict else None
                ),
                "next_action_clicked_at": session.next_action_clicked_at,
                "next_action_completed_at": session.next_action_completed_at,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _load_last_completed_verdict(
    db: AsyncSession, *, user_id: uuid.UUID
) -> tuple[ReadinessVerdict, ReadinessDiagnosticSession] | None:
    row = (
        await db.execute(
            select(ReadinessVerdict, ReadinessDiagnosticSession)
            .join(
                ReadinessDiagnosticSession,
                ReadinessDiagnosticSession.id == ReadinessVerdict.session_id,
            )
            .where(
                ReadinessDiagnosticSession.user_id == user_id,
                ReadinessDiagnosticSession.status
                == DIAGNOSTIC_STATUS_COMPLETED,
            )
            .order_by(desc(ReadinessVerdict.created_at))
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    return row[0], row[1]


# Re-exported for the orchestrator + tests.
__all__ = [
    "build_prior_session_hint",
    "list_past_diagnoses",
    "MockWeaknessLedger",  # convenience re-export
]
