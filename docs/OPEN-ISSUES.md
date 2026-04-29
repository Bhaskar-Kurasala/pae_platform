# Open issues — production-readiness tail

Living tracker for everything we *know* still needs work but consciously parked to avoid blocking the first deploy. Re-read this before tagging any release.

**Owner:** Bhaskar
**Started:** 2026-04-29 (after PR2/PR3 merge + MCP-driven coverage audit)
**Discoverable from:** [`PRODUCTION-READINESS.md`](./PRODUCTION-READINESS.md) (linked in the top banner)

---

## How to use this file

Three states per item:

- 🔲 **Open** — not yet started.
- 🟡 **In progress** — being actively worked on; replace with the branch name in `On:`.
- ✅ **Closed** — keep the row for institutional memory; move it to the **Closed** section at the bottom with a one-line resolution note.

When closing an item, **add a `closed-by:` line** with the commit SHA so the audit trail survives.

When new issues surface in production, add them here **before** firing off a fix — the act of writing them down forces clarity on severity and blast radius.

---

## Priority taxonomy

| Tier | Definition | Action window |
|---|---|---|
| **P0** | Blocks first prod deploy | Fix before `git tag v1.0.0` |
| **P1** | Acceptable for internal beta (≤ 5 users) but NOT for general onboarding | Fix before opening enrollment |
| **P2** | Quality polish / scale concerns | Fix in steady-state operation, not gated on launch |
| **P3** | Pre-existing tech debt unrelated to PR2/PR3 | Whenever convenient; don't let it grow |

---

## 🟡 In progress

*(none yet)*

---

## 🔲 Open

### P1-A — Admin interaction audit (buttons, workflows, mutations)

> **🔄 SUPERSEDED by [`RETENTION-ENGINE.md`](./RETENTION-ENGINE.md).** What started as a "do the buttons work" audit became a product-level rethink. Bhaskar (PM) reframed the question from "are admin tools functional?" to "is the system catching slipping students?" — and we discovered most of the broken buttons (Schedule call / Send DM / Add note) were *missing features*, not broken implementations. The 14-ticket retention-engine plan is the right answer; this entry stays for receipts.

The MCP coverage audit (commit `83b1f74`) verified every admin screen *renders* with real data. It did NOT verify that interactive elements actually do what they claim. Before opening admin access to non-Bhaskar accounts, every click target across `/admin/*` needs a smoke check.

**Specific call sites to verify:**

- `/admin` console:
  - "Open profile" on a call-list row → does it navigate to `/admin/students/{id}`?
  - "Schedule call" → does anything happen, or is it a stub?
  - "See full call list" CTA → where does it route?
  - 24h / 7d / 30d toggle on Platform pulse → does it refetch with the right window?
- `/admin/students`:
  - "Open" row action → loads `/admin/students/{id}` cleanly?
  - Sort columns (Student / Track / Stage / Progress / Streak / Last seen / Risk) → all 7 sort directions work?
  - Search box debounce → does it actually filter the roster?
  - Filter chips (All / Severe / High / Paid+stalled / Thriving / Joined<7d) → do they apply correctly?
- `/admin/agents`:
  - "Trigger" button on a stub agent → does the POST to `/api/v1/admin/agents/{name}/trigger` succeed?
- `/admin/feedback`:
  - "Resolve" PATCH → does the row disappear from the open queue?
- `/admin/confusion`:
  - 7d / 30d / 90d window switcher → refetches with `?days=N`?
- `/admin/at-risk`:
  - `min_score` filter — does adjusting it actually re-run the query?
  - "Open" → student timeline?
- `/admin/students/[id]`:
  - Per-student timeline — does it render with realistic event counts?

**How to close:** ~30 min of MCP-driven click-through, then 6-8 new Playwright specs covering the highest-leverage workflows. Add to `frontend/e2e/admin-coverage.spec.ts` rather than a new file — keep all admin coverage in one place.

**Severity rationale:** Admin actions are low-volume but high-trust. A broken "Resolve feedback" button doesn't hurt students but undermines the operator's ability to do their job. Worth catching before they discover it the hard way.

**On:** _(not yet)_

---

### P1-B — Multi-user / scale-realistic testing

Everything tested so far runs against 1 student + 1 admin on a fresh DB. Production realism gap:

- `/admin/students` table with 100+ rows: pagination performance, sort responsiveness, search debounce under load.
- Confusion heatmap with 50+ topics: does the grid layout break? Currently only 1 row exists, can't tell.
- Audit log: backend caps at `?limit=100`, but the UI table doesn't paginate. With 10,000+ rows on disk, the user only ever sees the most recent 100 — fine, but document it. With 10,000+ entries SHOULD render in <1s; not yet measured.
- Concurrent admin edits: two admins resolving the same feedback simultaneously — does the second PATCH 409, 500, or silently overwrite?
- Student-side concurrency: 50 students hitting `/today/summary` simultaneously — does the LangGraph orchestrator queue or thrash?

**How to close:**
1. Seed a load test fixture (~200 students, ~50 confusion topics, ~5000 audit entries) via `app/scripts/seed_today_demo.py` extension.
2. Re-walk admin screens via MCP under that load — visually confirm nothing breaks.
3. Add a smoke perf budget: `/admin/students` p95 render < 1.5s.

**Severity:** medium. Real-world breakage shows up at ~50 active users; not at 5.

**On:** _(not yet)_

---

### P1-C — First Fly deploy + post-deploy verification

`fly.toml` and `fly-frontend.toml` are written, valid TOML, but never executed against actual Fly. The first `fly deploy` will surface anything I got wrong:

- Region availability (we picked `iad`; verify Fly has capacity)
- Image size limits (Fly's free tier is 256MB shared-cpu)
- Secret name mismatches (`DATABASE_URL` vs `database_url` etc.)
- Health-check path mismatches (we set `/health/ready`; verify it works behind Fly's proxy)
- Bluegreen strategy timing (300s wait — enough? too much?)
- The deploy.yml CI workflow itself has never run; first push will reveal any YAML issues

**How to close:** Follow the "first deploy" runbook (which doesn't exist yet — see P2-A). Document each surprise.

**Severity:** P1 because the *plan* is solid; only execution can fail. But execution failure on a live tag push affects users — better to do a dry deploy first.

**On:** _(not yet)_

---

### P1-D — Real Sentry / PostHog verification

The shims (PR3/C3.1, PR3/C5.1) are unit-test-verified to no-op safely without DSN. Never tested against real Sentry / PostHog projects:

- Does `before_send` PII filtering actually strip headers when an event hits the wire? (Unit test stubs the SDK.)
- Do `llm.call` events accumulate correctly in the PostHog dashboard with the right `cost_estimate_inr` aggregation?
- Does the Sentry release tag (`getsentry/action-release@v1` step in `deploy.yml`) actually create a release in the project?
- Do source-maps from `withSentryConfig` actually upload + symbolicate stack traces?

**How to close:**
1. Spin up the free-tier Sentry + PostHog projects.
2. Set `SENTRY_DSN` / `POSTHOG_KEY` via `fly secrets set` after first deploy.
3. Trigger a deliberate error (e.g. `/admin/agents/{nonexistent}/trigger`) and confirm it lands in Sentry with the right tags + redacted PII.
4. Click around as a student for 5 min and confirm the events appear in PostHog under the right `distinct_id`.

**Severity:** P1 because broken observability silently hides production incidents — exactly when you need it most.

**On:** _(not yet)_

---

### P2-A — First-deploy runbook

`docs/runbooks/secret-rotation.md`, `restore.md`, `oncall.md`, `admin-management.md` all exist. **No runbook for the actual first deploy.** Steps a new operator (or future-me) needs:

1. Provision cloud accounts (Fly, Neon, Upstash Redis, Cloudflare R2, Sentry, PostHog, Healthchecks.io).
2. Initial `fly apps create pae-platform` + `fly apps create pae-platform-web` + `fly apps create pae-platform-backup`.
3. `fly secrets set ...` for each app (cross-reference the in-file comments in `fly.toml`, `fly-frontend.toml`, `fly-backup.toml`).
4. GitHub repo secrets: `FLY_API_TOKEN`, `SENTRY_AUTH_TOKEN`, `SENTRY_ORG`, `SENTRY_PROJECT_FRONTEND`.
5. First `git tag v1.0.0 && git push --tags` → watch the deploy workflow run.
6. Post-deploy: verify `/health/ready` returns 200 on prod URL, then promote first admin via `docs/runbooks/admin-management.md`.

**How to close:** Write `docs/runbooks/first-deploy.md` covering all six. Should fit in one screen for steps 1-3, one screen for 4-6. Each cloud account needs its own subsection.

**Severity:** P2 — the prerequisites are all documented in the existing TOMLs and runbooks; "first-deploy.md" just consolidates them into a single follow-once flow.

**On:** _(not yet)_

---

### P2-B — D9 accessibility (axe-core)

Originally numbered D9.1 in PR3. Deferred to post-first-deploy because it needs a live URL. Two parts:

- D9.1: `axe-core` CI run for 6 main screens (Today, Path, Practice, Promotion, Notebook, Catalog). Fails on serious / critical violations.
- D9.2: Manual keyboard-only walk on Today + Practice. Fix any focus traps.

**How to close:** Add a Playwright spec that loads each screen + runs `axe-core/playwright`. Follow-up PR per major fix. The keyboard walk is a one-time human pass.

**Severity:** P2 for paying customers. Could become P1 if you onboard a student using a screen reader.

**On:** _(not yet)_

---

### P2-C — D10 Lighthouse perf budget

Originally numbered D10. Deferred for the same reason — needs a live URL. Goal: every main screen has a budget (FCP < 2s, LCP < 2.5s on simulated 3G), CI fails on >10% regression from baseline.

**How to close:** Add `treosh/lighthouse-ci-action@v11` to the deploy workflow's smoke phase, post-deploy. Establish baselines from the first prod deploy.

**Severity:** P2. Slow pages don't break things, but they reduce engagement, especially on mobile.

**On:** _(not yet)_

---

### P3-A — Pre-existing backend SQLite/timezone test failures (24)

24 backend tests fail on `main` and have failed since well before PR2:

```
test_notebook_summary_route.py::test_summary_with_graduated_and_in_review_entries
test_notebook_summary_route.py::test_list_in_review_filter_excludes_graduated_entries
test_growth_snapshot_service.py::test_lessons_completed_in_window
test_learning_session_service.py — 9 tests
test_notebook_service.py — 9 tests
test_progress_service_weighted.py::test_active_course_is_most_recently_touched
test_srs_graduates_notebook.py — 2 tests
```

Root cause documented in `docs/lessons.md`: SQLite ARRAY param binding + naive vs aware datetime mismatch in the test conftest. Fixing requires either:
1. Switching tests to a Postgres test container (more work but truer to prod), or
2. Adding a SQLAlchemy `@compiles` shim for ARRAY parameter binding on SQLite (smaller scope but only helps notebook tests).

**Severity:** P3. They're red on main today; have been for weeks. Not new regressions. Mask future regressions in those modules though.

**How to close:** Pick option 2 first (smaller); revisit option 1 if more SQLite-specific tests start failing.

**On:** _(not yet)_

---

### P3-B — Pre-existing frontend chat test failures (69)

69 frontend tests fail on `main`, all in `frontend/src/app/(portal)/chat/__tests__/`. Root cause: tests don't wrap in `QueryClientProvider`. Pre-existing, unrelated to PR2/PR3.

**Severity:** P3. Same pattern as P3-A — old red, masking future regressions.

**How to close:** Add a shared `renderWithProviders` helper that wraps in `QueryClientProvider` + `ThemeProvider`, migrate the 69 tests to use it. Probably one focused PR.

**On:** _(not yet)_

---

### P3-C — `/api/v1/health` (legacy, no /api/v1 prefix on health) inconsistency

`/health/ready` and `/health/version` (PR3/C6) live at the bare root, not under `/api/v1/`. Other routes are under `/api/v1/`. Frontend code (`api-client.ts`) uses both prefixes inconsistently. Not a bug — health endpoints are conventionally bare-path — but worth documenting in `docs/ARCHITECTURE.md` so a future contributor doesn't accidentally "fix" it.

**Severity:** P3 — pure documentation drift.

**How to close:** One paragraph in ARCHITECTURE.md under "API Route Groups."

**On:** _(not yet)_

---

## ✅ Closed

### `/api/v1/goals/me` 404 noise across every authenticated screen
- **Closed by:** `83b1f74` (2026-04-29)
- **Resolution:** Endpoint now returns `200 + null` for users with no goal set. Absence of resource is not an error here. Frontend `useMyGoal` hook still has its 404 fallback for cached responses from older versions.

### `/admin/audit-log` empty-state forever (broken cookie auth)
- **Closed by:** `83b1f74`
- **Resolution:** Was a server component reading `access_token` cookie that's never set in this codebase. Converted to client component using the same useQuery+api.get pattern as the working admin screens.

### `/admin/content-performance` empty-state forever
- **Closed by:** `83b1f74`
- **Resolution:** Same cookie bug as audit-log. Same fix.

### Admin sidebar — 3 dead nav links (`/admin/courses`, `/admin/analytics`, `/admin/settings`)
- **Closed by:** `83b1f74`
- **Resolution:** Removed from `admin-layout.tsx` and `global-command-palette.tsx`. Re-add when each page is built. Next's prefetch-on-hover stopped 404'ing.

---

## Notes for the next reader

- This file is intentionally **the only** open-issues tracker. Don't fragment into GitHub issues + Notion + Linear + this file. One source.
- "Severity" reflects **current** state, not original importance. A P3 can become a P1 if it starts blocking a launch.
- The "How to close" sections are pre-thought so a future agent (or human) can just pick one up without re-deriving the plan.
- When you close an item, **don't delete it** — move to the Closed section. Future-you will be glad of the receipts.
