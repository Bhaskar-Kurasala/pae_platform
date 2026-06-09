# D18 Phase B — batch flakiness under real-LLM load

**Status:** Open. **Severity: LOW** (signal-not-bug; tests pass in
isolation, intermittent in heavy batch; not blocking any contract).
**Origin:** D18 Phase B CP3 closure 2026-05-09. Observed across CP1
(BUG-CP1E original symptom), CP2 (occasional short-password flake),
CP3 (3 transient failures one batch run, 1 transient the next).

## What this is

Phase B's full journey suite (now 42 passing tests + 3 xfailed under
runner overlay) runs sequentially through pytest. Real-LLM tests
take 30-90 seconds each; cumulative LLM cost is ~₹35-40 across the
full suite. Under sequential heavy-batch load, ~1-3 tests fail per
run with shapes that pass cleanly when re-run in isolation:

  * Empty `response` field from `/agentic/default/chat` (BUG-CP1E
    original; auto-resolved by BUG-CP1F fix; observed once post-fix)
  * Test reaches assertion but returns 200 with unexpected shape
  * Connection / DB-pool transient under thread-isolated asyncpg

**Failure rate observed at CP3:** ~3-4 of 43 tests per batch run,
non-deterministic; same tests pass on re-run. Different tests fail
each batch run.

## Why isolation passes but batch fails

Three plausible causes (not mutually exclusive):

  1. **LLM provider rate-limiting / circuit-breaker.** Anthropic's
     API per-key per-minute caps could trip under sequential bursts,
     producing transient empty/error responses that pytest reads as
     200 with empty body.
  2. **Backend connection-pool saturation.** Real LLM calls take
     30-90s; if 3-4 are in-flight (pytest-playwright parallelism +
     test setup + test teardown using the bridge), asyncpg pool
     exhaustion is plausible.
  3. **Conversation-memory cache pollution.** Redis caches per-
     student conversation context with 1h TTL; cleanup_student_via_db
     removes the user but not its Redis-side conversation state.
     Subsequent tests reusing IDs (unlikely with uuid suffixes but
     not impossible) could see leaked context.

Cause #1 is most likely given the failure shapes (empty response,
unexpected shape).

## Why this isn't a contract bug

Each affected test passes deterministically when re-run in isolation
or in a small group. The contracts the tests assert ARE holding;
the test framework's pre-conditions (LLM availability, network
reliability) are what flakes.

This is the same shape as BUG-CP1E originally was — a downstream
symptom rather than a contract violation. BUG-CP1E auto-resolved
when BUG-CP1F was fixed; the residual ~3-4 / batch flakiness now
is a different pipeline (the agent paths now correctly track cost
but the LLM provider still occasionally returns flaky data).

## Mitigation options

**Option A — Re-run-on-failure pytest plugin** (`pytest-rerunfailures`).
Adds 1-2 retries to flaky tests; passes if any attempt succeeds.
Hides flakiness signal from CI but reduces noise.

**Option B — Stricter rate-limit handling in the backend.**
Detect Anthropic 429 / circuit-breaker responses and surface them
distinctly (currently they may project as empty `response` in
the orchestrator's failure mode). Tests would see a distinct
"rate limited" error and could xfail-with-retry or skip.

**Option C — Lower batch concurrency.** Configure CI to run
real-LLM tests at concurrency 1 (which is what the runner already
does, but pytest-asyncio + pytest-playwright sometimes fork).
Verify and pin.

**Option D — Accept as known signal.** Document the 3-4 per batch
flake rate as the operating envelope; if it climbs above 10%,
re-investigate.

## Recommendation

  * **Short-term (CP4):** Document and accept (Option D); re-run
    the suite once before CP4 closure to confirm batch passes
    with a single known-flaky test budget.
  * **Long-term (post-Phase-B):** Option B is the architecturally
    correct answer — distinguishing rate-limit from contract failure
    in the orchestrator gives Phase B tests a signal to act on
    (xfail-with-retry vs xfail-strict). Option A is the cheap
    backstop.

## Cross-references

  * `docs/followups/bug-cp1e-empty-response-under-batch.md` —
    closed; the originally-suspected version of this symptom.
  * `docs/followups/bug-cp1f-cost-tracking-zero-on-agentic-path.md`
    — closed; the actual fix that auto-resolved CP1E.
  * Phase B journey tests under `backend/tests/playwright/journeys/`
    — the affected surface.
