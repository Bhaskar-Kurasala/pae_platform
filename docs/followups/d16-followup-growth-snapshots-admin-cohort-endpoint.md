# D16 follow-up — admin cohort read endpoint for growth_snapshots

**Status:** Open. LOW severity. Defer to D17b/post-launch.
**Created:** 2026-05-08 (D16/CP2 closure).

## What this is

CP1 finding (j): `growth_snapshots` Celery task writes `GrowthSnapshot`
rows weekly (Sunday 00:00 UTC) for every active user. Read side: only
`/api/v1/receipts/me` exposes growth snapshots, and only for the
authenticated student themself. There is no admin endpoint that reads
cohort growth data. The cockpit does not consume `growth_snapshots`.

The data is being written. There's no defect; the gap is read-side
visibility for operators.

## What this follow-up tracks

Adding `GET /api/v1/admin/growth-snapshots?week_ending=YYYY-MM-DD`
that returns a cohort summary the admin can use to spot low-growth
weeks at the cohort level.

## Sketch shape

```python
class AdminCohortGrowthSummary(BaseModel):
    week_ending: date
    user_count: int
    avg_lessons_completed: float
    median_lessons_completed: int
    avg_skills_touched: float
    avg_streak_days: float
    top_concepts: list[tuple[str, int]]  # (concept, frequency)
    bottom_quintile_users: list[uuid.UUID]  # for follow-up outreach
```

Endpoint reads `growth_snapshots WHERE week_ending = :week_ending`
and aggregates. Read-only; no writes.

## When to ship

Post-launch unless a pre-launch admin specifically asks for the
cohort view. Low-priority — the per-student growth view is already
visible via the timeline + activity panels.

## Cross-references

- `backend/app/tasks/growth_snapshots.py` — write side.
- `backend/app/api/v1/routes/receipts.py:45-65` — student-facing read.
- `docs/architecture/d16-functional-audit.md` finding (j).
