# Production-readiness test tracker

Living document. Last updated: 2026-05-14.

Owner: founder. Update every time a test is run or an edge case is
discovered. The `Status` column uses:

- ✅ — passed in browser/integration
- ❌ — failed; bug filed or fix shipped
- ⚠️ — partial / blocked / needs infra
- 🔲 — not yet tested
- 🔁 — deferred (post-launch acceptable)

---

## Section 1 — Tested so far (MCP browser audit, 2026-05-13)

### 1.1 Auth & navigation

| # | Test case | Status | Notes |
|---|-----------|--------|-------|
| 1.1.1 | Student login (cp3-smoke-student@example.com) | ✅ | Lands on /today |
| 1.1.2 | Admin login (admin-1776497996@example.com) | ✅ | Lands on /admin |
| 1.1.3 | Direct nav to `/logout` (was 404) | ✅ | Fixed in `ad43f2d` — now redirects to /login |
| 1.1.4 | Logout clears auth state | ✅ | Verified — login form re-rendered |

### 1.2 Chat (student)

| # | Test case | Status | Notes |
|---|-----------|--------|-------|
| 1.2.1 | Send a chat message → assistant response streams | ✅ | "Say hi…" round-trip clean |
| 1.2.2 | Quiz pregenerate 422 on every send | ✅ | Fixed in `ad43f2d` — content non-empty guard |
| 1.2.3 | Stale `?c=` ID produces 404 spam | ✅ | Fixed in `425602c` — self-heals to /chat |

### 1.3 Admin pages (admin role)

| # | Test case | Status | Notes |
|---|-----------|--------|-------|
| 1.3.1 | /admin home renders | ✅ | 0 errors |
| 1.3.2 | /admin/students | ✅ | 0 errors |
| 1.3.3 | /admin/courses | ✅ | 0 errors |
| 1.3.4 | /admin/at-risk | ✅ | 0 errors |
| 1.3.5 | /admin/audit-log | ✅ | 0 errors |
| 1.3.6 | /admin/confusion | ✅ | 0 errors |
| 1.3.7 | /admin/content | ✅ | 0 errors |
| 1.3.8 | /admin/content-performance | ⚠️ | Redirects to /admin/content — intentional? |
| 1.3.9 | /admin/pulse | ✅ | 0 errors |

### 1.4 Authz boundaries

| # | Test case | Status | Notes |
|---|-----------|--------|-------|
| 1.4.1 | Student → /api/v1/admin/students | ✅ | 403 |
| 1.4.2 | Student → /api/v1/admin/audit-log | ✅ | 403 |
| 1.4.3 | Student → /api/v1/admin/pulse | ✅ | 403 |
| 1.4.4 | Student → other student's conversation | ✅ | 404 (canonical safe response — no info leak) |

### 1.5 Mobile / responsive

| # | Test case | Status | Notes |
|---|-----------|--------|-------|
| 1.5.1 | 375×812 viewport — /today | ✅ | 0 errors |
| 1.5.2 | 375×812 viewport — /chat | ✅ | 0 errors |
| 1.5.3 | 375×812 viewport — /catalog | ✅ | 0 errors |

### 1.6 Payments

| # | Test case | Status | Notes |
|---|-----------|--------|-------|
| 1.6.1 | GET /api/v1/payments/orders responds | ✅ | 200 |
| 1.6.2 | Razorpay test-mode checkout flow | ⚠️ | Skipped — no Razorpay creds wired in dev |

---

## Section 2 — Edge cases identified, not yet tested

Brainstormed 2026-05-13. **High** rows are launch-blockers or close
to it. **Medium** rows worth checking but acceptable to launch with
unknowns. **Low** rows are post-launch polish.

### 2.1 Auth & sessions

| # | Test case | Priority | Status | Notes |
|---|-----------|----------|--------|-------|
| 2.1.1 | Expired access token mid-SSE stream — does refresh kick in or does stream die silently? | High | 🔲 | |
| 2.1.2 | Two tabs, one user — logout in tab A; tab B still operates until next 401 | Low | 🔲 | |
| 2.1.3 | Refresh-token rotation race — two parallel 401s both try to refresh | Medium | 🔲 | |
| 2.1.4 | Login with leading/trailing whitespace in email | Medium | 🔲 | Trim on frontend AND backend? |
| 2.1.5 | Password reset flow exists + works end-to-end | **High** | ❌ | **No endpoint found**. grep for `password.?reset\|forgot.?password\|reset_token` in routes/ returned 0. Launch blocker — users have no recovery path. |
| 2.1.6 | Email verification on signup — required? Bypassable? | Medium | 🔲 | |
| 2.1.7 | "Remember me" / session persistence across browser restart | Low | 🔲 | |
| 2.1.8 | Email enumeration on signup ("user exists" vs "ok") | **High** | ❌ | Existing email → 409; new email → 201. Distinct response codes = enumeration leak. Recommend returning 201/202 for both and emailing differentiated content out-of-band. |

### 2.2 Chat & streaming

| # | Test case | Priority | Status | Notes |
|---|-----------|----------|--------|-------|
| 2.2.1 | User closes tab mid-stream — does backend stop generating? | **High** | 🔲 | Burns LLM tokens otherwise |
| 2.2.2 | Network drop mid-stream — UI shows recoverable error or hangs? | Medium | 🔲 | |
| 2.2.3 | Double-submit while stream in flight — send button disabled? | Medium | 🔲 | |
| 2.2.4 | Empty / whitespace-only message — API 422 cleanly? | Low | 🔲 | Frontend likely blocks |
| 2.2.5 | Very long message (>20KB paste) — UX when exceeded? | Medium | 🔲 | |
| 2.2.6 | XSS / markdown injection in assistant output | **High** | ✅ | Fixed in `9ea91a2`. 3 sites of `dangerouslySetInnerHTML` audited: v8-topbar (hardcoded literals — safe), path-screen (already comment-disabled), admin/page.tsx (real XSS sink via user-controlled `full_name`/`exercise.title` → now renders as text). |
| 2.2.7 | Mode switch mid-conversation — applies to next message or retroactive? | Low | 🔲 | |

### 2.3 Cost ceilings & rate limits

| # | Test case | Priority | Status | Notes |
|---|-----------|----------|--------|-------|
| 2.3.1 | Hitting daily cost ceiling mid-stream — graceful abort? | Medium | 🔲 | |
| 2.3.2 | SlowAPI rate-limit response — frontend shows meaningful message? | Medium | 🔲 | |
| 2.3.3 | Midnight IST rollover mid-conversation — ceiling resets cleanly? | Low | 🔲 | |

### 2.4 Data integrity

| # | Test case | Priority | Status | Notes |
|---|-----------|----------|--------|-------|
| 2.4.1 | Account self-deletion (GDPR endpoint exists?) | Medium | 🔲 | Matters when first EU user signs up |
| 2.4.2 | Edit a message with child quiz/notebook attached — orphans? | Medium | 🔲 | |
| 2.4.3 | Concurrent edits from two tabs to same message | Low | 🔲 | |
| 2.4.4 | Conversation deletion cascade (notebook, quiz, flashcards) | Medium | 🔲 | |

### 2.5 Network / infra

| # | Test case | Priority | Status | Notes |
|---|-----------|----------|--------|-------|
| 2.5.1 | Backend cold start — frontend retries? | Low | 🔲 | |
| 2.5.2 | Nginx restart mid-request — graceful 502 + retry? | Low | 🔲 | |
| 2.5.3 | Slow LLM response (>30s) — proxy/keepalive timeout? | Medium | 🔲 | |

### 2.6 Browser / device

| # | Test case | Priority | Status | Notes |
|---|-----------|----------|--------|-------|
| 2.6.1 | Safari iOS — SSE + send-on-enter + IME | Medium | 🔲 | |
| 2.6.2 | Browser back button from /chat?c=ID → scroll + hydrate clean? | Low | 🔲 | |
| 2.6.3 | Screen-reader signup → chat-send a11y flow | 🔁 | 🔲 | Post-launch |
| 2.6.4 | Dark mode persists across refresh + login/logout | Low | 🔲 | |

### 2.7 Security (IDOR sweep — same probe as 1.4.4 across other resources)

| # | Test case | Priority | Status | Notes |
|---|-----------|----------|--------|-------|
| 2.7.1 | Student A → student B's notebook entry (PATCH + DELETE) | **High** | ✅ | Both 404 — owner-scoped query is correct. |
| 2.7.2 | Student A → student B's flashcards | 🔁 | N/A | No flashcards table — they live as JSON inside notebook_entries; covered by 2.7.1. |
| 2.7.3 | Student A → student B's quiz attempts | Medium | 🔲 | `quiz_results` table has no `user_id` column — needs separate audit of how ownership is enforced. |
| 2.7.4 | Student A → student B's mock-interview report | Medium | 🔲 | `mock_session_reports` has no `user_id` column — needs separate audit. |
| 2.7.5 | Student A → student B's portfolio (GET /receipts/autopsy/{id}) | **High** | ✅ | 404 — owner-scoped query is correct. |
| 2.7.6 | File-upload MIME check (chat attachments) | Medium | 🔲 | |
| 2.7.7 | File-upload size limit | Medium | 🔲 | |
| 2.7.8 | File-upload path traversal in filenames | Medium | 🔲 | |
| 2.7.9 | `.env` excluded from docker image + git | **High** | ✅ | `.gitignore` excludes `.env`; backend container has no `/app/.env` (confirmed via `ls`). |
| 2.7.10 | CORS allowlist — rejects `null` and `*` | Medium | 🔲 | |

### 2.8 Operational

| # | Test case | Priority | Status | Notes |
|---|-----------|----------|--------|-------|
| 2.8.1 | Sentry receives events in prod | **High** | 🔲 | Verify post-deploy with a forced exception |
| 2.8.2 | Honeycomb spans flowing in prod | **High** | 🔲 | Verify post-deploy |
| 2.8.3 | Backup job runs + restore tested | **High** | 🔲 | Launch blocker |
| 2.8.4 | Migration 0067 rollback exists + tested | **High** | ⚠️ | `downgrade()` exists and drops the column cleanly. Live rollback dry-run still 🔲. |

---

## Section 3 — Fixes shipped during this audit

| Commit | Fix |
|--------|-----|
| `ad43f2d` | /logout route (was 404); chat quiz pregenerate 422 race-condition guard; docker-compose API URL realigned to :8001 |
| `425602c` | Stale conversation 404 self-heal (strip `?c=` + clear localStorage) |
| `9ea91a2` | XSS in admin retention feed (event.text rendered as HTML; full_name was user-controlled) — render as text |

---

---

## Section 2 — Batch 1 automated test coverage (2026-05-14)

### 2.1 Auth API (pytest, tests/test_api/test_auth.py)

| # | Test case | Status | Notes |
|---|-----------|--------|-------|
| 2.1.1 | Register returns 202 + neutral message | ✅ | D-B |
| 2.1.2 | Duplicate email registration returns 202 (not 409) | ✅ | D-B enumeration prevention |
| 2.1.3 | Password < 12 chars rejected 422 | ✅ | D-D |
| 2.1.4 | WhatsApp number accepted on register | ✅ | D16/CP3.1 |
| 2.1.5 | Login success (verified user) | ✅ | D-C |
| 2.1.6 | Login blocked for unverified user (403) | ✅ | A2 |
| 2.1.7 | Login wrong password (401) | ✅ | D-C |
| 2.1.8 | Login unknown email (401) | ✅ | D-C |
| 2.1.9 | GET /me returns user data | ✅ | |
| 2.1.10 | GET /me with invalid token (401) | ✅ | |

### 2.2 AuthToken service unit tests (pytest, tests/test_services/test_auth_token_service.py)

45 tests covering:

| Group | Tests | Status |
|-------|-------|--------|
| (a) Token lifecycle — create/retrieve/mark-used/cleanup | 11 | ✅ 11/11 |
| (b) Register — all 3 branches return identical 202 shape | 4 | ✅ 4/4 |
| (c) Password complexity boundary | 5 | ✅ 5/5 |
| (e) Email verification — happy path, expired, reuse, wrong type | 5 | ✅ 5/5 |
| (f) Password reset — happy path, lockout clear, complexity, reuse, expired, wrong type | 6 | ✅ 6/6 |
| (g) Account lockout — thresholds, sliding window, reset paths | 6 | ✅ 6/6 |
| (h) Login blocked for unverified | 1 | ✅ 1/1 |
| (i) Login blocked for locked user + failure counter | 3 | ✅ 3/3 |
| (j) OAuth new user sets is_verified=True; existing preserved | 2 | ✅ 2/2 |
| (k) Email rate limit key structure independence | 2 | ✅ 2/2 |
| (l) grant_signup_grace JSONB regression guard | 1 | ✅ 1/1 |

**Critical regression guard:** test (l) `test_grant_signup_grace_jsonb_path_intact` — if this fails, the Batch 1 best-effort wrapper has regressed and must be investigated immediately.

### 2.3 Frontend auth page UI tests (Vitest, src/app/(public)/__tests__/auth-pages.test.tsx)

| # | Test case | Status | Notes |
|---|-----------|--------|-------|
| 2.3.1 | Register: 12-char hint visible | ✅ | D-D frontend |
| 2.3.2 | Register: password input has minLength=12 | ✅ | D-D frontend |
| 2.3.3 | Register: success state shown after 202 | ✅ | D-B frontend |
| 2.3.4 | Register: no /onboarding redirect on success | ✅ | D-B contract |
| 2.3.5 | Password reset request: email form renders | ✅ | A1 frontend |
| 2.3.6 | Password reset request: success message is generic (no email-existence leak) | ✅ | A1 + D-B pattern |
| 2.3.7 | Password reset confirm: renders new password form | ✅ | A1 frontend |
| 2.3.8 | Password reset confirm: success state + sign-in link | ✅ | A1 frontend |
| 2.3.9 | Login: locked message shown on 423 | ✅ | D-C frontend |
| 2.3.10 | Login: forgot password link present | ✅ | A1 frontend |
| 2.3.11 | Login: resend verification link shown on 403 unverified | ✅ | A2 frontend |

### 2.4 Phase B journey tests (pytest, tests/playwright/journeys/test_cp2_auth_journeys.py)

| # | Journey | Status | Notes |
|---|---------|--------|-------|
| 2.4.1 | Register returns 202 + neutral message (live API) | 🔲 | Requires Docker stack |
| 2.4.2 | Duplicate register still 202 (live API) | 🔲 | Requires Docker stack |
| 2.4.3 | Login blocked for unverified user (live API) | 🔲 | Requires Docker stack |
| 2.4.4 | Email verification token flow (live API) | 🔲 | Requires test-support token endpoint |
| 2.4.5 | Password reset request always 202 (live API) | 🔲 | Requires Docker stack |
| 2.4.6 | Password reset confirm flow + token reuse (live API) | 🔲 | Requires test-support token endpoint |
| 2.4.7 | Weak password rejected on reset confirm (live API) | 🔲 | Requires test-support token endpoint |
| 2.4.8 | 5 failed logins → 423 lockout (live API) | 🔲 | Requires Docker stack |
| 2.4.9 | Lockout clears after password reset (live API) | 🔲 | Requires test-support token endpoint |

Note: journeys 2.4.4/2.4.6/2.4.7/2.4.9 require a `/api/v1/auth/test-support/latest-token` endpoint that reads the latest auth_token row from the DB. This endpoint should only be mounted when `settings.testing = True`. Deferred to Batch 2 infrastructure work.

---

## How to use this doc

- When you run a test, update the row's Status + Notes.
- When you find a new edge case, add a row in the right section.
- When you ship a fix, add a row to Section 3.
- Treat **High**-priority 🔲 rows as launch blockers until they
  flip to ✅ or get a justified 🔁 with reasoning.
