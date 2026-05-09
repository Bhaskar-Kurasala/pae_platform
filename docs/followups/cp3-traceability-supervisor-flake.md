# Real-LLM batch-flake cluster (CP1F-shape + supervisor-malformed-JSON)

## 2026-05-09 update — CP3 closure adds two more flakes; rename advised

The original surfacing was the supervisor over-length flake (50%
isolation rate). D19.1 CP3 closure-time verification surfaced two
additional transient flakes that share a family:

  * `test_cp1_journey_e_career_coach.py::test_career_coach_responds_with_role_aware_guidance`
    — failed in CP3 Phase B sweep; 3/3 isolation runs **passed**.
    Failure mode in suite: supervisor LLM emitted malformed JSON
    (`JSONDecodeError: Expecting ',' delimiter: line 1 column 1054`),
    orchestrator returned blocked decline with empty response.

  * `test_cp1_journey_f_resume_reviewer.py::test_resume_reviewer_records_cost_inr_for_real_llm_call`
    — failed in CP3 Phase B sweep; 3/3 isolation runs **passed**.
    Failure mode in suite: no `agent_actions` row for `resume_reviewer`,
    suggesting the dispatch chain didn't reach the specialist (same
    family as the supervisor over-length pattern — supervisor's
    output bypassed validation; specialist never invoked).

Combined evidence across CP2 + CP3 verification runs:

| Test | Pre-CP1 | CP2 sweep | CP2 isolation | CP3 sweep | CP3 isolation |
|------|---------|-----------|---------------|-----------|---------------|
| career_coach_responds_with_role_aware_guidance | pass | pass | — | **fail** | 3/3 pass |
| resume_reviewer_records_cost_inr_for_real_llm_call | pass | pass | — | **fail** | 3/3 pass |
| career_coach_writes_agent_actions_with_full_cost_tracking | pass | **fail** | 2/4 pass | pass | — |

These are **batch-flakes under suite load**, not isolation flakes.
Different from the original supervisor over-length flake which
failed ~50% in isolation. Cumulative observation: D19.1's
substrate work (CP1 contextvars + CP2 metric emission + CP3
OTel auto-instrumentation) adds per-call latency that occasionally
pushes a real-LLM journey path over a retry / timeout threshold
under parallel-ish suite execution.

**Suggested rename when this followup is acted on:**
`real-llm-batch-flake-cluster.md`. The supervisor over-length
mechanism (Section "Mechanism" below) is one instance; the
malformed-JSON / dispatch-skip patterns above are sibling
instances. All three trace back to non-deterministic supervisor
LLM output bypassing the validation that's supposed to keep
specialist inputs well-formed.

## Disposition update

Original recommendation: A+B+C (prompt tightening + truncation +
cost-tracking gap fix), ~₹2-4 cost.

Updated recommendation: same + add a **suite-mode OTel sampler
override**. Set `OTEL_TRACES_SAMPLER_ARG=0.0` in the
`docker-compose.playwright.yml` overlay so spans are created but
immediately unsampled, removing per-call OTel overhead in the
test environment. Production keeps the 1% baseline. Estimated
~₹0 — one-line env addition + a single Phase B re-run to confirm
flake rate drops.

This is incremental to A+B+C, not a substitute. The underlying
supervisor non-determinism is still a real pre-launch concern.

---

# (original) Supervisor `constructed_context.user_message` over-length flake

**Status:** Open. Real-LLM flake pre-existing CP2; surfaced
2026-05-09 during D19.1 CP2 closure-time test verification. Affects
exactly one Phase B test:
`tests/playwright/journeys/test_cp3_traceability_agentic.py::test_career_coach_writes_agent_actions_with_full_cost_tracking`.

**Severity:** Medium. Test flakiness is the visible symptom; the
underlying behaviour (supervisor producing over-long composite
context fields) is a real product-quality signal worth addressing
before launch.

**Disposition:** Registered as Phase B / launch-readiness follow-up;
not gating D19.1 CP3. Three remediation candidates surfaced below;
decision deferred to a focused micro-deliverable (~₹2-4 cost).

---

## Empirical evidence

Phase B suite run 2026-05-09 post-D19.1 CP2:
`53 passed + 1 failed + 4 xfailed` in 11m51s. The 1 failure was
the test above.

Isolation re-runs (4×) in canonical playwright-runner environment
against `playwright_test` DB:

| Run | Outcome | Wall-clock |
|-----|---------|------------|
| 1   | passed  | 48.6s |
| 2   | failed  | 54.5s |
| 3   | failed  | 46.4s |
| 4   | passed  | 47.2s |

Plus 2 earlier ad-hoc isolation runs (1 fail, 1 pass). Cumulative:
**3 pass / 3 fail = ~50% flake rate.**

D18 Phase B closure (`d18-phase-b-test-coverage-overview.md`)
characterised batch-flakiness as "~1-3 transient-flake per
full-suite run; isolation re-run deterministic". The empirical
data shows isolation re-run is **not** deterministic for this
specific test on this specific data shape. That's a documentation
update worth making at the same time as the fix.

## Mechanism

Trace through `app/services/agentic_orchestrator.py` →
`app/agents/dispatch.py` → `CareerCoachInput`:

1. Supervisor runs (real LLM call to Sonnet via the configured
   factory). Returns a `RouteDecision` whose
   `constructed_context: dict[str, Any]` is built by the LLM
   from `student_snapshot`, `recent_agent_actions`, conversation
   thread, and the user's request body.

2. Per `app/agents/prompts/supervisor.md` line 92, the supervisor
   "Build[s] `constructed_context` keyed for the target agent".
   Per line 116, the prompt explicitly warns "Mix your reasoning
   into `constructed_context`" as a thing to avoid — but the LLM
   is non-deterministic about following that guidance.

3. When dispatching to `career_coach`, the supervisor sometimes
   includes a long `user_message` field directly in
   `constructed_context` (the LLM's reasoning bleeds into the
   field, sometimes echoing the entire student snapshot or recent
   agent thread back into the user_message slot).

4. `dispatch.py:252` does
   `payload.setdefault("user_message", ctx.user_message)`. Because
   `user_message` is *already* in the LLM-built payload, the
   `setdefault` is a no-op; the over-long supervisor-built
   user_message survives.

5. `CareerCoachInput.user_message` carries `Field(max_length=4000)`.
   Validation rejects with
   `String should have at most 4000 characters`.

6. `dispatch_single` logs `agentic.error` and returns a fallback;
   no `agent_actions` row is written for `career_coach`.

7. The orchestrator wrote the supervisor's row earlier (during
   `_supervisor.execute()`); that row is the most recent for the
   user. Supervisor's row has `cost_inr=0.0` because
   `supervisor.run()` does not call `self._track_llm_usage(ctx, response)`
   (see `app/agents/supervisor.py:199-204` — LLM call, no usage
   tracking).

8. The test's `LIMIT 1 ORDER BY created_at DESC` query lands on
   the supervisor row, sees `cost_inr=0.0`, and the BUG-CP1F
   regression-guard assertion fails:
   `BUG-CP1F regression on agent='supervisor': cost_inr=0.0`.

## Why this is real product debt, not just test flake

Even if the test were rewritten to scope to `agent_name='career_coach'`,
the underlying behaviour stands:

- **Supervisor occasionally emits prompts that overrun specialist
  input caps.** This is a real failure mode in production — a
  student request is silently routed nowhere; the orchestrator's
  fallback path serves them a "couldn't be processed" message.
- **Supervisor's own row has `cost_inr=0`** because `supervisor.run`
  does not call `_track_llm_usage`. The supervisor *does* spend
  real LLM cost (Sonnet call); it's just not attributed. This is
  the same shape as BUG-CP1F (consumer-convention drift on
  `_track_llm_usage`), just on the supervisor itself.

Both are launch-readiness items even if no test caught them.

## Remediation candidates

### Option A — Tighten supervisor prompt (smallest blast radius)

Edit `app/agents/prompts/supervisor.md` to make the
"don't mix reasoning into `constructed_context`" rule load-bearing
with an explicit length cap and a worked example. Add a final-pass
self-check instruction: "Before emitting JSON, verify each string
field in `constructed_context` is < 1000 characters; if longer,
truncate to a tight summary."

- Cost: ~₹2 (one prompt edit + 5-10 isolation re-runs to verify
  flake rate dropped).
- Risk: prompt edits are non-deterministic — flake rate may
  improve from 50% to 5% but not to 0%.

### Option B — Truncate at the boundary (defense in depth)

In `app/agents/dispatch.py:dispatch_single`, after the
`payload.setdefault("user_message", ...)` line, clip
`payload["user_message"]` to ≤3500 chars (4000 with safety margin).
Log a warning if truncation fires so we can spot supervisor
over-length emissions.

- Cost: ~₹0 (code change + unit test).
- Risk: truncation may drop semantically important content the
  supervisor put there. Mitigated by logging so we can monitor;
  combined with Option A this is robust.

### Option C — Fix the supervisor's `_track_llm_usage` gap (orthogonal but related)

`Supervisor.run` at `app/agents/supervisor.py:199-204` calls
`llm.ainvoke` without `self._track_llm_usage(ctx, response)`. Add
the call. This doesn't fix the flake (the test would still find
the supervisor row) but it does fix the cost-attribution gap so
the supervisor row would have `cost_inr > 0` and the assertion
would pass even when career_coach is rejected.

- Cost: ~₹0 (one-line edit + isolation re-run).
- Risk: this is the BUG-CP1F-shape pattern — instrumenting an
  agent path that was missed during the original sweep. The
  D18 BUG-CP1F closure noted 4 v2 agents needed the fix; the
  supervisor was apparently a 5th miss. Worth a sweep across all
  agentic-base subclasses to confirm there are no other holes.

## Recommended order

A + B + C together = full fix. C is the most independently valuable
(real cost-attribution gap pre-launch); A is the most non-deterministic
(prompt tuning); B is the cheapest insurance.

Recommended sequence: **C first** (one-line fix, surfaces the rest
of any audit gap), **then B** (defense in depth), **then A** if the
flake hasn't fully resolved after C+B. Combined cost ~₹2-4.

## Cross-references

- `docs/architecture/d18-phase-b-test-coverage-overview.md` — Phase B
  closure mentions batch flakiness; this doc updates the
  characterisation.
- `app/agents/supervisor.py` — `_track_llm_usage` gap.
- `app/agents/prompts/supervisor.md` — line 116 "don't mix reasoning"
  is the load-bearing instruction the LLM occasionally violates.
- `app/agents/dispatch.py` — line 252 `setdefault` is the boundary
  where Option B truncation lands.
- `app/schemas/agents/career_coach.py` (or equivalent) — the
  `max_length=4000` validator that rejects over-length input.
