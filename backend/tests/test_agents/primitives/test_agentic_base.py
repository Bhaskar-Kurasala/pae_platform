"""AgenticBaseAgent — composition of the 5 primitives + opt-outs.

The test surface mirrors D7's deliverable contract:

  • Subclassing auto-registers
  • Each opt-out flag works (off = no primitive cost)
  • execute() returns AgentResult regardless of self-eval state
  • Inter-agent calls thread the chain correctly
  • Memory + tool_call helpers are gated by their opt-outs
  • Unit-testing an agent's prompt logic doesn't require a critic LLM

We deliberately DO NOT test:
  • The Celery task body (D7b)
  • The webhook route mount (D7b)
  • The reference example_learning_coach (D8)
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agentic_base import (
    AgentContext,
    AgentInput,
    AgentResult,
    AgenticBaseAgent,
)
from app.agents.primitives import (
    CallChain,
    Critic,
    EscalationLimiter,
    clear_agentic_registry,
    get_agentic,
    list_agentic,
)


pytestmark = pytest.mark.asyncio


# ── Fixtures ────────────────────────────────────────────────────────


@pytest_asyncio.fixture(autouse=True)
async def _reset_registry() -> AsyncGenerator[None, None]:
    """Each test starts and ends with the agentic registry empty so
    auto-registration side effects don't leak across cases."""
    clear_agentic_registry()
    yield
    clear_agentic_registry()


@pytest_asyncio.fixture
async def agent_tables(pg_session: AsyncSession) -> AsyncSession:
    """Create the audit tables AgenticBaseAgent's primitives write
    to. Conftest only handles agent_memory; this fixture adds tools,
    chain, evaluation, escalation tables on demand."""
    await pg_session.execute(
        sql_text(
            """
            CREATE TABLE IF NOT EXISTS agent_tool_calls (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                agent_name TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                args JSONB NOT NULL,
                result JSONB,
                status TEXT NOT NULL,
                error_message TEXT,
                duration_ms INT NOT NULL,
                user_id UUID,
                call_chain_id UUID,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    await pg_session.execute(
        sql_text(
            """
            CREATE TABLE IF NOT EXISTS agent_call_chain (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                root_id UUID NOT NULL,
                parent_id UUID,
                caller_agent TEXT,
                callee_agent TEXT NOT NULL,
                depth INT NOT NULL DEFAULT 0,
                payload JSONB,
                result JSONB,
                status TEXT NOT NULL,
                user_id UUID,
                duration_ms INT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT agent_call_chain_status_chk CHECK (
                    status IN ('ok','error','cycle','depth_exceeded')
                ),
                CONSTRAINT agent_call_chain_depth_nonneg CHECK (depth >= 0)
            )
            """
        )
    )
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


# ── Test inputs ─────────────────────────────────────────────────────


class _SampleIn(AgentInput):
    """Concrete input for the test agents below."""

    question: str = Field(min_length=1, max_length=2000)
    style: str = "concise"


# ── Stub critic (deterministic, no live LLM) ───────────────────────


@dataclass
class _StubCriticLLM:
    """Stand-in for `Critic`'s LLM. Returns a fixed JSON verdict."""

    verdict_json: str

    async def ainvoke_text(self, prompt: str) -> str:
        return self.verdict_json


def _passing_critic() -> Critic:
    return Critic(
        _StubCriticLLM(
            verdict_json=(
                '{"accuracy": 0.9, "helpful": 0.9, "complete": 0.9, '
                '"reasoning": "ok"}'
            )
        )
    )


def _failing_critic() -> Critic:
    return Critic(
        _StubCriticLLM(
            verdict_json=(
                '{"accuracy": 0.2, "helpful": 0.2, "complete": 0.2, '
                '"reasoning": "weak"}'
            )
        )
    )


# ── Auto-registration via __init_subclass__ ────────────────────────


async def test_concrete_subclass_auto_registers() -> None:
    """A subclass with a non-empty `name` should land in the
    agentic registry the moment the class definition runs."""
    assert "_test_simple_agent" not in list_agentic()

    class _TestAgent(AgenticBaseAgent[_SampleIn]):
        name = "_test_simple_agent"
        description = "test"
        input_schema = _SampleIn

        async def run(self, input: _SampleIn, ctx: AgentContext) -> str:
            return f"answered: {input.question}"

    assert "_test_simple_agent" in list_agentic()
    instance = get_agentic("_test_simple_agent")
    assert isinstance(instance, _TestAgent)


async def test_intermediate_abstract_subclass_does_not_register() -> None:
    """A subclass with an empty `name` is treated as abstract and
    must NOT auto-register. Lets us define mixin-style intermediate
    classes without leaking phantom names into the registry."""

    class _AbstractWithMixin(AgenticBaseAgent[_SampleIn]):
        # No name — intentionally abstract
        pass

    assert "_AbstractWithMixin" not in list_agentic()
    # Even by class-name string lookup, no entry.
    assert list_agentic() == []


# ── execute() basic shape ──────────────────────────────────────────


async def test_execute_validates_input_against_schema(
    agent_tables: AsyncSession,
) -> None:
    """A bad shape should fail at the agent boundary with a
    pydantic ValidationError (caller bug, not an agent runtime
    failure)."""
    from pydantic import ValidationError

    class _A(AgenticBaseAgent[_SampleIn]):
        name = "_test_a_validate"
        description = "x"
        input_schema = _SampleIn

        async def run(self, input: _SampleIn, ctx: AgentContext) -> str:
            return "ok"

    a = _A()
    ctx = AgentContext(
        chain=CallChain.start_root(caller="test"),
        session=agent_tables,
    )
    with pytest.raises(ValidationError):
        await a.execute({"not_a_field": "wrong"}, ctx)


async def test_execute_returns_agent_result_when_self_eval_off(
    agent_tables: AsyncSession,
) -> None:
    """uses_self_eval=False → no critic call, AgentResult populated
    with score=None, retry_count=0."""

    class _A(AgenticBaseAgent[_SampleIn]):
        name = "_test_no_eval"
        description = "x"
        input_schema = _SampleIn
        uses_self_eval = False

        async def run(self, input: _SampleIn, ctx: AgentContext) -> str:
            return f"answer: {input.question}"

    a = _A()
    ctx = AgentContext(
        chain=CallChain.start_root(caller="test"),
        session=agent_tables,
    )
    result = await a.execute(
        {"question": "what is python?"}, ctx
    )
    assert isinstance(result, AgentResult)
    assert result.escalated is False
    assert result.score is None  # critic never ran
    assert result.retry_count == 0
    assert result.output == "answer: what is python?"


# ── Self-eval composition (uses_self_eval=True) ────────────────────


async def test_execute_runs_critic_when_self_eval_on(
    agent_tables: AsyncSession,
) -> None:
    """uses_self_eval=True → critic evaluates output. Stub critic
    returns 0.9; pass on first attempt; AgentResult.score reflects
    the critic's verdict."""

    class _A(AgenticBaseAgent[_SampleIn]):
        name = "_test_with_eval"
        description = "x"
        input_schema = _SampleIn
        uses_self_eval = True

        async def run(self, input: _SampleIn, ctx: AgentContext) -> str:
            return "good answer"

        def _critic(self) -> Critic:
            return _passing_critic()

    a = _A()
    ctx = AgentContext(
        chain=CallChain.start_root(caller="test"),
        session=agent_tables,
    )
    result = await a.execute({"question": "q"}, ctx)
    assert result.escalated is False
    assert result.score == pytest.approx(0.9)


async def test_execute_escalates_when_critic_keeps_failing(
    agent_tables: AsyncSession,
) -> None:
    """Two attempts both score 0.2 → escalation row + escalated=True."""

    class _A(AgenticBaseAgent[_SampleIn]):
        name = "_test_eval_escalate"
        description = "x"
        input_schema = _SampleIn
        uses_self_eval = True
        eval_max_retries = 1  # 2 attempts total

        async def run(self, input: _SampleIn, ctx: AgentContext) -> str:
            return "bad answer"

        def _critic(self) -> Critic:
            return _failing_critic()

        def _limiter(self) -> EscalationLimiter:
            # Isolate from other tests' rate-limit state so we can
            # assert notified_admin=True deterministically.
            return EscalationLimiter(limit_per_agent=99, window_seconds=60)

    a = _A()
    ctx = AgentContext(
        chain=CallChain.start_root(caller="test"),
        session=agent_tables,
    )
    result = await a.execute({"question": "q"}, ctx)
    assert result.escalated is True
    assert result.score == pytest.approx(0.2)
    assert result.notified_admin is True
    assert result.escalation_id is not None


# ── Critic feedback threading ──────────────────────────────────────


async def test_run_sees_critic_feedback_on_retry(
    agent_tables: AsyncSession,
) -> None:
    """When the critic fails attempt 1, the retry's run() must see
    the critic's reasoning under ctx.extra['critic_feedback'].

    The test uses a stub critic that fails-then-passes. We assert
    the agent's run captured the feedback string on attempt 2."""
    seen_feedback: list[str | None] = []

    @dataclass
    class _AlternatingLLM:
        async def ainvoke_text(self, prompt: str) -> str:
            # Use a list-of-responses pattern so attempt 1 fails,
            # attempt 2 passes.
            self.calls = getattr(self, "calls", 0) + 1
            return (
                '{"accuracy": 0.2, "helpful": 0.2, "complete": 0.2, '
                '"reasoning": "needs more detail"}'
                if self.calls == 1
                else '{"accuracy": 0.9, "helpful": 0.9, "complete": 0.9, '
                     '"reasoning": "great"}'
            )

    class _A(AgenticBaseAgent[_SampleIn]):
        name = "_test_eval_feedback"
        description = "x"
        input_schema = _SampleIn
        uses_self_eval = True

        async def run(self, input: _SampleIn, ctx: AgentContext) -> str:
            seen_feedback.append(ctx.extra.get("critic_feedback"))
            return "answer"

        def _critic(self) -> Critic:
            return Critic(_AlternatingLLM())

    a = _A()
    ctx = AgentContext(
        chain=CallChain.start_root(caller="test"),
        session=agent_tables,
    )
    result = await a.execute({"question": "q"}, ctx)
    assert result.escalated is False
    # First attempt: feedback=None; second attempt: critic reasoning.
    assert seen_feedback == [None, "needs more detail"]


# ── Memory opt-out ─────────────────────────────────────────────────


async def test_memory_helper_works_when_uses_memory_true(
    agent_tables: AsyncSession,
    voyage_disabled: None,
) -> None:
    """uses_memory=True → self.memory(ctx) returns a MemoryStore
    bound to the active session, and writes land in agent_memory."""

    class _A(AgenticBaseAgent[_SampleIn]):
        name = "_test_mem_on"
        description = "x"
        input_schema = _SampleIn
        uses_memory = True

        async def run(self, input: _SampleIn, ctx: AgentContext) -> str:
            from app.agents.primitives import MemoryWrite

            store = self.memory(ctx)
            await store.write(
                MemoryWrite(
                    user_id=ctx.user_id,
                    agent_name=self.name,
                    scope="user",
                    key=f"q:{input.question}",
                    value={"answered": True},
                )
            )
            return "ok"

    a = _A()
    user = uuid.uuid4()
    ctx = AgentContext(
        user_id=user,
        chain=CallChain.start_root(caller="test", user_id=user),
        session=agent_tables,
    )
    result = await a.execute({"question": "what is RAG?"}, ctx)
    assert result.output == "ok"
    raw = await agent_tables.execute(
        sql_text(
            "SELECT count(*) FROM agent_memory WHERE agent_name = "
            "'_test_mem_on'"
        )
    )
    assert raw.scalar_one() == 1


async def test_memory_helper_raises_when_opted_out(
    agent_tables: AsyncSession,
) -> None:
    """uses_memory=False → calling self.memory(ctx) raises so the
    opt-out is enforced at runtime, not just by convention."""

    class _A(AgenticBaseAgent[_SampleIn]):
        name = "_test_mem_off"
        description = "x"
        input_schema = _SampleIn
        uses_memory = False

        async def run(self, input: _SampleIn, ctx: AgentContext) -> str:
            self.memory(ctx)  # should raise
            return "unreachable"

    a = _A()
    ctx = AgentContext(
        chain=CallChain.start_root(caller="test"),
        session=agent_tables,
    )
    with pytest.raises(RuntimeError, match="uses_memory=False"):
        await a.execute({"question": "q"}, ctx)


# ── Tool opt-out ───────────────────────────────────────────────────


async def test_tool_call_helper_raises_when_opted_out(
    agent_tables: AsyncSession,
) -> None:
    class _A(AgenticBaseAgent[_SampleIn]):
        name = "_test_tools_off"
        description = "x"
        input_schema = _SampleIn
        uses_tools = False

        async def run(self, input: _SampleIn, ctx: AgentContext) -> str:
            await self.tool_call("anything", {}, ctx)
            return "unreachable"

    a = _A()
    ctx = AgentContext(
        chain=CallChain.start_root(caller="test"),
        session=agent_tables,
    )
    with pytest.raises(RuntimeError, match="uses_tools=False"):
        await a.execute({"question": "q"}, ctx)


# ── Inter-agent opt-out ────────────────────────────────────────────


async def test_call_helper_raises_when_opted_out(
    agent_tables: AsyncSession,
) -> None:
    class _A(AgenticBaseAgent[_SampleIn]):
        name = "_test_inter_off"
        description = "x"
        input_schema = _SampleIn
        uses_inter_agent = False

        async def run(self, input: _SampleIn, ctx: AgentContext) -> str:
            await self.call("anyone", {}, ctx)
            return "unreachable"

    a = _A()
    ctx = AgentContext(
        chain=CallChain.start_root(caller="test"),
        session=agent_tables,
    )
    with pytest.raises(RuntimeError, match="uses_inter_agent=False"):
        await a.execute({"question": "q"}, ctx)


# ── Inter-agent: agent A calls agent B ─────────────────────────────


async def test_inter_agent_call_threads_chain(
    agent_tables: AsyncSession,
) -> None:
    """Agent A calls agent B via self.call(); the chain root_id
    propagates and both audit rows land under the same root."""

    class _B(AgenticBaseAgent[_SampleIn]):
        name = "_test_inter_b"
        description = "callee"
        input_schema = _SampleIn

        async def run(self, input: _SampleIn, ctx: AgentContext) -> dict:
            return {"echo": input.question}

    class _A(AgenticBaseAgent[_SampleIn]):
        name = "_test_inter_a"
        description = "caller"
        input_schema = _SampleIn

        async def run(self, input: _SampleIn, ctx: AgentContext) -> dict:
            inner = await self.call(
                "_test_inter_b",
                {"question": input.question},
                ctx,
            )
            return {"from_a": True, "b_status": inner.status, "b_output": inner.output}

    a = _A()
    chain = CallChain.start_root(caller="test")
    ctx = AgentContext(chain=chain, session=agent_tables)

    result = await a.execute({"question": "ping"}, ctx)
    assert result.escalated is False
    assert result.output["b_status"] == "ok"
    assert result.output["b_output"] == {"echo": "ping"}

    # One audit row for the inter-agent hop A → B at depth=1 under
    # the root chain's id. A's outer execute() doesn't write a
    # chain row (only call_agent does, and it's only invoked when
    # an agent calls another agent — A itself was invoked directly
    # by the test harness, which is the equivalent of an MOA root
    # dispatch in production). MOA-level audit lands separately
    # in D7b's wiring.
    raw = await agent_tables.execute(
        sql_text(
            "SELECT callee_agent, caller_agent, depth, root_id "
            "FROM agent_call_chain ORDER BY depth"
        )
    )
    rows = raw.all()
    assert len(rows) == 1, (
        f"expected exactly one chain row for the A→B hop, got {rows}"
    )
    callee, caller, depth, root_id = rows[0]
    assert callee == "_test_inter_b"
    # The chain at A's run() carries caller='test' (the original
    # CallChain.start_root caller). When A calls self.call(), the
    # primitive sees caller='test' and writes that into the row.
    assert caller == "test"
    assert depth == 1
    assert root_id == chain.root_id


# ── run_agentic outside call_agent context ─────────────────────────


async def test_run_agentic_without_session_raises(
    agent_tables: AsyncSession,
) -> None:
    """If something tries to invoke run_agentic outside the
    call_agent boundary (no session in contextvar), the agent
    refuses. Real callers always come in through call_agent which
    sets the contextvar."""

    class _A(AgenticBaseAgent[_SampleIn]):
        name = "_test_run_agentic_direct"
        description = "x"
        input_schema = _SampleIn

        async def run(self, input: _SampleIn, ctx: AgentContext) -> str:
            return "ok"

    a = _A()
    chain = CallChain.start_root(caller="test")
    with pytest.raises(RuntimeError, match="outside an active call_agent"):
        await a.run_agentic({"question": "q"}, chain)


# ── Unit-testing without LLM (the spec requirement) ────────────────


async def test_agent_can_be_unit_tested_without_critic(
    agent_tables: AsyncSession,
) -> None:
    """Spec: 'A unit test for "does my agent prompt the LLM correctly?"
    shouldn't need to stand up the critic.' Agents with
    uses_self_eval=False (the default) MUST run end-to-end without
    any critic / LLM dependency.

    We prove it by importing AgenticBaseAgent + executing an agent
    in this test file with no Critic stub, no monkeypatches around
    `Critic.default`, no API key. If the default codepath ever
    starts touching the critic when self-eval is off, this test
    fails."""

    class _A(AgenticBaseAgent[_SampleIn]):
        name = "_test_pure_unit"
        description = "no critic"
        input_schema = _SampleIn
        # uses_self_eval defaults to False — no override needed

        async def run(self, input: _SampleIn, ctx: AgentContext) -> str:
            return f"q={input.question}, style={input.style}"

    a = _A()
    ctx = AgentContext(
        chain=CallChain.start_root(caller="unit_test"),
        session=agent_tables,
    )
    result = await a.execute({"question": "hi", "style": "verbose"}, ctx)
    assert result.output == "q=hi, style=verbose"
    assert result.score is None
    # No agent_evaluations rows (critic never ran).
    raw = await agent_tables.execute(
        sql_text("SELECT count(*) FROM agent_evaluations")
    )
    assert raw.scalar_one() == 0
