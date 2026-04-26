"""WeaknessLedger reads + writes — the cross-session memory that makes mock #5
feel different from mock #1.

The ledger is an upsert-on-concept table. The orchestrator passes any
weakness signals from the Scorer into ``record_weaknesses()``; the Analyst
passes any addressed concepts into ``mark_addressed()``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mock_interview import MockSessionReport, MockWeaknessLedger

log = structlog.get_logger()

# Memory hygiene:
#  - prune entries older than 90 days regardless of state
#  - prune addressed entries older than 60 days
_OPEN_HORIZON_DAYS = 90
_ADDRESSED_HORIZON_DAYS = 60


async def get_open_weaknesses(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    limit: int = 12,
) -> list[MockWeaknessLedger]:
    """Return current open weaknesses, severity-desc, that should inform the
    next session. Auto-prunes stale entries on read."""
    await _prune_stale(db, user_id=user_id)
    result = await db.execute(
        select(MockWeaknessLedger)
        .where(
            MockWeaknessLedger.user_id == user_id,
            MockWeaknessLedger.addressed_at.is_(None),
        )
        .order_by(
            MockWeaknessLedger.severity.desc(),
            MockWeaknessLedger.last_seen_at.desc(),
        )
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_recent_reports(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    limit: int = 3,
) -> list[MockSessionReport]:
    """Return the most recent session reports for the Analyst's continuity context."""
    from app.models.interview_session import InterviewSession

    result = await db.execute(
        select(MockSessionReport)
        .join(
            InterviewSession,
            InterviewSession.id == MockSessionReport.session_id,
        )
        .where(InterviewSession.user_id == user_id)
        .order_by(MockSessionReport.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def record_weakness_signals(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    signals: list[dict[str, object]],
) -> None:
    """Upsert ``MockWeaknessLedger`` entries from a Scorer's `weakness_signals` list.

    Each signal: ``{"concept": str, "severity": float}``. We bump severity
    toward the new value via EMA (alpha=0.4) to avoid one-shot extremes.
    """
    if not signals:
        return

    now = datetime.now(UTC)
    for sig in signals:
        concept = str(sig.get("concept", "")).strip().lower()
        new_severity = float(sig.get("severity", 0.5))
        if not concept:
            continue

        existing = await db.execute(
            select(MockWeaknessLedger).where(
                MockWeaknessLedger.user_id == user_id,
                MockWeaknessLedger.concept == concept,
            )
        )
        row = existing.scalar_one_or_none()

        if row is None:
            db.add(
                MockWeaknessLedger(
                    user_id=user_id,
                    concept=concept,
                    severity=new_severity,
                    evidence_session_ids=[str(session_id)],
                    last_seen_at=now,
                )
            )
        else:
            blended = round(0.6 * row.severity + 0.4 * new_severity, 3)
            evidence = list(row.evidence_session_ids or [])
            sid = str(session_id)
            if sid not in evidence:
                evidence.append(sid)
            row.severity = blended
            row.last_seen_at = now
            row.evidence_session_ids = evidence
            # If a previously-addressed concept resurfaces, re-open it.
            if row.addressed_at is not None and new_severity >= 0.5:
                row.addressed_at = None

    await db.commit()
    log.info(
        "mock.memory.weaknesses_recorded",
        user_id=str(user_id),
        session_id=str(session_id),
        signal_count=len(signals),
    )


async def mark_addressed(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    concepts: list[str],
) -> None:
    """Mark concepts as addressed (the candidate scored ≥ 7 on them this session)."""
    if not concepts:
        return
    now = datetime.now(UTC)
    normalized = [c.strip().lower() for c in concepts if c]
    result = await db.execute(
        select(MockWeaknessLedger).where(
            MockWeaknessLedger.user_id == user_id,
            MockWeaknessLedger.concept.in_(normalized),
            MockWeaknessLedger.addressed_at.is_(None),
        )
    )
    rows = list(result.scalars().all())
    for row in rows:
        row.addressed_at = now
    await db.commit()
    log.info(
        "mock.memory.weaknesses_addressed",
        user_id=str(user_id),
        count=len(rows),
    )


def memory_recall_greeting(weaknesses: list[MockWeaknessLedger]) -> str | None:
    """Build the conversational greeting that appears at session start.

    Returns ``None`` when there's no relevant memory yet — silence is better
    than a generic 'welcome back!' line.
    """
    if not weaknesses:
        return None

    high_severity = [w for w in weaknesses if w.severity >= 0.6][:2]
    if not high_severity:
        return None

    if len(high_severity) == 1:
        concept = high_severity[0].concept
        return (
            f"Last time, {concept.replace('_', ' ').replace('.', ' — ')} "
            f"tripped you up. Let's see how it lands today."
        )

    a, b = high_severity[0].concept, high_severity[1].concept
    return (
        f"Two threads worth picking up from prior sessions: "
        f"{a.replace('_', ' ')} and {b.replace('_', ' ')}. I'll work both in."
    )


async def _prune_stale(db: AsyncSession, *, user_id: uuid.UUID) -> None:
    """Drop entries past the open/addressed horizons. Lazy on read."""
    now = datetime.now(UTC)
    open_cutoff = now - timedelta(days=_OPEN_HORIZON_DAYS)
    addressed_cutoff = now - timedelta(days=_ADDRESSED_HORIZON_DAYS)

    result = await db.execute(
        select(MockWeaknessLedger).where(
            MockWeaknessLedger.user_id == user_id,
        )
    )
    rows = list(result.scalars().all())
    pruned = 0
    for row in rows:
        # SQLite (test path) returns naive datetimes for timezone-aware
        # columns; Postgres returns aware. Coerce to UTC-aware so the
        # comparison works on both. Storage zone is always UTC.
        last_seen = row.last_seen_at
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=UTC)
        if last_seen < open_cutoff:
            await db.delete(row)
            pruned += 1
            continue
        if row.addressed_at is not None:
            addressed = row.addressed_at
            if addressed.tzinfo is None:
                addressed = addressed.replace(tzinfo=UTC)
            if addressed < addressed_cutoff:
                await db.delete(row)
                pruned += 1
    if pruned:
        await db.commit()
        log.info("mock.memory.pruned", user_id=str(user_id), count=pruned)
