# MiniMax M2.7 — Throughput & Platform Characteristics

**Status:** Open. Captures empirical observations from D12 CP3 Phase 2 + Phase 4.
**Created:** 2026-05-07 (D12 closure).
**Cross-references:** `llm-latency-provider-awareness.md`, `llm-output-token-budget-calibration.md`, `schema-aware-server-side-validation.md`.

## Empirical observations

D12 verification fired ~15 real-MiniMax calls across study_planner / career_coach / resume_reviewer / tailored_resume. Aggregated measurements:

- **Output throughput**: ~25-30 tok/sec consistently. Pure-LLM diagnostic for career_coach measured 28.2 tok/sec; study_planner ~25 tok/sec.
- **Thinking blocks consume ~38% of output tokens.** A response with `output_tokens=1280` typically splits to ~490 thinking + ~790 text. This is invisible to the parser (we skip thinking blocks) but visible to the bill (MiniMax bills both).
- **P50 latency for structured outputs is 2-3x higher than Anthropic Sonnet equivalents.** A `CareerCoachOutput`-shaped schema took 45s on MiniMax versus an estimated 12-15s on Sonnet. The factor is consistent across structured-output prompts.
- **Cache performance**: when the same system prompt is reused (e.g., during verification iterations), MiniMax reports `cache_read_input_tokens: 1280` on subsequent calls — significant cache hit, no observed correctness drift.
- **Per-request tail latency**: a single P95 measurement is ~60s for heavy schemas (career_coach with full schema), suggesting P50→P95 ≈ 1.5x. The 3x multiplier we use in `resolve_timeout_seconds` is conservative for MiniMax specifically; safe margin.

## What this means for calibration

`typical_latency_ms` in `app/agents/capability.py` is now provider-specific (MiniMax) for the agents we measured. If we add an Anthropic fallback in the future, the same agent would have a different `typical_latency_ms` against that provider. See `llm-latency-provider-awareness.md` for the architectural framing.

## What this means for cost

MiniMax pricing (per `_PRICING_USD_PER_1M`) is `$0.30 input / $1.20 output` per 1M tokens — roughly 10x cheaper than Sonnet. Even with the 38% thinking overhead, cost-per-response is dramatically lower than Anthropic. The latency tradeoff (2-3x slower) is the price.

## Triage

D17 (when scale + observability work lands). Re-measure these characteristics with production data once we have weeks of usage. Current measurements are from a 4-hour window of synthetic verification; production tail behavior may differ.

## Open question

**Is MiniMax tail latency stable enough for production student traffic?** D12 verification ran during low-traffic hours; observed throughput was consistent. If MiniMax-side throughput degrades during their peak hours, our `timeout_override_seconds` budgets may be insufficient. Worth a periodic synthetic-monitoring probe post-launch.
