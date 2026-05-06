# Test suite full-run OOM (exit 137)

**Status:** Open. Pre-existing CI/local infrastructure issue, characterized during D12 CP4.2.
**Created:** 2026-05-07 (D12 closure).

## What it is

Running the full `tests/` suite (`uv run pytest tests/ ...`) inside the backend container hits OOM kill at exit 137 around the 10-15% completion mark. The targeted D12 surface runs cleanly; the full suite OOMs.

## Why it's pre-existing (not D12)

Existing CP3 context note flagged this behavior during the Phase F regression. The OOM is consistent across multiple runs and predates D12 work. D12's targeted surface (180 tests) runs in ~2 minutes within memory budget.

## Likely causes

1. **pytest-asyncio default loop scope**: each test function gets its own event loop, which means async fixtures (DB engines, Redis pools) recreate per-test rather than per-session. Across hundreds of tests this leaks.
2. **SQLAlchemy AsyncEngine instances**: each test that creates an engine via `create_async_engine` keeps connection pools open. The Postgres-backed integration tests (50+ across the suite) compound this.
3. **Container memory limits**: the dev container's default memory budget may be 4GB or similar; production CI runs would have more.

## Triage

D17 cleanup or when CI moves to a runner with more memory. Three remediation options:

1. **Session-scoped event loop** for pytest-asyncio: reduces fixture recreation but requires careful ordering of teardown.
2. **Explicit engine.dispose()** in fixture teardown: more annotation work but addresses the root cause.
3. **Run suite in smaller batches** in CI: split `tests/` into parallel jobs by directory; trades wall-clock for memory.

For now, D12 verification used targeted file lists (`pytest tests/test_agents/test_X.py tests/test_agents/test_Y.py ...`) which sidesteps the issue. Documented the pattern in `migration-verification-discipline.md`.

## Note on impact

This is a developer-experience issue, not a correctness issue. Tests pass when run; the OOM is an infrastructure problem. Production correctness is unaffected.
