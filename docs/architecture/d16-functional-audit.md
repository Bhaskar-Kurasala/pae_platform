# D16 CP1 — Functional Audit of Retention Engine

**Status:** Read-only investigative audit (CP1 of D16). No code changes.
**Created:** 2026-05-08 (post-D15 closure at `27125fa`).
**Method:** Three parallel sub-agents inspected source under
`backend/app/`, `frontend/src/app/admin/`, `docker-compose.yml`,
`fly.toml`, and `docs/followups/`. Cross-checked against the
D16 pre-flight audit (`d16-pre-flight-admin-surface-audit.md`).
**Scope:** 14 verification points (a-n) per the D16 prompt.

---

## Executive summary

The retention engine is **substantially operational** end-to-end. Of 14
verification points:

- **8 are WORKS** (a, b, c [all panels], e, f, g, k)
- **3 are PARTIAL** with non-blocking gaps (h, i, j, m)
- **1 is HIGH-severity launch blocker** (l: Celery Fly worker/beat apps not deployed; concurrency mis-set)
- **1 is STALE-but-safe / scaffolded-but-inert** (d: `admin_console_*` cluster — but the cockpit was already migrated to read primary tables; tables are now a safety net awaiting drop migration)
- **1 is workflow assessment, not a verification** (n: WhatsApp workflow gap — admin notes + in-app DM cover async, but no `wa.me/` deep link / phone field / "log WA contact" button)

**Total HIGH-severity: 1** (Celery Fly deployment). Comfortably under the 6-HIGH stop condition.

**Bug 24-class architectural finding:** none. The `admin_console_*`
cluster looked like a candidate, but inspection revealed an explicit
documented migration path: the cockpit `/api/v1/admin/console/v1`
already reads from primary tables (LD-1..LD-5 annotations), and the
admin_console_* tables are kept "for one more deploy as a safety net"
per `backend/app/api/v1/routes/admin.py:2051-2053`, with a follow-up
drop migration noted. This is documented technical debt cleanup, not
an architectural failure.

---

## Per-verification-point findings

### a — `risk_scoring` Celery task — **WORKS**

- **Tested:** Task → service path; slip_type enum alignment.
- **How:** Read `backend/app/tasks/risk_scoring.py:1-38`; cross-checked `backend/app/services/student_risk_service.py` (`classify()` line 238) and `disrupt_prevention_v2_service.py:71-80` (AUTOMATABLE_SLIPS).
- **Evidence:** Task awaits `score_all_users(session)` and persists upsert-by-user_id (`tasks/risk_scoring.py:20-28`). `classify()` writes correct `slip_type` (line 333). All 7 slip types align across model, service, and consumer.
- **Severity:** N/A.

### b — `outreach_automation` Celery task — **WORKS**

- **Tested:** Dry-run default; throttle; slip_type denormalization.
- **How:** Read `backend/app/tasks/outreach_automation.py:1-42`; traced into `backend/app/services/disrupt_prevention_v2_service.py:1-282`.
- **Evidence:**
  - Dry-run gate: `_should_actually_send()` requires `ENVIRONMENT=="production"` AND `OUTREACH_AUTO_SEND=="1"` (`disrupt_prevention_v2_service.py:152-158`).
  - Dry-run path writes `outreach_log` rows with `status="would_send"` (line 246).
  - Throttle: `outreach_service.was_sent_recently(db, user_id, template_key, within_days=7)` invoked before each send (lines 220-225).
  - Slip_type denormalization: `slip_type=signal.slip_type` passed into record() (line 244).
- **Severity:** N/A.

### c — Admin cockpit rendering — **WORKS** (all panels)

| Panel | Status | Evidence |
|---|---|---|
| Retention panels (5 slip cards) | ✅ | `frontend/src/app/admin/_components/retention-panels.tsx:46-289`; backend `admin.py:387-470` |
| Pulse strip (KPI cards) | ✅ | `frontend/src/app/admin/page.tsx:518-542`; spark via inline SVG `sparkPath()` (144-158) |
| Funnel chart | ✅ | `page.tsx:950-1025`; SVG with leak detection at dropPct ≥ 35% (line 568) |
| Action band (top-3 at-risk) | ✅ | `page.tsx:237-245, 423-484`; mailto via `buildCallInviteMailto()` |
| Roster (sortable + filterable) | ✅ | `page.tsx:627-826`; 6 general + 5 slip-pattern filter chips; client-side substring search; deep-link via `?slip_type=` |
| Student detail panel — agent trigger card | ✅ | `student-detail-panel.tsx:401-473`; 4 triggerable agents (re_engagement, weekly_report, learning_path, celebrate) |
| Student detail panel — refund offer card | ✅ | `student-detail-panel.tsx:476-551`; conditional render on paid_silent match |
| Student detail panel — admin notes card | ✅ | `student-detail-panel.tsx:554-622`; 2000-char limit; reverse-chrono list |
| Student detail panel — DM card | ✅ | `student-detail-panel.tsx:624-701`; thread mirror to outreach_log |
| Student detail panel — activity timeline | ✅ | `student-detail-panel.tsx:703-766`; cursor-stack pagination |

- **Backend response shape:** Frontend `ConsoleResponse` types (page.tsx:19-92) match `get_admin_console` return (`admin.py:2015-2159`). LD-1..LD-5 read from primary tables (users, student_risk_signals, agent_actions, learning_sessions, etc.) — NOT from admin_console_*. See finding (d).
- **Code health:** No broken imports, no `// TODO` / `// FIXME` in admin frontend. Skeleton/error states present everywhere. React Query mutations have proper invalidation.
- **Severity:** N/A.

### d — `admin_console_*` table cluster — **STALE, SAFE, SCAFFOLDED-BUT-INERT** ⚠️

This was the audit's most architecturally significant finding. The
cluster's resolution shape is materially different from what the D16
prompt anticipated.

- **All 8 models exist** (`backend/app/models/admin_console.py:31-167`): Profile, Engagement, FunnelSnapshot, PulseMetric, FeatureUsage, Event, Call, RiskReason. Migration `0039_admin_console_v1` creates all tables with indexes.
- **ZERO writers found** across `backend/app/services/`, `backend/app/tasks/`, `backend/app/agents/`, `backend/app/repositories/`.
- **Reader is already migrated to live primary tables.** `get_admin_console` (`admin.py:2016`) explicitly documents (lines 2051-2053) that the admin_console_* tables "remain in the schema for one more deploy as a safety net; they are dropped by a follow-up alembic migration once this code soaks in production." LD-1 through LD-5 read from users, student_risk_signals, agent_actions, learning_sessions, exercise_submissions, goal_contracts, student_progress, course_entitlements, outreach_log, cohort_events, payments, refunds (lines 2037-2049).
- **Status:** SCAFFOLDED-BUT-INERT (Pattern 29 candidate), but **safe** — the cockpit is not reading stale data. The tables are merely empty schema awaiting drop.
- **Severity:** **MEDIUM** (technical debt / cleanup, not data correctness). Does not block launch.
- **CP2 implication:** The D16 prompt's "Path A: build writers" vs "Path B: migrate cockpit reads" decision is **moot**. The cockpit is already on Path B. CP2.1 simplifies to: (i) verify LD-1..LD-5 actually return correct data on dev DB, then (ii) ship the drop migration for admin_console_* tables (or keep them dormant for one more deploy as the code comment intends, then drop).

### e — `admin_send_message` flow — **WORKS**

- **Tested:** Route → service → StudentMessage + outreach_log + thread grouping + reply tracking.
- **How:** Read `admin.py:2199-2222`, `student_message_service.py:45-148`, models.
- **Evidence:**
  - Route invokes `student_message_service.create_message()` with `sender_role="admin"` (admin.py:2214-2221).
  - StudentMessage row written with `sender_role` and UUID4 thread_id (service:70-81).
  - `_record_admin_outreach()` (service:83-89) writes outreach_log with `channel="in_app"`, `triggered_by="admin_manual"`, `triggered_by_user_id=admin_id`.
  - Reply path: student reply queries OutreachLog with `replied_at IS NULL` AND `triggered_by IN ("admin_manual", "system_nightly")`, orders DESC by sent_at, flips `replied_at` to now() (service:124-148).
- **Severity:** N/A.

### f — `create_student_note` flow — **WORKS**

- **Tested:** Route → service → StudentNote; append-only.
- **How:** Read `admin.py:478-492`, `student_note_service.py`, StudentNote model.
- **Evidence:**
  - Route POST /students/{id}/notes calls `add_note()` with admin_id, student_id, body_md.
  - Append-only enforced **structurally**: only `@router.post()` (create) and `@router.get()` (list) exist. No PUT/PATCH endpoint. Implicit guard by absence.
  - FK cascades on delete confirmed (model lines 26-30, 32-35).
- **Severity:** N/A.

### g — `refund_offer` flow — **WORKS**

- **Tested:** RefundOffer + SendGrid + outreach_log + linkage.
- **How:** Read `admin.py:551-580`, `refund_offer_service.py:46-141`, `outreach_email_service.py:95-261`.
- **Evidence:**
  - propose_refund writes RefundOffer with `status="proposed"` (service:54-64).
  - send_refund_offer calls `outreach_email_service.send_outreach_email()` with `template_key="refund_offer"`, `triggered_by="admin_manual"` (service:107-115).
  - outreach_email_service writes outreach_log row (lines 194-204), then flips status to 'sent'/'mocked'/'failed' after SendGrid call (lines 230-261).
  - On success, `offer.outreach_log_id = result.log_id` (service:124) and `offer.status = "sent"` (123). Linkage confirmed.
- **Severity:** N/A.

### h — `inactivity_sweep` Celery task — **PARTIAL**

- **Tested:** Event logging; consumption path.
- **How:** Read `backend/app/tasks/inactivity_sweep.py:1-39`; searched for consumers.
- **Finding:** The task logs `re_engagement.flagged` to **structlog only**. No DB row is written (no event_log, no notification, no agent_proactive_runs entry). The task docstring claims "the existing disrupt_prevention agent consumes these via the chat/agents surface," but **there is no consumer reading these events on chat-surface entry**. Re-engagement messaging today actually fires only via the admin-cockpit "trigger agent" button, not via this cron.
- **Severity:** **MEDIUM**. Misaligned docstring, not a launch blocker. The retention surface still works because admin can manually trigger re_engagement; the cron is observational.
- **Minimum-fix proposal:** Either (a) wire event persistence so disrupt_prevention can query recent flagged events at chat entry, or (b) update the docstring to reflect that the cron is observational-only and re-engagement is admin-triggered. **Option (b) is the cheaper pre-launch fix.** Real auto-consumption is post-launch work.

### i — `weekly_letters` Celery task — **PARTIAL**

- **Tested:** progress_report invocation; Notification; SendGrid; outreach_log audit.
- **How:** Read `backend/app/tasks/weekly_letters.py:1-238`.
- **Finding:** progress_report agent invoked correctly (line 104). Notification rows written (lines 131-145). Email sent via `email_service.send_weekly_letter()` (line 151) with graceful exception catch (158). **However: no `outreach_log` row written with `template_key='weekly_letter'`.** The email goes through EmailService directly, bypassing the outreach_service.record() audit trail.
- **Severity:** **MEDIUM**. Audit gap; weekly letters do not appear in the per-student outreach feed. Operator visibility into "when did this student last hear from us" is incomplete.
- **Minimum-fix proposal:** After successful send (line 156), call `await outreach_service.record(db, user_id=user.id, channel='email', template_key='weekly_letter', triggered_by='system_weekly_letters', status='sent')`.

### j — `growth_snapshots` Celery task — **PARTIAL**

- **Tested:** Write path; admin read-side.
- **How:** Read `backend/app/tasks/growth_snapshots.py:1-59`; grepped admin routes.
- **Finding:** Write side works (`build_and_persist(session, uid)` at line 39, idempotent on (user_id, week_ending)). Read side: only `/api/v1/receipts/me` exposes growth_snapshots, and only for the authenticated student themself. **No admin endpoint** reads cohort growth data. The cockpit does not consume growth_snapshots.
- **Severity:** **LOW** (post-launch defer). The cron runs and data is being written; an admin cohort view is enhancement, not defect.
- **Minimum-fix proposal:** Defer to D17b/post-launch. If pre-launch convenience desired, add `GET /api/v1/admin/growth-snapshots?week_ending=...` returning a cohort summary.

### k — `proactive_runner` infrastructure — **WORKS** (zero usage)

- **Tested:** Decorator + dispatch + idempotency + agent usage.
- **How:** Read `backend/app/agents/primitives/proactive.py`, `backend/app/tasks/proactive_runner.py`, `backend/app/core/celery_app.py:109-136`.
- **Evidence:**
  - `@proactive(cron=...)` decorator and `_proactive_schedules` registry exist (`primitives/proactive.py:118, 122-172`).
  - `register_proactive_schedules(celery_app)` merges into beat_schedule at boot (lines 617-678 of primitives + celery_app.py:109-136).
  - Idempotency key `cron:{agent}:{cron_expr}:{minute_bucket}[:{user_id}]` enforced via partial unique index ON CONFLICT (lines 458-461).
  - **Production agents using @proactive: zero.** Only `study_planner_v2.py` references it (in a docstring; deferred to D16). Pre-flight's "no" finding confirmed.
- **Severity:** N/A. Infrastructure ready; D-A locks D16 to no new agents, so this stays dormant. Future agents can adopt it without scaffold work.

### l — Celery infrastructure deployment readiness — **HIGH (launch blocker)** 🔴

- **Tested:** docker-compose services; Fly app state; celery-safety-memory-bump.md remediation status.
- **How:** Read `docker-compose.yml`, `fly.toml`, `docs/followups/celery-safety-memory-bump.md`, `backend/app/core/celery_app.py:156-182`.
- **Findings:**
  - **Item (a) memory bump to 4096 MB:** PARTIAL. `fly.toml:126` has `memory_mb = 4096` for the main API app. **Separate `pae-platform-worker.toml` and `pae-platform-beat.toml` do not exist** (per fly.toml:131-133 comment).
  - **Item (b) concurrency cap to 2:** UNRESOLVED. `docker-compose.yml:62` shows `--concurrency=4`, exceeding the safe value of 2 documented in celery-safety-memory-bump.md table (4×750MB ≈ 3GB resident, risky at 4096 MB).
  - **Item (c) Presidio eager-load:** ✅ DONE. `celery_app.py:156-182` implements `@worker_process_init.connect` handler that calls `get_default_gate()` (lines 169-171). Fail-soft if Presidio missing.
- **Severity:** **HIGH** — confirmed launch blocker per `celery-safety-memory-bump.md:3`. Production deployment of any scheduled retention work without this remediation will OOM workers at first scheduled run.
- **Minimum-fix proposal:** Author `pae-platform-worker.toml` and `pae-platform-beat.toml` with `memory_mb=4096`. Set `--concurrency=2` (override docker-compose default in fly.toml release commands). Run a smoke deploy and verify boot time + resident memory match D9 Checkpoint 1 numbers (~4.28s boot, ~1.4 GB resident).

### m — Email deliverability (SendGrid config) — **PARTIAL** (doc gap, not code defect)

- **Tested:** Config keys; SendGrid SDK integration; mock/dry-run mode; error handling.
- **How:** Read `backend/app/core/config.py:93-120`, `backend/app/services/outreach_email_service.py:1-305`.
- **Findings:**
  - Config: `sendgrid_api_key` defaults to empty string (config.py:93); `sendgrid_from_email` defaults `noreply@pae.dev` (line 120). Override paths via env: `OUTREACH_FROM_EMAIL`, `OUTREACH_FROM_NAME`, `OUTREACH_REPLY_TO`.
  - **No-op safe path:** when API key unset, sends write `status='mocked'` (lines 207-221). Dev parity with prod.
  - **Audit-before-network:** outreach_log row written `status='pending'` BEFORE SendGrid call (lines 194-204), then flipped after (230-255). Bounce-safe.
  - **Soft-fail:** SDK exceptions caught at line 246, returned as `status='failed'` with error text (246-261). PII filter: body_preview truncated to 200 chars (193).
- **Gaps (operational, not code):**
  - **No `.env.example` in repo** — operators have no documented list of required secrets.
  - **No bounce/complaint webhook route** (mark_delivered/mark_opened helpers exist in outreach_service.py:133-167, but no route registered for SendGrid Event Webhook).
  - **Default REPLY_TO points to personal email** (`bhaskar@pae-platform.dev`) — should be a monitored alias.
- **Severity:** **LOW-to-MEDIUM**. Code is correct; ops/documentation gaps. SPF/DKIM/DMARC verification is a deploy-time activity, not a code-side defect.
- **Minimum-fix proposal:** Create `.env.example` with documented keys (CP2). Webhook route can be post-launch. Reply-to address: founder decision.

### n — Admin workflow validation (drift → outreach) — **WORKFLOW ASSESSMENT**

The cockpit + per-student panel adequately support the admin's
"observe drift, reach out" workflow **for asynchronous in-app
outreach**. The friction is at the WhatsApp synchronous surface:

**What works today:**

- 5 slip-pattern panels make at-risk cohorts impossible to miss.
- Click into student → 5-card panel with full context (notes, timeline, DM thread, refund history, agent triggers).
- In-app DM (Card 4) lets admin send a message; reply tracked via outreach_log.replied_at.
- Admin notes (Card 3) let admin record "called via WhatsApp Mon 10am" as freeform text.
- "Schedule call" button generates a mailto with prefilled subject + risk_reason.

**What's missing for the founder's reframe ("reach out manually via WhatsApp"):**

1. No `whatsapp_number` / `phone_number` column on User. Signup schema doesn't collect it.
2. No `wa.me/{number}` deep-link button anywhere in the cockpit.
3. No "Log this WhatsApp contact" button (admin notes are the current substitute, but unattributed to channel).
4. No timeline filtering by outreach_log channel (so admin can't quickly see "last contacted via WhatsApp 5d ago, ghosted").

**Verdict:** The audit's Bucket-C agent recommends DEFER-CP3 because
the missing surface is not blocking work today (admin can use DM +
notes). However, the same agent estimates the gap-closing CP3 scope
at **~2 hours engineering** (User schema migration + UserCreate
schema + StudentDetailPanel header rendering + wa.me link button +
optional log-contact button writing outreach_log channel='whatsapp').

This contradicts a binary defer/ship verdict. Reframed: **CP3 is
cheap-to-ship, and the founder reframe explicitly assumes it.** If
the platform is not pre-launch-bottlenecked elsewhere, ship it. If
the team is racing to launch and the founder confirms in-app DM
suffices for v1, defer.

**Decision required from founder.** Default recommendation: ship CP3
because the prompt's locked decision D-B (outreach_log canonical for
admin contact records) only pays off once a non-email/non-in_app
channel actually exists. Without WhatsApp UI, channel='whatsapp' is
schema-future-proofing without consumers.

---

## CP2 scope synthesis

Ordered by severity. CP2 closes **HIGH** items unconditionally; **MEDIUM** items if scope allows; **LOW** items defer to D17b/post-launch.

### HIGH — must close before launch

**CP2.l — Celery worker + beat Fly app deployment** _(pre-known launch blocker)_

- Author `fly.toml` for `pae-platform-worker` (memory_mb=4096, concurrency=2 via release command).
- Author `fly.toml` for `pae-platform-beat` (memory_mb=4096, single-process beat).
- Verify boot + resident memory in smoke deploy.
- Update `docs/followups/celery-safety-memory-bump.md` items (a) and (b) to RESOLVED.
- Pre-launch smoke (manual, post-deploy): trigger risk_scoring + outreach_automation in production, verify execution + DB writes.

### MEDIUM — pre-launch fix if scope allows; defer otherwise

**CP2.h — `inactivity_sweep` docstring/behavior alignment**

- Cheapest fix: update task docstring to clarify that the cron is observational-only; re-engagement is admin-triggered.
- Real fix (post-launch): wire event persistence so disrupt_prevention can query recent flagged events at chat-surface entry.

**CP2.i — `weekly_letters` outreach_log audit gap**

- Add `outreach_service.record(channel='email', template_key='weekly_letter', triggered_by='system_weekly_letters', status='sent')` after successful SendGrid send (line 156 of weekly_letters.py).

**CP2.d — `admin_console_*` cluster cleanup** _(downgraded from D-A's HIGH expectation)_

- The cluster is **safely scaffolded-but-inert**. Not Path A (build writers) and not really Path B (migrate cockpit) — the cockpit is already migrated.
- Pre-launch CP2.d: verify LD-1..LD-5 actually return correct data on dev DB by hitting `/api/v1/admin/console/v1` and spot-checking against primary tables.
- Post-launch CP2.d: ship a drop migration for admin_console_* tables once the migrated cockpit code has soaked in production. Per the in-code comment, this is the next-deploy follow-up.

**CP2.m — `.env.example` documentation**

- Author `.env.example` documenting SENDGRID_API_KEY, OUTREACH_FROM_EMAIL, OUTREACH_FROM_NAME, OUTREACH_REPLY_TO, ENVIRONMENT, OUTREACH_AUTO_SEND, plus the rest of the Settings surface. Trivial; do this in CP2.

### LOW — defer to D17b/post-launch

**CP2.j — `growth_snapshots` admin cohort read endpoint**

- No production-blocking gap. Add `GET /api/v1/admin/growth-snapshots?week_ending=...` post-launch when an admin actually wants the cohort view.

---

## CP3 readiness assessment (per finding 1n)

**Recommendation: SHIP CP3** — but flag the decision to the founder.

Rationale:

- **Cheap to ship** (~2 hours engineering per Bucket-C audit).
- **D-B's outreach_log canonicalization** assumes channel='whatsapp' will eventually exist as a real value. Schema-future-proofing without UI is a soft contradiction.
- **The founder reframe explicitly requires it.** "Admin observes at-risk, reaches out manually via WhatsApp" without a phone field reduces to "manually search for student contact" — friction the platform's stated job is to remove.

If the founder confirms in-app DM + admin notes suffices for v1
launch volume (low cohort, admin already has student contacts in a
spreadsheet), **defer CP3** and register
`d16-followup-whatsapp-deeplinks.md`. Either decision is defensible;
neither blocks launch.

CP3 scope (if shipped):

- **CP3.1** — User schema extension: migration adds `whatsapp_number` (nullable text) to `users`. Update `UserCreate` schema. Optional collection in onboarding.
- **CP3.2** — Admin WhatsApp deep-link UI: render `wa.me/{number}` button on student-detail-panel when `whatsapp_number` present. "Log this contact" button writes outreach_log(channel='whatsapp', triggered_by='admin_manual', body_preview=`<typed>`).
- **CP3.3** — outreach_log channel surfacing: timeline shows WhatsApp + phone alongside email + in_app. Channel badges on outreach feed.
- **CP3.E2E** — Admin retention smoke: walk the full drift→outreach scenario, verify outreach_log shows the new channel, verify next risk_scoring run respects throttle.

---

## Stop-condition status

| Stop condition | Triggered? |
|---|---|
| > 6 HIGH-severity gaps | **No** (1 HIGH: l) |
| `admin_console_*` reveals broken populate path | **No** (no path exists; cockpit pre-migrated; safe) |
| Bug 24-class architectural finding | **No** (closest candidate, admin_console_*, has documented resolution path) |
| Admin doesn't actually use cockpit (1n) | **No** (cockpit is the canonical surface; gap is WhatsApp-specific) |
| Cumulative cost > ₹2.00 | **No** (CP1 was code reading; ₹0 LLM cost on the audit itself) |

CP1 proceeds to CP2 cleanly.

---

## Patterns surfaced

- **Pattern 28 candidate** (functional audit before gap-closure): D16 reframe validated. The original D16 plan (interrupt_agent + Email MCP + proactive layer) would have shipped scaffolding atop already-shipped infrastructure. CP1 prevented duplicate build.
- **Pattern 29 candidate** (scaffolded-but-inert detection): `admin_console_*` would have been the canonical case, but the cockpit was already migrated. Pattern is valid; this instance is benign. CI check for "tables with no writer" would have flagged this earlier and could be useful going forward.
- **Pattern 23 (follow-up doc framing drift):** `celery-safety-memory-bump.md` correctly tracks (a)/(b) as pending; this audit confirms its accuracy. Contrast with `inactivity_sweep.py` docstring (item h), which drifted from current behavior — the same discipline should apply to task docstrings.

---

## Cumulative cost

CP1: ~₹0.00 (sub-agents performed read-only code inspection; no
production LLM calls were made by the audit itself).

D16 cumulative: ~₹0.00 of ₹3.00 ceiling. Comfortable margin for CP2
engineering + CP3 (if shipped) + closure smoke.
