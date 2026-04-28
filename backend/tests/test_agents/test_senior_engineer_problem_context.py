"""P-Practice1: confirm `problem_context` flows from the request payload
into the senior-engineer agent's LLM prompt so exercise-aware reviews
actually carry the exercise rubric the student is solving against.

We mock `_build_llm` so the test is hermetic — no Anthropic API call.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.agents.base_agent import AgentState
from app.agents.senior_engineer import SeniorEngineerAgent


class _StubLLMResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _StubLLM:
    """Captures the messages it was called with for assertion."""

    def __init__(self) -> None:
        self.captured_messages: list[Any] = []

    async def ainvoke(self, messages: list[Any]) -> _StubLLMResponse:
        self.captured_messages = messages
        return _StubLLMResponse(
            json.dumps(
                {
                    "verdict": "comment",
                    "headline": "ok",
                    "strengths": [],
                    "comments": [],
                    "next_step": "ship it",
                }
            )
        )


@pytest.mark.asyncio
async def test_problem_context_threaded_into_llm_prompt() -> None:
    """The exercise rubric provided as `problem_context` must appear in the
    user message we send to the LLM. Without this, exercise-aware reviews
    are indistinguishable from free-form scratchpad reviews."""
    agent = SeniorEngineerAgent()
    stub = _StubLLM()
    agent._build_llm = lambda max_tokens=1500: stub  # type: ignore[method-assign,assignment]

    state = AgentState(
        student_id="user-1",
        task="senior_review",
        context={
            "code": "print('hi')",
            "problem_context": "Exercise: write a CLI greeter that asks for a name.",
        },
    )

    new_state = await agent.execute(state)

    assert new_state.response is not None
    # Two-message conversation: system + human.
    assert len(stub.captured_messages) == 2
    human_content = str(stub.captured_messages[1].content)
    assert "Problem context" in human_content
    assert "CLI greeter" in human_content
    assert "print('hi')" in human_content


@pytest.mark.asyncio
async def test_no_problem_context_omits_context_line() -> None:
    """When the request omits `problem_context`, the LLM prompt should NOT
    contain the 'Problem context' framing — otherwise we'd be lying to the
    model about an empty rubric."""
    agent = SeniorEngineerAgent()
    stub = _StubLLM()
    agent._build_llm = lambda max_tokens=1500: stub  # type: ignore[method-assign,assignment]

    state = AgentState(
        student_id="user-1",
        task="senior_review",
        context={"code": "x = 1\n"},
    )

    await agent.execute(state)

    human_content = str(stub.captured_messages[1].content)
    assert "Problem context" not in human_content
    assert "x = 1" in human_content


@pytest.mark.asyncio
async def test_problem_context_truncation_safe_for_long_rubric() -> None:
    """The frontend caps `problem_context` at 1900 chars before sending so
    we never exceed Pydantic's 2000-char limit. Verify the agent gracefully
    forwards a long-but-bounded rubric end-to-end."""
    agent = SeniorEngineerAgent()
    stub = _StubLLM()
    agent._build_llm = lambda max_tokens=1500: stub  # type: ignore[method-assign,assignment]

    long_context = "Rubric line. " * 140  # ~1820 chars
    state = AgentState(
        student_id="user-1",
        task="senior_review",
        context={"code": "x = 1\n", "problem_context": long_context},
    )

    new_state = await agent.execute(state)

    assert new_state.response is not None
    human_content = str(stub.captured_messages[1].content)
    assert "Problem context" in human_content
    assert "Rubric line." in human_content
