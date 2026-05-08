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


async def seed_python_developer_with_curated_bank(
    session: AsyncSession,
    *,
    email_suffix: str | None = None,
    days_in_role: int = 6,
) -> SeededStudent:
    """python_developer student with access to the curated bank.

    Entitled to BOTH `python-developer` (the role-named course, no
    exercises) AND `python-foundations` (tributary, mapped to
    python_developer at CP2b, holds 32 exercises + 1 capstone).
    accessible_curated_problems is non-empty for this student — used
    by CP4 Phase 1 to verify practice_curator's bank-selection path.
    """
    user_id, email = await _insert_user(
        session,
        email_suffix=email_suffix,
        full_name="D15 CP4 Python Developer (with bank)",
    )
    started = datetime.now(UTC) - timedelta(days=days_in_role)
    role_id = await _upsert_role_state(
        session,
        student_id=user_id,
        role_slug="python_developer",
        role_started_at=started,
    )
    for slug in ("python-developer", "python-foundations"):
        await _grant_entitlement(session, student_id=user_id, course_slug=slug)
    return SeededStudent(
        user_id=user_id,
        email=email,
        full_name="D15 CP4 Python Developer (with bank)",
        current_role_slug="python_developer",
        current_role_id=role_id,
        entitled_course_slugs=["python-developer", "python-foundations"],
        transitions_completed_count=0,
    )


async def seed_ml_engineer_with_capstone_submission(
    session: AsyncSession,
    *,
    email_suffix: str | None = None,
    days_in_role: int = 22,
    capstone_score: int = 78,
) -> tuple[SeededStudent, str]:
    """ml_engineer student who has submitted the D12 CP3 RAG Capstone
    (intro-ai-engineering, genai_engineer-tagged, has rubric).

    The capstone's parent course is genai_engineer-tagged per CP2b
    backfill. The student is at ml_engineer, so:
      • role progression next = genai_engineer (sequence_order 4 → 5).
      • capstone is the gate's load-bearing artifact — submitting it
        is exactly the action the gate evaluates.
      • rubric is present (D14c CP3 verified), so D-E
        rubric_available=True path fires.
      • transition_gate_status populates with capstone_threshold=0.75.

    Returns (student, exercise_submissions.id). Used by CP4 Phase 3 to
    drive project_evaluator on a real capstone with the gate-context
    sections fully populated.
    """
    student = await seed_ml_engineer_for_gate_prep(
        session,
        email_suffix=email_suffix,
        days_in_role=days_in_role,
    )
    cap_row = (
        await session.execute(
            sql_text(
                """
                SELECT e.id
                FROM exercises e
                JOIN lessons l ON l.id = e.lesson_id
                JOIN courses c ON c.id = l.course_id
                WHERE c.slug = 'intro-ai-engineering'
                  AND e.is_capstone = TRUE
                  AND e.title = 'D12 CP3 RAG Capstone'
                LIMIT 1
                """
            )
        )
    ).first()
    if cap_row is None:
        raise RuntimeError("D12 CP3 RAG Capstone not found on dev DB")
    exercise_id = cap_row[0]

    submission_row = (
        await session.execute(
            sql_text(
                """
                INSERT INTO exercise_submissions
                    (id, student_id, exercise_id, status, score,
                     attempt_number, code, self_explanation)
                VALUES (
                    gen_random_uuid(), :sid, :eid, 'evaluated', :score,
                    1,
                    '# RAG implementation: hybrid retrieval + reranker\n'
                    'def retrieve(query, k=10):\n'
                    '    bm25_hits = bm25.search(query, k=k*2)\n'
                    '    dense_hits = vec.search(query, k=k*2)\n'
                    '    return rrf(bm25_hits, dense_hits, k=k)',
                    'I built a hybrid retrieval pipeline: BM25 for '
                    'lexical recall, dense embeddings (text-embedding-3) '
                    'for semantic, RRF fusion for ranking. Eval harness '
                    'measures recall@10 and answer fidelity on a held-out '
                    'set; production deploy uses FAISS HNSW for hot tier '
                    'and a managed vector DB for warm.'
                )
                RETURNING id
                """
            ),
            {"sid": student.user_id, "eid": exercise_id, "score": capstone_score},
        )
    ).first()
    if submission_row is None:
        raise RuntimeError("INSERT exercise_submissions returned no id")
    submission_id = str(submission_row[0])
    return student, submission_id


async def seed_ml_engineer_for_gate_prep(
    session: AsyncSession,
    *,
    email_suffix: str | None = None,
    days_in_role: int = 22,
) -> SeededStudent:
    """ml_engineer student preparing for the ml_engineer→genai_engineer gate.

    Entitled to ml-engineer + production-rag + intro-ai-engineering
    (the latter two are genai_engineer-tagged courses; entitled here
    so the student has read access to the genai-adjacent reference
    material while practicing the gate). Used by CP4 Phase 4 to
    verify mock_interview's gate-prep verdict path.
    """
    user_id, email = await _insert_user(
        session,
        email_suffix=email_suffix,
        full_name="D15 CP4 ML Engineer",
    )
    started = datetime.now(UTC) - timedelta(days=days_in_role)
    transitions = []
    for from_slug, to_slug, score in (
        ("python_developer", "data_analyst", 0.78),
        ("data_analyst", "data_scientist", 0.74),
        ("data_scientist", "ml_engineer", 0.76),
    ):
        transitions.append(
            {
                "from_slug": from_slug,
                "to_slug": to_slug,
                "completed_at": (
                    datetime.now(UTC) - timedelta(days=days_in_role + 30)
                ).isoformat(),
                "capstone_score": score,
                "mock_session_ids": [str(uuid.uuid4()), str(uuid.uuid4())],
            }
        )
    role_id = await _upsert_role_state(
        session,
        student_id=user_id,
        role_slug="ml_engineer",
        role_started_at=started,
        transitions_completed=transitions,
    )
    for slug in ("ml-engineer", "production-rag", "intro-ai-engineering"):
        await _grant_entitlement(session, student_id=user_id, course_slug=slug)
    return SeededStudent(
        user_id=user_id,
        email=email,
        full_name="D15 CP4 ML Engineer",
        current_role_slug="ml_engineer",
        current_role_id=role_id,
        entitled_course_slugs=[
            "ml-engineer",
            "production-rag",
            "intro-ai-engineering",
        ],
        transitions_completed_count=3,
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
    "seed_ml_engineer_for_gate_prep",
    "seed_ml_engineer_with_capstone_submission",
    "seed_python_developer_fresh",
    "seed_python_developer_with_curated_bank",
]
