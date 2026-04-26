"""Smoke tests for the readiness + JD decoder models.

These tests don't exercise behavior — they exist to catch the most common
modeling mistakes the moment commit 1 lands:

  * Tables aren't registered on Base.metadata (would silently fail in
    fixtures that rely on create_all).
  * FK targets don't resolve (typo in ondelete, missing use_alter on the
    cyclic verdict_id ↔ session_id pair).
  * Required columns missing.
  * The JdAnalysis hash uniqueness constraint actually fires.

When the wider service tests (commit 2+) start exercising these models
end-to-end, this file's value drops — but it's cheap insurance for the
data-model boundary.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from hashlib import sha256

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.jd_decoder import JdAnalysis, JdMatchScore
from app.models.readiness import (
    DIAGNOSTIC_STATUS_ACTIVE,
    DIAGNOSTIC_STATUS_COMPLETED,
    ReadinessDiagnosticSession,
    ReadinessDiagnosticTurn,
    ReadinessStudentSnapshot,
    ReadinessVerdict,
)
from app.models.user import User


async def _make_user(db: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"{uuid.uuid4()}@test.local",
        full_name="Readiness Test User",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user.id


@pytest.mark.asyncio
async def test_snapshot_persists_payload_and_allowlist(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    snap = ReadinessStudentSnapshot(
        user_id=user_id,
        payload={
            "lessons_completed": 12,
            "exercises_submitted": 18,
            "capstones_shipped": 0,
        },
        evidence_allowlist=["lessons_completed", "exercises_submitted"],
    )
    db_session.add(snap)
    await db_session.commit()
    await db_session.refresh(snap)
    assert snap.id is not None
    assert snap.built_at is not None
    assert "lessons_completed" in snap.evidence_allowlist


@pytest.mark.asyncio
async def test_diagnostic_session_round_trip(
    db_session: AsyncSession,
) -> None:
    """Full lifecycle: session → turns → verdict, with the cyclic FK
    pointing both directions resolved."""
    user_id = await _make_user(db_session)

    session = ReadinessDiagnosticSession(
        user_id=user_id,
        status=DIAGNOSTIC_STATUS_ACTIVE,
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    db_session.add_all(
        [
            ReadinessDiagnosticTurn(
                session_id=session.id,
                role="agent",
                content="Tell me where you're at.",
            ),
            ReadinessDiagnosticTurn(
                session_id=session.id,
                role="student",
                content="I'm stuck on system design.",
            ),
        ]
    )
    await db_session.commit()

    verdict = ReadinessVerdict(
        session_id=session.id,
        headline="System design is the gap; everything else is in shape.",
        evidence=[
            {
                "text": "Shipped 4 capstones",
                "evidence_id": "capstones_shipped",
                "kind": "strength",
            }
        ],
        next_action_intent="skills_gap",
        next_action_route="/courses/system-design",
        next_action_label="Open the system design lesson",
    )
    db_session.add(verdict)
    await db_session.commit()
    await db_session.refresh(verdict)

    # Close the loop — the session points at the verdict via the
    # use_alter FK.
    session.verdict_id = verdict.id
    session.status = DIAGNOSTIC_STATUS_COMPLETED
    session.completed_at = datetime.now(UTC)
    await db_session.commit()

    rows = (
        await db_session.execute(
            select(ReadinessDiagnosticTurn).where(
                ReadinessDiagnosticTurn.session_id == session.id
            )
        )
    ).scalars().all()
    assert len(rows) == 2
    assert {r.role for r in rows} == {"agent", "student"}


@pytest.mark.asyncio
async def test_jd_hash_is_unique(db_session: AsyncSession) -> None:
    """jd_analyses.jd_hash is the cache key — duplicates must be rejected
    at the DB level so cache logic can rely on it."""
    text = "Junior Python Developer — Backend / Tooling. Python, async, APIs."
    h = sha256(text.encode()).hexdigest()
    db_session.add(
        JdAnalysis(
            jd_hash=h,
            jd_text_truncated=text,
            parsed={"role": "Junior Python Developer"},
            analysis={"culture_signals": []},
        )
    )
    await db_session.commit()

    db_session.add(
        JdAnalysis(
            jd_hash=h,
            jd_text_truncated=text,
            parsed={"role": "duplicate"},
            analysis={"culture_signals": []},
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_match_score_supports_null_score(
    db_session: AsyncSession,
) -> None:
    """A thin-data student gets score=None — must be persistable."""
    user_id = await _make_user(db_session)
    text = "Some JD text here, sufficiently long for the schema."
    h = sha256(text.encode()).hexdigest()
    analysis = JdAnalysis(
        jd_hash=h,
        jd_text_truncated=text,
        parsed={"role": "Data Analyst"},
        analysis={"culture_signals": []},
    )
    db_session.add(analysis)
    await db_session.commit()
    await db_session.refresh(analysis)

    db_session.add(
        JdMatchScore(
            user_id=user_id,
            jd_analysis_id=analysis.id,
            score=None,
            headline="Not enough activity yet to score this match.",
            evidence=[],
            next_action_intent="thin_data",
            next_action_route="/today",
            next_action_label="Build a week of activity",
        )
    )
    await db_session.commit()

    row = (
        await db_session.execute(
            select(JdMatchScore).where(JdMatchScore.user_id == user_id)
        )
    ).scalar_one()
    assert row.score is None
    assert row.next_action_intent == "thin_data"
