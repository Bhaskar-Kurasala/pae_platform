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
    from app.agents.primitives.evaluation import _write_evaluation_row

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
    from app.agents.primitives.evaluation import _write_evaluation_row

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
    )
    added_row = session.add.call_args[0][0]
    assert added_row.total_score == 0.0


async def test_write_evaluation_row_clamps_score_above_one() -> None:
    """Sanity: clamping logic still works post-fix (score > 1.0 → 1.0)."""
    from app.agents.primitives.evaluation import _write_evaluation_row

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
    )
    added_row = session.add.call_args[0][0]
    assert added_row.total_score == 1.0
