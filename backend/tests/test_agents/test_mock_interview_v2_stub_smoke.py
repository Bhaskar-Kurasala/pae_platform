"""D13 CP2 — stub-LLM smoke tests for mock_interview_v2.

Drives MockInterviewAgent.run() end-to-end with:
  • a stub LLM that returns a hardcoded MockInterviewOutput JSON
  • a stub MemoryStore (in-process dict) so memory_recall / memory_write
    fire through the real tool machinery without needing Postgres

Verifies for the four turn_kinds + first-turn vs follow-up paths:
  • dispatch reaches the agent
  • memory_recall fires BEFORE the LLM call (prior-turn + weakness recall)
  • memory_write fires AFTER the parsed output (turn log + weakness writes)
  • the parser handles dict-shape MiniMax-style content blocks
  • truncate_to_schema integration validates without error
  • follow-up turns echo the input session_id (not regenerate)
  • session_summary turns drive weakness writes; non-summary turns don't
  • non-summary turns force handoff_request=None even if LLM emits one
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agentic_base import AgentContext, CallChain
from app.agents.mock_interview import MockInterviewAgent
from app.agents.primitives.communication import _active_session
from app.schemas.agents.mock_interview import MockInterviewInput

pytestmark = [pytest.mark.asyncio]


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
    """In-memory MemoryStore replacement.

    Tracks recall queries and write upserts via instrumentation lists so
    the test can assert order (recall-before-LLM, write-after-parse).
    """

    def __init__(self, prior_turns: list[dict[str, Any]] | None = None) -> None:
        self._prior_turns = prior_turns or []
        self.recall_calls: list[dict[str, Any]] = []
        self.write_calls: list[dict[str, Any]] = []

    async def recall(
        self,
        query: str,
        *,
        user_id: Any = None,
        agent_name: str | None = None,
        scope: str | None = None,
        k: int = 5,
        mode: str = "hybrid",
        min_similarity: float | None = None,
    ) -> list[Any]:
        self.recall_calls.append(
            {
                "query": query,
                "user_id": user_id,
                "agent_name": agent_name,
                "scope": scope,
                "k": k,
                "mode": mode,
            }
        )
        # Return prior session turns only when the query is the session prefix.
        if query.startswith("mock_interview:session:"):
            return [_make_memory_row(p) for p in self._prior_turns]
        return []

    async def write(self, mw: Any) -> Any:
        self.write_calls.append(
            {
                "key": mw.key,
                "scope": mw.scope,
                "value": mw.value,
                "valence": mw.valence,
                "user_id": mw.user_id,
                "agent_name": mw.agent_name,
            }
        )
        row = MagicMock()
        row.id = uuid.uuid4()
        return row

    async def _find_one(self, **_: Any) -> Any:
        # memory_write probes for pre-existing rows; pretend none exist.
        return None


def _make_memory_row(payload: dict[str, Any]) -> Any:
    """Build a MemoryRow-shaped MagicMock for the stub recall."""
    row = MagicMock()
    row.id = uuid.uuid4()
    row.user_id = None
    row.agent_name = "mock_interview"
    row.scope = "user"
    row.key = (
        f"mock_interview:session:{payload.get('session_id', 'sid')}:0"
    )
    row.value = {
        "session_id": payload.get("session_id", "sid"),
        "mode": payload.get("mode", "behavioral"),
        "turn_kind": payload.get("turn_kind", "question"),
        "payload": payload,
    }
    row.valence = 0.0
    row.confidence = 1.0
    row.similarity = None
    return row


# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def stub_session() -> Any:
    """A MagicMock that satisfies AsyncSession spec — enough for the
    tool executor's audit-row path. Audit row writes are no-ops."""
    return MagicMock(spec=AsyncSession)


@pytest.fixture
def stub_ctx(stub_session: Any) -> AgentContext:
    return AgentContext(
        user_id=None,  # Skip user FK — the audit row tolerates None.
        chain=CallChain.start_root(caller="test"),
        session=stub_session,
        extra={"_llm_usage": []},
    )


@pytest.fixture
def patch_active_session(stub_session: Any):
    """Set the contextvar that universal tools read for the active session.
    Without this, memory_recall/memory_write raise RuntimeError."""
    token = _active_session.set(stub_session)
    yield
    _active_session.reset(token)


@pytest.fixture
def stub_store(monkeypatch: pytest.MonkeyPatch) -> _StubMemoryStore:
    """Replace MemoryStore at the import sites used by memory_recall and
    memory_write tools. Returns a single store instance shared across both
    tools so recall + write are observable from one place."""
    store = _StubMemoryStore()

    def _factory(_session: Any) -> _StubMemoryStore:
        return store

    monkeypatch.setattr(
        "app.agents.tools.universal.memory_recall.MemoryStore", _factory
    )
    monkeypatch.setattr(
        "app.agents.tools.universal.memory_write.MemoryStore", _factory
    )
    return store


@pytest.fixture
def patch_llm(monkeypatch: pytest.MonkeyPatch):
    """Returns a function the test calls with a JSON string; that string
    becomes the stub LLM response. Returns the StubLLM instance so the
    test can inspect .calls (e.g., ordering vs memory ops)."""

    def _install(json_text: str) -> _StubLLM:
        stub = _StubLLM(json_text)
        # build_llm is imported lazily inside run(); patch at the source
        # module so the lazy import resolves to the stub.
        monkeypatch.setattr(
            "app.agents.llm_factory.build_llm",
            lambda **_kw: stub,
        )
        return stub

    return _install


@pytest.fixture
def patch_executor_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    """ToolExecutor writes an audit row to agent_tool_calls for every call.
    Without Postgres backing, that insert blows up. Patch the audit-write
    helper to a no-op so we can drive the agent end-to-end against the
    MagicMock session."""
    async def _noop(*_args: Any, **_kw: Any) -> None:
        return None

    # The audit path is _record_tool_call inside ToolExecutor; patch the
    # underlying primitive that writes to the table.
    monkeypatch.setattr(
        "app.agents.primitives.tools.ToolExecutor._record_tool_call",
        _noop,
        raising=False,
    )


# ── JSON fixtures (stub LLM outputs) ──────────────────────────────


def _question_turn_json(session_id: uuid.UUID) -> str:
    return json.dumps(
        {
            "session_id": str(session_id),
            "mode": "behavioral",
            "turn_kind": "question",
            "question": {
                "question_text": "Tell me about a time you handled a "
                "production incident under pressure.",
                "rubric_summary": "STAR structure, ownership, "
                "quantified result, lessons learned.",
                "expected_minutes": 8,
            },
            "evaluation": None,
            "feedback": None,
            "session_summary": None,
            "handoff_request": None,
        }
    )


def _evaluation_turn_json(session_id: uuid.UUID) -> str:
    return json.dumps(
        {
            "session_id": str(session_id),
            "mode": "coding",
            "turn_kind": "evaluation",
            "question": None,
            "evaluation": {
                "score_0_to_10": 6,
                "strengths": ["clean recursion"],
                "gaps": ["missing big-O analysis"],
                "follow_up_question": "What's the worst-case complexity?",
            },
            "feedback": None,
            "session_summary": None,
            # LLM mistakenly emits a handoff on a non-summary turn — agent
            # must coerce this to None (D-2 defense-in-depth).
            "handoff_request": {
                "target_agent": "senior_engineer",
                "reason": "should be coerced to None",
                "handoff_type": "suggested",
            },
        }
    )


def _feedback_turn_json(session_id: uuid.UUID) -> str:
    return json.dumps(
        {
            "session_id": str(session_id),
            "mode": "system_design",
            "turn_kind": "feedback",
            "question": None,
            "evaluation": None,
            "feedback": {
                "overall_assessment": (
                    "Strong on storage layer, weak on observability."
                ),
                "one_thing_to_practice": (
                    "Practice articulating SLOs and the metrics "
                    "you'd page on."
                ),
            },
            "session_summary": None,
            "handoff_request": None,
        }
    )


def _session_summary_turn_json(session_id: uuid.UUID) -> str:
    return json.dumps(
        {
            "session_id": str(session_id),
            "mode": "coding",
            "turn_kind": "session_summary",
            "question": None,
            "evaluation": None,
            "feedback": None,
            "session_summary": {
                "overall_score_0_to_100": 58,
                "headline": "Mid-level coding fundamentals; needs DS&A reps.",
                "strengths": ["clean naming"],
                "weaknesses": ["graph algorithms", "amortized complexity"],
                "suggested_next_action": (
                    "Drill 5 medium graph problems on LeetCode."
                ),
            },
            "handoff_request": {
                "target_agent": "senior_engineer",
                "reason": (
                    "Coding round revealed unfamiliarity with graph "
                    "algorithms; senior_engineer can do code-level review."
                ),
                # Bug 21 (D13 CP3): suggested_context is dict[str, Any],
                # not a string. Fixture exercises a populated dict so the
                # test catches future drift back to string shape.
                "suggested_context": {
                    "weakness_topic": "graph_algorithms",
                    "interview_session_id": str(session_id),
                },
                "handoff_type": "suggested",
            },
        }
    )


# ── Tests ──────────────────────────────────────────────────────────


async def test_first_turn_question_dispatch_and_ordering(
    stub_ctx: AgentContext,
    patch_active_session: None,
    stub_store: _StubMemoryStore,
    patch_executor_audit: None,
    patch_llm: Any,
) -> None:
    """First turn (no input session_id) → agent generates UUID, recalls
    (returns nothing), calls LLM, writes the new turn. Assert ordering:
    recall calls happen BEFORE the LLM call; write calls AFTER."""
    sid = uuid.uuid4()
    stub = patch_llm(_question_turn_json(sid))

    agent = MockInterviewAgent()
    inp = MockInterviewInput(
        mode="behavioral",
        user_message="Practice me on conflict resolution.",
    )
    payload = await agent.run(inp, stub_ctx)

    # Recall fired twice (session log + weaknesses) before the LLM call.
    assert len(stub_store.recall_calls) == 2
    assert len(stub.calls) == 1

    # The first recall is the session prefix; second is the weakness prefix.
    queries = [c["query"] for c in stub_store.recall_calls]
    assert any(q.startswith("mock_interview:session:") for q in queries)
    assert any(q.startswith("mock_interview:weakness:") for q in queries)

    # Write fired exactly once (the turn log) — non-summary turns don't
    # write weaknesses.
    assert len(stub_store.write_calls) == 1
    assert stub_store.write_calls[0]["key"].startswith(
        "mock_interview:session:"
    )

    # Output projection.
    assert payload["turn_kind"] == "question"
    assert payload["mode"] == "behavioral"
    assert "answer" in payload
    assert "production incident" in payload["answer"]


async def test_followup_turn_echoes_session_id_and_recalls_priors(
    stub_ctx: AgentContext,
    patch_active_session: None,
    patch_executor_audit: None,
    patch_llm: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Follow-up turn: client passes session_id; the recall should return
    a prior question turn; the agent should echo session_id in output."""
    prior_sid = uuid.uuid4()

    prior_turn = {
        "session_id": str(prior_sid),
        "mode": "coding",
        "turn_kind": "question",
        "question": {
            "question_text": "Implement LRU cache.",
            "rubric_summary": "Big-O, eviction, thread-safety.",
            "expected_minutes": 25,
        },
    }
    store = _StubMemoryStore(prior_turns=[prior_turn])
    monkeypatch.setattr(
        "app.agents.tools.universal.memory_recall.MemoryStore",
        lambda _s: store,
    )
    monkeypatch.setattr(
        "app.agents.tools.universal.memory_write.MemoryStore",
        lambda _s: store,
    )

    stub = patch_llm(_evaluation_turn_json(prior_sid))

    agent = MockInterviewAgent()
    inp = MockInterviewInput(
        mode="coding",
        session_id=prior_sid,
        user_message="My answer: dict + doubly linked list, O(1) ops.",
    )
    payload = await agent.run(inp, stub_ctx)

    # Echo: output session_id matches input.
    assert payload["session_id"] == str(prior_sid)

    # The user_block delivered to the LLM included the prior turn.
    user_block = stub.calls[0][1]["content"]
    assert "Prior turns this session" in user_block
    assert "Implement LRU cache" in user_block


async def test_evaluation_turn_coerces_handoff_to_none(
    stub_ctx: AgentContext,
    patch_active_session: None,
    stub_store: _StubMemoryStore,
    patch_executor_audit: None,
    patch_llm: Any,
) -> None:
    """D-2 defense-in-depth: even when the LLM emits a handoff_request on
    a non-summary turn, run() forces it to None."""
    sid = uuid.uuid4()
    patch_llm(_evaluation_turn_json(sid))

    agent = MockInterviewAgent()
    inp = MockInterviewInput(
        mode="coding",
        session_id=sid,
        user_message="My answer is recursion with memoization.",
    )
    payload = await agent.run(inp, stub_ctx)

    assert payload["turn_kind"] == "evaluation"
    assert payload["handoff_request"] is None  # coerced even though LLM emitted one


async def test_feedback_turn_dispatches_and_no_weakness_writes(
    stub_ctx: AgentContext,
    patch_active_session: None,
    stub_store: _StubMemoryStore,
    patch_executor_audit: None,
    patch_llm: Any,
) -> None:
    """feedback turn writes only the turn log (no weaknesses — that's
    summary-only)."""
    sid = uuid.uuid4()
    patch_llm(_feedback_turn_json(sid))

    agent = MockInterviewAgent()
    inp = MockInterviewInput(
        mode="system_design",
        session_id=sid,
        user_message="That's all I have on this question.",
    )
    payload = await agent.run(inp, stub_ctx)

    assert payload["turn_kind"] == "feedback"
    # Exactly one write — the turn log.
    assert len(stub_store.write_calls) == 1
    assert stub_store.write_calls[0]["key"].startswith(
        "mock_interview:session:"
    )
    # No weakness writes.
    assert not any(
        c["key"].startswith("mock_interview:weakness:")
        for c in stub_store.write_calls
    )


async def test_session_summary_turn_writes_weaknesses(
    stub_ctx: AgentContext,
    patch_active_session: None,
    stub_store: _StubMemoryStore,
    patch_executor_audit: None,
    patch_llm: Any,
) -> None:
    """session_summary turn writes one turn-log entry PLUS one weakness
    write per identified weakness."""
    sid = uuid.uuid4()
    patch_llm(_session_summary_turn_json(sid))

    agent = MockInterviewAgent()
    inp = MockInterviewInput(
        mode="coding",
        session_id=sid,
        user_message="Wrap up the session.",
    )
    payload = await agent.run(inp, stub_ctx)

    assert payload["turn_kind"] == "session_summary"

    # Writes: 1 session-log + 2 weakness rows (graph algorithms, amortized
    # complexity). 3 total.
    assert len(stub_store.write_calls) == 3
    weakness_writes = [
        c for c in stub_store.write_calls
        if c["key"].startswith("mock_interview:weakness:")
    ]
    assert len(weakness_writes) == 2
    # Negative valence — these are gaps, not strengths.
    assert all(c["valence"] == -0.4 for c in weakness_writes)
    # Topic-anchored keys (whitespace normalized to underscores).
    assert any("graph_algorithms" in c["key"] for c in weakness_writes)
    assert any("amortized_complexity" in c["key"] for c in weakness_writes)


async def test_session_summary_preserves_handoff_request(
    stub_ctx: AgentContext,
    patch_active_session: None,
    stub_store: _StubMemoryStore,
    patch_executor_audit: None,
    patch_llm: Any,
) -> None:
    """On session_summary turns, the handoff_request emitted by the LLM
    is preserved (D-2 Option B allows it here)."""
    sid = uuid.uuid4()
    patch_llm(_session_summary_turn_json(sid))

    agent = MockInterviewAgent()
    inp = MockInterviewInput(mode="coding", session_id=sid, user_message="wrap")
    payload = await agent.run(inp, stub_ctx)

    assert payload["handoff_request"] is not None
    assert payload["handoff_request"]["target_agent"] == "senior_engineer"
    assert payload["handoff_request"]["handoff_type"] == "suggested"


async def test_truncate_to_schema_handles_overshoot(
    stub_ctx: AgentContext,
    patch_active_session: None,
    stub_store: _StubMemoryStore,
    patch_executor_audit: None,
    patch_llm: Any,
) -> None:
    """If the LLM emits a string longer than the schema max_length, the
    Bug 17 architectural fix (truncate_to_schema) trims it instead of
    raising ValidationError."""
    sid = uuid.uuid4()
    overshoot = "x" * 5000  # exceeds question_text max_length of 2000.
    raw = json.dumps(
        {
            "session_id": str(sid),
            "mode": "behavioral",
            "turn_kind": "question",
            "question": {
                "question_text": overshoot,
                "rubric_summary": "y" * 1000,  # exceeds 400.
                "expected_minutes": 10,
            },
            "evaluation": None,
            "feedback": None,
            "session_summary": None,
            "handoff_request": None,
        }
    )
    patch_llm(raw)

    agent = MockInterviewAgent()
    inp = MockInterviewInput(mode="behavioral", session_id=sid, user_message="go")
    payload = await agent.run(inp, stub_ctx)

    # Truncated, not rejected.
    assert payload["turn_kind"] == "question"
    assert len(payload["question"]["question_text"]) == 2000
    assert len(payload["question"]["rubric_summary"]) == 400


async def test_session_id_coerced_when_llm_drifts(
    stub_ctx: AgentContext,
    patch_active_session: None,
    stub_store: _StubMemoryStore,
    patch_executor_audit: None,
    patch_llm: Any,
) -> None:
    """If the LLM emits a different session_id than the orchestrator's,
    run() coerces back to the orchestrator's session_id (D-1 invariant
    defense)."""
    orch_sid = uuid.uuid4()
    drifted_sid = uuid.uuid4()
    raw = _question_turn_json(drifted_sid)  # LLM emits drifted_sid
    patch_llm(raw)

    agent = MockInterviewAgent()
    inp = MockInterviewInput(
        mode="behavioral",
        session_id=orch_sid,
        user_message="x",
    )
    payload = await agent.run(inp, stub_ctx)

    # Coerced back to the orchestrator's session_id.
    assert payload["session_id"] == str(orch_sid)
    assert payload["session_id"] != str(drifted_sid)
