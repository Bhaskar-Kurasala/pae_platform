# Admin Console — Live Data Migration (LD-1 → LD-7)

**Author:** Bhaskar
**Started:** 2026-04-30
**Tracker for:** Replacing the legacy "CareerForge_admin_v1" demo console (bottom half of `/admin`) with live data, block by block, while preserving the approved visual design.

---

## Why

The bottom half of `/admin` is currently powered by 8 `admin_console_*` tables seeded by `scripts/seed_admin_console.py`. That demo data was the right call to validate the visual design before we had real engagement, but now it competes with the live F4 retention panels above it and creates two operational problems:

1. **The numbers contradict each other.** Top half says "97 cold-signup students at risk". Bottom half says "Aanya Reddy 92 risk, scheduled at 10:30". An operator clicking Aanya finds out she doesn't exist as a real student.

2. **Click-throughs are dead.** "Open profile" / "Send DM" / "Schedule call" / "Add note" buttons in the modal go nowhere — they were placeholder design.

The fix: keep the visual layout (it's good), swap the data source on each block from `admin_console_*` to the equivalent live table.

## Scope (NOT changing)

- The visual design of `/admin` stays identical.
- The retention panels at the top (F4) are already live; this work is below them.
- Page sections (action band, pulse strip, funnel, feature pulse, roster, right rail) keep their current order and styling.
- The CSS module (`console.module.css`) does not change.

## Scope (changing)

- 9 blocks listed below, plus their backend routes.
- The 8 demo seed tables retire in LD-7 (last).
- The hardcoded `buildTimeline()` JS function in `frontend/src/app/admin/page.tsx` is removed; the modal either fetches the real `/admin/students/[id]/timeline` endpoint or is replaced by a hard-navigate to that page.

## Mapping — demo source → live source

| Block | Today reads from | New source |
|---|---|---|
| Action band — top 3 risk cards | `admin_console_profiles` + `admin_console_risk_reasons` | `student_risk_signals` ORDER BY risk_score DESC LIMIT 3 |
| Pulse strip (5 sparklines) | `admin_console_pulse_metrics` | `agent_actions`, `enrollments`, `feedback`, `payments` (per-day buckets for sparkline) |
| Learner funnel | `admin_console_funnel_snapshots` | `users`, `student_progress`, `exercise_submissions`, `users.promoted_at` |
| Feature pulse tiles (8) | `admin_console_feature_usage` | `srs_cards`, `agent_actions` (per agent), `ai_reviews`, `notebook_entries`, `exercise_submissions`, `interview_sessions`, `jd_match_scores` |
| Full student roster | `admin_console_profiles` + `admin_console_engagement` | `users` LEFT JOIN `student_risk_signals` + computed engagement counts |
| Right rail — today's calls | `admin_console_calls` | `outreach_log` rows where kind='scheduled_call' AND scheduled_at::date = today |
| Right rail — live event feed | `admin_console_events` | `cohort_events` (already populated, masked handles) |
| Right rail — revenue card | bundled in `admin_console_pulse_metrics` MRR row | SUM over `payments.amount_cents` grouped by month |
| Modal — student timeline | hardcoded JS `buildTimeline()` | `/api/v1/admin/students/{id}/timeline` (already exists, F14 paginated) |

---

## Status

**All 7 tickets shipped on `feat/ld-1-action-band-roster-live` branch.**

| Ticket | Status | Commit |
|---|---|---|
| LD-1 — action band + roster + click-thru | ✅ | `e8135a0` |
| LD-2 — pulse strip live with sparklines | ✅ | `ed0a699` |
| LD-3 — learner funnel real counts | ✅ | `2569afd` |
| LD-4 — feature pulse 8 tiles live | ✅ | `84b5b93` |
| LD-5 — right rail (calls + events + revenue) | ✅ | `c24dae0` |
| LD-6 — remove legacy student modal | ✅ | `56f9d5a` |
| LD-7 — drop unused admin_console_* imports | ✅ | `ac90c44` |

The legacy demo console v1 is now 100% sourced from live tables. The
8 admin_console_* tables and seed_admin_console.py script remain in
the schema for one more deploy as a safety net; a follow-up alembic
migration will drop them after this code soaks in production.

---

## Tickets

### ✅ LD-1 — Wire action band + roster to retention engine
**Effort:** ~½ day
**Depends on:** F1 (live), F4 (live)
**Owner:** main session (foreground)

**What it builds:**
- Action band reads top 3 from `student_risk_signals` ordered by `risk_score DESC`. Each card shows real name, real email, real risk reason from `student_risk_signals.risk_reason`.
- Full student roster is rendered from `users WHERE role='student'` LEFT JOINed with `student_risk_signals` (so risk score appears for at-risk students, blank for healthy).
- Row click navigates to `/admin/students/[id]` instead of opening the JS modal.

**Acceptance:**
- Click any roster row → lands on real `/admin/students/[id]` page.
- Action band names match `student_risk_signals` top 3.
- "0 students need a personal nudge" empty state when no rows in `student_risk_signals`.

---

### ✅ LD-2 — Pulse strip with sparklines (live)
**Effort:** ~1 day
**Depends on:** F12 (live)
**Owner:** parallel agent

**What it builds:**
- 5 metric cards, each with: current value, prior-period delta %, 14-day sparkline.
- Backend route `GET /api/v1/admin/pulse-strip?window=24h|7d|30d` returns all 5 in one shot.
- The 5 metrics:
  1. **Active students** — distinct `agent_actions.student_id` in window
  2. **Agent calls** — count of `agent_actions` in window
  3. **Avg eval score** — same proxy as F12 (avg duration_ms normalised)
  4. **New enrollments** — count of `enrollments.created_at` in window
  5. **MRR** — SUM(`payments.amount_cents`) for paid charges in last 30 days, divided by 30 × month-length
- Sparkline = same metric bucketed daily for the last 14 days.

**Acceptance:**
- Window switcher recomputes all 5 + sparklines.
- Sparkline renders 14 buckets even when most are 0.
- Delta % is correct vs. prior window (e.g. last 24h vs the 24h before that).

---

### ✅ LD-3 — Learner funnel real counts
**Effort:** ~½ day
**Depends on:** none
**Owner:** parallel agent

**What it builds:**
- 5-stage funnel: Signup → Day 1 active → First lesson complete → First capstone submitted → Promoted.
- Backend route `GET /api/v1/admin/learner-funnel?days=30` returns 5 counts.
- Each stage's drop-rate computed client-side from the response.

**Stages defined:**
- **Signup** — `users.created_at >= NOW() - days`
- **Day 1 active** — same cohort, has at least one row in `learning_sessions` OR `agent_actions` within 1 day of signup
- **First lesson complete** — same cohort, at least one `student_progress.status='completed'`
- **First capstone submitted** — same cohort, at least one `exercise_submissions` for an exercise with `is_capstone=true`
- **Promoted** — same cohort, `users.promoted_at IS NOT NULL`

**Acceptance:**
- Funnel chart renders even when later stages are 0.
- Drop-rate flagged red when ≥35% (matches existing UI threshold).

---

### ✅ LD-4 — Feature pulse tiles (8 metrics)
**Effort:** ~1 day
**Depends on:** none
**Owner:** parallel agent

**What it builds:**
- 8 tiles, each with: feature_key, name, count this week, sub-line ("vs prior week"), 7-day sparkline, cold flag.
- Backend route `GET /api/v1/admin/feature-pulse?days=7` returns 8 tiles.

**Tile mapping:**
| feature_key | Source | Count formula |
|---|---|---|
| flashcards | `srs_cards` | rows where `last_reviewed_at >= NOW() - days` |
| agent_q | `agent_actions` | rows where `agent_name='socratic_tutor' AND created_at >= NOW() - days` |
| senior_reviews | `ai_reviews` | rows where `created_at >= NOW() - days` |
| notes | `notebook_entries` | rows where `state='graduated' AND graduated_at >= NOW() - days` |
| labs | `exercise_submissions` | join `exercises` where `is_capstone=false`, count submissions in window |
| capstones | `exercise_submissions` | join `exercises` where `is_capstone=true`, count submissions in window |
| jd_match | `jd_match_scores` | rows in window |
| interview | `interview_sessions` | rows where `completed_at >= NOW() - days` |

**Cold flag:** `cold = current_count < 0.5 * prior_count` (the tile dims when usage drops by half vs the prior week).

**Sparkline:** same metric bucketed daily for the last 7 days.

**Acceptance:**
- All 8 tiles render with real numbers.
- Cold tiles visually dim (existing CSS class `.cold` already there).
- Bars chart has 7 bars even when most are 0.

---

### ✅ LD-5 — Right rail: today's calls + live event feed + revenue
**Effort:** ~1 day
**Depends on:** LD-1 (for outreach_log shape)
**Owner:** sequential after LD-1

**What it builds:**

- **Today's calls** — query `outreach_log` rows where `kind='scheduled_call' AND scheduled_at::date = current_date()`. Display time + student name + reason.
  - **Sub-task:** add `kind='scheduled_call'` and `scheduled_at` columns to `outreach_log` (alembic 0054). Wire F10 "Schedule call" mailto to also write a row.
  
- **Live event feed** — query last 50 `cohort_events` ordered by `created_at DESC`. Already populated by:
  - Promotion completion (`community_celebrator` agent on `users.promoted_at` write)
  - Capstone submission (auto-event on `exercise_submissions` insert where capstone)
  - Peer review request (`peer_review_assignments` insert)
  - Signup (auto-event on `users` insert)
  - Purchase (Stripe webhook)
  
- **Revenue card** — SUM(`payments.amount_cents`) WHERE status='succeeded' GROUPED BY month for the last 6 months. Display: this-month total, new purchases (this month), renewals (this month), refunds (this month, from `refunds` table). Sparkline = last 30 days daily totals.

**Backend route:** `GET /api/v1/admin/right-rail` returns all three blocks in one shot.

**Acceptance:**
- Calls list shows real scheduled calls (after at least one F10 click).
- Event feed shows real student names (masked first-name + last-initial).
- Revenue card matches Stripe dashboard for the same month.

---

### ✅ LD-6 — Wire student modal to live drilldown
**Effort:** ~½ day
**Depends on:** LD-1
**Owner:** sequential after LD-1

**Decision needed first:** keep the modal or remove it?

**Option A (remove modal):** row click → hard-navigate to `/admin/students/[id]`. Cleaner, simpler, but slower (full page nav).

**Option B (keep modal):** modal fetches real timeline + wires "Send DM" / "Add note" / "Schedule call" buttons.

**Recommended:** Option B. The modal is good UX for fast triage — operator can scan 5 students in 30 seconds without leaving the page. Wire it up:

- Modal fetches `/admin/students/{id}/timeline?limit=20` on open.
- Replace hardcoded `buildTimeline()` JS with rendered timeline events.
- "Send DM" → opens compose form, calls `POST /admin/students/{id}/messages`.
- "Add note" → opens compose form, calls `POST /admin/students/{id}/notes`.
- "Schedule call" → existing F10 `buildCallInviteMailto()`, plus writes `outreach_log` row (LD-5 dependency for the right-rail call list to populate).

**Acceptance:**
- Modal timeline shows real events for the clicked student.
- All three action buttons functional.
- Operator can triage 3 students from the roster without page navigation.

---

### ✅ LD-7 — Retire `admin_console_*` demo tables
**Effort:** ~½ day
**Depends on:** LD-1 → LD-6 all merged and verified
**Owner:** cleanup commit

**What it does:**
- New alembic migration `0055_retire_admin_console_demo` that drops the 8 `admin_console_*` tables.
- Delete `scripts/seed_admin_console.py`.
- Delete `app/models/admin_console.py`.
- Delete the `/api/v1/admin/console/v1` route handler.
- Delete the legacy `ConsoleResponse` types in `frontend/src/app/admin/page.tsx`.

**Acceptance:**
- `docker compose exec backend uv run alembic upgrade head` runs clean on a fresh DB.
- `/admin` still loads and all blocks populate from live data only.
- No imports of `admin_console_*` remain in the codebase (`grep -r admin_console_ backend/app frontend/src` returns nothing).

---

## Backend routes added by this work

| Route | Returns |
|---|---|
| `GET /api/v1/admin/pulse-strip?window=24h\|7d\|30d` | 5 pulse cards with sparklines |
| `GET /api/v1/admin/learner-funnel?days=30` | 5-stage funnel counts |
| `GET /api/v1/admin/feature-pulse?days=7` | 8 feature tiles with bars |
| `GET /api/v1/admin/right-rail` | calls + events + revenue bundle |

The legacy `GET /api/v1/admin/console/v1` route is retired in LD-7.

## Frontend hooks added

| Hook | Backs |
|---|---|
| `useAdminPulseStrip(window)` | LD-2 |
| `useAdminFunnel(days)` | LD-3 |
| `useAdminFeaturePulse(days)` | LD-4 |
| `useAdminRightRail()` | LD-5 |

## Sequencing

```
                LD-1 (foreground) ─┐
                                  │
       LD-2 (parallel agent) ─────┼── all merge to main
       LD-3 (parallel agent) ─────┤
       LD-4 (parallel agent) ─────┘
                                  │
                                  ▼
                LD-5 (sequential, depends on LD-1's outreach_log shape)
                                  │
                                  ▼
                LD-6 (sequential, depends on LD-1)
                                  │
                                  ▼
                LD-7 (cleanup, depends on LD-1..6 verified)
```

## Total effort

~5 working days for one engineer. Compressing to ~2 days with parallel agents on LD-2/LD-3/LD-4.
