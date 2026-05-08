# BUG-CP1E — empty response from /agentic/default/chat under batch

**Status:** Open. **Severity: LOW-MEDIUM** (flaky behavior; passes
in isolation, fails intermittently in batch).
**Origin:** D18 Phase B CP1 journey (e) authoring, 2026-05-09.
**Surfaced by:** test_cp1_journey_e_career_coach.py
(@pytest.mark.xfail strict=False, Convention A).

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

## Verification when fix lands

1. Drop `@pytest.mark.xfail` from
   `test_cp1_journey_e_career_coach.py::test_career_coach_responds_with_role_aware_guidance`.
2. Run journey (e) in isolation 5 times → 5/5 pass (baseline).
3. Run full CP1 journey batch 5 times → 5/5 pass for journey (e)
   (regression guard).

## Cross-references

  * `backend/tests/playwright/journeys/test_cp1_journey_e_career_coach.py` — the xfailed test.
  * BUG-CP1F-COST-TRACKING — same orchestration path; possibly
    related root cause if the orchestrator's wrap/unwrap is the
    common bug surface.
