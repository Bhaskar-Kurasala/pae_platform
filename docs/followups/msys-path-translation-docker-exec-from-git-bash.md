# MSYS path translation mangles `docker compose exec` paths from Git Bash

**Status:** Open. Operational. D18 Phase A Playwright test infrastructure
running on Windows hosts must guard against this.
**Origin:** D17b ITEM 2 closure note (mkdir failures during new-test-
sub-directory creation).
**Created:** 2026-05-08 (D17b ITEM 5).

## What this is

When `docker compose exec` is invoked from **Git Bash on Windows**
(MSYS2 / mingw64 environment), MSYS path translation rewrites any
argument that **looks like a Unix path** (starts with `/`) into a
Windows-prefixed equivalent before passing it to `docker.exe`.

The invocation:

```bash
docker compose exec -T backend mkdir -p /app/tests/test_agents/tools/.../project_evaluator
```

…is rewritten by MSYS to:

```
docker.exe ... mkdir -p C:/Program Files/Git/app/tests/test_agents/tools/.../project_evaluator
```

…before reaching the docker daemon. The container then dutifully
creates `/app/C:/Program Files/Git/app/tests/test_agents/tools/.../project_evaluator`
inside its filesystem (literally — that's a real path with `C:` as a
directory name). Subsequent `docker compose cp` calls to the intended
`/app/tests/...` target then fail with "could not find the file" because
the dir doesn't exist at the path the cp call asks for.

D17b ITEM 2 surfaced this when ITEM 2.A's new test directory creation
silently went to the wrong path; pytest collection then found 0 new
tests + the cp errors confused the issue further.

## Workaround

Wrap the path-bearing command in `sh -c '...'` so MSYS sees only the
sh invocation (no Unix-path-looking args at the docker exec layer):

```bash
docker compose exec -T --user root backend sh -c \
  "mkdir -p /app/tests/test_agents/tools/agent_specific/project_evaluator && \
   chown -R appuser:appuser /app/tests/test_agents/tools/agent_specific/project_evaluator"
```

The `/app/...` paths are inside the single-quoted sh script; MSYS
doesn't translate them because they're string contents, not docker
args.

Alternatively, use **PowerShell** (not Git Bash) for docker exec
invocations — PowerShell doesn't have MSYS in its path-handling
pipeline. Most D17b commands ran fine from PowerShell; the few that
went through Git Bash with raw Unix paths hit the translation issue.

## Operational impact

- **Test development on Windows hosts** — every `docker compose exec`
  with a `/app/...` path argument is at risk. Forgetting the `sh -c`
  wrap creates dirs at silent-wrong paths; subsequent operations
  on the intended path fail confusingly.
- **D18 Playwright tests on Windows hosts** — Playwright test
  scripts that invoke `docker compose exec` (e.g., to seed test data
  or trigger Celery tasks) must wrap path-bearing commands. Failure
  is silent until something downstream tries to read/write the
  intended path.
- **CI** — if CI runs on Linux (typical), this issue doesn't fire;
  MSYS only exists in the Windows Git-bundled bash. Cross-platform
  scripts must still defend against it for developer-machine usage.

## Three remediation paths

**Path A — defensive wrapping convention.** Document the `sh -c`
wrap as the canonical pattern in any project README / contributing
guide that mentions `docker compose exec`. Cheapest; relies on
discipline.

**Path B — PowerShell-first invocation.** Standardize on PowerShell
for docker exec from Windows hosts; document the choice. Removes
the MSYS issue but introduces shell-syntax inconsistency between
Linux + macOS (bash) and Windows (PowerShell) developer flows.

**Path C — environment variable opt-out.** Set `MSYS_NO_PATHCONV=1`
in the developer's shell environment when invoking docker. MSYS
respects this and skips path translation. Requires per-developer
shell config; one-line fix in `~/.bashrc` but not discoverable.

**Recommendation:** Path A as the documented convention; Path C as
an opt-in for developers who hit the issue often. Path B is
heavier-weight; only justified if the team standardizes on
PowerShell for other reasons.

## Cross-references

- D17b ITEM 2 closure (commit 88e1ddb) — first surfaced + worked
  around in the engagement. The misplaced `/app/C:/Program Files/
  Git/app/tests/...` directory persisted across container restarts
  in the dev container until manually cleaned.
- Sibling: `tests-dir-not-bind-mounted-docker-cp-workaround.md` —
  the new-test-sub-directory mkdir use case where this issue
  surfaced.
- Microsoft / MSYS2 docs on path conversion:
  https://www.msys2.org/wiki/Porting/#filesystem-namespaces (the
  underlying behavior; the env var to disable it is documented
  there).
