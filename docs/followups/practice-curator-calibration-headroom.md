# practice_curator calibration headroom — 1% margin observation

**Status:** Open. D14b CP3 + CP4 measurements show practice_curator landing at ~59-60s under the 60s `timeout_override_seconds` budget. Headroom is ~1% above the 60s cap.
**Created:** 2026-05-07 (D14b closure).
**Triage:** D17 cleanup or production-data trigger — bump override to 75-90s if production P95+ lands in the 55-60s window.
**Cross-references:** `app/agents/capability.py` (practice_curator entry); D14b CP3 closure (calibration measurements); Pattern 18 in `migration-verification-discipline.md` (MiniMax structured-output latency multiplier).

## What

D14b CP3 measured 3 phases under MiniMax M2.7:
- Phase 1 (easy + recursion + coding): 40.12s
- Phase 2 (hard + system_design): 42.69s
- Phase 3 (all-empty path): 59.30s

D14b CP4 post-cutover smoke (Phase-1-shape input): 59.91s

P95 across 4 calls: ~59.91s. Current `timeout_override_seconds=60`. **Headroom is 1%.** The all-empty path (Phase 3) and the post-cutover smoke (Phase 1 shape) both landed within 1s of the budget ceiling.

## Why this isn't blocking ship

1. **All 4 calls completed successfully.** No timeouts at the 60s budget; the `result.status="ok"` path held across all measurements.
2. **The 60s budget was deliberately set above measured P95.** D14b CP3 saw the 30s-floor formula budget time out repeatedly; the 60s override was the response to actual measurements, not aspirational.
3. **Production P95 vs. dev P95 may differ.** MiniMax latency varies by time of day, account quota, and content shape. The dev measurements are 4 data points from a single window; production traffic distribution is unknown.
4. **D14c project_evaluator's calibration guidance per Pattern 18 generalization is "set override to 90s proactively"** for the next agent in the line. That's effectively the higher-bar shape; if production data shows practice_curator needs the same, the precedent is set.

## What would trigger a bump

- Production agent_actions audit shows `practice_curator` with `status='timeout'` rate >2% over a 7-day window
- P95 elapsed in production lands in the 55-60s window for >25% of calls (signals headroom is being eaten regularly)
- Specific user-facing complaints about "exercises taking too long to generate" tied to dispatch-layer timeout messaging

## Recommended bump if triggered

Set `timeout_override_seconds=90` matching the D14c project_evaluator preemptive calibration. 30s additional headroom covers the realistic P99 + safety classifier overhead + tool call jitter without inflating the chain budget further.

If 90s itself proves insufficient (which would be surprising — would indicate a structural pipeline change since D14b), revisit at that point with measurements rather than guessing.

## Cross-references

- [backend/app/agents/capability.py](../../backend/app/agents/capability.py) — `timeout_override_seconds=60` site
- D14b CP3 closure — full measurement table
- D14b CP4 post-cutover smoke — final 59.91s measurement
- `migration-verification-discipline.md` Pattern 18 — generalized MiniMax latency multiplier guidance
