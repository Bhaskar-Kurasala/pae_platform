# `tests/` dir not bind-mounted; `docker compose cp` workaround for test edits

**Status:** Open. Operational. D18 Phase A test infrastructure should
adjust the docker-compose mount.
**Origin:** D17b ITEM 2 closure note (first formally documented; the
issue has been latent across the engagement but only became friction-
heavy when ITEMs 2 + 3 + 4 each added new test files).
**Created:** 2026-05-08 (D17b ITEM 5).

## What this is

`docker-compose.yml` for the `backend` service bind-mounts only
`./backend/app` and `./backend/alembic` (plus `alembic.ini`):

```yaml
backend:
  volumes:
    - ./backend/app:/app/app
    - ./backend/alembic:/app/alembic
    - ./backend/alembic.ini:/app/alembic.ini
```

The `tests/` directory is **baked into the image** via the Dockerfile's
`COPY . .` step, but is NOT bind-mounted. So:

- Edits to `app/` (production code) propagate live into the container
  via the bind mount; pytest sees them on next invocation.
- Edits to `tests/` (test code) **do not propagate**; pytest in the
  container sees the baked-in test files frozen at image-build time.

To exercise edited tests against the live container, the workaround is
**`docker compose cp`** to push fresh files into `/app/tests/` after
each edit:

```bash
docker compose cp backend/tests/test_services/test_X.py \
  backend:/app/tests/test_services/test_X.py
```

## Sub-issue 1 — new test sub-directories require root-mkdir

When a new test sub-directory is needed (e.g., adding
`tests/test_agents/tools/agent_specific/project_evaluator/`), the
container's `appuser` cannot `mkdir` it because:

- The `/app` tree is owned by `appuser`, but the parent dir contents
  were `chown`d in the Dockerfile and post-build dirs need elevated
  privileges to create.
- Plain `docker compose exec -T backend mkdir ...` from `appuser`
  returns "Permission denied".

The fix: `docker compose exec -T --user root backend sh -c
"mkdir -p PATH && chown -R appuser:appuser PATH"`. Then the
subsequent `docker compose cp` calls work because `appuser` owns the
new dir.

## Sub-issue 2 — restart wipes the new sub-directory

Restarting the backend container (`docker compose restart backend`)
wipes any non-bind-mounted writes from the previous container's
filesystem layer. New test sub-directories survive only as long as
the container instance does. Each container restart requires
re-running the mkdir + chown + cp sequence.

This is a non-issue for D17b ITEMs because we ran tests immediately
after copying without restarting. It would surface for any
test-driven workflow that expects test files to persist across
container lifecycle events (e.g., dev session with frequent restarts).

## Operational impact

- **Test development friction** — every `tests/` edit needs a
  `docker compose cp` step. Forgetting it means pytest runs against
  stale baked-in files; the symptom is "my test doesn't seem to
  pick up my latest change" or "the test that I thought I added
  isn't being collected." Multiple instances of this happened
  across D17b ITEMs.
- **New test sub-directory creation** is a 3-step ritual (root mkdir
  + chown + cp), not a single command. Easy to get wrong; the error
  modes (permission denied; MSYS path translation; restart-wipes-it)
  are not obvious to a developer who hasn't hit them before.
- **Pattern 27 (test fixture staleness as code evolves)** — if the
  symbol-under-test changes in `app/` and the test in `tests/` is
  edited to match, the developer who edits both files but only
  copies the `app/` file (because only `tests/` requires the cp
  step) will see the test fail "for no reason" until they realize
  the `tests/` edit didn't propagate.

## Three remediation paths (D18 Phase A)

**Path A — bind-mount `tests/`.** Add `- ./backend/tests:/app/tests`
to docker-compose. Test edits propagate live, no `docker compose
cp` needed. Lowest engineering cost; matches the `app/` mount's
ergonomics. The trade-off: production-image builds need a
`.dockerignore` entry to avoid baking tests in if size matters
(currently fine; tests/ is ~3 MB).

**Path B — per-test-run image rebuild.** Make the docker-compose
test workflow rebuild the backend image before running tests. Slow
(~30s per rebuild) but works without docker-compose changes. Bad
ergonomics for iterative test development.

**Path C — hybrid (bind in dev compose; bake in prod compose).**
Use a docker-compose.override.yml for dev that adds the `tests/`
mount; production compose stays as-is. Most correct; small
configuration surface.

**Recommendation:** Path C in D18 Phase A. Path A is simpler if no
production compose distinction matters yet (probably the case for
this engagement's launch shape).

## Cross-references

- D17b ITEM 2 closure (commit 88e1ddb) — first formal documentation
  of the workaround.
- D17b ITEMs 3, 4 closures — same workaround applied; observed
  consistently across the rest of the engagement.
- `docs/followups/test-suite-bulk-run-oom-by-directory-workaround.md`
  — sibling operational issue; both surface in test-author flow but
  via different mechanisms.
- Sibling: `msys-path-translation-docker-exec-from-git-bash.md` —
  the mkdir command above must be wrapped in `sh -c` from Git Bash
  to avoid MSYS path mangling.
