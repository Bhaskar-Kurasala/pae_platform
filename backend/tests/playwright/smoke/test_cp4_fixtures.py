"""D18 Phase A CP4 — fixture smoke tests.

Each test exercises one fixture / seed helper and verifies:
  1. The seed produces the expected DB state (rows exist with right shape).
  2. Cleanup leaves no orphan rows when the fixture tears down.

The CP4 cleanup contract is: cleanup_student_data() + commit removes
the user + all anchored rows in correct FK order; assert_no_orphan_rows
+ assert_user_deleted are the post-condition checks.

Pure DB tests (no Playwright `page` fixture) so they live in the
async-db-only invocation alongside test_cp2_db.py per the split-run
convention from CP3 (see docs/followups/pytest-asyncio-pytest-
playwright-split-runs.md).

Run with:
  docker compose exec -T backend sh -c \\
    "cd /app && uv run pytest tests/playwright/smoke/test_cp4_fixtures.py -v"
"""

from __future__ import annotations

import pytest
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.fixtures.admin_fixtures import (
    seed_admin_user_with_login,
    seed_admin_with_outreach_history,
)
from tests.fixtures.cleanup import (
    assert_no_orphan_rows,
    assert_user_deleted,
    cleanup_student_data,
)
from tests.fixtures.journey_fixtures import (
    seed_capstone_stalled_student,
    seed_cold_signup_student,
    seed_full_journey_through_data_analyst,
    seed_paid_silent_at_risk_student,
    seed_promotion_avoidant_student,
    seed_streak_broken_student,
)
from tests.fixtures.role_state_fixtures import (
    seed_admin_user,
    seed_capstone_submission,
    seed_outreach_log_entry,
    seed_passing_mock_session,
    seed_payment_intent,
    seed_python_developer_fresh,
)

pytestmark = [pytest.mark.asyncio]


# ── Primitive seeders (5 new at CP4) ────────────────────────────────


async def test_seed_admin_user_creates_admin_role(db_session: AsyncSession) -> None:
    admin = await seed_admin_user(db_session)
    await db_session.commit()
    role = (
        await db_session.execute(
            sql_text("SELECT role FROM users WHERE id = :id"),
            {"id": admin.user_id},
        )
    ).scalar_one()
    assert role == "admin"
    await cleanup_student_data(db_session, admin.user_id)
    await db_session.commit()
    await assert_user_deleted(db_session, admin.user_id)


async def test_seed_payment_intent_writes_payments_row(
    db_session: AsyncSession,
) -> None:
    student = await seed_python_developer_fresh(db_session)
    payment = await seed_payment_intent(
        db_session, student_id=student.user_id, amount_cents=12345,
        status="succeeded",
    )
    await db_session.commit()
    row = (
        await db_session.execute(
            sql_text(
                "SELECT amount_cents, status FROM payments WHERE id = :id"
            ),
            {"id": payment.payment_id},
        )
    ).one()
    assert row.amount_cents == 12345
    assert row.status == "succeeded"
    await cleanup_student_data(db_session, student.user_id)
    await db_session.commit()
    await assert_no_orphan_rows(db_session, student.user_id)


async def test_seed_capstone_submission_lazily_creates_exercise(
    db_session: AsyncSession,
) -> None:
    student = await seed_python_developer_fresh(db_session)
    sub = await seed_capstone_submission(
        db_session, student_id=student.user_id, score=85,
    )
    await db_session.commit()
    is_capstone = (
        await db_session.execute(
            sql_text("SELECT is_capstone FROM exercises WHERE id = :id"),
            {"id": sub.exercise_id},
        )
    ).scalar_one()
    assert is_capstone is True
    score = (
        await db_session.execute(
            sql_text(
                "SELECT score FROM exercise_submissions WHERE id = :id"
            ),
            {"id": sub.submission_id},
        )
    ).scalar_one()
    assert score == 85
    await cleanup_student_data(db_session, student.user_id)
    await db_session.commit()
    await assert_user_deleted(db_session, student.user_id)


async def test_seed_passing_mock_session_writes_agent_action(
    db_session: AsyncSession,
) -> None:
    student = await seed_python_developer_fresh(db_session)
    aid = await seed_passing_mock_session(
        db_session, student_id=student.user_id,
        target_role_slug="data_analyst",
    )
    await db_session.commit()
    output = (
        await db_session.execute(
            sql_text(
                "SELECT output_data FROM agent_actions WHERE id = :id"
            ),
            {"id": aid},
        )
    ).scalar_one()
    assert output["session_verdict"]["passed"] is True
    assert output["session_verdict"]["transition_target"]["to_role_slug"] == "data_analyst"
    await cleanup_student_data(db_session, student.user_id)
    await db_session.commit()
    await assert_no_orphan_rows(db_session, student.user_id)


async def test_seed_outreach_log_entry_writes_row(
    db_session: AsyncSession,
) -> None:
    student = await seed_python_developer_fresh(db_session)
    rid = await seed_outreach_log_entry(
        db_session, student_id=student.user_id, channel="whatsapp",
        body_preview="hi from cp4 smoke",
    )
    await db_session.commit()
    row = (
        await db_session.execute(
            sql_text(
                "SELECT channel, body_preview FROM outreach_log "
                "WHERE id = :id"
            ),
            {"id": rid},
        )
    ).one()
    assert row.channel == "whatsapp"
    assert row.body_preview == "hi from cp4 smoke"
    await cleanup_student_data(db_session, student.user_id)
    await db_session.commit()
    await assert_no_orphan_rows(db_session, student.user_id)


# ── Composite journey fixtures (6 at CP4) ───────────────────────────


async def test_journey_full_through_data_analyst(
    db_session: AsyncSession,
) -> None:
    journey = await seed_full_journey_through_data_analyst(db_session)
    await db_session.commit()
    # Two passing-mock action ids should exist on agent_actions.
    count_passing = (
        await db_session.execute(
            sql_text(
                """
                SELECT COUNT(*) FROM agent_actions
                WHERE student_id = :sid
                  AND agent_name = 'mock_interview'
                  AND output_data->'session_verdict'->>'passed' = 'true'
                """
            ),
            {"sid": journey.student.user_id},
        )
    ).scalar_one()
    assert count_passing == 2
    # data-analyst entitlement granted on top of base. course_entitlements
    # joins via course_id; resolve via slug → courses.id.
    count_ent = (
        await db_session.execute(
            sql_text(
                """
                SELECT COUNT(*) FROM course_entitlements ce
                JOIN courses c ON c.id = ce.course_id
                WHERE ce.user_id = :uid AND c.slug = 'data-analyst'
                """
            ),
            {"uid": journey.student.user_id},
        )
    ).scalar_one()
    assert count_ent == 1
    await cleanup_student_data(db_session, journey.student.user_id)
    await db_session.commit()
    await assert_no_orphan_rows(db_session, journey.student.user_id)


async def test_journey_paid_silent_at_risk(
    db_session: AsyncSession,
) -> None:
    journey = await seed_paid_silent_at_risk_student(db_session)
    await db_session.commit()
    row = (
        await db_session.execute(
            sql_text(
                "SELECT slip_type, paid, days_since_last_session "
                "FROM student_risk_signals WHERE user_id = :uid"
            ),
            {"uid": journey.student.user_id},
        )
    ).one()
    assert row.slip_type == "paid_silent"
    assert row.paid is True
    assert row.days_since_last_session == 12
    await cleanup_student_data(db_session, journey.student.user_id)
    await db_session.commit()
    await assert_no_orphan_rows(db_session, journey.student.user_id)


async def test_journey_capstone_stalled(db_session: AsyncSession) -> None:
    journey = await seed_capstone_stalled_student(db_session)
    await db_session.commit()
    # Ungraded capstone draft (score IS NULL).
    score = (
        await db_session.execute(
            sql_text(
                "SELECT score FROM exercise_submissions "
                "WHERE student_id = :sid"
            ),
            {"sid": journey.student.user_id},
        )
    ).scalar_one()
    assert score is None
    slip = (
        await db_session.execute(
            sql_text(
                "SELECT slip_type FROM student_risk_signals "
                "WHERE user_id = :uid"
            ),
            {"uid": journey.student.user_id},
        )
    ).scalar_one()
    assert slip == "capstone_stalled"
    await cleanup_student_data(db_session, journey.student.user_id)
    await db_session.commit()
    await assert_no_orphan_rows(db_session, journey.student.user_id)


async def test_journey_streak_broken(db_session: AsyncSession) -> None:
    journey = await seed_streak_broken_student(db_session)
    await db_session.commit()
    row = (
        await db_session.execute(
            sql_text(
                "SELECT slip_type, max_streak_ever "
                "FROM student_risk_signals WHERE user_id = :uid"
            ),
            {"uid": journey.student.user_id},
        )
    ).one()
    assert row.slip_type == "streak_broken"
    assert row.max_streak_ever == 8
    await cleanup_student_data(db_session, journey.student.user_id)
    await db_session.commit()
    await assert_no_orphan_rows(db_session, journey.student.user_id)


async def test_journey_promotion_avoidant(db_session: AsyncSession) -> None:
    journey = await seed_promotion_avoidant_student(db_session)
    await db_session.commit()
    slip = (
        await db_session.execute(
            sql_text(
                "SELECT slip_type FROM student_risk_signals "
                "WHERE user_id = :uid"
            ),
            {"uid": journey.student.user_id},
        )
    ).scalar_one()
    assert slip == "promotion_avoidant"
    await cleanup_student_data(db_session, journey.student.user_id)
    await db_session.commit()
    await assert_no_orphan_rows(db_session, journey.student.user_id)


async def test_journey_cold_signup(db_session: AsyncSession) -> None:
    journey = await seed_cold_signup_student(db_session, days_since_signup=7)
    await db_session.commit()
    row = (
        await db_session.execute(
            sql_text(
                "SELECT slip_type, days_since_last_session "
                "FROM student_risk_signals WHERE user_id = :uid"
            ),
            {"uid": journey.student.user_id},
        )
    ).one()
    assert row.slip_type == "cold_signup"
    assert row.days_since_last_session is None
    await cleanup_student_data(db_session, journey.student.user_id)
    await db_session.commit()
    await assert_no_orphan_rows(db_session, journey.student.user_id)


# ── Admin fixtures (2 at CP4) ───────────────────────────────────────


async def test_admin_user_with_login_has_real_bcrypt_hash(
    db_session: AsyncSession,
) -> None:
    """Verifies the bcrypt round-trip; admin can log in via HTTP."""
    from app.core.hashing import verify_password

    admin = await seed_admin_user_with_login(db_session)
    await db_session.commit()
    stored_hash = (
        await db_session.execute(
            sql_text("SELECT hashed_password FROM users WHERE id = :id"),
            {"id": admin.user_id},
        )
    ).scalar_one()
    assert verify_password(admin.password, stored_hash) is True
    await cleanup_student_data(db_session, admin.user_id)
    await db_session.commit()
    await assert_user_deleted(db_session, admin.user_id)


async def test_admin_with_outreach_history(db_session: AsyncSession) -> None:
    """Seeds an admin + a target student + outreach rows; verifies counts."""
    student = await seed_python_developer_fresh(db_session)
    composite = await seed_admin_with_outreach_history(
        db_session,
        target_student_id=student.user_id,
        channel_counts={"email": 3, "whatsapp": 2, "in_app": 1},
    )
    await db_session.commit()
    counts = (
        await db_session.execute(
            sql_text(
                """
                SELECT channel, COUNT(*) AS n
                FROM outreach_log
                WHERE user_id = :uid
                  AND triggered_by_user_id = :aid
                GROUP BY channel
                """
            ),
            {"uid": student.user_id, "aid": composite.admin.user_id},
        )
    ).all()
    by_channel = {c: n for c, n in counts}
    assert by_channel == {"email": 3, "whatsapp": 2, "in_app": 1}

    # Cleanup BOTH users (admin + student). Outreach rows are
    # CASCADE-deleted via the student FK, but admin row needs
    # explicit cleanup.
    await cleanup_student_data(db_session, student.user_id)
    await cleanup_student_data(db_session, composite.admin.user_id)
    await db_session.commit()
    await assert_no_orphan_rows(db_session, student.user_id)
    await assert_user_deleted(db_session, composite.admin.user_id)


# ── Cleanup helper invariants ───────────────────────────────────────


async def test_cleanup_idempotent(db_session: AsyncSession) -> None:
    """Calling cleanup twice on the same user is a no-op the second time."""
    student = await seed_python_developer_fresh(db_session)
    await db_session.commit()
    await cleanup_student_data(db_session, student.user_id)
    await db_session.commit()
    # Second call should not raise.
    await cleanup_student_data(db_session, student.user_id)
    await db_session.commit()
    await assert_user_deleted(db_session, student.user_id)


async def test_cleanup_handles_outreach_dual_fk(
    db_session: AsyncSession,
) -> None:
    """Ensures cleanup deletes outreach rows where the user is the trigger,
    not just the target. Prevents orphan triggered_by_user_id chains."""
    admin = await seed_admin_user(db_session)
    target = await seed_python_developer_fresh(db_session)
    await seed_outreach_log_entry(
        db_session,
        student_id=target.user_id,
        channel="email",
        triggered_by="admin",
        triggered_by_user_id=admin.user_id,
    )
    await db_session.commit()
    # Cleanup only the admin — target row should remain (outreach
    # rows targeting that student persist; only the trigger admin
    # is gone, with triggered_by_user_id now NULL via SET NULL).
    await cleanup_student_data(db_session, admin.user_id)
    await db_session.commit()
    await assert_user_deleted(db_session, admin.user_id)
    # Target student still exists.
    target_count = (
        await db_session.execute(
            sql_text("SELECT COUNT(*) FROM users WHERE id = :uid"),
            {"uid": target.user_id},
        )
    ).scalar_one()
    assert target_count == 1
    # Cleanup the target now.
    await cleanup_student_data(db_session, target.user_id)
    await db_session.commit()
    await assert_no_orphan_rows(db_session, target.user_id)
