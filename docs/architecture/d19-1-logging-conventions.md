# D19.1 — Logging conventions

Canonical reference for structured logging on the platform. Encodes the
existing convention as it was at D18 closure (eaef010) plus the
correlation-ID and sampling rules introduced in D19.1 CP1.

## Substrate

`structlog` configured in `app/core/logging.py`. JSON output to stdout;
no file sinks. Every log line is a single JSON object on a single line —
parseable by any backend (CloudWatch, Loki, Datadog) that accepts
JSON-on-stdout. Backend choice is deferred to D19.1 CP5.

`logging.basicConfig` bridges stdlib `logging.getLogger()` calls into
the same level so third-party libraries flow through the same output
path. We never call `print()`; the no-print rule predates D19.1 and is
encoded in `CLAUDE.md`.

## Correlation IDs (D19.1 D-B contract)

Every log line emitted during a request lifetime carries the
correlation IDs bound to structlog contextvars by middleware / deps /
agent harness. The IDs are:

| Key            | Bound by                                              | Required when                                 |
|----------------|-------------------------------------------------------|-----------------------------------------------|
| `request_id`   | `RequestIDMiddleware`                                 | Every HTTP request                            |
| `trace_id`     | `RequestIDMiddleware` (W3C 32-hex form)               | Every HTTP request; every Celery task        |
| `user_id`      | `get_current_user` / `get_current_user_optional`      | Authenticated requests                        |
| `agent_id`     | `BaseAgent.run`                                       | During an agent invocation                    |
| `session_id`   | (Reserved; not yet wired — CP1 placeholder.)          | Future: when session resolution lands         |
| `cohort_id`    | (Reserved; user.cohort_id schema does not exist.)     | Future: when cohort membership is modelled    |

**Single-source-of-truth identity.** `trace_id` is derived from the
same UUID4 bytes that produce `request_id` (`uuid4().hex` is a
W3C-compliant 32-hex). The two strings reference the same underlying
identity in different formats; logs grep'd by either land on the
same request.

**W3C `traceparent` defensive read.** If an upstream caller supplies
a well-formed `traceparent` header we adopt the trace-id portion. Full
W3C propagation (parent-id, sampled flag, outbound) is CP3 scope.

**Celery propagation.** `CorrelatedTask` (in `app/core/celery_logging.py`)
auto-injects the contextvars into `apply_async` headers at enqueue,
and `task_prerun` / `task_postrun` signal handlers restore / clear
them in the worker. Both `.delay()` and `.apply_async()` ride this
path — call sites do not need to pass headers.

**Beat-scheduled / CLI-invoked tasks** have no upstream request to
correlate to. The prerun signal mints a fresh `trace_id` for these
and tags `trace_origin="task"` so a log query can distinguish
"task that was queued by a request" from "task that started itself".

## Per-component log levels

The platform's existing convention, encoded here as canonical.

### `auth`

- INFO: state changes (login success, signup, password rotation, refresh-token grant).
- WARNING: failed auth attempts that aren't outright invalid (e.g. expired refresh token).
- ERROR: programming errors in the auth path (DB unreachable, JWT signing failure).
- DEBUG: token validation steps, claims inspection.

### `agent`

- INFO: `agent.run.start` and `agent.run.complete` per invocation; `llm.call` per LLM round-trip.
- WARNING: degraded paths (rate limit hit, schema-truncate fallback fired).
- ERROR: `agent.run.error` — wrapped by `BaseAgent.run` `except` block.
- DEBUG: tool-call dispatch, prompt template selection.

### `db`

- INFO: connection pool resize, slow-query log threshold breach.
- WARNING: query > 500ms (existing `slow_query_log` middleware contract).
- ERROR: connection failures, transaction rollbacks not initiated by the app.
- DEBUG: per-query SQL (off in prod by default).

### `api`

- INFO: rate-limit denials (slowapi `_rate_limit_handler` keeps these at INFO so on-call sees the rate).
- WARNING: 4xx responses other than 429 / 401 / 404 (mapped to WARN by `unhandled_exception_handler`).
- ERROR: 5xx responses, unhandled exceptions.
- DEBUG: per-route entry/exit (off in prod by default).

### `celery`

- INFO: `task.start` / `task.complete` (the prerun/postrun signals also log a structured event).
- WARNING: retries, soft timeouts.
- ERROR: hard failures, `worker.safety_gate_load_failed`, beat schedule misalignment.
- DEBUG: queue resolution, header inspection.

### `telemetry` / `sentry`

- INFO: enable / disable on boot.
- WARNING: SDK init or send failures (these are non-fatal — telemetry is never load-bearing).
- ERROR: never emitted from these modules; failures are downgraded to WARN by design.

## Sampling (D-E contract)

Implemented in `app/core/log_sampling.py`, wired into the structlog
processor chain after `merge_contextvars`.

| Level    | Default rate | Tunable via env                |
|----------|--------------|--------------------------------|
| ERROR    | 100%         | (not tunable — always shipped) |
| WARNING  | 100%         | (not tunable — always shipped) |
| INFO     | 100%         | `LOG_SAMPLE_INFO_RATE`         |
| DEBUG    | 1%           | `LOG_SAMPLE_DEBUG_RATE`        |

**Determinism.** When `trace_id` is present in the event dict (which
it is for any log line emitted during a request or a Celery task),
the retention decision is `hash(trace_id) < rate`. A given trace's
INFO logs are therefore *all* retained or *all* discarded — we never
ship half a request's logs to the backend, which would defeat
correlation.

**Pre-request lines** (boot, scheduler init) have no trace_id; we
fall back to per-call `random.random() < rate`. Loss of correlation
is acceptable because there is nothing to correlate to.

**Production tuning.** The defaults are conservative for cohort-1
launch (INFO retained at 100% so on-call has full signal). When INFO
volume justifies it, lower `LOG_SAMPLE_INFO_RATE` to `0.10` (the D-E
target). DEBUG defaults to 1% because DEBUG should be off in
production anyway via the `level=` argument to `configure_logging`.

## How to add a new log line

1. Use `log = structlog.get_logger()` at module top.
2. Use snake-dot event names: `agent.run.start`, `auth.login.failed`,
   `celery.task.timeout`. The dotted prefix is the component name from
   the per-component table above.
3. Pass structured kwargs, never f-strings: `log.info("auth.login.success", user_id=str(user.id))`.
4. Don't pass user-input strings as the *event name* (the first
   positional arg) — that's a cardinality fire and breaks downstream
   aggregations.
5. Don't include PII fields (email, full name, prompt content,
   response content). The Sentry breadcrumb bridge ships every log
   line as a breadcrumb; what you log here can land in the Sentry
   vault. The substrate-level redaction in `app/core/sentry.py`
   catches some shapes but it is a backstop, not the primary
   defence — discipline at the call site is load-bearing.

## Auditing PII at the structlog layer

The structlog → Sentry bridge means any field bound to contextvars
or passed as a log kwarg can flow into the Sentry vault. The vault's
`_REDACT_USER_KEYS` allowlist (`email`, `username`, `ip_address`,
`full_name`) catches Sentry's *user dict* but not arbitrary structured
event fields. CP1 audit: `set_user_context` is only ever called with
`user_id` (not email / name); Sentry's user dict is therefore minimal
and the redaction surface is correct as-is. CP1 binds `user_id` and
`agent_id` (both safe, by design ID-only) to contextvars — no
expansion of the redaction surface needed.

If a future binder adds `cohort_id`, no Sentry change is needed —
Sentry's `set_user_context` is not the propagation path; structlog
contextvars are. The Sentry breadcrumb stream picks structured
kwargs from log calls, where ID-only is the convention.

## See also

- `app/core/logging.py` — processor chain
- `app/core/request_id.py` — request_id / trace_id middleware
- `app/core/celery_logging.py` — Celery auto-propagation
- `app/core/log_sampling.py` — sampling processor
- `app/core/sentry.py` — PII redaction in the Sentry bridge
- `app/agents/base_agent.py` — `BaseAgent.run` agent_id binding
