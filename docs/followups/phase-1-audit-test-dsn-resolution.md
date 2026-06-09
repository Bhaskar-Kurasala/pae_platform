# Phase 1 audit — TEST_PG_DSN resolution between container and host

**Status:** Open. Triage → low-priority test infra cleanup.
**Created:** 2026-05-08 (D15 CP1 closure → CP2 entry).
**Cross-references:**
- `tests/test_infra/test_sqlite_jsonb_compat.py` (canonical Phase 1 audit pattern)
- `migration-verification-discipline.md` Pattern 22

## What this is

Phase 1 schema audit tests live at `backend/tests/test_infra/` and are
expected to run against the live Postgres container so they verify
deployed schema, not just the SQLAlchemy declaration. The convention
established by `test_sqlite_jsonb_compat.py` is:

1. Read `TEST_PG_DSN` env var.
2. If unset, default to `postgresql+asyncpg://postgres:postgres@localhost:5433/platform`.
3. Probe the DSN with `asyncpg.connect(timeout=2.0)`.
4. Skip the test if probe fails (so CI without DB doesn't break).

This default works only when tests run on the **host** (`localhost:5433`
is the docker-compose published port). When tests run **inside the
backend container** — which is the CP2-CP5 pattern because (a) `tests/`
is not bind-mounted and (b) `uv` lives only in the container venv —
`localhost:5433` resolves to the container's own loopback, where no
Postgres listens. The probe fails and Phase 1 audit tests silently skip.

## How D15 CP1 hit this

D15 CP1's `tests/test_infra/test_role_seed.py` (8 live-DB seed audit
tests) ran inside the container. With no env override, all 8 skipped:

```
tests/test_infra/test_role_seed.py::test_seed_six_roles_with_correct_sequence SKIPPED
… (7 more skipped)
================== 16 passed, 8 skipped, 2 warnings in 5.07s ===================
```

Workaround used: pass `TEST_PG_DSN` explicitly:

```bash
docker exec -e TEST_PG_DSN='postgresql+asyncpg://postgres:postgres@db:5432/platform' \
  pae_platform-backend-1 uv run pytest tests/test_infra/test_role_seed.py -v
```

That made all 8 tests pass.

## The actual problem

Phase 1 audit tests have a `_pg_reachable()` probe that returns False
when DSN is wrong, and the `pytest.mark.skipif` decorator turns failure
into silent skip. **A skipped test reads as success in CI.** If a
contributor relies on the default DSN inside the container, they get
green Phase 1 runs that verified nothing.

Two failure modes:

1. **Local dev:** contributor runs `docker exec … pytest`, sees skipped
   audit tests, assumes "no Postgres reachable" is correct (it isn't —
   `db:5432` is reachable, the default DSN just points at the wrong host).
2. **CI:** depends on whether CI runs tests host-side or container-side
   and whether `TEST_PG_DSN` is in the CI env. Surface during D17.

## Resolution options (defer decision to D17)

Option A — runtime-aware default in `_dsn()`:

```python
def _dsn() -> str:
    if env := os.environ.get("TEST_PG_DSN"):
        return env
    # Container-internal hostname when running inside docker-compose;
    # detect via /.dockerenv, else fall back to host port.
    if os.path.exists("/.dockerenv"):
        return "postgresql+asyncpg://postgres:postgres@db:5432/platform"
    return "postgresql+asyncpg://postgres:postgres@localhost:5433/platform"
```

Pros: zero env-var ergonomics for contributors, both paths just work.
Cons: hardcodes hostnames in two places; surface change if compose
service name renames.

Option B — single env var in `docker-compose.override.yml` for backend
service:

```yaml
services:
  backend:
    environment:
      TEST_PG_DSN: postgresql+asyncpg://postgres:postgres@db:5432/platform
```

Pros: fewer code changes, declarative.
Cons: contributors must use compose for tests; standalone
`docker run pae_platform-backend ...` won't inherit.

Option C — pytest plugin that emits a loud warning when audit tests
skip due to unreachable Postgres, distinguishing "DB not available"
(legitimate skip) from "DSN misconfigured" (failure).

Pros: surfaces the "silent skip on misconfiguration" anti-pattern
properly.
Cons: more code, more moving parts.

Recommendation: Option A. Two-line addition to each Phase 1 audit file,
makes the existing `test_sqlite_jsonb_compat.py` idempotent under both
host- and container-run.

## D15 CP2-CP5 mitigation (no code change needed for D15)

Continue passing `TEST_PG_DSN=...@db:5432/platform` to `docker exec`
calls when running Phase 1 audits. Document in CP2 report.

D17 picks this up and lands the resolution.
