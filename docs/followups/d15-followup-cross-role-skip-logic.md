# D15 follow-up — cross-role skip logic (D-A v2 territory)

**Status:** Open. v2 territory; not on any current roadmap.
**Created:** 2026-05-08 (D15 CP5 closure).

## What this is

Per D-A locked at CP1: the six-role progression is strictly sequential
in v1. `evaluate_student_against_gate` raises `ValueError` on any
non-adjacent target. This is the simplest correct implementation and
matches the founder's product opinion that the progression itself IS
the value.

Some students arrive with prior experience. A senior data scientist
joining the platform should not have to grind through python_developer
practice problems to prove they can write Python. v2 territory: an
admin-override path that lets a student start at any role with a
"placement" credential.

## Two design questions for v2

1. **What proves placement?**
   - Founder interview: simplest, highest-fidelity, doesn't scale.
   - Capstone assessment at the target role: student submits a
     real capstone for the role they want to start in;
     `project_evaluator` scores it. If above threshold, admin
     promotes. Equivalent to passing the gate without the gate's
     historical context.
   - Multi-role retroactive credit: student does the senior_genai
     gate-prep mock-interview suite; if they pass, ALL prior roles
     count as completed (skip-ahead with retroactive transition rows
     for audit).
   - Resume + portfolio review: lightest-weight; admin-judgmental.

2. **What does the data look like post-skip?**
   - Treat the skip as a single special transition row in
     `transitions_completed` with `from_slug = "(none)"` and
     `to_slug = "<placed_role>"`?
   - Or write N transition rows (one per skipped role) marked
     `placement: true` so dashboards can filter?
   - Schema implications: `transitions_completed` is JSONB, so this
     is a data-shape decision, not a schema migration.

## Why this stays deferred

- v1 student volume doesn't include senior arrivals at meaningful
  rate.
- Skip-logic complicates `evaluate_student_against_gate` (the current
  adjacency check would need a "placement" exception path).
- The progression's coherence depends on every student walking the
  same path; one-off skips erode the platform's narrative for
  marketing + cohort effects.

Trigger to revisit: a senior arrival lands and explicitly asks to
skip ahead.

## Cross-references

- `migration 0061_role_progression_schema.py` — sequence_order
  enforcement.
- `evaluate_student_against_gate.py` — current adjacency check.
- `docs/architecture/d15-role-progression-overview.md` — D-A locked
  decision context.
