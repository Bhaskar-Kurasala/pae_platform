"""D15 CP1 — model invariants for the role progression schema.

These tests pin the SQLAlchemy model contract using the in-memory SQLite
fixture (`db_session`). They cover:

  * Tables register on Base.metadata (so create_all wires them up)
  * FK shapes resolve (no typos, no use_alter required)
  * Required columns enforce nullability via the model layer
  * UNIQUE on slug, sequence_order, (from_role_id, to_role_id),
    student_id is enforceable end-to-end
  * JSONB columns round-trip dicts/lists cleanly under the SQLite shim
  * Slug constants stay in lockstep with `ROLE_SLUGS_IN_ORDER`

Live-DB seed verification (six rows in `roles`, five in
`role_transitions`, 129 backfilled `student_role_state`) lives at
`tests/test_infra/test_role_seed.py` because that's a Postgres-only
property of the deployed migration, not a SQLAlchemy model property.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.role import (
    ROLE_SLUG_DATA_ANALYST,
    ROLE_SLUG_DATA_SCIENTIST,
    ROLE_SLUG_GENAI_ENGINEER,
    ROLE_SLUG_ML_ENGINEER,
    ROLE_SLUG_PYTHON_DEVELOPER,
    ROLE_SLUG_SENIOR_GENAI_ENGINEER,
    ROLE_SLUGS_IN_ORDER,
    Role,
    RoleTransition,
    StudentRoleState,
)
from app.models.user import User


SIX_ROLES: list[tuple[str, str, int, bool]] = [
    (ROLE_SLUG_PYTHON_DEVELOPER, "Python Developer", 1, False),
    (ROLE_SLUG_DATA_ANALYST, "Data Analyst", 2, False),
    (ROLE_SLUG_DATA_SCIENTIST, "Data Scientist", 3, False),
    (ROLE_SLUG_ML_ENGINEER, "ML Engineer", 4, False),
    (ROLE_SLUG_GENAI_ENGINEER, "GenAI Engineer", 5, False),
    (ROLE_SLUG_SENIOR_GENAI_ENGINEER, "Senior GenAI Engineer", 6, True),
]

STANDARD_DIMS: dict[str, float] = {
    "clarity_of_questioning": 0.20,
    "directional_adherence": 0.30,
    "complexity_adaptation": 0.25,
    "technical_correctness": 0.25,
}


async def _seed_six_roles(db: AsyncSession) -> dict[str, Role]:
    """Helper: build the six-role identity sequence in test DB."""
    roles: dict[str, Role] = {}
    for slug, display, order, terminal in SIX_ROLES:
        r = Role(
            slug=slug,
            display_name=display,
            description=f"identity statement for {slug}",
            sequence_order=order,
            is_terminal=terminal,
        )
        db.add(r)
        roles[slug] = r
    await db.commit()
    for r in roles.values():
        await db.refresh(r)
    return roles


async def _seed_five_transitions(
    db: AsyncSession, roles: dict[str, Role]
) -> list[RoleTransition]:
    pairs = [
        (ROLE_SLUG_PYTHON_DEVELOPER, ROLE_SLUG_DATA_ANALYST, 0.65, 1),
        (ROLE_SLUG_DATA_ANALYST, ROLE_SLUG_DATA_SCIENTIST, 0.70, 1),
        (ROLE_SLUG_DATA_SCIENTIST, ROLE_SLUG_ML_ENGINEER, 0.72, 1),
        (ROLE_SLUG_ML_ENGINEER, ROLE_SLUG_GENAI_ENGINEER, 0.75, 1),
        (ROLE_SLUG_GENAI_ENGINEER, ROLE_SLUG_SENIOR_GENAI_ENGINEER, 0.80, 2),
    ]
    transitions: list[RoleTransition] = []
    for from_slug, to_slug, threshold, capstone_count in pairs:
        rt = RoleTransition(
            from_role_id=roles[from_slug].id,
            to_role_id=roles[to_slug].id,
            capstone_threshold=threshold,
            capstone_count_required=capstone_count,
            mock_interview_dimensions=STANDARD_DIMS,
            mock_interview_pass_threshold=threshold,
        )
        db.add(rt)
        transitions.append(rt)
    await db.commit()
    return transitions


async def _seed_user(db: AsyncSession) -> User:
    user = User(
        email=f"{uuid.uuid4()}@test.local",
        full_name="Role Test User",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


# ── Role model ────────────────────────────────────────────────────────


async def test_role_model_persists_with_required_fields(
    db_session: AsyncSession,
) -> None:
    """Six roles seed cleanly; sequence_order is unique per row."""
    roles = await _seed_six_roles(db_session)
    assert set(roles.keys()) == set(ROLE_SLUGS_IN_ORDER)

    rows = (
        await db_session.execute(select(Role).order_by(Role.sequence_order))
    ).scalars().all()
    assert [r.slug for r in rows] == ROLE_SLUGS_IN_ORDER
    assert [r.sequence_order for r in rows] == [1, 2, 3, 4, 5, 6]


async def test_role_only_terminal_is_senior_genai_engineer(
    db_session: AsyncSession,
) -> None:
    """is_terminal flag matches founder seed: only senior_genai_engineer."""
    roles = await _seed_six_roles(db_session)
    terminals = [r for r in roles.values() if r.is_terminal]
    assert len(terminals) == 1
    assert terminals[0].slug == ROLE_SLUG_SENIOR_GENAI_ENGINEER


async def test_role_slug_uniqueness_enforced(db_session: AsyncSession) -> None:
    """Two roles with the same slug must not coexist."""
    db_session.add(
        Role(
            slug=ROLE_SLUG_PYTHON_DEVELOPER,
            display_name="A",
            description="d",
            sequence_order=1,
        )
    )
    await db_session.commit()
    db_session.add(
        Role(
            slug=ROLE_SLUG_PYTHON_DEVELOPER,
            display_name="B",
            description="d",
            sequence_order=2,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_role_sequence_order_uniqueness_enforced(
    db_session: AsyncSession,
) -> None:
    """Two roles with the same sequence_order must not coexist."""
    db_session.add(
        Role(
            slug="role_a",
            display_name="A",
            description="d",
            sequence_order=1,
        )
    )
    await db_session.commit()
    db_session.add(
        Role(
            slug="role_b",
            display_name="B",
            description="d",
            sequence_order=1,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_role_slugs_constant_matches_seed_order(
    db_session: AsyncSession,
) -> None:
    """ROLE_SLUGS_IN_ORDER stays in lockstep with the canonical seed."""
    assert ROLE_SLUGS_IN_ORDER == [slug for slug, _, _, _ in SIX_ROLES]
    # Lengths match D-A: six roles, no skipping.
    assert len(ROLE_SLUGS_IN_ORDER) == 6


# ── RoleTransition model ──────────────────────────────────────────────


async def test_five_transitions_persist_with_correct_pairs(
    db_session: AsyncSession,
) -> None:
    """Five transitions connect adjacent roles in the canonical sequence."""
    roles = await _seed_six_roles(db_session)
    await _seed_five_transitions(db_session, roles)

    rows = (
        await db_session.execute(select(RoleTransition))
    ).scalars().all()
    assert len(rows) == 5

    # Build slug → slug pairs and verify each connects sequential roles.
    by_id = {r.id: r for r in roles.values()}
    pairs = sorted(
        (by_id[rt.from_role_id].sequence_order, by_id[rt.to_role_id].sequence_order)
        for rt in rows
    )
    assert pairs == [(1, 2), (2, 3), (3, 4), (4, 5), (5, 6)]


async def test_transition_dimension_weights_sum_to_one(
    db_session: AsyncSession,
) -> None:
    """All transitions share the standard rubric; weights sum to 1.0."""
    roles = await _seed_six_roles(db_session)
    await _seed_five_transitions(db_session, roles)

    rows = (await db_session.execute(select(RoleTransition))).scalars().all()
    for rt in rows:
        weights = list(rt.mock_interview_dimensions.values())
        assert pytest.approx(sum(weights), abs=1e-9) == 1.0


async def test_transition_pair_uniqueness_enforced(
    db_session: AsyncSession,
) -> None:
    """A second transition for the same (from, to) pair is rejected."""
    roles = await _seed_six_roles(db_session)
    await _seed_five_transitions(db_session, roles)

    db_session.add(
        RoleTransition(
            from_role_id=roles[ROLE_SLUG_PYTHON_DEVELOPER].id,
            to_role_id=roles[ROLE_SLUG_DATA_ANALYST].id,
            capstone_threshold=0.5,
            mock_interview_dimensions=STANDARD_DIMS,
            mock_interview_pass_threshold=0.5,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_transition_thresholds_within_unit_range(
    db_session: AsyncSession,
) -> None:
    """All seeded thresholds are within [0.0, 1.0]."""
    roles = await _seed_six_roles(db_session)
    await _seed_five_transitions(db_session, roles)

    rows = (await db_session.execute(select(RoleTransition))).scalars().all()
    for rt in rows:
        assert 0.0 <= rt.capstone_threshold <= 1.0
        assert 0.0 <= rt.mock_interview_pass_threshold <= 1.0
        assert rt.capstone_count_required >= 1


async def test_transition_capstone_count_two_only_for_terminal_gate(
    db_session: AsyncSession,
) -> None:
    """Only the genai_engineer → senior_genai_engineer gate requires 2 capstones."""
    roles = await _seed_six_roles(db_session)
    await _seed_five_transitions(db_session, roles)

    rows = (await db_session.execute(select(RoleTransition))).scalars().all()
    by_id = {r.id: r for r in roles.values()}
    for rt in rows:
        from_slug = by_id[rt.from_role_id].slug
        if from_slug == ROLE_SLUG_GENAI_ENGINEER:
            assert rt.capstone_count_required == 2
        else:
            assert rt.capstone_count_required == 1


# ── StudentRoleState model ────────────────────────────────────────────


async def test_student_role_state_persists_with_defaults(
    db_session: AsyncSession,
) -> None:
    """A student_role_state row materialises defaults for JSONB list/dict fields."""
    roles = await _seed_six_roles(db_session)
    user = await _seed_user(db_session)

    srs = StudentRoleState(
        student_id=user.id,
        current_role_id=roles[ROLE_SLUG_PYTHON_DEVELOPER].id,
    )
    db_session.add(srs)
    await db_session.commit()
    await db_session.refresh(srs)

    assert srs.id is not None
    assert srs.role_started_at is not None
    # Defaults: empty list/dict on JSONB columns. SQLite JSONB→TEXT shim
    # returns whatever the model `default=` produced, which is the empty
    # collection for both lists and the metadata dict.
    assert srs.transitions_completed == []
    assert srs.gates_attempted == []
    assert srs.state_metadata == {}


async def test_student_role_state_unique_per_student(
    db_session: AsyncSession,
) -> None:
    """A single user cannot have two student_role_state rows."""
    roles = await _seed_six_roles(db_session)
    user = await _seed_user(db_session)

    db_session.add(
        StudentRoleState(
            student_id=user.id,
            current_role_id=roles[ROLE_SLUG_PYTHON_DEVELOPER].id,
        )
    )
    await db_session.commit()

    db_session.add(
        StudentRoleState(
            student_id=user.id,
            current_role_id=roles[ROLE_SLUG_DATA_ANALYST].id,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_student_role_state_transitions_completed_round_trips(
    db_session: AsyncSession,
) -> None:
    """The append-only JSONB array survives a write/read round-trip."""
    roles = await _seed_six_roles(db_session)
    user = await _seed_user(db_session)

    history = [
        {
            "from_slug": ROLE_SLUG_PYTHON_DEVELOPER,
            "to_slug": ROLE_SLUG_DATA_ANALYST,
            "completed_at": "2026-05-07T00:00:00Z",
            "capstone_score": 0.78,
            "mock_session_ids": [str(uuid.uuid4()), str(uuid.uuid4())],
        }
    ]
    srs = StudentRoleState(
        student_id=user.id,
        current_role_id=roles[ROLE_SLUG_DATA_ANALYST].id,
        transitions_completed=history,
    )
    db_session.add(srs)
    await db_session.commit()
    await db_session.refresh(srs)

    assert srs.transitions_completed == history


async def test_student_role_state_fk_to_users_cascades(
    db_session: AsyncSession,
) -> None:
    """Deleting a user cascades to their student_role_state row.

    Note: SQLite enforces foreign keys only when PRAGMA foreign_keys=ON
    is set on each connection. SQLAlchemy's aiosqlite driver does NOT
    set that pragma by default, so we instead assert that the FK is
    declared correctly on the model — the live-DB enforcement is
    verified at tests/test_infra/test_role_seed.py.
    """
    fk_targets = {fk.target_fullname for fk in StudentRoleState.__table__.foreign_keys}
    assert "users.id" in fk_targets
    assert "roles.id" in fk_targets

    # ondelete=CASCADE on student_id, RESTRICT on current_role_id
    student_fk = next(
        fk
        for fk in StudentRoleState.__table__.foreign_keys
        if fk.target_fullname == "users.id"
    )
    role_fk = next(
        fk
        for fk in StudentRoleState.__table__.foreign_keys
        if fk.target_fullname == "roles.id"
    )
    assert student_fk.ondelete == "CASCADE"
    assert role_fk.ondelete == "RESTRICT"


async def test_role_transition_fk_uses_restrict(
    db_session: AsyncSession,
) -> None:
    """Both role_transitions FKs to roles use ON DELETE RESTRICT.

    Rationale: a role row should never be deleted out from under an
    active transition. RESTRICT surfaces the intent loudly.
    """
    fks = list(RoleTransition.__table__.foreign_keys)
    role_fks = [fk for fk in fks if fk.target_fullname == "roles.id"]
    assert len(role_fks) == 2
    for fk in role_fks:
        assert fk.ondelete == "RESTRICT"


# ── Cross-model: schema invariants ────────────────────────────────────


async def test_six_roles_five_transitions_invariant(
    db_session: AsyncSession,
) -> None:
    """The schema's load-bearing invariant: 6 roles → 5 transitions."""
    roles = await _seed_six_roles(db_session)
    await _seed_five_transitions(db_session, roles)

    n_roles = len(
        (await db_session.execute(select(Role))).scalars().all()
    )
    n_trans = len(
        (await db_session.execute(select(RoleTransition))).scalars().all()
    )
    assert n_roles == 6
    assert n_trans == 5
    # n - 1 transitions for a linear progression of n roles.
    assert n_trans == n_roles - 1
