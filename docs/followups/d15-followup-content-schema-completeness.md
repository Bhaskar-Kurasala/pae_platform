# D15 follow-up — content_schema_completeness state on dev DB

**Status:** Open. Tracking content authoring effort, not a bug.
**Created:** 2026-05-08 (D15 CP5 closure).

## What this is

`read_student_accessible_content` returns a `content_schema_completeness`
flag with three values: `complete` | `partial` | `minimal`.

CP3 + CP5 verification confirmed that all five updated agents handle
`partial` and `minimal` gracefully — no fabrication, honest
acknowledgement of what's missing. CP3 + CP5 phases observed `partial`
as the dominant state across every fixture × role combination.

This doc records the **content state at D15 ship** so future authoring
effort has a baseline.

## Dev DB content state at 2026-05-08

| Surface | State | Detail |
|---|---|---|
| `courses` | 12 rows | 5 role-named (python-developer, data-analyst, data-scientist, ml-engineer, genai-engineer); 7 tributary (incl. d12-smoke-course as test fixture). 11 of 12 mapped to roles via CP2b backfill. |
| `lessons` | non-empty | Inherits role transitively via course_id → courses.role_id. |
| `exercises` | 41 rows | All 41 sit under TRIBUTARY courses (python-foundations: 32, intro-ai-engineering: 8, production-rag: 1). **Zero exercises under role-named courses.** |
| `lesson_resources` (notebooks) | **0 rows** | The notebook surface is vacuous. Every agent's `accessible_notebooks` query returns empty. |
| Capstones (`exercises.is_capstone=TRUE`) | 3 rows | python-foundations: 1 ("CLI AI tool", no rubric). intro-ai-engineering: 2 ("D12 CP3 RAG Capstone", "D14c CP3 Phase 2: Multi-Agent Eval Harness", both have rubrics). |

### What "partial" means in practice

Every entitled student sees:
- 1+ `accessible_courses` (their entitled courses).
- N `accessible_curated_problems` for whichever tributary courses
  they're entitled to (32 for python-foundations entitled,
  0 for role-named-only entitled).
- **0 `accessible_notebooks`** universally.

The completeness logic treats this as `partial` (course present;
problems possibly present; notebooks empty). `minimal` only fires when
the student has no course entitlements at all OR the role_slug filter
excludes every entitled course.

## What "complete" would require

1. Authored `lesson_resources` rows for at least one course per role.
2. Curated exercises tagged to role-named courses (currently exercises
   only sit under tributary courses; rebalancing or copy/migration
   would be needed).

This is content-authoring effort, not a code or schema task. The
agents are ready to ground in the content the moment it's authored.

## Trigger to revisit

When notebook authoring effort kicks off OR exercises migrate from
tributary to role-named courses. Update this doc with the new
completeness ratios.

## Cross-references

- `docs/followups/d15-cp2-content-role-mapping-audit.md` — CP2 audit
  that captured the topology (audited at D15 ship; this doc tracks
  evolution).
- `read_student_accessible_content.py` — `_classify_completeness`
  helper (the function that applies the partial/minimal/complete
  rules).
- `migration 0064_courses_role_backfill.py` — CP2b tier-2 mappings
  that decided which tributary courses belong to which role.
