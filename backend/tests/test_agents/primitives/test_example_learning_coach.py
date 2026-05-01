"""Reference Learning Coach — three entry points, no live LLM.

The full unit suite runs in CI without `ANTHROPIC_API_KEY` per the
D7 contract. Strategies:

  • Stub `LearningCoach._build_llm` to return a deterministic LLM
    that produces a canned response.
  • Replace the @tool stubs with passing implementations registered
    inline so `tool_call` returns ok with realistic shapes.
  • Use the deterministic hash-fallback embedder for the memory
    layer (the per-test schema fixture handles this).

One separate live-Haiku integration test is `@pytest.mark.skipif`
gated on `ANTHROPIC_API_KEY` — skips cleanly in environments that
don't have the key. Smoke only; not a quality benchmark.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from pydantic import BaseModel
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agentic_base import AgentContext
from app.agents.example_learning_coach import (
    LearningCoach,
    LearningCoachInput,
    _GitHubPushInput,
)
from app.agents.primitives import (
    CallChain,
    Critic,
    EscalationLimiter,
    clear_agentic_registry,
    clear_proactive_registry,
    tool,
    tool_registry,
)
from app.agents.tools.content_tools import (
    CourseContentHit,
    SearchCourseContentInput,
    SearchCourseContentOutput,
)
from app.agents.tools.student_tools import (
    GetStudentStateInput,
    GetStudentStateOutput,
    SendStudentMessageInput,
    SendStudentMessageOutput,
    StudentSnapshot,
)


pytestmark = pytest.mark.asyncio


# ── Fixtures ────────────────────────────────────────────────────────


@pytest_asyncio.fixture(autouse=True)
async def _clean_registries() -> AsyncGenerator[None, None]:
    """Each test starts with empty registries + the LearningCoach
    module loaded. The decorator side effects (`@proactive`,
    `@on_event`, `__init_subclass__`) re-fire when we import the
    module fresh.

    importlib.reload is what re-runs the module body so the
    LearningCoach instance lands in `_agentic_registry` even after
    we cleared it. Without reload, the @register_agentic call from
    LearningCoach's __init_subclass__ would only run on first
    import."""
    import importlib

    import app.agents.example_learning_coach as coach_mod
    import app.agents.tools as tools_pkg
    import app.agents.tools.content_tools as content_tools
    import app.agents.tools.student_tools as student_tools

    def _reload_all() -> None:
        clear_agentic_registry()
        clear_proactive_registry()
        tool_registry.clear()
        import app.agents.primitives.tools as tools_mod

        tools_mod._DISCOVERED = False
        # Reload tools first so the @tool decorators register, THEN
        # the coach so it can find them.
        for mod in (
            student_tools,
            content_tools,
            tools_pkg,
            coach_mod,
        ):
            importlib.reload(mod)

    _reload_all()
    yield
    _reload_all()


@pytest_asyncio.fixture
async def coach_db(pg_session: AsyncSession) -> AsyncSession:
    """Per-test schema with all tables LearningCoach touches:
    agent_memory (from conftest), tools/calls, chain rows, inbox."""
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


# ── Stub LLM (no live API) ─────────────────────────────────────────


@dataclass
class _StubLLM:
    """Stand-in for the agent's main LLM. `responses` is a list of
    strings the stub returns in order; reuses the last item when
    exhausted (so a test that wants 'pass forever' configures one
    string and forgets the call count)."""

    responses: list[str]
    calls: int = 0

    async def ainvoke(self, messages: Any) -> Any:
        idx = min(self.calls, len(self.responses) - 1)
        self.calls += 1

        @dataclass
        class _Resp:
            content: str

        return _Resp(content=self.responses[idx])


def _socratic_response() -> str:
    """A minimally Socratic answer the agent's main path can return
    in tests. Note the question — the system prompt requires one,
    and downstream eval would fail without it."""
    return (
        "Great question. Before I answer, what do you already think the "
        "tradeoff is between latency and accuracy in a RAG system?"
    )


@dataclass
class _CriticStubLLM:
    """Critic-side LLM stub. Same shape as _StubLLM (returns whatever
    string we configured) but its responses are JSON verdicts the
    Critic class will parse. Defined locally so this file is
    self-contained."""

    verdict_json: str
    calls: int = 0

    async def ainvoke_text(self, prompt: str) -> str:
        self.calls += 1
        return self.verdict_json


def _passing_critic() -> Critic:
    """Critic that passes anything at 0.85 — for nightly nudge tests
    that just need to land on the "approved" branch."""
    return Critic(
        _CriticStubLLM(
            verdict_json=(
                '{"accuracy": 0.85, "helpful": 0.85, "complete": 0.85, '
                '"reasoning": "personal and specific"}'
            )
        )
    )


def _failing_critic() -> Critic:
    """Critic that flags drafts as too generic — exercises the
    retry path."""
    return Critic(
        _CriticStubLLM(
            verdict_json=(
                '{"accuracy": 0.30, "helpful": 0.30, "complete": 0.30, '
                '"reasoning": "generic mass-mail copy; no specifics"}'
            )
        )
    )


# ── Helper: register passing tool stubs ────────────────────────────


def _coach_permissions() -> frozenset[str]:
    """Permissions the coach needs across all three paths. Tests
    pass this via `AgentContext(permissions=...)` so the executor's
    permission gate doesn't reject our tool calls. In production
    the surrounding flow (chat handler / proactive runner /
    webhook route) is responsible for setting the right
    permissions on the context it constructs."""
    return frozenset(
        {
            "read:student",
            "read:course_content",
            "read:agent_memory",
            "write:student_inbox",
            "write:agent_memory",
            "write:student_skill_state",
            "write:srs_cards",
        }
    )


def _evict_tool(name: str) -> None:
    """Remove a tool from the registry so a test can re-register
    under the same name. Each individual test that wants a custom
    tool body calls this before its @tool block; the autouse
    fixture reloads the production stubs after each test, so
    leakage doesn't cross test boundaries."""
    tool_registry._tools.pop(name, None)


def _install_passing_tool_stubs() -> None:
    """Replace the production stub tools with passing
    implementations so `tool_call` returns ok status with
    realistic shapes. Tests that want to exercise the
    stub-error path skip this and inherit the registered
    NotImplementedError stubs.

    The autouse fixture's reload runs the production stubs first;
    we clear the three names we're about to redeclare so the
    @tool decorator's duplicate-name guard doesn't trip. Other
    tools (recall_memory, run_ruff, …) stay as their production
    stubs — the agent doesn't call them, so it doesn't matter."""
    for name in ("get_student_state", "search_course_content", "send_student_message"):
        tool_registry._tools.pop(name, None)

    @tool(
        name="get_student_state",
        description="passing test stub",
        input_schema=GetStudentStateInput,
        output_schema=GetStudentStateOutput,
        requires=("read:student",),
    )
    async def _stub_get_state(args: GetStudentStateInput) -> GetStudentStateOutput:
        return GetStudentStateOutput(
            snapshot=StudentSnapshot(
                user_id=args.user_id,
                full_name="Test Student",
                is_active=True,
                days_since_signup=14,
                days_since_last_login=2,
                overall_progress_pct=55.0,
                active_course_title="Production RAG",
                skill_summary={"rag": "proficient", "langgraph": "novice"},
            )
        )

    @tool(
        name="search_course_content",
        description="passing test stub",
        input_schema=SearchCourseContentInput,
        output_schema=SearchCourseContentOutput,
        requires=("read:course_content",),
    )
    async def _stub_search(
        args: SearchCourseContentInput,
    ) -> SearchCourseContentOutput:
        return SearchCourseContentOutput(
            hits=[
                CourseContentHit(
                    lesson_id=uuid.uuid4(),
                    lesson_title="Hybrid retrieval — semantic + structured",
                    snippet=(
                        "RAG combines a vector search step over chunked "
                        "documents with an LLM generation step grounded "
                        "in the retrieved excerpts."
                    ),
                    score=0.91,
                )
            ],
            used_index="test:stub",
        )

    @tool(
        name="send_student_message",
        description="passing test stub",
        input_schema=SendStudentMessageInput,
        output_schema=SendStudentMessageOutput,
        requires=("write:student_inbox",),
    )
    async def _stub_send(
        args: SendStudentMessageInput,
    ) -> SendStudentMessageOutput:
        return SendStudentMessageOutput(
            inbox_id=uuid.uuid4(),
            deduped=False,
        )


# ── Auto-registration ─────────────────────────────────────────────


async def test_learning_coach_auto_registers_with_agentic_registry() -> None:
    """The class definition runs `__init_subclass__` which calls
    `register_agentic`. Re-importing the module after a clear
    re-fires that side effect. Test asserts both the registry has
    the entry and the @proactive decorator side effect (a
    ProactiveSchedule entry) lands."""
    from app.agents.primitives import list_agentic, list_schedules, list_subscriptions

    assert "learning_coach" in list_agentic()
    schedules = [s for s in list_schedules() if s.agent_name == "learning_coach"]
    assert len(schedules) == 1
    assert schedules[0].cron == "0 9 * * *"
    assert schedules[0].per_user is True

    push_subs = [
        s for s in list_subscriptions("github.push") if s.agent_name == "learning_coach"
    ]
    assert len(push_subs) == 1


# ── Chat path ──────────────────────────────────────────────────────


async def test_chat_path_grounds_response_with_memory_and_tools(
    coach_db: AsyncSession,
    voyage_disabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full chat flow without an LLM:
      1. Pre-populate a memory row about the student.
      2. Install passing tool stubs.
      3. Stub the agent's main LLM to return a Socratic response.
      4. Call execute(), assert response shape + tool calls landed.
    """
    _install_passing_tool_stubs()

    from app.agents.primitives import list_agentic
    coach: LearningCoach = list_agentic()  # type: ignore[assignment]
    # `list_agentic()` returns names; fetch the instance.
    from app.agents.primitives import get_agentic
    coach = get_agentic("learning_coach")  # type: ignore[assignment]

    # Pre-seed a memory row.
    user = uuid.uuid4()
    chain = CallChain.start_root(caller="chat", user_id=user)
    ctx = AgentContext(
        user_id=user,
        chain=chain,
        session=coach_db,
        permissions=_coach_permissions(),
    )
    from app.agents.primitives.memory import MemoryStore, MemoryWrite

    await MemoryStore(coach_db).write(
        MemoryWrite(
            user_id=user,
            agent_name="learning_coach",
            scope="user",
            key="accessibility:dyslexic",
            value={"observed_at": "2026-04-01T12:00:00Z"},
        )
    )

    # Patch the agent's LLM factory to return a stub.
    monkeypatch.setattr(
        type(coach),
        "_build_llm",
        lambda self, *, max_tokens=1024: _StubLLM(responses=[_socratic_response()]),
    )

    result = await coach.execute(
        {"question": "How does RAG actually work?"},
        ctx,
    )

    # Output shape from `run()`.
    assert result.output["had_course_grounding"] is True
    assert result.output["memories_used"] >= 1
    assert "?" in result.output["answer"]  # Socratic — must have a question

    # Tool calls landed in audit.
    raw = await coach_db.execute(
        sql_text(
            "SELECT tool_name, status FROM agent_tool_calls "
            "ORDER BY tool_name"
        )
    )
    tool_rows = raw.all()
    tool_names = [r[0] for r in tool_rows]
    assert "get_student_state" in tool_names
    assert "search_course_content" in tool_names
    assert {r[1] for r in tool_rows} == {"ok"}


async def test_chat_path_records_dyslexia_preference(
    coach_db: AsyncSession,
    voyage_disabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The preference detector observes 'dyslexic' in the question
    and writes a memory row keyed `accessibility:dyslexic`. Same
    pattern for other trigger phrases."""
    _install_passing_tool_stubs()
    from app.agents.primitives import get_agentic

    coach = get_agentic("learning_coach")
    monkeypatch.setattr(
        type(coach),
        "_build_llm",
        lambda self, *, max_tokens=1024: _StubLLM(responses=[_socratic_response()]),
    )

    user = uuid.uuid4()
    ctx = AgentContext(
        user_id=user,
        chain=CallChain.start_root(caller="chat", user_id=user),
        session=coach_db,
        permissions=_coach_permissions(),
    )
    await coach.execute(
        {
            "question": (
                "I'm dyslexic — can you walk me through async/await "
                "with concrete code?"
            )
        },
        ctx,
    )
    raw = await coach_db.execute(
        sql_text(
            "SELECT key FROM agent_memory "
            "WHERE agent_name = 'learning_coach' "
            "AND user_id = :u ORDER BY key"
        ),
        {"u": user},
    )
    keys = [r[0] for r in raw.all()]
    assert "accessibility:dyslexic" in keys


async def test_chat_path_degrades_gracefully_when_tools_stub(
    coach_db: AsyncSession,
    voyage_disabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without `_install_passing_tool_stubs`, the registered tools
    raise NotImplementedError. The executor catches and returns
    status='error'. The agent's helpers (`_fetch_student_state`,
    `_search_relevant_content`) treat that as 'no data' and the
    chat path still answers from prompt + memory only.

    This is what 'production behaviour upgrades automatically when
    stubs land' actually means in practice — the agent works today,
    and works *better* after D-future stub fills."""
    from app.agents.primitives import get_agentic

    coach = get_agentic("learning_coach")
    monkeypatch.setattr(
        type(coach),
        "_build_llm",
        lambda self, *, max_tokens=1024: _StubLLM(responses=[_socratic_response()]),
    )
    user = uuid.uuid4()
    ctx = AgentContext(
        user_id=user,
        chain=CallChain.start_root(caller="chat", user_id=user),
        session=coach_db,
        permissions=_coach_permissions(),
    )
    result = await coach.execute({"question": "what is RAG?"}, ctx)
    # Tools failed but the chat path still produced a response.
    assert "?" in result.output["answer"]
    assert result.output["had_course_grounding"] is False
    assert result.output["memories_used"] == 0


# ── Webhook path ───────────────────────────────────────────────────


async def test_github_push_path_writes_memory_and_inbox_card(
    coach_db: AsyncSession,
    voyage_disabled: None,
) -> None:
    """When the @on_event handler dispatches a GitHub push to the
    Coach, we expect:
      • A memory row keyed `shipped:<repo>:<short_sha>`
      • An inbox card via `send_student_message`
    """
    _install_passing_tool_stubs()
    from app.agents.primitives import get_agentic

    coach = get_agentic("learning_coach")

    user = uuid.uuid4()
    ctx = AgentContext(
        user_id=user,
        chain=CallChain.start_root(caller="webhook:github", user_id=user),
        session=coach_db,
        permissions=_coach_permissions(),
    )
    payload = _GitHubPushInput(
        repo="alice/genai-capstone",
        commit_sha="deadbeefcafebabe1234567890abcdef12345678",
        pusher_login="alice",
        branch="main",
        files_changed=["src/agent.py", "tests/test_agent.py"],
    )
    out = await coach.run_on_github_push(payload, ctx)
    assert out["memory_written"] is True
    assert out["inbox_status"] == "ok"

    # Memory row with the expected key shape.
    raw = await coach_db.execute(
        sql_text(
            "SELECT key, value FROM agent_memory "
            "WHERE agent_name = 'learning_coach' AND user_id = :u"
        ),
        {"u": user},
    )
    rows = raw.all()
    assert len(rows) == 1
    assert rows[0][0].startswith("shipped:alice/genai-capstone:")
    assert rows[0][1]["branch"] == "main"
    assert rows[0][1]["files_changed"] == ["src/agent.py", "tests/test_agent.py"]

    # Inbox card landed via the tool — visible in agent_tool_calls.
    raw = await coach_db.execute(
        sql_text(
            "SELECT args FROM agent_tool_calls "
            "WHERE tool_name = 'send_student_message'"
        )
    )
    args_rows = raw.all()
    assert len(args_rows) == 1
    args = args_rows[0][0]
    assert args["kind"] == "celebration"
    assert args["idempotency_key"].startswith("push:deadbeefcafebabe")


# ── Proactive nightly path ─────────────────────────────────────────


async def test_nightly_check_skips_when_no_slip(
    coach_db: AsyncSession,
    voyage_disabled: None,
) -> None:
    """When `_detect_slip` returns None (student on track), the
    nightly check returns early with `action='no_action_needed'` —
    no tool calls, no inbox card, no critic invocation."""
    # Don't install passing tool stubs — get_student_state will
    # error, _detect_slip gets {}, returns None.
    from app.agents.primitives import get_agentic

    coach = get_agentic("learning_coach")
    user = uuid.uuid4()
    ctx = AgentContext(
        user_id=user,
        chain=CallChain.start_root(caller="proactive:cron", user_id=user),
        session=coach_db,
        permissions=_coach_permissions(),
    )
    result = await coach.run_nightly_check(user, ctx)
    assert result.escalated is False
    assert result.output["action"] == "no_action_needed"


async def test_nightly_check_drafts_personalised_nudge(
    coach_db: AsyncSession,
    voyage_disabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a slip is detected (we install stubs that report
    days_since_last_login=10 → streak_broken), the Coach drafts a
    nudge, the (passing) critic approves, and the inbox card lands."""
    _evict_tool("get_student_state")
    _evict_tool("send_student_message")

    @tool(
        name="get_student_state",
        description="slip simulator",
        input_schema=GetStudentStateInput,
        output_schema=GetStudentStateOutput,
        requires=("read:student",),
    )
    async def _slipping_state(
        args: GetStudentStateInput,
    ) -> GetStudentStateOutput:
        return GetStudentStateOutput(
            snapshot=StudentSnapshot(
                user_id=args.user_id,
                full_name="Slipping Student",
                is_active=True,
                overall_progress_pct=30.0,
                days_since_last_login=10,  # > 7 → streak_broken
            )
        )

    @tool(
        name="send_student_message",
        description="passing test stub",
        input_schema=SendStudentMessageInput,
        output_schema=SendStudentMessageOutput,
        requires=("write:student_inbox",),
    )
    async def _send(
        args: SendStudentMessageInput,
    ) -> SendStudentMessageOutput:
        return SendStudentMessageOutput(
            inbox_id=uuid.uuid4(),
            deduped=False,
        )

    from app.agents.primitives import get_agentic

    coach = get_agentic("learning_coach")
    monkeypatch.setattr(
        type(coach),
        "_build_llm",
        lambda self, *, max_tokens=1024: _StubLLM(
            responses=[
                "Heya — I noticed you stepped away from RAG this week. "
                "When you're back, want to pick up where we left off "
                "on hybrid retrieval?"
            ]
        ),
    )
    monkeypatch.setattr(
        type(coach), "_critic", lambda self: _passing_critic()
    )
    # Use a fresh limiter so this test is unaffected by other
    # tests' rate-limit state.
    monkeypatch.setattr(
        type(coach),
        "_limiter",
        lambda self: EscalationLimiter(limit_per_agent=10, window_seconds=60),
    )

    user = uuid.uuid4()
    ctx = AgentContext(
        user_id=user,
        chain=CallChain.start_root(caller="proactive:cron", user_id=user),
        session=coach_db,
        permissions=_coach_permissions(),
    )
    result = await coach.run_nightly_check(user, ctx)
    assert result.escalated is False
    assert result.score is not None and result.score >= 0.85

    # Inbox card landed.
    raw = await coach_db.execute(
        sql_text(
            "SELECT args FROM agent_tool_calls "
            "WHERE tool_name = 'send_student_message'"
        )
    )
    rows = raw.all()
    assert len(rows) == 1
    assert rows[0][0]["kind"] == "nudge"
    assert "nightly:streak_broken:" in rows[0][0]["idempotency_key"]


async def test_nightly_check_escalates_on_generic_drafts(
    coach_db: AsyncSession,
    voyage_disabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point of self-eval on the nightly path: a generic
    draft (no specifics) gets a low score from the critic and
    escalates after the retry budget. The inbox card MUST NOT
    land for an escalated nudge — the audit row carries the best
    attempt for admin review."""
    _evict_tool("get_student_state")
    _evict_tool("send_student_message")

    @tool(
        name="get_student_state",
        description="slip simulator",
        input_schema=GetStudentStateInput,
        output_schema=GetStudentStateOutput,
        requires=("read:student",),
    )
    async def _slipping_state(
        args: GetStudentStateInput,
    ) -> GetStudentStateOutput:
        return GetStudentStateOutput(
            snapshot=StudentSnapshot(
                user_id=args.user_id,
                full_name="X",
                is_active=True,
                overall_progress_pct=20.0,
                days_since_last_login=14,
            )
        )

    @tool(
        name="send_student_message",
        description="passing test stub",
        input_schema=SendStudentMessageInput,
        output_schema=SendStudentMessageOutput,
        requires=("write:student_inbox",),
    )
    async def _send(
        args: SendStudentMessageInput,
    ) -> SendStudentMessageOutput:
        return SendStudentMessageOutput(
            inbox_id=uuid.uuid4(), deduped=False
        )

    from app.agents.primitives import get_agentic

    coach = get_agentic("learning_coach")
    monkeypatch.setattr(
        type(coach),
        "_build_llm",
        lambda self, *, max_tokens=1024: _StubLLM(
            responses=["Hi there. Just checking in."]
        ),
    )
    monkeypatch.setattr(
        type(coach), "_critic", lambda self: _failing_critic()
    )
    monkeypatch.setattr(
        type(coach),
        "_limiter",
        lambda self: EscalationLimiter(limit_per_agent=10, window_seconds=60),
    )

    user = uuid.uuid4()
    ctx = AgentContext(
        user_id=user,
        chain=CallChain.start_root(caller="proactive:cron", user_id=user),
        session=coach_db,
        permissions=_coach_permissions(),
    )
    result = await coach.run_nightly_check(user, ctx)
    assert result.escalated is True
    # No inbox card — escalated nudges aren't sent to students.
    raw = await coach_db.execute(
        sql_text(
            "SELECT count(*) FROM agent_tool_calls "
            "WHERE tool_name = 'send_student_message'"
        )
    )
    assert raw.scalar_one() == 0
    # Escalation row landed.
    raw = await coach_db.execute(
        sql_text("SELECT count(*) FROM agent_escalations")
    )
    assert raw.scalar_one() >= 1


# ── Live integration (skipped without ANTHROPIC_API_KEY) ───────────


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="live LLM integration test — set ANTHROPIC_API_KEY to enable",
)
async def test_chat_path_smoke_with_live_haiku(
    coach_db: AsyncSession,
    voyage_disabled: None,
) -> None:
    """ONE live test — hits Haiku, asserts only that we get a
    string back. Not a quality benchmark; the goal is to catch
    'we wired up build_llm wrong' errors that the unit suite
    can't see (because it stubs the LLM).

    Skipped in CI without the API key. Local dev runs it with
    `ANTHROPIC_API_KEY=...`.
    """
    _install_passing_tool_stubs()
    from app.agents.primitives import get_agentic

    coach = get_agentic("learning_coach")
    user = uuid.uuid4()
    ctx = AgentContext(
        user_id=user,
        chain=CallChain.start_root(caller="chat_live", user_id=user),
        session=coach_db,
        permissions=_coach_permissions(),
    )
    result = await coach.execute(
        {"question": "What's the difference between memoization and caching?"},
        ctx,
    )
    assert isinstance(result.output["answer"], str)
    assert len(result.output["answer"]) > 20
