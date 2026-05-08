"""D13 CP3 Phase 1.7 — Bug 22 regression test.

Pins _write_evaluation_row's None-handling on the total_score
parameter. Bug 22 was a pre-existing brittleness: the agent-call-
failed branch at evaluate.py:855 sets verdict_score=None and passes
it directly to _write_evaluation_row, which clamped via
`min(1.0, total_score)` and crashed with:

    '<' not supported between instances of 'NoneType' and 'float'

This crash never surfaced before D13 because the agent-call-failed
path requires (a) the agent's run() raising, AND (b) the Critic loop
being active (uses_self_eval=True). D13's mock_interview is the
first agent to flip uses_self_eval=True; combined with Bug 21
(handoff schema validation) raising in run(), D13 CP3 Phase 4 hit
both conditions and surfaced Bug 22.

Fix: defensive None coercion to 0.0 inside _write_evaluation_row.
Matches Critic's parsed_ok=False semantics (no score → below
threshold).
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.asyncio]


async def test_write_evaluation_row_handles_none_total_score() -> None:
    """The Bug 22 invariant: total_score=None must not crash the row writer.

    Reproduces the exact call shape from evaluate_with_retry's
    agent-call-failed branch (line 859-870).
    """
    from app.agents.primitives.evaluation import (
        EvalFailureClass,
        _write_evaluation_row,
    )

    # Stub session — we don't care about the actual insert here, only
    # that the clamp logic doesn't crash on None. session.add() is sync;
    # session.flush() is async.
    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()

    result = await _write_evaluation_row(
        session=session,
        agent_name="mock_interview",
        user_id=uuid.uuid4(),
        call_chain_id=uuid.uuid4(),
        attempt_number=1,
        verdict=None,
        total_score=None,  # Bug 22 trigger
        threshold=0.6,
        passed=False,
        critic_reasoning="agent raised ValidationError: handoff_request.suggested_context",
        failure_class=EvalFailureClass.AGENT_RAISED,
    )

    # Pre-fix: this assertion never runs because the function crashes
    # before returning. Post-fix: the function returns the row id (or
    # None if it caught a different exception, but NOT a TypeError).
    # We assert session.add was called — that's the proof the clamp
    # logic ran without raising.
    assert session.add.called, (
        "session.add was never called — _write_evaluation_row likely "
        "crashed on None total_score before reaching the insert. "
        "Bug 22 regression."
    )
    # The row passed to session.add should have total_score=0.0 (the
    # None coercion).
    added_row = session.add.call_args[0][0]
    assert added_row.total_score == 0.0


async def test_write_evaluation_row_handles_zero_score() -> None:
    """Sanity: explicit 0.0 score still works post-fix."""
    from app.agents.primitives.evaluation import (
        EvalFailureClass,
        _write_evaluation_row,
    )

    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()

    await _write_evaluation_row(
        session=session,
        agent_name="mock_interview",
        user_id=None,
        call_chain_id=None,
        attempt_number=1,
        verdict=None,
        total_score=0.0,
        threshold=0.6,
        passed=False,
        critic_reasoning="x",
        failure_class=EvalFailureClass.CRITIC_FLAKED,
    )
    added_row = session.add.call_args[0][0]
    assert added_row.total_score == 0.0


async def test_write_evaluation_row_clamps_score_above_one() -> None:
    """Sanity: clamping logic still works post-fix (score > 1.0 → 1.0)."""
    from app.agents.primitives.evaluation import (
        EvalFailureClass,
        _write_evaluation_row,
    )

    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()

    await _write_evaluation_row(
        session=session,
        agent_name="mock_interview",
        user_id=None,
        call_chain_id=None,
        attempt_number=1,
        verdict=None,
        total_score=1.5,  # out-of-range; should clamp to 1.0
        threshold=0.6,
        passed=True,
        critic_reasoning="x",
        failure_class=EvalFailureClass.NONE,
    )
    added_row = session.add.call_args[0][0]
    assert added_row.total_score == 1.0


# D17a — verdict_reasoning silent-truncation gap (follow-up to Bug 22).
# See docs/followups/eval-row-writer-defensive-fix.md "What's NOT addressed"
# section. The 2000-char cap on critic_reasoning / escalation reason is
# now surfaced via a structlog warning when truncation fires, including
# the original length so debugging is possible.


async def test_write_evaluation_row_short_reasoning_round_trips_clean(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reasoning under the cap passes through unchanged with no warning."""
    from app.agents.primitives.evaluation import (
        EvalFailureClass,
        _write_evaluation_row,
    )

    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()

    short_text = "a" * 1500  # under the 2000-char cap

    await _write_evaluation_row(
        session=session,
        agent_name="mock_interview",
        user_id=None,
        call_chain_id=None,
        attempt_number=1,
        verdict=None,
        total_score=0.5,
        threshold=0.6,
        passed=False,
        critic_reasoning=short_text,
        failure_class=EvalFailureClass.BELOW_THRESHOLD,
    )
    added_row = session.add.call_args[0][0]
    assert added_row.critic_reasoning == short_text
    captured = capsys.readouterr()
    assert "evaluate.row_field_truncated" not in captured.out


async def test_write_evaluation_row_long_reasoning_truncates_with_warning(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reasoning over the cap is truncated AND a warning is logged with
    the original length so debugging the chopped-row case is possible.

    structlog routes through its own pipeline, so we assert against the
    captured stdout JSON event rather than caplog (which only sees stdlib
    logging records).
    """
    from app.agents.primitives.evaluation import (
        EvalFailureClass,
        _write_evaluation_row,
    )

    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()

    long_text = "x" * 5000  # well over the 2000-char cap

    await _write_evaluation_row(
        session=session,
        agent_name="mock_interview",
        user_id=None,
        call_chain_id=None,
        attempt_number=1,
        verdict=None,
        total_score=0.5,
        threshold=0.6,
        passed=False,
        critic_reasoning=long_text,
        failure_class=EvalFailureClass.BELOW_THRESHOLD,
    )
    added_row = session.add.call_args[0][0]
    assert added_row.critic_reasoning is not None
    assert len(added_row.critic_reasoning) == 2000
    # Warning must surface the original length so the operator can tell
    # "this row was capped at 2000 of {original_len}" without re-running.
    captured = capsys.readouterr()
    assert "evaluate.row_field_truncated" in captured.out
    assert "5000" in captured.out
    assert "critic_reasoning" in captured.out


async def test_write_escalation_row_long_reason_truncates_with_warning(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Escalation reason follows the same truncate-with-warning shape."""
    from app.agents.primitives.evaluation import _write_escalation_row

    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()

    long_text = "y" * 4096

    await _write_escalation_row(
        session=session,
        agent_name="mock_interview",
        user_id=None,
        call_chain_id=None,
        reason=long_text,
        best_attempt={"foo": "bar"},
        notified_admin=False,
    )
    added_row = session.add.call_args[0][0]
    assert len(added_row.reason) == 2000
    captured = capsys.readouterr()
    assert "evaluate.row_field_truncated" in captured.out
    assert "4096" in captured.out
    assert "reason" in captured.out


# ── D17b/ITEM 4.A — failure_class enum threading ─────────────────────


async def test_write_evaluation_row_persists_failure_class_agent_raised() -> None:
    """The Bug 22 path now records failure_class=AGENT_RAISED on the row.

    Replaces the prefix-substring contract on critic_reasoning text
    ("agent raised X: ...") with a queryable column.
    """
    from app.agents.primitives.evaluation import (
        EvalFailureClass,
        _write_evaluation_row,
    )

    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()

    await _write_evaluation_row(
        session=session,
        agent_name="mock_interview",
        user_id=None,
        call_chain_id=None,
        attempt_number=1,
        verdict=None,
        total_score=None,
        threshold=0.6,
        passed=False,
        critic_reasoning="agent raised RuntimeError: simulated failure",
        failure_class=EvalFailureClass.AGENT_RAISED,
    )
    added_row = session.add.call_args[0][0]
    assert added_row.failure_class == "agent_raised"


async def test_write_evaluation_row_persists_failure_class_critic_flaked() -> None:
    """Critic LLM ran but parsed_ok=False → failure_class=CRITIC_FLAKED."""
    from app.agents.primitives.evaluation import (
        EvalFailureClass,
        _write_evaluation_row,
    )

    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()

    await _write_evaluation_row(
        session=session,
        agent_name="mock_interview",
        user_id=None,
        call_chain_id=None,
        attempt_number=1,
        verdict=None,
        total_score=0.0,
        threshold=0.6,
        passed=False,
        critic_reasoning="critic flaked: malformed JSON in verdict",
        failure_class=EvalFailureClass.CRITIC_FLAKED,
    )
    added_row = session.add.call_args[0][0]
    assert added_row.failure_class == "critic_flaked"


async def test_write_evaluation_row_persists_failure_class_below_threshold() -> None:
    """Critic returned valid verdict but score < threshold →
    failure_class=BELOW_THRESHOLD."""
    from app.agents.primitives.evaluation import (
        CriticVerdict,
        EvalFailureClass,
        _write_evaluation_row,
    )

    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()

    verdict = CriticVerdict(
        accuracy=0.4, helpful=0.5, complete=0.3, reasoning="weak response"
    )

    await _write_evaluation_row(
        session=session,
        agent_name="mock_interview",
        user_id=None,
        call_chain_id=None,
        attempt_number=1,
        verdict=verdict,
        total_score=0.4,
        threshold=0.6,
        passed=False,
        critic_reasoning="weak response",
        failure_class=EvalFailureClass.BELOW_THRESHOLD,
    )
    added_row = session.add.call_args[0][0]
    assert added_row.failure_class == "below_threshold"
    # Sanity: verdict scores still flow through
    assert added_row.accuracy_score == 0.4


async def test_write_evaluation_row_persists_failure_class_none_on_pass() -> None:
    """Successful eval (passed=True) records failure_class=NONE."""
    from app.agents.primitives.evaluation import (
        CriticVerdict,
        EvalFailureClass,
        _write_evaluation_row,
    )

    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()

    verdict = CriticVerdict(
        accuracy=0.8, helpful=0.9, complete=0.85, reasoning="strong response"
    )

    await _write_evaluation_row(
        session=session,
        agent_name="mock_interview",
        user_id=None,
        call_chain_id=None,
        attempt_number=1,
        verdict=verdict,
        total_score=0.85,
        threshold=0.6,
        passed=True,
        critic_reasoning="strong response",
        failure_class=EvalFailureClass.NONE,
    )
    added_row = session.add.call_args[0][0]
    assert added_row.failure_class == "none"
    assert added_row.passed is True


def test_eval_failure_class_enum_values_match_db_check_constraint() -> None:
    """Pin the enum value set against the migration's CHECK constraint.

    Adding a new EvalFailureClass member without a corresponding
    migration that updates the agent_evaluations_failure_class_enum
    CHECK would cause runtime IntegrityError on insert. This test
    catches the drift at unit-test time.
    """
    from app.agents.primitives.evaluation import EvalFailureClass

    expected = {"none", "below_threshold", "critic_flaked", "agent_raised"}
    actual = {member.value for member in EvalFailureClass}
    assert actual == expected, (
        f"EvalFailureClass values drifted from migration 0066's CHECK "
        f"constraint set. Expected {expected}, got {actual}. "
        "Update both the enum AND the migration that drops + re-adds "
        "the agent_evaluations_failure_class_enum CHECK."
    )
