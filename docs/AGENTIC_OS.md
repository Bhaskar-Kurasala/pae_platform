# Agentic OS — architecture as built (D1–D8 + Track 2)

**Audience.** A future contributor — month 6, month 18, never met the
people who built this — who needs to add a new agent, debug an
existing one, or make a schema change. If you are that person and
something in this document is unclear, the document is wrong; open
an issue and edit it. Every counterintuitive decision in here has
its rationale (the *why*), not just its rule (the *what*) —
because rules without rationale rot the moment a "this seems
unnecessary" instinct fires on someone who doesn't know what
the original failure mode looked like.

**Status.** This document covers the agentic OS foundation as of
deliverable D8 plus Track 2. Forward-looking design (a supervisor
agent, agent-migration playbook, GraphRAG, entitlement enforcement,
safety beyond the critic, scale + observability, the naming sweep,
the implementation roadmap) lives in separate Pass 3b–3l design
documents. **Section 9** below names each explicitly so you know
where the boundary of this file ends.

**Source-of-truth file map.**

| Concept | File |
|---|---|
| Schema | `backend/alembic/versions/0054_agentic_os_primitives.py` |
| ORM | `backend/app/models/agent_*.py`, `backend/app/models/student_inbox.py` |
| Memory primitive | `backend/app/agents/primitives/memory.py` |
| Embeddings (Voyage + hash fallback) | `backend/app/agents/primitives/embeddings.py` |
| Tools registry + executor + 11 stubs | `backend/app/agents/primitives/tools.py`, `backend/app/agents/tools/` |
| Inter-agent communication | `backend/app/agents/primitives/communication.py` |
| Critic + retry + EscalationLimiter | `backend/app/agents/primitives/evaluation.py` |
| Proactive triggers (cron + webhook) | `backend/app/agents/primitives/proactive.py` |
| Metrics shim | `backend/app/agents/primitives/metrics.py` |
| Public surface | `backend/app/agents/primitives/__init__.py` |
| Agent base class | `backend/app/agents/agentic_base.py` |
| Boot-order loader | `backend/app/agents/_agentic_loader.py` |
| Celery task body | `backend/app/tasks/proactive_runner.py` |
| Webhook routes | `backend/app/api/v1/routes/agentic_webhooks.py` |
| Reference agent | `backend/app/agents/example_learning_coach.py` |

---

## 1. Overview

The agentic OS is a five-primitive substrate that lets an agent
(an `AgenticBaseAgent` subclass) be **stateful across
invocations**, **call tools and other agents**, **evaluate its own
output**, and **fire from cron + webhook** — without each agent
re-implementing those concerns.

The five primitives, in dependency order:

1. **Memory** (`MemoryStore`) — persistent long-term memory backed
   by Postgres + pgvector. Hybrid recall: structured (key
   substring) + semantic (cosine over `embedding`) + dedupe. Per-row
   `valence`, `confidence`, `expires_at`, plus a Celery-callable
   `decay()` sweep that lowers confidence on idle rows and prunes
   below threshold.
2. **Tools** (`ToolRegistry`, `@tool`, `ToolExecutor`) — typed
   registered functions with pydantic input/output schemas, audit
   row per call (`agent_tool_calls`), retry-on-transient,
   permanent-exception bucket, permission gating via
   `requires=("read:student",)`-style declarations.
3. **Inter-agent communication** (`call_agent`, `CallChain`) —
   one agent invokes another with the chain threaded through.
   `agent_call_chain` audit row per hop. Edge-based cycle
   detection. Depth ceiling. Fail-fast timeout.
4. **Evaluation** (`Critic`, `evaluate_with_retry`,
   `EscalationLimiter`/`RedisEscalationLimiter`) — LLM-as-judge
   with strict JSON contract at temperature 0; retry with critic
   reasoning fed back; escalate after retry budget exhausts; per-
   agent rate limit on the admin notification flag.
5. **Proactive triggers** (`@proactive`, `@on_event`,
   `dispatch_proactive_run`, `route_webhook`) — cron-fired and
   webhook-fired entry points with end-to-end idempotency keys
   (the `agent_proactive_runs.idempotency_key` partial unique
   index does the dedup).

`AgenticBaseAgent` composes all five via their public surface.
Subclasses override one method (`run`) and inherit everything else;
each primitive has an opt-out class flag (`uses_memory`,
`uses_tools`, `uses_inter_agent`, `uses_self_eval`,
`uses_proactive`) so an agent that doesn't need a primitive doesn't
pay its cost.

**Relationship to the legacy `BaseAgent`.** The legacy
`app.agents.base_agent.BaseAgent` and its 26 registered subclasses
(`socratic_tutor`, `mock_interview`, etc.) are NOT touched by this
layer. They register through `app.agents.registry.AGENT_REGISTRY`;
agentic agents register through `app.agents.primitives.communication
._agentic_registry`. MOA dispatches to the legacy registry today.
Migration of legacy agents to `AgenticBaseAgent` is a separate
per-agent PR and is out of scope for this document — see Section 9
and the Pass 3c playbook when it lands.

---

## 2. Schema (migration 0054)

Seven tables, one enum, pgvector extension. Migration file:
[`backend/alembic/versions/0054_agentic_os_primitives.py`](../backend/alembic/versions/0054_agentic_os_primitives.py).

**`pgvector` extension** is created at the top of the migration
with `CREATE EXTENSION IF NOT EXISTS vector`. Dev runs against the
`pgvector/pgvector:pg16` image (pinned to digest in
`docker-compose.yml`); prod runs against Neon, where pgvector is
on every plan's allowlist. The migration role needs `CREATE` on
the database — see `docs/followups/neon-pgvector-verification.md`.

**`agent_memory_scope` enum** has three values: `user`, `agent`,
`global`. See Section 7's "postgresql.ENUM vs sa.Enum" decision
for why this is created via raw SQL not via SQLAlchemy's helper.

### `agent_memory`

Columns: `id`, `user_id` (FK users, nullable, SET NULL for global
scope), `agent_name`, `scope` (enum), `key`, `value` (jsonb),
`embedding` (`vector(1536)`), `valence` (real, -1..1), `confidence`
(real, 0..1), `source_message_id`, `created_at`, `last_used_at`,
`access_count`, `expires_at` (nullable).

Indexes:
- `agent_memory_user_scope_idx (user_id, scope)` — the structured
  recall hot path
- `agent_memory_agent_idx (agent_name)` — per-agent introspection
- `agent_memory_expires_idx (expires_at) WHERE expires_at IS NOT NULL`
  — partial; the nightly decay sweep
- `agent_memory_embedding_idx USING hnsw (embedding vector_cosine_ops)`
  — semantic recall

Why `vector(1536)`: locks future provider flexibility (OpenAI
text-embedding-3-small is 1536-native, Cohere v3 is 1024 → padded,
Voyage-3 is 1024 → padded) at the cost of ~50% more bytes per row.
Re-embedding everything later because we picked too small is
expensive; oversizing now is cheap. See the cross-model padding
caveat in `embeddings._pad_to_target_dim`'s docstring — mixing
native-1536 and padded-1024 embeddings in the same recall is
unsupported.

### `agent_tool_calls`

Columns: `id`, `agent_name`, `tool_name`, `args` (jsonb), `result`
(jsonb, nullable), `status` (CHECK in `ok|error|timeout`),
`error_message` (text, nullable — contrast `agent_call_chain`),
`duration_ms`, `user_id` (FK SET NULL), `call_chain_id` (loose;
not a FK), `created_at`.

Indexes: `(agent_name, created_at)`, `(user_id, created_at)`,
`(call_chain_id)`.

`call_chain_id` is the join key that ties tool calls to the
outermost `execute()` invocation that produced them. It's loose
(no FK) because tool calls can happen before the surrounding
chain row is fully written; FK ordering would force a transaction
shape we don't want.

### `agent_call_chain`

Columns: `id`, `root_id`, `parent_id`, `caller_agent` (nullable —
NULL when the link is a root call from MOA / chat), `callee_agent`,
`depth` (int, CHECK >= 0), `payload` (jsonb), `result` (jsonb —
this also carries `{"error": "..."}` on failures; see Section 7
"error_message smuggled in result"), `status` (CHECK in
`ok|error|cycle|depth_exceeded`), `user_id` (FK SET NULL),
`duration_ms`, `created_at`.

Indexes: `(root_id, depth)`, `(callee_agent, created_at)`.

`root_id` is set on every chain row, including depth-0 calls. See
Section 5 (trace semantics).

### `agent_evaluations`

Columns: `id`, `agent_name`, `user_id`, `call_chain_id`,
`attempt_number` (int, CHECK >= 1), `accuracy_score`,
`helpful_score`, `complete_score` (all real, nullable — null means
"dimension didn't apply"), `total_score` (real, CHECK 0..1),
`threshold` (real), `passed` (bool), `critic_reasoning` (text),
`created_at`.

Index: `(agent_name, created_at)` — the prompt-quality dashboard
hot path.

Every attempt writes one row, including failed ones. The dashboard
query convention always includes a time window — see Section 6
convention #8.

### `agent_escalations`

Columns: `id`, `agent_name`, `user_id`, `call_chain_id`, `reason`
(text), `best_attempt` (jsonb — the highest-scoring of the failed
attempts is preserved here for admin review), `notified_admin`
(bool — gated by `EscalationLimiter`), `created_at`.

Index: `(agent_name, created_at)`.

The row is unconditionally written when the retry budget exhausts.
The `notified_admin` flag is what's rate-limited, not the row
itself — admins always have the audit trail.

### `agent_proactive_runs`

Columns: `id`, `agent_name`, `trigger_source` (text — `cron` |
`webhook:github` | `webhook:stripe` | `webhook:custom`),
`trigger_key` (text — the cron expression or event name),
`user_id` (FK SET NULL), `payload` (jsonb), `status` (CHECK in
`queued|ok|error|skipped`), `error_message` (text, nullable),
`duration_ms`, `idempotency_key` (text, nullable), `created_at`.

Indexes: `(user_id, created_at)`, `(idempotency_key) UNIQUE WHERE
idempotency_key IS NOT NULL`.

The partial unique index on `idempotency_key` is the load-bearing
piece. See Section 3's "proactive" subsection for the dedup
contract.

### `student_inbox`

Columns: `id`, `user_id` (FK CASCADE), `agent_name`, `kind` (text
— `nudge | celebration | job_brief | review_due | insight | ...`),
`title`, `body`, `cta_label`, `cta_url`, `read_at`, `dismissed_at`,
`expires_at`, `metadata` (jsonb, default `{}`), `idempotency_key`
(nullable), `created_at`.

Indexes: `(user_id, read_at, created_at)`, `(user_id,
idempotency_key) UNIQUE WHERE idempotency_key IS NOT NULL`.

The partial unique index on `(user_id, idempotency_key)` lets an
agent post the same card twice (e.g., a Celery retry) and have
the second attempt collapse into a no-op via
`ON CONFLICT DO NOTHING`. The `metadata` column is named
`metadata_` in Python because SQLAlchemy reserves `metadata` on
`DeclarativeBase`.

---

## 3. The 5 primitives

### 3.1 Memory — `MemoryStore`

**Public API.**

```python
store = MemoryStore(session)
await store.write(MemoryWrite(user_id=..., agent_name=..., scope="user",
                              key="...", value={...}))
rows = await store.recall(query, *, user_id=..., agent_name=..., scope="user",
                          k=5, mode="hybrid", min_similarity=0.35)
removed = await store.forget(memory_id)
counts = await store.decay(idle_window_days=14, ...)  # Celery sweep
```

**What it does.**

- `write` upserts on `(user_id, agent_name, scope, key)`. Re-writing
  the same key updates `value`, refreshes `last_used_at`, increments
  `access_count`. Embedding is computed lazily if not supplied.
- `recall` runs three modes: `semantic` (cosine over the embedding
  column with a threshold floor), `structured` (substring match on
  `key`), `hybrid` (default — both, dedup by id, semantic results
  sort first). Recalled rows have `access_count` incremented and
  `last_used_at` refreshed in a single UPDATE so the decay job
  treats them as "actively used."
- `forget` deletes one row by id.
- `decay` (Celery-callable) lowers `confidence` on rows whose
  `last_used_at` is older than the idle window, then deletes
  anything below `delete_below`. Also drops `expires_at`-passed
  rows. Commits its own transaction.

**What it does NOT do.**

- It does not write embeddings for failed ones — if Voyage 4xxs
  AND the hash fallback raises, the row is written with
  `embedding=NULL` and a warning log. Semantic recall skips
  null-embedding rows; structured recall still works.
- It does not commit. Writes flush; the caller's transaction
  decides commit/rollback. The exception is `decay` which manages
  its own transaction (it's a Celery task, has no caller session).
- It does not gate by `settings.enable_memory`. That flag is checked
  by `AgenticBaseAgent.memory(ctx)`; the store itself can be
  exercised by tests without touching settings.

**Key invariants.**

- Embedding dimension is exactly 1536 — three layers defend it:
  `_pad_to_target_dim` on every Voyage response, `_hash_fallback_vector`
  always emits 1536 floats L2-normalized, `MemoryWrite` pydantic
  validator rejects mismatched explicit embeddings.
- User-scoped recall NEVER leaks across users. The
  `_scope_clause` helper builds the WHERE clause; the test
  `test_recall_user_scope_isolates_users` is the load-bearing
  privacy assertion. Don't relax it without re-reading that test.

### 3.2 Tools — `ToolRegistry`, `@tool`, `ToolExecutor`

**Public API.**

```python
@tool(name="search_jobs", description="...",
      input_schema=SearchJobsInput, output_schema=SearchJobsOutput,
      requires=("read:job_board",), cost_estimate=0.0,
      timeout_seconds=20.0, is_stub=True)
async def search_jobs(args: SearchJobsInput) -> SearchJobsOutput:
    ...

executor = ToolExecutor(session)
result = await executor.execute(
    "search_jobs", args, context=ToolCallContext(
        agent_name="...", user_id=..., permissions=frozenset({...}),
        call_chain_id=...,
    ),
)
```

**What it does.**

- `@tool` registers a function with name, description, pydantic
  args + return schemas, optional permission requirements, cost
  estimate, timeout. The function still works as a normal callable
  (handy for unit-testing tool bodies without going through the
  executor) but production calls go through the executor.
- The registry is a process-local singleton (`tool_registry`).
  Auto-discovery happens via `ensure_tools_loaded()` which imports
  `app.agents.tools` (which itself imports each themed module).
  On first load, emits `tool_registry.loaded` with `total / stubs
  / real` counts — a free progress bar as stubs become real
  implementations.
- `ToolExecutor.execute` validates input args against the schema,
  enforces permissions, runs with timeout + bounded retries,
  validates output against the declared schema, writes one
  `agent_tool_calls` row regardless of outcome.

**What it does NOT do.**

- It does not raise for tool-internal failures. Runtime errors
  (NotImplementedError, RuntimeError, timeouts) become a
  `ToolCallResult(status="error"|"timeout")` so the calling agent
  decides what to surface. Caller-side bugs (`ToolNotFoundError`,
  `ToolValidationError`, `ToolPermissionError`) DO raise — those
  are programmer errors, not runtime failures.
- It does not retry permanent exceptions. The `_PERMANENT_EXCEPTIONS`
  tuple at the top of `tools.py` lists every exception type that
  short-circuits the retry loop, with a per-type rationale comment.
  Read the comment before adding or removing entries.

**Key invariants.**

- Output schema is enforced after the body returns. A tool that
  silently returns the wrong shape is a tool bug; the executor
  raises `ToolError` and writes the audit row with `status='error'`.
- Audit rows are written even for stubs that raise
  `NotImplementedError`. Production stubs in `app/agents/tools/`
  declare `is_stub=True`; the executor treats `NotImplementedError`
  as a permanent exception (no retry), surfaces it as `status='error'`.

### 3.3 Inter-agent communication — `call_agent`, `CallChain`

**Public API.**

```python
chain = CallChain.start_root(caller="moa", user_id=...)  # outermost call
result = await call_agent("learning_coach", payload={...},
                           session=session, chain=chain)
# result.status: 'ok' | 'error' | 'timeout'
# result.chain_id, result.root_id, result.depth always populated
```

**What it does.**

- `CallChain.start_root(...)` mints a fresh `root_id` UUID. Every
  call inside that root carries the same `root_id` even if the
  call goes one link deep.
- `call_agent` looks up the callee in the agentic registry,
  enforces `allowed_callers` and `allowed_callees` allow-lists,
  runs the callee inside `agent_call_timeout_seconds` (30s default),
  writes one `agent_call_chain` row per call. Returns
  `AgentCallResult` for runtime failures (timeout, callee
  exception); raises `CommunicationError` subclasses for protocol
  failures (cycle, depth ceiling, agent not found, permission
  denied).

**What it does NOT do.**

- It does not write a chain row for the OUTERMOST `execute()` call
  on an agent. Only `call_agent` writes chain rows. See Section 5.
- It does not retry on timeout — fail-fast (Section 7 "fail-fast
  timeouts").
- It does not check for graph cycles in the abstract — only for
  edge cycles (caller → callee). Diamonds (`A → B`, `A → C`, both
  reaching `D`) are allowed. See Section 7 "diamond pattern
  allowed."

**Key invariants.**

- `root_id` is set on every row. Trace queries `WHERE root_id =
  X` recover the full graph regardless of how deep it went.
- The session passed to `call_agent` is bound into a context var
  (`_active_session`) before the callee runs. `AgenticBaseAgent`
  recovers it via `get_active_session()` and rebuilds an
  `AgentContext`. This is how the protocol stays session-free
  while the runtime actually has a session — see Section 7
  "ContextVar for session passing."

### 3.4 Evaluation — `Critic`, `evaluate_with_retry`, `EscalationLimiter` / `RedisEscalationLimiter`

**Public API.**

```python
result = await evaluate_with_retry(
    agent_name="...",
    request=request_str,
    coro_factory=lambda feedback: _run_with_optional_feedback(feedback),
    session=session,
    critic=Critic.default(),                  # Haiku at temp=0
    threshold=0.6,
    max_retries=1,                            # 2 attempts total
    user_id=...,
    call_chain_id=...,
    limiter=escalation_limiter,               # Redis-backed by default
)
# result: AgentResult(output, score, reasoning, retry_count, escalated, ...)
```

**What it does.**

- `Critic` wraps a small LLM (Haiku, temperature 0) with a strict
  JSON output contract (`CriticVerdict`, `extra='forbid'`).
  Defensive parsing extracts the first balanced `{...}` from
  responses that leak prose. Validation failure → `parsed_ok=False`
  with a loud log. The orchestrator does NOT default to passing
  on critic flake — `score=None` fails the threshold check
  because `None` is not `>= 0.6`. See Section 7 "critic
  determinism."
- `evaluate_with_retry` runs the agent → critic → if score <
  threshold and budget remains → retry with critic reasoning fed
  back as `feedback` → otherwise escalate. Every attempt writes
  one `agent_evaluations` row.
- Escalation: writes one `agent_escalations` row with `best_attempt`
  preserved and `notified_admin` set per the rate limiter's
  decision.
- `EscalationLimiter` is the per-agent sliding-window rate limit
  on `notified_admin`. Default 5/hr per agent. Process-local
  in-memory.
- `RedisEscalationLimiter` is the multi-process-safe version —
  sorted set per agent in Redis, scored by epoch seconds, sliding
  window via `ZREMRANGEBYSCORE`. Default after Track 2.
- `make_escalation_limiter()` is the factory that probes Redis
  once at module import and returns the right backend. Boot-time
  fail-open: Redis unreachable → return in-memory + log loud. See
  Section 7 "in-memory then Redis-backed EscalationLimiter."

**What it does NOT do.**

- It does NOT run a second critic when the first flakes. See
  Section 6 convention #7.
- It does NOT default-to-pass on critic failure. Score=None fails
  the threshold check unconditionally.
- It does NOT silently downgrade Redis-backed → in-memory at
  runtime. Boot-time choice is sticky per worker; runtime Redis
  failures fail-open per call. See Section 7 "in-memory then
  Redis-backed EscalationLimiter" + the hot-recovery follow-up.

**Key invariants.**

- The critic LLM is always at `temperature=0`. Override only with
  a documented reason; cross-agent score consistency depends on
  it.
- Escalation rows ALWAYS write. Only `notified_admin` is
  rate-limited. The audit trail is non-negotiable.

### 3.5 Proactive triggers — `@proactive`, `@on_event`, `dispatch_proactive_run`, `route_webhook`

**Public API.**

```python
@proactive(agent_name="learning_coach", cron="0 9 * * *",
           per_user=True, description="...")
@on_event("github.push", agent_name="learning_coach")
class LearningCoach(AgenticBaseAgent[...]):
    ...

# Cron path (Celery → app.tasks.proactive_runner.run_proactive_task)
result = await dispatch_proactive_run(
    session=session,
    agent_name="...",
    trigger_source="cron",
    trigger_key="0 9 * * *",
    idempotency_key=cron_idempotency_key("...", "0 9 * * *",
                                          user_id=...),
    payload={...},
    user_id=...,
)

# Webhook path (FastAPI dependency-verified → route_webhook)
results = await route_webhook(
    session=session, source="github", event_name="github.push",
    delivery_id=request.headers["X-GitHub-Delivery"],
    payload=verified_body,
)
```

**What it does.**

- `@proactive` registers a cron schedule with the agent. At
  Celery boot, `register_proactive_schedules(celery_app)` merges
  these into `celery_app.conf.beat_schedule` — see Section 7
  "boot-order matters."
- `@on_event` registers a webhook subscription. Multiple agents
  can subscribe to the same event; each gets its own audit row
  (the idempotency key includes the agent name to prevent
  fan-out collapse).
- `dispatch_proactive_run` runs the agent via `call_agent` with a
  fresh `CallChain.start_root(caller="proactive:cron")`. Audit
  row written via `INSERT ... ON CONFLICT (idempotency_key) DO
  NOTHING RETURNING id`. Duplicate idempotency key → returns the
  existing row's id with `deduped=True` and does NOT re-invoke
  the agent.
- `route_webhook` fans out to every subscribed agent for the
  event name. Caller (the FastAPI route) MUST verify the signature
  before invoking — sig verification is a route-level dependency,
  not a function call inside the handler.
- Signature verifiers (`verify_github_signature`,
  `verify_stripe_signature`) use HMAC-SHA256 with constant-time
  comparison. Empty-secret config REJECTS all requests (we don't
  inherit the legacy chat-stack handler's silent-skip).

**What it does NOT do.**

- It does NOT mount FastAPI routes. The agentic webhook routes are
  in `app/api/v1/routes/agentic_webhooks.py`; this primitive
  provides the verifiers and the dispatcher.
- It does NOT register the Celery task. The task body lives in
  `app/tasks/proactive_runner.py` (`run_proactive_task`); this
  primitive provides the task name (`PROACTIVE_TASK_NAME`) and the
  `register_proactive_schedules` helper.
- It does NOT validate cron expressions beyond the standard 5-field
  shape. Bad cron strings are logged + skipped (don't crash boot).

**Key invariants.**

- Idempotency keys are deterministic. `cron_idempotency_key` is
  minute-bucketed in UTC. `webhook_idempotency_key` includes the
  agent name (so fan-out subscribers don't collapse to a single
  row — see Section 7 "agent name in webhook idempotency key").
- Webhook signature verification rejects empty secrets. Don't
  ever skip-when-unconfigured.
- The audit row is written before the agent runs (status='queued'
  → updated to 'ok'/'error' on completion). The eager UUID
  pattern lets nested rows reference `parent_id` without a
  transient state. See Section 7 "eager UUID minting."

---

## 4. AgenticBaseAgent — composition pattern

[`backend/app/agents/agentic_base.py`](../backend/app/agents/agentic_base.py).

**Subclass contract.**

```python
class MyAgent(AgenticBaseAgent[MyInputModel]):
    name: ClassVar[str] = "my_agent"
    description: ClassVar[str] = "What it does."
    input_schema: ClassVar[type[AgentInput]] = MyInputModel

    # Optional: opt out of primitives you don't need.
    uses_self_eval: ClassVar[bool] = True
    uses_proactive: ClassVar[bool] = False

    async def run(self, input: MyInputModel, ctx: AgentContext) -> Any:
        memories = await self.memory(ctx).recall(...)
        result = await self.tool_call("get_student_state", {...}, ctx)
        sub = await self.call("other_agent", {...}, ctx)
        return {...}
```

That's it. The base class provides:

- **Auto-registration** via `__init_subclass__`. Subclasses with a
  non-empty `name` register with `_agentic_registry` at class
  definition time. Subclasses with `name = ""` are treated as
  abstract (mirrors Python's ABC machinery — empty name = no
  registry entry).
- **Five opt-out flags.** Each defaults to a sensible value:
  - `uses_memory: bool = True` — `self.memory(ctx)` raises if False
  - `uses_tools: bool = True` — `self.tool_call(...)` raises if False
  - `uses_inter_agent: bool = True` — `self.call(...)` raises if False
  - `uses_self_eval: bool = False` — see Section 7
  - `uses_proactive: bool = False` — see Section 7
- **`execute(input, ctx)` orchestrator.** Validates input against
  `input_schema`, optionally wraps `run` in `evaluate_with_retry`
  (when `uses_self_eval=True`), returns `AgentResult`.
- **`run_agentic(payload, chain)` — the AgenticCallee protocol.**
  Called by `call_agent` on the receiving end. Recovers the
  session via `get_active_session()` (the contextvar set by
  `call_agent` itself), rebuilds an `AgentContext`, invokes
  `execute`, returns `AgentCallResult`.
- **Helpers** that gate on the opt-outs: `self.memory(ctx)`,
  `self.tool_call(name, args, ctx)`, `self.call(callee, payload, ctx)`.
  Each raises a descriptive `RuntimeError` if the corresponding
  opt-out is False.
- **Customization hooks** for tests + special cases:
  - `_critic()` — defaults to `Critic.default()`; override to
    inject a stub.
  - `_limiter()` — defaults to the module-level `escalation_limiter`;
    override to inject an isolated test limiter.
  - `_request_for_eval(input)` — defaults to `input.model_dump_json()`;
    override if your input has a single text field that's the
    actual question and the JSON dump would be noisy for the critic.
  - `_build_llm(max_tokens)` — defaults to `build_llm(tier="smart")`;
    override per agent for cheaper or different model tier.

**Why opt-outs default the way they do.**

- `uses_memory`, `uses_tools`, `uses_inter_agent` default `True`
  because most agents use them and the cost of being wrong is a
  runtime exception (loud), not silent misbehavior.
- `uses_self_eval` defaults `False` because it doubles LLM cost
  per execution and adds latency. Land each new agent dark; flip
  to True once you have baseline scores you trust.
- `uses_proactive` defaults `False` because cron + webhook entry
  points are intentional opt-in surfaces — every proactive
  agent fires without a user action, and that's a deliberate
  choice not a default.

---

## 5. Trace semantics

Two invariants determine whether your trace queries return the
rows you expect. Internalize both before building dashboards;
violating either silently doubles or halves your row count.

### Invariant A: cycle detection is on EDGES, not nodes

Cycles are detected on `(caller, callee)` edge tuples. A diamond
shape — `A → B`, `A → C`, both reaching `D` — is legitimate
fan-out. Only an actual cycle (`A → B → A`) is rejected.

**The rejection fires at the edge that closes the loop.** If
`A → B → A`, the rejection lands when `A`'s second invocation
tries to call `B` again — the `(A, B)` edge is already on the
chain from the first descent. The audit row that gets
`status='cycle'` has `callee_agent='B'`, not `'A'`. Subtle but
correct. See `test_cycle_a_to_b_to_a_raises_and_audits` for the
canonical assertion shape.

### Invariant B: `execute()` does NOT write a chain row, only `call_agent` does

The outermost agent invocation (chat dispatch, proactive trigger,
MOA root) calls `agent.execute(...)`, which does NOT produce an
`agent_call_chain` row. Only `call_agent` (which
`AgenticBaseAgent.call(...)` wraps) writes chain rows.

Concretely: if `A`'s execute() calls `B` (via `self.call("B", ...)`)
and `B` calls `C`, the chain table contains **two** rows (`A→B`
at depth=1, `B→C` at depth=2), not three. The outermost dispatch
lives elsewhere — `agent_actions` for legacy BaseAgent traffic,
`agent_proactive_runs` for cron/webhook flows, no row at all for
direct test invocations.

**The trap:** someone writes `SELECT count(*) FROM agent_call_chain
WHERE root_id = X` expecting the count to equal "number of agents
involved" and gets count - 1. They "fix" it by making `execute()`
write a row, which silently doubles every nested-call trace and
breaks every existing query. Don't.

### Standard query patterns

**Reconstruct a single trace.**

```sql
SELECT depth, caller_agent, callee_agent, status, duration_ms
FROM agent_call_chain
WHERE root_id = '<root-uuid>'
ORDER BY depth, created_at;
```

**Find all traces involving an agent in the last 7 days.**

```sql
SELECT DISTINCT root_id
FROM agent_call_chain
WHERE callee_agent = 'learning_coach'
  AND created_at > now() - interval '7 days';
```

**Join evaluations to their trace.**

```sql
SELECT e.agent_name, e.attempt_number, e.total_score, e.passed,
       c.depth, c.duration_ms
FROM agent_evaluations e
LEFT JOIN agent_call_chain c ON c.root_id = e.call_chain_id
WHERE e.created_at > now() - interval '7 days'
ORDER BY e.created_at DESC;
```

Always include the time window. See Section 6 convention #8.

---

## 6. Conventions

These eleven conventions plus a trace-semantics preamble were
codified during D1–D8 + Track 2 development. They're load-bearing
— each was added in response to an actual bug or design trap
hit during construction. The "Why" line on each is the failure
mode; rules without rationale rot.

The trace-semantics preamble (Section 5 above) is convention zero.
Read it first.

### #1 — Eager UUID generation for audit rows

**Rule.** Pre-mint the row's primary key with `uuid.uuid4()`,
then INSERT once with the final status. Do not use a transient
'queued' status.

**Why.** The migration's CHECK constraint pins `status` to a
closed set (`ok | error | cycle | depth_exceeded` for chain;
`ok | error | timeout` for tool calls). A 'queued' transient
state would either need its own enum slot (wider, harder to
backfill) or violate the CHECK temporarily. Eager UUID minting
sidesteps both: nested calls reference `parent_id = X` immediately
because we own X before the INSERT lands.

**Where it applies.** `agent_call_chain`, `agent_tool_calls`, any
future audit table where nested rows reference the parent's id.

### #2 — Timeouts are fail-fast, never auto-retried

**Rule.** When an agent or tool exceeds its timeout, return
status='timeout' (or 'error') and don't retry. Treat timeouts as
user-visible runtime failures, not transient blips.

**Why.** LLM stalls are almost never transient. They indicate one
of: context too long, provider degraded, prompt pathological. A
retry against the same prompt and provider stalls the same way,
burning tokens against the same root cause. Worse, it doubles
the wall-clock the user waits before the eventual failure
surface. The `tools.py` retry loop deliberately treats
`asyncio.TimeoutError` as a non-retried boundary.

**Counter-pattern to avoid.** "Just retry once on timeout." If
your agent legitimately needs a retry on timeout, that's a circuit
breaker problem (timeout the *whole* request earlier, surface a
useful error, don't shadow-retry).

### #3 — Cycle detection on edges, not nodes

**Rule.** Cycles are detected on `(caller, callee)` edge tuples,
not on visited node sets.

**Why.** A diamond shape — `A → B`, `A → C`, both reaching `D` —
is legitimate fan-out, not a cycle. Node-based detection would
reject the second `A → D` traversal even though it's via a fresh
path. Edge-based detection lets `tailored_resume` and
`cover_letter` both call `jd_analyst` from the same root execute()
without false positives.

**The cost.** A cycle is detected at the edge that *closes* the
loop, not the edge that *enters* it. If `A → B → A`, the
rejection fires when `A`'s second invocation tries `(A, B)` again.
Subtle but correct; documented in the relevant test.

### #4 — Permanent vs transient exception bucketing (tools layer)

**Rule.** A small, named tuple `_PERMANENT_EXCEPTIONS` contains
exception types that should NOT be retried. Each entry has a
one-paragraph rationale comment above the tuple.

**Why.** The temptation to "just retry on every exception" is real
and usually wrong. Permanent failures (auth missing, validation
failed, stub fired) re-fire identically; retries waste budget
and log noise. The named tuple + per-entry comment block forces
every new entry to be justified.

**Where it applies.** `app/agents/primitives/tools.py`. The
decoration pattern (rationale comment per type) should be carried
forward when adding new error types.

### #5 — Critic determinism

**Rule.** The self-eval critic LLM call uses `temperature=0` and
a strict JSON output contract validated by pydantic. Any malformed
output → `score=None`, `passed=None`, log loud, do NOT default
to passing.

**Why.** "Default to pass" means evaluation silently disappears
the moment the critic flakes. We want the opposite: a flaky
critic should reduce trust in the score, not eliminate the eval
signal. A `score=None` result lets the surrounding code see "this
attempt was not evaluated" and treat it as needs-human-review
rather than "green, ship it."

### #6 — Escalation rate limit

**Rule.** Per-agent rate limit on the admin-notification flag
for escalations (default 5/hour). Beyond the limit,
`agent_escalations` rows still land for forensics, but
`notified_admin` stays False.

**Why.** A single broken prompt can produce thousands of
escalations in an hour. Without a rate limit, the admin
notification firehose becomes useless — the real signal drowns
in the noise. The rate limit isolates the failure: one broken
prompt produces a few notifications, not a flood; the audit
trail still records every escalation for post-mortem.

### #7 — No critic-of-critic

**Rule.** When the critic flakes (returns malformed JSON, LLM
raises, score=null), the orchestrator escalates after the retry
budget exhausts. We do NOT introduce a second critic to evaluate
the first critic, nor a "judge of judges."

**Why.** Self-evaluation is a useful primitive precisely because
it has a clear stopping point. Once you start evaluating the
evaluator, you're committing to an infinite regress: who
evaluates the second critic? At what cost ceiling? With what
failure semantics when the meta-critic also flakes? The honest
answer to "the critic broke" is "this attempt has no trustworthy
evaluation; surface that to a human." Escalation does exactly
that.

The temptation to add critic-of-critic is real and recurring —
mostly motivated by "we don't want to bother admins with critic
flakes." The right response is to make the critic LLM more
deterministic (already temp=0, strict JSON contract), tighten
the retry budget, or rate-limit the escalation notification
(already done in convention #6). Not stack judgments.

### #8 — Dashboard queries always include a time window

**Rule.** Every aggregate query against `agent_evaluations` or
`agent_tool_calls` filters by `created_at > now() - interval
'<window>'`. There is no "scores all-time" query. The standard
window is 7 days; pages can offer 24h / 7d / 30d toggles.

**Why.** Without a time window, scores from a fixed prompt three
months ago drag the average. You cannot tell whether today's
prompt is regressing or whether the agent is mid-improvement.
Bounded windows make trends visible and let "is this getting
better or worse?" be a real question with a real answer.

Standard form for the prompt-quality dashboard:

```sql
SELECT
  agent_name,
  AVG(total_score)        AS avg_score,
  bool_or(passed)         AS passed_at_least_once,
  count(*) FILTER (WHERE passed)        AS passes,
  count(*) FILTER (WHERE NOT passed)    AS fails
FROM agent_evaluations
WHERE created_at > now() - interval '7 days'
GROUP BY agent_name
ORDER BY avg_score ASC;
```

### #9 — structlog reserves `event=` — never pass it as a kwarg

**Rule.** structlog uses the first positional argument to
`log.info(...)` etc. as the message-string key, internally bound
to `event=<message>`. Passing `event=` as a named kwarg in the
same call collides:

```python
# WRONG — TypeError at runtime
log.info("widget.dispatched", event="github.push", source="github")
# RIGHT
log.info("widget.dispatched", event_name="github.push", source="github")
```

**Why.** The collision presents as `TypeError: meth() got
multiple values for argument 'event'` at log time, and only fires
on the first execution of that code path — so a never-tripped
error branch can ship with a hidden bomb. We hit this twice
during D6 development on `@on_event` registration and
`route_webhook`'s unrouted-event log line. Both fixes were
trivial (rename the kwarg to `event_name`); the root cause is
structlog's contract, which won't change.

**Standard alternatives.** `event_name`, `event_type`,
`event_source`. Pick one and stick to it within a module so log
queries can join consistently. The Agentic OS primitives layer
uses `event_name` throughout.

### #10 — `__init__.py` files in import-heavy packages stay side-effect-free

**Rule.** In any package whose modules eventually import
C-extension dependencies (numpy, pgvector, lxml, cryptography),
the package's `__init__.py` must NOT eager-import those modules.
Callers go through the explicit submodule path:

```python
# WRONG — eager re-export from package init
# app/agents/__init__.py
from app.agents.agentic_base import AgenticBaseAgent  # ← cascades

# RIGHT — package init is empty (or docstring-only)
from app.agents.agentic_base import AgenticBaseAgent  # explicit
```

**Why.** Coverage instrumentation (and certain test runners)
walks the import graph at session start. When a package init
eagerly imports a module that pulls in numpy via pgvector,
numpy's `_multiarray_umath` extension trips its own "module
loaded more than once" guard and the test session crashes with
`ImportError: cannot load module more than once per process`.
The error has nothing to do with the agent code; it's a side
effect of how `coverage.py` interacts with C-extension reload
detection. Once the package init goes side-effect-free, the
problem vanishes.

**Where it does NOT apply.** Package inits that re-export
pure-Python symbols only (e.g. `app/schemas/__init__.py`
re-exporting pydantic models). Eager re-export is fine when the
cost is just "some Python tokens read at import time" — the
trap is the C-extension cascade.

### #11 — Production Celery is sync; tests drive the async helper directly

**Rule.** Celery task bodies that need to call async code use
`asyncio.run(...)` at the task's outer boundary. Tests do NOT
call `task.apply()` to exercise such tasks — they call the
async helper function directly. The asymmetry is deliberate.

```python
# Production task body (app/tasks/proactive_runner.py)
@shared_task(name=...)
def run_proactive_task(...):
    summary = asyncio.run(_run_proactive_async(...))
    return summary

# Test exercises the helper directly
async def test_proactive_runner_fires_agent(...):
    summary = await _run_proactive_async(...)  # not task.apply()
```

**Why.** Production Celery workers are synchronous — no event
loop is running, so `asyncio.run` is the textbook entry point
and works cleanly. Pytest-asyncio runs each test inside an event
loop; `task.apply()` invokes the body inside that loop, and
`asyncio.run` inside a running loop raises `RuntimeError: cannot
be called from a running event loop`.

The "obvious fix" (run the task body in a worker thread with
its own loop) creates a different problem: async SQLAlchemy
sessions are loop-bound, so passing a test's session into a
worker-thread loop trips `Future attached to a different loop`.
The async DB boundary is what makes the asymmetry stick.

**The right call is to keep production code simple** —
`asyncio.run` is correct in production — and accept that tests
drive the helper directly. ONE separate test asserts the
`@shared_task(name=...)` binding exists (catches typos that
would silently mis-route every cron firing in prod). See
`test_celery_task_registered` for the canonical example.

### #12 (proposed) — Infrastructure-degraded log lines name degradation, consequence, and recovery

**Rule.** When code falls back to a degraded mode because
infrastructure is unavailable (Redis down, embedding API 5xx,
provider rate-limited), the warning log line must spell out three
things:

1. What degradation just happened.
2. What the consequence is for the running system.
3. When (or how) the system self-heals.

The `escalation_limiter.redis_unreachable_at_boot` log line is
the canonical example:

```
escalation_limiter.redis_unreachable_at_boot
  fallback=in_memory
  note="Permissive across workers — admin notifications will
        over-grant by N× until Redis returns. Restore Redis to
        re-enable the cross-worker cap."
```

**Why.** When infrastructure pages, the on-call operator reads
logs. A bare `Redis unavailable` log doesn't tell them what
broke for users; "permissive across workers — over-grant by N×"
does. They can decide whether to wake the rest of the team or
let it burn until business hours.

**Status.** Convention #12 is proposed by Track 2 review. Add
new degraded-mode log lines that follow this shape; treat
existing log lines that don't follow it as candidates for
cleanup when touched.

---

## 7. Decisions made and why

This is the most important section of the document. Every
decision below was a fork; the alternative was real; the choice
was motivated by an observed failure mode. Read these before you
"fix" anything counterintuitive.

### `postgresql.ENUM` instead of `sa.Enum` in migrations

**Decision.** Use `from sqlalchemy.dialects.postgresql import ENUM`
in migrations; do NOT use the generic `sa.Enum`.

**Alternative considered.** The generic `sa.Enum(...,
create_type=False)` is what you'd reach for first — it's the
obvious abstraction.

**Why rejected.** `sa.Enum`'s `create_type=False` flag is
**silently ignored** by SQLAlchemy + asyncpg. `op.create_table`
re-emits `CREATE TYPE` on every column declaration regardless of
the flag, and you get a `DuplicateObjectError` on the second
column that uses the same enum. We hit this on D1 — the
migration ran once successfully (creating the type), then any
re-run failed because the type already existed.

**What we do instead.** A two-step pattern:

1. Raw SQL `DO $$ … IF NOT EXISTS … CREATE TYPE … $$` block at
   the top of the migration. Idempotent; honest about what's
   happening.
2. `postgresql.ENUM("user", "agent", "global",
   name="agent_memory_scope", create_type=False)` in the column
   declaration. The dialect-specific class actually respects
   `create_type=False` (the test failures confirm this — see
   D1's commit message).

**Where this applies.** Every future migration that uses an
enum. If you copy `0054_agentic_os_primitives.py` as a template,
the enum pattern is right there.

### Eager UUID minting (single INSERT) vs queued-then-update

**Decision.** Mint the row's primary key with `uuid.uuid4()`
before the INSERT, then INSERT once with the final status.

**Alternative considered.** INSERT a row with `status='queued'`,
let the agent run, then UPDATE the row with the final status.
This is the textbook async-job pattern.

**Why rejected.** The migration's CHECK constraint pins `status`
to a closed set (`ok | error | cycle | depth_exceeded` for chain;
`ok | error | timeout` for tool calls). Adding 'queued' would
either:

- Bloat the enum to support a transient state nobody queries on,
  OR
- Require the migration to allow temporary CHECK violations,
  which Postgres doesn't.

**The failure mode that motivated the choice.** D4's first draft
used the queued pattern. The CHECK constraint rejected the
INSERT. The "fix" attempt was to widen the CHECK; that broke
every existing dashboard query that filters on `status IN
(...)`. Eager UUID minting makes the transient state
unnecessary: nested calls reference `parent_id = X` because we
own X before the INSERT lands, and the INSERT happens once when
the outcome is known.

**Where this applies.** Every audit-row write where nested rows
need to reference the parent. Documented in code at the relevant
INSERT sites.

### ContextVar for session passing vs protocol extension

**Decision.** The active SQLAlchemy session is bound to a
`contextvars.ContextVar` (`_active_session` in
`communication.py`) before `call_agent` invokes the callee. The
callee recovers it via `get_active_session()`.

**Alternative considered.** Extend the `AgenticCallee` protocol
from `(payload, chain)` to `(payload, chain, session)`. Cleaner
on paper.

**Why rejected.** Two costs:

1. Every existing implementation of the protocol (the test
   mocks, the `AgenticBaseAgent` class) would need to be updated
   in lockstep. We accepted this when there were 3 implementations;
   if we'd done this in D7b after D8 added more, it would have
   been worse.
2. More importantly: chains are immutable and shareable across
   threads/tasks; sessions are NOT. A protocol that carries
   session in the same arg position as chain encourages callers
   to think they're symmetric. They're not.

**The failure mode that motivated the choice.** D7's first draft
had a private contextvar inside `agentic_base.py` (set by
`AgenticBaseAgent.call(...)`). That worked when the chat path
was the only entry point. Then D7b's proactive dispatch went
`dispatch_proactive_run → call_agent → callee.run_agentic`
without ever touching `AgenticBaseAgent.call(...)` — the
contextvar was never set, and `run_agentic` raised "outside an
active call_agent context." Moving the contextvar into
`communication.py` (the layer that owns the call boundary) made
it set for every entry path. Single source of truth.

### Fail-fast timeouts (no LLM retry on stall)

**Decision.** When an agent or tool exceeds its timeout, return
`status='timeout'` (or 'error') and don't retry.

**Alternative considered.** "Just retry once" — the universal
default for transient errors.

**Why rejected.** LLM stalls are almost never transient. They
indicate one of: context too long, provider degraded, prompt
pathological. A retry against the same prompt and provider
stalls the same way, burning tokens against the same root cause.
Worse, it doubles wall-clock the user waits before the eventual
failure surface.

**The failure mode that motivated the choice.** Production
operators repeatedly observe that "transient timeout" retries
cost 2× tokens and surface 2× later than just failing. The
project chose to surface fast and let the surrounding flow (or
the user re-issuing) decide what to do next. If your agent
needs a retry on timeout, that's a circuit breaker problem
(timeout the *whole* request earlier), not a retry-loop problem.

### Diamond pattern allowed (cycles ≠ shared callee)

**Decision.** Cycle detection compares `(caller, callee)` edge
tuples. A diamond — `A → B`, `A → C`, both reaching `D` — is
allowed.

**Alternative considered.** Visited-node set: reject any callee
already on the chain.

**Why rejected.** Visited-node detection would block legitimate
fan-out. `tailored_resume` and `cover_letter` both calling
`jd_analyst` from the same root execute() is a real use case;
the second `(*, jd_analyst)` traversal isn't a cycle.

**The cost we accepted.** A cycle is detected at the edge that
*closes* the loop, not the edge that *enters* it. If `A → B →
A`, the rejection fires when `A`'s second invocation tries the
already-visited `(A, B)` edge. The audit row that gets
`status='cycle'` has `callee_agent='B'`. Subtle but correct.
See `test_cycle_a_to_b_to_a_raises_and_audits` for the canonical
assertion.

### Critic determinism (temperature=0, default-to-fail on parse failure)

**Decision.** The critic LLM runs at `temperature=0` with a
strict JSON output contract (`CriticVerdict`, `extra='forbid'`).
Malformed output → `score=None`, NOT a default 0.5 or 0.8.

**Alternative considered.** "Default to a permissive score on
critic flake so we don't spam admins."

**Why rejected.** A flaky critic should REDUCE trust in the
score, not eliminate the eval signal. Default-to-pass means the
moment the critic provider has a 5xx, every agent looks like it
passed evaluation — until you check the dashboard a week later
and realize you stopped catching regressions.

**The mechanism.** `score=None` fails the threshold check
because `None is not >= 0.6`. The retry path fires; if the
critic flakes both attempts, the orchestrator escalates with
the reason "critic could not produce a verdict across N
attempts". Operators see a real signal — "the critic is
broken" — instead of silent passing.

### In-memory then Redis-backed `EscalationLimiter`

**Decision.** `EscalationLimiter` shipped as in-memory in D5;
`RedisEscalationLimiter` was added in Track 2 with a sorted-set
sliding-window backing.

**Alternative considered.** Ship Redis-backed from D5.

**Why rejected at D5.** D5 was the evaluation primitive; the
goal was to prove the orchestrator + critic + escalation flow
worked end-to-end. Multi-process correctness was a known
follow-up tracked at
`docs/followups/escalation-limiter-redis.md` from the moment
D5 landed. Shipping the simpler version first kept D5's review
surface manageable.

**Why Redis-backed in Track 2.** The moment proactive flows
landed (D6 + D7b infra; D8 first agent), Celery workers — by
definition multi-process — would over-grant the per-agent
notification budget by Nx where N = worker count. The Track 2
swap converts the budget from "per-process cap" to "actual
cap."

**Three-layer fail-open** is the defensive shape:

1. **Boot-time** — `make_escalation_limiter()` probes Redis with
   a 1s PING. Unreachable → return in-memory + log "permissive
   across workers — over-grant by Nx" so on-call sees the
   degradation.
2. **Runtime ZREMRANGEBYSCORE / ZCARD** — any exception →
   return True (escalate everything) + log
   `escalation_limiter.redis_failure`.
3. **Runtime ZADD / EXPIRE** — same.

If any layer were missing, you'd have a partial fail-open: Redis
goes down mid-request, one path catches it but the other throws.
Three layers cover all paths.

**The contract that matters most.** Fail-open returns True
(permissive), NOT False (suppress). On infrastructure failure
the instinct is to "be safe by refusing to act." That instinct
is wrong here: refusing means suppressing escalations during a
Redis incident, exactly when admins need notifications most.
Permissive behavior under failure is the correct default.

**Time-math units pinned.** All scores are EPOCH SECONDS via
`time.time()` — never milliseconds. Window default is 3600
seconds. Cutoff = `now - window_seconds`. Mixing seconds and
milliseconds across writes and reads would make the window 1000×
too narrow on read or too wide on write, and the bug only
surfaces under load. Code comments at every relevant line name
the unit explicitly.

### Off-by-default `uses_self_eval`

**Decision.** `AgenticBaseAgent.uses_self_eval` defaults to
`False`. Each new agent must opt in.

**Alternative considered.** Default to `True` — "evaluation is
good, why would you ever turn it off?"

**Why rejected.** Self-eval doubles LLM calls per execution
(agent's main call + critic call) and adds latency on every
turn. For chat-path agents (latency-sensitive, students see a
typing indicator), the cost is real. The right shape is to land
each new agent dark, observe baseline scores from spot-checks
or human review, then flip to True once you trust the critic to
judge that agent's output well.

**The failure mode this avoids.** Default-on would mean every
new agent's first chat reply takes 2× as long and burns 2× the
tokens before anyone notices. A team-wide LLM bill spike at the
end of month one would surface it eventually; opt-in surfaces
it on day one in design review, where it's cheaper to discuss.

The reference Learning Coach (D8) demonstrates the per-method
pattern: chat path stays critic-free for latency; nightly path
opts INTO self-eval inline by calling `evaluate_with_retry`
directly — that's where generic mass-mail nudges are the actual
failure mode and the critic earns its keep.

### Three-layer fail-open is a reusable defensive pattern

(Convention #12 above codifies the log shape; this entry
codifies the architectural pattern.)

When code depends on infrastructure that can be down, defend at
three layers:

1. **Boot-time probe** — fail-open at module import to a
   degraded mode with a loud warning that names the consequence.
2. **Wrapper around the read path** — every read that talks to
   the infrastructure is wrapped in try/except that fails open
   with a per-call warning.
3. **Wrapper around the write path** — same shape, separate try
   block, separate warning. Don't share the wrapper with the
   read path; partial fail-open (read works, write throws) is
   the worst kind of half-broken.

The Track 2 `RedisEscalationLimiter` is the canonical example.
Future infrastructure-dependent code should follow the same
shape.

---

## 8. Open follow-ups (post-D8 + Track 2 status)

Tracked under `docs/followups/`. Each file has a "done when"
checklist; resolved follow-ups stay in place with a "RESOLVED
YYYY-MM-DD" header so the trail of past decisions remains
useful.

### Open

- **`neon-pgvector-verification.md`** — confirm pgvector is on
  Neon's allowlist + the migration role has CREATE on the
  database before running migration 0054 in prod for the first
  time. One-time pre-deploy verification; not blocking dev.
- **`align-audit-error-columns.md`** — `agent_call_chain` stashes
  errors inside `result` JSONB while `agent_tool_calls` /
  `agent_proactive_runs` use a real `error_message` column.
  Schema-alignment proposal for the next agentic-OS migration;
  not urgent (the cross-table debug query is the only ergonomics
  hit), but the breadcrumb matters.
- **`escalation-limiter-hot-recovery.md`** — Track 2 ships
  boot-time probe + runtime fail-open, but no hot-recovery (a
  worker that boots with Redis down stays in-memory until
  restart). Acceptable for current deploy cadence; revisit when
  worker lifetime > 24h or student volume makes the over-grant
  visible.
- **`dev-db-image-swap.md`** — team channel notice + ack
  checklist for the docker-compose `db` swap to
  `pgvector/pgvector:pg16`. Operational awareness; not urgent.

### Resolved

- **`escalation-limiter-redis.md`** — RESOLVED 2026-05-02 by
  Track 2. `RedisEscalationLimiter` shipped with three-layer
  fail-open.

### Not yet a follow-up file (named for tracking)

- **The 26 legacy agents have not been migrated to
  `AgenticBaseAgent`.** They still register through
  `app.agents.registry.AGENT_REGISTRY` and dispatch via MOA.
  Migration is per-agent (each agent's prompts, eval
  thresholds, tool needs vary). The Pass 3c playbook will
  define the migration recipe. Until then: do NOT touch the
  legacy agents from this layer.

---

## 9. What this document does NOT cover

This document covers the agentic OS foundation as of D8 + Track
2. Forward-looking design lives in separate Pass 3b–3l design
documents. Each below is named so you know where the boundary of
this file ends and where to look for the rest.

- **Pass 3b — Supervisor agent.** A coordinator above the
  individual agents that decides which agent should handle a
  given user message, routes between them, and aggregates
  outputs. This file describes how individual agents are built;
  it does NOT describe how to choose among them at runtime.
- **Pass 3c — Agent migration playbook.** The recipe for moving
  one of the 26 legacy `BaseAgent` agents onto `AgenticBaseAgent`.
  Per-agent: input/output mapping, prompt re-anchoring, tool
  registration, self-eval threshold tuning, regression test set.
- **Pass 3d — Tool implementations.** The 11 tools registered in
  D3 (`recall_memory`, `store_memory`, `get_student_state`,
  `update_mastery`, `send_student_message`, `schedule_review`,
  `search_course_content`, `run_ruff`, `read_github_pr`,
  `search_jobs`, `parse_jd`) all raise `NotImplementedError`
  today. Pass 3d defines real bodies + the data sources each
  pulls from.
- **Pass 3e — GraphRAG.** Memory layer today is flat key-value
  with embedding similarity. GraphRAG adds entity + relationship
  modelling on top so an agent can reason about
  "Marcus's manager's pain points" not just "things tagged
  Marcus." Stretches the schema beyond `agent_memory`'s shape.
- **Pass 3f — Entitlement enforcement.** Tools today declare
  `requires=("read:student",)` but nothing enforces what
  permissions a request actually has. Pass 3f wires permissions
  from auth context into `AgentContext.permissions` and ties
  agent capability to entitlement (paid vs free).
- **Pass 3g — Safety beyond critic.** The critic catches
  generic-vs-specific. It does NOT catch unsafe outputs (PII
  leakage, harmful content, prompt-injection passthrough). Pass
  3g layers a content-safety filter that runs in parallel to
  the critic.
- **Pass 3h — Interrupt agent.** A long-running agent (mock
  interview, deep RAG, multi-step planning) needs cancellation
  semantics that today's `asyncio.wait_for` timeout doesn't
  provide. Pass 3h defines a graceful-cancel protocol with
  partial-output recovery.
- **Pass 3i — Scale and observability.** Today's metrics layer
  is a no-op shim. Pass 3i wires real Prometheus + adds the
  tracing context (OpenTelemetry spans threaded through
  `call_agent`) that production needs at scale.
- **Pass 3j — Naming sweep.** The repo carries "PAE" /
  "CareerForge" / "pae.dev" as legacy names. The Track 4 audit
  produces the inventory; Pass 3j defines the rename strategy
  (which surfaces are user-visible vs internal-only, which
  legacy receipts keep their prefix, etc.).
- **Pass 3l — Implementation roadmap.** The order in which
  Pass 3b–3j ship, what they depend on, and what blocks what.
  This is the schedule, not the architecture.

If you arrive at this codebase and need any of the above, the
Pass 3X documents are where to look. If they don't exist yet,
the design hasn't been done — surface the gap before
implementing.

---

## Appendix — File-by-file index

Every primitive's source location and what to read for what
question.

| Question | File |
|---|---|
| "Where's the schema?" | `backend/alembic/versions/0054_agentic_os_primitives.py` |
| "How do I add a new agent?" | `backend/app/agents/example_learning_coach.py` (template), this document Section 4 |
| "How do I add a new tool?" | `backend/app/agents/tools/student_tools.py` (any of the existing examples), Section 3.2 |
| "How does memory recall actually work?" | `backend/app/agents/primitives/memory.py` → `_semantic_search`, `_structured_search`, Section 3.1 |
| "Why is `event=` in my log line crashing?" | Section 6 convention #9 |
| "Why does `sa.Enum(create_type=False)` crash my migration?" | Section 7 "postgresql.ENUM vs sa.Enum" |
| "How do I trace which agent called which?" | Section 5 |
| "Where do escalations show up?" | `agent_escalations` table, Section 3.4, Section 7 in-memory→Redis |
| "Why doesn't my proactive cron fire?" | Section 7 "in-memory then Redis-backed EscalationLimiter" (no — wrong section!), check Celery beat boot logs for `agentic_loader.loaded` and `proactive.beat_register.merged` |
| "What's the Pass 3X for X?" | Section 9 |
