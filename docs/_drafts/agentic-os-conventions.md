# Agentic OS — conventions to surface in AGENTIC_OS.md (D9)

## Top-of-doc: trace semantics — read these before writing any
## query against `agent_call_chain`

Two invariants determine whether your trace queries return the
rows you expect. Internalize both before you build a dashboard;
violating either silently doubles or halves your row count.

### Invariant A: cycle detection is on EDGES, not nodes

Cycles are detected on `(caller, callee)` edge tuples, not on
visited node sets. A diamond shape — `A → B`, `A → C`, both
reaching `D` — is legitimate fan-out. Only an actual cycle
(`A → B → A`) is rejected. **The rejection fires at the edge that
*closes* the loop**, not the edge that enters it: if `A → B → A`,
the rejection lands when A's second invocation tries `(A, B)`
again, so the row that gets `status='cycle'` has
`callee_agent='B'`, not `'A'`. Subtle but correct; see
`test_cycle_a_to_b_to_a_raises_and_audits` in D4.

### Invariant B: `execute()` does NOT write a chain row, only `call_agent` does

The outermost agent invocation (the entry point — chat dispatch,
proactive trigger, MOA root) calls `agent.execute(...)`, which does
NOT produce an `agent_call_chain` row. Only `call_agent(...)` —
which AgenticBaseAgent's `self.call(...)` wraps — writes chain
rows.

Concretely: if A's execute() calls B (via `self.call("B", ...)`)
and B calls C, the chain table contains **two** rows (A→B at
depth=1, B→C at depth=2), not three. The outermost dispatch lives
elsewhere — `agent_actions` for legacy BaseAgent traffic,
`agent_proactive_runs` for cron/webhook flows, no row at all for
direct test invocations.

The trap: someone writes `SELECT count(*) FROM agent_call_chain
WHERE root_id = X` expecting the count to equal "number of agents
involved" and gets count - 1. They "fix" it by making execute()
write a row, which silently doubles every nested-call trace and
breaks every existing query. Don't.

If you need a single table that counts every agent invocation
(root + nested), JOIN `agent_actions` (or `agent_proactive_runs`)
to `agent_call_chain` on `root_id`. The nested rows live in chain;
the root lives wherever the dispatcher landed it. This split is
deliberate: it keeps cycle detection and depth tracking scoped
to inter-agent calls (where they matter) without forcing every
single-agent execution to pay for an extra row.

---


This file is a holding pen for design-decision rationale that needs
to make it into the public docs in deliverable 9. Each entry has a
one-line summary and the full reasoning so the D9 author can paste
it in without re-deriving the argument.

Delete this file when D9 ships and the points have been transcribed.

## 1. Eager UUID generation for audit rows

**Convention:** Pre-mint the row's primary key with `uuid.uuid4()`,
then INSERT once with the final status. Do not use a transient
'queued' status.

**Why:** The migration's CHECK constraint pins `status` to a closed
set ('ok', 'error', 'cycle', 'depth_exceeded'). A 'queued' transient
state would either need its own enum slot (wider, harder to
backfill) or violate the CHECK temporarily. Eager UUID minting
sidesteps both: nested calls reference `parent_id = X` immediately
because we own X before the INSERT lands.

**Where it applies:** `agent_call_chain`, `agent_tool_calls`, any
future audit table where nested rows reference the parent's id.

## 2. Timeouts are fail-fast, never auto-retried

**Convention:** When an agent or tool exceeds its timeout, return
status='timeout' and don't retry. Treat timeouts as user-visible
runtime failures, not transient blips.

**Why:** LLM stalls are almost never transient. They indicate one
of: context too long, provider degraded, prompt pathological. A
retry against the same prompt and provider will stall the same way,
burning tokens against the same root cause. Worse, it doubles the
wall-clock the user waits before the eventual failure surface.

The `tools.py` retry loop deliberately excludes `asyncio.TimeoutError`
from `_PERMANENT_EXCEPTIONS` only because the loop catches and
reports timeouts directly without going through the generic retry
path — same outcome (no retry on timeout), different code path.

**Counter-pattern to avoid:** "Just retry once on timeout." If your
agent legitimately needs a retry on timeout, that is a circuit
breaker problem (timeout the *whole* request earlier, surface a
useful error, don't shadow-retry).

## 3. Cycle detection on edges, not nodes

**Convention:** Cycles are detected on `(caller, callee)` edge
tuples, not on visited node sets.

**Why:** A diamond shape — `A → B`, `A → C`, both reaching `D` —
is legitimate fan-out, not a cycle. Node-based detection would
reject the second `A → D` traversal even though it's via a fresh
path. Edge-based detection lets `tailored_resume` and `cover_letter`
both call `jd_analyst` from the same root execute() without false
positives.

The cost: a cycle is detected at the edge that *closes* the loop,
not the edge that *enters* it. If `A → B → A`, the rejection fires
when `A`'s second invocation tries `(A, B)` again, not when `B`
tries `(B, A)`. Subtle but correct; documented in the relevant test.

## 4. Permanent vs transient exception bucketing (tools layer)

**Convention:** A small, named tuple `_PERMANENT_EXCEPTIONS`
contains exception types that should NOT be retried. Each entry
has a one-paragraph rationale comment above the tuple.

**Why:** The temptation to "just retry on every exception" is
real and usually wrong. Permanent failures (auth missing, validation
failed, stub fired) re-fire identically; retries waste budget and
log noise. The named tuple + per-entry comment block forces every
new entry to be justified.

**Where it applies:** `app/agents/primitives/tools.py`. The
decoration pattern (rationale comment per type) should be carried
forward when adding new error types.

## 5. Critic determinism

**Convention:** The self-eval critic LLM call uses `temperature=0`
and a strict JSON output contract validated by pydantic. Any
malformed output → score=null, passed=null, log loud, do NOT
default to passing.

**Why:** "Default to pass" means evaluation silently disappears the
moment the critic flakes. We want the opposite: a flaky critic
should reduce trust in the score, not eliminate the eval signal.
A score=null result lets the surrounding code see "this attempt
was not evaluated" and treat it as needs-human-review rather than
"green, ship it."

## 6. Escalation rate limit

**Convention:** Per-agent rate limit on the admin-notification
flag for escalations (e.g., 5 per hour). Beyond the limit,
`agent_escalations` rows still land for forensics, but
`notified_admin` stays False.

**Why:** A single broken prompt can produce thousands of
escalations in an hour. Without a rate limit, the admin notification
firehose becomes useless — the real signal drowns in the noise.
The rate limit isolates the failure: one broken prompt produces a
few notifications, not a flood; the audit trail still records every
escalation for post-mortem.

## 7. No critic-of-critic

**Convention:** When the critic flakes (returns malformed JSON,
LLM raises, score=null), the orchestrator escalates after the
retry budget exhausts. We do NOT introduce a second critic to
evaluate the first critic, nor a "judge of judges."

**Why:** Self-evaluation is a useful primitive precisely because
it has a clear stopping point. Once you start evaluating the
evaluator, you're committing to an infinite regress: who evaluates
the second critic? At what cost ceiling? With what failure semantics
when the meta-critic also flakes? The honest answer to "the critic
broke" is "this attempt has no trustworthy evaluation; surface that
to a human." Escalation does exactly that.

The temptation to add critic-of-critic is real and recurring —
mostly motivated by "we don't want to bother admins with critic
flakes." The right response is to make the critic LLM more
deterministic (already temp=0, strict JSON contract), tighten the
retry budget, or rate-limit the escalation notification (already
done in convention #6). Not stack judgments.

## 8. Dashboard queries always include a time window

**Convention:** Every aggregate query against `agent_evaluations`
or `agent_tool_calls` filters by `created_at > now() - interval
'<window>'`. There is no "scores all-time" query. The standard
window is 7 days; pages can offer 24h / 7d / 30d toggles.

**Why:** Without a time window, scores from a fixed prompt three
months ago drag the average. You cannot tell whether today's prompt
is regressing or whether the agent is mid-improvement. Bounded
windows make trends visible and let "is this getting better or
worse?" be a real question with a real answer.

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

## 9. structlog reserves `event=` — never pass it as a kwarg

**Convention:** structlog uses the first positional argument to
`log.info(...)` / `log.warning(...)` etc. as the message-string
key, internally bound to `event=<message>`. Passing `event=` as a
named kwarg in the same call collides:

```python
# WRONG — TypeError at runtime
log.info("widget.dispatched", event="github.push", source="github")

# RIGHT
log.info("widget.dispatched", event_name="github.push", source="github")
```

**Why:** The collision presents as
`TypeError: meth() got multiple values for argument 'event'` at
log time, and only fires on the first execution of that code path
— so a never-tripped error branch can ship with a hidden bomb.
We hit this twice during D6 development on `@on_event` registration
and `route_webhook`'s unrouted-event log line. Both fixes were
trivial (rename the kwarg to `event_name`); the root cause is
structlog's contract, which won't change.

**Standard alternatives:** `event_name`, `event_type`,
`event_source`. Pick one and stick to it within a module so log
queries can join consistently. The Agentic OS primitives layer
uses `event_name` throughout for parity with `WebhookSubscription`'s
field name.

## 10. `__init__.py` files in import-heavy packages stay side-effect-free

**Convention:** In any package whose modules eventually import
C-extension dependencies (numpy, pgvector, lxml, cryptography),
the package's `__init__.py` must NOT eager-import those modules.
Callers go through the explicit submodule path:

```python
# WRONG — eager re-export from package init
# app/agents/__init__.py
from app.agents.agentic_base import AgenticBaseAgent  # ← cascades

# RIGHT — package init is empty (or docstring-only)
# Callers import the explicit path:
from app.agents.agentic_base import AgenticBaseAgent
```

**Why:** Coverage instrumentation (and certain test runners) walks
the import graph at session start. When a package init eagerly
imports a module that pulls in numpy via pgvector, numpy's
`_multiarray_umath` extension trips its own "module loaded more
than once" guard:

```
ImportError: cannot load module more than once per process
```

The error has nothing to do with the agent code; it's a side
effect of how `coverage.py` interacts with C-extension reload
detection. Once the package init goes side-effect-free, the
problem vanishes.

We hit this exactly once during D7 development with
`app/agents/__init__.py` re-exporting `AgenticBaseAgent`. The fix
took 30 seconds — the diagnosis took 30 minutes. Codifying the
rule means the next person in `app/models/__init__.py` or
`app/services/__init__.py` doesn't repeat the loop.

**Where this applies:** any package whose modules transitively
import pgvector, numpy, lxml, cryptography, or pillow. When in
doubt, leave the init empty.

**Where it does NOT apply:** package inits that re-export pure-
Python symbols only (e.g. `app/schemas/__init__.py` re-exporting
pydantic models). Eager re-export is fine when the cost is just
"some Python tokens read at import time" — the trap is the
C-extension cascade.

## 11. Production Celery is sync; tests drive the async helper directly

**Convention:** Celery task bodies that need to call async code use
`asyncio.run(...)` at the task's outer boundary. Tests do NOT call
`task.apply()` to exercise such tasks — they call the async helper
function directly. The asymmetry is deliberate.

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

**Why:** Production Celery workers are synchronous — no event loop
is running, so `asyncio.run` is the textbook entry point and works
cleanly. Pytest-asyncio runs each test inside an event loop;
`task.apply()` invokes the body inside that loop, and `asyncio.run`
inside a running loop raises `RuntimeError: cannot be called from
a running event loop`.

The "obvious fix" (run the task body in a worker thread with its
own loop) creates a different problem: async SQLAlchemy sessions
are loop-bound, so passing a test's session into a worker-thread
loop trips `Future attached to a different loop`. The async DB
boundary is what makes the asymmetry stick.

**The right call is to keep production code simple** — `asyncio.run`
is correct in production — and accept that tests drive the helper
directly. We caught this during D7b development; the rationale is
documented at every site that touches it (task body, test docstring,
this convention).

**What this means for new agents:** when you add a `@shared_task`
that wraps an async helper, your test file should:

1. Test the helper async function directly, not via `task.apply()`
2. Have ONE separate test that asserts the `@shared_task(name=...)`
   binding exists (catches typos that would silently mis-route
   every cron firing in prod)

`test_celery_task_registered` in `test_d7b_integration.py` is the
canonical example of #2.
