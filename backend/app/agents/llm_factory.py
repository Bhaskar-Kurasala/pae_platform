"""Shared LLM factory for all agents.

Uses MiniMax-M2.7 via its Anthropic-compatible endpoint when MINIMAX_API_KEY is set,
falls back to Anthropic API when ANTHROPIC_API_KEY is set, otherwise raises.
"""

from langchain_anthropic import ChatAnthropic
from pydantic import SecretStr

from app.core.config import settings


def build_llm(max_tokens: int = 4096) -> ChatAnthropic:
    """Return a ChatAnthropic instance pointed at MiniMax or Anthropic."""
    if settings.minimax_api_key:
        return ChatAnthropic(  # type: ignore[call-arg]
            model=settings.minimax_model,
            anthropic_api_key=SecretStr(settings.minimax_api_key),
            base_url=settings.minimax_api_base_url,
            max_tokens=max_tokens,
        )
    if settings.anthropic_api_key:
        return ChatAnthropic(  # type: ignore[call-arg]
            model="claude-sonnet-4-6",
            anthropic_api_key=SecretStr(settings.anthropic_api_key),
            max_tokens=max_tokens,
        )
    raise RuntimeError("No LLM API key configured. Set MINIMAX_API_KEY or ANTHROPIC_API_KEY in .env")


def build_classifier_llm() -> ChatAnthropic:
    """Lightweight LLM for MOA intent classification (low token budget)."""
    return build_llm(max_tokens=30)
