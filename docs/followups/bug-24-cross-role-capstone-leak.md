# Bug 24 — cross-role capstone leak in read_capstone_status / read_active_capstone

**Status:** Open. **Founder decision required: scope-fix-into-CP3 vs defer to D15.5.**
**Created:** 2026-05-08 (D15 CP3 verification).
**Severity:** Runtime grounding violation (D-E discipline). Surfaced in 3 of 4
CP3 real-LLM phases.
**Cross-references:**
- D15 prompt's CP3 hard stop ("career_coach FABRICATES content … STOP")
- D15 CP2 audit `d15-cp2-content-role-mapping-audit.md` (the schema enabling
  the fix)
- D14c follow-up `migration-verification-discipline.md` Pattern 22

## What surfaced

CP3 Phase 1 (career_coach, fresh python_developer):
> **Suggested next action**: "Submit the D14c CP3 Phase 2 capstone — it's
> your highest-leverage blocker and the only gate item you can move today."
>
> **immediate_concerns[1]**: "No capstone submitted — your only assigned
> capstone (D14c Multi-Agent Eval Harness) is unsubmitted and is the
> blocking deliverable for your first gate"

The python_developer fixture is entitled to the `python-developer` course
ONLY (which has 0 exercises, 0 capstones). The capstone the LLM was told
to submit (`D14c CP3 Phase 2: Multi-Agent Eval Harness`) lives under
`intro-ai-engineering`, which CP2b mapped to `genai_engineer`. The student
has no entitlement to it AND it's tagged for a role 4 transitions away.

CP3 Phase 2 (career_coach, mid-progression data_scientist):
> **headline**: "Data Scientist 30 days in with an unsubmitted capstone
> blocking the ml_engineer gate — submit it first."
>
> **current_state_assessment**: "You've been in the Data Scientist role for
> 30 days and haven't yet submitted your capstone (D14c CP3 Phase 2:
> Multi-Agent Eval Harness)…"

Same fabrication. The data_scientist student has 0 capstones for their
current role (data-scientist course has 0 capstones on dev DB). The LLM
was again told the genai_engineer capstone is the blocker.

CP3 Phase 3 (study_planner, data_analyst weekly plan):
> **Mon 120min Capstone Progress** → "D14c CP3 Phase 2: Multi-Agent Eval
> Harness — start or continue implementation toward submission (8 hrs
> remaining)"
>
> **Wed 120min Capstone Progress** → "D14c CP3 Phase 2: continue eval
> harness work; aim to complete at least 1 major section"

Same fabrication. The data_analyst student is entitled only to
`data-analyst` (0 capstones); the plan tells them to spend 4 hours/week
on a capstone for a different role under a different course.

CP3 Phase 4 (study_planner, urgency override): **clean** — the
session_plan path uses `accessible_content` more directly and didn't
fabricate. Phase 4 also benefited from urgency context reshaping the
prompt away from "what's your active capstone" framing.

## Root cause

Both tools have the same SQL shape (D12 era, pre-D15 CP2b):

```python
# backend/app/agents/tools/agent_specific/career_coach/read_capstone_status.py
# backend/app/agents/tools/agent_specific/study_planner/read_active_capstone.py
SELECT ex.id, ex.title, (es.id IS NOT NULL) AS submitted, es.score
FROM exercises ex
LEFT JOIN exercise_submissions es
    ON es.exercise_id = ex.id AND es.student_id = :uid
WHERE ex.is_capstone = true
ORDER BY es.created_at DESC NULLS LAST, ex.created_at DESC
LIMIT 1
```

**The `LEFT JOIN` is the load-bearing problem.** When the student has
submitted nothing, the join produces a row for EVERY capstone in
`exercises` and the `ORDER BY ... ex.created_at DESC LIMIT 1` returns
the most-recently authored capstone globally — regardless of:

- Whether the student has a course_entitlements row that grants access
  to the course containing the capstone.
- Whether the capstone's parent course's `role_id` matches the
  student's current role.

On dev DB, the most recently created capstone is
`D14c CP3 Phase 2: Multi-Agent Eval Harness` under
`intro-ai-engineering` (genai_engineer). So every student without
submissions sees that capstone as their "active" one.

This was always wrong — it predates D15 and would also have surfaced for
any pre-D15 user who hadn't started any capstone work. The reason it
didn't surface earlier is that D12-D14c real-LLM verification used a
seeded test user (`d12_cp3_smoke@example.com`) who already had
submissions, so `LEFT JOIN` returned the joined-submission row, not the
unsubmitted-capstone row.

D15 CP3 surfaces it because the new fixtures explicitly seed students at
specific role states with NO submissions yet — which is the production-
realistic state the founder wanted CP3 to verify against.

## Sibling tool not affected

`resume_reviewer.read_capstones` uses an INNER JOIN against
`exercise_submissions` — it only returns capstones the student has
actually submitted. Safe by accident; should still get a role/entitlement
filter for hygiene.

## Why this is Bug 24 (new) and not an existing class

The 1-23 history covers prompt/parser/contract/tooling-protocol bugs.
This is the first surfaced case of a **read tool returning data the
student doesn't have access to**, AND the first case where the role-
filtering invariant introduced by D15 CP2b creates an obvious correctness
expectation that the legacy tool can't honor.

D-E (runtime content discovery, not author-time baking) is the exact
discipline this violates. The agent didn't fabricate text — but it was
fed fabricated context by a tool whose contract didn't account for
role/entitlement filtering.

## Three options for the founder

### Option 1 — Fix in CP3 (scope creep into CP3, ~1.5h)

Add an entitlement + role filter to both tools:

```sql
SELECT ex.id, ex.title, (es.id IS NOT NULL) AS submitted, es.score, c.role_id
FROM exercises ex
JOIN lessons l ON l.id = ex.lesson_id
JOIN courses c ON c.id = l.course_id
JOIN course_entitlements ce
    ON ce.user_id = :uid
    AND ce.course_id = c.id
    AND ce.revoked_at IS NULL
    AND (ce.expires_at IS NULL OR ce.expires_at > now())
LEFT JOIN exercise_submissions es
    ON es.exercise_id = ex.id AND es.student_id = :uid
LEFT JOIN student_role_state srs ON srs.student_id = :uid
WHERE ex.is_capstone = true
  AND (c.role_id IS NULL OR c.role_id = srs.current_role_id)
ORDER BY es.created_at DESC NULLS LAST, ex.created_at DESC
LIMIT 1
```

Filter rule: only show capstones the student is entitled to AND that
either belong to their current role OR are role-agnostic (NULL role_id).
This keeps tributary-but-unmapped capstones discoverable while
blocking cross-role leakage.

Re-run CP3 phases against the fix. Cost: another ~₹0.50 in real-LLM
runs.

**Pros:** CP3 verification lands clean; D-E invariant preserved;
no follow-up debt.
**Cons:** scope creep — was supposed to be a prompt-update CP, now
includes tool-SQL changes. Adds ~1.5h.

### Option 2 — Ship CP3 with a known limitation; fix in D15.5

Flag the limitation in the CP3 closure report, document Bug 24 here,
proceed to CP4 + CP5. Author a CP15.5 (or similar) follow-up after
D15 closes that lands the fix + verification.

**Pros:** CP3 stays narrow as designed; D15 closes faster.
**Cons:** D-E invariant violated for production users until D15.5
ships; CP3 verification phases are honestly only "passing" if we
discount the fabrication; CP4 verification would also surface the
issue.

### Option 3 — Fix in CP3 AND replace these tools' role with the D15
read_student_accessible_content / evaluate_student_against_gate
combo (the cleaner architecture, ~3-4h)

Drop `read_capstone_status` and `read_active_capstone` from
career_coach + study_planner. Replace with the D15 universal tools:

- `evaluate_student_against_gate` already returns
  `capstone_status.best_score_observed` + `capstones_meeting_threshold`
  — exactly the data career_coach needs for gate framing.
- `read_student_accessible_content` returns `accessible_curated_problems`
  with `is_capstone` flag — which is a strict superset of what
  `read_active_capstone` returned.

The legacy tools become unused for these agents; `resume_reviewer`
keeps `read_capstones` (still safe) and one of these two stays as
dead code or gets retired.

**Pros:** consolidates around the D15 architecture; eliminates the
buggy tools entirely; aligns with D-E by design.
**Cons:** more code change; touches more agent paths; needs a
migration story for tool retirement.

## Recommendation

**Option 1** for CP3 closure: minimal SQL change to both tools, re-run
the four real-LLM phases, ship CP3 clean. The Option 3 architectural
consolidation is the right long-term call and should be a D15.5 or
post-D15 follow-up — but doing it inside CP3 doubles the scope and
risks tail latency on tool surface changes that other agents depend on.

If the founder accepts the limitation as known and wants to ship CP3
narrow, Option 2 works — the workaround is "every student gets told
their capstone is D14c Multi-Agent Eval Harness," which is wrong but
recoverable once the fix lands.

## CP3 verification status

Without a decision, CP3 phases technically COMPLETED with status=ok and
the harness reported zero findings (the heuristic detect_fabrication
checked for "Production RAG" / "MLOps" / generic content — it missed
the actual fabrication because the LLM grounded in tool output that
LOOKED like real capstone titles). The verification's heuristic was
too narrow.

Phase 4 (study_planner urgency override) is unaffected and lands
clean. Phase 1, 2, 3 all surface the fabrication.

## What I am NOT doing without founder approval

- NOT modifying read_capstone_status or read_active_capstone SQL
- NOT re-running the CP3 phases
- NOT marking CP3 verification as passing

Standing by for Option 1 / 2 / 3 decision.
