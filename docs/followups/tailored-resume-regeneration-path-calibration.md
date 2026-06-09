# tailored_resume baseline-pipeline calibration gap

**Status:** Open — promoted from "regeneration-path" framing to "baseline-pipeline" framing after D13.5 Stage 3.2 surfaced the same timeout shape on strong-evidence input.
**Created:** 2026-05-07 (D13.5 Stage 3 first call).
**Updated:** 2026-05-07 (D13.5 Stage 3.2 — strong-evidence input also timed out, ruling out the "regeneration trigger" hypothesis).
**Triage:** D17 cleanup; earlier if production traffic shows >10% timeout rate on tailored_resume calls.
**Cross-references:** D12 CP3 Phase 3 calibration; `dispatch.py` timeout resolver; `capability.py` tailored_resume entry; `services/tailored_resume_service.py`.

## What

`tailored_resume`'s service-layer pipeline structurally runs **at least two inner LLM calls** as part of its baseline path (NOT a quality-driven regeneration trigger as initially hypothesized). Both inner calls log as `career.resume_content_generated` followed by `career.resume_regenerated force=False`. Across two D13.5 Stage 3 verification attempts — one with sparse-evidence input, one with strong-evidence input — the agent timed out at the 120s `timeout_override_seconds` budget mid-pipeline.

The original "regeneration trigger" hypothesis in this doc's first revision predicted that strong-evidence input would land single-pass and complete within 120s. **That hypothesis was falsified by Stage 3.2:** strong-evidence input also fires the second `career.resume_regenerated` event and also exceeds 120s. The two log events are baseline pipeline behavior, not conditional.

## Evidence

### Attempt 1 — sparse-evidence input (D13.5 Stage 3 first call)

Input: claim-heavy resume with sparse-but-real evidence (3 years experience, single capstone) targeted at a Senior GenAI Engineer role requiring 5+ years and team leadership.

```
t=6      tailored_resume.started
t=48     career.resume_content_generated (#1 — first inner LLM)
t=48     career.resume_regenerated       force=False
t=67     profile_aggregator.bundle_built
t=86     career.resume_content_generated (#2 — second inner LLM)
t=86     career.resume_regenerated       force=False
t=120    agentic.timeout — producer killed
```

### Attempt 2 — strong-evidence input (D13.5 Stage 3.2 retry)

Input: 6-year senior engineer with 5+ quantified accomplishments (200k queries/day RAG pipeline, open-sourced eval harness with 800 GH stars, multi-tenant gateway, mentorship outcomes). Specifically chosen because the original hypothesis predicted single-pass completion on strong evidence.

```
t=8      tailored_resume.started
t=46     career.resume_content_generated (#1 — first inner LLM)
t=46     career.resume_regenerated       force=False
t=46     profile_aggregator.bundle_built
t=79     career.resume_content_generated (#2 — second inner LLM)
t=79     career.resume_regenerated       force=False
t=120    agentic.timeout — producer killed
```

**Both attempts show the same shape: two inner LLM calls fire regardless of input quality.** The `force=False` parameter on both `career.resume_regenerated` events confirms this is default-path behavior, not a conditional regeneration. The total elapsed under MiniMax exceeds the 120s budget in both attempts (~120s+ before the dispatch wrapper killed the producer).

In both cases the agent's `run()` did not return; `call_agent` returned `status="timeout"`; `dispatch_single` correctly skipped the validator per the documented producer-failure semantic. **No D13.5 architectural breakage** — the chain wiring handled the timeout cleanly.

## Why this matters

`tailored_resume`'s `typical_latency_ms=10000` and `timeout_override_seconds=120` are **structurally undersized** for the agent's baseline pipeline under MiniMax. The 120s figure was calibrated in D12 CP3 Phase 3 — but D12's CP3 Phase 4 individual-call test passed within 120s on a different input shape (Stripe + LangChain candidate). Two Stage 3 attempts at D13.5 timing both took >120s under MiniMax. The root cause is most likely:

1. **MiniMax inner-LLM call latency is higher than D12's measurements.** Each `career.resume_content_generated` event takes ~30-40s under MiniMax in these runs; two calls structurally clear 60-80s before any other pipeline overhead.
2. **The `career.resume_regenerated force=False` event likely represents a baseline second pass** (probably the cover-letter generation or ATS-validation pass), not a conditional regeneration triggered by quality scores.

D13.5's mandatory validation chain handles the timeout cleanly — `dispatch_single` correctly returns when the producer times out, and the validator is correctly skipped per the documented producer-failure semantic. **No D13.5 architectural breakage.** But the user-facing experience under timeout is poor: the dispatch layer returns `AgentResult(blocked=False, structured_output=None)`, which doesn't communicate the timeout to the frontend cleanly. That's a separate dispatch-layer messaging gap worth flagging.

## Required investigation (D17 or earlier)

1. **Map the baseline pipeline.** Read `services/tailored_resume_service.py::generate_tailored_resume` end-to-end. Document each inner LLM call (JD parse, evidence allowlist, tailoring, cover letter, validation per the D12 follow-up note). Confirm whether the two `career.resume_content_generated` events represent separate stages or a literal repeated call.
2. **Measure inner-LLM latency under MiniMax.** Add per-stage timing log lines in the service (one per inner LLM call). Run 5 representative inputs against MiniMax and capture P50/P95 for each stage. Compare against D12 CP3 Phase 3's measurements (which passed under 120s) to confirm the regression.
3. **Decide remediation** based on the data:
   - Bump `timeout_override_seconds` to cover the actual baseline pipeline (likely 180-240s under MiniMax). Cheapest; risks per-call cost increase if some inner LLM calls can be eliminated.
   - Audit whether all inner LLM calls are necessary (e.g., if cover-letter generation can be split to a separate dispatch, the producer agent shrinks).
   - Add user-facing graceful-timeout messaging at the dispatch layer when `status="timeout"` so the frontend can surface "your tailoring is taking longer than expected" instead of a silent empty response.
4. **Write a regression test** that pins whichever shape the fix takes (live-LLM smoke against representative inputs, asserting <120s elapsed if the budget stays at 120s, or asserting <NEW_BUDGET if bumped).

## Why D13.5 doesn't fix this

D13.5's scope is the mandatory-validation chain architecture, not tailored_resume's service-layer pipeline. The chain wiring works correctly under timeout (verified: validator was skipped per the documented producer-failure semantic; baseline tests still pass; Stage 2 stub-smoke covers all 9 differentiated failure modes including this one). Bumping the budget here would mask the underlying calibration question without resolving it.

**D13.5 Stage 3 live verification could not exercise the chain end-to-end** because tailored_resume's baseline pipeline exceeds its budget under MiniMax in this environment. D13.5 closes with stub-smoke verification of the chain architecture (22/22 tests passing, 9 failure modes differentiated) and live verification deferred until this calibration gap resolves. The architectural pieces — capability extensions, adapter, dispatch wiring, output projection, chain-summed timeout, fail-loud vs best-effort semantics — are all stub-smoke verified.

## Cross-references

- [backend/app/agents/capability.py](../../backend/app/agents/capability.py) — `tailored_resume` capability entry with `timeout_override_seconds=120`
- [backend/app/services/tailored_resume_service.py](../../backend/app/services/tailored_resume_service.py) — service-layer pipeline; regeneration trigger lives here
- [backend/app/agents/dispatch.py](../../backend/app/agents/dispatch.py) — `dispatch_single`'s timeout handling (`should_validate` correctly short-circuits on producer timeout)
- D12 CP3 Phase 3 (commit `c1f941a`) — original calibration that didn't measure regeneration-path latency
- D13.5 Stage 3 closure — full timeline and diagnosis
