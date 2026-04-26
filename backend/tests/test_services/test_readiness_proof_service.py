"""Unit tests for the Readiness Proof Portfolio aggregator."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.compiler import compiles


@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(_type, _compiler, **_kw) -> str:  # type: ignore[no-untyped-def]
    return "TEXT"


def _visit_array(self, _type, **_kw):  # type: ignore[no-untyped-def]
    return "TEXT"


SQLiteTypeCompiler.visit_ARRAY = _visit_array  # type: ignore[attr-defined]

from app.models.ai_review import AIReview
from app.models.course import Course
from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission
from app.models.interview_session import InterviewSession
from app.models.lesson import Lesson
from app.models.mock_interview import MockSessionReport
from app.models.peer_review import PeerReviewAssignment
from app.models.portfolio_autopsy_result import PortfolioAutopsyResult
from app.models.user import User
from app.services.readiness_proof_service import load_proof


@pytest.mark.asyncio
async def test_load_proof_empty_user(db_session: AsyncSession) -> None:
    user = User(
        email="proof-empty@x.dev",
        full_name="Empty",
        hashed_password="x",
        role="student",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    result = await load_proof(db_session, user=user)

    assert result.capstone_artifacts == []
    assert result.ai_reviews.count == 0
    assert result.ai_reviews.last_three == []
    assert result.mock_reports == []
    assert result.autopsies == []
    assert result.peer_reviews.count_received == 0
    assert result.peer_reviews.count_given == 0
    assert result.last_capstone_summary is None


@pytest.mark.asyncio
async def test_load_proof_capstones_and_summary(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    user = User(
        email="proof-cap@x.dev",
        full_name="Cap Holder",
        hashed_password="x",
        role="student",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    course = Course(
        title="C", slug="c-proof", description="d",
        difficulty="medium", price_cents=0,
    )
    db_session.add(course)
    await db_session.flush()
    lesson = Lesson(
        course_id=course.id, title="L", slug="l-proof",
        order=1, is_published=True,
    )
    db_session.add(lesson)
    await db_session.flush()
    cap = Exercise(
        lesson_id=lesson.id,
        title="My Capstone",
        exercise_type="coding",
        difficulty="hard",
        is_capstone=True,
    )
    db_session.add(cap)
    await db_session.flush()

    db_session.add(
        ExerciseSubmission(
            student_id=user.id,
            exercise_id=cap.id,
            code="def main():\n    pass",
            status="graded",
            score=72,
        )
    )
    db_session.add(
        ExerciseSubmission(
            student_id=user.id,
            exercise_id=cap.id,
            code="def v2():\n    return 1",
            status="graded",
            score=85,
        )
    )
    await db_session.commit()

    result = await load_proof(db_session, user=user, now=now)

    assert len(result.capstone_artifacts) == 1
    artifact = result.capstone_artifacts[0]
    assert artifact.title == "My Capstone"
    assert artifact.draft_count == 2
    assert artifact.last_score in (72, 85)
    assert result.last_capstone_summary is not None
    assert result.last_capstone_summary.title == "My Capstone"
    assert result.last_capstone_summary.snippet is not None


@pytest.mark.asyncio
async def test_load_proof_autopsies_and_mocks(
    db_session: AsyncSession,
) -> None:
    user = User(
        email="proof-mix@x.dev",
        full_name="Mix",
        hashed_password="x",
        role="student",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    # 6 autopsies — only 5 should surface.
    for i in range(6):
        db_session.add(
            PortfolioAutopsyResult(
                user_id=user.id,
                project_title=f"Project {i}",
                project_description="desc",
                headline=f"Headline {i}",
                overall_score=50 + i,
                axes={},
                what_worked=[],
                what_to_do_differently=[],
                production_gaps=[],
            )
        )

    sess = InterviewSession(
        user_id=user.id, mode="behavioral", status="completed",
        target_role="Backend",
    )
    db_session.add(sess)
    await db_session.flush()
    db_session.add(
        MockSessionReport(
            session_id=sess.id,
            verdict="promising",
            headline="Solid behavioral",
        )
    )
    await db_session.commit()

    result = await load_proof(db_session, user=user)
    assert len(result.autopsies) == 5
    assert len(result.mock_reports) == 1
    assert result.mock_reports[0].target_role == "Backend"
    assert result.mock_reports[0].verdict == "promising"


@pytest.mark.asyncio
async def test_load_proof_ai_reviews_and_peer(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    user = User(
        email="proof-ai@x.dev",
        full_name="AI Bob",
        hashed_password="x",
        role="student",
    )
    other = User(
        email="proof-ai-o@x.dev",
        full_name="Other",
        hashed_password="x",
        role="student",
    )
    db_session.add_all([user, other])
    await db_session.commit()
    await db_session.refresh(user)
    await db_session.refresh(other)

    # 4 AI reviews — only 3 should surface; count = 4.
    for i in range(4):
        db_session.add(
            AIReview(
                user_id=user.id,
                code_snapshot="x = 1",
                review={"score": 60 + i, "notes": "ok"},
            )
        )

    # Peer review setup — needs a submission for each side.
    course = Course(
        title="C", slug="c-pr", description="d",
        difficulty="medium", price_cents=0,
    )
    db_session.add(course)
    await db_session.flush()
    lesson = Lesson(
        course_id=course.id, title="L", slug="l-pr",
        order=1, is_published=True,
    )
    db_session.add(lesson)
    await db_session.flush()
    ex = Exercise(
        lesson_id=lesson.id, title="E", exercise_type="coding",
        difficulty="medium", is_capstone=False,
    )
    db_session.add(ex)
    await db_session.flush()

    user_sub = ExerciseSubmission(
        student_id=user.id, exercise_id=ex.id, code="x", status="graded"
    )
    other_sub = ExerciseSubmission(
        student_id=other.id, exercise_id=ex.id, code="y", status="graded"
    )
    db_session.add_all([user_sub, other_sub])
    await db_session.flush()

    # 1 review received: someone reviewed user's submission.
    db_session.add(
        PeerReviewAssignment(
            submission_id=user_sub.id,
            reviewer_id=other.id,
            rating=4,
            completed_at=now,
        )
    )
    # 1 review given: user reviewed other's submission.
    db_session.add(
        PeerReviewAssignment(
            submission_id=other_sub.id,
            reviewer_id=user.id,
            rating=5,
            completed_at=now,
        )
    )
    await db_session.commit()

    result = await load_proof(db_session, user=user, now=now)

    assert result.ai_reviews.count == 4
    assert len(result.ai_reviews.last_three) == 3
    assert all(item.score is not None for item in result.ai_reviews.last_three)
    assert result.peer_reviews.count_received == 1
    assert result.peer_reviews.count_given == 1
