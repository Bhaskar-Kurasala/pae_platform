# D15 follow-up — role transition celebration UX

**Status:** Open. Post-launch frontend work.
**Created:** 2026-05-08 (D15 CP5 closure).

## What this is

When a student passes a gate (capstone + mock_interview window both
satisfy the threshold), the platform should:

1. Append a record to `student_role_state.transitions_completed` JSONB
   array with `from_slug`, `to_slug`, `completed_at`, `capstone_score`,
   `mock_session_ids`.
2. Update `student_role_state.current_role_id` to the next role.
3. Reset `role_started_at = now()` for the new role's day-counter.
4. Surface a celebration UX to the student — the moment they pass is
   load-bearing for engagement and motivation.

D15 v1 ships steps 1–3 (the data side) but does NOT auto-promote
students. The current architecture is **detection only**: the agents
can report `gate_passable=True`, but the actual transition row update
is manual / proactive-trigger territory (D16 candidate).

The celebration UX itself is post-launch frontend work.

## Two questions that need answering before implementation

1. **Auto-promote vs. opt-in promotion?**
   - Auto: the moment `evaluate_student_against_gate` returns
     `gate_passable=True`, write the transition row and surface the UX.
     Risk: students who satisfy the gate by accident (wrong-target mock
     session that happens to pass) get promoted unintentionally.
   - Opt-in: `gate_passable=True` surfaces a "ready to transition"
     prompt; the student must confirm. Safer; matches the
     "platform tells the truth, student decides" pattern.

2. **Where does the trigger live?**
   - Option A: D16's proactive layer — a nightly job that polls
     `evaluate_student_against_gate` for every active student and
     fires when any returns True.
   - Option B: A post-evaluation hook on `project_evaluator` and
     `mock_interview` — when either agent emits a `passes_threshold=True`
     verdict for the student's current gate, dispatch to the
     promotion service.
   - Option B is more responsive (the student sees the promotion right
     after the action that triggered it); Option A is cheaper and
     handles edge cases (delayed evaluation, retroactive grading).

## Celebration UX shape (sketch)

- Modal appears on next chat turn after promotion: "You just passed
  the gate to [next_role]." Quote the role's `description` so the
  student feels the new identity.
- The Today screen role badge updates from `[old_role.display_name]`
  to `[new_role.display_name]` with a transition animation.
- A timeline view shows all completed transitions with capstone
  scores + mock session IDs (sourced from `transitions_completed`
  JSONB).
- Senior_genai_engineer terminal transition triggers an additional
  copy: "Schedule the founder's in-person interview for external
  application endorsement."

## Trigger to revisit

Student passes their first real gate post-launch. Until then this is
deferred.

## Cross-references

- `student_role_state.transitions_completed` — schema (CP1).
- `evaluate_student_against_gate` tool — produces the verdict the
  promotion service consumes.
- D16 saved prompt (TBD) — proactive layer that may host the
  promotion trigger.
