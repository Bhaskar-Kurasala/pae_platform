"""D18 Phase A CP5 — assertion helpers + budget tracker smoke tests.

Per-helper coverage:
  * Each helper has a positive smoke (intended state → no assertion error)
    and a negative smoke (off-state → AssertionError raised).
  * Behavior-shape heuristics: each blocklist phrase is verified to
    flag, plus a calibration test verifies that legitimate empathy /
    concrete-deadline phrasing does NOT flag (false-positive guard).
  * Cost budget: tracker queries agent_invocation_log via inserted
    synthetic rows (no real LLM call — that's a CP6 concern).

All tests are async DB-only (no Playwright `page`); runs in the
same pytest invocation as CP2 + CP4 smoke per the documented
split-run convention.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.fixtures.cleanup import cleanup_student_data
from tests.fixtures.role_state_fixtures import (
    seed_admin_user,
    seed_outreach_log_entry,
    seed_passing_mock_session,
    seed_python_developer_fresh,
)
from tests.playwright.helpers.behavior_shape_assertions import (
    assert_no_fabricated_urgency,
    assert_no_sycophancy,
    assert_response_contains_intent,
    assert_response_role_appropriate,
)
from tests.playwright.helpers.cost_budget import (
    BudgetExceeded,
    TestBudgetTracker,
)
from tests.playwright.helpers.grounding_assertions import (
    assert_no_runtime_grounding_violation,
)
from tests.playwright.helpers.traceability_assertions import (
    assert_agent_action_logged,
    assert_outreach_log_entry,
    assert_student_message_thread,
    assert_student_note_count,
)

pytestmark = [pytest.mark.asyncio]
# Note: module-level asyncio mark applies to every test. Sync tests
# in this file (behavior-shape heuristics, budget report format) will
# emit a PytestWarning that they're marked async but aren't async.
# The warnings are noise-only — the tests still pass — and consolidating
# to per-test marks would require ~9 decorators. Accepted noise.


# ── Traceability assertions ─────────────────────────────────────────


async def test_assert_outreach_log_entry_positive(
    db_session: AsyncSession,
) -> None:
    student = await seed_python_developer_fresh(db_session)
    await seed_outreach_log_entry(
        db_session,
        student_id=student.user_id,
        channel="email",
        triggered_by="system",
        sent_hours_ago=0,  # very fresh
    )
    await db_session.commit()
    await assert_outreach_log_entry(
        db_session,
        user_id=student.user_id,
        channel="email",
        triggered_by="system",
        since_seconds_ago=300,
    )
    await cleanup_student_data(db_session, student.user_id)
    await db_session.commit()


async def test_assert_outreach_log_entry_negative(
    db_session: AsyncSession,
) -> None:
    """No matching row → AssertionError with diagnostic detail."""
    student = await seed_python_developer_fresh(db_session)
    await db_session.commit()
    with pytest.raises(AssertionError, match="no row matching"):
        await assert_outreach_log_entry(
            db_session,
            user_id=student.user_id,
            channel="whatsapp",
        )
    await cleanup_student_data(db_session, student.user_id)
    await db_session.commit()


async def test_assert_agent_action_logged_positive(
    db_session: AsyncSession,
) -> None:
    student = await seed_python_developer_fresh(db_session)
    await seed_passing_mock_session(
        db_session, student_id=student.user_id, hours_ago=0,
    )
    await db_session.commit()
    await assert_agent_action_logged(
        db_session,
        student_id=student.user_id,
        agent_name="mock_interview",
        status="completed",
    )
    await cleanup_student_data(db_session, student.user_id)
    await db_session.commit()


async def test_assert_agent_action_logged_negative(
    db_session: AsyncSession,
) -> None:
    student = await seed_python_developer_fresh(db_session)
    await db_session.commit()
    with pytest.raises(AssertionError, match="no row matching"):
        await assert_agent_action_logged(
            db_session,
            student_id=student.user_id,
            agent_name="career_coach",
        )
    await cleanup_student_data(db_session, student.user_id)
    await db_session.commit()


async def test_assert_student_message_thread_positive(
    db_session: AsyncSession,
) -> None:
    student = await seed_python_developer_fresh(db_session)
    admin = await seed_admin_user(db_session)
    thread_id = uuid.uuid4()
    for body in ("Hi student", "Following up"):
        await db_session.execute(
            sql_text(
                """
                INSERT INTO student_messages
                  (id, thread_id, student_id, sender_role,
                   sender_id, body, created_at, updated_at)
                VALUES
                  (:id, :tid, :sid, 'admin', :aid, :body, now(), now())
                """
            ),
            {
                "id": uuid.uuid4(),
                "tid": thread_id,
                "sid": student.user_id,
                "aid": admin.user_id,
                "body": body,
            },
        )
    await db_session.commit()
    await assert_student_message_thread(
        db_session,
        admin_id=admin.user_id,
        student_id=student.user_id,
        expected_message_count=2,
    )
    await cleanup_student_data(db_session, student.user_id)
    await cleanup_student_data(db_session, admin.user_id)
    await db_session.commit()


async def test_assert_student_message_thread_negative(
    db_session: AsyncSession,
) -> None:
    student = await seed_python_developer_fresh(db_session)
    admin = await seed_admin_user(db_session)
    await db_session.commit()
    with pytest.raises(AssertionError, match="expected 1"):
        await assert_student_message_thread(
            db_session,
            admin_id=admin.user_id,
            student_id=student.user_id,
            expected_message_count=1,
        )
    await cleanup_student_data(db_session, student.user_id)
    await cleanup_student_data(db_session, admin.user_id)
    await db_session.commit()


async def test_assert_student_note_count(db_session: AsyncSession) -> None:
    student = await seed_python_developer_fresh(db_session)
    admin = await seed_admin_user(db_session)
    await db_session.execute(
        sql_text(
            """
            INSERT INTO student_notes
              (id, admin_id, student_id, body_md,
               created_at, updated_at)
            VALUES (:id, :aid, :sid, 'A note', now(), now())
            """
        ),
        {"id": uuid.uuid4(), "aid": admin.user_id, "sid": student.user_id},
    )
    await db_session.commit()
    await assert_student_note_count(
        db_session, student_id=student.user_id, count=1,
    )
    with pytest.raises(AssertionError, match="expected 5"):
        await assert_student_note_count(
            db_session, student_id=student.user_id, count=5,
        )
    await cleanup_student_data(db_session, student.user_id)
    await cleanup_student_data(db_session, admin.user_id)
    await db_session.commit()


# ── Grounding assertions ────────────────────────────────────────────


async def test_grounding_passes_when_only_accessible_content_referenced() -> None:
    """Agent referencing only accessible-content names + role vocab passes."""
    response = (
        "Welcome back. Continue with the Data Analyst Path course; "
        "your Career Coach has prepared the next step."
    )
    accessible = {"Data Analyst Path"}
    assert_no_runtime_grounding_violation(response, accessible)


async def test_grounding_flags_fabricated_content() -> None:
    """Agent that fabricates content → AssertionError flags it.

    The D15 extractor catches two canonical fabrication shapes:
      * D-prefixed capstone titles (Bug 24 signature)
      * Parenthetical Title-Case phrases near content keywords
    We exercise the first one — plain made-up names without these
    syntactic markers don't trip the extractor by design (false-
    positive avoidance).
    """
    response = (
        "I recommend you tackle D14c CP3 Phase 2: Multi-Agent Eval "
        "Harness next. It's a great fit for your level."
    )
    accessible: set[str] = {"Data Analyst Path"}
    with pytest.raises(AssertionError, match="grounding violation"):
        assert_no_runtime_grounding_violation(response, accessible)


# ── Behavior-shape assertions ───────────────────────────────────────


def test_assert_response_contains_intent_positive() -> None:
    text = "Try the next exercise to lock in the concept."
    assert_response_contains_intent(text, ["next exercise", "practice"])


def test_assert_response_contains_intent_negative() -> None:
    text = "Hello there."
    with pytest.raises(AssertionError, match="none of"):
        assert_response_contains_intent(text, ["practice", "exercise"])


def test_assert_response_role_appropriate_positive() -> None:
    """Mentions the expected role label (Python Developer)."""
    assert_response_role_appropriate(
        "As a Python Developer, focus on idiomatic patterns next.",
        "python_developer",
    )


def test_assert_response_role_appropriate_no_other_role_pass() -> None:
    """Mentions no role labels at all → still passes (only-other-role-fails)."""
    assert_response_role_appropriate(
        "Focus on writing clean, idiomatic code next.",
        "python_developer",
    )


def test_assert_response_role_appropriate_negative() -> None:
    """References the wrong role label → fails."""
    with pytest.raises(AssertionError, match="references other roles"):
        assert_response_role_appropriate(
            "As a Data Scientist, you should... wait, ignore that.",
            "python_developer",
        )


def test_sycophancy_blocklist_flags_each_phrase() -> None:
    cases = [
        "Hey, we miss you!",
        "Don't give up — you've got this.",
        "A special offer just for you on premium content.",
        "You can't afford to miss this opportunity.",
        "This is your last chance to enroll.",
    ]
    for c in cases:
        with pytest.raises(AssertionError, match="sycophancy"):
            assert_no_sycophancy(c)


def test_sycophancy_calibration_legitimate_empathy_passes() -> None:
    """False-positive guard: legitimate empathy doesn't flag.

    These phrasings express care without manipulative re-engagement
    patterns; they must NOT match the conservative blocklist.
    """
    legitimate = [
        "I noticed you haven't logged a session this week — want to "
        "pick up where we left off?",
        "Learning is hard; let's break this into a smaller step.",
        "If you're stuck, here's a concrete next action.",
        "Your last submission scored 78. Let's improve to 85 next.",
    ]
    for c in legitimate:
        # Should not raise
        assert_no_sycophancy(c)


def test_urgency_blocklist_flags_each_phrase() -> None:
    cases = [
        "Limited time offer on this course.",
        "Your free trial expires soon.",
        "Act now to secure your spot.",
        "Today only — premium content unlocked.",
        "Enroll while supplies last.",
    ]
    for c in cases:
        with pytest.raises(AssertionError, match="fabricated_urgency"):
            assert_no_fabricated_urgency(c)


def test_urgency_calibration_concrete_deadlines_pass() -> None:
    """False-positive guard: concrete date references are legitimate."""
    legitimate = [
        "You have 3 days until the gate review on 2026-05-11.",
        "Your data_analyst capstone is due 2026-05-15.",
        "Review the rubric before your next mock interview on Friday.",
        "Your entitlement is active until 2026-12-31.",
    ]
    for c in legitimate:
        assert_no_fabricated_urgency(c)


# ── Cost budget tracker ─────────────────────────────────────────────


async def test_budget_tracker_queries_log_within_window(
    db_session: AsyncSession,
) -> None:
    """Insert two synthetic agent_invocation_log rows; tracker sums them."""
    student = await seed_python_developer_fresh(db_session)
    start = datetime.now(UTC) - timedelta(seconds=2)
    for cost in (0.05, 0.10):
        await db_session.execute(
            sql_text(
                """
                INSERT INTO agent_invocation_log
                  (id, user_id, source, source_id, sub_agent, model,
                   tokens_in, tokens_out, cost_inr, status, created_at)
                VALUES
                  (:id, :uid, 'cp5_smoke', NULL, 'fixture',
                   'claude-haiku-4-5', 100, 200, :cost, 'success', now())
                """
            ),
            {"id": uuid.uuid4(), "uid": student.user_id, "cost": cost},
        )
    await db_session.commit()

    tracker = TestBudgetTracker(budget=2.00)
    cost = await tracker.query_test_cost(db_session, since=start)
    assert cost == pytest.approx(0.15)
    await tracker.record_test_cost("synthetic_test", cost)
    assert tracker.cumulative == pytest.approx(0.15)

    await cleanup_student_data(db_session, student.user_id)
    await db_session.commit()


async def test_budget_tracker_raises_when_exceeded() -> None:
    """Recording a cost that pushes cumulative > budget raises BudgetExceeded."""
    tracker = TestBudgetTracker(budget=0.10)
    await tracker.record_test_cost("first", 0.05)
    with pytest.raises(BudgetExceeded, match="Cumulative"):
        await tracker.record_test_cost("second", 0.20)
    # Second test was still recorded so the report shows what happened.
    assert "second" in tracker.per_test_cost
    assert tracker.cumulative == pytest.approx(0.25)


def test_budget_tracker_report_format() -> None:
    """Sanity check on the report shape — used in conftest stderr summary."""
    tracker = TestBudgetTracker(budget=1.00)
    tracker.cumulative = 0.30
    tracker.per_test_cost = {"a": 0.10, "b": 0.20}
    report = tracker.report()
    assert "Total: ₹0.3" in report
    assert "Top 5" in report
    assert "a" in report and "b" in report
