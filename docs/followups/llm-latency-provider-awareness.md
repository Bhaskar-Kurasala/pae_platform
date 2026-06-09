# LLM Latency — Provider-aware capability metadata

**Status:** Open. Architectural concern surfaced by D12 CP3 Phase 4.
**Created:** 2026-05-07 (D12 closure).
**Cross-references:** `app/agents/capability.py` (`AgentCapability.typical_latency_ms`), `minimax-throughput-platform-characteristics.md`, `llm-output-token-budget-calibration.md`.

## What this is

`AgentCapability.typical_latency_ms` is currently **provider-agnostic** — one number per agent. In production reality it's **provider-specific**: career_coach takes 45s on MiniMax vs. estimated 12-15s on Anthropic Sonnet. The number we ship is MiniMax-flavored because that's the active provider; if we add Anthropic fallback, the numbers don't apply.

## Why this matters

Three production scenarios degrade silently if metadata stays provider-agnostic:

1. **Multi-provider routing.** If safety classifier uses Anthropic Haiku while the rest of the agents use MiniMax, the safety classifier's `typical_latency_ms` should reflect Haiku, not MiniMax.
2. **Cost-aware routing.** Future feature: route lightweight calls to a cheaper/faster provider, heavy calls to a smarter one. Capability metadata is the natural place to express provider routing preferences.
3. **Provider failover.** If MiniMax is down and we fail over to Anthropic, our `timeout_override_seconds` budgets are wrong — Anthropic completes 2-3x faster, so a 90s budget for career_coach is overprovisioned during fallback (wastes time on a hung request before falling through).

## Proposed shape (D17+)

```python
class AgentCapability(BaseModel):
    typical_latency_ms_by_provider: dict[Literal["anthropic", "minimax"], int] = Field(...)
    # OR keep the simple field but add an explicit provider-active flag
    # at the registry level:
    # capability.typical_latency_ms is interpreted against the
    # active LLM provider; switching providers requires recalibration.
```

The simpler shape is: keep the single field, add a doc string saying "calibrate against the active provider; if multi-provider routing lands, refactor this." That's the path D12 took implicitly.

## Triage

D17 cleanup. Multi-provider routing is not on the near-term roadmap; this is a "ready when needed" concern. The current MiniMax-grounded values are correct for current production.
