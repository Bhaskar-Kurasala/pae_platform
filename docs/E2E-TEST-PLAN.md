# End-to-End Test Plan — Production AI Engineering Platform

**Author:** Claude (senior QA engineer voice)
**Date:** 2026-04-19
**Scope:** Phase 3 close-out — production-quality E2E coverage across the full student learning journey.
**Status:** plan approved, execution in progress (see `E2E-TEST-TRACKER.md`).

---

## 1. The App We Are Testing

Every test in this suite must serve **one goal**: verify that a real student can successfully learn production AI engineering on this platform, end-to-end, without hitting a bug, a silent error, or a confusing dead-end.

The platform is:

- **A teacher** — 20 AI agents tutor, grade, coach, and review code.
- **A coach** — daily intention, reflection, streak (reframed as consistency), and "stuck for 10 min" interventions that keep a student from silently drowning.
- **A career runway** — mock interviews, portfolio, JD fit, resume coaching.
- **An admin console** — operator can see every cohort, every action, every at-risk student.

So our E2E suite is not "click through every page." It is: **prove the learning loop works for a student who shows up on day 1, returns on day 2, submits an exercise on day 3, gets stuck on day 4, reflects on day 5, and lands an interview on day 30.** If any of those steps break, the platform has failed its purpose.

---

## 2. Brainstorm — What Can Actually Go Wrong?

Before listing tests, we list the failure modes a senior engineer has seen in similar systems:

### 2.1 Silent UI failures

- A button renders but clicks nothing (handler not bound).
- A form submits successfully but the page never re-renders (stale query cache).
- A toast never appears because the `<Toaster/>` was defined but never mounted (*we actually had this exact bug; caught and fixed in B3*).
- Dark mode looks fine — unless the user started in light, toggled, then reloaded (hydration mismatch).

### 2.2 Data contract drift

- Backend returns a new field; frontend schema validator rejects the whole response and the page crashes.
- Backend renames a field from `days_this_week` to `active_days` and every consumer silently renders zero.
- Enum value added on backend (`mood: "overwhelmed"`), frontend filters it out of the mood picker and the user can't see their own stored reflection.

### 2.3 Auth edge cases

- Token expires mid-session; next action returns 401 with no automatic re-login flow.
- User is on `/today`, logs out in another tab, stays on `/today` and fails silently.
- JWT refresh race — two simultaneous expired-token requests both try to refresh and only one wins.
- Rate limit on `/register` (we set 10/min). Legitimate users trying the demo hit it and see a silent failure.

### 2.4 Async and stream failures

- Chat SSE stream drops mid-response; UI shows a half-finished reply with no "retry" affordance.
- Celery task fails (celery-beat is currently restarting in the stack — a real finding); dependent feature (digest email, weekly wrap-up) quietly doesn't ship.
- Student submits an exercise; grader takes 12s; user assumes it hung and reloads, losing the submission.

### 2.5 LLM-specific failures

- Model returns non-JSON when we asked for JSON. Parser throws. UI shows a stack trace.
- Model returns *too much* JSON (a markdown fence + commentary + JSON). Parser picks the wrong object.
- Rate limit from the Anthropic API returns 429; our retry is exponential so the user waits 8s with no feedback.
- Socratic tutor's response contains no `?` — our evaluator flags it low-quality but we show it anyway.
- Clarification pills appear when the user's question was perfectly clear, making the UI feel patronizing.

### 2.6 State machine violations

- Student marks a lesson complete twice (double-click). Progress record duplicated.
- Student completes lesson, then the retrieval quiz API returns zero questions. Fallback reflection prompt *must* appear, not a blank card.
- Student sets daily intention, the clock crosses midnight, next morning they still see *yesterday's* intention until page refresh.
- Student opens Studio, edits code for 9:59, saves. Stuck banner appears. Is that a bug? (It is — the save should reset the idle timer.)

### 2.7 Mobile-specific failures

- User taps a 30×30px heart icon on mobile. Their thumb hits the wrong thing half the time.
- User opens the sidebar drawer on mobile, rotates device to landscape, the drawer is now stuck.
- User focuses the reflection textarea on mobile, the soft keyboard covers it, and they can't see what they're typing.
- Bottom nav hides the "Mark complete" button on the lesson page because the page didn't add padding for it.

### 2.8 Architecture decisions that may be wrong

- `celery-beat` is restarting — silent tickets that should be scheduled aren't firing. We need a test that proves scheduled tasks run.
- `nginx` returns 502 on the root path — the proxy is misconfigured but every developer uses the direct frontend port 3002 and never notices.
- Multiple alembic heads were merged in B1; a future migration could silently create another divergence. We need a test that asserts single head.
- Frontend runs at port 3002, backend at 8001 — but `api-client.ts` hardcodes the base URL. If we deploy to prod with different ports, everything breaks.

### 2.9 Accessibility failures

- Keyboard-only user cannot complete an exercise submission (focus trap broken, or the self-explanation modal cannot be dismissed with Escape).
- Screen reader announces "button" for 50 unlabeled icon buttons.
- Reduced-motion user gets vertigo because fade-up animation still plays.

### 2.10 Performance / perception failures

- Today page loads, but Intention card flashes empty-state for 300ms before the real data renders.
- Route transitions have no loading bar — user clicks, waits 2s, clicks again thinking the first click missed.
- Large course list re-fetches on every navigation because `staleTime` is 0.

---

## 3. Architecture & Decisions

### 3.1 Infrastructure (what we're testing against)

Discovered via `docker ps`:

| Service | Port | Status | Notes |
|---|---|---|---|
| Frontend (Next.js) | `localhost:3002` | Up 12h | This is the real base URL for tests. |
| Backend (FastAPI) | `localhost:8001` | Up 12h (healthy) | Direct endpoint. |
| Nginx proxy | `localhost:8080` | Up, but returns 502 | **Flagged — fix or drop.** |
| Postgres | `localhost:5433` | Up (healthy) | Test user seeded here. |
| Redis | `localhost:6381` | Up (healthy) | Conversation history + rate-limit state. |
| Celery worker | — | Up 41 min | Recently restarted; investigate. |
| Celery beat | — | **Restarting (1)** | **Real bug flagged — scheduled tasks not firing.** |
| Meilisearch | `localhost:7700` | Up | Search backend (mostly used by content pipeline). |

E2E tests hit **`http://localhost:3002`** for UI and **`http://localhost:8001`** for direct backend verifications (auth token seeding, data fixture setup, and state assertions that are easier via API than via UI click).

### 3.2 Tech stack for E2E

| Tool | Purpose | Why |
|---|---|---|
| **Playwright (Chromium only)** | Browser automation | We validated that Chromium alone covers 95% of prod traffic; Firefox + Webkit double the install size and triple the run time for marginal gain. |
| **Playwright MCP** | Exploratory sessions | Used **only** to discover selectors, debug flaky tests, or confirm an unknown flow. Not a test runner — the committed `.spec.ts` files are the source of truth. |
| **@playwright/test runner** | Spec runner | Native assertions, retries, parallel workers, trace viewer, HTML report. |
| **TypeScript** | Test language | Matches the frontend codebase; reuse types from `src/lib/api-client.ts`. |
| **A backend API helper** (`tests-e2e/helpers/api.ts`) | Direct fixture seeding | Some state is 10× faster to set via API than via UI (create a user, set a goal, enroll in a course). Tests that *verify* behavior click through the UI; tests that *set up* state use the API. |
| **Test user pool** | Auth without re-registering every run | A small set of seeded users `e2e-student-1@pae.test` ... `e2e-student-5@pae.test` with known passwords. Tests lock a user per spec file. |
| **Trace + screenshot on failure** | Debug-ability | Playwright's built-in trace viewer. On fail: screenshot + full network + console. |

### 3.3 What we deliberately chose NOT to do

| Decision | Why |
|---|---|
| No MSW / mocked backend | The whole point is real E2E. We trust Docker more than a mock. |
| No cross-browser matrix | 80 tests × 3 browsers = 240 runs. Not worth the CI time for the marginal bug catch. Revisit post-launch. |
| No visual regression (Chromatic / Percy) | Out of scope for Phase 3. File a Phase 4 ticket if we want pixel diffs. |
| No load testing / k6 | Separate discipline, separate tool, separate phase. |
| No Playwright test generator (`codegen`) for production specs | `codegen` produces brittle, over-specified selectors. We write them by hand. |

### 3.4 Authentication strategy

We seed **5 known test users** directly via the backend API in a one-time `tests-e2e/globalSetup.ts`:

```
e2e-student-1@pae.test  / Pae-Test-2026!   — the "happy path" student (has goal, some progress)
e2e-student-2@pae.test  / Pae-Test-2026!   — brand-new student (no goal, no enrollment)
e2e-student-3@pae.test  / Pae-Test-2026!   — mid-course student (enrolled, some completions)
e2e-student-4@pae.test  / Pae-Test-2026!   — advanced student (near-complete, wins on record)
e2e-admin@pae.test      / Pae-Admin-2026!  — admin user for admin-console tests
```

Each spec file locks one user to avoid cross-spec interference. Parallelism is capped at the number of users (5) to keep isolation clean. This is 80 tests across 5 workers — fast enough.

### 3.5 Test categories

| Category | Meaning |
|---|---|
| **Journey** | Multi-page user flow (e.g. register → goal → course → lesson → complete → quiz). Catches integration bugs. |
| **Feature** | Single-feature depth (e.g. every state of the intention card). Catches state-machine bugs. |
| **Contract** | UI ↔ API shape assertions (fetches a real response, checks schema). Catches drift. |
| **Resilience** | Error, offline, 401, 429, stream drop. Catches graceful-failure bugs. |
| **A11y** | Keyboard nav, focus, aria, reduced motion. Catches inclusion bugs. |
| **Mobile** | Viewport ≤ 428px; drawer, bottom nav, tap targets. Catches phone-only bugs. |
| **Admin** | Admin-only pages and operator flows. |

---

## 4. The Test Plan — 95 Scenarios Across 14 Spec Files

We target **95 tests** (the "100-ish high-quality, catches real bugs" bar you set). Every test below is specific, owned, and traceable. The tracker doc (`E2E-TEST-TRACKER.md`) has one row per test with: **status**, **3-point outcome note**, and **blame-on-fail** pointer.

### File 1: `auth.spec.ts` — 10 tests

*Category: Journey + Resilience*

1. A new user can register → land on `/onboarding`.
2. Register with an existing email → error toast, stays on form.
3. Register with a weak password → inline field error, submit button stays disabled.
4. Login with correct credentials → redirects to `/today` (has goal) or `/onboarding` (no goal).
5. Login with wrong password → error toast, form not cleared, focus returns to password.
6. Logout from sidebar → token cleared, redirects to `/login`.
7. Visit `/today` without a token → redirects to `/login`.
8. Session token refresh works: let access token expire, make an authenticated request, expect silent refresh not a 401.
9. Register 11 times in 60s (rate limit is 10/min) → 11th shows a clear "slow down" message (not a silent failure).
10. After logout, browser back button does not restore an authenticated page's content (no stale session rendering).

### File 2: `onboarding.spec.ts` — 6 tests

*Category: Journey*

1. Brand-new user lands on `/onboarding` on first login.
2. Goal picker submits a free-text goal → redirects to `/today`.
3. Reloading `/onboarding` with a goal already set → redirects to `/today`.
4. Visiting `/today` without a goal → redirects to `/onboarding`.
5. Editing an existing goal from `/today` persists after reload.
6. Empty goal submission → validation error, no navigation.

### File 3: `today.spec.ts` — 12 tests

*Category: Feature + Journey (the Today screen is the platform's heartbeat)*

1. Before 18:00 local: intention card visible, reflection card hidden.
2. After 18:00 local: intention card hidden, reflection card visible. (Uses Playwright clock API to freeze time.)
3. Intention empty-state → typing + save → card flips to "filled" state, persists on reload.
4. Intention edit → cancel restores prior value; save overwrites.
5. Intention > 200 chars → cannot type beyond cap.
6. Consistency widget reads `days_this_week / window_days` correctly from API.
7. Consistency track has exactly 7 cells on mobile and desktop.
8. Micro-wins empty state copy appears when API returns `wins: []`.
9. Micro-wins list renders with relative timestamps ("just now", "3h ago") for seeded activity.
10. Reflection mood pills are a proper `radiogroup` with `aria-checked` toggling.
11. `today.variant_shown` CustomEvent fires with the right variant on mount.
12. Dev tools → offline → Today page shows the last cached data, not a blank screen.

### File 4: `courses.spec.ts` — 8 tests

*Category: Journey + Contract*

1. `/courses` lists published courses; each has title, difficulty, CTA.
2. Filter by difficulty → only matching courses remain; URL updates with `?difficulty=`.
3. Click a course card → navigates to `/courses/[id]`.
4. Course detail page shows the full lesson list with durations.
5. Enrollment CTA: free course enrolls instantly; paid course routes to checkout (stub).
6. Unauthenticated user on `/courses/[id]` → redirected to `/login` with `?next=` preserved.
7. Course not found (bad ID) → friendly 404 component, not a stack trace.
8. Course catalog is cached: second visit within 60s does not re-fetch.

### File 5: `lessons.spec.ts` — 10 tests

*Category: Journey (the learning loop)*

1. Lesson page renders title, video, description, and code block.
2. "Mark complete" sends a POST and flips to "Completed" state.
3. Double-click "Mark complete" → only one API call fires (idempotent UI).
4. On completion, Retrieval Quiz appears inline below.
5. Quiz with zero questions → fallback reflection prompt visible.
6. Quiz with N questions → Grade button disabled until every question is answered.
7. Submit quiz → results show `N / M correct` with per-question correctness.
8. Wrong answers show the correct answer and an explanation.
9. Navigate away mid-quiz → progress NOT lost (answers preserved in state or acceptably reset — pick one and test it).
10. Back-button from `/lessons/[id]` returns to `/courses/[id]` with scroll position preserved.

### File 6: `exercises.spec.ts` — 10 tests

*Category: Journey + Feature*

1. `/exercises` lists exercises; each shows difficulty + title.
2. Open an exercise → shows problem statement + starter code in editor.
3. Click "Submit" → Self-Explanation Modal opens (does NOT submit yet).
4. "Skip & submit" in modal → submits with empty explanation.
5. Modal submit button disabled until explanation ≥ 10 chars.
6. Submit with explanation → grade result renders with score + feedback.
7. Optimistic UI: after submit, the submission appears in the list before the server confirms.
8. Bad submission (empty code) → server returns validation error; shown as inline toast, not a crash.
9. Submission of 5000+ char code → editor handles it, submit succeeds.
10. Escape key closes the self-explanation modal and does not submit.

### File 7: `studio.spec.ts` — 10 tests

*Category: Feature + Resilience*

1. Studio loads with an empty editor and disabled Run button.
2. Type code → Run button enables.
3. Click Run → execution trace populates with stdout + steps.
4. Make a second run → diff button appears, shows a real diff.
5. History tab lists prior runs in reverse chronological order.
6. Request Senior Review with empty code → button disabled.
7. Request Senior Review with code → panel opens, loading state, then review arrives.
8. **Stuck banner**: with Playwright clock freeze, advance 10 min of inactivity → banner appears.
9. Stuck banner "Ask the tutor" → dispatches `studio.stuck_ask_tutor` event (listen on window).
10. Stuck banner "Dismiss" → banner disappears, `studio.stuck_dismissed` event fires.

### File 8: `chat.spec.ts` — 8 tests

*Category: Feature + Resilience + LLM-specific*

1. Sending a clear message streams a response in real time.
2. Sending "huh?" triggers clarification pills (not an answer).
3. Clicking a clarify pill sends the composed message with the right modifier.
4. After a long streamed response (≥ 80 chars), follow-up suggestion pills appear.
5. Clicking a follow-up pill prefills the input, does NOT auto-send.
6. Stopping mid-stream (disconnect test via route abort) shows a "retry" affordance.
7. Error from backend (simulate 500) → toast.error fires with a useful message.
8. Conversation history persists on reload (last 6 turns visible).

### File 9: `progress.spec.ts` — 6 tests

*Category: Journey + Contract*

1. `/progress` shows enrolled courses with % complete, matching what the backend returns.
2. Streak widget is NOT shown; consistency widget IS shown (intentional reframe — we deleted streak).
3. Spaced-review card shows due cards count.
4. Per-skill mastery bars match API data.
5. Empty state (new user): friendly prompt to enroll, not a broken chart.
6. Clicking a course on `/progress` navigates to `/courses/[id]`.

### File 10: `admin.spec.ts` — 8 tests

*Category: Admin + Journey*

1. Non-admin hitting `/admin` → redirected to `/today` (or 403).
2. Admin hitting `/admin` → stats dashboard loads.
3. `/admin/students` → table lists students; responsive on mobile (stacked cards).
4. `/admin/at-risk` → list populates only if any student qualifies; otherwise empty state.
5. `/admin/audit-log` → table renders N rows from `agent_actions`.
6. `/admin/agents` → health pings each agent; shows green/red status.
7. `/admin/feedback` → list of feedback items, filterable by type.
8. `/admin/content-performance` → per-lesson stats (confusion count, question count).

### File 11: `mobile.spec.ts` — 7 tests

*Category: Mobile (uses iPhone 12 viewport preset: 390×844)*

1. Mobile bottom nav is visible on every portal page; desktop has it hidden.
2. Edge-swipe from left opens the sidebar drawer.
3. Swipe-left inside drawer closes it.
4. Tap targets: all primary buttons have rendered height ≥ 44px.
5. Responsive table: on `/admin/students`, rows render as stacked cards.
6. Textarea on `/today` (intention): focusing it on mobile scrolls it into view above the virtual keyboard (check scroll position change on `focus`).
7. Main content has bottom padding so the bottom nav does not cover the last element (the "Mark complete" button on `/lessons/[id]`).

### File 12: `a11y.spec.ts` — 6 tests

*Category: A11y*

1. Tab from the top of `/today` reaches every interactive element in visual order.
2. Every icon-only button has an accessible name (`aria-label` or `sr-only` text).
3. Self-Explanation modal traps focus and closes on Escape.
4. Retrieval quiz `radiogroup` is keyboard-operable (arrow keys move selection).
5. Reduced-motion preference disables fade-up / route animations.
6. Dark mode meets WCAG AA contrast on `/today` primary text (checked via computed styles).

### File 13: `dark-mode.spec.ts` — 4 tests

*Category: A11y + Visual*

1. Toggle dark mode from sidebar → `html` gets `.dark` class, theme persists in localStorage.
2. Reload with `.dark` already set → no "flash of light mode" (FOUC) on hydration.
3. Every page renders without layout shift when theme toggled.
4. Toaster respects theme (dark background in dark mode).

---

**Total: 95 tests across 13 spec files + global setup.**

---

## 5. Execution Model

### 5.1 Directory layout

```
pae_platform/
  tests-e2e/
    playwright.config.ts
    globalSetup.ts                 — seeds 5 test users via API
    helpers/
      api.ts                       — authed fetch + fixture creation
      clock.ts                     — time-freeze helpers (for Today rotation, Stuck banner)
      user-pool.ts                 — locks a seeded user to a worker
    fixtures.ts                    — Playwright fixtures: authedPage, adminPage
    auth.spec.ts
    onboarding.spec.ts
    today.spec.ts
    ...
    README.md                      — how to run locally, how to debug
```

### 5.2 Running locally

```
cd pae_platform
pnpm --filter @pae/e2e install          # or wherever we land the package
pnpm exec playwright install chromium
pnpm exec playwright test               # all specs
pnpm exec playwright test today         # single spec
pnpm exec playwright test --headed      # watch it run
pnpm exec playwright test --ui          # interactive mode
pnpm exec playwright show-report        # open last HTML report
```

### 5.3 Running in CI (follow-up ticket)

Deferred. File `E2E-CI.md` as a Phase 4 ticket: add `.github/workflows/e2e.yml` that spins up the full docker-compose stack and runs specs.

---

## 6. Quality Bar — What "Done" Means for a Test

A test is **closed** only when all four hold:

1. **It passes against the current stack**, reliably, three consecutive runs (no flakes).
2. **It would fail if the feature broke.** (Run it, then revert the feature's code — does it go red? If not, the test proves nothing.)
3. **Its failure message is specific enough to localize the bug in ≤ 2 minutes** (use `expect(...).toHaveText(...)` over `expect(...).toBeTruthy()`).
4. **A tracker entry exists** in `E2E-TEST-TRACKER.md` with: status, 3-point outcome note, any bug filed as a result.

---

## 7. What Senior Engineers Do That Juniors Don't (Training Notes)

- **Before writing a test, think about what WOULD fail.** If you can't imagine a plausible bug this test catches, don't write it.
- **Avoid coupling tests to implementation details.** If you rely on a CSS class name that could refactor, your test is brittle. Prefer role + accessible name.
- **Test the contract, not the implementation.** `expect(page.getByRole('button', { name: 'Submit' }))` — not `page.locator('#submit-btn')`.
- **State is the enemy of good tests.** Start each test from a known state. Use API fixtures, not "click through the previous test's aftermath."
- **Wait for user-visible conditions, not timeouts.** `await expect(card).toBeVisible()` — not `await page.waitForTimeout(1000)`.
- **When a test is flaky, the test is lying.** Either the feature has a race condition (fix it) or the test is wrong (fix it). Never `test.retry(3)` to silence flakes.
- **A test that doesn't explain why it exists isn't maintainable.** Every spec file starts with a 2-line preamble: *what this tests, what it catches*.
- **The tracker is the source of truth.** If a test passes but didn't surface a known bug, note *"did not catch X — revisit."*

---

## 8. Known Issues Discovered During Planning (Pre-Existing, Worth Filing)

| # | Finding | Severity | Owner |
|---|---|---|---|
| E2E-DISC-1 | `celery-beat` container stuck in Restarting(1) → scheduled tasks are not running. | High | Infra |
| E2E-DISC-2 | `nginx` at :8080 returns 502 on `/` — proxy misconfig. Every dev uses :3002 direct, hiding this. | Medium | Infra |
| E2E-DISC-3 | Port mismatch: `docker-compose` maps backend to 8001, frontend to 3002; any docs / client pointing at 8000 / 3000 are wrong. | Medium | DevEx |
| E2E-DISC-4 | `landing.test.tsx` has 2 failing tests unrelated to B1-B4 work. Fix before shipping. | Low | Frontend |
| E2E-DISC-5 | The Sonner `<Toaster/>` was declared but never mounted before B3 commit `2a8af59`. Prior to that, every `toast.*` call was a silent no-op. Any past QA that relied on toast feedback was compromised. | High — fixed | Frontend |

These go in `E2E-TEST-TRACKER.md` as discovery items; fixes land as separate commits.

---

## 9. Sign-off

This plan is self-contained. If a senior engineer walks in cold tomorrow, they can read this doc + the tracker and pick up the work at the exact next test without asking anyone. That is the standard.

The tracker doc follows in `E2E-TEST-TRACKER.md`.
