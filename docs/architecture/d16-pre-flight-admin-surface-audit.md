# D16 Pre-Flight — Admin Retention Surface Audit

**Status:** Read-only investigative audit. No code changes; descriptive only.
**Created:** 2026-05-08 (post-D15 closure at 27125fa).
**Purpose:** Surface what admin-facing infrastructure exists today so D16
prompt design can be grounded in reality, not assumptions.
**D16 reframe (founder):** admin observes at-risk students; admin reaches
out manually via WhatsApp/personal contact; the platform's job is to
make admin observation efficient.

---

## Executive summary

The admin surface is **substantially built out** — more than the audit
prompt anticipated. Two large pieces already exist that D16 will primarily
extend rather than introduce:

1. **F4 admin Cockpit** at `/admin` — a single operator surface with
   retention panels (5 slip-pattern cards: paid_silent, capstone_stalled,
   streak_broken, promotion_avoidant, cold_signup), live KPI strip,
   funnel chart, action band of top-3 at-risk students, a sortable
   roster with risk-tier filters, and a per-student detail panel with
   5 cards (agent trigger, refund offer, notes, DM, timeline).
2. **F1/F3/F5/F9 retention engine on the backend** — `student_risk_signals`
   table (nightly slip-pattern + risk_score), `outreach_log` table
   (channel-agnostic audit), `outreach_email_service` (SendGrid
   templates), `outreach_automation` Celery beat task (daily 09:00 UTC,
   dry-run by default).

The gaps relative to D16's stated needs cluster into three areas:

- **No phone / WhatsApp contact storage on User** — `users` and
  `user_preferences` carry no phone field. D16's manual-WhatsApp
  outreach needs a place to put the number.
- **Celery beat not deployed to Fly production yet** — separate worker
  + beat Fly apps don't exist; memory-bump remediation items (a) and
  (b) from `celery-safety-memory-bump.md` are still pending.
- **AdminConsole\* table cluster exists but populate source is unclear** —
  the 8 tables shipped at migration 0039 (2026-04-25) but the writers
  are not findable in `backend/app/services/`. May be stale, may be
  fed by a job outside the codebase.

D16 design implications are at the bottom of this report.

---

## 1. Admin frontend pages

Frontend stack confirmed: Next.js 15 App Router, Tailwind 4 + shadcn/ui,
React Query for server state, Zustand for auth/theme.

### 1.1 Active admin routes

All routes live under `frontend/src/app/admin/`. Layout-level guard
(`useAuthStore`): unauthenticated → `/login?next=%2Fadmin`; authenticated
non-admin → `/today`; zombie auth (token-but-no-user, DISC-52) →
single `refreshMe()` retry before redirect.

| Route | File | Purpose |
|---|---|---|
| `/admin` | `frontend/src/app/admin/page.tsx` | **Cockpit (canonical overview).** Retention panels (5 slip-pattern cards), action band (top-3 at-risk + call list), platform pulse (24h/7d/30d KPIs), learner funnel, feature usage tiles, sortable/filterable student roster. Queries `/api/v1/admin/console/v1?window=...`. |
| `/admin/students` | `frontend/src/app/admin/students/page.tsx` | **Student catalog.** Searchable (server-side debounced), sortable (joined / name / last_seen). URL filter `?slip_type=...` deep-links from cockpit panels. Queries `/api/v1/admin/students`. |
| `/admin/students/[id]` | `frontend/src/app/admin/students/[id]/page.tsx` | **Student detail drilldown.** Renders `<StudentDetailPanel>` with all 5 operator cards. Direct-link / bookmark version of the cockpit drawer. |
| `/admin/content` | `frontend/src/app/admin/content/page.tsx` | **Content quality dashboard.** Two tabs: Confusion heatmap (7d/30d/90d) and per-lesson Performance. Queries `/api/v1/admin/confusion-heatmap`, `/api/v1/admin/content-performance`. |
| `/admin/feedback` | `frontend/src/app/admin/feedback/page.tsx` | **Feedback triage.** In-app feedback submissions with sentiment + route + timestamp. "Mark resolved" mutation. Queries `/api/v1/feedback/admin`. |
| `/admin/agents` | `frontend/src/app/admin/agents/page.tsx` | **Agent monitor grid.** Per-agent stats (total actions, errors, avg duration, success rate, last call) with healthy/degraded badges. 30s auto-refresh. Queries `/api/v1/admin/agents/health`. |
| `/admin/audit-log` | `frontend/src/app/admin/audit-log/page.tsx` | **Agent action feed.** Latest 100 `agent_actions` rows with student / agent / action / status / duration / timestamp. Queries `/api/v1/admin/audit-log?limit=100`. |
| `/admin/courses` | `frontend/src/app/admin/courses/page.tsx` | Course catalog list (title, slug, difficulty, price, lesson_count, publish state). Click to drilldown. Uses `useCourses` hook. |
| `/admin/courses/[id]/edit` | `frontend/src/app/admin/courses/[id]/edit/page.tsx` | Course editor (JSON textarea for metadata + rubric). POSTs `/api/v1/admin/courses/{id}/metadata` + rubric endpoints. |

### 1.2 Deprecated routes (still in tree, redirect-only)

| Route | Redirects to | Why |
|---|---|---|
| `/admin/at-risk` | `/admin` | Old multi-signal at-risk view; replaced by retention engine panels on cockpit. |
| `/admin/pulse` | `/admin` | Pulse strip is now canonical on cockpit. |
| `/admin/confusion` | `/admin/content` | Merged into content dashboard. |
| `/admin/content-performance` | `/admin/content` | Merged into content dashboard. |

D16 should not introduce new deprecated paths; the convention is
to keep redirect stubs so external links don't 404.

### 1.3 Admin component layer

Reusable admin patterns at `frontend/src/app/admin/_components/`:

- `admin-topbar.tsx` — shared header (brand + page switcher + search +
  theme toggle + avatar menu) across all admin routes.
- `admin-page-switcher.tsx` — dropdown nav pill (Operate / System
  groups).
- `student-detail-panel.tsx` — canonical 5-card student surface
  (agent trigger, refund offer, notes, DM, timeline). The
  per-student-detail page renders this; the cockpit's drawer wraps
  it via `student-detail-modal.tsx`.
- `student-detail-modal.tsx` — side-drawer wrapper used in cockpit
  triage flow.
- `retention-panels.tsx` — F4 slip-pattern card grid.
- shadcn primitives in routine use: `Card`, `Badge`, `Select`,
  `Button`, `Textarea`, `Dialog`, `Popover`, `Tooltip`, `Input`,
  `Combobox`, `Command-palette`.

Typical admin page shape:

1. `useQuery(...)` via React Query hook (e.g. `useAdminStudents`,
   `useRiskPanels`).
2. Conditional render skeleton → error → data.
3. Filter / sort UI + table or card grid.
4. Click handler opens `StudentDetailModal` (drawer) or navigates to
   `/admin/students/[id]`.
5. Mutations via `useMutation` (e.g. `useSendAdminMessage`,
   `useTriggerAgent`).

API access goes through `frontend/src/lib/api-client` (`api.get<T>`,
`api.post<T>`); error toasting is automatic with a `skipErrorToast`
meta opt-out.

### 1.4 Operator interaction surface today

The cockpit + per-student panel already supports:

- **Trigger an agent** (re_engagement / weekly_report / learning_path /
  celebrate) on a specific student.
- **Send a refund offer** (conditional on `paid_silent` slip): textarea
  for reason + send button + history.
- **Append a private admin note** on a student (timestamped, append-only).
- **Send a direct in-app message** (visible in student inbox; replies
  show as a thread).
- **View activity timeline** (login / lesson_completed / submission /
  agent_action with `kind` + `summary` + `detail JSON`).
- **Schedule call (mailto)** — `buildCallInviteMailto()` generates
  prefilled-subject mailto links with student name + risk reason +
  date suggestions.

What is **not** currently in the operator surface (gaps relative to
D16 reframe):

- No WhatsApp launch button (no `wa.me/...` links).
- No phone-number display anywhere — `User` doesn't carry a phone
  field (see §5.1).
- No "I just contacted X via WhatsApp" record-outreach button. Today
  the closest equivalents are the admin-notes textarea (free-form)
  and the in-app DM (writes `outreach_log` server-side as
  `channel='in_app'`).

---

## 2. Admin backend APIs

Two router files; both registered in `backend/app/main.py` under
prefix `/api/v1/admin`:

- `backend/app/api/v1/routes/admin.py` (~2200 lines, 27 endpoints)
- `backend/app/api/v1/routes/admin_journey.py` (~370 lines, 2 endpoints)

Plus one admin-only endpoint group outside the prefix:

- `backend/app/api/v1/routes/feedback.py` — `/api/v1/feedback/admin`
  (list + resolve), guarded by an in-file copy of `_require_admin`.

Every admin endpoint uses the same `Depends(_require_admin)` guard
that asserts `current_user.role == "admin"` and raises `HTTPException
403 "Admin only"` otherwise.

### 2.1 Student management

| Method + path | Function | Backing |
|---|---|---|
| `GET /api/v1/admin/stats` | `get_stats` | users, enrollments, exercise_submissions, agent_actions, payments |
| `GET /api/v1/admin/students` | `list_students` | users, student_progress, student_risk_signals (with `?q=` search, `?sort=` joined/name/last_seen, `?slip_type=` filter) |
| `GET /api/v1/admin/students/{student_id}/journey` | `student_journey` (admin_journey.py) | agent_actions, agent_call_chain, agent_memory, agent_escalations, safety_incidents (raw SQL) |
| `GET /api/v1/admin/students/{student_id}/timeline` | `get_student_timeline` | per-event timeline assembly |

### 2.2 Risk + engagement

| Method + path | Function | Backing |
|---|---|---|
| `GET /api/v1/admin/at-risk-students` | `get_at_risk_students` | `?min_score=0.35` filter |
| `GET /api/v1/admin/risk-panels` | `get_risk_panels` | F4 slip-pattern cohorts + sparklines |
| `GET /api/v1/admin/confusion-heatmap` | `get_confusion_heatmap` | content performance |
| `GET /api/v1/admin/content-performance` | `get_content_performance` | per-lesson confusion + question counts |
| `GET /api/v1/admin/pulse` | `get_pulse` | live platform KPIs (active learners, sessions, revenue, feature usage) |
| `GET /api/v1/admin/console/v1?window=` | `get_admin_console` | comprehensive console snapshot (LD-1…LD-5: students, pulse, funnel, features, calls, events, revenue) — **the single endpoint that powers `/admin` cockpit** |

### 2.3 Student interaction (admin → student)

| Method + path | Function | Behavior |
|---|---|---|
| `POST /api/v1/admin/students/{id}/notes` | `create_student_note` | Append admin note (StudentNoteService → `student_notes`) |
| `GET /api/v1/admin/students/{id}/notes` | `list_student_notes` | List admin notes |
| `POST /api/v1/admin/students/{id}/refund-offer` | `create_and_send_refund_offer` | Refund offer flow (RefundOfferService → email via outreach_email_service → `outreach_log` row) |
| `GET /api/v1/admin/students/{id}/refund-offers` | `list_student_refund_offers` | List refund offers per student |
| `POST /api/v1/admin/trigger-agent` | `trigger_agent` (DISC-57) | Admin-triggered agent invocation; logged to `agent_actions` with `actor_id` + `actor_role='admin'` + `on_behalf_of=student_id` |
| `POST /api/v1/admin/messages/{student_id}/send` | `admin_send_message` | Direct admin → student message (StudentMessageService → `student_messages` + `outreach_log` row with `channel='in_app'`, `triggered_by='admin_manual'`) |
| `GET /api/v1/admin/messages/{student_id}` | `admin_list_messages` | List admin↔student thread |

### 2.4 Audit + content

| Method + path | Function | Backing |
|---|---|---|
| `GET /api/v1/admin/audit-log?limit=` | `get_audit_log` | `agent_actions` with actor attribution (DISC-57 fields: actor_id, actor_role, on_behalf_of) |
| `GET /api/v1/admin/agents/health` | `get_agents_health` | per-agent rollup |
| `GET /api/v1/admin/agents/{agent_name}/recent-decisions` | `agent_recent_decisions` | `agent_call_chain` raw SQL |
| `PATCH /api/v1/admin/courses/{id}` | `update_course` | course title + description |
| `PATCH /api/v1/admin/exercises/{id}/rubric` | `update_exercise_rubric` | rubric + test cases |
| `GET /api/v1/admin/chat-feedback` | `get_chat_feedback_rollup` | `chat_message` + `feedback` aggregation |

---

## 3. Admin authentication + authorization

### 3.1 Admin-status determination

**Single source of truth:** `users.role` column (`String(50)`, default
`"student"`, NOT NULL). Defined at
`backend/app/models/user.py:16`.

- No separate `admin_users` table.
- No JWT role claim; the token only carries `sub=user_id`. Role is
  resolved per-request from the live DB row.
- Canonical admin string is `"admin"` (lowercase, case-sensitive). No
  enum, no role table; admin-vs-non-admin checks compare the column
  literally.
- Other observed `role` values include `"student"` (default).
  `users.promoted_to_role` is a separate, free-text field carrying
  legacy student-role progression strings (e.g., `"Senior ML Engineer"`)
  — see `d15-followup-legacy-promoted-role-reconciliation.md`. It is
  **unrelated** to the `role` column and should not be conflated with
  admin status.

### 3.2 JWT minting + auth flow

- Token issuance at `backend/app/core/security.py:20-26` —
  `create_access_token(data: dict, expires_delta) -> str` encodes
  `{"sub": user_id, "exp": ...}`. No role claim injected.
- Refresh tokens are httpOnly cookies; access tokens are bearer.
- No admin-specific login endpoint. Admin accounts are regular users
  whose `role='admin'` is set directly in the DB.
- Per-request: `get_current_user` decodes JWT → fetches `User` from
  DB by `sub`. The fresh DB read means a role flip takes effect on
  the next request, no token re-issue needed.

### 3.3 Admin guard implementation

Canonical at `backend/app/api/v1/routes/admin.py:87-90`:

```python
def _require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return current_user
```

In-file copies live at `admin_journey.py:37-52` (uses
`getattr(current_user, "role", None)` for safety) and `feedback.py:20-23`.
All three are identical in semantics; consolidating into a shared
dependency would be a hygiene cleanup but is not D16 scope.

### 3.4 Admin role tiers

**Single tier only** — `"admin"`. No super-admin / support / HR /
read-only-admin distinction. Every admin endpoint uses the same gate.
If D16 needs a more granular role (e.g. "support agent who can
contact but not refund"), that's a new capability.

---

## 4. Existing student observability surfaces

### 4.1 The retention engine — F1 + F4 (already shipped)

The platform already has a purpose-built retention engine. D16 will
extend it, not introduce it.

#### `student_risk_signals` (one row per active user)

Defined at `backend/app/models/student_risk_signals.py`. Migration
`0049_student_risk_signals`.

Columns:

- `user_id` (FK, unique, indexed)
- `risk_score` (0–100; 0=healthy, 100=will-churn)
- `slip_type` — enum-as-text: `none`, `cold_signup`,
  `unpaid_stalled`, `streak_broken`, `paid_silent`,
  `capstone_stalled`, `promotion_avoidant`
- `days_since_last_session` (nullable int)
- `max_streak_ever` (int)
- `paid` (bool, denormalized for fast filter)
- `recommended_intervention` (template_key for F5 outreach)
- `risk_reason` (human-readable text for admin UI; e.g.
  `"Paid 8d ago, silent 12d"`)
- `computed_at` (timestamp)
- Composite index on `(slip_type, risk_score DESC)` for fast panel
  queries.

Populated by `student_risk_service.classify()` running nightly via
the `risk_scoring.score_all_users` Celery task at 03:00 UTC.

Read by:

- F4 admin console (`/admin/risk-panels`, `/admin/students?slip_type=...`).
- F5 outreach service (reads `recommended_intervention`).
- F9 nightly automation (skips recently-contacted users).

D16 implication: every retention signal D16 needs is already in
`student_risk_signals`, freshly computed nightly.

#### Adjacent observability tables (live, populated)

| Model | Use |
|---|---|
| `StudentProgress` | per-(student, lesson) progress row; fed by lesson-completion events |
| `LearningSession` | per-(user, ordinal) session; warmup_done_at / lesson_done_at / reflect_done_at step timestamps |
| `Reflection` | one per user per day; mood string (`stuck/overwhelmed/frustrated/exhausted` etc.) — `at_risk_student_service` already counts low-mood streaks |
| `ConfidenceReport` | self-reported 1–5 confidence per skill; `asked_at`/`answered_at` measure engagement rate |
| `AgentAction` | granular per-agent-invocation audit (with DISC-57 actor fields for admin attribution) |
| `AgentInvocationLog` | unified per-LLM-call cost log (sub-agent granularity, post-migration 0040) |
| `CohortEvent` | append-only public milestones (level-up, capstone-shipped, streak-started) — 5-most-recent rendered on Today |
| `GrowthSnapshot` | weekly per-user frozen rollup (lessons / skills / streak / top concept); populated Sunday midnight |
| `StudentMisconception` | factual-error log from tutor disagreements (capture is live; reads are dormant pending curriculum-graph wiring) |

### 4.2 The `AdminConsole*` cluster — shipped, populate source unclear

Migration `0039_admin_console_v1` (2026-04-25) created 8 tables under
the `admin_console_*` prefix, all imported in
`backend/app/models/__init__.py`:

- `AdminConsoleProfile` — per-student denormalized snapshot
  (track, stage, progress_pct, streak_days, last_seen_days,
  risk_score, paid, joined_label, city). Indexed on `risk_score DESC`.
- `AdminConsoleEngagement` — per-student 14-day rollup
  (sessions_14d, flashcards_14d, agent_questions_14d, reviews_14d,
  notes_14d, labs_14d, capstones_14d, purchases_total).
- `AdminConsoleFunnelSnapshot` — daily cohort-funnel counts
  (signups → onboarded → first_lesson → paid → capstone → promoted →
  hired). Unique on `snapshot_date`.
- `AdminConsolePulseMetric` — KPI tiles (metric_key, label,
  display_value, unit, delta_pct, delta_text, color_hex,
  invert_delta, spark JSON, sort_order).
- `AdminConsoleFeatureUsage` — feature adoption tiles (feature_key,
  count_label, sub_label, is_cold flag, bars JSON).
- `AdminConsoleEvent` — live event feed (kind: signup, capstone,
  promo, purchase, review; body_html, occurred_at).
- `AdminConsoleCall` — scheduled admin↔student calls (admin manual
  entry implied by `reason` field).
- `AdminConsoleRiskReason` — top-card risk narrative per student
  (likely mirrors `student_risk_signals.risk_reason`).

**Populate source not findable in `backend/app/services/`.** No
service module under `services/` writes to any `admin_console_*`
table. The cockpit's `/api/v1/admin/console/v1` endpoint reads them
(per `get_admin_console`, line 2016), so they are consumed — but it
is unclear whether they are kept fresh by:

- A Celery task not yet visible in the audit (none of the 7 currently
  scheduled tasks targets `admin_console_*`).
- A populate path that lives outside `backend/app/services/` (e.g.
  triggers, scheduled SQL on the DB, an external job).
- A populate path that was scaffolded but never shipped.

D16 implication: **investigate the freshness of `admin_console_*`
data on dev DB before relying on these tables**. If they are stale,
either populate them as part of D16 or read directly from the
underlying primary tables (`users`, `agent_actions`, `payments`,
`student_risk_signals`, etc.) the way `risk_panels` already does.

### 4.3 Pass-3 era tools: shipped vs stubbed vs absent

| Surface | State | Detail |
|---|---|---|
| `readiness_orchestrator` | **Shipped + consumed** | `backend/app/services/readiness_orchestrator.py` manages `ReadinessDiagnosticSession` lifecycle; soft turn cap + ₹15 cost cap per session. **Student-initiated, not admin-gated.** |
| `readiness_sub_agents` | **Shipped + consumed by orchestrator** | `backend/app/agents/readiness_sub_agents.py` — `JDAnalyst`, `MatchScorer`, `DiagnosticInterviewer`, `VerdictGenerator`. No standalone endpoint; only invoked from the orchestrator. |
| `growth_snapshot_service` | **Shipped + populated, no admin read endpoint** | Sunday-midnight Celery beat job populates `growth_snapshots`. No `/api/v1/admin/growth-snapshots` route exists. The data is there; no admin UI exposes it. |
| `today_summary_service` | **Shipped + consumed by student `/api/v1/today/summary`** | Cross-cutting student-side aggregator. **No admin equivalent** (`/admin/today` does not exist). |
| `at_risk_student_service` | **Shipped + consumed** | Reads `Reflection` mood + `student_risk_signals`; backs `/api/v1/admin/at-risk-students` and `/risk-panels`. |
| `disrupt_prevention` agent (proactive scheduled trigger) | **Absent** | The agent class exists at `backend/app/agents/disrupt_prevention.py` but has no `@proactive(cron=...)` decorator. It runs on the chat surface only, triggered by `re_engagement.flagged` log events from `inactivity_sweep`. |

D16 implication: a "growth snapshot per student" view in admin would
be net-new but the data is already populated weekly. Today's-summary
parity for admin would be a service-extension job, not a new system.

---

## 5. Existing communication + contact tracking

### 5.1 Phone / WhatsApp contact storage — **absent**

`backend/app/models/user.py`: the User model carries `email`,
`hashed_password`, `full_name`, `role`, `is_active`, `is_verified`,
`github_username`, `avatar_url`, `stripe_customer_id`,
`last_login_at`, `promoted_at`, `promoted_to_role`. **No
`phone`, `phone_number`, `whatsapp`, or `country_code` column.**

`backend/app/models/user_preferences.py`: tutor / UI settings only
(`tutor_mode`, `socratic_level`, `ugly_draft_mode`). **No contact
preference fields.**

No other model carries student phone/WhatsApp data. The signup
schema at `backend/app/schemas/user.py` (`UserCreate`) doesn't
collect a phone number either.

D16 implication: D16's manual-WhatsApp outreach reframe assumes a
WhatsApp number per student, but **the platform has no place to
store one today**. Either (a) D16 adds a `whatsapp_number` /
`phone_number` field to `User` or `UserPreferences`, or (b) the
admin is expected to source contact info externally and the
platform's job is purely observation + record-of-outreach.

### 5.2 `outreach_log` — channel-agnostic universal audit (live, F3)

Defined at `backend/app/models/outreach_log.py`. Migration
`0051_outreach_log`.

Columns:

- `id`, `user_id` (FK, indexed)
- `channel` — `email`, `whatsapp`, `sms`, `in_app`, `phone`
  (string, NOT NULL)
- `template_key` (nullable; NULL for admin one-off messages)
- `slip_type` (nullable; denormalized from `student_risk_signals`
  for analytics)
- `triggered_by` — `system_nightly` | `admin_manual`
- `triggered_by_user_id` (nullable FK → users.id; the admin who
  triggered it)
- `sent_at` (server_default now())
- `delivered_at`, `opened_at`, `replied_at` (nullable; reply tracking
  signals customer engagement)
- `body_preview` (first 200 chars; full body NOT stored to avoid PII
  bloat)
- `external_id` (SendGrid msg-id, Twilio sid, etc.; for webhook
  matching)
- `status` — `pending` | `would_send` (dry-run) | `sent` |
  `delivered` | `bounced` | `failed` | `mocked`
- `error` (nullable text; populated on failure)

**Currently populated channels: `email` and `in_app`.** WhatsApp,
SMS, and phone are schema-future-proofed but not implemented.

Writers:

- `outreach_email_service` (F5 templated emails) — sends via SendGrid
  + records.
- `student_message_service` (F8 admin↔student in-app DMs) — writes
  the StudentMessage row + an `outreach_log` row with
  `channel='in_app'`, `triggered_by='admin_manual'`,
  `triggered_by_user_id=<admin>`. Student replies flip the most-recent
  admin row's `replied_at`.
- `refund_offer_service` (F11) — fires a templated email via
  `outreach_email_service`, links `outreach_log_id` back on the
  `RefundOffer` row.
- `outreach_automation` Celery task (F9, daily 09:00 UTC) — dry-run
  by default (writes `status='would_send'`); real sends only on
  production with `OUTREACH_AUTO_SEND=1` envvar.

Readers:

- F3 `outreach_service.was_sent_recently()` — throttling (per
  `(user_id, template_key)`, default 7-day window).
- F4 admin console — per-student outreach feed in detail panel.
- F9 nightly automation — skip recently-contacted users.

D16 implication: a "log that I just contacted this student via
WhatsApp" admin button would write `outreach_log` with
`channel='whatsapp'`, `triggered_by='admin_manual'`, `external_id`
optionally null (admin used phone, not platform-driven send), and
`body_preview` from the admin's typed-into-admin-UI summary. **The
schema fully supports this; only the UI button + backend route need
to be added.**

### 5.3 StudentMessage / StudentNote / RefundOffer (live admin↔student
records)

| Model | File | Behavior |
|---|---|---|
| `StudentMessage` | `student_message.py` | Two-party in-app threads (admin ↔ student); `thread_id` groups; `sender_role` ∈ {admin, student}; soft-delete via `deleted_at`. Service: `student_message_service.create_message()`. Mirrors `outreach_log` row on every send. |
| `StudentNote` | `student_note.py` | F10 admin-authored intervention note on a student. Append-only. `admin_id`, `student_id`, `body_md`. Service: `student_note_service.add_note()`. Wired to `/admin/students/{id}/notes`. **Enforces append-only**. |
| `RefundOffer` | `refund_offer.py` | F11 — Slip-4 (paid_silent day-14) proactive refund offer flow. `proposed_by`, `status` (proposed → sent → accepted/declined/expired), `outreach_log_id` link. Service: `refund_offer_service`. |
| `Notification` | `notification.py` | Generic per-user notification (title/body/type). Not D16-specific; populated by system + agents. |

D16 implication: `StudentNote` already gives admins a place to record
"I called this student, they said X" — except it's not channel-
attributed. D16 may want to extend either `StudentNote` (with a
`channel` field) or `outreach_log` (with admin-manual entries
unattached to a template) to capture admin's WhatsApp / phone-call
records distinctly from email/in-app sends.

---

## 6. Pass-3 era student-state visibility tools

Already covered in §4.3. Summary:

| Surface | Live? | Admin-gated? | Populated? |
|---|---|---|---|
| `readiness_orchestrator` | ✓ | No (student-facing) | On-demand per session |
| `readiness_sub_agents` | ✓ | No (called from orchestrator) | On-demand |
| `growth_snapshot_service` | ✓ | **No admin endpoint** | Weekly Sunday midnight |
| `today_summary_service` | ✓ | **No admin variant** | Per request from student `/today/summary` |
| `at_risk_student_service` | ✓ | Yes (`/admin/at-risk-students`, `/admin/risk-panels`) | Reads `student_risk_signals` + `Reflection` mood |
| `disrupt_prevention` agent | ✓ class | No proactive trigger | Chat-surface only |
| `AdminConsole*` table cluster | ✓ schema (mig 0039) | Yes (read by `/admin/console/v1`) | **Populate source unclear — investigate** |

---

## 7. Celery infrastructure state

Stack: Celery 5.6.3, Redis as broker + result backend, SendGrid 6.12.5
for email. Celery app definition at `backend/app/core/celery_app.py`
(includes registration block at lines 36–84 plus dynamic schedule
registration at line 136).

### 7.1 Existing Celery tasks (8 total, 7 scheduled)

| Task | File | Schedule | Purpose |
|---|---|---|---|
| `growth_snapshots.build_weekly_snapshots` | `tasks/growth_snapshots.py` | Sun 00:00 UTC | Weekly per-user growth snapshot (lessons + skills + streak + top concept) |
| `weekly_letters.send_weekly_letters` | `tasks/weekly_letters.py` | Sun 01:00 UTC | `progress_report` agent → notification + SendGrid email |
| `weekly_review.assemble_weekly_reviews` | `tasks/weekly_review.py` | Sun 02:00 UTC | Pre-build SRS-based weekly review quiz |
| `inactivity_sweep.sweep_inactive_students` | `tasks/inactivity_sweep.py` | Mon 09:00 UTC | Flag inactive (3+ days) students; logs `re_engagement.flagged` events for `disrupt_prevention` chat-surface consumption |
| `risk_scoring.score_all_users_task` | `tasks/risk_scoring.py` | Daily 03:00 UTC | **F1 nightly slip-pattern + risk_score compute** — writes `student_risk_signals` |
| `outreach_automation.run_nightly_outreach_task` | `tasks/outreach_automation.py` | Daily 09:00 UTC | **F9 nightly outreach dispatch** — dry-run default, real sends only on prod + `OUTREACH_AUTO_SEND=1`. Writes `outreach_log`. |
| `refresh_student_daily_cost.refresh_student_daily_cost_task` | `tasks/refresh_student_daily_cost.py` | Every 60s | D9 / Pass 3f §D.1 — `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_student_daily_cost` for cost-ceiling enforcement |
| `proactive_runner.run_proactive_task` (`@shared_task`) | `tasks/proactive_runner.py` | Dynamic — registered via `@proactive(cron=...)` on agents | Generic dispatcher for proactive agent runs (cron-fired or webhook-fired); writes `agent_proactive_runs` audit |

### 7.2 Beat schedule + dynamic registration

Static entries are in `celery_app.py` `beat_schedule`. Dynamic
proactive entries are merged at boot via
`register_proactive_schedules(celery_app)` (line 136), which loads
the `_proactive_schedules` list populated by the
`@proactive(cron=...)` decorator from
`app/agents/primitives/proactive.py`.

**Currently no production agent uses the `@proactive` decorator.**
The infrastructure is scaffolded but `D16 will be the first agent to
use it`. The dynamic schedule list will be empty until then.

### 7.3 Production deployment state

- **FastAPI Fly app**: deployed, `fly.toml` at repo root,
  `memory_mb = 4096`, single shared CPU.
- **Celery worker Fly app**: **does not exist yet**. The
  `celery-worker` service exists in `docker-compose.yml` for local
  dev (concurrency 4); no fly.toml. Comment in `fly.toml:130-133`
  notes the worker + beat are intended as separate Fly apps
  (`pae-platform-worker`, `pae-platform-beat`) "in a follow-up
  infra-PR" that hasn't landed.
- **Celery beat Fly app**: **does not exist yet**. The
  `celery-beat` service exists in docker-compose with mitigations
  for the known pidfile + schedule-shelve issues
  (DISC-1, line 74–77 of docker-compose.yml). The "celery-beat
  restart loop" mentioned in MEMORY.md and
  `project_open_bugs_and_gaps.md` is a known launch-blocker for D16.

### 7.4 Worker memory / safety primitive memory bump (in flight)

`docs/followups/celery-safety-memory-bump.md` (created
2026-05-02 at D9 Checkpoint 1) describes the OOM risk: Presidio +
spaCy `en_core_web_lg` ≈ 750 MB resident per process; default Fly
512 MB explodes. Three remediation items:

| # | Item | State |
|---|---|---|
| (a) | Bump worker memory to `memory_mb=4096` on both worker + beat Fly apps | **Pending** — Fly apps don't exist yet. FastAPI side already at 4096. |
| (b) | Cap worker concurrency to 2 (not 4+) — `--concurrency=2` or `CELERYD_CONCURRENCY=2` | **Pending** — docker-compose has `--concurrency=4` for local; Fly side blocked by (a). |
| (c) | Eager-load Presidio at worker boot (signal handler) instead of lazily | **Done** — `celery_app.py:156-182` implements `_eager_load_safety_in_worker()`; fail-soft if Presidio missing. |

D16 implication: **(a) and (b) are launch-blocker for D16 production
rollout.** D16 prompt should either (i) pre-condition on the infra-PR
landing first or (ii) explicitly call out that D16 ships against
local dev + waits for the worker Fly app before the cron actually
fires in prod.

### 7.5 Tables already wired to scheduled retention work

- `student_risk_signals` — written nightly by `risk_scoring`
  (operational since F1 ship).
- `outreach_log` — written by `outreach_automation` (F9 daily; email
  channel only currently).
- `student_inbox` — schema and `dispatch_proactive_run()` audit
  infrastructure ready; **no scheduled writer exists yet**. D16 is
  the candidate first writer.
- `agent_proactive_runs` — schema + dispatch logic ready (idempotency
  key `{agent}:{cron}:{date_bucket}` enforced via partial unique
  index); awaits first @proactive agent.

---

## 8. Frontend admin component patterns

Stack details consolidated from §1 above:

- **Component library**: shadcn/ui (Tailwind 4 + Base UI). Confirmed
  by `package.json`: `@base-ui/react ^1.3.0`, `shadcn ^4.2.0`.
- **Icons**: `lucide-react` (~16 icons per admin page).
- **State**: React Query (`@tanstack/react-query ^5.96.2`) for
  server state; Zustand (`zustand ^5.0.12`) for auth + theme; plain
  `useState` for UI state.
- **API client**: `frontend/src/lib/api-client` wraps `api.get<T>(url)`
  / `api.post<T>(url, body)` with automatic error toasting and
  `skipErrorToast` meta opt-out.
- **Reusable admin building blocks**: `admin-topbar`,
  `admin-page-switcher`, `student-detail-panel` (canonical 5-card
  surface), `student-detail-modal` (drawer wrapper), `retention-panels`
  (slip-pattern card grid), full shadcn primitive set
  (Card / Badge / Select / Button / Textarea / Dialog / Popover /
  Tooltip / Input / Combobox / Command-palette).
- **Styling**: Tailwind utility classes + shadcn variants; one
  CSS module (`console.module.css`) for cockpit-specific tweaks.
- **Page shape**: hook-based `useQuery` → conditional render
  (skeleton/error/data) → filter/sort UI → table or card grid →
  click handler opens modal/drawer → mutation via `useMutation`.

D16 implication: a new admin page should follow this exact pattern.
A "retention triggers" page or a "WhatsApp contact log" page can
reuse `student-detail-panel` for per-student drill-down,
`retention-panels` patterns for cohort cards, and the existing
`api-client` wrapper for all data fetches.

---

## 9. WhatsApp / phone contact infrastructure

Combined frontend + backend findings.

### 9.1 Phone/WhatsApp data — **not collected, not stored**

- `users.phone_number` / `users.whatsapp_number` — **absent**.
- `user_preferences` contact fields — **absent**.
- Signup schema (`UserCreate`) — **no phone field**.
- No frontend display of phone numbers anywhere in admin UI.
- No mailto / wa.me / tel: deep-link buttons.

### 9.2 WhatsApp SDK — **not integrated**

- Backend `pyproject.toml` dependencies: `celery`, `sendgrid`. No
  Twilio, no Meta Cloud API, no gupshup, no other WhatsApp/SMS SDK.
- Grep for `twilio`, `whatsapp`, `wa_`, `gupshup` in backend/app
  returns no source-level imports.
- `outreach_log.channel` schema-supports WhatsApp/SMS/phone but
  no service writes those channel values today.

### 9.3 Templated messaging — **email-only**

- Email templates: Jinja2 templates at `backend/app/templates/email/`
  (weekly letter etc.).
- No centralized template registry model; no WhatsApp template
  primitives.

### 9.4 What this means for D16's reframe

The "admin reaches out manually via WhatsApp" reframe has two
infrastructure-level prerequisites that are **not present today**:

1. A place to store the student's WhatsApp number (`User.whatsapp_number`
   or similar).
2. A way to record "I just messaged X via WhatsApp" — either the
   admin clicks a `wa.me/<number>` deep link from the cockpit and
   writes `outreach_log(channel='whatsapp', triggered_by='admin_manual')`
   from the same UI, or there's a "log outreach" button that records
   the contact retrospectively.

Both are net-new. The `outreach_log` table itself is fully ready for
this; only the field on `User` and the UI button need to land.

---

## 10. D16 design implications

Pure architectural observations, not D16 design.

1. **D16 extends, not introduces, the retention engine.** F1 (nightly
   risk scoring) + F4 (admin cockpit) + F5 (templated email) + F9
   (nightly automation) are already operational. Pinpoint a new
   D16 surface in terms of "what does this add to the cockpit" or
   "what does this make visible that's currently invisible."

2. **The biggest concrete gap is `User.phone_number` /
   `User.whatsapp_number`.** Every other infrastructure piece for
   manual-WhatsApp outreach (audit table, throttling, admin guard)
   is in place. If the founder confirms the reframe, the smallest
   ship-able D16 may be: (a) add `whatsapp_number` to `User`,
   (b) collect it in onboarding, (c) render `wa.me/<number>` deep
   link buttons on the cockpit's per-student panel, (d) wire a
   "log this contact" button that writes
   `outreach_log(channel='whatsapp', triggered_by='admin_manual')`.

3. **The cockpit pattern is canonical.** Any new admin surface should
   follow `student-detail-panel` (5-card per-student) + `admin-topbar`
   + `retention-panels` patterns. shadcn/ui + React Query + Zustand
   are the only frontend tools to use.

4. **Celery beat is scaffolded but not deployed to Fly.** D16's
   prompt should explicitly handle the path: "the trigger evaluator
   ships now, the cron fires once the Fly worker + beat apps land
   (infra-PR remediation items (a) and (b) from
   `celery-safety-memory-bump.md`)." Local dev exercises the path
   today; production firing waits on infra.

5. **The `proactive_runner` + `@proactive(cron=...)` infrastructure is
   ready and unused.** D16's first scheduled-retention agent will
   be the first @proactive in the system. The audit infrastructure
   (`agent_proactive_runs` + idempotency key `{agent}:{cron}:{date_bucket}`)
   is in place; D16 doesn't need to introduce its own.

6. **`admin_console_*` table cluster needs a freshness audit before
   D16 reads from it.** Either confirm a populate path exists outside
   `backend/app/services/`, or read directly from primary tables
   (`users`, `student_risk_signals`, `agent_actions`, `payments`,
   `learning_sessions`) the way `risk_panels` already does. If the
   `admin_console_*` cluster is genuinely stale, D16 might be the
   point where it gets retired in favor of live primary-table reads.

7. **D16's "admin observation" reframe maps cleanly to extending the
   existing observability surface, not building new analytics.**
   Specific extensions that fit the reframe:
   - Per-student timeline filtering by `outreach_log` channel
     (so admin sees "this student was emailed X days ago, then I
     called them Y days ago").
   - Cohort views by `outreach_log.replied_at` (who responded vs
     ghosted).
   - "Time to first admin contact after slip flag" KPI on the pulse
     strip.
   - WhatsApp deep-link buttons on the cockpit drawer.

8. **Single-admin-role today is the right starting assumption.** The
   `users.role == "admin"` check is the entire authorization model.
   If D16 needs a more granular role (e.g. "support agent who can
   contact but not refund"), surface that as a deliberate decision;
   otherwise stay single-tier.

9. **`StudentNote` overlaps with the "admin records that I called
   this student" use case.** A clean D16 design either (a) reuses
   `StudentNote` and adds a `channel` field for attribution, or
   (b) routes admin contact-records through `outreach_log` only and
   uses `StudentNote` for free-form analyst observations. Mixing
   the two is the trap.

10. **No multi-channel notification orchestrator exists today.** If
    D16 wants "send WhatsApp + email, fall back to email if WhatsApp
    bounces," that's net-new infrastructure. If D16 stays in the
    "admin observes + acts manually" reframe, this is moot.

---

## Appendix — file path reference

Backend admin routes:
- `backend/app/api/v1/routes/admin.py`
- `backend/app/api/v1/routes/admin_journey.py`
- `backend/app/api/v1/routes/feedback.py` (admin-only sub-routes)

Backend admin guard:
- `backend/app/api/v1/routes/admin.py:87-90` (canonical `_require_admin`)

Backend retention engine:
- `backend/app/models/student_risk_signals.py` (mig 0049)
- `backend/app/models/outreach_log.py` (mig 0051)
- `backend/app/models/student_message.py`
- `backend/app/models/student_note.py`
- `backend/app/models/refund_offer.py`
- `backend/app/services/student_risk_service.py` (F1)
- `backend/app/services/outreach_email_service.py` (F5)
- `backend/app/services/outreach_service.py` (F3 throttle + record)
- `backend/app/services/student_message_service.py` (F8)
- `backend/app/services/student_note_service.py` (F10)
- `backend/app/services/refund_offer_service.py` (F11)

Backend `AdminConsole*` cluster:
- `backend/app/models/admin_console.py` (mig 0039)
- (no populate-side service module found; investigate)

Backend Celery:
- `backend/app/core/celery_app.py`
- `backend/app/tasks/risk_scoring.py`
- `backend/app/tasks/outreach_automation.py`
- `backend/app/tasks/proactive_runner.py`
- `backend/app/tasks/growth_snapshots.py`
- `backend/app/tasks/inactivity_sweep.py`
- `backend/app/agents/primitives/proactive.py`

Frontend admin:
- `frontend/src/app/admin/page.tsx` (cockpit)
- `frontend/src/app/admin/students/page.tsx`
- `frontend/src/app/admin/students/[id]/page.tsx`
- `frontend/src/app/admin/_components/admin-topbar.tsx`
- `frontend/src/app/admin/_components/student-detail-panel.tsx`
- `frontend/src/app/admin/_components/student-detail-modal.tsx`
- `frontend/src/app/admin/_components/retention-panels.tsx`
- `frontend/src/lib/api-client.ts`

Cross-references:
- `docs/followups/celery-safety-memory-bump.md` — worker memory
  remediation (a)/(b) pending.
- `docs/followups/d15-followup-legacy-promoted-role-reconciliation.md`
  — `users.promoted_to_role` is unrelated to admin status.
- `docs/architecture/d15-role-progression-overview.md` — D15
  primitives D16 will consume (`evaluate_student_against_gate`,
  `read_student_role_state`).
- `docs/architecture/pass-3h-interrupt-agent-proactive-loop.md` —
  prior architectural sketch of proactive layer (not yet wired into
  any production agent).
