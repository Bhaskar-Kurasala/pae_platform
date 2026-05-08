# D18 Phase A — Test infrastructure overview

**Status:** Phase A complete (2026-05-08). Phase B (journey tests
authored against this infrastructure) begins on a separate prompt
cycle.

This document is the load-bearing reference for any author writing
journey tests against the Playwright suite. Read this before writing
new tests; if a question isn't answered here, look in the linked
follow-up docs or open the source.

---

## What Phase A shipped

Six checkpoints, ratified at commits:

| CP  | Commit    | What landed                                    |
|-----|-----------|------------------------------------------------|
| CP1 | 84c9835   | Playwright + pytest-playwright setup           |
| CP2 | b220182   | Test database infrastructure + 3 forward-fixed migrations |
| CP3 | 8c7587b   | 8 page object models + selector conventions   |
| CP4 | 47bdb59   | Fixture library extensions                     |
| CP5 | c5a46c8   | Assertion helpers + budget tracker + admin auth supersession |
| CP6 | (this commit) | Production build pipeline + CI + final smoke |

---

## Suite layout

```
backend/tests/
├── fixtures/
│   ├── role_state_fixtures.py     # 12 D15+D17b student seeders
│   │                              # + 5 CP4 primitive seeders (admin/payment/
│   │                              #   capstone/passing-mock/outreach)
│   ├── journey_fixtures.py        # 6 CP4 composite scenarios
│   ├── admin_fixtures.py          # CP4 admin auth fixtures
│   ├── cleanup.py                 # cleanup_student_data + FK CASCADE map
│   └── runtime_grounding_verifier.py  # D15 CP3 verifier (CP5 wraps)
└── playwright/
    ├── conftest.py                # session reset + db_session +
    │                              # python_developer_student / etc /
    │                              # admin_browser_context / budget_tracker
    ├── pages/                     # CP3 page objects
    │   ├── base_page.py
    │   ├── login_page.py
    │   ├── today_page.py
    │   ├── admin_cockpit_page.py
    │   ├── student_detail_panel.py
    │   ├── catalog_page.py
    │   ├── lesson_page.py
    │   ├── mock_interview_page.py
    │   ├── chat_page.py
    │   └── _helpers.py            # legacy login_as_student (login_as_admin
    │                              #   retired at CP5)
    ├── helpers/                   # CP5 assertion helpers
    │   ├── traceability_assertions.py
    │   ├── grounding_assertions.py
    │   ├── behavior_shape_assertions.py
    │   └── cost_budget.py
    ├── db/
    │   ├── create_template.py     # build playwright_test_template (CP2)
    │   └── reset_for_suite.py     # clone playwright_test (CP2)
    ├── scripts/
    │   └── build_and_serve.sh     # end-to-end orchestrator (CP6)
    └── smoke/                     # one file per CP
        ├── test_cp2_db.py         # 4 tests (template seeded shape)
        ├── test_cp3_pages.py      # 8 tests (page objects work)
        ├── test_cp4_fixtures.py   # 15 tests (fixtures + cleanup)
        ├── test_cp5_helpers.py    # 21 tests (assertion helpers)
        └── test_cp6_full_loop.py  # 2 tests (full stack login flow)
```

Plus at repo root:
- `docker-compose.playwright.yml` — overlay routing backend onto
  `playwright_test` + adding the `playwright-runner` service
- `.github/workflows/playwright-tests.yml` — CI definition

---

## Page object catalog (8 surfaces)

| Page                  | Selector strategy                       | CP3 inline testid additions                 |
|-----------------------|-----------------------------------------|---------------------------------------------|
| LoginPage             | role-first (label + button name)        | none                                        |
| TodayPage             | role-first + 4 testids                  | today-capstone-trailer, today-step-{warmup,lesson,reflect} |
| AdminCockpitPage      | role-first (`Admin home` aria-label, etc.) | none                                     |
| StudentDetailPanel    | role-first (Select aria-label, options) | none                                        |
| CatalogPage           | role-first (h1 + role=link)             | none                                        |
| LessonPage            | role-first (button name + href)         | none                                        |
| MockInterviewPage     | role-first + 1 testid                   | interview-verdict-badge                     |
| ChatPage              | testid-dominant (most instrumented surface) | none (frontend has 16+ pre-existing)    |

**Selector convention (Path C, ratified at CP3):** role-first; testid
only where role-based selection is genuinely insufficient. If a page
object needs a testid the frontend doesn't have, trivial 1-line
additions land inline; non-trivial additions go to
`docs/followups/frontend-testid-additions-d18.md`.

---

## Fixture catalog (25 total)

### D15+D17b origin (12)
seed_python_developer_fresh, seed_mid_progression_data_scientist,
seed_data_analyst_with_entitlement, seed_python_developer_with_curated_bank,
seed_ml_engineer_with_capstone_submission, seed_ml_engineer_for_gate_prep,
seed_returning_after_absence_data_analyst, seed_just_passed_mock_data_scientist,
seed_just_cleared_gate_data_analyst, seed_healthy_data_analyst,
seed_stalled_data_analyst, seed_momentum_data_analyst.

### CP4 primitive seeders (5)
seed_admin_user, seed_payment_intent, seed_capstone_submission,
seed_passing_mock_session, seed_outreach_log_entry.

### CP4 composite journey fixtures (6)
seed_full_journey_through_data_analyst, seed_paid_silent_at_risk_student,
seed_capstone_stalled_student, seed_streak_broken_student,
seed_promotion_avoidant_student, seed_cold_signup_student.

### CP4 admin fixtures (2)
seed_admin_user_with_login, seed_admin_with_outreach_history.

### Pytest fixtures wired in conftest.py
python_developer_student, admin_user_with_login, paid_silent_student,
capstone_stalled_student, journey_through_data_analyst,
admin_browser_context (CP5), budget_tracker (CP5).

**Convention:** seed helpers don't commit; the pytest fixture wrapper
controls transactions. Cleanup goes through `cleanup_student_data()`
which runs DELETEs in the documented FK order (children → users).

---

## Assertion helper catalog (4 modules)

### traceability_assertions
`assert_outreach_log_entry`, `assert_agent_action_logged`,
`assert_student_message_thread`, `assert_student_note_count`.

### grounding_assertions
`assert_no_runtime_grounding_violation` (explicit titles),
`assert_no_runtime_grounding_violation_db` (DB-derived). Wraps D15.

### behavior_shape_assertions
`assert_response_contains_intent`, `assert_response_role_appropriate`,
`assert_no_sycophancy` (5 phrases), `assert_no_fabricated_urgency`
(5 phrases). Conservative blocklists with per-phrase calibration
notes inline.

### cost_budget
`TestBudgetTracker.query_test_cost(...)` /
`record_test_cost(...)`, `BudgetExceeded`. Session fixture
`budget_tracker`. Default ₹2.00 ceiling; override via
`PLAYWRIGHT_BUDGET_INR`.

---

## Run conventions

### Split-run discipline (CP3-surfaced)

pytest-asyncio (CP2/CP4/CP5 async fixtures) and pytest-playwright's
sync API cannot share an event loop. Run as two pytest invocations:

```bash
# Async DB-only
docker compose exec -T backend sh -c \
  "cd /app && uv run pytest \
     tests/playwright/smoke/test_cp2_db.py \
     tests/playwright/smoke/test_cp4_fixtures.py \
     tests/playwright/smoke/test_cp5_helpers.py"

# Sync browser
docker compose exec -T backend sh -c \
  "cd /app && PLAYWRIGHT_BASE_URL=http://frontend:3000 uv run pytest \
     tests/playwright/smoke/test_cp3_pages.py \
     tests/playwright/smoke/test_cp6_full_loop.py"
```

CI in `.github/workflows/playwright-tests.yml` runs them as two
separate jobs (also handles the bulk-suite-OOM workaround).

### Frontend rebuild ritual

The frontend container runs the production build, NOT `pnpm dev`. Any
frontend code change requires `docker compose build frontend && docker
compose up -d frontend` before browser tests will see the change.
`build_and_serve.sh --rebuild` does this; CI always passes `--rebuild`.

### tests/ directory bind-mount

Resolved at CP6 in `docker-compose.playwright.yml` — the playwright-
runner service mounts `./backend:/app`, including `tests/`. The base
`docker-compose.yml`'s backend service still doesn't mount tests/
(CP1 follow-up); to test code edits in dev without the overlay, use
`docker compose cp` per the workaround in
`docs/followups/tests-dir-not-bind-mounted-docker-cp-workaround.md`.

---

## Topology invariants

### `PLAYWRIGHT_BACKEND_DB`

Any fixture that creates state via the backend's HTTP path
(`admin_browser_context` is the canonical example) writes to the
backend's connected DB. With the `docker-compose.playwright.yml`
overlay, that's `playwright_test` (the overlay forces both
`POSTGRES_DB` and `DATABASE_URL`). Without the overlay, the dev
backend talks to `platform`. CP4 introduced the `PLAYWRIGHT_BACKEND_DB`
env var as a fallback override.

**Rule for fixture authors:** any fixture that registers via HTTP
or queries via the backend's pool MUST run under the overlay (or
explicitly set `PLAYWRIGHT_BACKEND_DB`). Direct asyncpg fixtures (the
`db_session` path) target `playwright_test` regardless.

### `PLAYWRIGHT_FULL_LOOP_OK`

The CP6 final smoke (`test_cp6_full_loop.py`) requires the chromium-
loaded frontend bundle to reach the backend. The frontend build bakes
in `NEXT_PUBLIC_API_URL` at build time; for in-network test runs that
URL must be reachable from chromium. The smoke auto-skips unless
`PLAYWRIGHT_FULL_LOOP_OK=1` is set explicitly OR
`PLAYWRIGHT_BASE_URL` is a localhost variant (host-side execution).
The overlay + CI workflow set this var to opt in.

---

## Runner overlay end-to-end verification (post-CP6 retrofit, 2026-05-08)

CP6 ratified the `playwright-runner` service in
`docker-compose.playwright.yml` but never executed it end-to-end —
the upstream image was pulled and verified pullable, never invoked
against the live stack. Phase B's pre-CP1 verification (Path A) was
the first end-to-end run, and surfaced four layered gaps that are
now resolved:

| Gap                                                   | Fix |
|-------------------------------------------------------|-----|
| Upstream runner image has no pytest / project deps    | `backend/tests/playwright/Dockerfile.runner` extends the upstream image with `uv sync --frozen` (prod deps) + `uv pip install` (dev deps via uv-quirk workaround) |
| Frontend bundle bakes `localhost:8080` API URL        | Overlay rebuilds frontend with `NEXT_PUBLIC_API_URL=http://nginx`; pinning pnpm@10.5.0 was a prerequisite to enable the rebuild (`fix(frontend)` commit `d6b2374`) |
| Bind mount `./backend:/app` shadowed runner `.venv`   | Narrowed mount to `./backend/tests:/app/tests` only; runner's baked `.venv` survives |
| Same-origin policy blocked browser→`http://nginx` API | `PLAYWRIGHT_BASE_URL=http://nginx` (was `http://frontend:3000`); page + API now share origin |

After all four fixes, the full Phase A baseline runs cleanly through
the runner overlay:

  * `test_cp2_db.py` — 4 passed (DB-only)
  * `test_cp3_pages.py` — 8 passed (browser, page objects)
  * `test_cp4_fixtures.py` — 15 passed (DB-only)
  * `test_cp5_helpers.py` — 21 passed (DB-only)
  * `test_cp6_full_loop.py` — **2 passed** (was auto-skipping at
    CP6 close; first end-to-end pass at retrofit verification)

Total: **50 passed, 0 skipped, 0 failures.**

### Build + run commands (canonical)

```bash
# One-time per host (or after pyproject.toml/uv.lock changes):
docker compose -f docker-compose.yml -f docker-compose.playwright.yml \
    --profile playwright build playwright-runner
docker compose -f docker-compose.yml -f docker-compose.playwright.yml \
    build frontend

# Bring up stack against playwright_test:
docker compose -f docker-compose.yml -f docker-compose.playwright.yml \
    up -d backend frontend nginx

# Run any test suite via the runner:
docker compose -f docker-compose.yml -f docker-compose.playwright.yml \
    --profile playwright run --rm playwright-runner \
    "pytest tests/playwright/smoke/test_cp6_full_loop.py -v"
```

`build_and_serve.sh` automates the first three commands (with
`--rebuild` always rebuilding both frontend AND runner). CI runs
this script before the test step.

### Pattern 29 evidence base extends

Phase A close had two Pattern 29 instances on the catalog
(admin_console_*, runner overlay scaffolding). Path A's verification
extends to a third: scaffolded-but-pullable is not the same as
ready-and-executed. The runner image being pullable from CP6 close
was misread as "infrastructure ready"; the four-layer gap surfaced
only on first invocation. Canonical statement strengthens to:
**infrastructure is ready when its happy-path smoke has been executed
end-to-end at least once, not when its components have been
authored.**

---

## Three-layer admin auth pattern (CP5)

The `admin_browser_context` fixture is canonical for any browser test
needing admin auth. Three layers:

  1. **Sync fixture (not async).** pytest-playwright's sync API
     can't share an event loop with pytest-asyncio fixtures within
     one test.
  2. **Thread-isolated `asyncio.run`** for asyncpg work. The main
     thread already has an ambient loop from pytest-playwright;
     spawning a fresh thread sidesteps it. Reusable pattern for any
     future sync-fixture-with-async-DB-work.
  3. **`localStorage` user injection with `role: "admin"`.** The
     admin layout's route guard checks `user?.role`, not just
     `isAuthenticated`. CP3's null-user pattern (sufficient for
     /today) failed at /admin until the user object was injected.

If Phase B needs more sync-fixture DB writes, factor `_run_async`
out of `conftest.py` into a shared helper.

---

## Pattern 22 reinforcement evidence base (Phase A)

Pattern 22 = "spec/schema reconciliation": any artifact making schema
or vocabulary claims must verify against the live source at pre-flight;
assume drift exists, prove it doesn't.

Phase A added five concrete instances:

| CP | Drift                                                    | Caught at |
|----|----------------------------------------------------------|-----------|
| CP2 | Migration 0023 — String(36) FK to UUID users.id          | Chain replay |
| CP2 | Migration 0024 — duplicate-named index                   | Chain replay |
| CP2 | Migration 0025 — `Base.metadata.create_all` references future ENUM | Chain replay |
| CP4 | `agent_actions` claimed `triggered_by_user_id` / `target_user_id` columns; actual columns are `actor_id` / `on_behalf_of` | Smoke run |
| CP4 | `lessons.position` claimed; actual column is `"order"` (reserved word, must quote) | Smoke run |
| CP4 | `course_entitlements.course_slug` claimed; actual column is `course_id` (slug→id resolution lives in `_grant_entitlement`) | Smoke run |

Each one was a docs/model-graph cache out of step with live Postgres.
The discipline: read `pg_constraint` and `pg_attribute` against the
live DB at pre-flight (the CP4 `cleanup.py` docstring captures the
canonical queries). At CP5, the discipline extended to vocabulary —
`_LEGITIMATE_ROLE_REFERENCES` is imported, not duplicated.

---

## Operational follow-up resolutions

| Follow-up                                              | Status at Phase A close                              |
|--------------------------------------------------------|------------------------------------------------------|
| `tests-dir-not-bind-mounted-docker-cp-workaround.md`   | Resolved for runner via overlay; dev path still uses `cp` |
| `test-suite-bulk-run-oom-by-directory-workaround.md`   | CI splits by file group (workflow has 2 jobs)        |
| `pytest-asyncio-pytest-playwright-split-runs.md`       | Documented + CI honors split                         |
| `migration-chain-fresh-db-rebuildability.md`           | Open; discipline encoded in `create_template.py`     |
| `frontend-testid-additions-d18.md`                     | Path A escalation trigger documented                 |
| `capstone-submission-frontend-not-built.md`            | Open; frontend feature gap; founder decision pending |

---

## How to author a Phase B journey test

A canonical journey test:

```python
import pytest
from playwright.sync_api import Page

from tests.playwright.pages import LoginPage, TodayPage
from tests.playwright.helpers import (
    assert_outreach_log_entry,
    assert_no_sycophancy,
    BudgetExceeded,
)


def test_paid_silent_student_receives_nudge(
    page: Page,
    paid_silent_student,             # CP4 composite fixture
    db_session,                      # CP2 async session
    budget_tracker,                  # CP5 budget tracker (opt-in)
) -> None:
    # 1. Authenticate (CP3 helper or admin_browser_context fixture)
    # ... login flow

    # 2. Drive the UI through the page object
    today = TodayPage(page)
    today.navigate()

    # 3. Trigger the action under test
    # ... click, type, submit

    # 4. Verify side effects
    await assert_outreach_log_entry(
        db_session,
        user_id=paid_silent_student.student.user_id,
        channel="email",
        triggered_by="system",
    )

    # 5. Verify behavior shape
    response_text = today.page.get_by_test_id("nudge-text").inner_text()
    assert_no_sycophancy(response_text)

    # Cleanup happens automatically via the fixture's teardown.
```

Key conventions:
- Request the most-specific fixture you need (composite > primitive).
- Don't commit inside the test; the fixture wraps your work.
- Assert with the helpers, not raw SQL — diagnostic detail is in
  the helper's error path.
- For real-LLM tests, opt into `budget_tracker` and capture
  `start = datetime.now(UTC)` before the LLM call; the tracker's
  `query_test_cost(db_session, since=start)` attributes cost.

---

## Phase B prerequisites met

Phase B can begin authoring journey tests immediately. The
infrastructure surface is:

  ✅ Stack management: `build_and_serve.sh`
  ✅ DB strategy: template + per-suite clone
  ✅ Fixtures: 25 helpers + 7 pytest wrappers
  ✅ Page objects: 8 surfaces
  ✅ Assertion helpers: 4 modules + budget tracker
  ✅ Auth: student + admin paths working
  ✅ CI: 2-job split, budget enforcement
  ✅ Patterns documented for cross-cutting concerns

Phase B prompt drafting starts after this commit lands.
