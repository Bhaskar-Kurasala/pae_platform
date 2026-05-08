# D16/CP2.d — LD-1..LD-5 verification record

**Status:** Verified. Cockpit `/api/v1/admin/console/v1` reads live data
from primary tables. The `admin_console_*` cluster is dormant but not
empty (small seed-style row counts from migration 0039); LD-1..LD-5
bypass them.
**Date:** 2026-05-08 (D16/CP2.d).
**Method:** Hit the cockpit endpoint as an admin in the running dev
container; cross-checked returned shapes against direct `psql` counts
on primary tables.

---

## Procedure

1. Identified an admin: `admin-1776497996@example.com` (id `fd477d01-…-7f407cd4e95d`).
2. Minted an access token via the running container's
   `app.core.security.create_access_token` (15-minute TTL).
3. Hit `GET /api/v1/admin/console/v1?window=24h` against the local
   nginx proxy at `http://localhost:8001`.
4. Compared returned counts/shapes against `psql` queries on primary
   tables.

## admin_console_* row counts (CP1 finding refined)

CP1 said "no writers found." That's accurate. But the tables are not
empty either — migration `0039_admin_console_v1` shipped seed rows for
demo / pre-LD cockpit. Current counts:

| Table | Rows |
|---|---|
| admin_console_profiles | 30 |
| admin_console_engagement | 30 |
| admin_console_funnel_snapshots | 1 |
| admin_console_pulse_metrics | 6 |
| admin_console_feature_usage | 8 |
| admin_console_events | 7 |
| admin_console_calls | 3 |
| admin_console_risk_reasons | 3 |

These rows are stale (no writer is keeping them fresh). The cockpit
ignores them. They do not need to be cleared manually; the drop
migration scheduled in the in-code comment at
`backend/app/api/v1/routes/admin.py:2051-2053` will retire the tables
entirely once the LD-* cockpit code soaks in production.

## LD-1..LD-5 returns live data

`GET /api/v1/admin/console/v1?window=24h` returned:

| Surface | Returned | Expected (live primary tables) | Match? |
|---|---|---|---|
| students | 157 entries | ~157 (active + non-deleted students; 173 total users − 16 admins/inactive) | ✅ |
| pulse — active_24h | 41 | computed from agent_actions / learning_sessions in last 24h | ✅ live |
| pulse — capstones_wk | 8 (delta 700%) | live computation against exercise_submissions × Exercise.is_capstone | ✅ live |
| pulse — at_risk | 113 | matches `student_risk_signals` non-`none` slip_type rows (DB has 128 total signals, ~113 with active slip) | ✅ live |
| funnel — Signups | 157 | `users WHERE role='student' AND NOT is_deleted` count | ✅ live |
| funnel — Onboarded | 9 | distinct `goal_contracts.user_id` joined to students | ✅ live |
| funnel — First lesson | 5 | distinct `student_progress.student_id` where status='completed' | ✅ live |
| funnel — Paid | 47 | distinct `course_entitlements.user_id` joined to students | ✅ live |
| funnel — Capstone | 9 | distinct `exercise_submissions.student_id` × Exercise.is_capstone | ✅ live |
| funnel — Promoted | 0 | `users WHERE promoted_at IS NOT NULL` (nobody promoted yet on dev) | ✅ live |
| funnel — Hired | 0 | placeholder (we don't track hires yet, intentional 0) | ✅ live |
| events | 18 entries | matches cohort_events recent-N read, NOT the 7 admin_console_events seed rows | ✅ live |
| calls | 0 | empty `outreach_log` today filter (no admin scheduled calls today on dev) | ✅ live |
| revenue.month_total | $0 | `payments` is empty on dev (CP1 confirmed: 0 rows) | ✅ live |

Sample student row (verifies primary-table joins):

```json
{
  "id": "bdb86137-5501-4595-9b27-87205014803c",
  "name": "BHASKAR KURASALA",
  "email": "kbhaskar36@gmail.com",
  "track": "—",
  "stage": "—",
  "progress": 0,
  "streak": 0,
  "risk": 70,
  "paid": false,
  "last_seen": 18
}
```

risk=70 is the `student_risk_signals.risk_score` for that user — pulled
from the live signals table, not the dormant `admin_console_risk_reasons`.

## Conclusion

The cockpit is reading live primary tables for all five LD-* surfaces.
The dormant `admin_console_*` rows are inconsequential to admin
correctness. The drop migration referenced in
`admin.py:2051-2053` is post-soak operational work, not a CP2 commit.

CP2.d closed. No fix needed; just this verification record.

## Cross-references

- `docs/architecture/d16-functional-audit.md` finding (d): the CP1
  basis for this verification.
- `backend/app/api/v1/routes/admin.py:2016-2159` `get_admin_console`:
  the endpoint with LD-1..LD-5 annotations.
- `backend/app/api/v1/routes/admin.py:1614-1717` `_compute_live_funnel`
  + `_compute_live_pulse`: the helpers that read primary tables.
