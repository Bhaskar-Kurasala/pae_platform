# D12–D14c Read-Tool Entitlement Leakage Audit

**Provenance.** D15 CP3 resume — Bug 24 follow-on audit.
**Origin.** Bug 24 (commit `779fb2f`) — runtime grounding violation in two
pre-existing read tools (`career_coach/read_capstone_status.py` and
`study_planner/read_active_capstone.py`) that fall through to the most-recently-authored
capstone globally when the calling student has no submissions yet.
**Scope.** Every per-student read tool authored in D12, D13, D14b, D14c
under `backend/app/agents/tools/agent_specific/` (excluding
`tools/universal/`, billing_support's authoritative entitlement readers,
and pure write tools).
**Date.** 2026-05-08.

---

## Top Summary — HIGH severity findings

Two HIGH-severity tools (both already known as **Bug 24**):

1. `career_coach/read_capstone_status.py`
2. `study_planner/read_active_capstone.py`

Both share the same `LEFT JOIN exercise_submissions … ORDER BY ex.created_at DESC LIMIT 1`
fall-through pattern. Both are on the live chat path. **No additional
HIGH-severity instances were found beyond Bug 24.** That keeps CP3 scope
clean — fix the two known offenders and ship.

A close-but-not-HIGH note: `project_evaluator/read_rubric_for_capstone.py`
queries `exercises` with no entitlement filter and no student scoping at
all. It's MEDIUM (the agent treats input `exercise_id` as adversary-controlled
in the dual-rail D-4 contract, and the agent is itself instructor-grading
content; rubric is not PII), but worth treating in D17b.

---

## HIGH severity (fix in CP3 alongside Bug 24)

| Tool | Pattern | Consumer | Rationale |
|---|---|---|---|
| `backend/app/agents/tools/agent_specific/career_coach/read_capstone_status.py` | `FROM exercises ex LEFT JOIN exercise_submissions es ON es.exercise_id = ex.id AND es.student_id = :uid WHERE ex.is_capstone = true ORDER BY es.created_at DESC NULLS LAST, ex.created_at DESC LIMIT 1` | `career_coach_v2.py` (chat path) | Bug 24 origin. LEFT JOIN + global `is_capstone=true` + `ORDER BY ex.created_at DESC` falls through to whichever capstone was authored most recently across the entire content catalog when the student has no submissions — leaking cross-role / non-entitled capstones. |
| `backend/app/agents/tools/agent_specific/study_planner/read_active_capstone.py` | `FROM exercises ex LEFT JOIN exercise_submissions es ON es.exercise_id = ex.id AND es.student_id = :uid WHERE ex.is_capstone = true ORDER BY es.created_at DESC NULLS LAST, ex.created_at DESC LIMIT 1` | `study_planner_v2.py` (chat path) | Sibling of Bug 24 — identical pattern. Same fall-through. Surfaces as study_planner allocating capstone_work blocks against an inaccessible capstone. |

---

## MEDIUM severity (D17b cleanup)

| Tool | Pattern | Consumer | Rationale |
|---|---|---|---|
| `backend/app/agents/tools/agent_specific/project_evaluator/read_rubric_for_capstone.py` | `SELECT e.rubric, e.is_capstone, e.title FROM exercises e WHERE e.id = :exercise_id` | `project_evaluator.py` | No `course_entitlements` filter, no student scoping. Caller passes `exercise_id` derived from a submission (input is `submission_id` first, then derived); but the tool itself returns rubric for any `exercise_id` the agent supplies. Rubric content is instructor-authored, not PII; blast radius is observability/abuse-of-tool-contract, not a student-data leak. Add an entitlement check for hygiene in D17b. |
| `backend/app/agents/tools/agent_specific/project_evaluator/read_capstone_submission_content.py` | `SELECT … FROM exercise_submissions es JOIN exercises e ON es.exercise_id = e.id WHERE es.id = :submission_id` | `project_evaluator.py` | Lookup by `submission_id` only; no `student_id` filter. Returns the submission row including `student_id`. If an attacker can drive the agent to call this with another student's `submission_id`, they get that student's code/feedback. The agent is instructor-context (project_evaluator runs in a grading flow), so blast radius is bounded; but tool should accept and enforce a `student_id` parameter. |
| `backend/app/agents/tools/agent_specific/tailored_resume/lookup_jd_decoded.py` | `SELECT jd_text, jd_parsed FROM tailored_resumes WHERE jd_id = :jd_id LIMIT 1` | `tailored_resume_v2.py` (chat path) | No `user_id`/`student_id` filter — any `jd_id` retrieves the JD payload regardless of owner. JDs are typically not sensitive but `tailored_resumes` rows may include other students' JD context. Add `AND user_id = :uid`. |

---

## LOW severity (document and defer)

| Tool | Pattern | Consumer | Rationale |
|---|---|---|---|
| `backend/app/agents/tools/agent_specific/career_coach/read_goal_contract.py` | `WHERE user_id = :uid AND (expires_at IS NULL OR expires_at > now()) ORDER BY created_at DESC LIMIT 1` | `career_coach_v2.py` | Correctly scoped by `user_id`. No entitlement check needed — goal_contracts are per-user. |
| `backend/app/agents/tools/agent_specific/career_coach/read_mastery_summary.py` | `MemoryStore.recall(user_id=…, agent_name='career_coach', scope='user')` | `career_coach_v2.py` | Reads agent_memory scoped to `(user_id, agent_name, scope)`. Memory primitive enforces the filter. Safe. |
| `backend/app/agents/tools/agent_specific/career_coach/read_student_full_progress.py` | `JOIN enrollments e … WHERE e.student_id = :uid` | `career_coach_v2.py`, `practice_curator.py`, `project_evaluator.py` | `student_id` is in WHERE, joins fan out only across that student's enrollments. Returns aggregates, no cross-student leak. |
| `backend/app/agents/tools/agent_specific/study_planner/read_due_srs_cards.py` | `WHERE user_id = :uid AND next_due_at <= :cutoff` | `study_planner_v2.py` | Scoped correctly. SRS cards are per-user by definition. |
| `backend/app/agents/tools/agent_specific/study_planner/read_goal_contract.py` | Same as career_coach version | `study_planner_v2.py` | Same as career_coach goal_contract — safe. |
| `backend/app/agents/tools/agent_specific/study_planner/read_recent_session_history.py` | `MemoryStore.recall(user_id=…, agent_name='study_planner', scope='user')` | `study_planner_v2.py`, `practice_curator.py` | Memory-primitive scoped. Safe. |
| `backend/app/agents/tools/agent_specific/study_planner/track_adherence.py` | `MemoryStore.write(user_id=…, …)` | `study_planner_v2.py` | Write tool — out of audit scope. Properly scoped. |
| `backend/app/agents/tools/agent_specific/study_planner/commit_plan.py` | `MemoryStore.write/recall(user_id=…, …)` | `study_planner_v2.py` | Write tool — out of audit scope. Properly scoped. |
| `backend/app/agents/tools/agent_specific/resume_reviewer/read_top_exercise_submissions.py` | `JOIN exercises ex ON ex.id = es.exercise_id WHERE es.student_id = :uid AND es.score IS NOT NULL` | `resume_reviewer_v2.py` | INNER JOIN driven by `exercise_submissions.student_id`. No fall-through possible — empty set returns empty result. No global cross-role leak. |
| `backend/app/agents/tools/agent_specific/senior_engineer/lookup_prior_reviews.py` | `MemoryStore.recall(user_id=…, agent_name='senior_engineer', scope='user', mode='structured')` | `senior_engineer.py` | Memory-primitive scoped. Safe. |
| `backend/app/agents/tools/agent_specific/senior_engineer/lookup_prior_submissions.py` | `MemoryStore.recall(user_id=…, agent_name='senior_engineer', scope='user', mode='hybrid')` | `senior_engineer.py` | Memory-primitive scoped. Safe. |
| `backend/app/agents/tools/agent_specific/tailored_resume/lookup_base_resume.py` | `WHERE user_id = :uid ORDER BY updated_at DESC LIMIT 1` | `tailored_resume_v2.py` | Scoped correctly. |
| `backend/app/agents/tools/agent_specific/billing_support/lookup_refund_status.py` | `JOIN orders o ON o.id = r.order_id … WHERE o.user_id = :uid` | `billing_support` | Security gate via orders.user_id JOIN, explicitly documented. Safe. |
| `backend/app/agents/tools/agent_specific/billing_support/escalate_to_human.py` | Write — INSERT into student_inbox with user_id | `billing_support` | Write tool — out of audit scope. |

---

## Sibling note — `resume_reviewer/read_capstones.py`

`backend/app/agents/tools/agent_specific/resume_reviewer/read_capstones.py`
uses **INNER JOIN** on `exercise_submissions`:

```sql
FROM exercises ex
JOIN exercise_submissions es
    ON es.exercise_id = ex.id AND es.student_id = :uid
WHERE ex.is_capstone = true
ORDER BY es.created_at DESC
```

Empty submissions → empty result set, no fall-through. **Safe today.**
However, it still doesn't filter by `course_entitlements` / role
content-mapping. If a student previously submitted to a capstone that
later got reassigned to a different role they're no longer entitled to,
the row would still surface here. Recommend a hygiene pass in D17b to
join through `course_entitlements` for symmetry with the post-CP3
hardened pattern.

---

## Triage

- **HIGH** (CP3, fix alongside Bug 24): the two LEFT-JOIN-fall-through tools
  listed above. Fix is a one-liner each — replace `LEFT JOIN
  exercise_submissions` with an entitlement-gated subquery
  (`exercises ex JOIN course_entitlements ce ON ce.role = exercises_role(ex)
  AND ce.user_id = :uid AND ce.is_active`) plus a `LEFT JOIN
  exercise_submissions` on top, OR keep the LEFT JOIN but require
  `es.id IS NOT NULL` so the global-content fall-through can't fire.
  Final shape to be locked at CP3.

- **MEDIUM** (D17b cleanup, not blocking): 3 tools.
  - `read_rubric_for_capstone.py` — add entitlement filter for hygiene.
  - `read_capstone_submission_content.py` — add `student_id` parameter and
    enforce `WHERE es.student_id = :uid` so the tool can't be tricked into
    returning another student's submission.
  - `lookup_jd_decoded.py` — add `AND user_id = :uid`.

- **LOW** (document, no action): 13 tools all properly scoped. Sibling
  `read_capstones.py` gets an entitlement filter when it's convenient
  (D17b at the latest).

---

## Method

For each `.py` file under `backend/app/agents/tools/agent_specific/`:

1. Read the SQL or memory-primitive call.
2. Check whether `student_id` / `user_id` is in WHERE (load-bearing) vs
   ORDER BY (decorative) vs absent.
3. Check whether `LEFT JOIN` against per-student tables can fall through
   to global rows.
4. Check whether content-table reads (`exercises`, `lessons`, etc.) are
   gated on `course_entitlements` / role mapping.
5. Cross-reference `tool_name` against `backend/app/agents/*.py` to find
   consumer agents.

Excluded per audit prompt: `tools/universal/*`,
`billing_support/lookup_active_entitlements.py`,
`billing_support/lookup_order_history.py`, `sandbox/*` (no per-student
data — they execute code), pure write tools beyond noting their scope.
