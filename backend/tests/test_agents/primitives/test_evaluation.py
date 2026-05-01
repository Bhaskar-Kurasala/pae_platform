"""Critic + retry + escalation — Agentic OS Primitive 4.

The critic is mocked end-to-end: tests inject `CriticLLM`-shaped
stubs that return whatever raw string the test wants the critic
parser to see. That lets us exercise:

  • happy path (high score → pass on attempt 1)
  • retry path (low score → retry → high score → pass on attempt 2)
  • escalation path (low score twice → escalate)
  • critic-flake path (malformed JSON → score=None → never default-to-pass)
  • rate limit (5 escalations in window → 6th has notified_admin=False)

No live LLM calls, no live Claude, no real network.

The agent_evaluations + agent_escalations tables are created
on-demand in the per-test schema, mirroring the test_tools.py and
test_communication.py pattern.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.primitives import (
    Critic,
    CriticLLM,
    EscalationLimiter,
    escalation_limiter,
    evaluate_with_retry,
)


pytestmark = pytest.mark.asyncio


# ── Fixtures ────────────────────────────────────────────────────────


@pytest_asyncio.fixture(autouse=True)
async def _reset_limiter() -> AsyncGenerator[None, None]:
    """Each test starts with an empty rate-limit bucket."""
    escalation_limiter.reset()
    yield
    escalation_limiter.reset()


@pytest_asyncio.fixture
async def eval_tables(pg_session: AsyncSession) -> AsyncSession:
    """Create agent_evaluations + agent_escalations in the per-test
    schema. Same shape as the migration."""
    await pg_session.execute(
        sql_text(
            """
            CREATE TABLE IF NOT EXISTS agent_evaluations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                agent_name TEXT NOT NULL,
                user_id UUID,
                call_chain_id UUID,
                attempt_number INT NOT NULL DEFAULT 1
                    CHECK (attempt_number >= 1),
                accuracy_score REAL,
                helpful_score REAL,
                complete_score REAL,
                total_score REAL NOT NULL
                    CHECK (total_score BETWEEN 0.0 AND 1.0),
                threshold REAL NOT NULL,
                passed BOOLEAN NOT NULL,
                critic_reasoning TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    await pg_session.execute(
        sql_text(
            """
            CREATE TABLE IF NOT EXISTS agent_escalations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                agent_name TEXT NOT NULL,
                user_id UUID,
                call_chain_id UUID,
                reason TEXT NOT NULL,
                best_attempt JSONB,
                notified_admin BOOLEAN NOT NULL DEFAULT false,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    await pg_session.commit()
    return pg_session


# ── Mock critic LLM ─────────────────────────────────────────────────


@dataclass
class _StubLLM:
    """CriticLLM stub.

    `responses` is a list of strings the stub will return in order.
    If exhausted, the stub repeats the last item — that means a test
    that wants "pass forever" can pass `responses=[good_json]` once
    and not worry about how many attempts run.
    """

    responses: list[str]
    calls: int = 0

    async def ainvoke_text(self, prompt: str) -> str:
        idx = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[idx]


def _good_json(score: float = 0.9, reasoning: str = "Looks good.") -> str:
    return (
        '{"accuracy": ' + str(score) + ', "helpful": ' + str(score) +
        ', "complete": ' + str(score) + ', "reasoning": "' + reasoning + '"}'
    )


def _bad_json(score: float = 0.4, reasoning: str = "Misses the point.") -> str:
    return (
        '{"accuracy": ' + str(score) + ', "helpful": ' + str(score) +
        ', "complete": ' + str(score) + ', "reasoning": "' + reasoning + '"}'
    )


# ── Critic parsing ──────────────────────────────────────────────────


async def test_critic_parses_clean_json() -> None:
    critic = Critic(_StubLLM(responses=[_good_json(0.85, "ok")]))
    result = await critic.evaluate(request="q", response="a")
    assert result.parsed_ok is True
    assert result.verdict is not None
    assert result.verdict.accuracy == 0.85
    assert result.total_score == pytest.approx(0.85)


async def test_critic_extracts_first_json_from_messy_response() -> None:
    """LLM may leak prose around the JSON; we still parse it."""
    raw = (
        "Sure! Here is my evaluation:\n\n"
        '{"accuracy": 0.7, "helpful": 0.8, "complete": null, '
        '"reasoning": "Mostly there."}\n\n'
        "Hope that helps."
    )
    critic = Critic(_StubLLM(responses=[raw]))
    result = await critic.evaluate(request="q", response="a")
    assert result.parsed_ok is True
    assert result.verdict is not None
    # Mean of the two non-null sub-scores.
    assert result.total_score == pytest.approx(0.75)


async def test_critic_returns_parsed_ok_false_on_garbage() -> None:
    """Critical contract: malformed JSON → parsed_ok=False, NOT a
    silent 0.5 default. The orchestrator threshold-check fails on
    score=None which is correct."""
    critic = Critic(_StubLLM(responses=["definitely not json {{{ at all"]))
    result = await critic.evaluate(request="q", response="a")
    assert result.parsed_ok is False
    assert result.total_score is None
    assert result.verdict is None


async def test_critic_returns_parsed_ok_false_on_schema_violation() -> None:
    """Extra fields → schema violation (extra='forbid'). The critic
    can't smuggle 'overall_quality' or any other invented field."""
    raw = (
        '{"accuracy": 0.9, "helpful": 0.9, "complete": 0.9, '
        '"reasoning": "fine", "overall_quality": "A+"}'
    )
    critic = Critic(_StubLLM(responses=[raw]))
    result = await critic.evaluate(request="q", response="a")
    assert result.parsed_ok is False


async def test_critic_returns_parsed_ok_false_on_score_out_of_range() -> None:
    raw = (
        '{"accuracy": 1.5, "helpful": 0.5, "complete": 0.5, '
        '"reasoning": "calibration broken"}'
    )
    critic = Critic(_StubLLM(responses=[raw]))
    result = await critic.evaluate(request="q", response="a")
    assert result.parsed_ok is False


async def test_critic_handles_llm_exception_gracefully() -> None:
    """When the LLM call raises, parsed_ok=False with a marker
    string — never a silent pass."""

    @dataclass
    class _ExplodingLLM:
        async def ainvoke_text(self, prompt: str) -> str:
            raise RuntimeError("provider 503")

    critic = Critic(_ExplodingLLM())
    result = await critic.evaluate(request="q", response="a")
    assert result.parsed_ok is False
    assert result.total_score is None
    assert "provider 503" in result.raw_response


async def test_critic_total_score_handles_partial_subscores() -> None:
    raw = (
        '{"accuracy": 0.6, "helpful": null, "complete": null, '
        '"reasoning": "only accuracy applies"}'
    )
    critic = Critic(_StubLLM(responses=[raw]))
    result = await critic.evaluate(request="q", response="a")
    assert result.parsed_ok is True
    assert result.total_score == pytest.approx(0.6)


# ── evaluate_with_retry: happy path ─────────────────────────────────


async def test_eval_passes_on_first_attempt(eval_tables: AsyncSession) -> None:
    """Score >= threshold → AgentResult ok, retry_count=0,
    one agent_evaluations row written."""
    critic = Critic(_StubLLM(responses=[_good_json(0.85)]))

    async def _factory(_feedback: str | None) -> str:
        return "good answer"

    result = await evaluate_with_retry(
        agent_name="test_agent",
        request="explain X",
        coro_factory=_factory,
        session=eval_tables,
        critic=critic,
    )
    assert result.escalated is False
    assert result.retry_count == 0
    assert result.score == pytest.approx(0.85)

    raw = await eval_tables.execute(
        sql_text(
            "SELECT count(*), bool_or(passed) FROM agent_evaluations"
        )
    )
    count, passed = raw.one()
    assert count == 1
    assert passed is True


# ── evaluate_with_retry: retry path ─────────────────────────────────


async def test_eval_retries_on_low_score_then_passes(
    eval_tables: AsyncSession,
) -> None:
    """First attempt < threshold → retry. Second attempt's coro_factory
    sees the critic's reasoning as `feedback`. Critic blesses round 2."""
    critic = Critic(_StubLLM(responses=[_bad_json(0.3, "needs depth"), _good_json(0.9)]))

    seen_feedback: list[str | None] = []

    async def _factory(feedback: str | None) -> str:
        seen_feedback.append(feedback)
        return "answer v1" if feedback is None else "answer v2 (refined)"

    result = await evaluate_with_retry(
        agent_name="retry_agent",
        request="explain X",
        coro_factory=_factory,
        session=eval_tables,
        critic=critic,
        threshold=0.6,
        max_retries=1,
    )
    assert result.escalated is False
    assert result.retry_count == 1
    assert result.score == pytest.approx(0.9)
    # First attempt: feedback=None. Second attempt: critic's reasoning.
    assert seen_feedback == [None, "needs depth"]

    raw = await eval_tables.execute(
        sql_text(
            "SELECT attempt_number, passed, total_score "
            "FROM agent_evaluations ORDER BY attempt_number"
        )
    )
    rows = raw.all()
    assert len(rows) == 2
    assert rows[0][0] == 1 and rows[0][1] is False
    assert rows[1][0] == 2 and rows[1][1] is True


# ── evaluate_with_retry: escalation path (the spec test) ────────────


async def test_eval_escalates_after_two_failures(
    eval_tables: AsyncSession,
) -> None:
    """Spec: mock an agent that returns bad output. Retry happens.
    Escalation fires after 2 failures."""
    critic = Critic(
        _StubLLM(responses=[_bad_json(0.3, "round one bad"), _bad_json(0.4, "round two also bad")])
    )

    async def _factory(_feedback: str | None) -> str:
        return "garbage"

    result = await evaluate_with_retry(
        agent_name="escalating_agent",
        request="explain X",
        coro_factory=_factory,
        session=eval_tables,
        critic=critic,
        threshold=0.6,
        max_retries=1,
    )
    assert result.escalated is True
    assert result.retry_count == 1
    # Best score is 0.4 (the better of the two bad attempts).
    assert result.score == pytest.approx(0.4)
    assert result.notified_admin is True  # under default 5/hr limit
    assert result.escalation_id is not None

    # Two evaluation rows + one escalation row.
    raw_evals = await eval_tables.execute(
        sql_text("SELECT count(*) FROM agent_evaluations")
    )
    assert raw_evals.scalar_one() == 2
    raw_esc = await eval_tables.execute(
        sql_text(
            "SELECT count(*), bool_or(notified_admin) FROM agent_escalations"
        )
    )
    count, notified = raw_esc.one()
    assert count == 1
    assert notified is True


async def test_eval_escalates_when_critic_flakes_both_times(
    eval_tables: AsyncSession,
) -> None:
    """If the critic returns malformed JSON twice, the orchestrator
    must NOT silently pass. Escalation fires; reasoning records the
    flake. Spec: never default-to-pass on critic failure."""
    critic = Critic(_StubLLM(responses=["not json", "still not json"]))

    async def _factory(_feedback: str | None) -> str:
        return "any answer"

    result = await evaluate_with_retry(
        agent_name="flaky_critic_agent",
        request="explain X",
        coro_factory=_factory,
        session=eval_tables,
        critic=critic,
        max_retries=1,
    )
    assert result.escalated is True
    assert result.score is None or result.score == 0.0

    raw = await eval_tables.execute(
        sql_text(
            "SELECT reason FROM agent_escalations LIMIT 1"
        )
    )
    reason = raw.scalar_one()
    # The escalation reason should include the score floor + attempt count
    # so admins can tell apart "model was bad" from "critic was bad".
    assert "attempts" in reason.lower()


# ── evaluate_with_retry: agent itself raises ────────────────────────


async def test_eval_treats_agent_exception_as_failed_attempt(
    eval_tables: AsyncSession,
) -> None:
    """When the agent's coroutine raises, that's a failed attempt
    (score=0). The retry budget still applies; on success at retry 2
    the result.escalated is False."""
    critic = Critic(_StubLLM(responses=[_good_json(0.9)]))
    counter = {"calls": 0}

    async def _factory(_feedback: str | None) -> str:
        counter["calls"] += 1
        if counter["calls"] == 1:
            raise RuntimeError("transient agent crash")
        return "recovered"

    result = await evaluate_with_retry(
        agent_name="crashy_agent",
        request="explain X",
        coro_factory=_factory,
        session=eval_tables,
        critic=critic,
        max_retries=1,
    )
    assert result.escalated is False
    assert result.retry_count == 1
    assert result.score == pytest.approx(0.9)


# ── EscalationLimiter unit tests ────────────────────────────────────


# Limiter unit tests don't need async — they're pure. Marked with
# the module's pytestmark for consistency with the rest of the file;
# pytest-asyncio in `auto` mode dispatches them without needing them
# to actually await anything.
async def test_limiter_admits_under_budget() -> None:
    limiter = EscalationLimiter(limit_per_agent=3, window_seconds=60)
    assert limiter.should_notify("a") is True
    assert limiter.should_notify("a") is True
    assert limiter.should_notify("a") is True


async def test_limiter_blocks_over_budget() -> None:
    limiter = EscalationLimiter(limit_per_agent=2, window_seconds=60)
    assert limiter.should_notify("a") is True
    assert limiter.should_notify("a") is True
    assert limiter.should_notify("a") is False
    assert limiter.should_notify("a") is False


async def test_limiter_segments_by_agent() -> None:
    """Agent A's quota does not deplete agent B's quota."""
    limiter = EscalationLimiter(limit_per_agent=1, window_seconds=60)
    assert limiter.should_notify("a") is True
    assert limiter.should_notify("b") is True
    assert limiter.should_notify("a") is False
    assert limiter.should_notify("b") is False


async def test_limiter_window_slides() -> None:
    """Old entries fall out of the window. Use an injectable clock so
    the test runs in microseconds, not minutes."""
    fake_now = [0.0]

    def clock() -> float:
        return fake_now[0]

    limiter = EscalationLimiter(
        limit_per_agent=2, window_seconds=10, clock=clock
    )
    assert limiter.should_notify("a") is True   # t=0, count=1
    assert limiter.should_notify("a") is True   # t=0, count=2
    assert limiter.should_notify("a") is False  # over budget

    fake_now[0] = 11.0  # advance past the window
    assert limiter.should_notify("a") is True   # bucket cleared


async def test_limiter_zero_budget_never_notifies() -> None:
    """A limit of 0 disables notifications entirely (e.g. a quiet
    deployment that shouldn't page on anything)."""
    limiter = EscalationLimiter(limit_per_agent=0, window_seconds=60)
    assert limiter.should_notify("a") is False
    assert limiter.should_notify("a") is False


# ── escalation rate limit: integration ─────────────────────────────


async def test_eval_respects_escalation_rate_limit(
    eval_tables: AsyncSession,
) -> None:
    """6th escalation in window → audit row still lands, but
    notified_admin=False. Real signal preserved; firehose suppressed."""
    limiter = EscalationLimiter(limit_per_agent=2, window_seconds=60)

    async def _bad_factory(_feedback: str | None) -> str:
        return "bad"

    for i in range(3):
        critic = Critic(
            _StubLLM(responses=[_bad_json(0.2), _bad_json(0.2)])
        )
        result = await evaluate_with_retry(
            agent_name="noisy_agent",
            request=f"q{i}",
            coro_factory=_bad_factory,
            session=eval_tables,
            critic=critic,
            limiter=limiter,
            max_retries=1,
        )
        assert result.escalated is True
        if i < 2:
            assert result.notified_admin is True
        else:
            assert result.notified_admin is False

    raw = await eval_tables.execute(
        sql_text(
            "SELECT notified_admin, count(*) "
            "FROM agent_escalations "
            "GROUP BY notified_admin "
            "ORDER BY notified_admin"
        )
    )
    by_flag = dict(raw.all())
    # Two notified, one suppressed.
    assert by_flag[True] == 2
    assert by_flag[False] == 1
