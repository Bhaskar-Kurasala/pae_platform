# D15 CP2 — entitlements ↔ content ↔ role mapping audit

**Status:** Open. **Founder decision required before CP2 tool authoring proceeds.**
**Created:** 2026-05-08 (D15 CP2 entry).
**Severity:** Bug-24-class (architectural finding, not a bug). Per the D15
prompt hard stop: *"Audit reveals partial role↔content mapping: STOP and
surface; founder decides which content types D15 v1 supports vs. which
are deferred."*

**Cross-references:**
- D15 prompt at `docs/claude-code-prompts/d15-prompt.md` (CP2 spec)
- `migration-verification-discipline.md` Pattern 22 (spec-vs-schema reconciliation)
- D14c `read_capstone_submission_content.py` (canonical content-tool pattern)
- D10 `lookup_active_entitlements.py` (canonical entitlements-query pattern)

## TL;DR

The audit's outcome is **PARTIAL**, not Clean and not Missing.

- Entitlements layer is **clean** — `course_entitlements` cleanly answers
  "which courses does student X have access to."
- Course → role mapping is **derivable by slug convention but incomplete** —
  6 of 6 role slugs have a same-named course; 5 of 12 catalog courses have
  no role-slug match.
- Lesson → role mapping is **transitive only** (lesson belongs to a course
  that may match a role slug; no `role_id` column anywhere).
- Exercise → role mapping is **broken in practice** — exercises live under
  tributary courses whose slugs do NOT match role slugs. The role-named
  courses currently have **zero exercises**.
- Notebook → role mapping is **vacuous** — `lesson_resources` table has
  zero rows on dev DB.
- Capstone → role mapping is **broken in practice** — 3 capstones exist
  on the platform, all live under tributary courses (`python-foundations`
  and `intro-ai-engineering`); zero capstones live under role-named courses.
- The legacy `users.promoted_to_role` shadow column is unrelated and
  tracked separately at `d15-followup-legacy-promoted-role-reconciliation.md`.

This means `read_student_accessible_content` cannot be authored as-spec'd
without making one of three product decisions (see "Three options" below).

## Schema topology — what actually exists

### Tables with declared role linkage

```
roles                   — six role identities (D15 CP1, just shipped)
role_transitions        — five gate definitions (D15 CP1, just shipped)
student_role_state      — one row per student (D15 CP1, just shipped, 129 rows)
```

These are clean. No drift between model and DB.

### Tables involved in content discovery — declared FK shapes

```
courses
  id (PK), slug (UNIQUE), title, description, price_cents, is_published,
  difficulty, metadata::jsonb (free-form catalog dict)
  — NO role_id, NO role_slug, NO role-tagged metadata key.

course_bundles
  id, slug (UNIQUE), title, course_ids::json (list of course-id strings),
  metadata::json
  — NO role linkage.

course_entitlements
  id, user_id → users.id, course_id → courses.id,
  source ('purchase'|'free'|'bundle'|'admin_grant'|'trial'),
  granted_at, revoked_at, expires_at
  — Authoritative "what does student X have access to right now." Clean.

lessons
  id (PK), course_id → courses.id (CASCADE), title, slug, order,
  is_published, skill_id → skills.id (SET NULL, NULLABLE)
  — NO role_id. Inherits role from parent course IF course is role-named.

lesson_resources
  id, course_id, lesson_id (NULLABLE), kind (str), title, path, url,
  is_required
  — NO role_id. The "notebook" surface in spirit; empty on dev DB.

exercises
  id (PK), lesson_id → lessons.id (CASCADE), title, exercise_type,
  difficulty, is_capstone (bool, ✓ as D15 CP2 expects),
  pass_score (int, default 70), skill_id → skills.id (SET NULL)
  — NO role_id. Inherits role transitively via lesson → course IF
    course is role-named. is_capstone flag IS present per spec.

exercise_submissions
  id, student_id → users.id, exercise_id → exercises.id,
  score (int), status, ai_feedback::json, code, github_pr_url,
  self_explanation
  — Project_evaluator's output lands in ai_feedback (D14c). Clean.

skills
  id, slug (UNIQUE), name, difficulty (1-5)
  — Atomic concept tags (Docker, FastAPI, LangGraph, etc.). NOT roles.
    43 skills seeded.

concepts (curriculum graph from D9 / 0056_curriculum_graph.py)
  — Empty schema; D15 reframe explicitly defers curriculum graph
    indefinitely (out of scope per prompt). Ignore.
```

### Live data on dev DB (`pae_platform-db-1`, 2026-05-08)

```
courses (12 published except d12-smoke-course):
  agent-orchestration-langgraph    (tributary)
  d12-smoke-course                 (test fixture)
  data-analyst                     (matches role slug data_analyst)
  data-analyst-path                (tributary; sibling to data-analyst)
  data-scientist                   (matches role slug data_scientist)
  genai-engineer                   (matches role slug genai_engineer)
  intro-ai-engineering             (tributary; holds 8 exercises + 2 capstones)
  llm-evaluation                   (tributary)
  ml-engineer                      (matches role slug ml_engineer)
  production-rag                   (tributary; holds 1 exercise)
  python-developer                 (matches role slug python_developer)
  python-foundations               (tributary; holds 32 exercises + 1 capstone)

course_bundles:
  data-career-arc, ai-engineer-arc

active entitlements (revoked_at IS NULL):
  data-scientist: 3, python-developer: 3, data-analyst: 3,
  genai-engineer: 2, production-rag: 2, llm-evaluation: 1,
  ml-engineer: 1, agent-orchestration-langgraph: 1, d12-smoke-course: 1.

lessons:                     [count not enumerated; non-empty]
lesson_resources:            0 rows  ← VACUOUS
exercises:                   41 rows total
  python-foundations:           32 exercises, 1 capstone
  intro-ai-engineering:          8 exercises, 2 capstones
  production-rag:                1 exercise,  0 capstones
  (all OTHER courses, including all 6 role-named courses): 0 exercises
exercises with skill_id populated: 0 / 41
```

## Mapping topology — content-type by content-type

### Course → role: derivable by slug convention, INCOMPLETE

Of 12 courses on dev DB:

```
ROLE-NAMED (6 of 12):
  python-developer    → role.slug python_developer       ✓
  data-analyst        → role.slug data_analyst           ✓
  data-scientist      → role.slug data_scientist         ✓
  ml-engineer         → role.slug ml_engineer            ✓
  genai-engineer      → role.slug genai_engineer         ✓
  (no course matches  ← role.slug senior_genai_engineer)

TRIBUTARY (no role match):
  python-foundations           — duplicate of python-developer's metadata
  intro-ai-engineering         — pre-progression onboarding?
  llm-evaluation               — topic-specific course
  production-rag               — topic-specific course
  agent-orchestration-langgraph — topic-specific course
  data-analyst-path            — sibling/alias of data-analyst?
  d12-smoke-course             — test fixture (is_published=false)
```

Two product realities surface:

- **No course exists for `senior_genai_engineer`.** The terminal role has
  no published course; D15 prompt's role identity statement says this
  level is "no longer to build the system; it's to decide what gets built"
  — consistent with the absence of a course.
- **5 of 12 courses don't map to any role.** They cover concepts
  orthogonal to the linear progression (RAG, evals, agents) — useful but
  not slotted into the six-role spine.

### Lesson → role: transitive via course, INCOMPLETE

Lessons inherit role IFF their parent course matches a role slug.
For tributary courses, lessons have no role.

### Exercise → role: BROKEN IN PRACTICE

The role-named courses have **zero exercises** in the live DB.
All 41 exercises live under tributary courses.

This is the load-bearing finding: an agent calling
`read_student_accessible_content(student_id, role_slug='data_analyst')`
expecting a list of role-tagged practice problems would receive **zero
results from the role-named course**, even when the student is fully
entitled and lessons exist.

The spec's `accessible_curated_problems` field has nothing to populate.
Falling back to D14b generative behavior (per D-E) is the only viable
path for v1.

### Notebook → role: VACUOUS

`lesson_resources` table has zero rows on dev DB. The "notebook"
content surface as architected has no published rows. Either:

- Notebooks haven't been authored yet, OR
- "Notebooks" lives elsewhere (course `description` markdown?
  `lesson.content` markdown? lesson `youtube_video_id`?), OR
- The platform doesn't actually have a notebook content surface yet
  beyond chat-bookmarks (`notebook_entries`, which are user-authored,
  not platform-published).

The D15 prompt's references to "the curated problems for your current
role" and "accessible_notebooks list" assume a published bank that
doesn't exist yet on dev DB.

### Capstone → role: BROKEN IN PRACTICE

3 capstones exist:

```
python-foundations          — 1 capstone
intro-ai-engineering        — 2 capstones
```

All live under tributary courses. The role transition gate
(`role_transitions.capstone_threshold`) expects to evaluate against
capstones for the student's CURRENT role. But there is no capstone
under `data-analyst`, `data-scientist`, `ml-engineer`, or any
role-named course.

`evaluate_student_against_gate` would correctly report `gate_passable=
False` for every student (no qualifying capstones exist for any
role-named course), even when a student has clearly worked through
substantial platform content — because that content lived under
tributary courses, not the role-named one.

## Three options for the founder

### Option 1 — Slug-convention mapping with explicit fallback (LOWEST RISK, fastest)

Author `read_student_accessible_content` to use slug convention:

- Course is "role-tagged" iff `course.slug.replace('-','_') == role.slug`.
- Lessons + exercises inherit role from their course transitively.
- Notebooks: omit the field from output v1 (return `None`, signaling
  agents to fall back to role-identity-only reasoning per D-E spec).
- `content_schema_completeness` flag returns:
  - `"complete"` — student has accessible role-tagged courses with
    non-zero published lessons AND non-zero exercises.
  - `"partial"` — student has accessible role-tagged courses with
    lessons but no exercises (= the current state for most role-named
    courses on dev DB).
  - `"minimal"` — student has zero accessible role-tagged content for
    the requested role.

Tributary courses are reported under `accessible_courses` but with
`role_slug=None` so agents understand they're orthogonal.

**Pros:** Implementable today with zero schema change. Honors D-E
runtime grounding. Agents handle empty banks gracefully (CP3-CP4
prompt updates already plan for this per D-E spec).

**Cons:** Convention-based mapping is fragile — a future course slug
rename silently de-tags content. Capstones under tributary courses
(the 3 that exist!) are invisible to gate evaluation; gate would
report False for everyone, breaking CP4 verification meaningfully.

### Option 2 — Add `role_id` column to courses (CORRECT BUT LARGER)

Schema change (separate Alembic migration):

- ALTER TABLE courses ADD COLUMN role_id UUID NULL REFERENCES roles(id);
- Backfill: for each role-named course, set role_id to matching role.
- For tributary courses, role_id stays NULL.
- For capstones in tributary courses, founder authors a one-time
  decision: `intro-ai-engineering` capstones map to which role?
  `python-foundations` capstone → python_developer? Author the
  decision as a data migration.

**Pros:** Authoritative role tag at the right grain. No reliance on
slug conventions. Tributary courses get explicit "no role" semantics
(NULL role_id). Capstones become discoverable for gate evaluation.

**Cons:** ~3-5 hours of schema + data work; founder must decide
tributary-course role mappings (judgment calls); no immediate
exercise/lesson role tagging beyond transitive inheritance from
course.

### Option 3 — Defer `read_student_accessible_content` entirely; ship D15 v1 without it (NARROWEST SCOPE)

CP2 ships only `read_student_role_state` and `evaluate_student_
against_gate` (the latter against `is_capstone` flag without role
filtering — accept that gate evaluation in v1 is approximate).

`read_student_accessible_content` is deferred to a D15.5 follow-up
once content authoring catches up (capstones under role-named
courses, populated `lesson_resources`).

CP3-CP4 agent prompts update to reference content "abstractly"
(per D-E spec) without ever needing to ground in
runtime-discovered specifics. The agents read role identity from
`student_role_state`, frame work in role-relative terms, and
explicitly acknowledge to the student that the curated bank is
still being authored.

**Pros:** Smallest change set. Avoids fabricating SQL on top of
schema that doesn't support the spec. CP3-CP4 work proceeds with
clean role-aware prompts grounded in identity statements alone.

**Cons:** Loses the runtime content discovery story for v1. The
D-E discipline becomes "agents reason in role-identity terms" only,
which is a weaker version of the spec.

## Recommendation

**Option 1 (slug-convention mapping with `content_schema_
completeness` flag)** is the lowest-risk path that preserves the
D15 prompt's runtime-grounding discipline. The `completeness` flag
honestly signals what's missing; agents handle `partial`/`minimal`
without fabricating per D-E. Capstones under tributary courses
remain a gap, but that's a content-authoring problem, not a tool
problem.

If the founder wants gate evaluation to actually work in CP4
verification (i.e., a seeded test student passes the python_developer
→ data_analyst gate end-to-end), **Option 2** is required because
the only existing capstones live under tributary courses. Without
role-tagging those capstones, gate evaluation will return False for
every student in every test.

If the founder accepts that D15 ships role-aware voice + identity
grounding only, with content discovery deferred, **Option 3** is
acceptable — it's the smallest change set and unblocks CP3-CP4
work fastest.

## What CP2 needs from the founder

A choice among Options 1 / 2 / 3 (or a hybrid).

If 1: I proceed to author `read_student_accessible_content` with
slug-convention mapping + completeness flag, ship all three tools,
finish CP2.

If 2: I author a CP2.5 schema migration to add `courses.role_id`,
backfill from role-name courses + founder-authored tributary
mappings, then resume CP2 tool authoring. Adds ~half a day to D15
timeline.

If 3: I ship CP2 with two tools (`read_student_role_state` +
`evaluate_student_against_gate`), defer
`read_student_accessible_content` to a follow-up, and rewrite
CP3-CP4 prompt update specs to drop content-grounding language.

Standing by.
