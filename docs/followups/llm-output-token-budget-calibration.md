# LLM Output Token Budget Calibration

**Status:** Open. Lesson from D12 CP3 Phase 4 Bug 16.
**Created:** 2026-05-07 (D12 closure).
**Cross-references:** `app/agents/llm_factory.py::_DEFAULT_MAX_TOKENS_BY_TIER`, `minimax-throughput-platform-characteristics.md`.

## What we learned

`max_tokens` defaults set against Anthropic-era output sizes do not account for:

1. **MiniMax thinking blocks** (~38% of output tokens; the assistant produces extended reasoning before the structured response).
2. **Post-Bug-15 schema enumeration** in prompts (explicit field type listings make models produce more comprehensive outputs).

Original D12 v2 agents called `build_llm(max_tokens=2048, tier="smart")` (career_coach, resume_reviewer) or `max_tokens=1800` (study_planner, tailored_resume_llm). All four hit truncation under MiniMax once prompts were Bug-15-enumerated. Fix: bump to 8192 across all four; raise smart-tier default to 8192 in `llm_factory`.

## Rule of thumb (D13+ migrations)

For any agent expected to produce structured-JSON output under MiniMax:

```
max_tokens >= 2 × (expected text-only output tokens) + 50% thinking margin
```

For an agent whose schema typically produces ~2000 token text output: `2 × 2000 = 4000`, plus 50% margin = `~6000`. Round up to 8192 (smart-tier default).

For lightweight-output agents (classifiers, single-field decisions): keep low (e.g., 30 for the route classifier). Don't blanket-apply 8192.

## How to measure expected output

The Phase 2 + Phase 4 pure-LLM diagnostic pattern (see `scripts/d12_cp3_phase2_diagnose_llm.py`, `scripts/d12_cp3_phase4_career_coach_pure_llm.py`) measures output token count for one representative call. Run that for each new agent during CP2 stub-LLM smoke; the measured value sets the `max_tokens` ceiling.

## Triage

Document as discipline; apply per-agent during D13+ migrations. No retroactive changes needed for D12 (which is now over-budgeted but correctly so).
