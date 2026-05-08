# BUG-CP1E — empty response from /agentic/default/chat under batch

**Status:** ✅ **CLOSED** at pre-CP2 bug remediation 2026-05-09 — auto-resolved by the BUG-CP1F fix.
**Severity at discovery:** LOW-MEDIUM.
**Origin:** D18 Phase B CP1 journey (e) authoring, 2026-05-09.
**Surfaced by:** test_cp1_journey_e_career_coach.py
(@pytest.mark.xfail strict=False, Convention A).
**Closed by:** Auto-resolved when BUG-CP1F fix landed
(`_track_llm_usage` added to career_coach_v2 + others).

## What this is

POST `/api/v1/agentic/default/chat` returns 200 with an empty
`response` field (and `agent_name` set, `blocked=false`,
`block_reason=null`, `decline_reason=null`) under batch test
execution. The same call passes consistently in isolation:

  * Isolation run: `1 passed in 34s` (real LLM, substantive
    response, behavior-shape clean).
  * Batch run (after journeys c/f/d already executed): empty
    `response` field, test fails.

## Suspected causes

Three plausible explanations, ordered by likelihood:

  1. **Conversation memory pollution.** The orchestrator caches
     conversation context in Redis (1h TTL per `docs/AGENTS.md`).
     Batch tests register fresh users each time, so user-keyed
     memory shouldn't collide — but if there's a session-scoped
     cache key that shares across users, prior tests' contexts
     might bleed into the new test.
  2. **LLM rate limit / circuit breaker.** Sequential real-LLM
     calls (4 in the batch: f, e, c, d) within ~2 minutes might
     trip an Anthropic rate-limit or an internal circuit-breaker.
     Empty response is one possible failure mode.
  3. **Race in the supervisor's intent classification.** When the
     supervisor LLM call returns an empty/incomplete response, the
     orchestrator may dispatch to a default agent that itself
     returns empty if it can't determine intent.

## Why xfail is strict=False (not strict=True)

Per Convention A, strict=True flips xpassed → unexpected-pass →
test failure. But this bug is non-deterministic — sometimes the
batch passes, sometimes it fails. strict=False lets xpassed
silently report as xpassed (so we get a signal when behavior
stabilizes) without hard-failing on the inherent flakiness.

When the underlying issue is fixed and the test passes
deterministically in batch, drop the xfail entirely.

## Resolution (2026-05-09) — auto-resolved by BUG-CP1F

Per the architect's diagnose-first directive, BUG-CP1F was
investigated and traced to per-agent missing `_track_llm_usage`
calls (NOT supervisor orchestration as initially hypothesized).
Fix added the missing calls to career_coach_v2 (among others).

Re-running journey (e) batch under the runner overlay post-fix:
journey (e) passes consistently. The "empty response" symptom
disappears with the cost-tracking fix in place.

Best-fit explanation: when `_track_llm_usage` was missing,
`agent_actions.output_data` was incomplete (llm_calls=0,
tokens=0). Whatever downstream code path was inspecting that
output_data — possibly a circuit-breaker, possibly the
orchestrator's response synthesis — was treating the all-zeros
state as "no LLM result" and projecting an empty response back to
the client. With usage now tracked, the output_data is complete
and the response synthesis works correctly.

### Verification

  * journey (e) `test_career_coach_responds_with_role_aware_guidance`:
    xfail-loose dropped; passes in batch alongside f and d (4/4
    in 135s).
  * Full CP1 journey suite: 21 passed + 3 xfailed (stripe-env-gated
    only). No flakiness in batch run.

This is exactly the auto-resolution the architect's directive
anticipated when it said "if F resolves cleanly, re-test E to see
if it auto-resolves." Closed as duplicate of BUG-CP1F.

## Cross-references

  * `backend/tests/playwright/journeys/test_cp1_journey_e_career_coach.py` — the xfailed test.
  * BUG-CP1F-COST-TRACKING — same orchestration path; possibly
    related root cause if the orchestrator's wrap/unwrap is the
    common bug surface.
