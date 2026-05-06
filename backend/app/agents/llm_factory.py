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
    # MiniMax M2.7 via Anthropic-compatible endpoint (verified May 2026).
    # Roughly 10x cheaper than Sonnet — see docs/followups/llm-cost-tracking-silent-zero.md
    # for what this means for Pass 3i §I.3 cost projections.
    "MiniMax-M2.7": (0.30, 1.20),
}
_USD_TO_INR = 84.0  # rough conversion for cost-cap accounting


def model_for(tier: Tier) -> str:
    return "claude-haiku-4-5" if tier == "fast" else "claude-sonnet-4-6"


# PR2/B5.1 — Anthropic client timeouts and retry budget.
#
#   * `timeout` is the HARD wall-clock cap on a single LLM round-trip.
#     Originally 30s (Anthropic-era; structured-output Sonnet calls
#     completed well within that). Bumped to 90s during D12 CP3 Phase 4
#     after pure-LLM diagnostic measured career_coach's MiniMax round-trip
#     at 45.4s for a single attempt — the prior 30s was killing every
#     substantive structured-output call BEFORE it could return. The 90s
#     ceiling absorbs MiniMax P95 (~60s) with safety margin while still
#     preventing pathological hangs from leaking into request handlers.
#     The orchestrator's per-agent dispatch wrapper (resolve_timeout_seconds,
#     30-60s with 120s tailored_resume override) sits ABOVE this and
#     remains the first line of defense.
#   * `max_retries` is the SDK-internal retry on transient 5xx / network
#     errors. Was 3 (SDK default); dropped to 1 in Phase 4 because at
#     90s timeout, retries are about transient network failures (rare),
#     not slow generations (which we now allow time for). 3x retries on
#     90s = 270s of cumulative wait and was dangerous; 1 retry is
#     sufficient for one network blip without compounding the wait.
_LLM_TIMEOUT_S = 90.0
_LLM_MAX_RETRIES = 1


# Per-tier max_tokens defaults used when the caller doesn't pass an
# explicit value. Smart-tier was bumped from 4096 to 8192 in D12 CP3
# Phase 4 — career_coach's expanded output schema (post-Bug-15 Literal
# allowlist enumeration) plus MiniMax thinking blocks (~38% of output)
# consistently exceeds 4096. 8192 provides headroom; MiniMax bills per
# consumed token so worst-case is unchanged. Fast-tier (Haiku for
# classification/JD-parsing) stays at 4096 — those tasks have small
# structured outputs and don't trigger the MiniMax thinking-block bloat.
_DEFAULT_MAX_TOKENS_BY_TIER: dict[str, int] = {
    "smart": 8192,
    "fast": 4096,
}


def build_llm(max_tokens: int | None = None, tier: Tier = "smart") -> ChatAnthropic:
    """Return a ChatAnthropic instance pointed at MiniMax or Anthropic.

    *tier="fast"* selects Haiku for cheap structured tasks (JD parsing,
    validation, intake-question selection). *tier="smart"* is the default
    and returns Sonnet — used for resume tailoring and cover letters.

    MiniMax doesn't offer a separate fast model in this stack, so when
    MINIMAX_API_KEY is set both tiers route to the configured MiniMax model.

    Every client returned carries a 90s hard timeout and a 1-retry budget
    for transient failures (PR2/B5.1, updated in D12 CP3 Phase 4) —
    without these, a wedged upstream can hang a request indefinitely
    and starve the workers.

    `max_tokens` defaults to a tier-specific value (smart=8192, fast=4096).
    Callers that need a tighter budget (e.g. classifiers) pass an explicit
    value to override.
    """
    effective_max_tokens = (
        max_tokens
        if max_tokens is not None
        else _DEFAULT_MAX_TOKENS_BY_TIER.get(tier, 4096)
    )
    if settings.minimax_api_key:
        return ChatAnthropic(  # type: ignore[call-arg]
            model=settings.minimax_model,
            anthropic_api_key=SecretStr(settings.minimax_api_key),
            base_url=settings.minimax_api_base_url,
            max_tokens=effective_max_tokens,
            timeout=_LLM_TIMEOUT_S,
            max_retries=_LLM_MAX_RETRIES,
        )
    if settings.anthropic_api_key:
        return ChatAnthropic(  # type: ignore[call-arg]
            model=model_for(tier),
            anthropic_api_key=SecretStr(settings.anthropic_api_key),
            max_tokens=effective_max_tokens,
            timeout=_LLM_TIMEOUT_S,
            max_retries=_LLM_MAX_RETRIES,
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
