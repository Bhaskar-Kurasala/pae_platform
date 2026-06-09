# `log_event` observability sink — D17 dashboard prerequisite

**Status:** Open — D17 cleanup territory. Not a bug; an architecture gap
for D17 dashboards that aggregate agent-emitted events.
**Created:** 2026-05-06 (D12 CP3 Part F.5).
**Cross-references:**
[backend/app/agents/tools/universal/log_event.py](../../backend/app/agents/tools/universal/log_event.py)
(the tool — currently structlog-only),
[agent-tool-call-discipline.md](./agent-tool-call-discipline.md)
(sibling pattern doc — broad-except hides the gap),
[llm-cost-tracking-silent-zero.md](./llm-cost-tracking-silent-zero.md)
(the related cost-tracking observability gap, fixed for tailored_resume in D12 CP3 Part C).

## What this is

`log_event` is the audited @tool that agents call when they want to
surface a structured event the auto-logged `agent_actions` row doesn't
already cover — a mode inference, a breakthrough, an unusual student
state. Per Pass 3d §D.4, the tool's spec'd implementation is "wraps
structlog + PostHog." The current implementation is structlog-only.

```python
# log_event.py:106-116 — current sink
async def log_event(args: LogEventInput) -> LogEventOutput:
    method = getattr(log, args.severity, log.info)
    method(args.event_name, **args.properties)
    return LogEventOutput(logged=True)
```

The events emit cleanly to structured stdout where the operational
logging pipeline picks them up. They are NOT in any queryable sink:

- No DB table (no `events` table — naming overlap with the `agent_actions`
  audit trail, but agent_actions is auto-emitted per execution, not the
  same surface as log_event)
- No PostHog (deferred per the source comment)
- No log aggregation (Loki / Datadog / ELK not provisioned in dev or prod)

## Why this surfaces now

D12 added `study_planner.mode_inferred` as the first non-trivial use of
`log_event`. The original D12 CP3 verification plan said "check the
events row" to confirm mode inference fires under real MiniMax. There IS
no events row to check — the event lives only in the structlog stdout
stream of whatever container handled the request.

This is fine for verification (check container logs after the request);
it's not fine for D17 dashboards that aggregate "how often is mode
inferred vs. supplied across all students this week?" That query needs
a queryable sink.

## D17 decision required

When dashboards become a deliverable, pick one:

1. **Log aggregation (Loki, Datadog, ELK)**: keep `log_event` as
   structlog-only and rely on infra-level aggregation. Lowest code
   change; requires infra provisioning. Best when other observability
   needs (request traces, error rates) also live there.
2. **DB sink (events table)**: create `events` table with columns
   matching `LogEventInput` (event_name, properties JSONB, severity,
   user_id, agent_name, created_at). Add the write inside `log_event`
   alongside the structlog emit. Queryable from SQL alongside
   `agent_actions`; doesn't depend on log infra. Higher write volume
   on the primary DB.
3. **Hybrid**: structlog + a partitioned/TTL'd events table. Best of
   both; most code change.

Recommended default: option 2 if D17 ships before log aggregation;
option 1 if log aggregation lands first.

## D12 CP3 verification accommodation

Until the sink is wired, real-LLM verification of `log_event`-emitting
paths reads container stdout after the test request. Acceptable for
one-off verification; not viable for production dashboards. The CP3 Part
A.2 verification protocol uses this approach.

## Cross-references

- [backend/app/agents/tools/universal/log_event.py](../../backend/app/agents/tools/universal/log_event.py) — the tool
- [Pass 3d §D.4](../architecture/pass-3d-tool-system.md) — the spec'd
  "wraps structlog + PostHog" intent
- [agent-tool-call-discipline.md](./agent-tool-call-discipline.md) —
  Pattern 1 (broad-except) compounds with this gap: a swallowed
  ValidationError on `log_event` is silent BOTH because of the broad
  except AND because there's no sink to notice the absence in.
