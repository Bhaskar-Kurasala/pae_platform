"""D13 CP3 Phase 1.6 — Bug 19 regression test.

Pins the Critic's max_tokens budget against a future shrink that would
re-introduce the Bug 19 empty-content failure under MiniMax M2.7.

Bug 19 history:
  After Bug 18 (drop temperature kwarg) landed, the Critic's
  max_tokens=400 budget collapsed under MiniMax. tier="fast" doesn't
  route to Haiku when MINIMAX_API_KEY is set — both tiers route to
  M2.7 (per llm_factory.py:77-78). M2.7 always emits a thinking block
  (~38% of output tokens per D12 measurements). With max_tokens=400,
  the thinking block consumed the full budget and the response had
  no text block. Critic's content extraction returned "" → verdict
  parse failed → critic-tolerant retry → second agent run → 36s
  dispatch timeout → mock_interview unusable.

  Interim fix: bump max_tokens to 2048 (D13 CP3 Phase 1.6).
  Architectural fix: route Critic directly to Anthropic Haiku
  bypassing build_llm's MINIMAX preference (D14 prerequisite,
  see docs/followups/critic-tier-routing-architectural.md).

This file pins TWO invariants:
  1. The Critic's content-extraction logic correctly distinguishes
     empty-text-block (Bug 19 symptom) from text-present.
  2. The Critic's max_tokens budget cannot be shrunk below the
     MiniMax thinking-block floor without test failure.
"""

from __future__ import annotations

import inspect

import pytest


# ── Test 1: content extraction correctly handles MiniMax-shape responses ──


class _StubResponse:
    """Mimics the LangChain ChatAnthropic.ainvoke response shape."""

    def __init__(self, content: list[dict] | str) -> None:
        self.content = content


class _StubLLM:
    """Stub LLM that returns a fixed response. Used to drive the Critic
    content-extraction logic without an actual API call."""

    def __init__(self, response: _StubResponse) -> None:
        self._response = response

    async def ainvoke(self, _messages: list) -> _StubResponse:
        return self._response


@pytest.mark.asyncio
async def test_critic_extracts_text_when_thinking_and_text_blocks_present() -> None:
    """The healthy MiniMax shape: a thinking block followed by a text block.
    Critic must skip thinking and return the text payload."""
    from app.agents.primitives.evaluation import _DefaultLLM

    client = _DefaultLLM()
    client._llm = _StubLLM(
        _StubResponse(
            [
                {"type": "thinking", "thinking": "internal reasoning..."},
                {"type": "text", "text": '{"score": 0.7}'},
            ]
        )
    )

    text = await client.ainvoke_text("dummy prompt")
    assert text == '{"score": 0.7}', (
        f"Critic should extract the text block, got: {text!r}"
    )


@pytest.mark.asyncio
async def test_critic_returns_empty_when_only_thinking_block(caplog: pytest.LogCaptureFixture) -> None:
    """The Bug 19 failure shape: MiniMax returns ONLY a thinking block
    (text budget exhausted). The Critic's extractor returns "". This is
    NOT a Critic correctness bug — it's correctly reporting that the
    upstream LLM gave it nothing to parse. The fix lives upstream
    (max_tokens budget), but we pin the extractor's behavior here so
    nobody refactors it to silently default to a passing verdict.
    """
    from app.agents.primitives.evaluation import _DefaultLLM

    client = _DefaultLLM()
    client._llm = _StubLLM(
        _StubResponse(
            [
                {"type": "thinking", "thinking": "consumed all 400 tokens here"},
            ]
        )
    )

    text = await client.ainvoke_text("dummy prompt")
    assert text == "", (
        "Critic must return empty string when there's no text block, "
        f"so the verdict parser sees parsed_ok=False. Got: {text!r}"
    )


@pytest.mark.asyncio
async def test_critic_extracts_string_content_passthrough() -> None:
    """The Anthropic-native shape: content is a plain string (not a list
    of blocks). Critic must return it as-is."""
    from app.agents.primitives.evaluation import _DefaultLLM

    client = _DefaultLLM()
    client._llm = _StubLLM(_StubResponse('{"score": 0.85}'))

    text = await client.ainvoke_text("dummy prompt")
    assert text == '{"score": 0.85}'


# ── Test 2: max_tokens budget pinning ──


def test_critic_max_tokens_meets_minimax_thinking_floor() -> None:
    """Pins the Critic's max_tokens budget against the Bug 19 floor.

    Under MiniMax M2.7, max_tokens needs ≥ 2048 to give the thinking
    block ~800 tokens of headroom and leave ~1200 for the verdict JSON.
    Anything below 1024 risks the Bug 19 failure mode where the thinking
    block consumes the entire budget.

    This test reads the source of `_DefaultLLM.ainvoke_text` and
    inspects the build_llm call's max_tokens kwarg. If a future refactor
    drops it back to 400 (or worse, removes the explicit value), this
    test fails — at which point either bump it back or land the D14
    architectural fix (Critic → Anthropic Haiku direct, where 400 is
    correct because Haiku has no thinking blocks).
    """
    import re

    from app.agents.primitives import evaluation

    src = inspect.getsource(evaluation._DefaultLLM)
    matches = re.findall(r"build_llm\((.*?)\)", src, re.DOTALL)
    assert matches, "Could not find build_llm call in _DefaultLLM source"

    # Extract max_tokens value from the call. Tolerates kwarg ordering
    # changes; the assertion is on the integer value.
    max_tokens_values: list[int] = []
    for call in matches:
        m = re.search(r"max_tokens\s*=\s*(\d+)", call)
        if m:
            max_tokens_values.append(int(m.group(1)))

    assert max_tokens_values, (
        "Could not parse max_tokens from build_llm call in Critic. "
        "Has the call signature changed? Update this regression test "
        "or restore explicit max_tokens."
    )
    # The Bug 19 floor under MiniMax is ~1024. We pin 2048 as the
    # documented safe value; anything below 1024 is the Bug 19 risk
    # zone.
    min_value = min(max_tokens_values)
    assert min_value >= 1024, (
        f"Critic max_tokens={min_value} risks Bug 19 (MiniMax thinking "
        f"block consumes entire budget; text block empty). Either bump "
        f"back to >=2048 or land the D14 architectural fix routing "
        f"Critic directly to Haiku. See "
        f"docs/followups/critic-tier-routing-architectural.md."
    )
