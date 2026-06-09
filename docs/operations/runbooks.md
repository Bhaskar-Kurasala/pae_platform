# Operations runbooks

Scaffolded D19.1 CP4. Bodies populate at D19.4 (on-call substrate)
when the alerting pipeline is wired and on-call shapes the procedural
detail per real incident shape.

Until then: each section below is a placeholder pointing at the
dashboard panel(s) an on-call engineer should look at first, plus
the structlog event names + correlation IDs to grep for if the
panel doesn't tell the full story.

---

## api-health

**Dashboard:** [api-health.json](dashboards/api-health.json) — request rate, error rate, latency percentiles by endpoint.

**First look:** the `error-rate-by-endpoint` panel — which endpoint is breaking, and is the rate climbing?

**Correlate to logs:** every 5xx response logs `unhandled_exception` (see `app/core/exception_handler.py`) with `request_id` + `trace_id` from CP1. Grep structlog for `"event": "unhandled_exception"` filtered by the affected endpoint.

**Correlate to traces:** the offending request's full call graph is in the trace span tagged with the matching `trace_id`. CP3 auto-instruments FastAPI/SQLAlchemy/Redis/httpx so the span tree includes downstream calls without manual instrumentation.

**Body to author at D19.4:** classification table (5xx vs 4xx-misdirected, transient vs persistent), escalation path (when to wake founder), restoration patterns (rollback vs hotfix), post-incident review template.

---

## agent-health

**Dashboard:** [agent-health.json](dashboards/agent-health.json) — per-agent invocations, error rate, latency percentiles, top-10 slowest, eval score, inter-agent depth.

**First look:** the `error-rate-by-agent` panel. Which specialist is failing? Cross-reference the `top-10-slowest-agents` panel — is it slow + erroring (specialist regression), or fast + erroring (contract failure)?

**Correlate to logs:** `agent.run.error` events carry `agent_id` (CP1.2c contextvar) + `trace_id`. Grep `"event": "agent.run.error"` filtered by `agent_id`.

**Correlate to traces:** every agent invocation is wrapped in `agent.<name>` span (CP3). Span attributes: `agent.tokens_in/out`, `agent.cost_inr`, `agent.outcome`. Anomalous tokens / cost = upstream LLM regression; anomalous outcome = specialist contract drift.

**Body to author at D19.4:** specialist-by-specialist incident playbooks (career_coach prompt drift, supervisor JSON malformation, etc.); links to BUG-CP1F + cp3-traceability-supervisor-flake.md mechanism; rollback procedure for prompt updates.

---

## cost

**Dashboard:** [cost.json](dashboards/cost.json) — cost-rate by agent, cumulative today/week/month, top burners.

**First look:** the `cumulative-cost-today` panel against the cohort-1 daily ceiling (₹50/student/day per Pass 3f §D.1). Approaching ceiling = burst-rate investigation; over ceiling = enforcement gate is broken.

**Correlate to logs:** `llm.call` events (`app/agents/base_agent.py:log_action`) carry `cost_estimate_inr` + `agent_name` + `tokens_in/out`. Per-user attribution is via the `user_id` contextvar from CP1.2a.

**Correlate to traces:** `agent.<name>` spans carry `agent.cost_inr` + `agent.tokens_total` (CP3). Tail-sample any trace where `agent.cost_inr > 1.0` (D19.1 CP3 D-E rule, deferred to CP5 collector).

**Body to author at D19.4:** budget burn-rate alerting thresholds (D19.2); per-cohort attribution methodology when cohort_id schema lands (see `docs/followups/cohort-membership-modeling.md` if registered); founder escalation path.

---

## db-health

**Dashboard:** [db-health.json](dashboards/db-health.json) — pool gauge, query rate by type, p95 query latency, slow-query count.

**First look:** `pool-connections-in-use` against `db_pool_size + db_max_overflow` (settings: 10 + 20 = 30 max). >25 sustained = saturation imminent.

**Correlate to logs:** `slow_query` warnings (>500ms threshold; see `app/core/database.py:_attach_slow_query_logger`) carry the SQL preview + parameters. Grep `"event": "slow_query"` for the offending statement.

**Correlate to traces:** SQLAlchemy auto-instrumentation (CP3) creates a span per query with the SQL text. Pool exhaustion shows as queue waits in the span timing.

**Body to author at D19.4:** index audit checklist; managed-DB failover procedure (Neon → standby); migration runbook including rollback.

---

## auth-events

**Dashboard:** [auth-events.json](dashboards/auth-events.json) — signup, login, login-failure rates + signup-conflict rate.

**First look:** `login-failure-rate` divided by `login-rate`. Persistent ratio >5% = brute-force probe or password-rotation event; investigate before alerting.

**Correlate to logs:** `auth.login`, `auth.register`, `auth.refresh`, `auth.signup_grace_failed`, `auth.cohort_event_failed` events. All carry `user_id` (CP1.2a).

**Correlate to traces:** auth events are short-span (single request); the FastAPI auto-instrumentation span carries the route + status_code. No per-event manual span needed at CP3 scope.

**Body to author at D19.4:** brute-force response procedure (rate-limit tightening, IP block, founder notification); the `auth.signup_grace_failed` SQL bug (separate from D19.x; surfaced during CP3 verification — see backend logs around 2026-05-09 06:56:13 UTC); cohort-event recovery procedure.

---

## operational

**Dashboard:** [operational.json](dashboards/operational.json) — Celery task rate / success / error / retry by name, memory recall + write rates, tool-call latency.

**First look:** `celery-error-rate` and `celery-retry-rate` per task. A spike in retry without error spike = transient downstream (Redis / LLM); spike in both = real failure.

**Correlate to logs:** Celery task lifecycle events (`task.start`, `task.complete`) carry `task_name` + `trace_id` (propagated from upstream request via CP1.3 + CP3 CeleryInstrumentor). Per-task structlog conventions land at D19.4.

**Correlate to traces:** `CeleryInstrumentor` (CP3) creates a span per task; combined with CP1's `CorrelatedTask.apply_async` header injection, the broker round-trip preserves the full trace.

**Body to author at D19.4:** queue-saturation runbook (worker scaling, task throttling); broker (Redis) failover; beat-schedule recovery after worker restart (the beat schedule is in-memory; restart reload is automatic but worth pinning).

---

## How runbooks evolve

D19.4 (on-call substrate) populates the bodies based on:

- D19.2 alert thresholds — each alert needs a runbook entry on what to do.
- D19.5 pre-launch verification incidents — every incident shapes the runbook.
- Real cohort-1 launch incidents — the highest-value source.

The discipline: every alert has a runbook entry; no orphan alerts.
Every dashboard panel above has a runbook section; no orphan panels.
Owners (per dashboard) are responsible for keeping their runbook
section current.
