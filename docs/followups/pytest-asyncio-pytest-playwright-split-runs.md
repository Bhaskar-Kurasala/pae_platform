# pytest-asyncio + pytest-playwright sync API coexistence — split runs

**Status:** Open. Operational. CP3-surfaced. Affects how CI and local
developers invoke the playwright suite.
**Origin:** D18 Phase A CP3 (2026-05-08).
**Created:** 2026-05-08.

## What this is

The Playwright suite at `backend/tests/playwright/smoke/` mixes two
test shapes:

1. **Async DB-only smoke** (CP2) — uses `@pytest_asyncio.fixture
   db_session`, no Playwright `page` fixture. pytest-asyncio drives
   its own event loop per test.
2. **Sync browser smoke** (CP3 onward) — uses pytest-playwright's
   sync `page` fixture, which internally creates a greenlet-driven
   loop on top of the asyncio runtime.

Running both in one pytest invocation triggers an event-loop conflict
at teardown:

```
RuntimeError: Cannot run the event loop while another loop is running
```

The error surfaces during `loop.run_until_complete(loop.shutdown_asyncgens())`
of the async DB tests, after the sync Playwright tests have run in
the same session.

Each suite passes cleanly in isolation:
  * `pytest tests/playwright/smoke/test_cp2_db.py` — 4 passed.
  * `pytest tests/playwright/smoke/test_cp3_pages.py` — 6 passed,
    2 xfailed.

## The convention

Run the two shapes as **separate pytest invocations**:

```bash
# DB-only smoke (no browser; no PLAYWRIGHT_BASE_URL needed)
docker compose exec -T backend sh -c \
  "cd /app && uv run pytest tests/playwright/smoke/test_cp2_db.py"

# Browser smoke (needs PLAYWRIGHT_BASE_URL because it's running
# inside the backend container talking to the frontend service)
docker compose exec -T backend sh -c \
  "cd /app && PLAYWRIGHT_BASE_URL=http://frontend:3000 \
   uv run pytest tests/playwright/smoke/test_cp3_pages.py"
```

CI must execute these as two distinct steps. A wrapper script (deferred
to CP6) will hide the split from local developers.

## Why we don't fix this with conftest gymnastics

Tried at CP3 design time:
  * **Function-scoping the async DB engine** (per-test create/dispose).
    Necessary fix in its own right (asyncpg connections bind to the
    creating loop), but doesn't address the session-teardown collision.
  * **`loop_scope="session"` on pytest-asyncio.** Would force a
    single loop, but pytest-playwright's sync API doesn't share that
    loop — it creates its own.
  * **Switching CP3 to async Playwright fixtures.** `pytest-playwright`
    ships both; using the async `page` would align loops. Deferred:
    aligns Phase A CP4 fixture authoring (we'd need to convert the
    auth helper + every page object to async). Not a CP3-scope
    change.

The split-run convention is the industry-standard workaround when
both plugins are installed together. Most production projects that
mix pytest-asyncio + pytest-playwright sync API run them as separate
jobs.

## When to revisit

If CP4 or later cleanly migrates DB-only tests to use `httpx`
backend-driven assertions (no async fixtures at all — the page objects
do all the seeding via the API), the conflict disappears. Or, if Phase
B converges on async Playwright fixtures throughout, that also
resolves it.

Until then: separate invocations.

## CP5 — thread-isolated asyncpg pattern for sync browser fixtures

Some sync browser fixtures need to write to the DB (e.g.,
`admin_browser_context` needs to seed an admin user with role='admin'
since the public /auth/register doesn't allow role promotion).
asyncpg is the only sync-DB driver shipped in the venv, but
calling `asyncio.run()` from the sync fixture's thread fails because
pytest-playwright's sync API has an ambient asyncio loop on the
main thread.

**Pattern: run asyncpg in a fresh thread.** Spawn a thread that has
no ambient loop, call `asyncio.run` inside it, join. Fixture in
`backend/tests/playwright/conftest.py` calls this `_run_async()`
helper. Industry-standard workaround when sync-Playwright + async-DB
work need to coexist within one test.

This pattern is local to CP5's admin fixture; if Phase B needs more
sync-fixture DB writes, factor `_run_async` into a shared helper
(probably `tests/playwright/helpers/sync_async_bridge.py`).

## D19.1 CP1 addendum — don't combine pytestmark anyio with auto-mode

Surfaced 2026-05-09 during D19.1 CP1 closure-time test verification.

The project's `backend/pyproject.toml` sets
`asyncio_mode = "auto"` for pytest-asyncio. That alone drives every
`async def test_*` function. **Async unit-test files must NOT also
add `pytestmark = pytest.mark.anyio`** — both plugins then race for
the same coroutine, producing the same
`Runner.run() cannot be called from a running event loop` error
described above (which is otherwise reserved for the
pytest-asyncio + pytest-playwright collision).

The CP1 test file at `backend/tests/test_core/test_d19_cp1_correlation.py`
shipped with the marker; targeted run alone passed (11/11) because
Playwright fixtures weren't loaded into the session. Running the
combined suite — even with the split-run convention applied — still
crashed because the second pytest-asyncio runner is invoked when
auto-mode collides with the explicit anyio marker.

**Rule:** in the `backend/tests/` tree, async tests get auto-mode
pytest-asyncio for free. Don't add `pytest.mark.anyio` /
`pytestmark = pytest.mark.anyio`. The pre-existing
`tests/test_core/test_request_id.py` carries the marker historically
and works because of small fixture surface, but new files should
follow the canonical pattern. (A CP-equivalent cleanup of
`test_request_id.py` is out of scope until the next test-touch.)

## Cross-references

- `backend/tests/playwright/conftest.py` — function-scoped engine
  fix from CP2.
- `backend/tests/playwright/smoke/test_cp2_db.py` — async DB shape.
- `backend/tests/playwright/smoke/test_cp3_pages.py` — sync browser
  shape.
- `docs/followups/test-suite-bulk-run-oom-by-directory-workaround.md`
  — sibling operational issue (different mechanism, also requires
  splitting test runs).
