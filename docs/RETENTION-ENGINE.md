# Retention Engine — Detailed Ticket List

**Owner:** Bhaskar
**Started:** 2026-04-29
**Goal:** Turn `/admin/*` from a static read-only dashboard into a **retention engine** — a system that detects students slipping out, intervenes through the right channel at the right time, and keeps the operator (Bhaskar = solopreneur) in the loop only at the moments that matter.

**Discoverable from:** [`PRODUCTION-READINESS.md`](./PRODUCTION-READINESS.md) banner + [`OPEN-ISSUES.md`](./OPEN-ISSUES.md) Tier-1 P1 entries.

---

## Why this exists (one paragraph)

A student who paid for a career change but never returned is the worst-case outcome of every learning platform. They feel trapped, will eventually request a refund, and their bad experience compounds into bad word-of-mouth. The product job is **to be a ratchet that catches students before they fall** — not "a dashboard for an admin," which is the developer frame. Six distinct slip patterns (cold-signup, unpaid-stalled, streak-broken, paid-silent, capstone-stalled, promotion-avoidant) each need their own detection, their own intervention, and their own admin surface. Email is the only universal channel for inactive students; in-app messaging only reaches the active ones. The operator (you) is the bandwidth-constrained resource — the system has to do most of the watching and most of the nudging.

---

## The six slip patterns

| # | Pattern | Detection signal | Why it matters | Intervention |
|---|---|---|---|---|
| 1 | **Cold signup** | `sessions_count == 0 AND days_since_signup > 1` | First session is the highest-leverage moment in the funnel | Day 1, 3, 7 emails (escalating personalization) |
| 2 | **Unpaid stalled** | `first_session_at IS NOT NULL AND days_since_first_session > 7 AND no payment` | Got past first-session friction; blocker is price/doubt | Day 7 social proof email; day 14 evidence + discount |
| 3 | **Streak broken** | `max_streak >= 3 AND last_session_at < now - 5d` | MOST recoverable churn class — life pulled them away | Day 5 low-friction return email; day 10 WhatsApp; day 14 personal call |
| 4 | **Paid silent** | `paid_at > now - 30d AND last_session_at < now - 7d` | Worst combination — paid + not using = refund risk | Day 3: email + WhatsApp; day 7: calendar invite; day 14: refund offer |
| 5 | **Capstone stalled** | `capstone_started_at IS NOT NULL AND last_capstone_draft_at < now - 14d` | Confidence churn, not time-management churn | Day 7: auto-trigger socratic_tutor with their last submission; day 10: worked-example agent; day 14: peer match |
| 6 | **Promotion avoidant** | `capstone_review_passed AND last_promotion_attempt_at < passed_at - 7d` | Imposter syndrome — needs permission to claim the win | Day 3: system celebration; day 7: cohort celebrator; day 10: direct prompt |

---

## Ticket states

- 🔲 **Open** — not yet started
- 🟡 **In progress** — replace with branch name in `On:` field
- ✅ **Closed** — keep entry, add `closed-by:` SHA + one-line resolution

---

## Tier 1 — Foundation (must build before launch)

These tickets are mutually independent at the file level (designed for parallel execution) but logically F4 reads from F1's output, F5 reads from F3's plumbing.

---

### ✅ F1 — `student_risk_service` + nightly scoring

**Status:** Open
**On:** _(not yet)_
**Depends on:** F0-migrations (cheap-now plumbing, see below)
**Touches:** `backend/app/services/student_risk_service.py` (new), `backend/app/models/student_risk_signals.py` (new), `backend/app/tasks/risk_scoring_task.py` (new), `backend/alembic/versions/0XXX_student_risk_signals.py` (new)
**Estimated:** 1 day

**What it builds:**

A service that, for every active user, computes:
- `risk_score`: 0-100 composite
- `slip_type`: one of `none | cold_signup | unpaid_stalled | streak_broken | paid_silent | capstone_stalled | promotion_avoidant`
- `days_since_last_session`: int
- `max_streak_ever`: int
- `recommended_intervention`: text key, e.g. `email_template_paid_silent_day3`

A nightly Celery task (Celery Beat at 03:00 UTC, off-peak for Neon) writes these into `student_risk_signals` (one row per user). A second-pass query produces the materialized panels for F4.

**Why this first:**
Every other feature reads from this. F4 panels filter by `slip_type`. F5 outreach picks templates by `recommended_intervention`. F2 admin notes display alongside `risk_score`. Build the spine first.

**Acceptance:**
- New table `student_risk_signals` (UUID PK, FK to users, computed_at timestamp, all 5 fields above) — migration applies cleanly via D6.1 CI
- Service unit-tested for each of the 6 slip patterns: given a fixture user with a specific session/payment history, returns the expected slip_type
- Celery task runs end-to-end against the test DB, populates one row per active user
- `risk_score` computation documented inline (which factors weight what)
- Production tests: 100 fixture users → all 6 slip_types represented in output

**Test plan:**
- Backend: pytest covering 6 fixture scenarios per slip pattern + edge cases (brand-new user, user with future-dated session, user with deleted enrollment)
- Manual: invoke the task locally, inspect 5 random rows in `student_risk_signals`, verify the slip_type matches the underlying data

**Surprises to watch for:**
- "Active user" definition: includes users in soft-deleted enrollments? My answer: NO — soft-deleted = out of cohort
- Time zones: all comparisons in UTC; never use server-local time
- Streak computation: define "streak day" as a session that included a `today.warmup_done` event (PR3/C3.2). Otherwise streak = sessions count, which is misleading

---

### ✅ F2 — `student_notes` (admin's private notes per student)

**Status:** Open
**On:** _(not yet)_
**Depends on:** F0-migrations
**Touches:** `backend/app/models/student_note.py` (new), `backend/app/api/v1/routes/admin.py` (extend), `backend/app/schemas/student_note.py` (new), `frontend/src/app/admin/students/[id]/page.tsx` (extend), `frontend/src/lib/hooks/use-admin.ts` (extend), `backend/alembic/versions/0XXX_student_notes.py` (new)
**Estimated:** 4 hours

**What it builds:**

Per-student admin-only private notes:
- Append-only — new notes don't overwrite, they accumulate
- Each note: actor_id (which admin), body (text), pinned (bool), created_at
- Visible on `/admin/students/{id}`: chronological feed + "Add note" textarea
- Pinned notes float to top
- The "Add note" stub on `/admin/page.tsx` becomes real (with same form)

**Why:**
Within the first week of active students, the operator (you) will forget which student you told what. Without notes, every interaction starts from zero. This is the tool that makes you remember.

**Acceptance:**
- `student_notes` table: UUID PK, student_id FK, actor_id FK to users, body TEXT (max 2000 chars), pinned BOOL DEFAULT FALSE, created_at, updated_at — soft delete supported
- New routes: `POST /api/v1/admin/students/{id}/notes` (admin gate via `_require_admin`), `GET /api/v1/admin/students/{id}/notes`, `PATCH /api/v1/admin/students/{id}/notes/{note_id}` (for pin toggle), `DELETE /api/v1/admin/students/{id}/notes/{note_id}` (soft)
- Frontend: notes feed on `/admin/students/{id}` below the timeline, "Add note" textarea + post button, pin toggle per note
- The console modal's "Add note" button opens a side-panel that writes to the same endpoint
- Admin tests: 403 for non-admin, 200 for admin
- E2E: admin types a note, refreshes, note persists

**Test plan:**
- Backend: 5 pytest cases — list (empty), create, list (1 row), pin, soft-delete
- E2E: 1 Playwright case — admin opens student detail, types "Called on Mon, said busy this week, will follow up Fri", saves, refreshes, note shows up

**Surprises to watch for:**
- Markdown rendering: notes should NOT render markdown (you'll write quick prose, not formatted docs). Plain `<pre className="whitespace-pre-wrap">` is correct.
- 2000 char cap is generous; below 100 chars probably typical
- Pinning: only one pinned note per student? Or multiple? Decision: multiple, sorted pinned-first

---

### ✅ F3 — `outreach_log` table + service

**Status:** Open
**On:** _(not yet)_
**Depends on:** F0-migrations
**Touches:** `backend/app/models/outreach_log.py` (new), `backend/app/services/outreach_service.py` (new), `backend/alembic/versions/0XXX_outreach_log.py` (new)
**Estimated:** 3 hours

**What it builds:**

Single audit table for every outreach we send (now or later, system or admin):

```sql
CREATE TABLE outreach_log (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  channel TEXT NOT NULL,        -- 'email' | 'whatsapp' | 'sms' | 'in_app' | 'phone'
  template_key TEXT,             -- 'cold_signup_day_1' | NULL for ad-hoc
  slip_type TEXT,                -- denormalized for fast filtering
  triggered_by TEXT NOT NULL,    -- 'system_nightly' | 'admin_manual'
  triggered_by_user_id UUID,     -- when admin-triggered, who
  sent_at TIMESTAMP WITH TIME ZONE NOT NULL,
  delivered_at TIMESTAMP WITH TIME ZONE,
  opened_at TIMESTAMP WITH TIME ZONE,
  replied_at TIMESTAMP WITH TIME ZONE,
  body_preview TEXT,             -- first 200 chars for audit trail
  external_id TEXT,              -- SendGrid message id, Twilio sid, etc.
  status TEXT NOT NULL,          -- 'pending' | 'sent' | 'delivered' | 'bounced' | 'failed'
  error TEXT
);
```

Plus `OutreachService` with:
- `record(...)` — writes a row
- `was_sent_recently(user_id, template_key, within_days)` — for per-user-per-week throttle
- `mark_delivered(external_id)`, `mark_opened(external_id)` — webhook handlers
- `list_for_user(user_id)` — admin view

**Why:**
Without this, F5 (email) and F9 (automation) will spam students. Build the audit table BEFORE the senders, not after. Cheap to add now, expensive to retrofit.

**Acceptance:**
- Migration applies cleanly
- Service has 4 methods, each unit-tested
- `was_sent_recently` index: `(user_id, template_key, sent_at DESC)` — query plan should be index-only

**Test plan:**
- Backend: 6 pytest cases — record, list_for_user, throttle (within window = blocked), throttle (outside window = allowed), mark_delivered idempotent, mark_opened
- No frontend in this ticket — F4 + F5 consume it

**Surprises:**
- Throttle is per-template, not per-user globally. A "paid silent day 3" email and "paid silent day 7" email are different templates, both can fire for the same user
- Webhook signatures (SendGrid, Twilio): verify before recording. F5 owns the signature check; F3 trusts pre-validated input

---

### ✅ F4 — Real `/admin/console` panels (kill the mock data)

**Status:** Open
**On:** _(not yet)_
**Depends on:** F1
**Touches:** `frontend/src/app/admin/page.tsx` (rebuild central section), `backend/app/services/admin_console_service.py` (extend or rebuild), `backend/app/api/v1/routes/admin.py` (extend)
**Estimated:** 1 day

**What it builds:**

Replace the mock-data sections of `/admin` with five real, query-driven panels:

1. **"Paid + silent"** — Slip 4 students. Highest priority. Top of page.
2. **"Capstone stalled"** — Slip 5. Second priority. Show last submission inline so admin sees what's broken.
3. **"Streak broken"** — Slip 3. Third priority.
4. **"Cold signups"** — Slip 1. Lower priority but bigger volume.
5. **"Ready but stalled"** — Slip 6. Easy wins.

Each panel:
- Reads from `student_risk_signals` (F1) filtered by `slip_type`
- Shows top 10 students per panel, full list behind a "See all (N)" link
- Each row: avatar + name + last_session_age + risk_score + a CTA matching the slip's intervention pattern
- The 5 questions from the dashboard spec, answered with real data, no mock fixtures

**Why:**
This is the difference between admin-as-toy and admin-as-tool. Right now `/admin` looks impressive but reads from mock data — operator can't act on it. After F4, every number is derivable from the database.

**Acceptance:**
- All five panels render with live data on local docker
- "Paid + silent" with 0 students shows a clean empty state ("Nice — every paid student is active.") not a broken table
- Funnel widget at the top: 5 numbers (signups → first-session → paid → capstone → promoted) all from real queries
- Pulse strip: keeps the 6 metrics, all from real queries (PR3/C7.1 already wired the cost number)
- The deleted mock arrays are GONE from the source — no `MOCK_STUDENTS` lingering

**Test plan:**
- Backend: 1 pytest per panel querying a fixture DB — 5 panels × 2 cases each (with data, empty)
- E2E: 1 Playwright case asserting all 5 panels render against a seeded DB
- MCP: walk every panel after deploy, verify numbers match `psql` direct queries

**Surprises:**
- "Capstone stalled" panel needs the last submission's code rendered inline. ~150 char preview; full code in a modal-on-click. Don't paste 5KB of student code into the dashboard
- Sort order within each panel: by `risk_score DESC` so the worst case is row 1
- Top-right console search box (currently dead) gets wired to filter all 5 panels at once

---

### ✅ F5 — Email outreach service (SendGrid wrapper)

**Status:** Open
**On:** _(not yet)_
**Depends on:** F3
**Touches:** `backend/app/services/email_service.py` (new), `backend/app/services/outreach_service.py` (extend with `send_email` orchestration), `backend/app/templates/email/` (new dir for HTML templates), `backend/app/api/v1/routes/webhooks.py` (extend for SendGrid webhook), `backend/pyproject.toml` (already has sendgrid)
**Estimated:** 6 hours

**What it builds:**

Wraps SendGrid in a thin chokepoint:
- `send_email(to_user_id, template_key, vars)`:
  1. Calls `OutreachService.was_sent_recently()` — if blocked, skip + log
  2. Loads HTML template from `app/templates/email/{template_key}.html` + Jinja2-renders `vars`
  3. Calls SendGrid's `mail/send` API
  4. Logs to `outreach_log` with status=`pending`, then `sent` on successful API response
  5. SendGrid webhook (`POST /api/v1/webhooks/sendgrid`) flips to `delivered` / `opened`
- No-op safe: when `SENDGRID_API_KEY` is unset, logs the email at INFO + writes to `outreach_log` with status=`mocked`. Dev/CI work normally.
- Rate-limited: max 1 send per user per template per 24h (defense in depth on top of F3 throttle)
- PII filter: strips student email from logs (only user_id is referenced in structured logs)

**Why:**
Email is the only universal channel for inactive students. Build the chokepoint once; F9 (nightly automation) and the F4 admin "Send email" button both call into it.

**Acceptance:**
- Service unit-tested for: send happy path, send throttled (returns `{skipped: true, reason: 'throttle'}`), send no-DSN (mocked), send 5xx from SendGrid (logged, status=`failed`, doesn't crash caller)
- Webhook tested for: valid signature → status flip, invalid signature → 401
- One end-to-end test using SendGrid's sandbox mode: real API call, real webhook, real DB row

**Test plan:**
- Backend: 8 pytest cases — happy, throttle, no-key, 5xx, webhook valid, webhook invalid sig, webhook with unknown external_id, idempotency
- Manual: in dev with mocked mode, trigger a send, verify outreach_log row, verify the rendered HTML matches template

**Surprises:**
- SendGrid's `personalizations` API supports batch sending; we use single-recipient for simplicity (and per-user PII isolation)
- Webhook signature: SendGrid uses an Ed25519 public key, NOT HMAC like Stripe. Don't copy the Stripe verification code blindly
- Bounces: a bounce should mark the user's email as `bounced` so we don't keep retrying. Add `users.email_bounced_at` (small migration in this ticket)

---

### ✅ F6 — Six email templates (one per slip type)

**Status:** Open
**On:** _(not yet)_
**Depends on:** F5
**Touches:** `backend/app/templates/email/cold_signup_day_1.html`, `..._day_3.html`, `..._day_7.html`, `unpaid_stalled_day_7.html`, `unpaid_stalled_day_14.html`, `streak_broken_day_5.html`, `paid_silent_day_3.html`, `paid_silent_day_7.html`, `capstone_stalled_day_7.html`, `promotion_avoidant_day_3.html` (and a few more — 12 total at the day-cadence level for 6 slip types)
**Estimated:** 4 hours (drafting + you reviewing)

**What it builds:**

12 markdown-source email templates (rendered to HTML by Jinja2 in F5). Each template:
- Subject line (specific, not "Quick check-in")
- Body in plain prose (not corporate)
- Single CTA — never multiple choices, always one obvious action
- Personalized: `{{name}}`, `{{target_role}}`, `{{days_since}}`, `{{last_lesson_title}}`, etc.
- Footer with unsubscribe link (legal requirement)

I'll draft all 12; you review them once. Tone calibrated to:
- Not corporate — written like a friend
- Not pushy — never "you're falling behind"
- Specific to slip type — Slip 4 (paid silent) is more direct than Slip 1 (cold signup)
- Always offers a no-effort path forward

**Why:**
These ARE the product for inactive students. They're the only thing the student sees. Generic "we noticed you haven't been around" reads as automated and gets ignored.

**Acceptance:**
- 12 templates committed, each with realistic test variables in a comment block at the top
- A `render_email_preview` admin route (or local script) renders any template to an HTML file for manual review
- All 12 reviewed and approved by Bhaskar before merge
- Subject lines stored in template frontmatter so F5 can read them without parsing the HTML
- Unsubscribe link points to a real `/unsubscribe?token=...` route (nano-feature: F6 includes the unsubscribe handler too)

**Test plan:**
- Render each template with synthetic vars, eyeball the output
- Send each template to your real email via SendGrid sandbox, check rendering on Gmail / Apple Mail / mobile

**Surprises:**
- Mobile-first: 60% of students will read on phone. Templates use a single-column layout, no nested tables
- Image-free: outlook strips images. Templates use plain text + maybe an emoji or two
- Reply-to: set to `bhaskar@yourdomain` not `noreply@`. Students should be able to reply and have it land in your inbox

---

## Tier 2 — Right after Tier 1 lands

### 🔲 F7 — WhatsApp Business outreach (via Twilio)

**Status:** Open
**Depends on:** F3, F5 (template pattern)
**Estimated:** 1 day
**Why later:** WA is high-cost per message ($0.005-$0.05) and high-friction setup (Twilio approval, template approval). Reserve for Slip 4 (paid + silent) only. Don't build until F1-F6 prove email isn't enough.

**What it builds:** Same shape as F5 but Twilio. Pre-approved WA templates (Twilio requires this). Same `outreach_log` entry shape. Same throttle.

---

### ✅ F8 — In-app DM (real implementation)

**Status:** Closed by `c48f96d` (merged via `c673e5e`)
**Depends on:** F3
**Estimated:** 1.5 days
**Why later:** Only useful for *active* students. The retention engine's first concern is *inactive* students. Build after F1-F6 ship.

**What shipped:** `student_messages` table (alembic 0053, chained off F11's 0052), admin compose card on `/admin/students/{id}` alongside refund offer + admin notes. Student-side endpoints: unread-count poller, thread list, thread detail, reply, mark-read. Admin sends double-write to `outreach_log` for engagement attribution; student replies stamp `replied_at` on the most recent admin/system outreach. 8/8 service tests green.

---

### ✅ F9 — Nightly `disrupt_prevention_v2` Celery task

**Status:** Closed by `61ebcd8` (merged via `c673e5e`)
**Depends on:** F1, F3, F5, F6
**Estimated:** 4 hours
**Why later:** Don't auto-send emails until F1-F6 are solid AND we've manually sent through the system at least 50 times. Otherwise we'll auto-send a bug to 100 students.

**What shipped:** `disrupt_prevention_v2_service.run_nightly_outreach` reads `student_risk_signals` (F1), dispatches via the slip-typed templates from F5/F6. Layered defenses: production gate (ENV=production AND OUTREACH_AUTO_SEND=1), per-template throttle (F3), global cap of 2/week per user (admin_manual sends excluded), excluded test/dev email suffixes, AUTOMATABLE_SLIPS allowlist of 6 slip types. Beat schedule entry `outreach-automation-nightly` at 09:00 UTC (6h after F1's 03:00 risk scoring, leaving an operator review window). 8/8 service tests green.

---

### ✅ F10 — Calendar integration (mailto-shim)

**Status:** Closed by `a7762fb` (merged via `475591a`)
**Estimated:** 1.5 days
**Why later:** Required when you have >20 paid students. Until then, mailto: with subject "Quick check-in?" works.

**What shipped:** `buildCallInviteMailto` helper + "Schedule call" CTA on `/admin/students/{id}` that generates a mailto URL with student email pre-filled and a slip-type-aware subject/body. Real Cal.com / OAuth integration deferred to Tier 3.

---

### ✅ F11 — Refund offer flow (Slip 4 day 14)

**Status:** Closed by `1bc1c7e` (merged via `475591a`)
**Depends on:** F9
**Estimated:** 4 hours
**Why later:** Risk of mis-firing — don't auto-offer refunds until you've validated the trigger by hand a few times.

**What shipped:** `refund_offers` table (alembic 0052), admin-only refund offer card on `/admin/students/{id}` visible only when student is in the paid_silent risk panel. Admin clicks "Send refund offer", service writes the offer row + sends the templated email + records to `outreach_log`. Send failures keep the offer in `proposed` state for retry. 5/5 service tests green + 1 Playwright e2e.

---

## Tier 3 — Polish

### ✅ F12 — Wire pulse 24h/7d/30d windows
**Closed by `7b80094`.** Backend takes `?window=24h|7d|30d`; frontend tab switcher recomputes active_students, agent_calls, avg_eval_score. Legacy `_24h` response keys preserved on default window for backwards-compat.

### ✅ F13 — Admin sort columns on `/admin/students`
**Closed by `7b80094`.** Sortable headers on Joined / Name / Last seen (server-side via `?sort=`) + Lessons / AI Chats (client-side off the limit-capped page). Adds a "Last seen" column that was missing before.

### ✅ F14 — Student-detail timeline pagination
**Closed by `7b80094`.** Backend `?before=<iso-ts>` cursor; "Load older" button below the timeline fetches the next page. Synthetic "Last login" anchor only emitted on the first page so it doesn't duplicate.

---

## F0 — Cheap-now plumbing migrations (NOW, before any of the above)

**Status:** 🔲 Open
**Estimated:** 30 minutes
**Touches:** Two new alembic migration files only

**What it builds:**

1. `0XXX_outreach_log.sql` — creates the table. No service yet (that's F3); just the schema.
2. `0XXX_student_notes.sql` — creates the table. No API yet (that's F2).
3. `0XXX_student_risk_signals.sql` — creates the table. No service yet (that's F1).

**Why now:** All Tier 1 work depends on these tables existing. Adding the migrations today (in one commit) means F1-F4 can start in parallel without waiting on each other for migrations. They'll pass D6.1 CI fresh-Postgres apply on next push.

**Acceptance:**
- 3 migrations apply cleanly
- `alembic upgrade head` then `alembic downgrade -3` round-trips
- D6.1 CI green on the PR

---

## Dependency graph + parallelization plan

```
                       F0 (3 migrations, 30 min)
                          │
              ┌───────────┼───────────┐
              ▼           ▼           ▼
            F1          F2          F3
        (risk svc)  (notes UI)  (outreach log)
              │                       │
              │                       ▼
              │                      F5 (email service)
              │                       │
              ▼                       ▼
            F4 (console panels)  F6 (templates × 12)
                                      │
                                      ▼
                                Tier 2: F7 / F9 / F11
                                Tier 3: F12 / F13 / F14
```

**Parallel-safe groups (do simultaneously):**

- **Wave 1 (after F0)**: F1 + F2 + F3 — no file overlap, three different domains
- **Wave 2 (after Wave 1)**: F4 (depends on F1) + F5 (depends on F3) — no file overlap
- **Wave 3 (after F5)**: F6 templates — sequential drafting

**Lessons from PR3 parallel-agent attempt:**
- Always pass `isolation: "worktree"` to background agents
- Size each agent's scope to ~5-7 small actions (we hit usage caps when we tried 10+ per agent)
- Local main session takes the most file-conflicting work; agents take infra-flavored or model/migration work
- Merge-coordination eats ~15 min per agent — factor that in

**Concrete plan for this round:**
- F0 (migrations): main session, 30 min
- F1 + F2 + F3: main session takes F1 (most logic-dense), spawn 2 isolated agents for F2 and F3
- Wave 2: main takes F4 (UI-heavy), spawn 1 agent for F5 (backend chokepoint)
- F6: main session, sequential, with you reviewing each draft

---

## Production-quality testing checklist (per ticket)

Every ticket follows the same definition-of-done. Don't merge without all four:

| Layer | What | Why |
|---|---|---|
| **Backend pytest** | Unit tests for the service + integration test that hits the route + asserts DB state | Locks correctness at the data-access layer |
| **MCP exploratory** | Walk the live UI as student + admin, capture screenshots, find what unit tests can't | Catches "the page doesn't render the right shape even though the API is correct" |
| **Playwright spec** | Add to `frontend/e2e/admin-coverage.spec.ts` — every workflow that mutates state gets a regression lock | CI catches the regression on every PR forever |
| **`OPEN-ISSUES.md` close** | Move closed item to ✅ section with commit SHA | Receipts survive |

Plus a global integration test after Wave 2 lands: seed the demo DB → run F9 in dry-run → verify F4 panels populate from F1's `student_risk_signals` → manually click an F2 note → verify F3 outreach_log gets a row.

---

## Sign-off needed before I start

This document is the plan. Before I touch code:

1. ✅ / ❌ — Tier 1 (F0 + F1-F6) is the launch-blocking set. Tier 2 + 3 are deferred.
2. ✅ / ❌ — The 6 slip patterns are correct. (or which to add/remove?)
3. ✅ / ❌ — Email-first; WhatsApp/calendar/in-app are Tier 2.
4. ✅ / ❌ — Parallel plan: main session takes F1+F4+F6, two isolated agents take F2+F3 then F5.
5. ✅ / ❌ — F0 migrations land today (30 min); Wave 1 starts immediately after; full Tier 1 done in ~4 days.

Once you give the green light on all five, I execute as senior engineer: F0 first, then waves with full test discipline per the checklist above.

---

## Closed tickets

### Tier 1 (foundation) — 2026-04-30

All 6 core tickets shipped in a single coordinated build. Total: ~2 days work, 27 backend pytests + 7 Playwright e2e specs all green, MCP-verified live against the running stack.

**F0 — Cheap-now plumbing migrations**
- 0049_student_risk_signals — created
- 0051_outreach_log — created
- 0050_student_notes (originally planned) — discovered table already existed from Phase 3 (`0014_student_notes.py`); reused existing schema rather than alter
- closed-by: `3197dec` (merged via `82e6246`)

**F1 — student_risk_service + nightly scoring**
- New `app/models/student_risk_signals.py`
- New `app/services/student_risk_service.py` — 6 slip pattern classifier with priority order (paid_silent > capstone_stalled > streak_broken > promotion_avoidant > unpaid_stalled > cold_signup)
- New `app/tasks/risk_scoring.py` — Celery Beat scheduled at 03:00 UTC daily
- 14 unit tests covering all 6 slip patterns + priority conflicts + edge cases
- **Live data: scored 101 users, found 97 cold_signups + 4 healthy** when invoked manually
- closed-by: `3197dec` (merged via `82e6246`)

**F2 — student_notes admin UI**
- Backend routes were already shipped in Phase 3 (`POST/GET /admin/students/{id}/notes`)
- New hooks: `useStudentNotes`, `useCreateStudentNote`
- Notes card added to `/admin/students/{id}` between Trigger agent and Activity timeline
- MCP verified end-to-end: typed → 201 POSTed → rendered → textarea cleared
- closed-by: `3197dec` (merged via `82e6246`)

**F3 — outreach_log table + OutreachService**
- New `app/models/outreach_log.py`
- New `app/services/outreach_service.py` with `record`, `was_sent_recently` (per-template throttle), `mark_delivered`, `mark_opened`, `list_for_user`
- 7 unit tests covering throttle window, per-template separation, idempotent webhooks, failed-status doesn't block retry
- closed-by: `3197dec` (merged via `82e6246`)

**F4 — Real `/admin` retention panels (kill mock data)**
- New backend `GET /admin/risk-panels` returns 5 panels with top-N students per slip type
- New `app/admin/_components/retention-panels.tsx` — 5-panel grid with priority ordering, empty states, "see all (N)" links
- Drops above the legacy ACTION BAND on `/admin/page.tsx` (legacy mock-data section retained pending v2 rebuild)
- MCP verified: all 5 panels render with correct totals matching API
- closed-by: `3197dec` (merged via `82e6246`)

**F5 — Outreach email service (SendGrid wrapper)**
- New `app/services/outreach_email_service.py` (distinct from legacy `email_service.py` which handles welcome/digest emails)
- No-op safe: missing SENDGRID_API_KEY → status='mocked', dev/CI work normally
- Audit-before-network: row written with status='pending' before SendGrid call, flipped to 'sent'/'failed' after
- 6 unit tests: mocked path, throttled, no-recipient, render-failure, real-send (mocked SDK), SDK-exception swallowed
- closed-by: `3197dec` (merged via `82e6246`)

**F6 — Six email templates (one per slip pattern)**
- `cold_signup_day_1.html` — first-session reminder, refs target_role
- `unpaid_stalled_day_7.html` — social proof, no-discount-yet
- `streak_broken_day_5.html` — most recoverable; warm, low-friction return
- `paid_silent_day_3.html` — refund risk; signed Bhaskar; reply-with-one-word CTA
- `capstone_stalled_day_7.html` — confidence churn; specific unblock path
- `promotion_avoidant_day_3.html` — celebrate; lower the perceived bar
- All Jinja2-rendered, mobile-first single-column, frontmatter-style `{% set subject = ... %}`
- closed-by: `3197dec` (merged via `82e6246`)

**E2E coverage (Playwright)**
- New `frontend/e2e/retention-engine.spec.ts` — 7 tests covering F4 panel render, totals API contract, F2 add-note round-trip, zero console errors, admin-gate enforcement
- Combined with admin-coverage + production-readiness specs: **30/31 green** (1 intentional skip)

### Lessons learned

- **Phase 3 already had a `student_notes` table.** Always grep for existing schema before writing migrations — `0014_student_notes.py` was already shipped. Saved a migration, reused existing model.
- **Production Dockerfile doesn't include `tests/`.** To run pytest in the container, copy tests/ + conftest.py in via `docker cp` and run `cd /app && uv run python -m pytest`. Setting PYTHONPATH alone doesn't work — must `cd` first.
- **Playwright strict mode catches text duplication.** When a sentinel string lives in BOTH the textarea (still typed) and the rendered note list, `getByText(sentinel)` fails strict-mode. Target `ol li pre` to scope to the rendered note specifically.
- **F1 risk service has v1-quality payment detection.** Currently `paid_at = None` for all users (documented in code). F1.1 (follow-up) will wire payment data once the canonical "is paid" signal is settled.
