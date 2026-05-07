"""Critic tier routing — architectural fix verification (D14 prerequisite).

Pins the Critic's two-path construction:
  • settings.anthropic_api_key set → ChatAnthropic(Haiku) direct
    with max_tokens=400, temperature=0.0
  • settings.anthropic_api_key absent → build_llm fallback with
    max_tokens=2048 (D13 Bug 19 interim fix shape)

The fix closes Bug 19's architectural concern: build_llm(tier="fast")
collapses to MiniMax M2.7 when MINIMAX_API_KEY is set, which is the
wrong route for Critic infrastructure (Pattern 18). Direct ChatAnthropic
construction routes Critic to its design target (Haiku) when the key
is available.

Pure construction tests — no LLM call, no cost.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest


def test_critic_uses_chat_anthropic_when_anthropic_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When settings.anthropic_api_key is set, the Critic constructs
    ChatAnthropic(Haiku) directly, bypassing build_llm. max_tokens=400
    matches Haiku's no-thinking-block output shape."""
    from app.agents.primitives.evaluation import _DefaultLLM

    # Force the Anthropic-key path.
    monkeypatch.setattr(
        "app.agents.primitives.evaluation.settings.anthropic_api_key",
        "test-anthropic-key-not-real",
    )

    captured: dict[str, Any] = {}

    class _FakeChatAnthropic:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(
        "langchain_anthropic.ChatAnthropic", _FakeChatAnthropic
    )

    client = _DefaultLLM()
    assert client._llm is None

    # Drive the lazy-build by calling ainvoke_text. We don't actually
    # invoke the LLM — _FakeChatAnthropic doesn't implement ainvoke,
    # so the call will raise AttributeError when reaching .ainvoke().
    # That's fine; we only care that construction captured the kwargs.
    import asyncio

    with pytest.raises(Exception):
        asyncio.run(client.ainvoke_text("dummy"))

    assert captured.get("model") == "claude-haiku-4-5"
    assert captured.get("max_tokens") == 400
    assert captured.get("temperature") == 0.0
    assert captured.get("max_retries") == 0
    # timeout should be Critic-specific (15s), not main-agent's 90s.
    assert captured.get("timeout") == 15.0


def test_critic_falls_back_to_build_llm_when_no_anthropic_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When settings.anthropic_api_key is not set, the Critic falls back
    to build_llm with max_tokens=2048 (D13 Bug 19 interim fix shape)."""
    from app.agents.primitives.evaluation import _DefaultLLM

    monkeypatch.setattr(
        "app.agents.primitives.evaluation.settings.anthropic_api_key", None
    )

    captured: dict[str, Any] = {}

    def _fake_build_llm(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return object()  # any sentinel

    monkeypatch.setattr(
        "app.agents.llm_factory.build_llm", _fake_build_llm
    )

    client = _DefaultLLM()
    import asyncio

    with pytest.raises(Exception):
        # _llm is now a plain object() with no ainvoke; call will raise.
        asyncio.run(client.ainvoke_text("dummy"))

    assert captured.get("max_tokens") == 2048
    assert captured.get("tier") == "fast"


def test_critic_anthropic_path_preserves_temperature_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin the temperature=0.0 invariant: the Anthropic path restores
    the deterministic-verdict requirement that D13 Bug 18 dropped (the
    drop was forced by build_llm not accepting temperature; direct
    ChatAnthropic construction has no such constraint).
    """
    from app.agents.primitives.evaluation import _DefaultLLM

    monkeypatch.setattr(
        "app.agents.primitives.evaluation.settings.anthropic_api_key", "k"
    )

    captured: dict[str, Any] = {}

    class _FakeChatAnthropic:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(
        "langchain_anthropic.ChatAnthropic", _FakeChatAnthropic
    )

    client = _DefaultLLM()
    import asyncio

    with pytest.raises(Exception):
        asyncio.run(client.ainvoke_text("dummy"))

    assert "temperature" in captured
    assert captured["temperature"] == 0.0


def test_critic_anthropic_path_uses_secret_str() -> None:
    """The Anthropic path wraps the API key in pydantic.SecretStr (matches
    the codebase's canonical pattern in safety/llm_classifier.py)."""
    from pydantic import SecretStr
    from app.agents.primitives.evaluation import _DefaultLLM

    with patch(
        "app.agents.primitives.evaluation.settings"
    ) as mock_settings:
        mock_settings.anthropic_api_key = "test-key"

        captured: dict[str, Any] = {}

        class _FakeChatAnthropic:
            def __init__(self, **kwargs: Any) -> None:
                captured.update(kwargs)

        with patch("langchain_anthropic.ChatAnthropic", _FakeChatAnthropic):
            client = _DefaultLLM()
            import asyncio

            with pytest.raises(Exception):
                asyncio.run(client.ainvoke_text("dummy"))

            assert isinstance(captured["anthropic_api_key"], SecretStr)


def test_existing_bug18_signature_test_still_holds() -> None:
    """Sanity: the Bug 18 regression test (build_llm doesn't accept
    temperature) is unaffected by this change. The fallback path's
    build_llm call still has no temperature kwarg."""
    import inspect
    import re

    from app.agents.primitives import evaluation

    src = inspect.getsource(evaluation._DefaultLLM)
    # Find any build_llm calls; assert none pass temperature.
    for call in re.findall(r"build_llm\((.*?)\)", src, re.DOTALL):
        kwargs = re.findall(r"(\w+)\s*=", call)
        assert "temperature" not in kwargs, (
            "Bug 18 regression: build_llm should not be called with "
            "temperature. Direct ChatAnthropic construction is the "
            "right place for temperature pinning."
        )


def test_existing_bug19_max_tokens_floor_still_holds() -> None:
    """Sanity: the Bug 19 max_tokens floor regression test still holds.
    The fallback path uses 2048 (above the 1024 floor)."""
    import inspect
    import re

    from app.agents.primitives import evaluation

    src = inspect.getsource(evaluation._DefaultLLM)

    # The fallback path's build_llm call.
    fallback_calls = re.findall(r"build_llm\((.*?)\)", src, re.DOTALL)
    fallback_max_tokens: list[int] = []
    for call in fallback_calls:
        m = re.search(r"max_tokens\s*=\s*(\d+)", call)
        if m:
            fallback_max_tokens.append(int(m.group(1)))

    assert fallback_max_tokens, "No build_llm call found in Critic"
    assert min(fallback_max_tokens) >= 1024, (
        "Bug 19 regression: Critic fallback max_tokens below MiniMax "
        "thinking-block floor. See Pattern 18 / Bug 19 history."
    )
