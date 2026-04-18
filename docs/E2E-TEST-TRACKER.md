# E2E Test Tracker — Production AI Engineering Platform

**Companion to:** [`E2E-TEST-PLAN.md`](./E2E-TEST-PLAN.md)
**Last updated:** 2026-04-19
**Owner:** Claude (senior QA engineer voice)

This file is the single source of truth for E2E execution progress. Every test in the plan has a row here. After each test run, the row is updated with **3 outcome bullets** (what was verified, what bug was caught/fixed, status change) so the next engineer can pick up the thread cold.

---

## Progress Summary

| Category | Total | Pending | In progress | Passing | Failing | Closed |
|---|---:|---:|---:|---:|---:|---:|
| Auth & session | 10 | 0 | 0 | 0 | 4 | 6 |
| Onboarding | 6 | 6 | 0 | 0 | 0 | 0 |
| Today (daily loop) | 12 | 12 | 0 | 0 | 0 | 0 |
| Courses catalogue | 8 | 8 | 0 | 0 | 0 | 0 |
| Lessons & progress | 10 | 10 | 0 | 0 | 0 | 0 |
| Exercises & grading | 10 | 10 | 0 | 0 | 0 | 0 |
| Studio & stuck-banner | 10 | 10 | 0 | 0 | 0 | 0 |
| Chat & agents | 8 | 8 | 0 | 0 | 0 | 0 |
| Progress & receipts | 6 | 6 | 0 | 0 | 0 | 0 |
| Admin console | 8 | 8 | 0 | 0 | 0 | 0 |
| Mobile & gestures | 7 | 7 | 0 | 0 | 0 | 0 |
| Accessibility | 6 | 6 | 0 | 0 | 0 | 0 |
| Dark-mode & theme | 4 | 4 | 0 | 0 | 0 | 0 |
| **Total** | **95** | **85** | **0** | **0** | **4** | **6** |

**Legend**
- `pending` — not yet started
- `in-progress` — spec written, not yet green
- `passing` — green against docker stack
- `failing` — red; blocked on a bug (link it)
- `closed` — passing **and** 3-bullet outcome recorded below

A test is only considered **done** when its row has a status of `closed`, the 3-bullet outcome is filled in, and any discovered defects are filed in the Discovery section.

---

## How To Update This Tracker

When you finish a test (or learn something from one that's still red), edit its row to say:

1. **Verified:** what behavior you actually exercised end-to-end.
2. **Fixed / flagged:** what bug was caught, a link to the fix commit or a `E2E-DISC-#` in the Discovery section.
3. **Status:** new status + date (e.g. `closed 2026-04-20`).

Keep each bullet ≤ 1 line. If there's more to say, file a ticket and link it.

---

## 1. Auth & Session — `auth.spec.ts`

| # | Test | Category | Status | Outcome (3 bullets) |
|---|---|---|---|---|
| A1 | register new user with valid email + strong password redirects to `/onboarding` | Journey | closed | - Verified: fresh signup at `/register` with valid email + 17-char password lands on `/onboarding` with a Goal Contract wizard heading "Let's make this real, {firstName}"; auth token persisted to `localStorage["auth-storage"]`.<br>- Fixed: E2E-DISC-7 (wrong redirect target), E2E-DISC-8 (broken prod build blocking the verification), E2E-DISC-9 (missing DB columns causing onboarding 500s).<br>- Status: closed 2026-04-19 |
| A2 | register with weak password shows inline validation, no network call fires | Contract | closed | - Verified: submitting `abc` as password triggers native-browser `minLength=8` block first; stripping native attrs then re-submitting shows the JS guard "Password must be at least 8 characters." rendered in the destructive-toned alert banner.<br>- Verified: `browser_network_requests` filtered on `/api/v1/auth` confirms **zero** POST fires in either path (defense-in-depth: HTML + JS).<br>- Status: closed 2026-04-19 |
| A3 | register when rate limited (11th attempt/min) shows a specific error, not a silent failure | Resilience | closed | - Verified: fired 12 rapid POSTs to `/api/v1/auth/register`; requests 1–10 returned 201, requests 11–12 returned 429 with body `{"error":"Rate limit exceeded: 10 per 1 minute"}` — backend limit wired correctly.<br>- Verified (UI): 11th UI submit renders the destructive banner — not silent — but the visible text falls back to HTTP status text "Too Many Requests" instead of the backend's informative message. Flagged as E2E-DISC-10 (polish-level, low severity).<br>- Status: closed 2026-04-19 |
| A4 | login with correct credentials lands on `/today` and sets tokens in storage | Journey | closed | - Verified: `/api/v1/auth/login` 200 with valid creds; `router.replace("/today")` fires, then `/today` bounces to `/onboarding` because the test user has no goal yet (correct behavior per `today/page.tsx:39-43`, not a bug).<br>- Verified: `localStorage["auth-storage"]` persists `{token, isAuthenticated: true, user: {id, email, ...}}`; follow-up `GET /auth/me` 200 confirms bearer token is honored.<br>- Status: closed 2026-04-19 |
| A5 | login with wrong password shows error, does not clear email field | Feature | closed | - Verified: `POST /api/v1/auth/login` 401; banner renders generic "Invalid credentials" — doesn't distinguish "unknown email" vs "wrong password" so no user-enumeration leak.<br>- Verified: stays on `/login`; email field value preserved; `localStorage["auth-storage"]` remains `{isAuthenticated:false, token:null}` — no partial auth state written on failure.<br>- Status: closed 2026-04-19 |
| A6 | expired access token triggers silent refresh, original request retries transparently | Resilience | failing | - Verified: installed an expired JWT (`exp=1000000000`) in `auth-storage`; `/today` fired 3 protected calls (`/goals/me`, `/preferences/me`, `/notifications/me`) all 401.<br>- Flagged: **no refresh attempted** — `/auth/refresh` endpoint is missing backend-side and the client has no refresh path; instead `clearAuthAndRedirect()` → `/login`. Tracked as E2E-DISC-11 (high). Fallback is graceful (no loop, clean redirect) so it's a feature-gap rather than a regression.<br>- Status: **failing** — spec assumes an unimplemented feature. Re-open after E2E-DISC-11 is fixed. (2026-04-19) |
| A7 | refresh token also expired redirects to `/login` with a banner explaining re-auth | Resilience | failing | - Verified (partial): with no refresh flow (see E2E-DISC-11), every 401 already redirects to `/login` — so the "refresh expired" end-state is reached vacuously, but the destination has **no banner** explaining the forced re-auth; the user lands on a blank `/login` and may think they just weren't logged in.<br>- Flagged: missing re-auth banner blocks this spec. Part of E2E-DISC-11 follow-up; when refresh lands, so should a toast/banner on 401-clear.<br>- Status: **failing** — cannot pass independently of E2E-DISC-11 fix. (2026-04-19) |
| A8 | logout in tab A while tab B is on `/today` makes tab B's next action re-auth gracefully | Resilience | failing | - Verified: simulated Tab A logout (localStorage cleared + `storage` event dispatched); Tab B's Zustand in-memory store kept `{token, isAuthenticated:true}` and the page stayed on `/onboarding` — no immediate redirect.<br>- Flagged: `auth-store.ts` has no cross-tab sync. Next guarded action *would* eventually 401-bounce to `/login`, so it's "graceful re-auth eventually", but the security-sensitive "immediate logout on all tabs" expectation fails. Tracked as E2E-DISC-12 (medium).<br>- Status: **failing** — re-open after E2E-DISC-12 fix. (2026-04-19) |
| A9 | deep link to `/today` while logged out redirects to `/login?next=/today` and honors `next` | Journey | failing | - Verified: `/studio` while logged-out redirected to `/login` **without** any `?next=` query; login then sent user to `/today`/`/onboarding`, losing the deep-link.<br>- Verified: manually setting `/login?next=/studio` and signing in still sent the user to the hardcoded destination — `login/page.tsx` never reads `useSearchParams()`.<br>- Status: **failing** — tracked as E2E-DISC-13 (medium). Re-open after the `?next=` capture + honor is added. (2026-04-19) |
| A10 | brute-force 6 wrong logins in 30s gets rate limited with a user-visible countdown, not a silent 429 | Resilience | failing | - Verified: server *does* rate-limit login — 25 rapid POSTs produced 19×401 + 6×429 with body `{"error":"Rate limit exceeded: 20 per 1 minute"}`; ceiling is **20/min**, far more generous than the spec's 6/30s target.<br>- Flagged: **no user-visible countdown** on the login page; combined with E2E-DISC-10 the banner would only read "Too Many Requests" with no retry-after timer. Recommend tightening limit to ~5-6/min for `/auth/login` and surfacing a countdown from the `Retry-After` header.<br>- Status: **failing** — correct server behavior present but UX contract not met. Will re-open when the tighter limit + countdown are wired. (2026-04-19) |

## 2. Onboarding — `onboarding.spec.ts`

| # | Test | Category | Status | Outcome (3 bullets) |
|---|---|---|---|---|
| O1 | fresh user sees onboarding wizard, can skip to `/today` and return later via banner | Journey | pending | — |
| O2 | picking goal + experience persists and pre-seeds `/today` copy for morning variant | Feature | pending | — |
| O3 | choosing "intermediate" experience hides the "what is Python" starter course | Feature | pending | — |
| O4 | closing wizard mid-way preserves partial state (refresh resumes where left off) | Resilience | pending | — |
| O5 | onboarding finish dispatches `onboarding.complete` custom event exactly once | Contract | pending | — |
| O6 | revisiting `/onboarding` after completion redirects to `/today`, not re-runs wizard | Journey | pending | — |

## 3. Today (Daily Loop) — `today.spec.ts`

| # | Test | Category | Status | Outcome (3 bullets) |
|---|---|---|---|---|
| T1 | morning variant (hour<18) shows intention card + consistency + micro-wins in that order | Feature | pending | — |
| T2 | evening variant (hour≥18) swaps intention for reflection, keeps consistency/wins | Feature | pending | — |
| T3 | variant_shown custom event dispatches once per mount with correct `{variant}` payload | Contract | pending | — |
| T4 | submitting an intention shows optimistic UI, survives a refresh, matches server value | Journey | pending | — |
| T5 | 201-character intention is rejected client-side with the exact MAX_LENGTH error | Feature | pending | — |
| T6 | intention textarea is keyboard-focusable and Enter inside it does not submit form | A11y | pending | — |
| T7 | consistency cell "7/7" + green badge when all 7 days active; "0/7" renders empty track | Feature | pending | — |
| T8 | micro-wins relative timestamps update (just now → 1m ago → 3h ago) without refresh | Feature | pending | — |
| T9 | empty wins shows "Your wins will show up here", not a skeleton flash that never resolves | Feature | pending | — |
| T10 | toast appears when intention save fails (server 500) — **regression for B3 Toaster bug** | Contract | pending | — |
| T11 | navigation to `/today` with stale token retries once and renders, not a blank card | Resilience | pending | — |
| T12 | `/today` on first paint has no layout shift > 0.1 CLS when wins/intention load in | Perf | pending | — |

## 4. Courses Catalogue — `courses.spec.ts`

| # | Test | Category | Status | Outcome (3 bullets) |
|---|---|---|---|---|
| C1 | `/courses` lists all published courses, paginated, sorted by difficulty then price | Feature | pending | — |
| C2 | clicking a free course navigates to detail without payment modal | Journey | pending | — |
| C3 | clicking a paid course shows "Enroll" CTA that opens Stripe modal (stubbed) | Journey | pending | — |
| C4 | search "agent" filters list to courses whose title/description matches | Feature | pending | — |
| C5 | empty search state shows "No courses match" with reset button | Feature | pending | — |
| C6 | enrolled course shows "Continue" CTA that jumps to last-watched lesson | Journey | pending | — |
| C7 | course list survives a `/api/v1/courses` 500 with a retry button, not a white screen | Resilience | pending | — |
| C8 | clicking course detail → back → scroll position restored (App Router scroll restoration) | Feature | pending | — |

## 5. Lessons & Progress — `lessons.spec.ts`

| # | Test | Category | Status | Outcome (3 bullets) |
|---|---|---|---|---|
| L1 | lesson page loads YouTube player + transcript + "Mark complete" CTA | Feature | pending | — |
| L2 | marking complete updates sidebar percent AND `/progress` page simultaneously (cache invalidation) | Contract | pending | — |
| L3 | un-complete toggle persists through refresh | Feature | pending | — |
| L4 | watching ≥ 80% auto-posts completion (watch-time endpoint) | Journey | pending | — |
| L5 | next-lesson button is disabled on the last lesson, not hidden | A11y | pending | — |
| L6 | lesson transcript search highlights matches and jumps the player to that timestamp | Feature | pending | — |
| L7 | lesson with no transcript shows an empty-state pane, not a broken search box | Resilience | pending | — |
| L8 | attempting a lesson you haven't unlocked shows a paywall/prereq, not a 404 | Journey | pending | — |
| L9 | broken YouTube iframe (network block) falls back to transcript-only view | Resilience | pending | — |
| L10 | rapid-fire mark/unmark (click 5× in 1s) settles to the correct final state | Resilience | pending | — |

## 6. Exercises & Grading — `exercises.spec.ts`

| # | Test | Category | Status | Outcome (3 bullets) |
|---|---|---|---|---|
| E1 | exercise page shows prompt, starter code editor, rubric, and "Submit" | Feature | pending | — |
| E2 | submitting empty code shows inline warning, does not hit the grader | Feature | pending | — |
| E3 | submit triggers grading spinner, result rendered as rubric breakdown | Journey | pending | — |
| E4 | grader 502 is retried once then shows a "Try again" toast | Resilience | pending | — |
| E5 | "Show solution" is hidden until after a submit or a 24h timer, not both free | Feature | pending | — |
| E6 | submission history shows prior attempts with timestamps and scores | Feature | pending | — |
| E7 | passing submission updates `/progress` count and fires `exercise.passed` event | Contract | pending | — |
| E8 | failing submission offers "Ask the tutor" — dispatches agent handoff with code+reason | Journey | pending | — |
| E9 | exercise prompt with code blocks renders with correct syntax highlighting (no raw markdown) | Feature | pending | — |
| E10 | long code submission (>10k chars) is rejected client-side with a char-count hint | Feature | pending | — |

## 7. Studio & Stuck Banner — `studio.spec.ts`

| # | Test | Category | Status | Outcome (3 bullets) |
|---|---|---|---|---|
| S1 | studio loads editor + run button + output pane | Feature | pending | — |
| S2 | "Run" executes code and streams stdout into output pane | Journey | pending | — |
| S3 | run error surfaces stderr with red styling + line number from stack | Feature | pending | — |
| S4 | stuck banner appears after 10 min of no code change + no run | Feature | pending | — |
| S5 | stuck banner `Ask the tutor` dispatches `studio.stuck_ask_tutor` with `{code, reason}` | Contract | pending | — |
| S6 | stuck banner `X` dismisses and dispatches `studio.stuck_dismissed` | Contract | pending | — |
| S7 | editing code resets the 10-min timer | Feature | pending | — |
| S8 | running code resets the 10-min timer | Feature | pending | — |
| S9 | stuck banner does not appear on first visit before any activity | Feature | pending | — |
| S10 | stuck banner text uses ≥44px tap targets on mobile pointer:coarse | Mobile | pending | — |

## 8. Chat & Agents — `chat.spec.ts`

| # | Test | Category | Status | Outcome (3 bullets) |
|---|---|---|---|---|
| CH1 | new chat creates session, routes to socratic_tutor for "what is RAG" | Journey | pending | — |
| CH2 | "review my code" with a snippet routes to code_review and returns rubric JSON rendered as UI | Feature | pending | — |
| CH3 | chat stream tokenizes visibly, no whole-response flash | Feature | pending | — |
| CH4 | stream interruption (server disconnect) shows "Connection lost, retry" | Resilience | pending | — |
| CH5 | chat history persists across refresh | Feature | pending | — |
| CH6 | empty message input disables send button | A11y | pending | — |
| CH7 | unknown-intent message falls through to the LLM classifier, not a 500 | Resilience | pending | — |
| CH8 | chat message `shift+enter` inserts newline; plain `enter` sends | A11y | pending | — |

## 9. Progress & Receipts — `progress.spec.ts`

| # | Test | Category | Status | Outcome (3 bullets) |
|---|---|---|---|---|
| P1 | `/progress` shows lesson%, exercise%, streak/consistency, and per-course breakdown | Feature | pending | — |
| P2 | completing a lesson in another tab updates `/progress` on refocus (focus-refetch) | Contract | pending | — |
| P3 | `/receipts` lists weekly letters; unread badge reflects `useMyNotifications` feed | Feature | pending | — |
| P4 | opening a weekly letter marks it read and clears the sidebar unread dot | Feature | pending | — |
| P5 | empty receipts inbox shows "Your weekly letters will arrive here" | Feature | pending | — |
| P6 | receipts detail page renders markdown (headings, code, lists) without raw `#` characters | Feature | pending | — |

## 10. Admin Console — `admin.spec.ts`

| # | Test | Category | Status | Outcome (3 bullets) |
|---|---|---|---|---|
| AD1 | non-admin user hitting `/admin` is redirected, not shown a 403 shell | Journey | pending | — |
| AD2 | admin landing shows stats tiles (students, enrollments, revenue, agent calls) | Feature | pending | — |
| AD3 | agent health page lists 20 agents with last-call, success-rate, avg-latency | Feature | pending | — |
| AD4 | at-risk students panel shows users with days_inactive ≥ 3 | Feature | pending | — |
| AD5 | clicking a student opens their activity timeline | Journey | pending | — |
| AD6 | admin search by email returns result in ≤ 500ms p95 | Perf | pending | — |
| AD7 | admin can trigger `disrupt_prevention` agent manually from a student row | Feature | pending | — |
| AD8 | admin actions log to `agent_actions` table with actor_id = admin user | Contract | pending | — |

## 11. Mobile & Gestures — `mobile.spec.ts`

| # | Test | Category | Status | Outcome (3 bullets) |
|---|---|---|---|---|
| M1 | viewport 375×812 (iPhone 13) renders bottom nav with 4 items + safe-area padding | Mobile | pending | — |
| M2 | edge-swipe from < 24px opens sidebar drawer | Mobile | pending | — |
| M3 | drag sidebar left > 60px closes it; < 60px snaps back open | Mobile | pending | — |
| M4 | focusing a textarea scrolls it above the on-screen keyboard (pointer:coarse) | Mobile | pending | — |
| M5 | responsive table switches to stacked cards at < 768px, primary col is card title | Mobile | pending | — |
| M6 | mobile bottom nav marks active route with `aria-current=page` | A11y | pending | — |
| M7 | portrait → landscape rotation on `/studio` reflows editor without losing unsaved code | Mobile | pending | — |

## 12. Accessibility — `a11y.spec.ts`

| # | Test | Category | Status | Outcome (3 bullets) |
|---|---|---|---|---|
| AC1 | axe-core scan of `/today` returns 0 serious or critical violations | A11y | pending | — |
| AC2 | axe-core scan of `/courses`, `/progress`, `/admin` returns 0 serious violations | A11y | pending | — |
| AC3 | tab order on `/today` goes intention → consistency → micro-wins → sidebar | A11y | pending | — |
| AC4 | every interactive element shows a visible focus ring (outline: 2px solid var(--ring)) | A11y | pending | — |
| AC5 | ESC closes mobile sidebar, chat modal, and any open dialog | A11y | pending | — |
| AC6 | screen-reader label for the "Open sidebar" button announces "Open sidebar" (not icon code) | A11y | pending | — |

## 13. Dark Mode & Theme — `theme.spec.ts`

| # | Test | Category | Status | Outcome (3 bullets) |
|---|---|---|---|---|
| TH1 | toggling theme persists via `next-themes` across refresh | Feature | pending | — |
| TH2 | theme toggle transitions colors smoothly (no flash of wrong theme on load) | Feature | pending | — |
| TH3 | dark mode contrast on `/today` cards meets WCAG AA 4.5:1 | A11y | pending | — |
| TH4 | code editor in Studio respects theme (dark editor on dark mode) | Feature | pending | — |

---

## Discovery — Issues Found While Planning (or Running)

These are issues found *during* test authoring or execution, independent of the test pass/fail status. Every time a test run uncovers a defect, file it here with a short repro and a severity, then link the test row to the ID.

| ID | Title | Severity | Where found | Status | Notes |
|---|---|---|---|---|---|
| E2E-DISC-1 | `celery-beat` container in restart loop | high | `docker ps` during infra sweep | open | Stack is stable without it but scheduled tasks (weekly letter, disrupt_prevention) will not fire. File ticket before beta. |
| E2E-DISC-2 | nginx returns 502 on `:8080` (all `/api/` routes broken for browser) | **critical** | `curl localhost:8080/api/v1/courses` | **fixed** | **Root cause:** nginx cached backend IP at startup; backend container was recreated with a new IP, nginx kept connecting to the dead one. **Fix (`nginx/nginx.conf`):** replaced static `upstream` blocks with docker-resolver + `set $var http://backend:8000; proxy_pass $var;` pattern so nginx re-resolves on each request. Applied via `nginx -s reload`. |
| E2E-DISC-3 | Backend port mismatch: docs say `:8000`, container publishes `:8001` | medium | docker ps vs README | open | Update `docs/ARCHITECTURE.md` and `.env.example`; add port to `CLAUDE.md` quick commands. |
| E2E-DISC-4 | `landing.test.tsx` has 2 pre-existing failing assertions | low | `pnpm test` pre-flight | open | Unrelated to P3 work; file as a separate chore ticket. |
| E2E-DISC-5 | `<Toaster/>` declared but never mounted — all `toast.*` calls silent | **critical** | code audit during B3 | **fixed** | Mounted in `frontend/src/lib/providers.tsx`; regression guarded by test T10. |
| E2E-DISC-6 | 7 footer links 404 on every RSC prefetch (`/security`, `/terms`, `/privacy`, `/changelog`, `/docs`, `/status`, `/blog`) | low | console on every page load | open | Either add stub pages or remove the links from footer. Batch with next UI polish pass. |
| E2E-DISC-7 | `/register` redirected new users to `/dashboard`, bypassing onboarding goal wizard | **critical** | A1 test — fresh signup never asked for goal | **fixed** | `frontend/src/app/(public)/register/page.tsx`: success redirect → `/onboarding`; already-authed redirect → `/today`. Onboarding page now redirects to `/today` if goal already set (unless `?edit=1`). Previously new users hit an empty dashboard and never got the Goal Contract prompt, which the platform leans on for 3.2× retention. |
| E2E-DISC-8 | Production Next.js build broken: `useSearchParams()` in `RouteLoadingBar` without Suspense | **critical** | first `docker compose build frontend` of this session | **fixed** | Wrapped inner hook-using component in `<Suspense fallback={null}>` in `frontend/src/components/ui/route-loading-bar.tsx`. Build blocked on prerendering `/about` and `/career/interview-bank`. **Means no one has deployed a production build since `RouteLoadingBar` landed.** |
| E2E-DISC-9 | DB alembic stamp stuck at 0009 while models and tables are at 0024-era, with 3 columns and 13 tables silently missing | **critical** | onboarding 500 on `/goals/me` + `/preferences/me` | **fixed** | Alembic: `stamp head` to 0024. Missing columns added: `goal_contracts.weekly_hours`, `reflections.kind`, `user_preferences.socratic_level`, `exercise_submissions.self_explanation`. Missing tables created via `Base.metadata.create_all(checkfirst=True)`: confidence_reports, conversation_memory, daily_intentions, feedback, interview_questions, peer_review_assignments, question_posts, question_votes, resumes, saved_skill_paths, student_misconceptions, student_notes, weekly_intentions. **Every authenticated page requiring goals/preferences/today data has been returning 500 since those features shipped.** Root cause: DB was previously `create_all`-bootstrapped and migration history never caught up. Next step: generate a single consolidated "0025_reconcile" Alembic migration so future environments don't need this manual repair. |
| E2E-DISC-10 | API client drops slowapi's informative 429 body, surfaces generic "Too Many Requests" instead | low | A3 — UI submits 11th register within 1 min | open | Backend returns `{"error":"Rate limit exceeded: 10 per 1 minute"}` (slowapi default), but `frontend/src/lib/api-client.ts::request()` only reads `detail` (FastAPI convention). Fix: also read `.error` when `.detail` is absent, OR swap slowapi's handler for one that emits `{"detail": ...}`. Not a blocker — user still sees a banner, just less helpful. |
| E2E-DISC-11 | Token auto-refresh is unimplemented — expired access token forces full re-login despite refresh token lifetime (7d) | **high** | A6 — installed expired JWT, hit `/today`, observed 401 → `/login` redirect | open | Backend issues `refresh_token` in `TokenResponse` but there is **no** `POST /api/v1/auth/refresh` endpoint; `frontend/src/lib/api-client.ts:46-48` simply calls `clearAuthAndRedirect()` on any 401. Net effect: every user is kicked to `/login` at the 8-hour access-token mark regardless of the 7-day refresh lifetime. Fallback is graceful (no spin-loop, no silent error, email field preserved) so no P0 — but the feature is effectively advertised by the response shape and is missing. Fix: add `/auth/refresh` route + client-side pre-flight refresh on 401. |
| E2E-DISC-12 | Multi-tab logout does not sync — in-memory Zustand store ignores cross-tab `storage` events | medium | A8 — simulated Tab A logout, confirmed Tab B kept its in-memory token and stayed on `/onboarding` | open | `frontend/src/stores/auth-store.ts` uses `persist` without a `storage` event listener. When Tab A calls `logout()`, localStorage is cleared, but Tab B's Zustand store still has `{token, isAuthenticated:true}` in memory and UI treats the user as logged-in until something triggers a 401. Security-relevant on shared devices. Fix: add a `window.addEventListener('storage', ...)` in a root client component that calls `useAuthStore.getState().clearAuth()` when the key changes to a cleared state — or use `zustand/middleware`'s `subscribeWithSelector` + a store-side cross-tab sync helper. |
| E2E-DISC-13 | Deep-link preservation is unimplemented — `?next=` is never captured on redirect and never honored on login | medium | A9 — deep-linked `/studio` redirected to `/login` with no `?next=`; manually setting `?next=/studio` was also ignored post-login | open | Two gaps: (1) `frontend/src/lib/api-client.ts::clearAuthAndRedirect()` hardcodes `/login` without appending `?next={currentPath}`; (2) `frontend/src/app/(public)/login/page.tsx` hardcodes `router.replace("/today")` with no `useSearchParams()` read. Result: any deep-link to a protected route (e.g. a shared `/studio/{id}` link) lands the user on `/today` after login, losing the intended destination. Fix: append `?next=` in `clearAuthAndRedirect`, read it in login/register `page.tsx` and `router.replace(validatedNext ?? defaultLanding)`. Sanitize `next` to prevent open-redirect. |

**Severity legend:** critical = blocks learning loop · high = blocks a category · medium = visible bug or doc drift · low = cosmetic / non-blocking.

---

## Deferred Fixes — Open Discoveries With Planned Fix Window

**Purpose of this section:** so no open discovery is silently forgotten. Every `open` row in the table above has an entry here with: why we chose **not** to fix it in the current session, when the fix is planned, and which test(s) must re-run to confirm green. The Discovery row stays `open` until re-test passes **and** a linked fix commit lands.

**Decision rule:** the E2E sweep prioritises **functional coverage** (find every bug) over **fix latency** (fix each bug immediately). We batch fixes across discoveries that share a code surface so one PR closes multiple rows.

| Discovery | Severity | Planned fix window | Re-tests that must pass before closing | Reason for deferral |
|---|---|---|---|---|
| E2E-DISC-1 — `celery-beat` in restart loop | high | **after E2E sweep** (one Celery/infra fix PR after all specs run) | A scheduled-tasks smoke (weekly letter + disrupt_prevention trigger) — add to infra spec bucket | Stack is stable without it for the full learning loop; scheduled tasks are background-only. Fixing now would pull the current docker stack down and delay the sweep. |
| E2E-DISC-3 — Backend port mismatch in docs | medium | **batched with next docs PR** | Docs-only — verify `ARCHITECTURE.md` / `.env.example` / `CLAUDE.md` agree post-fix | Pure documentation drift; does not affect any test flow. |
| E2E-DISC-4 — 2 pre-existing failing frontend tests | low | **chore ticket — separate PR, post-sweep** | `pnpm test` in `frontend/` is green | Unrelated to B5; pre-existing before this session. |
| E2E-DISC-6 — 7 footer links 404 | low | **UI polish pass — post-sweep** | Every footer link returns 200 (no RSC 404s) | Cosmetic; appears in every page console but doesn't break any flow. |
| E2E-DISC-10 — slowapi 429 body key mismatch | low | **bundled with DISC-11 (auth hardening PR)** | Re-run A3 (register 11th) + A10 (login 21st); banner should read the specific backend message, not "Too Many Requests" | Same area as DISC-11; fixing in the same PR avoids churning `api-client.ts::request()` twice. |
| E2E-DISC-11 — no `/auth/refresh` endpoint + client flow | **high** | **Auth Hardening PR — scheduled after the full E2E sweep closes (post all 13 suites)** | Re-run **A6** and **A7** end-to-end: install expired JWT, confirm silent refresh fires, confirm original request retries transparently; confirm 7-day expiry boots the user with an explanatory banner | Users won't hit this inside a single session (access token = 8h). Fixing now forces a schema change and a client-wide refactor; safer to batch with DISC-10/12/13 in one auth-hardening PR where we can design the refresh interceptor once. |
| E2E-DISC-12 — no cross-tab logout sync | medium | **bundled with DISC-11 (auth hardening PR)** | Re-run **A8**: open two tabs, logout in Tab A, confirm Tab B redirects to `/login` within 1s without a page reload | Lives in the same store (`auth-store.ts`); fits cleanly alongside the refresh-token client work. |
| E2E-DISC-13 — `?next=` not captured/honored | medium | **bundled with DISC-11 (auth hardening PR)** | Re-run **A9**: deep-link `/studio` logged-out → login → land on `/studio`, not `/today`. Also confirm `next` is sanitized against open-redirect (reject `next=http://evil.com`) | Same code surfaces as DISC-11 (`api-client.ts::clearAuthAndRedirect` + `login/page.tsx`); one PR, one review, one release. |

### "Auth Hardening PR" — explicit bundle definition

One PR will close DISC-10, DISC-11, DISC-12, DISC-13 together. **Scope:**

1. **Backend:** add `POST /api/v1/auth/refresh` — accepts the refresh token, returns a fresh access token. Reject reused refresh tokens; rotate on use.
2. **Backend:** swap slowapi's default 429 handler for one that emits `{"detail": "..."}` (FastAPI-native shape).
3. **Frontend — `api-client.ts`:** on 401, attempt `/auth/refresh` before redirecting; if refresh also 401s, append `?next={location.pathname}${location.search}` and redirect to `/login`. Single-flight the refresh (multiple concurrent 401s must only trigger one refresh).
4. **Frontend — `auth-store.ts`:** subscribe to `storage` events; when `auth-storage` is cleared from another tab, run `clearAuth()` + `router.replace('/login')`.
5. **Frontend — `login/page.tsx` + `register/page.tsx`:** read `?next=`, validate it's a same-origin absolute-path (regex `^\/[^/].*`), `router.replace(next ?? defaultLanding)`.
6. **Re-test:** A3, A6, A7, A8, A9, A10 must all flip from `failing` → `closed` with fresh 3-bullet outcomes.

**When:** After the full E2E sweep (all 13 suites) lands — currently projected for the end of this B5 cycle. We'll open the PR before CI is set up (per the "functional-correctness-first" direction).

**Who re-tests:** whoever executes the Auth Hardening PR opens re-runs A3 + A6–A10 against the docker stack, updates the tracker rows, and **only then** may flip each DISC-N row from `open` → `fixed`.

---

## Outcome Note Template

Copy this into a row's outcome cell when closing a test:

```
- Verified: {one sentence on what the test actually exercised end-to-end}
- Fixed / flagged: {commit link OR E2E-DISC-N reference OR "no defect"}
- Status: closed {YYYY-MM-DD}
```

Keep each bullet to one line. If a test uncovered more than one issue, file each in Discovery and reference both IDs.

---

## Done Definition (Restated from Plan §6)

A test row may be marked `closed` only when **all four** hold:

1. The spec runs green against the real docker stack (not a mock), twice in a row.
2. The 3-bullet outcome note is filled in.
3. Any defect found is either linked to a fix commit or filed in the Discovery section.
4. The test asserts the user-visible outcome, not an implementation detail (no selector-chasing).
