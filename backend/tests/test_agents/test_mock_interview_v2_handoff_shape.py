"""D13 CP3 Phase 1.7 — Bug 21 regression test (handoff_request shape).

Pins mock_interview's handoff_request output against
app.schemas.supervisor.HandoffRequest. Catches the Bug 21 failure
mode where the prompt told the LLM to emit suggested_context as a
string but the schema expects dict[str, Any].

Bug 21 history:
  D13 CP3 Phase 4 (real-LLM) raised ValidationError when MiniMax
  emitted handoff_request.suggested_context as a string per the
  prompt's "short string of context" instruction. The schema field
  is dict[str, Any]; the prompt was wrong.

  Fix: prompt updated to spec dict shape. Stub-smoke fixture
  updated to use dict. This file pins the constraint.

These tests drive the agent end-to-end (stubbed LLM, stubbed memory)
and assert the produced handoff_request validates against the
Supervisor's HandoffRequest schema — no dict-vs-string drift, no
Pydantic ValidationError.
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
from app.schemas.supervisor import HandoffRequest

pytestmark = [pytest.mark.asyncio]


# ── Test doubles (mirrored from stub_smoke; small enough to keep self-contained) ──


class _StubResponse:
    def __init__(self, json_text: str) -> None:
        self.content = [
            {"type": "thinking", "thinking": "skipped"},
            {"type": "text", "text": json_text},
        ]
        self.usage_metadata = {"input_tokens": 100, "output_tokens": 50}


class _StubLLM:
    def __init__(self, json_text: str) -> None:
        self._json_text = json_text

    async def ainvoke(self, _messages: Any, **_: Any) -> _StubResponse:
        return _StubResponse(self._json_text)


class _StubMemoryStore:
    def __init__(self) -> None:
        self.write_calls: list[dict[str, Any]] = []

    async def recall(self, *_args: Any, **_kw: Any) -> list[Any]:
        return []

    async def write(self, mw: Any) -> Any:
        self.write_calls.append(
            {"key": mw.key, "scope": mw.scope, "value": mw.value}
        )
        row = MagicMock()
        row.id = uuid.uuid4()
        return row

    async def _find_one(self, **_: Any) -> Any:
        return None


@pytest.fixture
def stub_session() -> Any:
    return MagicMock(spec=AsyncSession)


@pytest.fixture
def stub_ctx(stub_session: Any) -> AgentContext:
    return AgentContext(
        user_id=None,
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
def patch_llm(monkeypatch: pytest.MonkeyPatch):
    def _install(json_text: str) -> _StubLLM:
        stub = _StubLLM(json_text)
        monkeypatch.setattr(
            "app.agents.llm_factory.build_llm", lambda **_kw: stub
        )
        return stub

    return _install


@pytest.fixture
def patch_executor_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(*_args: Any, **_kw: Any) -> None:
        return None

    monkeypatch.setattr(
        "app.agents.primitives.tools.ToolExecutor._record_tool_call",
        _noop,
        raising=False,
    )


# ── JSON output fixtures ───────────────────────────────────────────


def _summary_with_dict_context(session_id: uuid.UUID) -> str:
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
                "headline": "Mid-level coding; needs DS&A reps.",
                "strengths": ["clean naming"],
                "weaknesses": ["graph algorithms"],
                "suggested_next_action": "Drill 5 medium graph problems.",
            },
            "handoff_request": {
                "target_agent": "senior_engineer",
                "reason": "Graph algorithm gap warrants senior_engineer review.",
                "suggested_context": {
                    "weakness_topic": "graph_algorithms",
                    "interview_session_id": str(session_id),
                    "score": 58,
                },
                "handoff_type": "suggested",
            },
        }
    )


def _summary_with_empty_dict_context(session_id: uuid.UUID) -> str:
    return json.dumps(
        {
            "session_id": str(session_id),
            "mode": "behavioral",
            "turn_kind": "session_summary",
            "question": None,
            "evaluation": None,
            "feedback": None,
            "session_summary": {
                "overall_score_0_to_100": 70,
                "headline": "Decent storytelling; needs result quantification.",
                "strengths": ["concrete examples"],
                "weaknesses": ["unquantified results"],
                "suggested_next_action": "Practice quantifying impact.",
            },
            "handoff_request": {
                "target_agent": "career_coach",
                "reason": "Strategic readiness gap on quantification.",
                "suggested_context": {},
                "handoff_type": "suggested",
            },
        }
    )


def _question_turn_json(session_id: uuid.UUID) -> str:
    """Non-summary turn — handoff_request must be None even if LLM emits one."""
    return json.dumps(
        {
            "session_id": str(session_id),
            "mode": "behavioral",
            "turn_kind": "question",
            "question": {
                "question_text": "Tell me about a recent on-call incident.",
                "rubric_summary": "STAR; quantified outcome.",
                "expected_minutes": 8,
            },
            "evaluation": None,
            "feedback": None,
            "session_summary": None,
            # LLM mistakenly emits a populated handoff with dict context;
            # agent should coerce to None per D-2.
            "handoff_request": {
                "target_agent": "senior_engineer",
                "reason": "leak from non-summary turn",
                "suggested_context": {"should_be_dropped": True},
                "handoff_type": "suggested",
            },
        }
    )


# ── Tests ──────────────────────────────────────────────────────────


async def test_handoff_with_populated_dict_context_validates(
    stub_ctx: AgentContext,
    patch_active_session: None,
    stub_store: _StubMemoryStore,
    patch_executor_audit: None,
    patch_llm: Any,
) -> None:
    """The Bug 21 fix shape: suggested_context is a dict with keys.
    Output validates against Supervisor's HandoffRequest schema."""
    sid = uuid.uuid4()
    patch_llm(_summary_with_dict_context(sid))

    agent = MockInterviewAgent()
    inp = MockInterviewInput(
        mode="coding",
        session_id=sid,
        user_message="Wrap up.",
    )
    payload = await agent.run(inp, stub_ctx)

    assert payload["turn_kind"] == "session_summary"
    hr = payload["handoff_request"]
    assert hr is not None
    # Schema validation against Supervisor's contract.
    validated = HandoffRequest.model_validate(hr)
    assert validated.target_agent == "senior_engineer"
    assert validated.handoff_type == "suggested"
    # The Bug 21 invariant: suggested_context is a dict.
    assert isinstance(validated.suggested_context, dict)
    assert validated.suggested_context["weakness_topic"] == "graph_algorithms"
    assert validated.suggested_context["score"] == 58


async def test_handoff_with_empty_dict_context_validates(
    stub_ctx: AgentContext,
    patch_active_session: None,
    stub_store: _StubMemoryStore,
    patch_executor_audit: None,
    patch_llm: Any,
) -> None:
    """Empty dict is also valid per the schema's default_factory=dict."""
    sid = uuid.uuid4()
    patch_llm(_summary_with_empty_dict_context(sid))

    agent = MockInterviewAgent()
    inp = MockInterviewInput(
        mode="behavioral",
        session_id=sid,
        user_message="Done.",
    )
    payload = await agent.run(inp, stub_ctx)

    hr = payload["handoff_request"]
    validated = HandoffRequest.model_validate(hr)
    assert validated.target_agent == "career_coach"
    assert validated.suggested_context == {}


async def test_handoff_dropped_on_non_summary_turn(
    stub_ctx: AgentContext,
    patch_active_session: None,
    stub_store: _StubMemoryStore,
    patch_executor_audit: None,
    patch_llm: Any,
) -> None:
    """D-2 defense-in-depth still works when LLM emits a Bug-21-shape
    handoff (with dict context) on a non-summary turn — agent forces
    handoff_request=None regardless of shape."""
    sid = uuid.uuid4()
    patch_llm(_question_turn_json(sid))

    agent = MockInterviewAgent()
    inp = MockInterviewInput(
        mode="behavioral",
        session_id=sid,
        user_message="Start me off.",
    )
    payload = await agent.run(inp, stub_ctx)

    assert payload["turn_kind"] == "question"
    assert payload["handoff_request"] is None


async def test_handoff_string_context_now_rejected_by_schema() -> None:
    """The Bug 21 failure shape: suggested_context emitted as a string.
    Pydantic rejects this, surfacing the prompt-vs-schema mismatch.
    Pure schema test; no agent dispatch needed."""
    from pydantic import ValidationError

    bad_payload = {
        "target_agent": "senior_engineer",
        "reason": "test",
        # Bug 21 shape: string instead of dict.
        "suggested_context": "this is what MiniMax produced when prompt was wrong",
        "handoff_type": "suggested",
    }
    with pytest.raises(ValidationError) as exc_info:
        HandoffRequest.model_validate(bad_payload)
    # Confirm it's the suggested_context field that triggered the error.
    assert "suggested_context" in str(exc_info.value)


async def test_prompt_documents_dict_shape_for_suggested_context() -> None:
    """Static check on the prompt itself — keeps the prompt's description
    of suggested_context aligned with the schema. Catches future drift
    where someone reverts the prompt back to 'short string'."""
    from pathlib import Path

    prompt_path = Path(
        "/app/app/agents/prompts/mock_interview.md"
    )
    if not prompt_path.exists():
        # Local-machine fallback; tests run inside container in CI.
        prompt_path = (
            Path(__file__).parent.parent.parent
            / "app"
            / "agents"
            / "prompts"
            / "mock_interview.md"
        )
    text = prompt_path.read_text()
    # Find the suggested_context line.
    sc_line = next(
        (line for line in text.splitlines() if "suggested_context" in line),
        None,
    )
    assert sc_line is not None, "suggested_context not documented in prompt"
    lower = sc_line.lower()
    assert "dict" in lower, (
        f"prompt's suggested_context description must mention 'dict'. "
        f"Got: {sc_line!r}. This is the Bug 21 regression check."
    )
