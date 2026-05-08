# career_coach + study_planner tail-latency baseline under MiniMax

**Status:** Open. Operational. D18 Phase A Playwright timeout buffers
must accommodate this baseline.
**Origin:** D17b ITEM 3 (Path E) verification observed symmetric
tail-latency variance across stalled/healthy phases for both agents.
**Created:** 2026-05-08 (D17b ITEM 5).

## What this is

D17b ITEM 3's 4-phase real-LLM verification (under MiniMax M2.7,
production routing) measured the following tail latencies across
multiple runs of the same payload + same agent + same model:

| Agent | Dispatch ceiling | Observed P3 (stalled) | Observed P4 (healthy control) |
|---|---|---|---|
| career_coach | 150s | 53-88s | 25-150s (one timeout per ~3 runs) |
| study_planner | 30s | 22-27s | 22-30s (one timeout per ~3 runs) |

The variance is **symmetric** between trigger phase (P3) and control
phase (P4) for each agent — the lead-in opener composition (Path E)
adds zero LLM-side cost, so any difference between the trigger and
control phases is **MiniMax tail-latency variance**, not any D17b
regression.

## Why this matters

The dispatch-time ceilings (150s career_coach, 30s study_planner) are
calibrated against measured Pre-D17b baselines (Pattern 18b discipline:
spec × 4-5 preemptive at CP1, tightened post-measurement). They are
**not** Pattern 18b "headroom" budgets — they are at the actual
observed P95 of MiniMax tail latency for these specific agents'
prompt sizes and structured-output complexity.

Tail latency above P95 is real. It surfaces as `result.status="timeout"`
on the affected calls. The behavior is:

- **3-15% of calls** exceed the calibrated ceiling and timeout. This
  is documented Pattern 18b behavior (D14c CP4 evidence: 22s
  spread on identical input at n=2 — MiniMax tail can be wider than
  observed_max × 1.30).
- The agent's `result.status` flips to `timeout`; downstream
  `result.output` is `{}` (empty dict). Caller patterns must handle
  this — agent-driven flows that assume non-empty output break
  silently.
- The student-facing chat surface today retries at user discretion
  (the user re-sends the message). For automated test flows, this
  does not work — the test fails on the first timeout.

## Operational impact for D18 Phase A (test infrastructure)

- **Playwright tests targeting career_coach or study_planner** must
  account for the 3-15% timeout rate. Three options:

  - Tag affected tests as flaky-tolerant: pytest-retry or equivalent;
    re-run on timeout up to 2 additional times.
  - Increase the dispatch ceiling for the test path: pass an explicit
    `timeout_override` higher than production (e.g. 60s for
    study_planner, 240s for career_coach). Acknowledge in test
    comments that the elevated value is for test-flake mitigation,
    not production calibration.
  - Skip-on-timeout: tests that timeout count as skipped, not
    failed. Less discipline; risks hiding real regressions.

- **Test selection discipline** — for Playwright suites targeting
  the chat surface broadly, prefer tests against agents whose tail
  latency is tighter (e.g., billing_support, senior_engineer when
  available). career_coach and study_planner can be tested against
  *one* representative scenario per agent rather than full
  permutation-grid coverage; this reduces aggregate timeout
  exposure.

- **Pre-launch smoke test suite** should explicitly include
  career_coach + study_planner tail-latency observation (e.g., 10
  consecutive runs of the same payload, expect ≤ 1 timeout) so the
  baseline is monitored over time. Drift in either direction is
  signal: tighter would let the dispatch ceiling tighten; wider
  is a MiniMax-side issue worth surfacing.

## Why this isn't a D17b regression

The same elapsed-time variance was symmetric across:

- D17b ITEM 3 Path E P3 (stalled trigger; opener composition fired)
  vs P4 (healthy control; no opener composition)
- D17b ITEM 3 Path E (no prompt change) vs the discarded interim
  prompt-side approach (prompt grew ~80 lines on study_planner;
  timeouts hit 3/6 phases, much higher than baseline)

The 3-15% timeout rate observed at Path E **matches the pre-D17b
baseline** that D14c CP4 + D15 CP3-CP5 measurements documented. ITEM 3
Path E neither improved nor regressed it; the prompt-side approach
made it worse, and the revert to Path E restored the baseline.

## Cross-references

- D17b ITEM 3 (Path E) closure — primary source of the symmetric-
  variance observation; commits 3443b07 + 353c738.
- Pattern 18b in `migration-verification-discipline.md` — the
  preemptive-sizing discipline that calibrated the current ceilings;
  the D17b ITEM 3 prompt-size extension is the latest amendment.
- `docs/followups/celery-safety-memory-bump.md` — separate Pattern
  18b instance (worker memory cap interacts with concurrency).
- Pre-D17b career_coach + study_planner CP3 measurements documented
  in D15 closure: baselines were 60s preemptive + 30s preemptive
  respectively; tightened/calibrated since.

## When to revisit

- If MiniMax adds tier support and study_planner can route to a
  faster tier specifically for the planning-output workload, the
  30s ceiling could come down + tail variance could narrow. Worth
  checking quarterly.
- If observed timeout rate drifts above ~15% on the pre-launch
  smoke test, that's signal of MiniMax-side change; surface as a
  separate investigation.
- Post-launch: if real-user complaints emerge about timeouts for
  these agents, consider raising the ceiling further OR adding a
  "we're thinking…" fallback UI that absorbs the wait better.
