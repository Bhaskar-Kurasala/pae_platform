# Production-Readiness Execution Plan

**Owner:** Bhaskar
**Started:** 2026-04-28
**Goal:** Take the platform from "developer-quality demo" to "we can let real users in tomorrow."

This document is the **single source of truth** for the production-readiness pass. Every working agent — current or future — reads this first, picks the next `[ ]` task in the active PR, executes it under the standards in [`AGENT-OPERATING-SPEC.md`](./AGENT-OPERATING-SPEC.md), then flips the checkbox to `[x]` with a one-paragraph completion note.

---

## Why this exists

The platform is feature-rich. It is not yet bulletproof. Specifically:

1. **Schema↔UI drift is untested.** Nothing fails CI when a backend field renames and the frontend type drifts.
2. **Dead code is accumulating.** After Practice merged Exercises + Studio, there are routes, hooks, and components that nothing reaches.
3. **Error paths are silent.** A render exception white-screens the user; a 500 from an aggregator returns a generic message; a stale token returns a 500 instead of refreshing.
4. **No observability.** When a user reports "the page broke at 11:47am," we cannot trace the request, see the error, or correlate it to a deploy.
5. **No backups.** If the dev DB is wiped, every demo account is gone forever. This single item gates real launch.

This plan addresses all five categories in **3 PRs of decreasing safety**, then deploys to **Fly.io + Neon Postgres + Cloudflare R2 backups**.

---

## Hosting target — locked

| Component | Provider | Why | Day-1 cost | 1k-user cost |
|---|---|---|---|---|
| App (front + back containers) | **Fly.io** | Per-second billing, scales to zero in dev, Docker-native, worldwide edge | $0 (free tier) | ~$70/mo |
| Postgres | **Neon** | Cheapest "real Postgres + PITR" tier; free 0.5GB; branching for staging | $0 free | $69 Scale (50GB) |
| Backup storage | **Cloudflare R2** | Zero egress fees → restore drills are free | $0 (<10GB free) | ~$1/mo |
| Error reporting | **Sentry** | Browser + Python SDKs, source-maps, free up to 5k errors/mo | $0 free | $26/mo Team |
| Product analytics | **PostHog Cloud** | Free up to 1M events/mo, OSS-friendly | $0 free | $0 (still under 1M) |
| Status / uptime | **Better Stack** or **healthchecks.io** | Free tier covers 10 monitors | $0 free | $0 free |

**Total month-1 cost: ~$0. Total at 1,000 students: ~$150/mo.**

Production domain to be picked at PR 3 cut-over.

---

## PR Plan

| PR | Theme | Risk | Lines changed (est.) | Status |
|---|---|---|---|---|
| **PR 1** | Read-only audits — surface the bug list | None (no behavior change) | ~600 (mostly tooling + doc) | 🟡 In progress |
| **PR 2** | Resilience + cleanup — fix the bugs PR 1 found | High (deletes dead code, changes error paths) | ~1500 | 🔲 Not started |
| **PR 3** | Observability + production deploy | Medium (additive, but new infra) | ~1200 | 🔲 Not started |

**Sequencing rule:** No agent starts a task in PR N+1 until PR N is **merged and verified in production**. This prevents agents stomping on each other and ensures every PR ships a complete, testable slice.

**Parallelism rule:** Within a single PR, multiple agents may work in parallel iff they touch *non-overlapping files*. The "Touches:" field on every task lists the file paths claimed. Before starting, an agent verifies no other in-flight task lists the same path.

---

## PR 1 — Read-only audits

**Goal:** Land a bug list. Fix nothing yet. Surface the mess so we can triage before deleting.
**Branch:** `prod/pr1-audits`
**Output:** A markdown report at `docs/AUDIT-2026-04-28.md` plus three new audit scripts in `scripts/`.

### A1 — Endpoint inventory

- [x] **A1.1** Write `scripts/audit_endpoints.py` that walks the FastAPI router tree, extracts every `(method, path, handler_func)`, and writes `docs/audits/endpoints.csv`.
  - **Touches:** `scripts/audit_endpoints.py`
  - **Acceptance:**
    - CSV columns: `method,path,tag,handler,file,line`.
    - Output is sorted by `path`.
    - Running on current `main` produces ~80–100 rows (sanity check).
    - Includes a `__main__` so `python scripts/audit_endpoints.py` works.
  - **Done note:** Implemented as a stdlib-only `ast`-based walker — no FastAPI import, runs from a clean clone in <100ms. Sanity check **found 215 rows**, much higher than my 80–100 estimate (the codebase has more surface than I'd internalized). The script also rewrites `/health/*` paths so they don't end up double-prefixed under `/api/v1`. Output: `docs/audits/endpoints.csv`. Verified by spot-checking known routes (`/api/v1/path/summary`, `/api/v1/promotion/confirm`, `/health/ready` all present with correct method + handler).

- [x] **A1.2** Write `scripts/audit_frontend_callers.mjs` that grep-walks `frontend/src` for every `api.get/post/put/patch/delete/del` call site and emits `docs/audits/api-callers.csv`.
  - **Touches:** `scripts/audit_frontend_callers.mjs`
  - **Acceptance:**
    - CSV columns: `path_template,method,caller_file,caller_line,via_helper`.
    - `via_helper` resolves the named helper (e.g. `pathApi.summary`) so the path matches the route inventory.
    - Catches both direct `api.X(...)` and api-client wrapper helpers (`pathApi.summary`, `practiceApi.review`, etc.).
  - **Done note:** Three rounds of fixing taught me how the codebase's call sites are actually shaped:
    1. Initial regex `[^`"']+` for the path arg broke on **nested template literals** (e.g. `/api/v1/chat/conversations${qs ? \`?${qs}\` : ""}`). Replaced with a proper string-literal reader that walks brace-balanced `${...}` expressions and skips nested strings inside them.
    2. **Camel-case path params** mismatched FastAPI's snake-case (e.g. `/api/v1/foo/${id}` vs `/api/v1/foo/{conversation_id}`). Solution: shape-based normalization — every `{...}` segment in both inventories maps to `{*}`. Names don't have to match.
    3. **Query-string templates** like `${qs ? \`?${qs}\` : ""}` should produce a plain path, not `/path/{*}`. Heuristic: any trailing `${expr}` whose interpolated expression contains a literal `?` is treated as a query suffix and dropped.
    4. **The `del` alias** — `api.del()` is the wrapper for DELETE because `delete` is a reserved word in some object-literal contexts. Added it to `HTTP_VERBS` and aliased the emitted method to "DELETE".
    Output: 167 caller rows (160 → 167 across the four fixes). Verified that known-live routes (`/today/summary`, `/path/summary`, `/exercises`, `/chat/conversations`, `DELETE /chat/conversations/{id}`, etc.) all resolve.

- [x] **A1.3** Write `scripts/audit_join.py` that joins the two CSVs and writes `docs/audits/endpoint-coverage.md` — a markdown table grouped by handler, showing every endpoint and its callers (or "DEAD" if zero).
  - **Touches:** `scripts/audit_join.py`, `docs/audits/endpoint-coverage.md`
  - **Acceptance:**
    - Table shows `method | path | callers | verdict`. Verdict is one of: `live`, `dead`, `legacy-redirect`, `webhook-only`, `admin-only`.
    - Manual triage column at the right edge for me to fill in.
  - **Done note:** Joins on `(method, shape_key(path))` where `shape_key` collapses every `{param}` to `{*}` so backend `{conversation_id}` matches frontend `{*}` regardless of original variable name. Classifier produces six verdicts: `live`, `dead`, `admin-only`, `webhook-only`, `oauth-callback`, `health` — and the dead candidates intentionally excludes admin/webhook/oauth/health to avoid false positives. **Final tally: 154 live · 44 dead · 8 admin-only · 6 webhook-only · 4 oauth-callback · 3 health (215 total).** The 44 dead routes are real — they're surfaces that were planned but never wired up (peer-reviews, worked-examples, scaffolding, billing portal, demo/chat, etc.). They're triage candidates for PR2/A2.2.

### A2 — Frontend dead-component scan

- [ ] **A2.1** Add `knip` and `ts-prune` as dev deps; configure `knip.json` to scan `frontend/src/**`.
  - **Touches:** `frontend/package.json`, `frontend/knip.json`
  - **Acceptance:**
    - `pnpm exec knip` runs in <30s and emits a categorized list (unused exports, unused files, unused deps).
    - Output committed to `docs/audits/dead-frontend.md` for triage.
  - **Done note:**

### A3 — Schema↔UI invariant tests

This is the highest-leverage item in this PR. It will *find* most of the bugs you suspect exist.

- [ ] **A3.1** Write `backend/tests/test_contracts/test_aggregator_contracts.py`. For each aggregator endpoint, the test:
  1. Logs in as a seeded user.
  2. Calls the endpoint.
  3. Walks the **frontend's TypeScript interface** for the response (we'll snapshot the relevant ones into Python literal at the top of the test file — these are read-only contracts, so a manual sync is fine for now).
  4. For every required field, asserts the response carries it AND that it is non-null where the frontend would render unconditionally.
  - **Touches:** `backend/tests/test_contracts/test_aggregator_contracts.py`
  - **Endpoints covered:**
    - `GET /api/v1/today/summary`
    - `GET /api/v1/path/summary`
    - `GET /api/v1/promotion/summary`
    - `GET /api/v1/readiness/overview`
    - `GET /api/v1/catalog/`
    - `GET /api/v1/exercises`
    - `GET /api/v1/chat/notebook`
    - `GET /api/v1/srs/due`
  - **Acceptance:**
    - Each endpoint has its own test with a clear failure message.
    - Failures itemize the field name(s) that drifted.
    - Tests pass on current `main` (they're additive — they don't fix anything, just guard).
  - **Done note:**

- [ ] **A3.2** Write `frontend/src/test/contracts/api-shape.test.ts`. For each api-client interface, snapshot the field set; if the snapshot drifts, CI fails. Catches the *frontend* side of the same drift.
  - **Touches:** `frontend/src/test/contracts/api-shape.test.ts`, `frontend/src/test/contracts/__snapshots__/`
  - **Acceptance:**
    - One snapshot per public interface (`PathSummaryResponse`, `PromotionSummaryResponse`, `TodaySummaryResponse`, `PracticeReviewRecord`, `NotebookEntryOut`).
    - Running on current `main` writes the initial snapshots and passes.
  - **Done note:**

### A5 — Markdown / preview leak audit

- [ ] **A5.1** Grep for every place that dumps an entry's `content` or `body` into a small `<p>` or preview tile. Replace each with `stripMarkdownToText(...) + truncateAtWord(...)`.
  - **Touches:**
    - `frontend/src/app/(portal)/chat/page.tsx` (sidebar preview)
    - `frontend/src/components/v8/screens/today-screen.tsx` (micro-wins, capstone preview)
    - Any other call site Grep finds
  - **Acceptance:**
    - One Vitest test per touched file confirms a markdown-laden fixture renders as plain text.
    - Manual check: chat sidebar previews no longer show `**bold**` or ` ``` ` fences.
  - **Done note:**

### Deliverable

- [ ] **A-OUT** Generate `docs/AUDIT-2026-04-28.md` summarizing:
  - Dead endpoints (with proposed deletions)
  - Dead frontend exports (with proposed deletions)
  - Schema drift findings (likely 5–15 items)
  - Markdown leak fixes already applied
  - Recommended PR 2 ticket ordering based on what was found
  - **Done note:**

**PR 1 verification:** `make test && make lint` green; audit doc reviewed by Bhaskar; merge.

---

## PR 2 — Resilience + cleanup

**Goal:** Fix everything PR 1 found. No silent failures. No dead code.
**Branch:** `prod/pr2-resilience`
**Depends on:** PR 1 merged.

### A2 — Cleanup deletions

- [ ] **A2.2** Delete every confirmed-dead route. Each deletion gets a 1-line justification in commit message.
  - **Touches:** decided after A1.3
  - **Acceptance:** `pnpm test && uv run pytest -x` still green. No 404s introduced for any link reachable from the UI.
  - **Done note:**

- [ ] **A2.3** Delete every confirmed-dead component / hook.
  - **Likely victims (to confirm):** `<StudioLayout>` directory (~24 files), legacy `studio-screen.tsx`, old `/practice/page.tsx` shadcn list, old `/exercises/page.tsx` original list.
  - **Acceptance:** TypeScript compiles. Frontend bundle size shrinks. Storybook (if configured) stays green.
  - **Done note:**

### A4 — Deprecation discipline

- [ ] **A4.1** Add a `deprecated()` decorator in `backend/app/api/_deprecated.py` that adds `Deprecation: true` and `Sunset: <date>` response headers, AND emits `log.warning("deprecated_endpoint_called", route=..., user_id=...)`.
  - **Touches:** `backend/app/api/_deprecated.py`, every legacy endpoint
  - **Acceptance:**
    - Calling a decorated endpoint returns the headers.
    - Hitting it emits a structlog warning.
    - We can grep logs to find the last living caller before deletion.
  - **Done note:**

### B1 — Frontend ApiError handling

- [ ] **B1.1** Audit every `useQuery` and `useMutation` in `frontend/src/lib/hooks/` and `frontend/src/components/`. Every one with a network call gets either an `onError: (e) => toast.error(...)` or a documented "render handles error state" comment.
  - **Touches:** `frontend/src/lib/hooks/use-*.ts` (~30 files)
  - **Acceptance:**
    - No bare `console.error` for an API failure (replace with `toast.error`).
    - One end-to-end test that simulates a 500 and confirms the user-facing toast.
  - **Done note:**

### B2 — Token refresh interceptor

- [ ] **B2.1** Audit `frontend/src/lib/api-client.ts` request helper. Confirm 401 triggers a single refresh attempt, retries the original request, and on second 401 redirects to `/login?next=...`.
  - **Touches:** `frontend/src/lib/api-client.ts`
  - **Acceptance:**
    - Manual test: in browser, set token expiry to 30 seconds in dev mode, click around a protected page, observe a single quiet refresh + retry.
    - Vitest covers the refresh path with a mocked 401→200 sequence.
  - **Done note:**

### B3 — Error boundaries with branded copy

- [ ] **B3.1** Replace each `error.tsx` route boundary in `frontend/src/app/` with a real branded boundary that:
  1. Shows a friendly message ("Something broke. We've logged it. Try again or go home.").
  2. Surfaces the `request_id` from the response header so support can find the trace.
  3. Has "Reload" and "Back to Today" buttons.
  4. Reports the error to Sentry (PR 3) — use a no-op stub for now.
  - **Touches:** `frontend/src/app/(portal)/error.tsx`, `frontend/src/app/(public)/error.tsx`, `frontend/src/app/(admin)/error.tsx`
  - **Acceptance:**
    - Trigger by throwing inside a screen — no white-screen.
    - Request ID is visible.
  - **Done note:**

- [ ] **B3.2** Wrap heavy panels in client `<ErrorBoundary>`: `<Monaco>`, `<MarkdownRenderer>`, the catalog price formatter, the takeover modal.
  - **Touches:** `frontend/src/components/error-boundary.tsx` + call sites
  - **Acceptance:** A throw inside Monaco doesn't take down the whole Practice screen.
  - **Done note:**

### B4 — Backend exception middleware

- [ ] **B4.1** Add `@app.exception_handler(Exception)` in `backend/app/main.py` that:
  1. Generates / propagates the request_id.
  2. Logs `event="unhandled_exception"` with full context.
  3. Returns `{"error": {"type": "internal_error", "message": "...", "request_id": "..."}}` with a stable JSON shape.
  4. Never leaks a Python traceback.
  - **Touches:** `backend/app/main.py`, `backend/app/core/middleware.py`
  - **Acceptance:**
    - A test that raises inside a route returns the expected JSON shape with the right shape and a 500 status.
    - The traceback IS in the log, NOT in the response body.
  - **Done note:**

### B5 — Timeouts

- [ ] **B5.1** Audit Anthropic client construction. Add `timeout=30.0` and `max_retries=3` to every `Anthropic()` / `AsyncAnthropic()` call site.
  - **Touches:** `backend/app/agents/llm_factory.py`, `backend/app/services/*` that construct clients directly
  - **Acceptance:** Grep for `Anthropic(` finds zero call sites without a timeout.
  - **Done note:**

- [ ] **B5.2** Postgres `statement_timeout = 5000` (5 seconds) on connection setup. The `/execute` sandbox already has its own timeout — leave that alone.
  - **Touches:** `backend/app/core/database.py`
  - **Acceptance:** `SHOW statement_timeout;` in a test connection reads `5s`.
  - **Done note:**

- [ ] **B5.3** Frontend `fetch` calls that may stream or take >10s wrap in `AbortController` with a 30s timeout (chat stream is exempt — different lifetime).
  - **Touches:** `frontend/src/lib/api-client.ts`
  - **Acceptance:** A frozen backend doesn't hang the UI forever; user sees a "request took too long" toast after 30s.
  - **Done note:**

### B6 — Idempotency on writes

- [ ] **B6.1** Notebook save: dedupe on `(user_id, message_id, content_hash)` for 60 seconds via Redis. A double-click doesn't double-save.
  - **Touches:** `backend/app/api/v1/routes/notebook.py`, `backend/app/services/notebook_service.py`
  - **Acceptance:** A test that posts the same payload twice within 5s gets back the same entry id, not two.
  - **Done note:**

- [ ] **B6.2** SRS auto-seed: confirm uniqueness constraint on `(user_id, concept_key)`. If missing, add an Alembic migration to enforce it.
  - **Touches:** `backend/alembic/versions/0049_srs_uniqueness.py` (if needed)
  - **Acceptance:** A test that inserts the same `(user_id, concept_key)` twice gets exactly one row.
  - **Done note:**

### B7 — Rate limits

- [ ] **B7.1** Apply slowapi limits per the table:

| Endpoint | Limit | Why |
|---|---|---|
| `POST /api/v1/senior-review` | 10/min | LLM cost |
| `POST /api/v1/execute` | 5/min | Sandbox CPU |
| `POST /api/v1/chat/stream` | 20/min | LLM cost |
| `POST /api/v1/notebook/summarize` | 15/min | LLM cost |
| `POST /api/v1/promotion/confirm` | 3/hour | Side effect (state change) |

  - **Touches:** the route files above
  - **Acceptance:** A test confirms the 11th call to senior-review in 60s returns 429.
  - **Done note:**

### A5 — leftover preview-leak fixes

- [ ] **A5.2** Apply remaining markdown-strip fixes from PR 1's audit.
  - **Touches:** decided after A5.1
  - **Acceptance:** No remaining surface dumps raw markdown into a small preview.
  - **Done note:**

**PR 2 verification:** Full `make test && make lint`. Manual smoke walk on Today / Practice / Notebook / Promotion at 1440×900 and 768×1024. All confirmed-dead code removed.

---

## PR 3 — Observability + production deploy

**Goal:** Know what's happening. Survive a panic. Ship to Fly.
**Branch:** `prod/pr3-observability`
**Depends on:** PR 2 merged.

### C1–C2 — Request tracing + structured logs

- [ ] **C1.1** Middleware in `backend/app/core/middleware.py` that:
  1. Generates `request_id = uuid4().hex[:16]` if not present.
  2. Stores it on a contextvar so `structlog.get_logger()` calls auto-include it.
  3. Sets `X-Request-ID` on the response.
  4. Frontend `api-client.ts` reads `X-Request-ID` from every response and stashes it on a `lastRequestId` ref so error toasts can show it.
  - **Touches:** `backend/app/core/middleware.py`, `frontend/src/lib/api-client.ts`
  - **Acceptance:** Every log line for a request has the same `request_id`. UI errors show "Reference: abc123de" so support can search by it.
  - **Done note:**

- [ ] **C2.1** Audit every `except` block. Every one logs with structured fields: `event=...`, `user_id=...`, `request_id=...`, plus relevant context. No bare `except: pass`. No `print`.
  - **Touches:** `backend/app/**/*.py`
  - **Acceptance:** Grep for `except` returns ~50 hits; every one has a matching `log.error` or `log.warning` within 3 lines.
  - **Done note:**

### C3 — PostHog telemetry

- [ ] **C3.1** Add `posthog-node` (backend) and `posthog-js` (frontend). Init from env vars; no-op when key absent (dev / CI).
  - **Touches:** `frontend/src/lib/telemetry.ts`, `backend/app/core/telemetry.py`
  - **Acceptance:** Without `NEXT_PUBLIC_POSTHOG_KEY`, no events fire and no errors thrown.
  - **Done note:**

- [ ] **C3.2** Emit the standard event set:
  - `auth.signed_up`, `auth.signed_in`, `auth.token_refreshed`
  - `today.summary_loaded`, `today.warmup_done`, `today.lesson_done`, `today.reflect_done`
  - `practice.run`, `practice.review_requested`, `practice.notebook_saved`, `practice.exercise_selected`
  - `notebook.saved`, `notebook.opened`, `notebook.deleted`
  - `promotion.summary_viewed`, `promotion.ready`, `promotion.confirmed`
  - `payment.checkout_opened`, `payment.completed`, `payment.failed`
  - `error.boundary_caught`, `error.api_failed`
  - **Touches:** every screen + the relevant hooks
  - **Acceptance:** Manual test: click around as the demo user, see events in PostHog dev project.
  - **Done note:**

### C4–C5 — Sentry

- [ ] **C4.1** Frontend Sentry. `@sentry/nextjs` with source-map upload at build time.
  - **Touches:** `frontend/sentry.client.config.ts`, `frontend/sentry.server.config.ts`, `frontend/next.config.js`
  - **Acceptance:** Throw in dev → see in Sentry; stack trace is readable (TS source, not minified).
  - **Done note:**

- [ ] **C5.1** Backend Sentry. `sentry-sdk[fastapi]` with PII filtering. Tags: `route`, `user_id`, `agent_name`.
  - **Touches:** `backend/app/main.py`, `backend/app/core/sentry.py`
  - **Acceptance:** Raise in dev → see in Sentry tagged with route + user.
  - **Done note:**

### C6 — Health checks

- [ ] **C6.1** `GET /health/ready` — pings DB, Redis, returns 200 only when all green. Returns `{db: "ok", redis: "ok", anthropic: "skipped" | "ok"}`.
  - **Touches:** `backend/app/api/v1/routes/health.py`
  - **Acceptance:** Stop redis → endpoint returns 503 with `redis: "unreachable"`.
  - **Done note:**

- [ ] **C6.2** `GET /health/version` — returns `{commit_sha, build_time, env}`. Set during Docker build.
  - **Touches:** `backend/app/api/v1/routes/health.py`, `backend/Dockerfile`
  - **Acceptance:** Calling on dev returns the local commit SHA; calling on Fly returns the deployed SHA.
  - **Done note:**

- [ ] **C6.3** Switch docker-compose healthcheck and Fly healthcheck to `/health/ready`.
  - **Touches:** `docker-compose.yml`, `fly.toml`
  - **Done note:**

### C7 — Cost tracking per LLM call

- [ ] **C7.1** Instrument every Anthropic call to log `{event: "llm.call", agent_name, model, tokens_in, tokens_out, duration_ms, user_id, cost_estimate_usd}`.
  - **Touches:** `backend/app/agents/base_agent.py`, `backend/app/agents/llm_factory.py`
  - **Acceptance:** Daily aggregate via PostHog `SUM(cost_estimate_usd) BY user_id` is queryable.
  - **Done note:**

### C8 — Slow-query log

- [ ] **C8.1** Set Postgres `log_min_duration_statement = 500` in the Neon dashboard / connection params. Log slow queries to Sentry as performance issues.
  - **Touches:** `backend/app/core/database.py`, Neon config
  - **Acceptance:** A deliberately slow query shows up in the slow-query log.
  - **Done note:**

### D1 — Database backups (highest priority of the whole plan)

- [ ] **D1.1** Fly cron machine that runs `pg_dump $NEON_URL | gzip | aws s3 cp - s3://r2-bucket/backups/$(date +%Y%m%d-%H%M).sql.gz` daily at 04:00 UTC.
  - **Touches:** `infra/backup/Dockerfile`, `infra/backup/backup.sh`, `fly-backup.toml`
  - **Acceptance:** A backup file lands in R2 every night.
  - **Done note:**

- [ ] **D1.2** Run a verified-restore drill: pull latest backup, restore to a Neon branch, run the read-only contract tests against it, document the procedure in `docs/runbooks/restore.md`.
  - **Touches:** `docs/runbooks/restore.md`
  - **Acceptance:** Drill completes in <15 minutes; runbook is followable by anyone with shell access.
  - **Done note:**

- [ ] **D1.3** R2 retention policy: 7 daily + 4 weekly + 3 monthly = 14 backups kept rolling.
  - **Touches:** R2 lifecycle rule
  - **Done note:**

### D2 — Secrets

- [ ] **D2.1** Generate a 32-byte JWT secret. Document rotation procedure.
  - **Touches:** `docs/runbooks/secret-rotation.md`
  - **Done note:**

- [ ] **D2.2** Pydantic `production_required` validator: when `ENV=production`, refuses to boot if `JWT_SECRET`, `ANTHROPIC_API_KEY`, `DATABASE_URL`, `REDIS_URL` are missing or look like dev defaults.
  - **Touches:** `backend/app/core/config.py`
  - **Acceptance:** Booting with `ENV=production` and a default JWT raises; with strong values, boots cleanly.
  - **Done note:**

### D3 — CORS / cookies

- [ ] **D3.1** CORS allowlist driven by `CORS_ORIGINS` env var. Production list is hard-coded to the prod domain(s).
  - **Touches:** `backend/app/main.py`
  - **Acceptance:** A request from a foreign origin is rejected in prod mode.
  - **Done note:**

- [ ] **D3.2** Refresh-token cookie set with `Secure`, `SameSite=Lax`, `HttpOnly`, `Path=/api/v1/auth`.
  - **Touches:** `backend/app/api/v1/routes/auth.py`
  - **Acceptance:** Browser dev-tools shows the right flags.
  - **Done note:**

### D4 — Dependency audit

- [ ] **D4.1** Add `pip-audit` and `pnpm audit` to GitHub Actions CI. Block merge on critical/high vulnerabilities.
  - **Touches:** `.github/workflows/ci.yml`
  - **Done note:**

### D5 — Image hygiene

- [ ] **D5.1** Both Dockerfiles run as non-root user. Builder stages don't leak into runner.
  - **Touches:** `backend/Dockerfile`, `frontend/Dockerfile`
  - **Acceptance:** `docker run --rm pae-backend whoami` returns a non-root username.
  - **Done note:**

### D6 — Migration safety

- [ ] **D6.1** CI step: `alembic upgrade head --sql > /dev/null` against a fresh Postgres image. Fails if any migration emits invalid SQL.
  - **Touches:** `.github/workflows/ci.yml`
  - **Done note:**

- [ ] **D6.2** Verify the most recent 5 migrations have working `downgrade()` implementations. Test by rolling forward then back on a scratch DB.
  - **Touches:** maybe edits to migration files; otherwise just a runbook entry.
  - **Done note:**

### D7 — SLO + alerts

- [ ] **D7.1** Healthchecks.io ping for `/health/ready` every 5 minutes. Email/Slack on miss.
  - **Touches:** `docs/runbooks/oncall.md`
  - **Done note:**

- [ ] **D7.2** Sentry alert: error rate > 0.5% over a 10-minute window → email.
  - **Done note:**

### D8 — Smoke tests on deploy

- [ ] **D8.1** GitHub Actions step that runs after Fly deploy: hit `/health/ready`, log in as the smoke user, fetch `/today/summary`, assert 200 + non-empty.
  - **Touches:** `.github/workflows/deploy.yml`
  - **Done note:**

### D9 — Accessibility / mobile minimum

- [ ] **D9.1** axe-core CI run for 6 main screens (Today, Path, Practice, Promotion, Notebook, Catalog). Fails on serious or critical violations.
  - **Touches:** `frontend/e2e/axe.spec.ts`
  - **Done note:**

- [ ] **D9.2** Manual keyboard-only walk on Today + Practice. Fix any obvious traps.
  - **Touches:** discovered as needed
  - **Done note:**

### D10 — Lighthouse budget

- [ ] **D10.1** Lighthouse CI runs on Today, Practice, Notebook. Budget: Performance ≥ 80, Accessibility ≥ 95, Best Practices ≥ 95.
  - **Touches:** `frontend/lighthouserc.json`, `.github/workflows/ci.yml`
  - **Done note:**

**PR 3 verification:** All telemetry events visible in PostHog. Both Sentry projects receive a test error. Backup file present in R2 with timestamp from last night. Smoke test passes after a deploy.

---

## After PR 3 — production launch

- [ ] **LAUNCH-1** Pick production domain. Configure DNS at registrar.
- [ ] **LAUNCH-2** Fly deploy from `main` with prod env vars. Run smoke tests. Verify backups.
- [ ] **LAUNCH-3** Migrate demo users + capstone seeds.
- [ ] **LAUNCH-4** Open the URL to a small private cohort (≤20 students) for one week. Monitor Sentry / PostHog daily.
- [ ] **LAUNCH-5** Public launch.

---

## Operating procedure

### How an agent picks up work

1. Read this file top-to-bottom.
2. Read [`AGENT-OPERATING-SPEC.md`](./AGENT-OPERATING-SPEC.md) — non-negotiable engineering standards.
3. Find the **active PR** (the one whose status is "In progress" — only one is active at a time).
4. Find the next `[ ]` task **whose dependencies are met** and **whose `Touches:` paths are not currently claimed** by another in-flight task.
5. Update the task status to `[~]` (in progress) along with `claimed-by: <agent-id>` and `claimed-at: <ISO timestamp>` in the same line block.
6. Execute the task under the standards in the operating spec.
7. When done, flip to `[x]` and write a one-paragraph **Done note** with: what changed, what was tested, any follow-up filed.
8. Commit with the conventional-commits format and a body that references the task ID (`PR2/B1.1`, etc.).

### How parallel agents coordinate

- The Task ID owns the truth. If two agents try to claim the same one, the second one yields.
- A task is "in flight" if its checkbox shows `[~]`. Either flip it to `[x]` (done) or back to `[ ]` (released) — never leave a task `[~]` across sessions.
- Cross-PR work is forbidden. Finish PR N before any task in PR N+1 starts.

### How to resume from a fresh session

A fresh agent reads this doc, finds:
- which PR is active (look for `Status: 🔲 Not started`, `🟡 In progress`, `✅ Merged`),
- which tasks are `[ ]` (open), `[~]` (in flight), `[x]` (done),
- which dependencies the open tasks are waiting on,
- the operating spec for engineering standards.

The agent then either picks up an open task or, if none are unblocked, asks the human for guidance.

---

## Status legend

- 🔲 Not started — branch not cut yet
- 🟡 In progress — at least one task is `[~]` or `[x]`
- ✅ Merged — PR shipped to `main` and verified

---

## Change log for this document

- **2026-04-28** — Initial creation. PR 1 / 2 / 3 plan locked. Hosting target Fly + Neon + R2.
