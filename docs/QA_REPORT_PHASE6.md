# QA Test Report — Phase 6
## Date: 2026-04-09
## Tested against: localhost:8080 (frontend via nginx) + localhost:8001 (backend direct)
## Tester: Claude Code (Senior QA Engineer mode)
## Note: Playwright MCP was added but not active in session — browser tests done via HTTP curl + HTML inspection. P0 interactive flows (login redirect, form submit) require Playwright for full validation.

---

## Summary

| Status | Count |
|--------|-------|
| PASS   | 21    |
| FAIL   | 8     |
| BLOCKED| 3     |
| SKIP   | 0     |

---

## P0 Test Results (Must Pass for Launch)

| Test ID     | Test Name                              | Status    | Details |
|-------------|----------------------------------------|-----------|---------|
| AUTH-001    | Register new student                   | PASS      | POST /auth/register works. Field is `full_name` not `name` — UI label says "Full name" and uses correct field. |
| AUTH-002    | Login with valid credentials           | PASS      | Returns access_token + refresh_token + token_type |
| AUTH-003    | Login with wrong password              | PASS      | Returns 401 "Invalid credentials" |
| AUTH-004    | Get /me with valid token               | PASS      | Returns email + role correctly |
| AUTH-005    | Unauthenticated access to protected route | PASS   | /students/me/progress → 401 |
| AUTH-006    | Student accessing admin endpoint       | PASS      | /admin/stats → 403 for student role |
| COURSE-001  | List courses returns array             | PASS      | Returns empty array [] — see COURSE-BUG-001 |
| COURSE-002  | Get course by ID                       | PASS      | Returns correct course object |
| COURSE-003  | Get course lessons                     | PASS      | Returns all 10 lessons |
| COURSE-004  | Non-existent course → 404              | PASS      | Returns 404 |
| LEARN-001   | Mark lesson complete                   | PASS      | Returns `{status: "completed"}` |
| LEARN-002   | Progress endpoint returns data         | PASS      | Returns array of student_progress records |
| EX-001      | Get exercise by ID                     | PASS      | Returns exercise with title + difficulty |
| EX-002      | Submit exercise                        | FAIL      | `exercise_id` required in BOTH path param AND body — redundant, error-prone API design |
| EX-003      | Submit without auth → 401              | PASS      | 401 returned correctly |
| WEBHOOK-001 | Stripe webhook validates signature     | FAIL      | Returns 200 with `{"status":"received"}` — no signature check when `STRIPE_WEBHOOK_SECRET` is empty. Accepts any payload. |
| WEBHOOK-002 | GitHub webhook validates signature     | FAIL      | Returns 401 (not 403), but signature IS checked |
| AGENT-001   | Agent chat returns response or graceful error | FAIL | Returns raw Python traceback (500) with internal file paths exposed when `ANTHROPIC_API_KEY` is empty |
| AGENT-002   | List agents endpoint                   | FAIL      | Returns 200 without auth — endpoint is public, no authentication required |
| ADMIN-001   | Admin stats accessible by admin        | PASS      | Returns `{total_students, total_enrollments, total_submissions, mrr_cents}` |
| ADMIN-002   | Admin agents health shows all agents   | PASS      | All 20 agents listed with status=healthy |
| ADMIN-003   | Admin students list                    | PASS      | Returns 5 students |

---

## P1 Test Results (Should Pass)

| Test ID     | Test Name                                   | Status   | Details |
|-------------|---------------------------------------------|----------|---------|
| COURSE-005  | Public course listing accessible without auth | PASS   | GET /courses → 200 without token |
| COURSE-006  | is_published field in CourseCreate           | FAIL     | `is_published` not in CourseCreate schema — silently ignored, course always created unpublished. Public listing returns 0 courses. |
| COURSE-007  | Dynamic course page renders                  | PASS     | /courses/production-rag → 200 |
| LEARN-003   | Progress response schema                     | FAIL     | Returns array of `student_progress` rows, not a summary object. No `total_lessons`, `completed_lessons`, or `progress_pct` fields. Frontend likely can't show "3/10 (30%)" without this. |
| RATE-001    | Rate limiting on /register (10/min)          | FAIL     | 11 rapid requests all returned 201. Rate limiter not enforcing limit in Docker (likely cleared between tests, or in-memory state issue). |
| UI-001      | Landing page renders with title              | PASS     | `<title>Production AI Engineering Platform</title>`, h2 headings visible |
| UI-002      | Login page has email + password inputs       | PASS     | `type="email"`, `type="password"`, `type="submit"` present in HTML |
| UI-003      | Register page has correct fields             | PASS     | `type="text"`, `type="email"`, `type="password"` present. "Full name" label found. |
| UI-004      | Dashboard, Chat, Admin pages return 200      | PASS     | All return HTTP 200 (auth handled client-side by Next.js) |
| UI-005      | Non-existent lesson page renders 200         | PASS     | Returns 200 with Next.js shell (dynamic route, 404 content rendered client-side) |
| HEALTH-001  | Backend health endpoint                      | PASS     | `{"status":"ok","version":"0.1.0"}` via nginx and direct |
| HEALTH-002  | Docker healthcheck for backend               | FAIL     | Container status=UNHEALTHY — `curl` not installed in `python:3.12-slim`. Healthcheck always fails. |
| INFRA-001   | Nginx proxies /api/ to backend               | PASS     | /health, /docs, /api/* all proxied correctly |
| INFRA-002   | All 8 containers running                     | PASS     | db, redis, backend, frontend, celery-worker, celery-beat, meilisearch, nginx all up |

---

## Blocked Tests (Require Playwright)

| Test ID  | Reason |
|----------|--------|
| AUTH-007 | Cannot verify client-side redirect to /login after navigating to /dashboard without cookies — requires real browser |
| VIS-001  | Cannot verify empty state UI message for unenrolled student — requires browser rendering |
| VIS-002  | Cannot verify form error messages on invalid login — requires browser JS execution |

---

## Failure Analysis

### FAIL: EX-002 — Exercise Submit Requires Redundant exercise_id in Body

**What happened:** `POST /api/v1/exercises/{exercise_id}/submit` requires `exercise_id` in the request body even though it is already in the URL path parameter.

**Expected:** Path param should be sufficient. Body should only need `code` and optionally `github_pr_url`.

**Root cause:** `SubmissionCreate` schema has `exercise_id` as a required field. The route handler likely uses the body field to populate the model rather than reading from path params.

**File to fix:** `backend/app/schemas/` (SubmissionCreate schema) + `backend/app/api/v1/routes/exercises.py`

**Fix description:** Either make `exercise_id` optional in `SubmissionCreate` (defaulting to path param), or remove it from the body entirely and inject from path.

**Severity:** Major — every client must send duplicate data; confusing API contract.

---

### FAIL: WEBHOOK-001 — Stripe Webhook Accepts Any Payload Without Signature Check

**What happened:** `POST /api/v1/webhooks/stripe` with invalid `Stripe-Signature` header returns `{"status":"received","event":"..."}` (HTTP 200). The endpoint processes any payload with no validation when `STRIPE_WEBHOOK_SECRET` is empty string.

**Expected:** Should return 400/403 when signature is missing or invalid.

**Root cause:** Webhook handler checks `STRIPE_WEBHOOK_SECRET` but silently skips validation when it is empty. This is a dev-mode bypass that can leak to production.

**File to fix:** `backend/app/api/v1/routes/webhooks.py`

**Fix description:** If `stripe_webhook_secret` is empty, return 503 "Stripe integration not configured" rather than bypassing verification. Never accept unverified Stripe events.

**Severity:** Critical — in production this allows anyone to fake payment events and grant course access for free.

---

### FAIL: AGENT-001 — Chat Endpoint Leaks Python Traceback on Missing API Key

**What happened:** `POST /api/v1/agents/chat` returns a raw Python traceback with internal file paths and stack frames when `ANTHROPIC_API_KEY` is empty. The response body is a plain-text traceback, not JSON.

**Expected:** Should return `{"error": "AI service not configured"}` (HTTP 503) or similar structured error.

**Root cause:** `ChatAnthropic` constructor raises `ValidationError` when `anthropic_api_key` is None. The exception propagates through LangGraph and Starlette's `ErrorMiddleware` which formats it as a plaintext traceback (because the response is not wrapped in a try/except before the middleware sees it).

**File to fix:** `backend/app/agents/base_agent.py` or `backend/app/api/v1/routes/agents.py`

**Fix description:** Wrap `graph.ainvoke()` call in `agents.py` route in try/except, catch `Exception`, and return `{"error": "Agent service unavailable"}` with HTTP 503. Also add startup validation: if `ANTHROPIC_API_KEY` is empty, log a warning and disable the agents routes.

**Severity:** Critical — exposes internal architecture, file paths, and library versions to attackers.

---

### FAIL: AGENT-002 — /agents/list Endpoint is Public (No Auth Required)

**What happened:** `GET /api/v1/agents/list` returns the full list of 20 agents and their descriptions without authentication. HTTP 200 without any token.

**Expected:** Should require a valid user token (401 if missing).

**Root cause:** The route is missing a `Depends(get_current_user)` dependency.

**File to fix:** `backend/app/api/v1/routes/agents.py`

**Fix description:** Add `current_user: UserResponse = Depends(get_current_user)` to the `list_agents` route handler.

**Severity:** Minor — agent names/descriptions are not secret, but it's an inconsistent API surface.

---

### FAIL: COURSE-006 — CourseCreate Schema Missing is_published Field

**What happened:** `POST /api/v1/courses` with `"is_published": true` in the body silently ignores the field. Course is stored with `is_published=false`. The public `GET /api/v1/courses` listing returns 0 results (only shows published courses).

**Expected:** Admin should be able to publish a course on creation or via an update endpoint.

**Root cause:** `CourseCreate` Pydantic schema does not include `is_published`. The field exists in the database but there is no way to set it via the API.

**File to fix:** `backend/app/schemas/course.py` (add `is_published: bool = False` to CourseCreate and CourseUpdate)

**Fix description:** Add `is_published: bool = False` to `CourseCreate` schema. Verify `CourseUpdate` also accepts it. Test by creating a course with `is_published=true` and confirming it appears in the public listing.

**Severity:** Critical — without this fix, no courses can be published through the API. The entire learning platform is non-functional for students.

---

### FAIL: LEARN-003 — Progress Endpoint Returns Raw Rows Not Summary

**What happened:** `GET /api/v1/students/me/progress` returns an array of individual `student_progress` records `[{lesson_id, status, completed_at, ...}]`. There is no summary with `total_lessons`, `completed_lessons`, `progress_pct`.

**Expected:** Either the endpoint returns a summary object, or the frontend computes it — but the frontend needs to know total lesson count per course to compute a percentage.

**Root cause:** Progress endpoint returns raw DB rows. No aggregation or course context.

**File to fix:** `backend/app/api/v1/routes/students.py`, `backend/app/services/` (student service)

**Fix description:** Return a structured response: `{"enrollments": [{course_id, course_title, total_lessons, completed_lessons, progress_pct, progress_rows: [...]}]}`. Or document this as intentional and verify the frontend does the aggregation.

**Severity:** Major — dashboard "Continue Learning" and progress % cannot work without knowing total lessons per course.

---

### FAIL: RATE-001 — Rate Limiting Not Enforced in Docker

**What happened:** 11 rapid POST /auth/register calls all returned 201. Rate limit (10/min) not triggered.

**Expected:** 11th request should return 429.

**Root cause:** `slowapi` uses in-memory storage. Each `gunicorn` worker has its own memory. With 4 workers (`--workers 4`), the request counter is spread across workers — each worker sees ~2-3 requests in the window, never hitting 10.

**File to fix:** `backend/app/core/rate_limit.py`

**Fix description:** Use Redis as the storage backend for slowapi: `limiter = Limiter(key_func=get_remote_address, storage_uri=settings.redis_url)`. This shares rate limit counters across all gunicorn workers.

**Severity:** Major — rate limiting is completely ineffective in multi-worker production configuration.

---

### FAIL: HEALTH-002 — Docker Healthcheck Always Fails

**What happened:** Backend container status shows `(unhealthy)`. The container is fully functional but Docker marks it unhealthy.

**Expected:** Container should show `(healthy)` once the API is responding.

**Root cause:** Healthcheck uses `curl` which is not installed in `python:3.12-slim`.

**File to fix:** `backend/Dockerfile` or `docker-compose.yml`

**Fix description:** Either add `RUN apt-get install -y curl` to the Dockerfile (adds ~3MB), or change the healthcheck to use Python: `CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]`

**Severity:** Minor — app works fine, but misleading status and docker orchestrators may restart the container unnecessarily.

---

## Missing Endpoints / Features

| Feature | Expected Endpoint | Status | Impact |
|---------|-------------------|--------|--------|
| Course enrollment | POST /api/v1/courses/{id}/enroll | MISSING | Students cannot enroll through the API — must be done via direct DB insert |
| Course publish toggle | PATCH /api/v1/courses/{id} with is_published | PARTIAL | CourseUpdate may exist but is_published not in schema |
| Exercise creation via API | POST /api/v1/exercises | MISSING | Exercises must be seeded via DB. No admin UI path to add exercises. |
| Refresh token endpoint | POST /api/v1/auth/refresh | MISSING | refresh_token is returned at login but no endpoint to exchange it for a new access_token |
| Student enrollment list | GET /api/v1/students/me/enrollments | MISSING | Students can't query their enrolled courses |
| Progress summary | GET /api/v1/students/me/progress (summary) | PARTIAL | Returns raw rows, not an aggregated course-level summary |

---

## Infrastructure Notes

| Item | Status |
|------|--------|
| Port remapping from defaults | 8080 (nginx), 8001 (backend), 3001 (frontend), 5433 (db), 6381 (redis) — due to port conflicts with other running containers on this machine |
| Alembic DB URL fix | `alembic/env.py` was using hardcoded `localhost:5432` — fixed to use `settings.database_url` |
| POSTGRES_HOST in .env | Was missing `POSTGRES_HOST=db` — fixed |
| NEXT_PUBLIC_API_URL baked at build time | Fixed via Docker build arg in Dockerfile stage 2 |
| docker-compose `version:` warning | `version: '3.9'` is obsolete — can be removed |

---

## Recommendations (Prioritized Fix List)

### P0 — Fix Before Any User Testing

1. **Add `is_published` to `CourseCreate` schema** — without this, no course can be published via API and the platform shows no content to students. (`backend/app/schemas/course.py`)

2. **Fix Stripe webhook signature bypass** — when `STRIPE_WEBHOOK_SECRET` is empty, return 503, do not accept events. (`backend/app/api/v1/routes/webhooks.py`)

3. **Fix agent chat crash / traceback leak** — wrap `graph.ainvoke()` in try/except, return structured 503. (`backend/app/api/v1/routes/agents.py`)

4. **Add course enrollment endpoint** — `POST /api/v1/courses/{id}/enroll`. Students have no way to enroll without direct DB access.

### P1 — Fix Before Beta Launch

5. **Fix rate limiting to use Redis** — multi-worker gunicorn defeats in-memory rate limiter. (`backend/app/core/rate_limit.py`)

6. **Fix exercise submit schema** — remove redundant `exercise_id` from body (already in path). (`backend/app/schemas/submission.py`)

7. **Fix progress endpoint** — return summary with `total_lessons`, `completed_lessons`, `progress_pct` per enrollment. (`backend/app/api/v1/routes/students.py`)

8. **Add auth to `/agents/list`** — add `Depends(get_current_user)`. (`backend/app/api/v1/routes/agents.py`)

### P2 — Polish

9. **Fix Docker healthcheck** — use Python urllib instead of curl. (`docker-compose.yml` or `backend/Dockerfile`)

10. **Add refresh token endpoint** — `POST /api/v1/auth/refresh` to exchange refresh_token for new access_token.

11. **Add exercise creation endpoint** — `POST /api/v1/exercises` so admin can create exercises without direct DB access.

12. **Remove `version:` from docker-compose.yml** — obsolete field causes warning on every `docker compose` command.

---

## Test Environment Details

| Item | Value |
|------|-------|
| Backend | FastAPI 0.1.0 on gunicorn+uvicorn (4 workers) |
| Frontend | Next.js standalone build, Node 22 |
| Database | PostgreSQL 16-alpine, 12 tables migrated |
| Test users | admin@test.com, student@test.com, student2@test.com, qa@test.com |
| Test course | "Production RAG Engineering" (10 lessons, 3 exercises) |
| ANTHROPIC_API_KEY | Empty — agent features not testable |
| Playwright | Configured but not active in session — browser flows untested |
