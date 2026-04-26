"""StudentSnapshot — the verified-data picture both readiness agents read.

Wraps :class:`profile_aggregator.BaseResumeBundle` (the resume agent's
existing evidence aggregator) and extends it with the additional
dimensions the diagnostic and JD decoder need:

  * lessons_completed              (count of student_progress rows with
                                    completed_at not null)
  * exercises_submitted            (already on BaseResumeBundle as
                                    exercise_count)
  * capstones_shipped              (Q1 default: count of submissions
                                    tagged 'capstone' if such a tag
                                    exists; otherwise 0 with TODO)
  * recent_mock_scores             (last 5 InterviewSession.overall_score)
  * mocks_taken                    (count of completed InterviewSessions)
  * peer_review_count              (Q2 default: counts only — never
                                    quote peer review text)
  * peer_review_avg_rating         (1-5)
  * weakness_ledger_open           (open MockWeaknessLedger entries)
  * weakness_ledger_resolved_recent (entries marked addressed in last
                                    30 days — supports memory-surfacing)
  * resume_freshness_days          (days since Resume.updated_at)
  * time_on_task_minutes           (Q3 default: derived from
                                    student_progress.watch_time_seconds
                                    + exercises_submitted * 8min heuristic)
  * recent_diagnostic_verdicts     (last 3 ReadinessVerdicts — feeds the
                                    cross-session memory surface)

The snapshot is **persisted** as a ``readiness_student_snapshots`` row so
the diagnostic and decoder both see the same evidence within a session,
and the EvidenceValidator can audit later. TTL is 1 hour: a snapshot
older than that is discarded and rebuilt on the next request.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.interview_session import InterviewSession
from app.models.mock_interview import MockWeaknessLedger
from app.models.peer_review import PeerReviewAssignment
from app.models.readiness import ReadinessStudentSnapshot, ReadinessVerdict
from app.models.resume import Resume
from app.models.student_progress import StudentProgress
from app.services.profile_aggregator import (
    BaseResumeBundle,
    build_base_resume_bundle,
)

log = structlog.get_logger()

SNAPSHOT_TTL = timedelta(hours=1)

# Heuristic: each completed exercise represents roughly 8 minutes of
# focused coding time. Coarse but honest — we deliberately do not engineer
# a separate IDE-time signal (Phase 2 work).
_EXERCISE_MINUTES = 8


@dataclass
class StudentSnapshot:
    """Strongly-typed view onto a ``readiness_student_snapshots`` row."""

    id: uuid.UUID
    user_id: uuid.UUID
    payload: dict[str, Any]
    evidence_allowlist: set[str]
    bundle: BaseResumeBundle | None = None
    built_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def summary_for_llm(self) -> dict[str, Any]:
        """The compact JSON the LLM sees in any prompt.

        Smaller than ``payload`` — drops verbose lists like the full
        weakness ledger and recent verdicts; downstream prompts that need
        them pull from ``payload`` directly.
        """
        p = self.payload
        return {
            "target_role": p.get("target_role"),
            "lessons_completed": p.get("lessons_completed", 0),
            "exercises_submitted": p.get("exercises_submitted", 0),
            "capstones_shipped": p.get("capstones_shipped", 0),
            "mocks_taken": p.get("mocks_taken", 0),
            "recent_mock_scores": p.get("recent_mock_scores", [])[:3],
            "peer_review_count": p.get("peer_review_count", 0),
            "peer_review_avg_rating": p.get("peer_review_avg_rating"),
            "open_weaknesses": [
                w["concept"] for w in p.get("open_weaknesses", [])
            ][:6],
            "resume_freshness_days": p.get("resume_freshness_days"),
            "time_on_task_minutes": p.get("time_on_task_minutes", 0),
            "skills_top": [
                s["name"] for s in p.get("skills_top", [])
            ][:8],
        }


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


async def build_student_snapshot(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    fresh: bool = False,
) -> StudentSnapshot:
    """Return a snapshot for *user_id*. Reuses the most recent persisted
    row if it's within ``SNAPSHOT_TTL`` and *fresh* is False.
    """
    if not fresh:
        cached = await _load_recent_snapshot(db, user_id=user_id)
        if cached is not None:
            return cached

    bundle = await build_base_resume_bundle(db, user_id=user_id)

    lessons_completed = await _count_lessons_completed(db, user_id=user_id)
    capstones_shipped = await _count_capstones(db, user_id=user_id)
    mocks_taken, recent_mock_scores = await _mock_summary(
        db, user_id=user_id
    )
    peer_count, peer_avg = await _peer_review_summary(db, user_id=user_id)
    open_weaknesses = await _open_weaknesses(db, user_id=user_id)
    weaknesses_resolved_recent = await _weaknesses_resolved_recent(
        db, user_id=user_id
    )
    resume_freshness_days = await _resume_freshness(db, user_id=user_id)
    watch_seconds = await _watch_time_seconds(db, user_id=user_id)
    time_on_task = (
        watch_seconds // 60
    ) + bundle.exercise_count * _EXERCISE_MINUTES
    recent_verdicts = await _recent_verdicts(db, user_id=user_id)

    target_role: str | None = None
    intake = bundle.intake_data or {}
    if isinstance(intake, dict):
        prefs = intake.get("preferences") or {}
        if isinstance(prefs, dict):
            tr = prefs.get("target_role")
            if isinstance(tr, str) and tr.strip():
                target_role = tr.strip()

    skills_top: list[dict[str, Any]] = sorted(
        (
            {"name": k, "confidence": round(v, 2)}
            for k, v in bundle.skill_map.items()
        ),
        key=lambda x: float(x["confidence"]),
        reverse=True,
    )

    payload: dict[str, Any] = {
        "target_role": target_role,
        "lessons_completed": lessons_completed,
        "exercises_submitted": bundle.exercise_count,
        "capstones_shipped": capstones_shipped,
        "mocks_taken": mocks_taken,
        "recent_mock_scores": recent_mock_scores,
        "peer_review_count": peer_count,
        "peer_review_avg_rating": peer_avg,
        "open_weaknesses": [
            {
                "concept": w.concept,
                "severity": w.severity,
                "last_seen_at": w.last_seen_at.isoformat()
                if w.last_seen_at
                else None,
            }
            for w in open_weaknesses
        ],
        "weaknesses_resolved_recent": weaknesses_resolved_recent,
        "resume_freshness_days": resume_freshness_days,
        "time_on_task_minutes": time_on_task,
        "skills_top": skills_top,
        "recent_verdict_summaries": recent_verdicts,
    }
    allowlist = _build_evidence_allowlist(bundle, payload)

    row = ReadinessStudentSnapshot(
        user_id=user_id,
        payload=payload,
        evidence_allowlist=sorted(allowlist),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    log.info(
        "student_snapshot.built",
        user_id=str(user_id),
        evidence_size=len(allowlist),
    )
    return StudentSnapshot(
        id=row.id,
        user_id=user_id,
        payload=payload,
        evidence_allowlist=allowlist,
        bundle=bundle,
        built_at=row.built_at,
    )


async def _load_recent_snapshot(
    db: AsyncSession, *, user_id: uuid.UUID
) -> StudentSnapshot | None:
    cutoff = datetime.now(UTC) - SNAPSHOT_TTL
    row = (
        await db.execute(
            select(ReadinessStudentSnapshot)
            .where(
                ReadinessStudentSnapshot.user_id == user_id,
                ReadinessStudentSnapshot.built_at >= cutoff,
            )
            .order_by(desc(ReadinessStudentSnapshot.built_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return StudentSnapshot(
        id=row.id,
        user_id=row.user_id,
        payload=dict(row.payload or {}),
        evidence_allowlist=set(row.evidence_allowlist or []),
        built_at=row.built_at,
    )


# ---------------------------------------------------------------------------
# Per-dimension queries (each returns a primitive — keep the surface tight).
# ---------------------------------------------------------------------------


async def _count_lessons_completed(
    db: AsyncSession, *, user_id: uuid.UUID
) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(StudentProgress)
        .where(
            StudentProgress.student_id == user_id,
            StudentProgress.completed_at.is_not(None),
        )
    )
    return int(result.scalar_one_or_none() or 0)


async def _count_capstones(db: AsyncSession, *, user_id: uuid.UUID) -> int:
    """Capstones don't have a first-class model yet (see the spec Q1 in
    the build plan). Today we cannot distinguish capstones from regular
    exercise submissions, so we honestly return 0 and surface the gap.

    TODO: when capstones become a first-class model (their own table or
    a dedicated tag on Exercise), update this to count completed
    capstone submissions.
    """
    return 0


async def _mock_summary(
    db: AsyncSession, *, user_id: uuid.UUID
) -> tuple[int, list[float]]:
    rows = (
        await db.execute(
            select(InterviewSession.overall_score)
            .where(
                InterviewSession.user_id == user_id,
                InterviewSession.overall_score.is_not(None),
            )
            .order_by(desc(InterviewSession.created_at))
            .limit(5)
        )
    ).scalars().all()
    return len(rows), [float(s) for s in rows if s is not None]


async def _peer_review_summary(
    db: AsyncSession, *, user_id: uuid.UUID
) -> tuple[int, float | None]:
    """Counts + average rating only. We never quote peer-review text."""
    result = await db.execute(
        select(
            func.count(PeerReviewAssignment.id),
            func.avg(PeerReviewAssignment.rating),
        ).where(
            PeerReviewAssignment.reviewer_id == user_id,
            PeerReviewAssignment.completed_at.is_not(None),
        )
    )
    count, avg = result.one()
    avg_value: float | None = float(avg) if avg is not None else None
    return int(count or 0), avg_value


async def _open_weaknesses(
    db: AsyncSession, *, user_id: uuid.UUID
) -> list[MockWeaknessLedger]:
    rows = (
        await db.execute(
            select(MockWeaknessLedger)
            .where(
                MockWeaknessLedger.user_id == user_id,
                MockWeaknessLedger.addressed_at.is_(None),
            )
            .order_by(
                desc(MockWeaknessLedger.severity),
                desc(MockWeaknessLedger.last_seen_at),
            )
            .limit(12)
        )
    ).scalars().all()
    return list(rows)


async def _weaknesses_resolved_recent(
    db: AsyncSession, *, user_id: uuid.UUID
) -> list[str]:
    cutoff = datetime.now(UTC) - timedelta(days=30)
    rows = (
        await db.execute(
            select(MockWeaknessLedger.concept)
            .where(
                MockWeaknessLedger.user_id == user_id,
                MockWeaknessLedger.addressed_at.is_not(None),
                MockWeaknessLedger.addressed_at >= cutoff,
            )
            .order_by(desc(MockWeaknessLedger.addressed_at))
            .limit(8)
        )
    ).scalars().all()
    return [str(r) for r in rows]


async def _resume_freshness(
    db: AsyncSession, *, user_id: uuid.UUID
) -> int | None:
    row = (
        await db.execute(
            select(Resume.updated_at).where(Resume.user_id == user_id)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    # SQLite (test path) stores DateTime(timezone=True) values as naive
    # strings; Postgres returns aware datetimes. Coerce to aware so the
    # subtraction works on both. UTC is the platform-wide stored zone
    # (every model column uses timezone=True with UTC defaults).
    if row.tzinfo is None:
        row = row.replace(tzinfo=UTC)
    delta = datetime.now(UTC) - row
    return max(0, delta.days)


async def _watch_time_seconds(
    db: AsyncSession, *, user_id: uuid.UUID
) -> int:
    result = await db.execute(
        select(func.coalesce(func.sum(StudentProgress.watch_time_seconds), 0))
        .where(StudentProgress.student_id == user_id)
    )
    return int(result.scalar_one_or_none() or 0)


async def _recent_verdicts(
    db: AsyncSession, *, user_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Pulls the last 3 verdicts via the session join. Used by the
    memory-surfacing service in commit 6.
    """
    from app.models.readiness import ReadinessDiagnosticSession

    rows = (
        await db.execute(
            select(ReadinessVerdict, ReadinessDiagnosticSession.completed_at)
            .join(
                ReadinessDiagnosticSession,
                ReadinessDiagnosticSession.id == ReadinessVerdict.session_id,
            )
            .where(ReadinessDiagnosticSession.user_id == user_id)
            .order_by(desc(ReadinessVerdict.created_at))
            .limit(3)
        )
    ).all()
    return [
        {
            "headline": v.headline,
            "next_action_intent": v.next_action_intent,
            "completed_at": completed_at.isoformat()
            if completed_at
            else None,
            # We surface the gap-evidence concepts so memory-surfacing can
            # check whether the gap has since been closed; we deliberately
            # do NOT surface strength evidence (that would lean toward
            # over-confident memory references).
            "gap_concepts": [
                e.get("evidence_id")
                for e in (v.evidence or [])
                if isinstance(e, dict) and e.get("kind") == "gap"
            ],
        }
        for v, completed_at in rows
    ]


# ---------------------------------------------------------------------------
# Allowlist construction
# ---------------------------------------------------------------------------


def _build_evidence_allowlist(
    bundle: BaseResumeBundle, payload: dict[str, Any]
) -> set[str]:
    """Set of evidence_id strings the LLM may cite.

    Inherits the resume agent's existing allowlist (skill names, exercise
    volume, self-attested entries with explicit IDs) and adds the
    snapshot-level signals.
    """
    allowlist: set[str] = set(bundle.evidence_allowlist)
    # Snapshot-level signals — every key the verdict / match-score may
    # reference must appear here.
    snapshot_ids = {
        "lessons_completed",
        "exercises_submitted",
        "capstones_shipped",
        "mocks_taken",
        "recent_mock_scores",
        "peer_review_count",
        "peer_review_avg_rating",
        "resume_freshness_days",
        "time_on_task_minutes",
        "target_role",
    }
    allowlist.update(snapshot_ids)
    # Each open-weakness concept is independently citable.
    for w in payload.get("open_weaknesses", []):
        if isinstance(w, dict) and w.get("concept"):
            allowlist.add(f"weakness:{w['concept']}")
    # Each recently-resolved weakness too — supports the memory-surfacing
    # "you closed the X gap" case.
    for concept in payload.get("weaknesses_resolved_recent", []):
        allowlist.add(f"resolved:{concept}")
    return allowlist


__all__ = [
    "StudentSnapshot",
    "SNAPSHOT_TTL",
    "build_student_snapshot",
]
