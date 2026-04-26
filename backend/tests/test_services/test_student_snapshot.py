"""StudentSnapshot service tests.

Coverage:

  1. fresh_build_emits_persisted_row — build_student_snapshot returns a
     snapshot AND persists a readiness_student_snapshots row.
  2. ttl_reuses_recent_snapshot — a subsequent build within SNAPSHOT_TTL
     returns the cached row instead of rebuilding (idempotent + cheap).
  3. fresh_flag_forces_rebuild — fresh=True bypasses the TTL cache.
  4. peer_review_counts_only_no_quotes — the snapshot exposes count +
     avg rating but never raw comment text. Hard guardrail per Q2.
  5. capstones_shipped_returns_zero_today — Q1 default holds; the field
     exists with a 0 placeholder, ready for the future first-class model.
  6. recent_verdicts_surface_gap_concepts_only — past verdicts'
     gap-evidence is exposed; strength-evidence is intentionally omitted
     so memory-surfacing doesn't over-confidently reference past wins.
  7. allowlist_contains_snapshot_signals — every snapshot-level signal
     the LLM may cite is in the evidence_allowlist.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.peer_review import PeerReviewAssignment
from app.models.readiness import (
    ReadinessDiagnosticSession,
    ReadinessStudentSnapshot,
    ReadinessVerdict,
)
from app.models.user import User
from app.services.student_snapshot_service import (
    build_student_snapshot,
)


@pytest.fixture(autouse=True)
def _stub_regenerate_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_student_snapshot transitively calls profile_aggregator.
    build_base_resume_bundle, which calls regenerate_resume, which makes a
    live LLM call. The same monkeypatch the resume route tests use lets
    us run snapshot tests without an LLM key."""
    from app.services import career_service
    from app.services import profile_aggregator as pa

    async def fake_regen(db, *, user_id, force: bool = False):
        return await career_service.get_or_create_resume(db, user_id=user_id)

    monkeypatch.setattr(career_service, "regenerate_resume", fake_regen)
    monkeypatch.setattr(pa, "regenerate_resume", fake_regen)


async def _make_user(db: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"{uuid.uuid4()}@test.local",
        full_name="Snapshot Test User",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user.id


@pytest.mark.asyncio
async def test_fresh_build_emits_persisted_row(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    snap = await build_student_snapshot(db_session, user_id=user_id)

    persisted = (
        await db_session.execute(
            select(ReadinessStudentSnapshot).where(
                ReadinessStudentSnapshot.user_id == user_id
            )
        )
    ).scalars().all()

    assert len(persisted) == 1
    assert snap.id == persisted[0].id
    assert "lessons_completed" in snap.payload


@pytest.mark.asyncio
async def test_ttl_reuses_recent_snapshot(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    first = await build_student_snapshot(db_session, user_id=user_id)
    second = await build_student_snapshot(db_session, user_id=user_id)
    assert first.id == second.id

    persisted = (
        await db_session.execute(
            select(ReadinessStudentSnapshot).where(
                ReadinessStudentSnapshot.user_id == user_id
            )
        )
    ).scalars().all()
    assert len(persisted) == 1


@pytest.mark.asyncio
async def test_fresh_flag_forces_rebuild(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    first = await build_student_snapshot(db_session, user_id=user_id)
    second = await build_student_snapshot(
        db_session, user_id=user_id, fresh=True
    )
    assert first.id != second.id


@pytest.mark.asyncio
async def test_peer_review_counts_only_no_quotes(
    db_session: AsyncSession,
) -> None:
    """Per Q2 default: counts + average rating, never the comment text."""
    user_id = await _make_user(db_session)
    db_session.add_all(
        [
            PeerReviewAssignment(
                submission_id=uuid.uuid4(),
                reviewer_id=user_id,
                rating=5,
                comment="This is a private peer comment we never quote.",
                completed_at=datetime.now(UTC),
            ),
            PeerReviewAssignment(
                submission_id=uuid.uuid4(),
                reviewer_id=user_id,
                rating=3,
                comment="another private comment",
                completed_at=datetime.now(UTC),
            ),
        ]
    )
    await db_session.commit()

    snap = await build_student_snapshot(
        db_session, user_id=user_id, fresh=True
    )
    assert snap.payload["peer_review_count"] == 2
    assert snap.payload["peer_review_avg_rating"] == pytest.approx(4.0)

    # No comment text anywhere in payload.
    serialized = repr(snap.payload).lower()
    assert "private" not in serialized, (
        "peer review comment text leaked into snapshot — Q2 hard rule "
        "(counts + rating only, never quote)."
    )


@pytest.mark.asyncio
async def test_capstones_shipped_returns_zero_today(
    db_session: AsyncSession,
) -> None:
    """Q1 default holds: capstones aren't first-class yet, so the field
    is 0. Will become a real count when capstones are modeled."""
    user_id = await _make_user(db_session)
    snap = await build_student_snapshot(db_session, user_id=user_id)
    assert snap.payload["capstones_shipped"] == 0
    # And the field is part of the LLM summary so the agent knows it is
    # not data-rich on this dimension.
    assert snap.summary_for_llm()["capstones_shipped"] == 0


@pytest.mark.asyncio
async def test_recent_verdicts_surface_gap_concepts_only(
    db_session: AsyncSession,
) -> None:
    """Past verdicts contribute their gap-evidence concepts to the
    snapshot. Strength-evidence is intentionally omitted so the
    memory-surfacing service doesn't lean overconfident on past wins."""
    user_id = await _make_user(db_session)

    # Seed a past completed session + verdict.
    session = ReadinessDiagnosticSession(
        user_id=user_id, status="completed"
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    verdict = ReadinessVerdict(
        session_id=session.id,
        headline="System design is the gap.",
        evidence=[
            {
                "text": "No system design exposure",
                "evidence_id": "weakness:system_design",
                "kind": "gap",
            },
            {
                "text": "Strong Python skills",
                "evidence_id": "python",
                "kind": "strength",
            },
        ],
        next_action_intent="skills_gap",
        next_action_route="/courses/system-design",
        next_action_label="Open the system design lesson",
    )
    db_session.add(verdict)
    await db_session.commit()

    snap = await build_student_snapshot(
        db_session, user_id=user_id, fresh=True
    )
    rv = snap.payload.get("recent_verdict_summaries") or []
    assert len(rv) == 1
    assert rv[0]["gap_concepts"] == ["weakness:system_design"]
    # No strength evidence exposed.
    assert "python" not in rv[0]["gap_concepts"]


@pytest.mark.asyncio
async def test_allowlist_contains_snapshot_signals(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    snap = await build_student_snapshot(db_session, user_id=user_id)
    must_be_citable = {
        "lessons_completed",
        "exercises_submitted",
        "capstones_shipped",
        "mocks_taken",
        "peer_review_count",
        "resume_freshness_days",
        "time_on_task_minutes",
        "target_role",
    }
    missing = must_be_citable - snap.evidence_allowlist
    assert missing == set(), (
        f"Evidence allowlist is missing snapshot-level signals: {missing}. "
        "Verdict and match-score outputs reference these by ID — if any "
        "is absent the validator rejects every chip that cites it."
    )
