# D15 follow-up — admin UI for tuning gate thresholds

**Status:** Open. Post-launch frontend work.
**Created:** 2026-05-08 (D15 CP5 closure).

## What this is

Per D-B (locked decision at CP1): gate thresholds in `role_transitions`
are tunable data, not code. Admins update `capstone_threshold`,
`capstone_count_required`, `mock_interview_dimensions` (JSONB
weights), `mock_interview_pass_threshold`,
`mock_interview_sessions_required_pass`, and
`mock_interview_sessions_window` via direct DB updates.

D15 v1 ships without an admin UI. Direct DB access is acceptable for a
small founder-operated platform. Once student volume grows or the
founder delegates gate-tuning to other operators, the DB-direct path
becomes friction.

## What an admin UI would cover

- List the five role transitions with current threshold values.
- Per-transition edit form: capstone_threshold (0.0–1.0 slider with
  CHECK-constraint enforcement), capstone_count_required (int >= 1),
  mock_interview_pass_threshold (0.0–1.0), sessions_required_pass +
  window (defaulted 2/3; admin can adjust).
- mock_interview_dimensions JSONB editor with constraint that weights
  sum to 1.0 (the current schema doesn't enforce this — runtime backstops
  in `_enforce_session_verdict` normalize). Admin form should pre-flight
  the sum.
- Audit log: who changed what threshold when. Surface in
  `agent_actions` or a new `gate_tuning_audit` table.

## Why post-launch

- v1 founder-operated; DB access is the founder's tool.
- Student volume is small enough that gate observability is "look at
  agent_evaluations + agent_actions for the past month, eyeball the
  pass rates."
- The schema is already admin-tunable; the UI is just ergonomic
  packaging.

Trigger to revisit: founder delegates gate-tuning, OR pass rates need
weekly retuning.

## Cross-references

- `migration 0061_role_progression_schema.py` — schema columns.
- `migration 0064_courses_role_backfill.py` — first-pass values.
- `docs/architecture/d15-role-progression-overview.md` — D-B locked
  decision context.
