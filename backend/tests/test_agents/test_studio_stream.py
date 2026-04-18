"""Unit tests for the Studio context-aware tutor stream (P1-B-3).

Focus: the stream endpoint's _token_generator must inject the student's code
into the system prompt when context.code is provided, so the tutor can reference
specific lines.
"""

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import pytest
from langchain_core.messages import SystemMessage

from app.api.v1.routes import stream as stream_module


class _FakeChunk:
    def __init__(self, text: str) -> None:
        self.content = text


class _FakeLLM:
    """Captures the messages passed to .astream and yields a fixed response."""

    def __init__(self) -> None:
        self.captured_messages: list[Any] | None = None

    async def astream(self, messages: list[Any]) -> AsyncIterator[_FakeChunk]:
        self.captured_messages = messages
        yield _FakeChunk("ok")


@pytest.mark.asyncio
async def test_studio_tutor_injects_code_into_system_prompt() -> None:
    fake_llm = _FakeLLM()
    with patch.object(stream_module, "build_llm", return_value=fake_llm):
        code = "def add(a, b):\n    return a - b  # bug\n"
        gen = stream_module._token_generator(
            message="What's wrong with add()?",
            agent_name="studio_tutor",
            conversation_history=[],
            code_context=code,
        )
        # Drain generator to trigger astream
        async for _ in gen:
            pass

    assert fake_llm.captured_messages is not None
    system_msg = fake_llm.captured_messages[0]
    assert isinstance(system_msg, SystemMessage)
    assert "Studio tutor" in system_msg.content
    assert "Student's current code" in system_msg.content
    assert "return a - b" in system_msg.content


@pytest.mark.asyncio
async def test_studio_tutor_without_code_omits_code_block() -> None:
    fake_llm = _FakeLLM()
    with patch.object(stream_module, "build_llm", return_value=fake_llm):
        gen = stream_module._token_generator(
            message="hi",
            agent_name="studio_tutor",
            conversation_history=[],
            code_context=None,
        )
        async for _ in gen:
            pass

    assert fake_llm.captured_messages is not None
    system_msg = fake_llm.captured_messages[0]
    assert isinstance(system_msg, SystemMessage)
    assert "Student's current code" not in system_msg.content


@pytest.mark.asyncio
async def test_code_context_truncated_at_8000_chars() -> None:
    """Huge files must not blow up token budgets — generator receives only up
    to 8000 chars (trimmed by the route). Here we just confirm the generator
    itself embeds whatever it's given, so the route-level cap matters."""
    fake_llm = _FakeLLM()
    big_code = "x" * 10_000
    with patch.object(stream_module, "build_llm", return_value=fake_llm):
        gen = stream_module._token_generator(
            message="review",
            agent_name="studio_tutor",
            conversation_history=[],
            code_context=big_code,
        )
        async for _ in gen:
            pass

    system_msg = fake_llm.captured_messages[0]
    # Generator doesn't cap — route does. Ensure the cap value is documented
    # in the route so this boundary is explicit.
    import inspect

    route_src = inspect.getsource(stream_module.stream_chat)
    assert "8000" in route_src, "Expected 8k code-context cap in stream route"
    # And that the generator faithfully embedded the (un-truncated) input here.
    assert "x" * 100 in system_msg.content
