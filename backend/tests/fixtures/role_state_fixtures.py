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


# ── D17b/ITEM 3 lead-in signal seed helpers ──────────────────────────
#
# These extend the canonical role-state seeders with the additional
# state required by read_student_lead_in_signals: student_risk_signals
# (slip_type + days_since_last_session), agent_actions
# (mock_interview verdicts), and learning_sessions (activity proxy).
#
# Each helper composes on top of one of the existing canonical seeders
# (e.g., data_analyst_with_entitlement) so the role-progression
# context is always coherent. The helpers do NOT commit; the caller
# controls transactions.


async def _seed_risk_signal(
    session: AsyncSession,
    *,
    student_id: uuid.UUID,
    slip_type: str,
    days_since_last_session: int | None,
    risk_score: int = 50,
) -> None:
    """Insert/update student_risk_signals. id is NOT NULL with no DB
    default — supply explicitly."""
    await session.execute(
        sql_text(
            """
            INSERT INTO student_risk_signals
              (id, user_id, slip_type, risk_score,
               days_since_last_session, max_streak_ever, paid)
            VALUES (:id, :uid, :slip, :score, :days, 0, FALSE)
            ON CONFLICT (user_id) DO UPDATE
            SET slip_type = EXCLUDED.slip_type,
                risk_score = EXCLUDED.risk_score,
                days_since_last_session =
                  EXCLUDED.days_since_last_session
            """
        ),
        {
            "id": uuid.uuid4(),
            "uid": student_id,
            "slip": slip_type,
            "score": risk_score,
            "days": days_since_last_session,
        },
    )


async def _seed_passing_mock_action(
    session: AsyncSession,
    *,
    student_id: uuid.UUID,
    hours_ago: int,
    target_role_slug: str = "data_analyst",
) -> None:
    """Insert an agent_actions row simulating a passing mock_interview.

    The aggregator filters on
    output_data['session_verdict']['passed']=true. action_type is
    NOT NULL on agent_actions; supply 'execute'.
    """
    output = {
        "session_verdict": {
            "passed": True,
            "transition_target": {"to_role_slug": target_role_slug},
        }
    }
    when = datetime.now(UTC) - timedelta(hours=hours_ago)
    await session.execute(
        sql_text(
            """
            INSERT INTO agent_actions
              (id, agent_name, student_id, action_type, status,
               output_data, created_at)
            VALUES
              (:id, 'mock_interview', :sid, 'execute', 'completed',
               CAST(:out AS JSONB), :ts)
            """
        ),
        {
            "id": uuid.uuid4(),
            "sid": student_id,
            "out": json.dumps(output),
            "ts": when,
        },
    )


async def _seed_learning_session(
    session: AsyncSession,
    *,
    student_id: uuid.UUID,
    days_ago: int,
    ordinal: int,
) -> None:
    """Insert a learning_sessions row at days_ago from now. Distinct
    days within the 7-day window drive the recent_activity_days_count_7d
    aggregator output."""
    when = datetime.now(UTC) - timedelta(days=days_ago)
    await session.execute(
        sql_text(
            """
            INSERT INTO learning_sessions
              (id, user_id, ordinal, started_at, created_at)
            VALUES (:id, :uid, :ord, :ts, :ts)
            """
        ),
        {
            "id": uuid.uuid4(),
            "uid": student_id,
            "ord": ordinal,
            "ts": when,
        },
    )


async def seed_returning_after_absence_data_analyst(
    session: AsyncSession,
    *,
    email_suffix: str | None = None,
    days_absent: int = 7,
) -> SeededStudent:
    """data_analyst student who hasn't logged in for `days_absent` days.

    Triggers career_coach + study_planner Rule 1
    (days_since_last_session >= 5 → returning-after-absence framing).
    """
    base = await seed_data_analyst_with_entitlement(
        session, email_suffix=email_suffix
    )
    # No active slip — just absence. F1 would normally classify as
    # cold_signup or similar but for this test we want pure-absence.
    await _seed_risk_signal(
        session,
        student_id=base.user_id,
        slip_type="none",
        days_since_last_session=days_absent,
    )
    return base


async def seed_just_passed_mock_data_scientist(
    session: AsyncSession,
    *,
    email_suffix: str | None = None,
    mock_hours_ago: int = 6,
) -> SeededStudent:
    """data_scientist who passed a mock_interview within the last
    `mock_hours_ago` hours.

    Triggers career_coach Rule 2 (mock pass within 24h →
    mock-progress framing).
    """
    base = await seed_mid_progression_data_scientist(
        session, email_suffix=email_suffix
    )
    await _seed_passing_mock_action(
        session,
        student_id=base.user_id,
        hours_ago=mock_hours_ago,
        target_role_slug="ml_engineer",
    )
    # Recent activity so absence framing doesn't also fire.
    await _seed_risk_signal(
        session,
        student_id=base.user_id,
        slip_type="none",
        days_since_last_session=1,
    )
    return base


async def seed_just_cleared_gate_data_analyst(
    session: AsyncSession,
    *,
    email_suffix: str | None = None,
    transition_hours_ago: int = 24,
) -> SeededStudent:
    """data_analyst who cleared the python_developer → data_analyst
    transition within the last `transition_hours_ago` hours.

    Triggers career_coach Rule 3 (transition within 48h →
    gate-cleared celebration framing). The base helper already seeds
    a transitions_completed entry; this helper overrides its
    completed_at to a fresh timestamp.
    """
    base = await seed_data_analyst_with_entitlement(
        session, email_suffix=email_suffix
    )
    # Override transitions_completed with a recent completed_at
    transitions = [
        {
            "from_slug": "python_developer",
            "to_slug": "data_analyst",
            "completed_at": (
                datetime.now(UTC) - timedelta(hours=transition_hours_ago)
            ).isoformat(),
            "capstone_score": 0.78,
            "mock_session_ids": [str(uuid.uuid4()), str(uuid.uuid4())],
        }
    ]
    await session.execute(
        sql_text(
            """
            UPDATE student_role_state
            SET transitions_completed = CAST(:completed AS JSONB)
            WHERE student_id = :sid
            """
        ),
        {"sid": base.user_id, "completed": json.dumps(transitions)},
    )
    await _seed_risk_signal(
        session,
        student_id=base.user_id,
        slip_type="none",
        days_since_last_session=1,
    )
    return base


async def seed_healthy_data_analyst(
    session: AsyncSession,
    *,
    email_suffix: str | None = None,
) -> SeededStudent:
    """data_analyst with no signals warranting a lead-in.

    Control fixture — verifies prompts default to no-lead-in when
    none of Rules 1-3 match (career_coach) and no stalled/momentum
    signal triggers (study_planner). Active recent (1 day ago) so no
    absence; no slip; no recent transition (uses base helper's
    days_in_role+1 backdate); no recent mock pass.
    """
    base = await seed_data_analyst_with_entitlement(
        session, email_suffix=email_suffix
    )
    await _seed_risk_signal(
        session,
        student_id=base.user_id,
        slip_type="none",
        days_since_last_session=1,
    )
    return base


async def seed_stalled_data_analyst(
    session: AsyncSession,
    *,
    email_suffix: str | None = None,
) -> SeededStudent:
    """data_analyst with current_slip_type='capstone_stalled'.

    Triggers study_planner Rule 1 (stalled → walk-through framing).
    Caller-supplied days_since_last_session=2 so absence doesn't
    also fire; the prompt's priority order picks stalled either way
    (stalled > returning > momentum) but explicit avoids ambiguity.
    """
    base = await seed_data_analyst_with_entitlement(
        session, email_suffix=email_suffix
    )
    await _seed_risk_signal(
        session,
        student_id=base.user_id,
        slip_type="capstone_stalled",
        days_since_last_session=2,
        risk_score=72,
    )
    return base


async def seed_momentum_data_analyst(
    session: AsyncSession,
    *,
    email_suffix: str | None = None,
) -> SeededStudent:
    """data_analyst with 4 distinct active days in the last 7.

    Triggers study_planner Rule 3 (momentum proxy: >=3 active days
    in last 7 AND no slip → momentum framing). No slip; recent
    activity present.
    """
    base = await seed_data_analyst_with_entitlement(
        session, email_suffix=email_suffix
    )
    # 4 distinct days within the 7-day window
    for i, days_ago in enumerate([0, 1, 3, 5]):
        await _seed_learning_session(
            session,
            student_id=base.user_id,
            days_ago=days_ago,
            ordinal=i + 1,
        )
    await _seed_risk_signal(
        session,
        student_id=base.user_id,
        slip_type="none",
        days_since_last_session=0,
    )
    return base


# ── D18 Phase A CP4 — admin / payment / capstone-submission /
# passing-mock-session / outreach seeders ──────────────────────────────
#
# Five new seed helpers added at CP4. Like the D15+D17b helpers, none
# of these commit; the caller controls the transaction. These are the
# building blocks for journey_fixtures.py composites.


@dataclass
class SeededAdmin:
    """Identifiers for a seeded admin user."""

    user_id: uuid.UUID
    email: str
    full_name: str
    role: str = "admin"


async def seed_admin_user(
    session: AsyncSession,
    *,
    email_suffix: str | None = None,
    full_name: str = "D18 CP4 Admin",
    hashed_password: str = "x",
) -> SeededAdmin:
    """Seed an admin user via direct DB insert.

    The hashed_password default ('x') is a placeholder — login via
    HTTP requires a real bcrypt hash. admin_fixtures.py provides an
    alternate seed path that goes through the API register flow so
    the resulting admin can authenticate.

    Pydantic email-validator rejects .invalid/.test/.local; this
    helper uses example.com (RFC 6761 reserved-for-documentation,
    never resolves) so the same user can also flow through HTTP
    paths if needed.
    """
    sid = uuid.uuid4()
    suffix = email_suffix or sid.hex[:12]
    email = f"d18-cp4-admin-{suffix}@example.com"
    await session.execute(
        sql_text(
            "INSERT INTO users (id, email, full_name, hashed_password, "
            "is_active, is_verified, role) "
            "VALUES (:id, :email, :name, :pw, TRUE, TRUE, 'admin')"
        ),
        {"id": sid, "email": email, "name": full_name, "pw": hashed_password},
    )
    return SeededAdmin(user_id=sid, email=email, full_name=full_name)


@dataclass
class SeededPayment:
    """Identifiers for a seeded payments row."""

    payment_id: uuid.UUID
    user_id: uuid.UUID
    amount_cents: int
    status: str


async def seed_payment_intent(
    session: AsyncSession,
    *,
    student_id: uuid.UUID,
    amount_cents: int = 9900,
    status: str = "succeeded",
    currency: str = "inr",
) -> SeededPayment:
    """Seed a payments row for retention/billing tests.

    Default amount is ₹99 (cents). Status defaults to 'succeeded' —
    realistic for paid-but-stalled fixtures; tests that need
    pending/failed override.

    course_id is left NULL — journey fixtures generally don't pin a
    payment to a specific course (entitlement does that work).
    """
    pid = uuid.uuid4()
    await session.execute(
        sql_text(
            """
            INSERT INTO payments
              (id, user_id, amount_cents, currency, status,
               payment_method, created_at, updated_at)
            VALUES
              (:id, :uid, :amt, :cur, :st, 'card', now(), now())
            """
        ),
        {
            "id": pid,
            "uid": student_id,
            "amt": amount_cents,
            "cur": currency,
            "st": status,
        },
    )
    return SeededPayment(
        payment_id=pid,
        user_id=student_id,
        amount_cents=amount_cents,
        status=status,
    )


@dataclass
class SeededCapstoneSubmission:
    """Identifiers for a seeded capstone exercise submission."""

    submission_id: uuid.UUID
    student_id: uuid.UUID
    exercise_id: uuid.UUID
    score: int | None
    status: str


async def _ensure_capstone_exercise(
    session: AsyncSession,
    *,
    course_slug: str = "data-analyst",
) -> uuid.UUID:
    """Find a real is_capstone=TRUE exercise tied to course_slug,
    or create one if none exists.

    The playwright_test template seeds 11 catalog courses but no
    lessons/exercises; CP4 fixtures need a real capstone-exercise
    row to anchor submissions. We create one lazily and reuse it
    across the run (a single capstone-exercise row supports many
    submissions; that's the natural data shape).
    """
    exercise_id = (
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
    ).scalar_one_or_none()
    if exercise_id is not None:
        return exercise_id

    course_id = (
        await session.execute(
            sql_text("SELECT id FROM courses WHERE slug = :s"),
            {"s": course_slug},
        )
    ).scalar_one()

    # `order` is a reserved word in Postgres — must quote. Pre-flight
    # was wrong: schema column is `order` (not `position`). Caught at
    # CP4 smoke; documented in cleanup.py's pg_constraint discipline
    # note.
    lesson_id = uuid.uuid4()
    await session.execute(
        sql_text(
            """
            INSERT INTO lessons (id, course_id, title, slug, "order",
                                 created_at, updated_at)
            VALUES (:id, :cid, 'CP4 capstone harness lesson',
                    :sl, 9999, now(), now())
            """
        ),
        {"id": lesson_id, "cid": course_id, "sl": f"cp4-capstone-{lesson_id.hex[:8]}"},
    )

    new_id = uuid.uuid4()
    await session.execute(
        sql_text(
            """
            INSERT INTO exercises
              (id, lesson_id, title, description, is_capstone,
               "order", created_at, updated_at)
            VALUES
              (:id, :lid, 'CP4 capstone harness exercise',
               'Test fixture capstone for CP4', TRUE, 9999,
               now(), now())
            """
        ),
        {"id": new_id, "lid": lesson_id},
    )
    return new_id


async def seed_capstone_submission(
    session: AsyncSession,
    *,
    student_id: uuid.UUID,
    course_slug: str = "data-analyst",
    score: int | None = 85,
    status: str = "graded",
    code: str = "# CP4 fixture capstone submission\nprint('hello')\n",
) -> SeededCapstoneSubmission:
    """Seed an exercise_submissions row against a real capstone exercise.

    Resolves a capstone exercise on `course_slug` (creates one if the
    template doesn't have any). Default score=85 = passing-grade
    semantics; pass score=None for an ungraded draft.
    """
    exercise_id = await _ensure_capstone_exercise(session, course_slug=course_slug)
    sub_id = uuid.uuid4()
    await session.execute(
        sql_text(
            """
            INSERT INTO exercise_submissions
              (id, student_id, exercise_id, code, status, score,
               attempt_number, created_at, updated_at)
            VALUES
              (:id, :sid, :eid, :code, :status, :score, 1, now(), now())
            """
        ),
        {
            "id": sub_id,
            "sid": student_id,
            "eid": exercise_id,
            "code": code,
            "status": status,
            "score": score,
        },
    )
    return SeededCapstoneSubmission(
        submission_id=sub_id,
        student_id=student_id,
        exercise_id=exercise_id,
        score=score,
        status=status,
    )


async def seed_passing_mock_session(
    session: AsyncSession,
    *,
    student_id: uuid.UUID,
    target_role_slug: str = "data_analyst",
    hours_ago: int = 24,
    dimension_scores: dict[str, float] | None = None,
) -> uuid.UUID:
    """Seed a passing mock interview signal.

    The retention/gate aggregator filters on
    agent_actions.output_data.session_verdict.passed=true for
    "passed mock" semantics; that's where this writes. Mirrors the
    private `_seed_passing_mock_action` helper used by D17b lead-in
    fixtures (kept private; this is the public CP4 surface).

    Returns the agent_actions row id.
    """
    if dimension_scores is None:
        dimension_scores = {
            "code_quality": 0.85,
            "problem_solving": 0.82,
            "communication": 0.80,
            "domain_depth": 0.78,
        }
    output = {
        "session_verdict": {
            "passed": True,
            "transition_target": {"to_role_slug": target_role_slug},
            "dimension_scores": dimension_scores,
        }
    }
    when = datetime.now(UTC) - timedelta(hours=hours_ago)
    aid = uuid.uuid4()
    await session.execute(
        sql_text(
            """
            INSERT INTO agent_actions
              (id, agent_name, student_id, action_type, status,
               output_data, created_at)
            VALUES
              (:id, 'mock_interview', :sid, 'execute', 'completed',
               CAST(:out AS JSONB), :ts)
            """
        ),
        {
            "id": aid,
            "sid": student_id,
            "out": json.dumps(output),
            "ts": when,
        },
    )
    return aid


async def seed_outreach_log_entry(
    session: AsyncSession,
    *,
    student_id: uuid.UUID,
    channel: str,
    triggered_by: str = "system",
    triggered_by_user_id: uuid.UUID | None = None,
    status: str = "delivered",
    body_preview: str | None = None,
    sent_hours_ago: int = 1,
    template_key: str | None = None,
    slip_type: str | None = None,
) -> uuid.UUID:
    """Seed an outreach_log row.

    `channel` ∈ {'email', 'in_app', 'whatsapp', 'phone', 'sms'}.
    `triggered_by` ∈ {'system', 'admin'} — admin-triggered rows
    should also pass `triggered_by_user_id`.

    Returns the new row id.
    """
    rid = uuid.uuid4()
    when = datetime.now(UTC) - timedelta(hours=sent_hours_ago)
    await session.execute(
        sql_text(
            """
            INSERT INTO outreach_log
              (id, user_id, channel, template_key, slip_type,
               triggered_by, triggered_by_user_id, sent_at,
               body_preview, status)
            VALUES
              (:id, :uid, :ch, :tk, :slip, :tb, :tbu, :sent,
               :body, :st)
            """
        ),
        {
            "id": rid,
            "uid": student_id,
            "ch": channel,
            "tk": template_key,
            "slip": slip_type,
            "tb": triggered_by,
            "tbu": triggered_by_user_id,
            "sent": when,
            "body": body_preview,
            "st": status,
        },
    )
    return rid


__all__ = [
    "SeededAdmin",
    "SeededCapstoneSubmission",
    "SeededPayment",
    "SeededStudent",
    "seed_admin_user",
    "seed_capstone_submission",
    "seed_data_analyst_with_entitlement",
    "seed_healthy_data_analyst",
    "seed_just_cleared_gate_data_analyst",
    "seed_just_passed_mock_data_scientist",
    "seed_mid_progression_data_scientist",
    "seed_ml_engineer_for_gate_prep",
    "seed_ml_engineer_with_capstone_submission",
    "seed_momentum_data_analyst",
    "seed_outreach_log_entry",
    "seed_passing_mock_session",
    "seed_payment_intent",
    "seed_python_developer_fresh",
    "seed_python_developer_with_curated_bank",
    "seed_returning_after_absence_data_analyst",
    "seed_stalled_data_analyst",
]
