# Critic tier routing — architectural fix (RESOLVED, pre-D13.5)

**Status:** Resolved. Architectural fix landed pre-D13.5 in commit following the D13 closure (`5cd7760`). See "Architectural fix (landed)" section below.

## What

`app.agents.primitives.evaluation._DefaultLLM` (the Critic LLM client) calls `build_llm(max_tokens=…, tier="fast")`. The `tier="fast"` argument is meaningful only on the Anthropic route — it selects Haiku, a cheap model with no thinking blocks. On the MiniMax route, `tier="fast"` and `tier="smart"` both collapse to MiniMax M2.7 (per [llm_factory.py:77-78](../../backend/app/agents/llm_factory.py#L77-L78): *"MiniMax doesn't offer a separate fast model in this stack, so when MINIMAX_API_KEY is set both tiers route to the configured MiniMax model."*).

This is a provider-routing invariant break with two entangled symptoms:

1. **Budget mismatch.** The Critic was sized for Haiku (`max_tokens=400`). MiniMax M2.7 always emits a thinking block (~38% of output tokens per D12 measurements). Under M2.7 + max_tokens=400, the thinking block consumes the entire budget and the response has no text block — Critic content extraction returns `""`, verdict parse fails, retry path fires. This was D13's Bug 19, surfaced when mock_interview became the first v2 agent with `uses_self_eval=True`.
2. **Cost mismatch.** The Critic was designed to be cheap — Haiku evaluations cost ~₹0.005 per call. Under MiniMax M2.7, every Critic call costs ~₹0.20 (~40× higher). Acceptable for D13's single agent; not acceptable as D14+ inherits it across project_evaluator + practice_curator (likely both flip `uses_self_eval=True`).

## Bug 19 partial fix (D13 CP3 Phase 1.6)

Bumped `_DefaultLLM` max_tokens from 400 → 2048. This addresses the budget symptom (MiniMax thinking block now has ~800 tokens of headroom; text block has ~1200 tokens for verdict JSON + reasoning) but does not address the routing symptom — the Critic still uses M2.7 instead of Haiku, so cost-per-evaluation stays at ~₹0.20.

Pinned by [test_critic_minimax_content_extraction.py](../../backend/tests/test_agents/test_critic_minimax_content_extraction.py) — content extraction logic + max_tokens floor (≥1024).

## Architectural fix (landed)

`_DefaultLLM.ainvoke_text` constructs `ChatAnthropic` directly when `settings.anthropic_api_key` is set, bypassing `build_llm`'s MiniMax preference:

```python
if settings.anthropic_api_key:
    self._llm = ChatAnthropic(
        model="claude-haiku-4-5",
        anthropic_api_key=SecretStr(settings.anthropic_api_key),
        temperature=0.0,    # restored — direct construction has no Bug-18 constraint
        max_tokens=400,     # correct for Haiku's no-thinking output shape
        timeout=15.0,       # Critic-specific; main agent's 90s is overkill
        max_retries=0,
    )
else:
    # Fallback for environments without Anthropic key — MiniMax with
    # bumped max_tokens (D13 Bug 19 interim fix shape preserved).
    from app.agents.llm_factory import build_llm
    self._llm = build_llm(max_tokens=2048, tier="fast")
```

Pinned by [test_critic_tier_routing.py](../../backend/tests/test_agents/test_critic_tier_routing.py) — 6 tests covering both branches + temperature=0.0 invariant + SecretStr usage + Bug 18/19 regression intersection.

## Why this landed before D13.5

- D14's project_evaluator and practice_curator both likely flip `uses_self_eval=True` (rubric-driven scoring pairs naturally with the Critic loop). The architectural fix lets D14 agents land on Haiku-cost economics from day one (~₹0.005/Critic-call) instead of inheriting D13's ~₹0.20/Critic-call interim.
- The fix is small (one if/else branch in one file, ~10 lines) and well-isolated — production paths and the D13 interim fallback both still work.
- Restores `temperature=0.0` for the Critic that D13 Bug 18 had to drop (the drop was forced by `build_llm` not accepting `temperature`; direct `ChatAnthropic` construction has no such constraint).

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
