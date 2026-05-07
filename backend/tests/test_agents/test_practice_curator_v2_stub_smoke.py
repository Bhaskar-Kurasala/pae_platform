"""D14b CP2 — stub-LLM smoke tests for practice_curator_v2.

Drives PracticeCuratorAgent.run() end-to-end with:
  • a stub LLM that returns a hardcoded PracticeCuratorOutput JSON
  • a stub MemoryStore + tool stubs so memory_recall + DB read tools
    fire through the real tool machinery without needing Postgres

Verifies, for the five exercise types + key invariants:
  • dispatch reaches the agent
  • memory_recall fires BEFORE the LLM call (target_role + weakness recalls)
  • DB reads fire BEFORE the LLM call (read_student_full_progress + read_recent_session_history)
  • the parser handles dict-shape MiniMax-style content blocks
  • truncate_to_schema clips overshoots (Bug 17 regression)
  • strip_extra_fields drops top-level extras (Bug 23 regression)
  • all 3 difficulty levels round-trip
  • handoff_request gated by D11 Option B (only when student requests evaluation)
  • HandoffRequest.suggested_context is dict, not string (Bug 21 regression)
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agentic_base import AgentContext, CallChain
from app.agents.practice_curator import PracticeCuratorAgent
from app.agents.primitives.communication import _active_session
from app.agents.primitives.tools import ensure_tools_loaded
from app.schemas.agents.practice_curator import PracticeCuratorInput
from app.schemas.supervisor import HandoffRequest

# Pattern 16 (D13 closure): real-LLM/integration test fixtures must
# populate the tool registry. The agent loader populates the agent
# registry but NOT the tool registry; ensure_tools_loaded() is the
# canonical second loader. Module-level so it fires once per test run.
ensure_tools_loaded()

pytestmark: list = []


# ── Test doubles ───────────────────────────────────────────────────


class _StubResponse:
    """LangChain ainvoke()-shape response with dict-style content blocks
    (MiniMax Anthropic-compatible endpoint shape — exercises Bug 10a)."""

    def __init__(self, json_text: str) -> None:
        self.content = [
            {"type": "thinking", "thinking": "internal reasoning skipped"},
            {"type": "text", "text": json_text},
        ]
        self.usage_metadata = {"input_tokens": 100, "output_tokens": 50}


class _StubLLM:
    def __init__(self, json_text: str) -> None:
        self._json_text = json_text
        self.calls: list[list[dict[str, str]]] = []

    async def ainvoke(self, messages: Any, **_: Any) -> _StubResponse:
        self.calls.append(messages)
        return _StubResponse(self._json_text)


class _StubMemoryStore:
    """In-memory MemoryStore replacement."""

    def __init__(self) -> None:
        self.recall_calls: list[dict[str, Any]] = []

    async def recall(
        self, query: str, *, user_id: Any = None, agent_name: str | None = None,
        scope: str | None = None, k: int = 5, mode: str = "hybrid",
        min_similarity: float | None = None,
    ) -> list[Any]:
        self.recall_calls.append({"query": query, "mode": mode, "k": k})
        return []  # default empty; tests can override

    async def write(self, mw: Any) -> Any:  # not used by curator (single-shot)
        row = MagicMock()
        row.id = uuid.uuid4()
        return row

    async def _find_one(self, **_: Any) -> Any:
        return None


# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def stub_session() -> Any:
    return MagicMock(spec=AsyncSession)


@pytest.fixture
def stub_ctx(stub_session: Any) -> AgentContext:
    """Test ctx with a user_id set. Curator's run() passes ctx.user_id
    into the D12-audited DB read tools; those tools' input schemas
    require student_id, so a real UUID is needed even when the tools
    are stubbed (the input validation runs before the stub func)."""
    return AgentContext(
        user_id=uuid.uuid4(),
        chain=CallChain.start_root(caller="test"),
        session=stub_session,
        extra={"_llm_usage": []},
    )


@pytest.fixture
def patch_active_session(stub_session: Any):
    token = _active_session.set(stub_session)
    yield
    _active_session.reset(token)


@pytest.fixture
def stub_store(monkeypatch: pytest.MonkeyPatch) -> _StubMemoryStore:
    store = _StubMemoryStore()
    monkeypatch.setattr(
        "app.agents.tools.universal.memory_recall.MemoryStore", lambda _s: store
    )
    monkeypatch.setattr(
        "app.agents.tools.universal.memory_write.MemoryStore", lambda _s: store
    )
    return store


@pytest.fixture
def patch_db_tools(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Stub the D12-audited DB read tools to return empty results.
    Recorded in the dict so tests can assert they were invoked."""
    invocations: dict[str, list[Any]] = {
        "read_student_full_progress": [],
        "read_recent_session_history": [],
    }

    async def _stub_progress(args: Any) -> Any:
        invocations["read_student_full_progress"].append(args)
        from app.agents.tools.agent_specific.career_coach.read_student_full_progress import (
            ReadStudentFullProgressOutput,
        )
        return ReadStudentFullProgressOutput(
            courses=[],
            total_lessons_completed=0,
            total_exercise_submissions=0,
        )

    async def _stub_history(args: Any) -> Any:
        invocations["read_recent_session_history"].append(args)
        from app.agents.tools.agent_specific.study_planner.read_recent_session_history import (
            ReadRecentSessionHistoryOutput,
        )
        return ReadRecentSessionHistoryOutput(
            sessions=[],
            days_with_activity=0,
        )

    # ToolSpec is a frozen dataclass; replace the entire entry in the
    # registry's _tools dict with a copy that has the stub func.
    from dataclasses import replace
    from app.agents.primitives.tools import registry

    progress_spec = registry.get("read_student_full_progress")
    history_spec = registry.get("read_recent_session_history")

    new_progress = replace(progress_spec, func=_stub_progress)
    new_history = replace(history_spec, func=_stub_history)

    monkeypatch.setitem(
        registry._tools, "read_student_full_progress", new_progress
    )
    monkeypatch.setitem(
        registry._tools, "read_recent_session_history", new_history
    )
    return invocations


@pytest.fixture
def patch_llm(monkeypatch: pytest.MonkeyPatch):
    def _install(json_text: str) -> _StubLLM:
        stub = _StubLLM(json_text)
        monkeypatch.setattr(
            "app.agents.llm_factory.build_llm",
            lambda **_kw: stub,
        )
        return stub

    return _install


@pytest.fixture
def patch_executor_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    """ToolExecutor writes audit rows to agent_tool_calls; without
    Postgres backing, that insert blows up. Patch the audit-write
    helper to a no-op."""
    async def _noop(*_args: Any, **_kw: Any) -> None:
        return None

    monkeypatch.setattr(
        "app.agents.primitives.tools.ToolExecutor._record_tool_call",
        _noop,
        raising=False,
    )


# ── JSON output fixtures ───────────────────────────────────────────


def _make_output(
    *,
    title: str = "Recursion drill",
    difficulty: str = "easy",
    description: str = "Implement factorial recursively.",
    starter_code: str | None = "def factorial(n):\n    pass",
    handoff_request: dict | None = None,
    extra_top_level: dict | None = None,
) -> str:
    """Build a valid PracticeCuratorOutput dict with optional shape drift."""
    payload: dict[str, Any] = {
        "exercise": {
            "title": title,
            "concept_tags": ["recursion"],
            "difficulty": difficulty,
            "description": description,
            "constraints": ["Must use recursion, not iteration."],
            "test_cases_visible": [
                {"input_description": "n=0", "expected_output_description": "1"},
                {"input_description": "n=5", "expected_output_description": "120"},
            ],
            "test_cases_hidden": [
                {"input_description": "n=10", "expected_output_description": "3628800"},
            ],
        },
        "starter_code": starter_code,
        "expected_solution_shape": "A recursive function with base case + reduction step.",
        "evaluation_criteria": [
            "Handles n=0 correctly (base case)",
            "Uses recursion not iteration",
            "Doesn't call itself unboundedly",
        ],
        "hint_sequence": [
            {"order": 1, "text": "What's the simplest case where you don't recurse?"},
            {"order": 2, "text": "Once you have the base case, what's the reduction step?"},
        ],
        "estimated_time_minutes": 20 if difficulty == "easy" else (45 if difficulty == "medium" else 90),
        "handoff_request": handoff_request,
    }
    if extra_top_level:
        payload.update(extra_top_level)
    return json.dumps(payload)


# ── Tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_easy_coding(
    stub_ctx: AgentContext,
    patch_active_session: None,
    stub_store: _StubMemoryStore,
    patch_db_tools: dict[str, list[Any]],
    patch_executor_audit: None,
    patch_llm: Any,
) -> None:
    """Easy coding exercise round-trips cleanly. Memory recalls fire,
    DB reads fire, LLM returns valid output, schema validates."""
    stub = patch_llm(_make_output(difficulty="easy"))

    agent = PracticeCuratorAgent()
    inp = PracticeCuratorInput(
        concept_focus="recursion",
        exercise_type="coding",
        difficulty_level="easy",
    )
    payload = await agent.run(inp, stub_ctx)

    # Both memory recalls fired (target_role + weaknesses).
    queries = [c["query"] for c in stub_store.recall_calls]
    assert any("pref:target_role" in q for q in queries)
    assert any("mock_interview:weakness:" in q for q in queries)

    # Both DB reads fired.
    assert len(patch_db_tools["read_student_full_progress"]) == 1
    assert len(patch_db_tools["read_recent_session_history"]) == 1

    # LLM was called.
    assert len(stub.calls) == 1

    # Output schema validates and matches the stub.
    assert payload["exercise"]["difficulty"] == "easy"
    assert "answer" in payload
    assert "Recursion drill" in payload["answer"]
    assert payload["handoff_request"] is None  # default — student didn't request


@pytest.mark.asyncio
async def test_happy_path_hard_system_design(
    stub_ctx: AgentContext,
    patch_active_session: None,
    stub_store: _StubMemoryStore,
    patch_db_tools: dict[str, list[Any]],
    patch_executor_audit: None,
    patch_llm: Any,
) -> None:
    """Hard system_design with starter_code=None — schema accepts."""
    patch_llm(_make_output(
        difficulty="hard",
        title="Design a multi-tenant inference gateway",
        starter_code=None,
    ))

    agent = PracticeCuratorAgent()
    inp = PracticeCuratorInput(
        exercise_type="system_design",
        difficulty_level="hard",
    )
    payload = await agent.run(inp, stub_ctx)
    assert payload["exercise"]["difficulty"] == "hard"
    assert payload["starter_code"] is None
    assert payload["estimated_time_minutes"] == 90


@pytest.mark.asyncio
async def test_strip_extra_fields_drops_top_level_drift(
    stub_ctx: AgentContext,
    patch_active_session: None,
    stub_store: _StubMemoryStore,
    patch_db_tools: dict[str, list[Any]],
    patch_executor_audit: None,
    patch_llm: Any,
) -> None:
    """Bug 23 regression: LLM emits a rogue top-level field;
    strip_extra_fields drops it before validation."""
    patch_llm(_make_output(
        extra_top_level={"rogue_top_level": "should be dropped"},
    ))

    agent = PracticeCuratorAgent()
    inp = PracticeCuratorInput(concept_focus="recursion")
    payload = await agent.run(inp, stub_ctx)

    # No ValidationError raised → strip_extra_fields handled it.
    assert payload["exercise"]["difficulty"] == "easy"
    assert "rogue_top_level" not in payload  # dropped at strip stage


@pytest.mark.asyncio
async def test_truncate_to_schema_clips_long_description(
    stub_ctx: AgentContext,
    patch_active_session: None,
    stub_store: _StubMemoryStore,
    patch_db_tools: dict[str, list[Any]],
    patch_executor_audit: None,
    patch_llm: Any,
) -> None:
    """Bug 17 regression: LLM emits 5000-char description (over 3000
    cap); truncate_to_schema clips before validation."""
    long_desc = "x" * 5000
    patch_llm(_make_output(description=long_desc))

    agent = PracticeCuratorAgent()
    inp = PracticeCuratorInput()
    payload = await agent.run(inp, stub_ctx)

    # Truncated to 3000 chars.
    assert len(payload["exercise"]["description"]) == 3000


@pytest.mark.asyncio
async def test_handoff_request_gated_to_evaluation_intent(
    stub_ctx: AgentContext,
    patch_active_session: None,
    stub_store: _StubMemoryStore,
    patch_db_tools: dict[str, list[Any]],
    patch_executor_audit: None,
    patch_llm: Any,
) -> None:
    """D11 Option B + D14b runtime backstop: when LLM emits a handoff
    but student didn't request evaluation, agent forces handoff_request=None."""
    patch_llm(_make_output(
        handoff_request={
            "target_agent": "senior_engineer",
            "reason": "leak from a curator that wasn't asked to evaluate",
            "suggested_context": {"exercise_id": "x"},
            "handoff_type": "suggested",
        },
    ))

    agent = PracticeCuratorAgent()
    # No "evaluate" / "review" / "grade" in user_message.
    inp = PracticeCuratorInput(user_message="Just give me a quick drill.")
    payload = await agent.run(inp, stub_ctx)

    # Defense-in-depth coerced to None.
    assert payload["handoff_request"] is None


@pytest.mark.asyncio
async def test_handoff_request_preserved_when_evaluation_requested(
    stub_ctx: AgentContext,
    patch_active_session: None,
    stub_store: _StubMemoryStore,
    patch_db_tools: dict[str, list[Any]],
    patch_executor_audit: None,
    patch_llm: Any,
) -> None:
    """When student message DOES request evaluation, the handoff
    survives the runtime backstop. Bug 21 regression: suggested_context
    is dict, not string."""
    patch_llm(_make_output(
        handoff_request={
            "target_agent": "senior_engineer",
            "reason": "Student asked for code review post-attempt.",
            "suggested_context": {
                "concept_tags": ["recursion"],
                "exercise_id": "ex_001",
            },
            "handoff_type": "suggested",
        },
    ))

    agent = PracticeCuratorAgent()
    inp = PracticeCuratorInput(
        user_message="Give me a coding exercise and have it evaluated when I'm done."
    )
    payload = await agent.run(inp, stub_ctx)

    hr = payload["handoff_request"]
    assert hr is not None
    # Validates against Supervisor's HandoffRequest contract (D-2 integration).
    validated = HandoffRequest.model_validate(hr)
    assert validated.target_agent == "senior_engineer"
    assert validated.handoff_type == "suggested"
    # Bug 21 invariant: suggested_context is a dict, not a string.
    assert isinstance(validated.suggested_context, dict)
    assert validated.suggested_context["concept_tags"] == ["recursion"]


@pytest.mark.asyncio
async def test_all_difficulties_round_trip(
    stub_ctx: AgentContext,
    patch_active_session: None,
    stub_store: _StubMemoryStore,
    patch_db_tools: dict[str, list[Any]],
    patch_executor_audit: None,
    patch_llm: Any,
) -> None:
    """easy / medium / hard all validate cleanly through the pipeline."""
    for difficulty in ("easy", "medium", "hard"):
        patch_llm(_make_output(difficulty=difficulty))
        agent = PracticeCuratorAgent()
        inp = PracticeCuratorInput(difficulty_level=difficulty)
        payload = await agent.run(inp, stub_ctx)
        assert payload["exercise"]["difficulty"] == difficulty


@pytest.mark.asyncio
async def test_recall_results_threaded_into_user_block(
    stub_ctx: AgentContext,
    patch_active_session: None,
    monkeypatch: pytest.MonkeyPatch,
    patch_db_tools: dict[str, list[Any]],
    patch_executor_audit: None,
    patch_llm: Any,
) -> None:
    """Memory recall results land in the user_block sent to the LLM.
    Specifically: weakness topics from cross-session recall surface."""
    # Custom store that returns weakness rows for the weakness recall.
    class _StoreWithWeaknesses(_StubMemoryStore):
        async def recall(self, query: str, **_: Any) -> list[Any]:
            self.recall_calls.append({"query": query})
            if "weakness" in query:
                row = MagicMock()
                row.id = uuid.uuid4()
                row.user_id = None
                row.agent_name = "mock_interview"
                row.scope = "user"
                row.key = "mock_interview:weakness:graph_algorithms"
                row.value = {"topic": "graph_algorithms", "source": "session_summary"}
                row.valence = -0.4
                row.confidence = 0.7
                row.similarity = None
                return [row]
            return []

    store = _StoreWithWeaknesses()
    monkeypatch.setattr(
        "app.agents.tools.universal.memory_recall.MemoryStore", lambda _s: store
    )

    stub = patch_llm(_make_output())
    agent = PracticeCuratorAgent()
    inp = PracticeCuratorInput()
    await agent.run(inp, stub_ctx)

    # The user_block (second message) should mention graph_algorithms.
    user_block = stub.calls[0][1]["content"]
    assert "Cross-session weaknesses" in user_block
    assert "graph_algorithms" in user_block


@pytest.mark.asyncio
async def test_tool_call_ordering_recalls_before_llm(
    stub_ctx: AgentContext,
    patch_active_session: None,
    stub_store: _StubMemoryStore,
    patch_db_tools: dict[str, list[Any]],
    patch_executor_audit: None,
    patch_llm: Any,
) -> None:
    """Sanity: the LLM call is the LAST step. By the time the LLM is
    invoked, both recalls + both DB reads must have fired. Single
    LLM call per run() (no retries on stub-smoke since uses_self_eval=False)."""
    stub = patch_llm(_make_output())
    agent = PracticeCuratorAgent()
    inp = PracticeCuratorInput(concept_focus="x")
    await agent.run(inp, stub_ctx)

    # 2 memory recalls + 2 DB reads happened, then 1 LLM call.
    assert len(stub_store.recall_calls) == 2
    assert len(patch_db_tools["read_student_full_progress"]) == 1
    assert len(patch_db_tools["read_recent_session_history"]) == 1
    assert len(stub.calls) == 1


@pytest.mark.asyncio
async def test_caller_constraints_threaded_into_user_block(
    stub_ctx: AgentContext,
    patch_active_session: None,
    stub_store: _StubMemoryStore,
    patch_db_tools: dict[str, list[Any]],
    patch_executor_audit: None,
    patch_llm: Any,
) -> None:
    """Caller-supplied constraints (concept_focus, exercise_type,
    difficulty_level) appear in the user_block."""
    stub = patch_llm(_make_output(difficulty="medium"))
    agent = PracticeCuratorAgent()
    inp = PracticeCuratorInput(
        concept_focus="vector_indexing",
        exercise_type="prompt_engineering",
        difficulty_level="medium",
    )
    await agent.run(inp, stub_ctx)

    user_block = stub.calls[0][1]["content"]
    assert "vector_indexing" in user_block
    assert "prompt_engineering" in user_block
    assert "medium" in user_block
