# Playwright setup — D18 Phase A backend suite

This document covers the Python `pytest-playwright` suite at
`backend/tests/playwright/`. It is the backend-fixture-driven full-stack
journey suite landed in D18.

It is **not** the same as `frontend/e2e/` (TypeScript `@playwright/test`,
frontend-team-owned UI smoke). See **Two-suite world** below.

---

## Two-suite world

| Suite | Path | Owner | What it tests | Stack |
| --- | --- | --- | --- | --- |
| Backend journeys | `backend/tests/playwright/` | Backend / agents | Fixture-seeded full-stack journeys (DB → backend → frontend); real LLM in Phase B | Python · `pytest-playwright` |
| Frontend UI smoke | `frontend/e2e/` | Frontend | UI behavior, route smoke, design contracts | TypeScript · `@playwright/test` |

**Scoping rule for new tests.** If the test starts from a fixture-seeded
DB state and asserts agent behavior or backend persistence, author it in
`backend/tests/playwright/journeys/` (Phase B). If the test exercises
frontend UI behavior or styling, author it in `frontend/e2e/`. When in
doubt, ask: does this test need `seed_*()` from
`backend/tests/fixtures/role_state_fixtures.py`? If yes — backend suite.

---

## Prerequisites

The suite runs against a live docker-compose stack. It does not start
the stack itself.

```bash
# From the repo root
docker compose up -d --build
docker compose exec backend uv run alembic upgrade head

# Verify
curl http://localhost:8080/health        # backend via nginx → {"status":"ok"}
curl -I http://localhost:3002            # frontend (production build)
```

If the stack is down, the CP1 smoke fails with an actionable hint
pointing back to these commands.

### Frontend rebuild gotcha (D-A: production build)

The docker-compose frontend container runs `node server.js` from a Next.js
**standalone production build** — not `pnpm dev`. HMR / file-touch tricks
do not work against the container. After any frontend change you must
rebuild and restart before the new code is served:

```bash
docker compose build frontend && docker compose up -d frontend
```

Playwright tests hit the container; a green run after a frontend code
change without a rebuild is testing the **previous** bundle.

This is the same gotcha documented in `frontend/CLAUDE.md`. D-A
(production build, not dev server) is therefore **inherent** at the
docker-compose level — no special override file is needed for D18 Phase A
beyond a possible `DATABASE_URL` override in CP6.

If you need true HMR for frontend debugging, run `pnpm dev` on host
port 3000 and point the suite at it:

```bash
PLAYWRIGHT_BASE_URL=http://localhost:3000 uv run pytest tests/playwright/smoke/
```

---

## Install (one-time)

### Python deps

```bash
cd backend
uv sync                       # picks up pytest-playwright + playwright from pyproject.toml
```

### Browser binary

`playwright install chromium` downloads the chromium browser. Choose one
of the two workflows below:

**Host workflow.** Browser binaries land in your user cache (`~/.cache/ms-playwright`
on Linux / macOS, `%LOCALAPPDATA%\ms-playwright` on Windows).

```bash
cd backend
uv run playwright install chromium
```

**Container workflow.** If you want the suite to run inside a container
(matching CI), the chromium binary needs to live inside the container,
and so do the browser system libs (libglib, libnss, libcups, etc.).

The current `pae_platform-backend-1` image ships with neither. A one-shot
fix (not durable across rebuilds) is:

```bash
docker exec pae_platform-backend-1 sh -c "cd /app && uv run playwright install chromium"
docker exec --user root pae_platform-backend-1 sh -c "cd /app && uv run playwright install-deps chromium"
```

This is what CP1 used to verify the smoke in-container.

**Durable fix is a CP6 deliverable** — see
`docs/followups/playwright-browser-system-deps-in-backend-container.md`.
CP6 ships `docker-compose.playwright.yml` with a dedicated
`playwright-runner` service based on the official Microsoft Playwright
Python image (browser + libs pre-installed and version-locked).

Firefox and WebKit are deferred to post-launch unless Phase C surfaces
a specific need.

---

## Run

### Local — host workflow against docker stack

```bash
cd backend
uv run pytest tests/playwright/smoke/ -v
```

Default base URL is `http://localhost:3002` (the docker-compose frontend's
host port mapping per `README.md` and `frontend/CLAUDE.md`). Override:

```bash
# pnpm dev workflow on host port 3000
PLAYWRIGHT_BASE_URL=http://localhost:3000 uv run pytest tests/playwright/smoke/

# In-container CI (when CP6 ships docker-compose.playwright.yml)
PLAYWRIGHT_BASE_URL=http://frontend:3000 uv run pytest tests/playwright/smoke/
```

### Headed mode for debugging

```bash
uv run pytest tests/playwright/smoke/ --headed --slowmo 500
```

### Single test

```bash
uv run pytest tests/playwright/smoke/test_cp1_smoke.py -v
```

---

## Configuration

Defaults are set in `backend/tests/playwright/conftest.py`:

| Setting | Default | How to override |
| --- | --- | --- |
| Browser | chromium | `--browser firefox` (post-launch) |
| Headless | true | `--headed` |
| Viewport | 1920×1080 | edit `DEFAULT_VIEWPORT` (post-launch) |
| Base URL | `http://localhost:3002` | `PLAYWRIGHT_BASE_URL` env |
| Default action timeout | 30 s | `page.set_default_timeout(...)` per test |

Per-action timeout buffers for slow agents (per
`docs/followups/study-planner-career-coach-tail-latency-baseline.md`):

| Surface | Suggested timeout |
| --- | --- |
| Standard pages | 15 s (reduce from default if you want fail-fast) |
| `study_planner` agent | 30 s + buffer |
| `career_coach` agent | 150 s + buffer |

These come into play in CP3+ when page objects invoke agents.

---

## Operational gotchas

### 1. MSYS path translation (Windows + Git Bash)

Per `docs/followups/msys-path-translation-docker-exec-from-git-bash.md`,
running `docker exec backend pytest /app/tests/...` from Git Bash on
Windows triggers MSYS path translation that mangles the `/app/...` path.
Workaround: wrap in `sh -c '...'` so MSYS skips the rewrite:

```bash
docker compose exec backend sh -c 'cd /app && uv run pytest tests/playwright/smoke/ -v'
```

PowerShell and WSL bash do not have this problem.

### 2. Tests directory not bind-mounted into container

Per `docs/followups/tests-dir-not-bind-mounted-docker-cp-workaround.md`,
the default `docker-compose.yml` does not bind-mount `backend/tests/`
into the backend container, so newly authored Playwright tests are not
visible to in-container `pytest` runs without an image rebuild.

**Local workflow** (CP1 default): run `uv run pytest tests/playwright/...`
from the host. The host has the tests directly. No bind-mount needed.

**In-container workflow** (CP6 / CI): CP6 ships
`docker-compose.playwright.yml` that mounts `./backend/tests:/app/tests`
so fresh tests are picked up without a rebuild.

### 3. Bulk-suite OOM

Per `docs/followups/test-suite-bulk-run-oom-by-directory-workaround.md`,
running the entire backend test suite in a single pytest invocation
exhausts container memory. CP6's CI configuration splits tests by file
group across 4-6 parallel jobs to handle this. For local Playwright
runs, target specific directories:

```bash
uv run pytest tests/playwright/smoke/      # CP-level smoke
uv run pytest tests/playwright/journeys/   # Phase B journeys (when authored)
```

### 4. Tail-latency baseline

Per `docs/followups/study-planner-career-coach-tail-latency-baseline.md`,
`career_coach` and `study_planner` have non-trivial p95 tail latency
because of MiniMax LLM behavior. Page objects invoking these agents must
set per-action timeouts above the baseline (see config table above).

---

## First-run smoke

After install + stack-up:

```bash
cd backend
uv run pytest tests/playwright/smoke/test_cp1_smoke.py -v
```

Expected output:

```
tests/playwright/smoke/test_cp1_smoke.py::test_can_open_login_page PASSED
```

If the smoke fails, the assertion message points to the most likely
cause (stack down → `docker compose up`; chromium missing → `playwright
install chromium`; selectors absent → frontend route changed, surface
to the team).

---

## What CP2-CP6 will add

- **CP2** — `db/` template database + per-suite reset; `db_session` fixture ✅
- **CP3** — `pages/` page object models for 8 surfaces ✅
- **CP4** — `fixtures/` extending `role_state_fixtures.py` with admin /
  payment / submission / outreach / journey fixtures
- **CP5** — `helpers/` traceability + grounding + behavior-shape + budget
  assertion utilities
- **CP6** — `scripts/build_and_serve.sh`, `docker-compose.playwright.yml`,
  CI config, final end-to-end smoke

Each CP lands its own smoke tests under `smoke/` so the infrastructure
verifies itself.

---

## CP3 — Page objects + selector conventions (2026-05-08)

### Selector convention (Path C)

Page objects in `backend/tests/playwright/pages/` follow these rules,
ratified at CP3:

1. **Role-first.** Use Playwright's `get_by_role`, `get_by_label`,
   `get_by_text`. Mirrors the existing `frontend/e2e/` TS suite.
2. **`data-testid` only where role-based selection is genuinely
   insufficient** — state-driven elements with no accessible name,
   dynamic disambiguation across siblings of the same role, badges
   that share a parent role.
3. **If a page object needs a testid the frontend doesn't have:**
   - Trivial 1-line addition: add inline as part of the same commit
     as the page object.
   - Non-trivial (refactor / prop threading / conditional rendering):
     register at `docs/followups/frontend-testid-additions-d18.md`.

Per-page selector strategy is documented in each page object's module
docstring. Phase B authors should read the docstring before writing
new tests.

### CP3 inline frontend testid additions

Five 1-line additions landed in the CP3 commit:

| File | Element | Testid |
|---|---|---|
| `frontend/src/components/v8/screens/today-screen.tsx:594` | capstone teaser `<section>` | `today-capstone-trailer` |
| `frontend/src/components/v8/screens/today-screen.tsx:418` | step card "warmup" | `today-step-warmup` |
| `frontend/src/components/v8/screens/today-screen.tsx:441` | step card "lesson" | `today-step-lesson` |
| `frontend/src/components/v8/screens/today-screen.tsx:465` | step card "reflect" | `today-step-reflect` |
| `frontend/src/app/(portal)/interview/page.tsx:57` | VerdictBadge `<span>` | `interview-verdict-badge` |

### Async DB engine scoping (CP2 → CP3 carryover)

`db_session` is **function-scoped, not session-scoped**. The async
engine is created and disposed per test. Reason: asyncpg connections
bind to the event loop that created them, and pytest-asyncio uses
function-scoped event loops by default. A session-scoped engine would
fail with "another operation is in progress" / "Event loop is closed"
on the second test in a run. Phase B authors must NOT migrate to
session-scoped engines without first changing pytest-asyncio's
loop_scope.

### Run convention — split DB-only and browser smoke

pytest-asyncio (used by `db_session`) and pytest-playwright's sync API
(used by the `page` fixture) cannot share an event loop. Running
`tests/playwright/smoke/` in one pytest invocation triggers
`RuntimeError: Cannot run the event loop while another loop is
running` at teardown. Run them as **two separate pytest invocations**:

```bash
# DB-only smoke
docker compose exec -T backend sh -c \
  "cd /app && uv run pytest tests/playwright/smoke/test_cp2_db.py"

# Browser smoke
docker compose exec -T backend sh -c \
  "cd /app && PLAYWRIGHT_BASE_URL=http://frontend:3000 \
   uv run pytest tests/playwright/smoke/test_cp3_pages.py"
```

Each suite passes cleanly in isolation. CI runs them as separate
steps. Full background at
`docs/followups/pytest-asyncio-pytest-playwright-split-runs.md`.

### CP3 auth helper — temporary

`backend/tests/playwright/pages/_helpers.py` provides
`login_as_student(page)` and `login_as_admin(page)`. Both are flagged
as **CP4 supersedes**. The admin helper currently fails (admin user
not seeded by the playwright_test template); CP3 admin smoke tests
are marked `xfail` to surface the gap until CP4's admin fixture
ships.
