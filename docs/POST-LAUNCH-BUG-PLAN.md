# Post-Launch Bug-Fix Plan

**Snapshot date:** 2026-04-19
**Context:** Written after the 10-PR B5 E2E Hardening sweep closed 82 rows in [E2E-TEST-TRACKER.md](E2E-TEST-TRACKER.md). This doc captures what remains so we don't lose the picture when the team scatters post-launch.

**Current totals:** 14 passing · 9 failing · 82 closed · ~20 DISC-# items open across all buckets.

---

## Bucket 1 — Launch blockers (DO NOT SHIP WITHOUT)

Must be green before a student touches paid flows. Estimated **2–3 working days** total.

| ID | Title | Why it blocks | Rough effort |
|---|---|---|---|
| **DISC-1** | celery-beat restart loop — scheduled tasks not firing | Weekly progress letters + `disrupt_prevention` re-engagement never run. Silent user drop-off. | 1 day (diagnose loop cause → fix broker/scheduler config → verify beat stays up for 24h) |
| **DISC-21** | Paid-course paywall not wired on frontend | $49/$99 courses fully open — zero revenue capture. | 1–1.5 days (`useMyEnrollments` hook + Enroll CTA on courses/[id] + Stripe checkout redirect + lesson-list gating) |

**Exit criteria for launch:** both rows flipped to `closed` in the tracker, verified in a staging deploy with Stripe test mode.

---

## Bucket 2 — First-week fixes (ship within 7 days of launch)

These degrade the experience but don't block launch. Students will notice within a week. Estimated **3–4 working days** total.

| ID | Title | User impact | Rough effort |
|---|---|---|---|
| **DISC-18** | Onboarding skip button bypasses profile creation | New students land on Today with empty profile → broken agent personalization. | 0.5 day |
| **DISC-22** | Progress page "% complete" always shows 0 for courses without lessons seeded | Cosmetic but confusing on dashboards. | 0.5 day |
| **DISC-20** | Exercise submission retry loop on 500 | Bad network → infinite spinner, no retry cap. | 0.5 day |
| **DISC-3** | Chat streaming cursor jumps on long responses | Visual jank, not a data bug. | 1 day |
| **DISC-6** | Socratic tutor occasionally returns raw JSON when max_tokens truncates | Ugly; parsing fallback already handles it but users see the tail. | 1 day (bump max_tokens + add guard in parser) |

---

## Bucket 3 — Deferrable / polish (land opportunistically)

Safe to leave open at launch. Most are admin-side, edge-case, or cosmetic. Estimated **4–6 working days** total — batch into 1–2 PRs per week post-launch.

| ID | Title | Notes |
|---|---|---|
| DISC-14 | Admin audit log filter by actor_role is slow on 10k+ rows | Add partial index when row count grows. |
| DISC-23 | Lessons missing `video_id` show empty player | Backfill once real content lands. |
| ~~DISC-25~~ | ~~Lesson page un-complete toggle missing~~ | Closed 2026-04-19 — added `DELETE /students/me/lessons/{id}/complete` + "Mark as incomplete" button. |
| DISC-29 | Agent health page "last call" shows UTC not local | One-line `toLocaleString()` swap. |
| DISC-36 | Student drilldown timeline pagination after 200 events | Not hit until power-users accumulate. |
| ~~DISC-38~~ | ~~"Ask the tutor" handoff on failing submission~~ | Closed 2026-04-19 — exercise card CTA + chat `?submission_id=` prefill. |
| DISC-17 | Studio agent-builder preview drifts from prod config | Internal tool, low priority. |
| DISC-19 | Settings page theme toggle doesn't persist across devices | Needs user-preferences table. |
| ~~DISC-4~~ | ~~`landing.test.tsx` stale assertions~~ | Closed 2026-04-19 — tests rewritten against current landing IA. |

---

## Bucket 4 — Tracker reconciliation (do immediately, 0.5 day)

DISC-59, DISC-60, DISC-61 are marked **fixed** in the Deferred Fixes table but still say **open** in the Discoveries table of [E2E-TEST-TRACKER.md](E2E-TEST-TRACKER.md). Verify each is truly closed, then flip the Discoveries row to `closed` to keep the two tables in sync.

---

## Suggested sequencing

```
Week 1 (pre-launch):  Bucket 1  → launch gate
Week 2 (launch + 7):  Bucket 2  → first patch release
Week 3–4:             Bucket 3  → batched polish PRs
Any time:             Bucket 4  → housekeeping
```

**Total remaining effort to zero open bugs: ~10–13 working days (~2–2.5 calendar weeks at steady pace).**

---

## How to use this doc

- When a DISC-# is fixed, strike it here AND flip the row in [E2E-TEST-TRACKER.md](E2E-TEST-TRACKER.md).
- New bugs found post-launch: add to the tracker first, then categorize into a bucket here.
- Re-snapshot this doc at the end of each week so the effort column stays honest.
