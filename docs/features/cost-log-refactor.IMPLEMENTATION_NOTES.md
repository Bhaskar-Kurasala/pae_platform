# Cost Log Refactor — Implementation Notes

**Date shipped:** 2026-04-25 (commit 0 of the readiness-diagnostic build)
**Migration:** `0040_agent_invocation_log`
**Companion specs:** the readiness diagnostic and JD decoder both write to
this table from day one.

---

## What was built

A unified `agent_invocation_log` table replaces the per-agent ad-hoc cost
tables (`mock_cost_log`, the cost columns on `generation_logs`). The
refactor was sequenced ahead of the diagnostic + JD decoder build because
those two agents would be the third and fourth instances of per-agent cost
columns — abstraction is justified at the third user, not the second.

* **One row per LLM call.** Grain matches `mock_cost_log` already; the
  resume agent's coarser one-row-per-generation is preserved in the
  backfill via the synthetic `sub_agent='tailoring_agent'` label, with
  per-sub-agent observability beginning the day this migration deploys.
* **Cost-only.** Lifecycle events (`started`, `quota_blocked`,
  `downloaded`) stay on `generation_logs`. The new table's `status` field
  carries cost-bearing outcomes only: `succeeded`, `failed`, `cap_exceeded`.
* **Dual-write window.** Resume and mock services write to BOTH legacy and
  new tables. Read paths still use the legacy tables, gated by a durable
  parallel-read counter that flips after 100 consecutive matching reads.

---

## Dual-write window

**Sunset target: 2026-05-09** (~2 weeks after deploy).

> **Calendar vs. correctness — important.** The 2026-05-09 sunset target
> is a calendar *aspiration*, not the flip condition. The actual flip
> condition is `consecutive_agreements >= 100`. If May 9 arrives without
> 100 agreements (e.g., due to low resume-generation traffic in dev or
> staging environments), **extend the dual-write window**. Never flip
> the read path without the threshold being met. Correctness first,
> calendar second.

The follow-up migration that fires on or after that date will:

1. Drop the `cost_inr`, `input_tokens`, `output_tokens`, `latency_ms`,
   `model`, `validation_passed`, `error_message` columns from
   `generation_logs` (the table itself stays — it still owns lifecycle
   events).
2. Drop the `mock_cost_log` table entirely.
3. Remove the dual-write branches in `tailored_resume_service._log_event`
   and `mock_interview_service._log_cost`.
4. Remove the parallel-read gate in `quota_service`; flip the read path
   to `agent_invocation_log` unconditionally.

If the parallel-read gate has not flipped by the sunset date, **do not
ship the cleanup migration.** Investigate divergences first via
`migration_gates.last_divergence_payload`.

### Parallel-read gate operational definition

* **Counter location:** `migration_gates` table, row
  `name='agent_invocation_log_quota_parity'`. Durable across deploys.
* **Increment trigger:** every call to `quota_service._count_events`
  runs both queries and records a parity check.
* **Flip condition:** `consecutive_agreements >= 100` AND legacy/new
  results match for that 100th check.
* **Reset condition:** any divergence resets `consecutive_agreements`
  to 0; the diverging payload is persisted on
  `migration_gates.last_divergence_payload` for audit.
* **Divergence handling policy:** structured warning logged via
  structlog (`agent_invocation_logger.parity_divergence`); the request
  continues with the legacy result. Divergences never raise.

The 100-check threshold is per-environment, not per-user. In production
this fires on every quota-check the resume agent makes; expected fill
time is hours-to-days depending on traffic. The gate is intentionally
durable so production traffic counts toward the threshold across deploys.

---

## Historical backfill caveat

`generation_logs` did not record per-sub-agent breakdowns; one row per
generation captured the entire pipeline (jd parser, tailoring agent,
validator) collapsed. The backfill writes those rows with the synthetic
label `sub_agent='tailoring_agent'`.

> **For analysts: any chart faceted by `sub_agent` for
> `source='resume_generation'` should filter to `created_at >= 2026-04-25`
> to avoid mixing pre-refactor catch-all rows with the per-sub-agent rows
> written from migration date forward.**

`mock_cost_log` already stored per-sub-agent rows, so its backfill is
faithful — `sub_agent` reflects the actual sub-agent that fired (one of
`question_selector`, `interviewer`, `scorer`, `analyst`).

---

## Quota semantics — preserved

`quota_service.CONSUMING_EVENTS = ("completed", "failed")` is preserved
verbatim on the legacy path. The new path counts
`status IN ('succeeded', 'failed')` — the `QUOTA_CONSUMING_STATUSES`
constant on `app.models.agent_invocation_log`. Both `failed` cases
**count toward quota by deliberate design**: a failed generation still
spent LLM tokens before failing, and still consumed the user's slot.
Counting it prevents a retry loop from being free.

A regression test (`test_failed_counts_toward_quota`) pins this
behavior on both paths. If a future contributor "fixes" either rule
to count successes only, the test fails immediately.

---

## Tracking issues

### Anti-sycophancy CI gate promotion (readiness diagnostic)

**Currently:** anti-sycophancy evaluator runs as warning + structured log
on every verdict.

**Promotion to CI-blocking criteria:** false-positive rate **<5%** on a
held-out set of 20 verdicts manually labeled as "honest." Calibrate
against the first ~50 real verdicts before flipping to blocking.

**Owner:** TBD. **Tracking:** open an issue once the diagnostic ships and
verdicts start landing.

### Cost-log dual-write sunset

**Target:** 2026-05-09 (calendar aspiration). **Owner:** TBD.
**Pre-flight (the actual gate):**
`migration_gates.flipped = true` for `agent_invocation_log_quota_parity`.
If the gate has not flipped by the calendar target, extend the window.

### Resume-agent cap_exceeded → failed asymmetry

**Description.** The resume agent's `CostCapExceededError` handler emits
`event="failed"` to `_log_event`, which dual-writes to
`agent_invocation_log` as `status='failed'`. The mock interview agent and
the new readiness diagnostic write `status='cap_exceeded'` directly when
their circuit breakers fire. Result: cost-cap fires for the resume agent
appear under `status='failed'` while every other agent's cap fires appear
under `status='cap_exceeded'`.

**Why we accepted it.** Preserving today's legacy `event='failed'`
behavior on `generation_logs` was load-bearing for the dual-write window;
splitting the event would have either (a) broken legacy semantics or
(b) required a parallel `event='cap_exceeded'` value that the legacy
code paths and existing log-readers don't recognize. Either change is
out of scope for commit 0.

**Query patterns it affects.** Any cross-agent analytics that group by
`status` will undercount resume-generation cap fires:

```sql
-- This query UNDERCOUNTS cost-cap fires for resume_generation.
-- They land under status='failed' instead of status='cap_exceeded'.
SELECT source, COUNT(*)
FROM agent_invocation_log
WHERE status = 'cap_exceeded'
GROUP BY source;
```

To get a faithful cross-agent cap-fire count today, use:

```sql
SELECT
  source,
  CASE
    WHEN source = 'resume_generation' AND error_message ILIKE '%cost cap exceeded%' THEN 'cap_exceeded'
    ELSE status
  END AS effective_status,
  COUNT(*)
FROM agent_invocation_log
WHERE status IN ('failed', 'cap_exceeded')
GROUP BY source, effective_status;
```

**Owner:** TBD. **Target for resolution:** during the legacy-table
cleanup migration that fires after the dual-write sunset. At that point
the resume service can be updated to emit `event="cap_exceeded"` (or
the cap branch can call a new `_log_event(..., event="cap_exceeded")`
that maps to `STATUS_CAP_EXCEEDED` on the new path), with no remaining
legacy consumers to break.

---

## Files touched

### New

- `backend/app/models/agent_invocation_log.py`
- `backend/app/models/migration_gate.py`
- `backend/app/services/agent_invocation_logger.py`
- `backend/alembic/versions/0040_agent_invocation_log.py`
- `backend/tests/test_services/test_agent_invocation_log_dual_write.py`

### Edited

- `backend/app/models/__init__.py` — register new models
- `backend/app/services/mock_interview_service.py` — `_log_cost` dual-write
- `backend/app/services/tailored_resume_service.py` — `_log_event` dual-write
- `backend/app/services/quota_service.py` — parallel-read gate

---

## Deviations from the original plan

None for this commit. The user's two pre-flight concerns
(durable counter location; failure-path coverage) were addressed in-line
during commit 0:

* Counter is durable in Postgres via `migration_gates`, not Redis or
  in-memory.
* Failure paths share the single `_log_event` entry point; the
  `_EVENT_TO_STATUS` map ensures each cost-bearing event (`completed`,
  `failed`) dual-writes to `agent_invocation_log` while the lifecycle
  events (`started`, `quota_blocked`, `downloaded`) skip it. Both
  failure paths in `tailored_resume_service.generate_tailored_resume`
  (CostCapExceededError handler at line 368, generic exception handler
  at line 380) currently emit `event="failed"` — preserving today's
  legacy behavior — and so dual-write fires correctly on both. A future
  refinement could route the cost-cap path to `event="cap_exceeded"` to
  unlock distinct status reporting on the new table; not required now.
