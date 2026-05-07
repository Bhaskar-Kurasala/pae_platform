"""D15 CP3 — reusable role-state student seed pattern.

Three canonical fixtures, each callable from a pytest async test or
from a real-LLM verification script:

  * `seed_python_developer_fresh(session, *, email_suffix=None)` —
    student at python_developer with 0 capstones, 0 mock sessions,
    entitled to python-developer course only.

  * `seed_mid_progression_data_scientist(session, ...)` — student at
    data_scientist after completing two transitions (python_developer
    → data_analyst → data_scientist). Entitled to python-developer +
    data-analyst + data-scientist + python-foundations. 0 capstones
    for the CURRENT role, since current role's capstones are what
    gate the move OUT.

  * `seed_data_analyst_with_entitlement(session, ...)` — student at
    data_analyst with entitlement to data-analyst course only. Used
    for study_planner runtime grounding tests.

Each helper returns a `SeededStudent` dataclass with ids the caller
can pass to the role-state tools and to call_agent payloads.

D16 + Playwright reuse these helpers to drive verification scenarios
against the same canonical states.

Notes on data conventions:

  * email_suffix lets multiple test runs coexist; default is uuid4.
  * The helpers DO NOT commit; the caller controls transaction
    boundaries (test rollback fixture, or script-level commit). This
    is the same convention as D14c CP3's setup_user_and_entitlement.
  * Capstone seeding is intentionally absent — CP3 phases verify the
    "no capstone" gap path. Use seed_capstone_submission from the
    smoke-test helpers when you need a graded capstone.
  * Mock-interview seeding is also absent — CP4 will populate
    output_data.session_verdict; CP3 phases verify the
    sessions_passed=0 fallback path explicitly.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class SeededStudent:
    """Identifiers for a seeded test student.

    Returned by every seed_* helper so callers can pass these into
    role-state tools, call_agent payloads, and assertion lookups
    without re-querying.
    """

    user_id: uuid.UUID
    email: str
    full_name: str
    current_role_slug: str
    current_role_id: uuid.UUID
    entitled_course_slugs: list[str] = field(default_factory=list)
    transitions_completed_count: int = 0


# ── Internal helpers ──────────────────────────────────────────────────


async def _get_role_id(session: AsyncSession, slug: str) -> uuid.UUID:
    return (
        await session.execute(
            sql_text("SELECT id FROM roles WHERE slug = :s"),
            {"s": slug},
        )
    ).scalar_one()


async def _get_course_id(session: AsyncSession, slug: str) -> uuid.UUID:
    return (
        await session.execute(
            sql_text("SELECT id FROM courses WHERE slug = :s"),
            {"s": slug},
        )
    ).scalar_one()


async def _insert_user(
    session: AsyncSession,
    *,
    email_suffix: str | None,
    full_name: str,
) -> tuple[uuid.UUID, str]:
    sid = uuid.uuid4()
    suffix = email_suffix or sid.hex[:12]
    email = f"d15-cp3-{suffix}@test.invalid"
    await session.execute(
        sql_text(
            "INSERT INTO users (id, email, full_name, hashed_password, "
            "is_active, is_verified, role) "
            "VALUES (:id, :email, :name, 'x', TRUE, FALSE, 'student')"
        ),
        {"id": sid, "email": email, "name": full_name},
    )
    return sid, email


async def _upsert_role_state(
    session: AsyncSession,
    *,
    student_id: uuid.UUID,
    role_slug: str,
    role_started_at: datetime | None = None,
    transitions_completed: list[dict] | None = None,
) -> uuid.UUID:
    role_id = await _get_role_id(session, role_slug)
    started = role_started_at or datetime.now(UTC)
    completed_json = json.dumps(transitions_completed or [])
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
    return role_id


async def _grant_entitlement(
    session: AsyncSession,
    *,
    student_id: uuid.UUID,
    course_slug: str,
    source: str = "free",
) -> None:
    course_id = await _get_course_id(session, course_slug)
    await session.execute(
        sql_text(
            "INSERT INTO course_entitlements "
            "(id, user_id, course_id, source) "
            "VALUES (gen_random_uuid(), :uid, :cid, :src)"
        ),
        {"uid": student_id, "cid": course_id, "src": source},
    )


# ── Canonical seed helpers ────────────────────────────────────────────


async def seed_python_developer_fresh(
    session: AsyncSession,
    *,
    email_suffix: str | None = None,
    days_in_role: int = 12,
) -> SeededStudent:
    """Fresh python_developer student.

    Entitled to python-developer (the role-named course only). Zero
    capstones, zero mock sessions, zero completed transitions.
    Used by CP3 Phase 1 to verify career_coach refuses Senior GenAI
    application requests at this readiness state.
    """
    user_id, email = await _insert_user(
        session,
        email_suffix=email_suffix,
        full_name="D15 CP3 Python Developer",
    )
    started = datetime.now(UTC) - timedelta(days=days_in_role)
    role_id = await _upsert_role_state(
        session,
        student_id=user_id,
        role_slug="python_developer",
        role_started_at=started,
    )
    await _grant_entitlement(
        session, student_id=user_id, course_slug="python-developer"
    )
    return SeededStudent(
        user_id=user_id,
        email=email,
        full_name="D15 CP3 Python Developer",
        current_role_slug="python_developer",
        current_role_id=role_id,
        entitled_course_slugs=["python-developer"],
        transitions_completed_count=0,
    )


async def seed_mid_progression_data_scientist(
    session: AsyncSession,
    *,
    email_suffix: str | None = None,
    days_in_role: int = 30,
) -> SeededStudent:
    """Mid-progression student at data_scientist.

    Has completed two transitions (python_developer → data_analyst,
    data_analyst → data_scientist). Entitled to all four foundational
    courses (python-developer, python-foundations, data-analyst,
    data-scientist). Zero capstones for the CURRENT (data_scientist)
    role, since data_scientist's capstone is what gates the move to
    ml_engineer — the gap CP3 Phase 2 verifies career_coach surfaces.
    """
    user_id, email = await _insert_user(
        session,
        email_suffix=email_suffix,
        full_name="D15 CP3 Data Scientist",
    )
    started = datetime.now(UTC) - timedelta(days=days_in_role)

    # Two completed transitions on the trajectory.
    transitions = [
        {
            "from_slug": "python_developer",
            "to_slug": "data_analyst",
            "completed_at": (
                datetime.now(UTC) - timedelta(days=days_in_role + 60)
            ).isoformat(),
            "capstone_score": 0.82,
            "mock_session_ids": [str(uuid.uuid4()), str(uuid.uuid4())],
        },
        {
            "from_slug": "data_analyst",
            "to_slug": "data_scientist",
            "completed_at": (
                datetime.now(UTC) - timedelta(days=days_in_role + 1)
            ).isoformat(),
            "capstone_score": 0.78,
            "mock_session_ids": [str(uuid.uuid4()), str(uuid.uuid4())],
        },
    ]

    role_id = await _upsert_role_state(
        session,
        student_id=user_id,
        role_slug="data_scientist",
        role_started_at=started,
        transitions_completed=transitions,
    )

    for slug in (
        "python-developer",
        "python-foundations",
        "data-analyst",
        "data-scientist",
    ):
        await _grant_entitlement(session, student_id=user_id, course_slug=slug)

    return SeededStudent(
        user_id=user_id,
        email=email,
        full_name="D15 CP3 Data Scientist",
        current_role_slug="data_scientist",
        current_role_id=role_id,
        entitled_course_slugs=[
            "python-developer",
            "python-foundations",
            "data-analyst",
            "data-scientist",
        ],
        transitions_completed_count=2,
    )


async def seed_data_analyst_with_entitlement(
    session: AsyncSession,
    *,
    email_suffix: str | None = None,
    days_in_role: int = 8,
) -> SeededStudent:
    """data_analyst student with role-appropriate entitlement.

    Entitled to data-analyst course only (the role-named one) —
    deliberately excludes data-analyst-path tributary so the
    accessible-content state is partial-but-clean. Used by CP3
    Phase 3 (study_planner role grounding) and Phase 4 (urgency
    override).
    """
    user_id, email = await _insert_user(
        session,
        email_suffix=email_suffix,
        full_name="D15 CP3 Data Analyst",
    )
    started = datetime.now(UTC) - timedelta(days=days_in_role)
    role_id = await _upsert_role_state(
        session,
        student_id=user_id,
        role_slug="data_analyst",
        role_started_at=started,
        transitions_completed=[
            {
                "from_slug": "python_developer",
                "to_slug": "data_analyst",
                "completed_at": (
                    datetime.now(UTC) - timedelta(days=days_in_role + 1)
                ).isoformat(),
                "capstone_score": 0.71,
                "mock_session_ids": [str(uuid.uuid4()), str(uuid.uuid4())],
            }
        ],
    )
    await _grant_entitlement(
        session, student_id=user_id, course_slug="data-analyst"
    )
    return SeededStudent(
        user_id=user_id,
        email=email,
        full_name="D15 CP3 Data Analyst",
        current_role_slug="data_analyst",
        current_role_id=role_id,
        entitled_course_slugs=["data-analyst"],
        transitions_completed_count=1,
    )


__all__ = [
    "SeededStudent",
    "seed_data_analyst_with_entitlement",
    "seed_mid_progression_data_scientist",
    "seed_python_developer_fresh",
]
