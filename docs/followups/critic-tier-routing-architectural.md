# Critic tier routing — architectural fix (D14 prerequisite)

## What

`app.agents.primitives.evaluation._DefaultLLM` (the Critic LLM client) calls `build_llm(max_tokens=…, tier="fast")`. The `tier="fast"` argument is meaningful only on the Anthropic route — it selects Haiku, a cheap model with no thinking blocks. On the MiniMax route, `tier="fast"` and `tier="smart"` both collapse to MiniMax M2.7 (per [llm_factory.py:77-78](../../backend/app/agents/llm_factory.py#L77-L78): *"MiniMax doesn't offer a separate fast model in this stack, so when MINIMAX_API_KEY is set both tiers route to the configured MiniMax model."*).

This is a provider-routing invariant break with two entangled symptoms:

1. **Budget mismatch.** The Critic was sized for Haiku (`max_tokens=400`). MiniMax M2.7 always emits a thinking block (~38% of output tokens per D12 measurements). Under M2.7 + max_tokens=400, the thinking block consumes the entire budget and the response has no text block — Critic content extraction returns `""`, verdict parse fails, retry path fires. This was D13's Bug 19, surfaced when mock_interview became the first v2 agent with `uses_self_eval=True`.
2. **Cost mismatch.** The Critic was designed to be cheap — Haiku evaluations cost ~₹0.005 per call. Under MiniMax M2.7, every Critic call costs ~₹0.20 (~40× higher). Acceptable for D13's single agent; not acceptable as D14+ inherits it across project_evaluator + practice_curator (likely both flip `uses_self_eval=True`).

## Bug 19 partial fix (D13 CP3 Phase 1.6)

Bumped `_DefaultLLM` max_tokens from 400 → 2048. This addresses the budget symptom (MiniMax thinking block now has ~800 tokens of headroom; text block has ~1200 tokens for verdict JSON + reasoning) but does not address the routing symptom — the Critic still uses M2.7 instead of Haiku, so cost-per-evaluation stays at ~₹0.20.

Pinned by [test_critic_minimax_content_extraction.py](../../backend/tests/test_agents/test_critic_minimax_content_extraction.py) — content extraction logic + max_tokens floor (≥1024).

## Architectural fix (D14 prerequisite)

`_DefaultLLM` should construct `ChatAnthropic` directly, bypassing `build_llm`'s MINIMAX preference, when `ANTHROPIC_API_KEY` is set. Roughly:

```python
def __init__(self) -> None:
    self._llm: Any | None = None

def _build(self) -> ChatAnthropic:
    from app.core.config import settings
    if settings.anthropic_api_key:
        # Critic always routes to Haiku — cheap, no thinking blocks,
        # 400 tokens is correct.
        return ChatAnthropic(
            model="claude-haiku-4-5",
            anthropic_api_key=SecretStr(settings.anthropic_api_key),
            max_tokens=400,
            timeout=_LLM_TIMEOUT_S,
            max_retries=_LLM_MAX_RETRIES,
        )
    # Fall back to the MiniMax-shape budget for environments without
    # an Anthropic key.
    from app.agents.llm_factory import build_llm
    return build_llm(max_tokens=2048, tier="fast")
```

Touches one file (~10 lines). Adds environment branching that needs verification under both configurations (Anthropic-only, MiniMax-only, both-keys).

## Why deferred to D14

- D14 likely flips `uses_self_eval=True` on at least project_evaluator (rubric-driven scoring naturally pairs with critic loop) and possibly practice_curator. D14's prerequisites should include the Critic routing fix so D14 agents land on Haiku-cost economics from day one.
- D13 ships with `mock_interview` paying ~₹0.20/Critic-call instead of ~₹0.005. Single-agent overshoot is tolerable; bundle overshoot would not be.
- The interim max_tokens=2048 fix is regression-tested and verified live under MiniMax (D13 CP3 Phase 1 re-run).

## Cost impact

| Configuration | Per-Critic cost | D13 budget impact |
|---|---|---|
| Today (max_tokens=2048, MiniMax M2.7) | ~₹0.20 | accepted for D13 |
| After D14 routing fix (Haiku direct) | ~₹0.005 | -97.5% |

## Cross-references

- [backend/app/agents/primitives/evaluation.py:340](../../backend/app/agents/primitives/evaluation.py#L340) — Critic's `build_llm` call (current interim fix).
- [backend/app/agents/llm_factory.py:70](../../backend/app/agents/llm_factory.py#L70) — `build_llm` and the MiniMax preference.
- [backend/app/agents/capability.py](../../backend/app/agents/capability.py) — `uses_self_eval` flag in capability metadata.
- [backend/tests/test_agents/test_critic_build_llm_signature.py](../../backend/tests/test_agents/test_critic_build_llm_signature.py) — Bug 18 regression (no `temperature` kwarg).
- [backend/tests/test_agents/test_critic_minimax_content_extraction.py](../../backend/tests/test_agents/test_critic_minimax_content_extraction.py) — Bug 19 regression (max_tokens floor).
- D13 CP3 closure — full Bug 18 + 19 history and three patterns (16, 17, 18).
