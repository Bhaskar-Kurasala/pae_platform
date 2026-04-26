"""Shared LLM factory for all agents.

Uses MiniMax-M2.7 via its Anthropic-compatible endpoint when MINIMAX_API_KEY is set,
falls back to Anthropic API when ANTHROPIC_API_KEY is set, otherwise raises.
"""

from typing import Literal

from langchain_anthropic import ChatAnthropic
from pydantic import SecretStr

from app.core.config import settings

Tier = Literal["smart", "fast"]

# Anthropic list pricing (USD per 1M tokens) — used for cost estimation only.
# The values intentionally lean conservative to keep the ₹20 cap safe.
_PRICING_USD_PER_1M: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (0.80, 4.0),
}
_USD_TO_INR = 84.0  # rough conversion for cost-cap accounting


def model_for(tier: Tier) -> str:
    return "claude-haiku-4-5" if tier == "fast" else "claude-sonnet-4-6"


def build_llm(max_tokens: int = 4096, tier: Tier = "smart") -> ChatAnthropic:
    """Return a ChatAnthropic instance pointed at MiniMax or Anthropic.

    *tier="fast"* selects Haiku for cheap structured tasks (JD parsing,
    validation, intake-question selection). *tier="smart"* is the default
    and returns Sonnet — used for resume tailoring and cover letters.

    MiniMax doesn't offer a separate fast model in this stack, so when
    MINIMAX_API_KEY is set both tiers route to the configured MiniMax model.
    """
    if settings.minimax_api_key:
        return ChatAnthropic(  # type: ignore[call-arg]
            model=settings.minimax_model,
            anthropic_api_key=SecretStr(settings.minimax_api_key),
            base_url=settings.minimax_api_base_url,
            max_tokens=max_tokens,
        )
    if settings.anthropic_api_key:
        return ChatAnthropic(  # type: ignore[call-arg]
            model=model_for(tier),
            anthropic_api_key=SecretStr(settings.anthropic_api_key),
            max_tokens=max_tokens,
        )
    raise RuntimeError("No LLM API key configured. Set MINIMAX_API_KEY or ANTHROPIC_API_KEY in .env")


def build_classifier_llm() -> ChatAnthropic:
    """Lightweight LLM for MOA intent classification (low token budget)."""
    return build_llm(max_tokens=30, tier="fast")


def estimate_cost_inr(*, model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate generation cost in INR based on token usage.

    Returns 0.0 for unknown models — callers should treat that as 'unmetered'
    and rely on the absolute ₹20 circuit breaker rather than this estimate.
    """
    pricing = _PRICING_USD_PER_1M.get(model)
    if not pricing:
        return 0.0
    in_rate, out_rate = pricing
    usd = (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate
    return round(usd * _USD_TO_INR, 4)
