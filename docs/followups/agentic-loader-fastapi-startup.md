# P0 — `_agentic_loader` must run on FastAPI startup, not only Celery

**Owner:** _to be assigned at Pass 3h kickoff (or earlier if proactive
flows ship before then)._
**Status:** **OPEN — P0 correctness bug**, masked today, would
manifest the moment any agentic agent registers a `@on_event` webhook
subscription that fires from real production traffic.
**Created:** 2026-05-02
**Triggered by:** Track 5 surface mapping. Promoted from
`docs/audits/agentic-os-precondition-gaps.md` PG-1 ("test gap")
to P0 ("real production bug") at Track 5 sign-off.

## The bug

`backend/app/agents/_agentic_loader.py::load_agentic_agents()` is the
function that imports every agentic agent module so the
`@proactive` and `@on_event` decorators run and populate the
in-process subscription registries
(`backend/app/agents/primitives/proactive.py`).

Today it is called from **exactly one place**:

```
$ grep -rn "load_agentic_agents" backend/app/
backend/app/core/celery_app.py:108:    from app.agents._agentic_loader import load_agentic_agents
backend/app/core/celery_app.py:111:    load_agentic_agents()
```

The Celery worker boot path imports it. **The FastAPI app factory
does not.** That means:

- The Celery worker process has the agentic registry populated.
  Cron-fired proactive flows work.
- The FastAPI process does not. Webhook flows are broken.

## How it manifests

`POST /api/v1/webhooks/agentic/github` is handled by
`receive_github_webhook` in
`backend/app/api/v1/routes/agentic_webhooks.py`. The handler:

1. Verifies the X-Hub-Signature-256 header (works — uses
   `verify_github_signature` from the primitives module which is
   importable independently of agent registration).
2. Calls `route_webhook(session=db, source="github", event_name=...,
   payload=...)`.
3. `route_webhook` reads the in-process subscription registry
   (`_event_subscriptions` dict in `proactive.py`) to find every
   agent subscribed to the event name.

In the FastAPI process, that dict is **empty** — because no agent
module was ever imported here. `route_webhook` returns an empty
results list. The webhook returns:

```json
{
  "event": "github.push",
  "delivery_id": "...",
  "subscribers": 0,
  "results": []
}
```

200 OK. Looks healthy. **Nothing fired.**

## Why it's masked today

1. **No agentic agent currently subscribes to a webhook in production
   traffic.** `example_learning_coach` declares
   `@on_event("github.push", ...)` but no real GitHub repo is
   wired to fire production webhooks against the agentic endpoint
   yet (the legacy `/webhooks/github` route is what receives them
   today, and it dispatches via the legacy `BaseAgent` registry).
2. **Dev secrets are empty.** `github_webhook_secret` and
   `stripe_webhook_secret` are unset, so the positive path is
   never exercised in dev or in CI.
3. **The Celery worker has its own boot path.** Anything dispatched
   through Celery (cron-fired @proactive sweeps, deferred webhook
   processing) runs in a process where the registry IS populated.
   So tests that exercise the Celery path see correct behaviour.

The bug surfaces the moment ALL of these change:
  • A production `@on_event` agent subscription lands
  • Dev/prod webhook secrets get configured
  • A real upstream (GitHub / Stripe) starts firing against the
    agentic endpoint

That's the proactive-flows GA milestone. Pass 3h-ish.

## The fix

Five lines, FastAPI startup hook. In `backend/app/main.py`, add to
the lifespan or a startup event:

```python
from app.agents._agentic_loader import load_agentic_agents

@app.on_event("startup")
async def _load_agentic_agents() -> None:
    # Populate the in-process @on_event / @proactive registries so
    # webhook routing sees subscribers. Celery boots its own copy
    # via app/core/celery_app.py — both processes need this.
    load_agentic_agents()
```

(Use lifespan if `@on_event` is being phased out per FastAPI's
roadmap; same call.)

The function is **idempotent** — it imports modules, and Python's
module cache means a second call is a no-op. Safe to call from both
boot paths.

## The test that proves it

A dedicated unit test in
`backend/tests/test_api/test_agentic_webhooks.py` (or alongside
the existing webhook tests):

```python
async def test_fastapi_process_has_agentic_registry_populated_after_startup(
    fastapi_client, valid_github_signature
):
    # POST a valid-signature webhook; assert subscribers > 0.
    # If this returns 0, _agentic_loader didn't fire on startup.
    resp = await fastapi_client.post(
        "/api/v1/webhooks/agentic/github",
        headers=valid_github_signature("push", body),
        content=body,
    )
    assert resp.status_code == 200
    assert resp.json()["subscribers"] >= 1, (
        "agentic registry empty in FastAPI process — "
        "_agentic_loader did not run on startup"
    )
```

This is one of the few tests where asserting `subscribers >= 1` is
honest: it's the regression test for THIS bug.

## Why this isn't part of Track 5 or any parallel-work track

The parallel-work tracks (1-6) explicitly forbid application-code
changes. This is an application-code change. It belongs in Pass 3h
(or earlier if proactive flows ship first).

## When to revisit

- **Immediately**, if proactive flows are turned on in production
  before Pass 3h lands (because at that point the bug is no longer
  hypothetical — a real webhook will silently no-op).
- **At Pass 3c kickoff**, fold the fix into the agent migration
  playbook so future agentic agents added via the new HTTP surface
  also get registry coverage.
- **At Pass 3h**, definitely. This is the prerequisite for any
  webhook-driven proactive flow to work correctly.

## Done when

- [ ] `load_agentic_agents()` called from FastAPI startup (lifespan
      or `on_event("startup")`)
- [ ] Regression test asserts `subscribers >= 1` for a valid
      webhook delivery in the FastAPI process
- [ ] Resolution noted at the top of this file (don't delete — the
      trail of resolved follow-ups is itself useful per
      `docs/followups/README.md`)

## References

- Track 5 audit: `docs/audits/agentic-os-precondition-gaps.md` §PG-1
  (this follow-up supersedes that finding's classification)
- Track 5 spec: `frontend/e2e/agentic-os.spec.ts` (deliberately does
  NOT assert `subscribers > 0` because this bug exists today)
- Celery boot path with the working call: `app/core/celery_app.py:108-112`
- Loader: `app/agents/_agentic_loader.py`
- Registry consumer: `app/agents/primitives/proactive.py::route_webhook`
- Webhook route: `app/api/v1/routes/agentic_webhooks.py`
