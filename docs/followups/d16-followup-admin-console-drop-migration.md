# D16 follow-up — drop migration for admin_console_* tables

**Status:** Open. Post-soak operational work.
**Created:** 2026-05-08 (D16/CP2 closure).

## What this is

Migration `0039_admin_console_v1` (2026-04-25) shipped 8 `admin_console_*`
tables that the cockpit originally read from. The cockpit was migrated
in a subsequent change (LD-1..LD-5 annotations in
`backend/app/api/v1/routes/admin.py:2016-2159`) to read from primary
tables instead. The `admin_console_*` tables remain in the schema as a
safety net per the in-code comment at lines 2051-2053:

> "The 8 admin_console_* tables and their seed script remain in the
> schema for one more deploy as a safety net; they are dropped by a
> follow-up alembic migration once this code soaks in production."

CP2.d verified this by hitting `/api/v1/admin/console/v1` against the
running dev container and confirming live primary-table reads (record:
`docs/architecture/d16-cp2d-ld-verification.md`).

## What this follow-up tracks

The drop migration that retires the cluster.

## When to ship

After the LD-1..LD-5 cockpit code has soaked in production for at least
one full release cycle without rollback. Soak duration is operational —
the founder/operator decides "we're confident enough" based on the
absence of cockpit complaints, telemetry on `/api/v1/admin/console/v1`
error rates, and the absence of any "hey can we restore admin_console_*"
fire drill.

## What the migration looks like

A new alembic revision dropping the 8 tables:

```python
def upgrade() -> None:
    op.drop_table("admin_console_risk_reasons")
    op.drop_table("admin_console_calls")
    op.drop_table("admin_console_events")
    op.drop_table("admin_console_feature_usage")
    op.drop_table("admin_console_pulse_metrics")
    op.drop_table("admin_console_funnel_snapshots")
    op.drop_table("admin_console_engagement")
    op.drop_table("admin_console_profiles")


def downgrade() -> None:
    # Re-add the schema only — no seed data on downgrade. Recovery from
    # a wrong drop is a snapshot restore, not a downgrade.
    raise NotImplementedError("Re-create from migration 0039 if needed")
```

Plus deletion of the matching ORM models in
`backend/app/models/admin_console.py` and removal from
`backend/app/models/__init__.py`.

## Pre-drop checklist

- [ ] `/api/v1/admin/console/v1` has been on LD-1..LD-5 in production
  for ≥ 2 weeks
- [ ] No cockpit-related rollback has happened in the soak window
- [ ] No active code path imports `AdminConsoleProfile` /
  `AdminConsoleEngagement` / etc. (grep verifies)
- [ ] The migration has been applied and rolled back successfully on
  staging

## Cross-references

- `docs/architecture/d16-cp2d-ld-verification.md` — CP2.d verification
  record (live data confirmed).
- `docs/architecture/d16-functional-audit.md` finding (d).
- `backend/app/api/v1/routes/admin.py:2051-2053` — the in-code comment
  that pre-committed to this drop.
