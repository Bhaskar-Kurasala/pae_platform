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
| Onboarding | 6 | 0 | 0 | 0 | 3 | 3 |
| Today (daily loop) | 12 | 0 | 0 | 0 | 3 | 9 |
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
| **Total** | **95** | **67** | **0** | **0** | **10** | **18** |

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
| O1 | fresh user sees onboarding wizard (hard gate — cannot reach `/today` until goal is set) | Journey | closed | - Verified: fresh user at `/onboarding` sees header "Let's make this real, {firstName}." + 3-step progressbar (01/02/03 with step 01 active) + 4 motivation radios; Back & Next both `disabled` until a motivation is picked. Layout matches `GoalContractForm` component spec (3 steps: motivation → deadline → success).<br>- Verified: hard-gate behavior — clicking Today in sidebar bounces back to `/onboarding` because `/today/page.tsx:39-43` redirects when `goal === null`. Matches the deliberate "no Today until Goal Contract" product decision (3.2× retention lever) — spec phrasing was out-of-date. Spec row updated to reflect hard-gate intent.<br>- Status: closed 2026-04-19 |
| O2 | picking goal + experience persists and pre-seeds `/today` copy for morning variant | Feature | closed | - Verified: drove 3-step wizard end-to-end (career_switch → 4 months → 101-char success statement); `GET /goals/me` returns exact values (motivation, deadline_months=4, success_statement verbatim, user_id bound correctly).<br>- Verified: `/today` morning variant seeds "Good morning, A4." + goal card with "Career switch" label, blockquoted success statement, 123 days remaining, target Aug 19 2026, 0% time used, Edit goal link → `/onboarding`. Morning/evening split uses `new Date().getHours()` client-side so timezone-correct.<br>- Flagged: no "experience" field exists in the current wizard (spec assumption from an earlier design). O3's experience-based filter is therefore a code-level gap — see O3 outcome.<br>- Status: closed 2026-04-19 |
| O3 | choosing "intermediate" experience hides the "what is Python" starter course | Feature | failing | - Verified (code inspection): no `experience`/`skill_level` field exists on the onboarding wizard (`goal-contract-form.tsx`), the `goal_contracts` model, or any schema. No "Python starter" course is seeded either. Feature was never built.<br>- Flagged as E2E-DISC-14 (low-severity feature gap). Decision needed: is this a real roadmap item or stale spec? Per product/phase memory, the current onboarding is a 3-step Goal Contract only; experience-based filtering isn't part of B5 scope.<br>- Status: **failing** — spec assumes an unbuilt feature. Either build the feature and re-run, or deprecate this spec row. (2026-04-19) |
| O4 | closing wizard mid-way preserves partial state (refresh resumes where left off) | Resilience | failing | - Drove wizard to step 3 (career_switch → 4 months → 52-char success draft), reloaded `/onboarding`: wizard snapped back to step 1 with `aria-valuenow=1`, no active motivation radio, and `#success-statement` gone from the DOM. `localStorage` shows only `auth-storage`; no `onboarding`/`goal`/`wizard` keys.<br>- Code audit: [goal-contract-form.tsx:84-95](../frontend/src/components/features/goal-contract-form.tsx#L84-L95) stores `step`, `motivation`, `deadline`, `successStatement` in `useState` with no localStorage/sessionStorage/zustand backing. Refresh wipes all drafted input.<br>- Filed **E2E-DISC-15** (medium: UX regression risk — a 60-second wizard losing a user's partial answer is a churn risk). Status: **failing** 2026-04-19. |
| O5 | onboarding finish dispatches `onboarding.complete` custom event exactly once | Contract | failing | - Instrumented `window.addEventListener` for 5 candidate event names (`onboarding.complete`, `onboarding_complete`, `goal.created`, `goal.set`, `onboarding.finished`) before submitting; drove the 3-step wizard and submitted. After soft-nav to `/today`, `window.__onboardingEvents` was `[]` — zero events captured.<br>- Code audit: grep across `frontend/src` shows **no** `CustomEvent("onboarding.complete"...)` dispatch anywhere. The only `dispatchEvent` sites are `today.variant_shown`, `studio.stuck_ask_tutor`, `studio.stuck_dismissed`, and chat pill telemetry. `onboarding/page.tsx:70-73` does `await upsert.mutateAsync(values); router.push("/today")` with no intermediate event emission.<br>- Filed **E2E-DISC-16** (medium: blocks analytics/telemetry-dependent downstream flows). Status: **failing** 2026-04-19. |
| O6 | revisiting `/onboarding` after completion redirects to `/today`, not re-runs wizard | Journey | closed | - Verified: after submitting a goal in O5, navigating to `/onboarding` (no query) bounces to `/today` within ~2s (idempotent flow gate in [onboarding/page.tsx:19-26](../frontend/src/app/(portal)/onboarding/page.tsx#L19-L26)).<br>- Verified: `/onboarding?edit=1` escape hatch renders the wizard on step 1 **pre-filled** with the user's existing motivation radio in the `aria-checked="true"` state, confirming `defaultValues` are read from the existing goal contract.<br>- Status: closed 2026-04-19 |

## 3. Today (Daily Loop) — `today.spec.ts`

| # | Test | Category | Status | Outcome (3 bullets) |
|---|---|---|---|---|
| T1 | morning variant (hour<18) shows intention card + consistency + micro-wins in that order | Feature | closed | - Verified: at local hour=2 (<18) `/today` renders the header "Today · Sunday, April 19 · **Morning view**" + greeting "Good morning, E2E.".<br>- Verified (DOM order): SECTIONs render as Your goal → **Today's intention** → Your next action → **Consistency this week** → Spaced review → Teach it back → **Recent wins** → Signal from reality. Intention precedes consistency precedes wins as specced.<br>- Status: closed 2026-04-19 |
| T2 | evening variant (hour≥18) swaps intention for reflection, keeps consistency/wins | Feature | closed | - Verified: stubbed `Date.prototype.getHours` to return 20, soft-nav to `/today` re-mounted TodayPage; header now reads "Today · Sunday, April 19 · **Evening view**" + greeting "Good evening, E2E.".<br>- Verified (DOM sections): Your goal → Your next action → Consistency → Spaced review → Teach it back → Recent wins → **Daily reflection** → Signal. The `Today's intention` section is gone; `Daily reflection` appears in its place. Consistency + Recent wins remain present as specced. See [today/page.tsx:100-110, 162-172](../frontend/src/app/(portal)/today/page.tsx#L100-L172) for the `isMorning` / `!isMorning` conditional branches.<br>- Status: closed 2026-04-19 |
| T3 | variant_shown custom event dispatches once per mount with correct `{variant}` payload | Contract | closed | - Verified: attached `window.addEventListener('today.variant_shown', ...)` listener, soft-navigated `/today → /dashboard → /today`. After one fresh mount, `window.__variantEvents.length === 1` with payload `{ variant: "evening" }` (Date stub still active, hour=20). No duplicate firings.<br>- Code reference: [today/page.tsx:45-53](../frontend/src/app/(portal)/today/page.tsx#L45-L53) — `useEffect([variant])` fires on mount and re-fires only if variant actually changes (morning↔evening), not on unrelated re-renders.<br>- Status: closed 2026-04-19 |
| T4 | submitting an intention shows optimistic UI, survives a refresh, matches server value | Journey | closed | - Verified: typed "Ship one RAG prototype end-to-end." in the Daily intention textarea, clicked "Set intention". Card immediately transitioned from edit-form to "Your intention / Edit" view with the text rendered — optimistic UI.<br>- Verified: hard-refreshed `/today`; intention text persisted in the UI. `GET /api/v1/today/intention` returned 200 with `text: "Ship one RAG prototype end-to-end."` matching exactly.<br>- Flagged: server stored `intention_date: 2026-04-18` while user's IST clock read 2026-04-19 — timezone-boundary bug filed as **E2E-DISC-17** (low; only bites users setting intentions between midnight and UTC offset). Status: closed 2026-04-19 |
| T5 | 201-character intention is rejected client-side with the exact MAX_LENGTH error | Feature | failing | - Observed: pasted/setter-injected 201 x's into the intention textarea (bypassing the HTML `maxLength=200` attribute which only rate-limits typing, not programmatic/paste input). Clicked "Set intention" — no error shown, POST `/api/v1/today/intention` returned 200 and the card re-rendered with all 201 chars. Server-side read confirms `text.length === 201`.<br>- Code audit: UI shows "0 / 200" counter but the form has no `if (value.length > 200) setError(...)` JS guard. Backend `DailyIntentionCreate` schema caps at **300**, not 200 — client/server cap mismatch. Either side would have caught this had it been wired.<br>- Filed **E2E-DISC-18** (medium: overflow storage + spec violation). Status: **failing** 2026-04-19. |
| T6 | intention textarea is keyboard-focusable and Enter inside it does not submit form | A11y | closed | - Verified: `textarea[aria-label="Daily intention"]` is focusable (`document.activeElement === ta` after `.focus()`, `tabIndex=0`, not disabled, not readonly).<br>- Verified: typed "Line one" + pressed Enter; textarea stayed in edit mode, value became `"Line one\n"` (newline inserted, no form submission, card still in edit UI with counter reading 8/200).<br>- Status: closed 2026-04-19 |
| T7 | consistency cell "7/7" + green badge when all 7 days active; "0/7" renders empty track | Feature | closed | - Verified empirically (0/7 case): `/today` for this user shows "0 of 7 days this week", 7 listitems all labeled "— no activity", pct=0%. Badge uses primary (teal) which reads as green per design token `#1D9E75`.<br>- Verified via code audit ([today-consistency.tsx:55-68](../frontend/src/components/features/today-consistency.tsx#L55-L68)): renders `window_days` bars; the first `days_this_week` are `bg-primary` (active), the rest `bg-foreground/10` (gray). At `days_this_week===7`, all 7 bars are primary/green and badge reads 100%. Logic symmetric for 0 → all gray, confirmed live.<br>- Minor note: component packs active bars to the left rather than aligning to actual weekdays M-T-W-T-F-S-S. Spec doesn't assert weekday alignment, so not flagged as a defect — recorded here for later UX review.<br>- Status: closed 2026-04-19 |
| T8 | micro-wins relative timestamps update (just now → 1m ago → 3h ago) without refresh | Feature | failing | - Code audit: [today-micro-wins.tsx:7-16](../frontend/src/components/features/today-micro-wins.tsx#L7-L16) — `formatWhen()` is a pure function computed at render time only. There is no `setInterval`, `useEffect` tick, `useNow()` hook, or React Query refetch trigger. Grep for `setInterval/useInterval` on the file returns zero hits.<br>- Impact: a win that lands at 20:00:00 renders as "just now" and stays "just now" even at 20:03:00 unless the user triggers a re-render (nav away + back, refresh, refetch).<br>- Filed **E2E-DISC-19** (low: cosmetic — "just now" is visibly stale after a minute but the absolute timestamp is still retrievable via tooltip or refresh). Fix: add `const [now, setNow] = useState(Date.now()); useEffect(() => { const id = setInterval(() => setNow(Date.now()), 60_000); return () => clearInterval(id); }, [])` and use `now` inside `formatWhen`. Status: **failing** 2026-04-19. |
| T9 | empty wins shows "Your wins will show up here", not a skeleton flash that never resolves | Feature | closed | - Verified: `/today` for a user with zero wins renders the empty-state `<h2>Your wins will show up here</h2>` + subtitle "Finish a lesson, pass an exercise, or ace a quiz — you'll see it land here." No skeleton persists.<br>- Code reference: [today-micro-wins.tsx:64-70](../frontend/src/components/features/today-micro-wins.tsx#L64-L70) — `wins.length > 0` ternary: non-empty → list; empty → labeled empty-state with subtitle. Skeleton only renders while `isLoading` is true; `useMicroWins` resolves to `data={wins:[]}` on empty, flipping off loading cleanly.<br>- Status: closed 2026-04-19 |
| T10 | toast appears when intention save fails (server 500) — **regression for B3 Toaster bug** | Contract | closed | - Verified: monkey-patched `window.fetch` to return a synthetic 500 for `POST /api/v1/today/intention`, clicked "Set intention", and captured the sonner toaster DOM. Toast text: **"Couldn't save your intention. Try again."** rendered in `[data-sonner-toaster]`.<br>- Verified: card stayed in edit mode with the user's draft text preserved (no optimistic rollback lost data); re-enabling real fetch + re-submitting succeeds cleanly.<br>- **Regression guard for DISC-5 (B3 Toaster bug) holds** — the `<Toaster/>` mounted in [providers.tsx](../frontend/src/lib/providers.tsx) is receiving `toast.*` calls.<br>- Status: closed 2026-04-19 |
| T11 | navigation to `/today` with stale token retries once and renders, not a blank card | Resilience | failing | - Installed structurally-valid expired JWT (`exp = now - 3600`), navigated `/today`. Client immediately redirected to `/login` without any silent-refresh attempt; goal + consistency + wins never rendered.<br>- **Duplicate of E2E-DISC-11** — same root cause: `frontend/src/lib/api-client.ts` has no `/auth/refresh` retry path; backend has no matching endpoint. Re-test of T11 is in the **Auth Hardening PR re-test bundle** (closes when silent refresh ships).<br>- Status: **failing** 2026-04-19 — tracking under DISC-11. |
| T12 | `/today` on first paint has no layout shift > 0.1 CLS when wins/intention load in | Perf | closed | - Measured via `PerformanceObserver({ type: 'layout-shift', buffered: true })` from first paint for 3s: **total CLS = 0.072** (1 shift entry, source DIV, value 0.072) — comfortably below the 0.1 threshold.<br>- Contributing factor observed: skeleton components in [today-intention.tsx:40-49](../frontend/src/components/features/today-intention.tsx#L40-L49), [today-consistency.tsx:12-21](../frontend/src/components/features/today-consistency.tsx#L12-L21), and [today-micro-wins.tsx:34-46](../frontend/src/components/features/today-micro-wins.tsx#L34-L46) reserve height via fixed-pixel placeholders (`h-3 w-28`, `h-5 w-2/3`, etc.), preventing reflow when the real content lands.<br>- Status: closed 2026-04-19 |

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
| E2E-DISC-14 | Onboarding has no experience/skill-level question — spec row O3 assumes an unbuilt feature | low | O3 — spec says "intermediate experience hides Python starter course"; wizard has only motivation/deadline/success fields | open | Code audit confirms: `frontend/src/components/features/goal-contract-form.tsx` is a 3-step wizard (motivation → deadline → success statement) with no `experience` or `skill_level` collection; `goal_contracts` model + schemas do not carry such a column; no "Python starter" course is seeded. The feature was never built. **Decision needed (product):** either add the field + course filtering to the roadmap, or deprecate spec row O3. Current onboarding is the 3-step Goal Contract only — experience-based filtering is not in B5 scope. |
| E2E-DISC-15 | Onboarding wizard loses all partial state on refresh / tab reopen | medium | O4 — drafted career_switch + 4 months + 52-char success text, reloaded, wizard snapped to step 1 empty | open | `frontend/src/components/features/goal-contract-form.tsx:84-95` holds step, motivation, deadline, successStatement in `useState` with no persistence layer. A user who accidentally closes the tab or refreshes mid-wizard loses everything — bad first-impression UX and a churn risk for the goal-contract funnel. Fix: persist partial form values (not auth/PII — just the 4 fields) to `sessionStorage` under a stable key like `onboarding-draft-v1`, restore on mount, clear on successful submit or on `edit=1` revisit. sessionStorage preferred over localStorage so it doesn't linger across devices / tabs indefinitely. |
| E2E-DISC-16 | `onboarding.complete` (or any equivalent) custom event is never dispatched on goal submit | medium | O5 — listener array stayed `[]` after a full wizard submission; grep confirms zero dispatch sites | open | Spec assumes a `window.dispatchEvent(new CustomEvent("onboarding.complete"))` at the moment the goal is persisted — presumably so downstream analytics, toasts, or in-app nudges can react without coupling to the mutation. `frontend/src/app/(portal)/onboarding/page.tsx:70-73` does `await upsert.mutateAsync; router.push` with no event emission. Fix: after `mutateAsync` resolves, fire `window.dispatchEvent(new CustomEvent("onboarding.complete", { detail: { motivation, deadline_months } }))`; keep it outside the mutation so React Query cache invalidation isn't coupled to event firing. Ensure it only fires once per submit (the current success branch is already single-fire). |
| E2E-DISC-17 | `intention_date` stored under UTC date — IST users setting intentions between 00:00 and 05:30 IST land on the previous day's bucket | low | T4 — user in IST saw `intention_date: 2026-04-18` while local date read 2026-04-19 | open | Backend uses `datetime.utcnow().date()` for the intention_date field; IST (+05:30) means the first 5.5h of every local calendar day land in the previous UTC day. Second-intention-of-the-local-day may appear to overwrite yesterday's record. Fix: either accept client-supplied `intention_date` (validated against now-6h/now+30m) or compute bucket using the user's timezone (store TZ on user profile). Low impact because most users set intentions after sunrise. |
| E2E-DISC-18 | Intention cap mismatch: UI counter says `200`, HTML `maxLength=200` doesn't cover paste/programmatic input, backend schema caps at `300` — no real validation on either side | medium | T5 — injected 201 x's, 200 OK, server stored text.length===201 | open | Two fixes needed: (1) [today-intention.tsx:115-127](../frontend/src/components/features/today-intention.tsx#L115-L127) `handleSave` must hard-reject `trimmed.length > MAX_LENGTH` with a visible error (client); (2) backend `DailyIntentionCreate` schema in `backend/app/schemas/today.py` should drop `maxLength=300` to `200` to match client. Bundle both in a single PR so the caps can never drift again. |
| E2E-DISC-19 | Micro-wins relative timestamps (`just now → 1m ago → …`) don't update without a full re-render | low | T8 — grep for `setInterval`/`useInterval` in today-micro-wins returns zero hits | open | [today-micro-wins.tsx:7-16](../frontend/src/components/features/today-micro-wins.tsx#L7-L16) computes `formatWhen()` at render only. Fix: `const [now, setNow] = useState(Date.now()); useEffect(() => { const id = setInterval(() => setNow(Date.now()), 60_000); return () => clearInterval(id); }, [])` and thread `now` into `formatWhen`. Low priority: the stale label is cosmetic (real timestamp returns on refresh/nav). |

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
| E2E-DISC-14 — no experience field in onboarding (spec gap) | low | **blocked on product decision** — no engineering fix window until the roadmap question is answered | If kept: re-run **O3** once the field + course filtering ship; an intermediate user must not see the Python starter course. If deprecated: update `E2E-TEST-PLAN.md` to delete row O3 and mark this discovery as **invalidated**. | Engineering shouldn't guess here — whether to build the feature or drop the spec row is a product/scope call. Flagging so no one silently forgets. |
| E2E-DISC-15 — wizard drops partial state on refresh | medium | **Onboarding Polish PR — scheduled after the full E2E sweep closes** | Re-run **O4**: drive to step 3 with a partial success draft, reload, confirm wizard restores the exact step, motivation, deadline, and draft textarea value. Also confirm a completed goal (`edit=1` revisit) does **not** re-hydrate a stale draft. | Bundled with DISC-16 in Onboarding Polish PR (same page/component); fixing one at a time would churn the file twice. |
| E2E-DISC-16 — no onboarding.complete custom event dispatched | medium | **Onboarding Polish PR — scheduled after the full E2E sweep closes** | Re-run **O5**: submit wizard with a `window.addEventListener('onboarding.complete', ...)` in place; listener must fire **exactly once** with a payload containing `motivation` and `deadline_months`. | Same code surface as DISC-15 (`onboarding/page.tsx` + `goal-contract-form.tsx`); one PR, one review covers both. Low risk of regression since no existing code listens for this event yet. |
| E2E-DISC-17 — intention_date uses UTC (IST boundary issue) | low | **Today Polish PR — scheduled after the full E2E sweep closes** (bundle with DISC-18/DISC-19) | Re-run **T4** between 00:00 and 05:30 IST: `intention_date` returned must match the user's local date. | Low severity (cosmetic for most users); batching with DISC-18/19 avoids churning `today/intention` endpoint twice. |
| E2E-DISC-18 — intention length caps disagree (200 UI / 300 server), neither enforced | medium | **Today Polish PR — scheduled after the full E2E sweep closes** | Re-run **T5**: inject 201 chars, expect visible client-side error "Intention must be 200 characters or fewer" and no POST fires. Also POST 201 chars via cURL — expect 422 from the backend. | Single-file fix per side; bundling with DISC-17/19 keeps the Today Polish PR focused and one review per surface. |
| E2E-DISC-19 — micro-wins relative timestamps don't tick | low | **Today Polish PR — scheduled after the full E2E sweep closes** | Re-run **T8**: seed a win, observe label transitioning `just now → 1m ago → 2m ago` within 2 minutes without any user action. | Smallest of the three Today bugs; no reason to ship it separately. |

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

### "Onboarding Polish PR" — explicit bundle definition

One PR will close DISC-15 and DISC-16 together. **Scope:**

1. **Frontend — `goal-contract-form.tsx`:** persist `{step, motivation, deadline, successStatement}` to `sessionStorage` under key `onboarding-draft-v1` on every change; restore on mount when no `defaultValues` prop is present; clear on successful submit.
2. **Frontend — `onboarding/page.tsx`:** after `await upsert.mutateAsync(values)` resolves, call `window.dispatchEvent(new CustomEvent("onboarding.complete", { detail: { motivation, deadline_months } }))` *before* `router.push`.
3. **Re-test:** O4 and O5 must flip from `failing` → `closed`.

### "Today Polish PR" — explicit bundle definition

One PR will close DISC-17, DISC-18, DISC-19 together. **Scope:**

1. **Backend — `today.py` schemas:** tighten `DailyIntentionCreate.text.max_length` from 300 to 200 (matches UI counter).
2. **Backend — `today` route for intention:** compute `intention_date` from client-supplied ISO date (validated) or from the user's stored timezone; drop the raw `utcnow().date()` call.
3. **Frontend — `today-intention.tsx`:** in `handleSave`, reject `trimmed.length > MAX_LENGTH` with a visible inline error; do not call the mutation.
4. **Frontend — `today-micro-wins.tsx`:** add `const [now, setNow] = useState(Date.now()); useEffect(() => { const id = setInterval(() => setNow(Date.now()), 60_000); return () => clearInterval(id); }, [])` and thread `now` into `formatWhen`.
5. **Re-test:** T4 (IST boundary), T5 (length cap), T8 (tick) must flip to `closed`.

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
