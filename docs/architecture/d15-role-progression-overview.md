# D15 — Role Progression Overview

**Status:** Shipped 2026-05-08.
**Implementation:** CP1–CP5 commits 965bf61 → 77105ed (CP5 closure commit added below).
**Saved prompt:** `docs/claude-code-prompts/d15-prompt.md`.

This is the architectural one-pager for the D15 role progression model.
Implementation detail lives in the saved prompt and the per-checkpoint
commit messages; this doc orients new readers in 10 minutes.

## Product framing

AICareerOS is a **curated linear career simulation**, not a curriculum
platform. Students progress through six role identities, gated by
capstones and mock interviews. Existing agents (career_coach,
study_planner, practice_curator, project_evaluator, mock_interview)
adjust voice and content based on the student's current role AND on
content the student actually has access to at runtime.

This reframe replaced the original D15 plan (curriculum graph +
content_ingestion + curriculum_mapper merge); those efforts are
deferred indefinitely. Real student usage will signal whether
topic-graph infrastructure is ever needed.

## Six roles, five gates

```
python_developer  →  data_analyst  →  data_scientist  →  ml_engineer
                                                              ↓
                                          genai_engineer  →  senior_genai_engineer
                                                                    ↑
                                                              terminal role
```

Sequence is strictly enforced. No skip-ahead in v1 (D-A locked
decision; admin override is post-launch territory). Each non-terminal
role is gated by:

1. **Capstone** — `project_evaluator` scores a submission against the
   exercise's published rubric. The transition's `capstone_threshold`
   defines the bar (0.65 for the first transition, tightening to 0.80
   at `genai_engineer → senior_genai_engineer`). The terminal gate
   requires 2 capstones; all others require 1.
2. **Mock interview** — `mock_interview` runs a multi-turn session and
   produces a multi-dimensional `SessionVerdict` (4 dimensions:
   clarity_of_questioning, directional_adherence, complexity_adaptation,
   technical_correctness). The gate requires **2 of the last 3 mock
   sessions** (for the relevant transition) to pass at the threshold.

Students must pass BOTH conditions for their current role before
transitioning to the next. The terminal `senior_genai_engineer` role
also requires the founder's in-person interview (out of D15 scope;
gates the platform's external-application endorsement).

## Why agents reason in role-relative terms

The five updated agents read three universal tools at runtime to
ground their output in actual student state:

- **`read_student_role_state`** — current role, days in role,
  completed transitions, next-transition gate summary.
- **`read_student_accessible_content`** — courses, curated problems,
  notebooks the student has entitled access to RIGHT NOW, optionally
  filtered to a single role. Returns a `content_schema_completeness`
  flag (`complete` | `partial` | `minimal`) that agents read to
  decide whether to ground in specific content or fall back to
  role-identity-only reasoning.
- **`evaluate_student_against_gate`** — composes student state +
  capstone history + recent mock sessions into a structured pass/fail
  verdict with a `gap_summary` string.

Plus one CP4-added universal tool:

- **`read_role_transition_gate`** — pure metadata read of a single
  (from, to) transition's gate definition. Used by `project_evaluator`
  for D-G gate-context awareness and by `mock_interview` for gate-prep
  session scoring.

## Runtime content discovery (D-E discipline)

Agents NEVER reference specific content (notebook titles, problem
names, capstone descriptions) **in their prompts**. They reference
content abstractly ("the curated problems for your current role")
and discover concrete content at runtime via
`read_student_accessible_content`. Agents handle the three
completeness states distinctly:

- **`complete`** — every content type non-empty for the requested role.
  Reference items by title verbatim.
- **`partial`** — at least one accessible course but at least one of
  (curated problems, notebooks) empty. Ground in what's present;
  honestly acknowledge what's missing.
- **`minimal`** — no accessible content for the requested role. Reason
  in role-identity terms only ("practice the kind of problems this
  role faces"). Never invent.

`partial` is the production-realistic dominant state on dev DB at
ship — `lesson_resources` is empty so notebooks are universally
absent. CP3-CP5 verification confirmed all five agents handle
`partial` gracefully without fabrication.

## Schema

Three new tables added at CP1 (migration 0061) + 0062 backfill:

```
roles                   — six identity rows (slug, display_name,
                          description, sequence_order, is_terminal,
                          metadata).
role_transitions        — five gate definitions, one per adjacent pair.
                          mock_interview_dimensions JSONB rubric.
                          Thresholds, count_required, window/required_pass.
student_role_state      — one row per student (UNIQUE student_id).
                          current_role_id, role_started_at,
                          transitions_completed JSONB array,
                          gates_attempted JSONB scratch.
```

CP2 added one column at migration 0063 + 0064 backfill:

```
courses.role_id         — optional FK to roles. NULL for orthogonal
                          courses (electives, fixtures). Backfilled
                          via tier-1 (slug convention) + tier-2
                          (founder-decided tributary mappings).
```

CP1 backfill seeded all 129 existing students at `python_developer`.
CP2 backfill mapped 11 of 12 catalog courses to roles (1 left NULL —
the test fixture). Capstones become visible to gate evaluation via
the courses.role_id JOIN.

## How gate evaluation composes (D-D)

`evaluate_student_against_gate(student_id, target_role_slug)`:

1. Read student's `current_role_id`. Validate adjacency:
   `target.sequence_order == current.sequence_order + 1` (D-A invariant).
2. Read the `role_transitions` row for current → target.
3. Capstone status: query `exercise_submissions JOIN exercises
   (is_capstone) JOIN lessons JOIN courses` filtering by `c.role_id =
   current_role_id`. Normalize integer 0–100 score to float 0.0–1.0
   before threshold comparison. Sort descending; check that the top-N
   meet the threshold.
4. Mock interview status: query `agent_actions WHERE agent_name =
   'mock_interview'` ordered descending by created_at, LIMIT
   `mock_interview_sessions_window`. Filter to sessions whose
   `output_data.session_verdict.transition_target.to_role_slug` matches
   the target. Count those with `passed=True`. Pass iff count >=
   `mock_interview_sessions_required_pass`.
5. Aggregate; produce `gap_summary` for narrative use.

CP4 closed the metadata coupling that CP2 deferred:
`mock_interview` now populates `output_data.session_verdict` with
`transition_target.to_role_slug` + `passed` at session_summary turns
when gate-prep intent was detected. The end-to-end loop closes.

## Locked decisions (D-A through D-G)

- **D-A**: Six sequential roles, no skipping in v1.
- **D-B**: Gate thresholds as tunable JSONB data; admin updates via DB.
- **D-C**: No new agents. Existing agents updated.
- **D-D**: Mock interview multi-dimensional verdict; 2-of-last-3 window.
- **D-E**: Runtime content discovery, never author-time baking.
- **D-F**: Backend-only readiness; UI rendering post-launch.
- **D-G**: `project_evaluator` gate-context awareness via
  `TransitionGateStatus`.

## Implementation surface

- 5 commits across CP1–CP5 (965bf61, f8dd8b6, 742ce4e, 779fb2f,
  162bac7, 77105ed, plus the CP5 closure commit appending this doc).
- 4 new Alembic migrations (0061, 0062, 0063, 0064).
- 3 new tables + 1 column on `courses`.
- 4 net-new universal tools.
- 5 agents prompt-updated + agent-code-extended.
- 2 new schema types: `TransitionGateStatus`, `SessionVerdict`.
- 1 reusable test utility: `runtime_grounding_verifier`.
- ~110 net-new tests across the slice.

## What's NOT in D15 (intentionally)

- Curriculum graph (Pass 3e) — deferred indefinitely.
- `content_ingestion` agent — deferred indefinitely.
- `curriculum_mapper` merge — irrelevant; legacy file deleted in D17.
- Frontend UI rendering — post-launch (D-F).
- Admin UI for tuning gate thresholds — DB-direct in v1.
- Cross-role skip logic — v2 territory (D-A).
- Role transition celebration UX — post-launch frontend.

## Where to read more

- Saved prompt: `docs/claude-code-prompts/d15-prompt.md`.
- CP-by-CP commits: `git log --grep="D15 CP" --oneline`.
- Per-CP verification telemetry: real-LLM phase scripts at
  `backend/scripts/d15_cp{3,4,5}_*.py`.
- Patterns canonical at `docs/followups/migration-verification-discipline.md`
  (Patterns 23-27 added at D15 closure).
