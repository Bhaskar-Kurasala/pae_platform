# Agentic OS — E2E precondition gaps

**Generated:** 2026-05-02 (Track 5 of the parallel cleanup workstream)
**Companion to:** `frontend/e2e/agentic-os.spec.ts`
**Scope:** what *cannot* be E2E-tested today against the D1–D8 surface,
and what would have to land first to make each surface reachable.

---

## Why this document exists

The brief for Track 5 was: write MCP-Playwright E2E coverage for D1–D8
of the Agentic OS layer. The honest outcome is **the layer is mostly
not reachable from outside the process today**, and the most valuable
test of "what's missing" is this document, not a fabricated test
harness.

The principle from the Track 5 sign-off prompt:

> "Do not invent an endpoint that 'would' trigger a memory write just
> to test that memory writes work. Stub-testing against fabricated
> endpoints produces tests that pass today and lie tomorrow when the
> real endpoint differs."

So this doc enumerates each precondition gap (PG-N), with:

- **What's missing** — the endpoint / fixture / wiring that doesn't
  exist
- **Why it blocks E2E** — the specific test that wanted to verify the
  primitive's behaviour
- **Smallest unblocking change** — what would have to land for the
  gap to close
- **Workaround used today** — what unit/integration tests cover
  instead, so the primitive isn't *un*tested, just not E2E-tested

---

## What IS E2E-tested in `agentic-os.spec.ts`

For context, the spec landed alongside this doc covers:

| # | Test | What it proves |
|---|---|---|
| 1 | `/health/ready` reports db + redis healthy | D2 (memory) and D5 (Redis limiter) supporting infra is up |
| 2 | `/health/version` returns build provenance | The Python module graph compiled cleanly (negative signal: a syntax error in any agent module would crash here) |
| 3 | github webhook 401 on invalid sig | D7 signature contract (negative) |
| 4 | github webhook 400 missing `X-GitHub-Event` | D7 input validation |
| 5 | github webhook 400 missing `X-GitHub-Delivery` | D7 input validation (idempotency-key precondition) |
| 6 | stripe webhook 401 on invalid sig | D7 signature contract (negative) |
| 7 | stripe webhook 4xx on missing header | D7 input validation |
| 8 | frontend home page title | UI bootstraps cleanly |

8 tests, all green against the live stack in 3.6s.

**Negative-path coverage on D7 is full.** Positive-path coverage on
every other primitive is blocked by the gaps below.

---

## Precondition gaps

### PG-1 — `_agentic_loader.load_agentic_agents()` is not called from FastAPI startup

**What's missing:** The agentic loader (which imports
`example_learning_coach` so its `@on_event("github.push")` and
`@on_event("stripe.checkout.session.completed")` decorators register
into the in-process subscription registry) is currently called *only*
from `app/core/celery_app.py` boot. FastAPI's startup never calls it.

**Evidence:**

```
$ grep -rn "load_agentic_agents" backend/app/
backend/app/core/celery_app.py:108:    from app.agents._agentic_loader import load_agentic_agents
backend/app/core/celery_app.py:111:    load_agentic_agents()
```

Zero hits in `app/main.py` or any FastAPI startup hook.

**Why it blocks E2E:** Even with valid webhook secrets configured,
posting a valid-signature `push` event to
`/api/v1/webhooks/agentic/github` would receive `subscribers: 0`
back, because the FastAPI process has no agents registered to the
proactive subscription registry. The webhook handler runs, signature
verifies, `route_webhook` is called — and finds an empty registry
because nothing imported `example_learning_coach` in this process.

The webhook contract says "subscribers: N, results: [...]" — which
is observable. We could write `expect(body.subscribers).toBe(1)` —
but it would be `0` against the live stack and pass against future
state. Either way the test would mislead.

**Smallest unblocking change:** Call `load_agentic_agents()` from
FastAPI startup the same way Celery does, OR move the loader to
`app/agents/primitives/__init__.py` so any import of the primitives
package triggers it. Either is ~5 LOC. Trade-off: importing in
`__init__` slows test imports; calling from startup is explicit but
adds another boot-order edge to the FastAPI lifespan.

**Workaround used today:** unit tests in
`backend/tests/test_agents/primitives/test_proactive.py` import the
agent modules directly and exercise `route_webhook` against a real
Postgres test DB. Coverage of the dispatch logic is solid; what's
NOT covered is "the FastAPI process has the same registration state
as the Celery process."

---

### PG-2 — webhook secrets (`github_webhook_secret`, `stripe_webhook_secret`) are unset in dev

**What's missing:** Both env vars are empty in the running container:

```
$ docker exec pae_platform-backend-1 sh -c \
    'echo "github=[$GITHUB_WEBHOOK_SECRET]"; echo "stripe=[$STRIPE_WEBHOOK_SECRET]"'
github=[]
stripe=[]
```

The agentic verifiers (`verify_github_signature`,
`verify_stripe_signature`) treat empty secret as **hard reject** by
design (per D7 spec — see `proactive.py:262-267, 297-302`):

> "An environment that hasn't configured `github_webhook_secret`
> MUST NOT accept GitHub webhooks. The previous webhook handler
> chose the opposite (silently skip verification when the secret
> is empty); that pattern is unsafe for a primitive that lands new
> agent traffic."

**Why it blocks E2E:** Cannot construct a request that passes
signature verification. Negative-path tests are fully covered (the
spec asserts 401 on invalid sig). Positive-path is unreachable
without setting a dev-only secret in `.env`.

**Smallest unblocking change:** Add to backend `.env`:

```
GITHUB_WEBHOOK_SECRET=dev-webhook-secret-not-for-prod
STRIPE_WEBHOOK_SECRET=dev-webhook-secret-not-for-prod
```

The E2E spec then computes the HMAC client-side:

```ts
const secret = "dev-webhook-secret-not-for-prod";  // matches container env
const body = JSON.stringify({...});
const sig = "sha256=" + crypto
  .createHmac("sha256", secret).update(body).digest("hex");
```

Trade-off: a dev-secret in `.env.example` clarifies the contract but
also normalises "secrets in the repo" hygiene. Better: document the
dev-secret pattern in a runbook, leave `.env.example` blank.

**Workaround used today:** `test_proactive.py` constructs valid HMAC
signatures inline using a test-injected secret via Pydantic Settings
override. Not visible to a black-box client, but proves the algorithm
side.

---

### PG-3 — D2 MemoryStore has no HTTP surface

**What's missing:** No public endpoint to write or recall agent memory.
`MemoryStore.write()` and `MemoryStore.recall()` are only callable
from Python — they're invoked from inside an agent's `run()` method.

**Why it blocks E2E:** A test like "POST a chat message → assert a
new row in `agent_memory` referencing the user" requires a chat
endpoint that drives an agentic agent through the memory primitive.
None exists today (PG-5 covers chat).

**Smallest unblocking change:** Either (a) add a debug-only admin
endpoint `POST /admin/agentic/memory` for test fixtures, or (b)
land PG-5 (D8 chat HTTP surface) so memory writes happen as a side
effect of a real flow.

**Workaround used today:** Direct DB inspection in
`backend/tests/test_agents/primitives/test_memory.py`. Covers
correctness; doesn't cover "writes happen during real agent runs."

---

### PG-4 — D3 Tools, D4 Communication, D5 Critic have no HTTP surface

**What's missing:** Same shape as PG-3. `ToolExecutor.execute()`,
`call_agent()`, and `evaluate_with_retry()` are internal Python APIs.
A black-box client cannot:

- ask "execute this tool with these args" (D3)
- ask "have agent A call agent B" (D4)
- ask "run the critic against this result" (D5)

**Why it blocks E2E:** Coverage of "did the limiter reject the 6th
escalation in an hour" requires either a way to fire 6 escalations
through HTTP, or a fixture endpoint that surfaces the limiter's
state. Neither exists.

**Smallest unblocking change:** None worth shipping just for tests.
The right unblock is PG-5 — once a real agent flow runs end-to-end,
each primitive fires as a side effect and is verifiable via DB
inspection.

**Workaround used today:** Unit + integration tests at
`backend/tests/test_agents/primitives/test_{tools,communication,evaluation}.py`.
The Track 2 RedisEscalationLimiter has 25/25 tests including one
that simulates multi-process state.

---

### PG-5 — D8 `example_learning_coach` chat path has no UI route or HTTP endpoint

**What's missing:** `LearningCoach.run(LearningCoachInput, ctx)` is
exposed only as a Python method. The agent IS NOT registered in the
legacy `AGENT_REGISTRY` (it's an `AgenticBaseAgent`, not a
`BaseAgent`), so:

- It does NOT appear in `GET /api/v1/agents/list`
- It cannot be invoked via `POST /api/v1/admin/agents/{name}/trigger`
  (that endpoint hard-codes `_ensure_registered() + get_agent(name)`,
  see `admin.py:875-889`)
- It is not wired to any chat route, MOA classifier, or `/api/v1/agents/chat`
- It has no frontend route invoking it

**Why it blocks E2E:** The most valuable Track 5 test would have been
"open the chat UI, send a message, assert the response cites course
content (D3 tool call) and persists a preference (D2 memory write)."
That flow requires a UI route bound to LearningCoach. Neither the UI
nor the HTTP layer exists.

**Smallest unblocking change:** Two-step.
  1. Add an HTTP endpoint, e.g.
     `POST /api/v1/agentic/learning-coach/chat` that calls
     `LearningCoach().run(...)` directly. Bypasses MOA. ~30 LOC.
  2. Wire a chat route in the v8 frontend that posts to it.
     Larger change — ties to the broader question of "when does
     LearningCoach actually replace socratic_tutor / student_buddy
     in the registry?" (per `example_learning_coach.py` docstring).

Either step alone unblocks E2E (HTTP-only test is fine; UI is bonus).

**Workaround used today:**
`backend/tests/test_agents/primitives/test_example_learning_coach.py`
exercises `run()` directly with a fake Anthropic client. Excellent
unit-level coverage; zero black-box visibility.

---

### PG-6 — D6 proactive cron path has no HTTP trigger

**What's missing:** `@proactive(cron=...)` schedules are dispatched
exclusively by Celery beat. There is no admin "fire this proactive
schedule now" endpoint.

**Why it blocks E2E:** A test like "trigger the nightly check, assert
N students were processed" requires either waiting for the next
cron tick (e.g. `0 9 * * *`) or driving the Celery task directly.
Neither fits a Playwright spec.

**Smallest unblocking change:** Add an admin-only endpoint
`POST /admin/agentic/proactive/{schedule_id}/run` that calls
`dispatch_proactive_run()` directly with synthetic timing. ~20 LOC.

Trade-off: any "fire-now" endpoint is also a way to run prod cron
flows out-of-band. Lock to admin role + audit-log it.

**Workaround used today:** `test_proactive.py` calls
`dispatch_proactive_run()` directly and asserts the return value
shape, idempotency-key collision, etc. Cron *triggering* is not
end-to-end tested anywhere — only the Celery beat config is.

---

### PG-7 — D5 escalation rows have no admin "list recent" endpoint

**What's missing:** `agent_escalations` rows are written by
`should_notify()` but the only way to inspect them today is direct
SQL.

**Why it blocks E2E:** Even if PG-1 + PG-2 + PG-5 land, the assertion
"after 5 escalations the 6th was suppressed" requires reading
`agent_escalations` to count `notified_admin=true` rows per agent.
Direct SQL works inside Python tests; not from a Playwright spec.

**Smallest unblocking change:** Add
`GET /admin/agentic/escalations?agent={name}&since={ts}` returning
recent rows. Trivial repo + route. ~30 LOC.

**Workaround used today:** Test code uses an `AsyncSession` fixture
to query the table directly. See
`test_evaluation.py::test_redis_limiter_shares_state_across_instances`
for the canonical pattern.

---

### PG-8 — `agent_call_chain` has no admin "trace" endpoint

**What's missing:** Same shape as PG-7. The trace-chain rows that
inter-agent calls write are inspectable only via SQL.

**Why it blocks E2E:** The Section-5 invariants in `AGENTIC_OS.md`
(edge-based cycle detection, `execute()` doesn't write chain rows)
are testable only inside Python.

**Smallest unblocking change:** `GET /admin/agentic/trace/{root_id}`
returning the chain rows for one root invocation. Pairs naturally
with PG-7 — both are admin-debug surfaces for the same primitives
layer.

**Workaround used today:**
`backend/tests/test_agents/primitives/test_communication.py` covers
the invariants directly.

---

## Summary of unblocking sequence

If the team wants meaningful E2E coverage of D1–D8 (not just the
negative-path D7 surface), the dependency order is:

```
   PG-1 (fastapi loads agentic agents)  ──┐
                                          ├──► positive-path D7 webhook tests
   PG-2 (dev secrets configured)       ──┘

   PG-5 (D8 chat HTTP endpoint)         ──► chat E2E that exercises
                                            D2 (memory), D3 (tools),
                                            D4 (call_agent) as side
                                            effects

   PG-7 (escalations admin list)        ──┐
                                          ├──► D5 evaluation E2E
   PG-8 (trace admin list)              ──┘

   PG-6 (proactive fire-now endpoint)   ──► D6 cron E2E
```

PG-1 + PG-5 are the highest-leverage. Together they unblock 4 of the
8 gaps; the remaining 4 are admin-surface conveniences.

**Estimated unblock cost:** PG-1 ≈ 5 LOC, PG-2 ≈ env doc + secret,
PG-5 ≈ 30 LOC + frontend wire, PG-6/7/8 ≈ 20–30 LOC each = ~6 hours
of focused work to convert 0% E2E coverage into ~80%.

---

## What this audit deliberately did NOT do

- **Did not fabricate endpoints to test against.** No "the endpoint
  doesn't exist so let's mock it in nginx" workarounds.
- **Did not assert subscribers > 0** in the webhook tests, since
  PG-1 means it would be 0 today and would lie tomorrow.
- **Did not write tests that pass today by coincidence.** Every test
  in `agentic-os.spec.ts` describes a behaviour the system will
  always exhibit (signature contract + health probes), not a state
  that depends on fixtures.
- **Did not auth-test admin endpoints.** That is covered by the
  existing admin smoke spec.

---

## References

- Architecture: `docs/AGENTIC_OS.md` (Section 3 per-primitive APIs;
  Section 5 trace invariants; Section 9 "what this does NOT cover")
- Companion E2E spec: `frontend/e2e/agentic-os.spec.ts`
- Existing E2E suite: `frontend/e2e/production-readiness.spec.ts`
  (PR2/PR3 surfaces) and `frontend/e2e/admin-console-smoke.spec.ts`
- Webhook implementation: `backend/app/api/v1/routes/agentic_webhooks.py`
- Proactive implementation: `backend/app/agents/primitives/proactive.py`
- Loader: `backend/app/agents/_agentic_loader.py`
- Reference agent: `backend/app/agents/example_learning_coach.py`
