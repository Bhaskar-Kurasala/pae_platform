"""D15 CP2 — stub-LLM smoke tests for the three role-state tools.

Coverage matrix:

  read_student_role_state:
    1. happy path: seeded student returns python_developer
    2. terminal role: senior_genai_engineer returns next_transition=None
    3. found=False when no student_role_state row exists
    4. transitions_completed JSONB array round-trips through the tool
    5. days_in_role is computed from role_started_at via Postgres
       date arithmetic

  read_student_accessible_content:
    6. happy path: student with one entitlement, role_slug=None,
       returns the course + any exercises under it
    7. role_slug filter narrows the courses list to the requested role
    8. no entitlements → found=False, completeness=minimal
    9. tributary course (role_id=NULL) is reported with role_slug=None

  evaluate_student_against_gate:
    10. zero capstones, zero mocks → fail (the typical CP2-ship state
        for a fresh student)
    11. capstone above threshold but mocks empty → fail (mock side blocks)
    12. non-adjacent target raises ValueError
    13. no student_role_state raises ValueError
    14. terminal role raises ValueError (no further transitions)
    15. capstone status reflects normalized score (int/100 → float)

Each test runs inside a Postgres transaction that's rolled back on
teardown — the dev DB's seeded data is untouched. The contextvar
`_active_session` is set to that same session so tool bodies can
recover it via get_active_session().
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.agents.primitives import communication as comm_mod
from app.agents.tools.universal.evaluate_student_against_gate import (
    EvaluateStudentAgainstGateInput,
    evaluate_student_against_gate,
)
from app.agents.tools.universal.read_student_accessible_content import (
    ReadStudentAccessibleContentInput,
    read_student_accessible_content,
)
from app.agents.tools.universal.read_student_role_state import (
    ReadStudentRoleStateInput,
    read_student_role_state,
)


def _dsn() -> str:
    return os.environ.get(
        "TEST_PG_DSN",
        "postgresql+asyncpg://postgres:postgres@localhost:5433/platform",
    )


def _pg_reachable() -> bool:
    raw = _dsn().replace("postgresql+asyncpg://", "postgresql://", 1)

    async def _probe() -> bool:
        try:
            conn = await asyncpg.connect(raw, timeout=2.0)
            await conn.close()
            return True
        except Exception:
            return False

    try:
        return asyncio.run(_probe())
    except Exception:
        return False


_PG_OK = _pg_reachable()
pytestmark = pytest.mark.skipif(
    not _PG_OK,
    reason="No reachable Postgres at TEST_PG_DSN; skip role-state tools smoke.",
)


@pytest_asyncio.fixture
async def pg_session() -> AsyncGenerator[AsyncSession, None]:
    """Open a session, run inside an outer transaction, roll back on
    teardown. Dev DB's seeded rows (six roles, five transitions, 129
    student_role_state rows) are visible to the test; any test inserts
    are wiped on teardown.
    """
    engine = create_async_engine(_dsn(), echo=False)
    async with engine.connect() as connection:
        outer_tx = await connection.begin()
        async_session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            yield async_session
        finally:
            await async_session.close()
            await outer_tx.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def session_on_contextvar(
    pg_session: AsyncSession,
) -> AsyncGenerator[AsyncSession, None]:
    token = comm_mod._active_session.set(pg_session)
    try:
        yield pg_session
    finally:
        comm_mod._active_session.reset(token)


# ── Test helpers ──────────────────────────────────────────────────────


async def _make_student(session: AsyncSession) -> uuid.UUID:
    sid = uuid.uuid4()
    await session.execute(
        sql_text(
            "INSERT INTO users (id, email, full_name, hashed_password, "
            "is_active, is_verified, role) "
            "VALUES (:id, :email, :name, 'x', TRUE, FALSE, 'student')"
        ),
        {
            "id": sid,
            "email": f"d15-smoke-{sid}@test.invalid",
            "name": "D15 Smoke",
        },
    )
    return sid


async def _seed_role_state(
    session: AsyncSession,
    student_id: uuid.UUID,
    *,
    role_slug: str = "python_developer",
    role_started_at: datetime | None = None,
    transitions_completed: list[dict] | None = None,
) -> None:
    role_id = (
        await session.execute(
            sql_text("SELECT id FROM roles WHERE slug = :s"),
            {"s": role_slug},
        )
    ).scalar_one()
    started = role_started_at or datetime.now(UTC)
    import json as _json

    completed_json = _json.dumps(transitions_completed or [])
    await session.execute(
        sql_text(
            """
            INSERT INTO student_role_state
                (student_id, current_role_id, role_started_at,
                 transitions_completed)
            VALUES (:sid, :rid, :started, CAST(:completed AS JSONB))
            ON CONFLICT (student_id) DO UPDATE
            SET current_role_id = EXCLUDED.current_role_id,
                role_started_at = EXCLUDED.role_started_at,
                transitions_completed = EXCLUDED.transitions_completed
            """
        ),
        {
            "sid": student_id,
            "rid": role_id,
            "started": started,
            "completed": completed_json,
        },
    )


async def _seed_entitlement(
    session: AsyncSession,
    student_id: uuid.UUID,
    course_slug: str,
) -> None:
    course_id = (
        await session.execute(
            sql_text("SELECT id FROM courses WHERE slug = :s"),
            {"s": course_slug},
        )
    ).scalar_one()
    await session.execute(
        sql_text(
            "INSERT INTO course_entitlements "
            "(id, user_id, course_id, source) "
            "VALUES (gen_random_uuid(), :uid, :cid, 'free')"
        ),
        {"uid": student_id, "cid": course_id},
    )


async def _seed_capstone_submission(
    session: AsyncSession,
    student_id: uuid.UUID,
    *,
    course_slug: str,
    score: int,
) -> None:
    """Seed a fully-evaluated capstone submission under a course.

    The score is the integer 0-100 the schema stores; the tool
    normalizes by dividing by 100 when comparing against the float
    threshold.
    """
    cap_row = (
        await session.execute(
            sql_text(
                """
                SELECT e.id
                FROM exercises e
                JOIN lessons l ON l.id = e.lesson_id
                JOIN courses c ON c.id = l.course_id
                WHERE c.slug = :slug AND e.is_capstone = TRUE
                LIMIT 1
                """
            ),
            {"slug": course_slug},
        )
    ).first()
    assert cap_row is not None, f"no capstone under {course_slug}"
    exercise_id = cap_row[0]
    await session.execute(
        sql_text(
            "INSERT INTO exercise_submissions "
            "(id, student_id, exercise_id, status, score, attempt_number) "
            "VALUES (gen_random_uuid(), :sid, :eid, 'evaluated', :score, 1)"
        ),
        {"sid": student_id, "eid": exercise_id, "score": score},
    )


# ── read_student_role_state tests ─────────────────────────────────────


async def test_read_student_role_state_happy_path(
    session_on_contextvar: AsyncSession,
) -> None:
    sid = await _make_student(session_on_contextvar)
    await _seed_role_state(session_on_contextvar, sid, role_slug="python_developer")

    out = await read_student_role_state(
        ReadStudentRoleStateInput(student_id=sid)
    )

    assert out.found is True
    assert out.current_role is not None
    assert out.current_role.slug == "python_developer"
    assert out.current_role.sequence_order == 1
    assert out.current_role.is_terminal is False
    assert out.next_transition is not None
    assert out.next_transition.target_role_slug == "data_analyst"
    # gate_summary format: "capstone score >= X.XX (need 1) AND 2 of last 3 ..."
    assert "capstone" in out.next_transition.gate_summary
    assert "0.65" in out.next_transition.gate_summary


async def test_read_student_role_state_terminal_has_no_next(
    session_on_contextvar: AsyncSession,
) -> None:
    sid = await _make_student(session_on_contextvar)
    await _seed_role_state(
        session_on_contextvar, sid, role_slug="senior_genai_engineer"
    )

    out = await read_student_role_state(
        ReadStudentRoleStateInput(student_id=sid)
    )

    assert out.found is True
    assert out.current_role is not None
    assert out.current_role.is_terminal is True
    assert out.next_transition is None


async def test_read_student_role_state_not_found(
    session_on_contextvar: AsyncSession,
) -> None:
    bogus = uuid.uuid4()  # never inserted

    out = await read_student_role_state(
        ReadStudentRoleStateInput(student_id=bogus)
    )

    assert out.found is False
    assert out.current_role is None
    assert out.next_transition is None
    assert out.transitions_completed == []


async def test_read_student_role_state_transitions_completed_round_trip(
    session_on_contextvar: AsyncSession,
) -> None:
    sid = await _make_student(session_on_contextvar)
    history = [
        {
            "from_slug": "python_developer",
            "to_slug": "data_analyst",
            "completed_at": "2026-04-01T00:00:00+00:00",
            "capstone_score": 0.78,
            "mock_session_ids": [str(uuid.uuid4()), str(uuid.uuid4())],
        }
    ]
    await _seed_role_state(
        session_on_contextvar,
        sid,
        role_slug="data_analyst",
        transitions_completed=history,
    )

    out = await read_student_role_state(
        ReadStudentRoleStateInput(student_id=sid)
    )

    assert out.found is True
    assert len(out.transitions_completed) == 1
    record = out.transitions_completed[0]
    assert record.from_slug == "python_developer"
    assert record.to_slug == "data_analyst"
    assert record.capstone_score == pytest.approx(0.78, abs=1e-9)
    assert len(record.mock_session_ids) == 2


async def test_read_student_role_state_days_in_role_computed(
    session_on_contextvar: AsyncSession,
) -> None:
    sid = await _make_student(session_on_contextvar)
    await _seed_role_state(
        session_on_contextvar,
        sid,
        role_slug="python_developer",
        role_started_at=datetime.now(UTC) - timedelta(days=10),
    )

    out = await read_student_role_state(
        ReadStudentRoleStateInput(student_id=sid)
    )

    assert out.found is True
    assert out.days_in_role is not None
    # Rounding/timezone arithmetic — accept 9-11 days for a 10-day stamp.
    assert 9 <= out.days_in_role <= 11


# ── read_student_accessible_content tests ─────────────────────────────


async def test_read_accessible_content_happy_path_unfiltered(
    session_on_contextvar: AsyncSession,
) -> None:
    sid = await _make_student(session_on_contextvar)
    # python-foundations is the tributary tier-2 course; mapped to
    # python_developer per CP2b. Has 32 exercises + 1 capstone.
    await _seed_entitlement(session_on_contextvar, sid, "python-foundations")

    out = await read_student_accessible_content(
        ReadStudentAccessibleContentInput(student_id=sid, role_slug=None)
    )

    assert out.found is True
    assert out.filtered_to_role_slug is None
    course_slugs = {c.course_slug for c in out.accessible_courses}
    assert "python-foundations" in course_slugs
    # python-foundations holds 32 exercises (1 capstone + 31 non-capstone).
    assert len(out.accessible_curated_problems) >= 1
    assert any(p.is_capstone for p in out.accessible_curated_problems)
    # Notebooks are still empty in CP2 (lesson_resources unpopulated).
    assert out.accessible_notebooks == []
    # courses + problems present, notebooks empty → partial.
    assert out.content_schema_completeness == "partial"


async def test_read_accessible_content_role_slug_filter(
    session_on_contextvar: AsyncSession,
) -> None:
    sid = await _make_student(session_on_contextvar)
    await _seed_entitlement(session_on_contextvar, sid, "python-foundations")
    await _seed_entitlement(session_on_contextvar, sid, "data-analyst")

    # Filter to data_analyst — python-foundations should be excluded.
    out = await read_student_accessible_content(
        ReadStudentAccessibleContentInput(
            student_id=sid, role_slug="data_analyst"
        )
    )

    assert out.found is True
    assert out.filtered_to_role_slug == "data_analyst"
    course_slugs = {c.course_slug for c in out.accessible_courses}
    assert "data-analyst" in course_slugs
    assert "python-foundations" not in course_slugs
    # data-analyst has no exercises on dev DB; problems list is empty.
    assert out.accessible_curated_problems == []
    # Has course but no problems and no notebooks → partial.
    assert out.content_schema_completeness == "partial"


async def test_read_accessible_content_no_entitlements(
    session_on_contextvar: AsyncSession,
) -> None:
    sid = await _make_student(session_on_contextvar)
    # No entitlements seeded.

    out = await read_student_accessible_content(
        ReadStudentAccessibleContentInput(student_id=sid, role_slug=None)
    )

    assert out.found is False
    assert out.accessible_courses == []
    assert out.accessible_curated_problems == []
    assert out.accessible_notebooks == []
    assert out.content_schema_completeness == "minimal"


async def test_read_accessible_content_tributary_course_role_slug_null(
    session_on_contextvar: AsyncSession,
) -> None:
    """d12-smoke-course intentionally has role_id=NULL post-CP2b backfill."""
    sid = await _make_student(session_on_contextvar)
    await _seed_entitlement(session_on_contextvar, sid, "d12-smoke-course")

    out = await read_student_accessible_content(
        ReadStudentAccessibleContentInput(student_id=sid, role_slug=None)
    )

    assert out.found is True
    smoke_course = next(
        (c for c in out.accessible_courses if c.course_slug == "d12-smoke-course"),
        None,
    )
    assert smoke_course is not None
    assert smoke_course.role_slug is None


# ── evaluate_student_against_gate tests ───────────────────────────────


async def test_evaluate_gate_no_data_fails(
    session_on_contextvar: AsyncSession,
) -> None:
    sid = await _make_student(session_on_contextvar)
    await _seed_role_state(
        session_on_contextvar, sid, role_slug="python_developer"
    )

    out = await evaluate_student_against_gate(
        EvaluateStudentAgainstGateInput(
            student_id=sid, target_role_slug="data_analyst"
        )
    )

    assert out.gate_passable is False
    assert out.overall_passed is False
    assert out.capstone_status.passed is False
    assert out.capstone_status.best_score_observed is None
    assert out.mock_interview_status.passed is False
    assert out.mock_interview_status.sessions_passed_in_window == 0
    assert "no evaluated capstone" in out.gap_summary
    assert "mock interviews" in out.gap_summary


async def test_evaluate_gate_capstone_above_threshold_mocks_empty(
    session_on_contextvar: AsyncSession,
) -> None:
    """Capstone alone isn't enough — mocks must also pass.

    Seeds a 0.85 (= 85/100) capstone for python_developer. Threshold
    is 0.65; capstone side passes. Mocks empty so overall fails.
    """
    sid = await _make_student(session_on_contextvar)
    await _seed_role_state(
        session_on_contextvar, sid, role_slug="python_developer"
    )
    await _seed_capstone_submission(
        session_on_contextvar,
        sid,
        course_slug="python-foundations",
        score=85,
    )

    out = await evaluate_student_against_gate(
        EvaluateStudentAgainstGateInput(
            student_id=sid, target_role_slug="data_analyst"
        )
    )

    assert out.capstone_status.passed is True
    assert out.capstone_status.capstones_meeting_threshold == 1
    assert out.capstone_status.best_score_observed == pytest.approx(0.85, abs=1e-9)
    assert out.mock_interview_status.passed is False
    assert out.overall_passed is False


async def test_evaluate_gate_non_adjacent_raises(
    session_on_contextvar: AsyncSession,
) -> None:
    sid = await _make_student(session_on_contextvar)
    await _seed_role_state(
        session_on_contextvar, sid, role_slug="python_developer"
    )

    with pytest.raises(ValueError, match="non-adjacent"):
        await evaluate_student_against_gate(
            EvaluateStudentAgainstGateInput(
                student_id=sid, target_role_slug="data_scientist"
            )
        )


async def test_evaluate_gate_no_role_state_raises(
    session_on_contextvar: AsyncSession,
) -> None:
    bogus = uuid.uuid4()

    with pytest.raises(ValueError, match="no student_role_state"):
        await evaluate_student_against_gate(
            EvaluateStudentAgainstGateInput(
                student_id=bogus, target_role_slug="data_analyst"
            )
        )


async def test_evaluate_gate_terminal_role_raises(
    session_on_contextvar: AsyncSession,
) -> None:
    sid = await _make_student(session_on_contextvar)
    await _seed_role_state(
        session_on_contextvar, sid, role_slug="senior_genai_engineer"
    )

    with pytest.raises(ValueError, match="terminal role"):
        await evaluate_student_against_gate(
            EvaluateStudentAgainstGateInput(
                student_id=sid, target_role_slug="python_developer"
            )
        )


async def test_evaluate_gate_capstone_normalization(
    session_on_contextvar: AsyncSession,
) -> None:
    """A 64/100 score is BELOW 0.65 threshold; 65/100 is at the boundary;
    66/100 is above. Pin the score/100 normalization explicitly so a
    future schema change to a float-scaled column doesn't silently break.
    """
    sid = await _make_student(session_on_contextvar)
    await _seed_role_state(
        session_on_contextvar, sid, role_slug="python_developer"
    )
    await _seed_capstone_submission(
        session_on_contextvar,
        sid,
        course_slug="python-foundations",
        score=64,
    )

    out = await evaluate_student_against_gate(
        EvaluateStudentAgainstGateInput(
            student_id=sid, target_role_slug="data_analyst"
        )
    )

    assert out.capstone_status.best_score_observed == pytest.approx(0.64, abs=1e-9)
    assert out.capstone_status.capstones_meeting_threshold == 0
    assert out.capstone_status.passed is False
