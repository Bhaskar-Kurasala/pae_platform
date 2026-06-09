# `uv sync --group dev` silently skips playwright in this project

**Status:** Open. Workaround in place
(`uv pip install` for the affected packages); root cause unknown.
**Origin:** D18 Phase A retrofit (Path A pre-CP1 verification),
2026-05-08. Investigated for ~30 minutes during retrofit; root
cause not identified, workaround chosen for unblocking.

## What this is

In this project, `uv sync --group dev --frozen` reports
"Resolved 169 packages" but only installs 166. The three packages
silently skipped from the dev group are:

  * `playwright>=1.55.0`
  * `pytest-playwright>=0.7.1`
  * `pytest-base-url` (transitive of pytest-playwright)

Other dev-group packages (`pytest`, `mypy`, `ruff`, `httpx`,
`types-redis`, etc.) install correctly.

The same packages install cleanly via `uv pip install`:

```bash
uv pip install --python /app/.venv/bin/python \
    "playwright>=1.55.0" \
    "pytest-playwright>=0.7.1"
```

Verified: post-`uv pip install`, `python -c "import playwright"`
works; tests run.

## What's verified

  * `pyproject.toml` `[dependency-groups] dev` declares all three
    packages with floor-version specifiers.
  * `uv.lock` contains the lockfile entries for all three under
    `[package.dev-dependencies] dev` AND
    `[package.metadata.requires-dev] dev`.
  * `uv tree --group dev` does NOT show playwright (despite the
    package being in pyproject + lockfile).
  * `uv sync --group dev --reinstall` reinstalls 166 packages but
    not playwright/pytest-playwright/pytest-base-url.
  * `uv sync --group dev --reinstall-package playwright` reports
    "Checked" but no install action.
  * `uv export --group dev` does NOT emit playwright in the export
    output.

uv version at the time: `uv 0.11.8 (x86_64-unknown-linux-musl)`.
Python: 3.12. Image:
`mcr.microsoft.com/playwright/python:v1.59.0` AND
`python:3.12-slim` (backend image) — both reproduce.

## What's not yet investigated

  * Is this a uv bug specific to a marker / tag combination on the
    playwright wheel that uv's resolver doesn't understand? The
    playwright lockfile entry has 8 wheels (Linux x86_64, Linux
    aarch64, macOS, Windows variants); none have explicit markers
    that would obviously exclude `linux_x86_64 + python3.12`.
  * Does `uv sync` on a clean checkout (no prior `.venv`) reproduce?
    Investigation was on a venv that had already been partially
    populated; possible the issue is interaction with that state.
  * Does this reproduce on uv ≥ 0.12 / a newer release line? uv's
    dependency-groups handling has had multiple bug-fix releases
    over 2026.
  * Does the project's lockfile have stale dependency-groups
    metadata from an earlier `[tool.uv.dev-dependencies]` migration?
    The lockfile uses both `[package.dev-dependencies]` and
    `[package.metadata.requires-dev]` schemas — possibly they
    diverged at some point.

## Workaround in use

`backend/tests/playwright/Dockerfile.runner` installs the dev-group
packages via explicit `uv pip install` instead of relying on
`uv sync --group dev`:

```dockerfile
RUN uv pip install --python /app/.venv/bin/python \
    "playwright>=1.55.0" \
    "pytest>=9.0.3" \
    "pytest-asyncio>=1.3.0" \
    "pytest-playwright>=0.7.1" \
    "pytest-cov>=7.1.0" \
    "httpx>=0.28.1"
```

Loses the strict-lockfile guarantee that `--frozen` provides for
these specific packages, but the version floors in pyproject.toml
are tight enough that the practical version drift is small.

## When to revisit

  * If a uv release ≥ 0.12.x changes the resolution behavior, retry
    `uv sync --group dev --frozen` against this project — may be a
    fixed bug.
  * If the project regenerates its lockfile from a clean state
    (e.g., `rm uv.lock && uv lock`), check whether the regenerated
    lockfile also exhibits the issue.
  * Before adding new dev-group packages, verify they install via
    `uv sync --group dev`; if not, append to the explicit
    `uv pip install` list in `Dockerfile.runner`.

## Cross-references

  * `backend/tests/playwright/Dockerfile.runner` — the workaround.
  * D18 Phase A retrofit commit (immediately follows this doc) —
    the retrofit work that surfaced this and worked around it.
