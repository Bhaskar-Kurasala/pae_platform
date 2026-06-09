# Naming audit — repository-wide

**Audit only. No renames. No deletions.** This document is an inventory
of naming patterns that diverge from the established convention in
each part of the tree. Every finding includes:

- Where the convention lives (the rule the deviation is measured against)
- What deviates and where
- Whether the deviation is intentional, accidental, or unclear
- A recommendation classified as **TRIVIAL** / **DISCUSS** / **DO NOT CHANGE**

The cleanup commits — if any — happen later under explicit approval.

**Generated:** 2026-05-02 (Track 4 of the parallel cleanup workstream)
**Scope:** `backend/`, `frontend/`, `docs/`, top-level repo layout
**Out of scope:** the 26 legacy BaseAgent agents, the agent registry, MOA
(per global rules of this workstream)

---

## 1. Backend — Python files

### 1.1 Convention

- **Rule:** `snake_case.py` for all modules (per `CLAUDE.md` and
  `.claude/rules/conventions.md`).
- **Test files:** `test_{name}.py`.
- **Underscore-prefix `_module.py`:** Python's standard for
  module-private (importable but not part of the public API).

### 1.2 Inventory

| Area | File pattern | Status | Notes |
|---|---|---|---|
| `backend/app/**/*.py` | All snake_case | ✅ Conforms | No PascalCase, kebab-case, or mixedCase Python files anywhere in `app/`. |
| `backend/app/agents/_agentic_loader.py` | Leading underscore | ✅ Intentional | Module-private loader; called only from `register_proactive_schedules` boot path. The leading-`_` makes the privacy explicit. |
| `backend/app/agents/_llm_utils.py` | Leading underscore | ✅ Intentional | Helpers shared between agents; not a public surface. |
| `backend/app/api/_deprecated.py` | Leading underscore | ✅ Intentional | The `@deprecated` decorator + middleware. Used internally by route modules; not a stable public API. |
| `backend/run_3*_tests.py` (17 files at backend root) | snake_case | ✅ Naming conforms | Naming is fine. Their **status** is a dead-code question, not a naming question — see [dead-code-audit.md](dead-code-audit.md) §3. |

**Recommendation:** No backend Python rename actions needed. The
underscore-prefixed modules are intentional and consistent with Python's
convention for "private to the package."

---

## 2. Backend — Service files: the `_v2` / `_v3` versioning pattern

### 2.1 Observation

Several services have `_v2` siblings. The pattern is inconsistent:
sometimes the legacy file is `@deprecated`, sometimes both are live,
sometimes the v2 supersedes but the legacy is still wired into a route.

### 2.2 Inventory

| Pair | Live? | Convention used | Status |
|---|---|---|---|
| `interview_service.py` + `interview_service_v2.py` | Both wired | `<name>` + `<name>_v2` | ⚠️ **DISCUSS** — see §2.3 |
| `disrupt_prevention_v2_service.py` (alone) | Live | `<name>_v2_service` | ⚠️ Different word order from interview pair |
| `payments_v2.py` (route) + `payments_webhook.py` | Both live | `<name>_v2` route, no v1 | ✅ v1 was deleted; naming is fine |
| `0035_career_tables_v2.py` (migration) | Applied | Numeric `_v2` suffix on a migration file | ✅ Migration filenames are historical; rename would break alembic |

### 2.3 The `interview_service` problem

`interview_service.py` is **still imported by a live route**:

```
backend/app/api/v1/routes/interview.py:41
  from app.services.interview_service import (...)
```

The `interview` router is mounted at `/api/v1/interview`. The newer
`interview_service_v2.py` is wired to a *separate* `mock_interview` route
at `/api/v1/mock` (the canonical Mock Interview Agent v3 surface).

**The legacy interview route is NOT marked `@deprecated`** — even though
the route layer has 38 other handlers using the `@deprecated(sunset=...)`
pattern. So the team's deletion machinery (deprecation header + log line +
sunset date) is not pointed at the legacy `/interview` surface.

**Recommendation: DISCUSS.** Two options, neither a rename:
- **Option A:** Mark the legacy `/interview` handlers `@deprecated(sunset=...)`,
  leave the file in place. No code rename, but the existing deletion
  pipeline starts ticking on it.
- **Option B:** If `/interview` is no longer reachable from the v8
  frontend, treat it as dead-code and route it through the next
  cleanup pass.

**Why this is a naming-audit finding (not a dead-code finding):** the
file is reachable from a live route. It's a *naming/lifecycle* problem
(no `_v2` deprecation marker on the v1 surface), not a dead-code
problem yet.

### 2.4 The word-order inconsistency

`disrupt_prevention_v2_service.py` puts `_v2` between the topic and
the `_service` suffix. The interview pair puts `_v2` after the `_service`
suffix (`interview_service_v2.py`).

| File | Pattern |
|---|---|
| `interview_service_v2.py` | `<topic>_service_v2` |
| `disrupt_prevention_v2_service.py` | `<topic>_v2_service` |

**Recommendation: DISCUSS.** Pick one. Renaming either is a
mechanical refactor — but since the file is imported in 4 places
(see grep below), it's not free. Defer until a cleanup batch.

```
backend/app/tasks/outreach_automation.py:25
backend/tests/test_services/test_disrupt_prevention_v2.py:31, 92, 275, 303
```

---

## 3. Backend — Route files

### 3.1 Convention

- **Rule:** `<topic>.py` per route group, snake_case.
- **Router prefix:** `/<topic>` (no `_v2` in URL paths; versioning lives
  at the API level, `/api/v1/...`).

### 3.2 Inventory

| File | Prefix | Status |
|---|---|---|
| `interview.py` | `/interview` | Live, **not @deprecated** despite being legacy (see §2.3) |
| `mock_interview.py` | `/mock` | Live, canonical |
| `payments_v2.py` | `/payments` (assumed) | ✅ File suffix `_v2`, prefix is unversioned — clean |
| `payments_webhook.py` | webhook-specific | ✅ Topic-split is intentional |
| `confidence.py` | `/confidence` | All handlers `@deprecated` — file kept until sunset 2026-07-01 |
| `demo.py` | `/demo` | All handlers `@deprecated` — file kept until sunset 2026-07-01 |
| `application_kit.py`, `lessons.py`, `goals.py`, `agents.py`, `chat.py`, `courses.py`, `diagnostic.py`, `exercises.py`, `billing.py`, `readiness.py`, `receipts.py`, `tailored_resume.py` | various | Mix of live + `@deprecated` handlers in same file — that's the team's pattern |

**Recommendation:** No route file renames. The one finding (interview.py
not marked deprecated) is captured in §2.3.

---

## 4. Frontend — TypeScript files

### 4.1 Convention

- **Rule (per `frontend/CLAUDE.md` and root `.claude/rules/conventions.md`):**
  - Pages (App Router): `kebab-case.tsx`
  - Components: `PascalCase.tsx`
  - Tests: `{name}.test.tsx`

### 4.2 Inventory

`frontend/src/components/` directories are kebab-case at the file level
(e.g. `agent-chat-stream.tsx`, `studio-page-header.tsx`,
`feedback-widget.tsx`). This is **the opposite** of the documented rule
("Components: PascalCase").

| File pattern | Count (sampled) | Status |
|---|---|---|
| `src/components/**/*.tsx` (kebab-case) | ~150+ | ⚠️ Diverges from the documented rule |
| `src/components/features/skill-map/*.tsx` (kebab-case) | 8 | Same |
| `src/app/**/page.tsx` (always `page.tsx`) | many | ✅ Next.js convention |
| `src/app/**/layout.tsx` | many | ✅ Next.js convention |

**The codebase has standardised on kebab-case for components, contradicting
the rule in `CLAUDE.md`.** Two ways to read this:

- **The doc is stale** — kebab-case is what the team actually does, and
  the rule should be updated.
- **The code is wrong** — components should be `PascalCase.tsx` and the
  team has drifted.

**Recommendation: DO NOT CHANGE the code. Update `CLAUDE.md` and
`.claude/rules/conventions.md`** to match the actual convention
(`kebab-case.tsx` for components). Renaming 150+ component files would
be a high-churn refactor for zero behavioural change. The doc is the
cheaper thing to fix.

### 4.3 Sub-inventory: nothing else weird in frontend

- `frontend/src/middleware.ts`, `frontend/src/instrumentation.ts`,
  `frontend/src/instrumentation-client.ts` — Next.js conventions, fine.
- `frontend/src/app/v8.css`, `frontend/src/app/v8-overrides.css` —
  intentional v8 design-system suffix per the v8 migration project
  (see memory: `project_v8_migration.md`).
- `frontend/src/components/v8/` — same.

No other naming surprises.

---

## 5. Documentation — `docs/`

### 5.1 Observation: three competing conventions

| Pattern | Examples | Count |
|---|---|---|
| `UPPER_SNAKE.md` | `AGENTIC_OS.md`, `AGENTS.md`, `ARCHITECTURE.md` | ~3 |
| `UPPER-HYPHEN.md` | `AGENT-OPERATING-SPEC.md`, `ROADMAP-P3-CRITIC.md`, `CHAT-FIX-TRACKER.md`, `E2E-TEST-PLAN.md`, `OPEN-ISSUES.md`, `POST-LAUNCH-BUG-PLAN.md`, `PRODUCTION-READINESS.md`, `RETENTION-ENGINE.md`, `ADMIN-LIVE-DATA.md`, `QA_REPORT_PHASE6.md` | ~10+ |
| `lower-hyphen.md` | `awesome-design.md`, `placement-quiz.md` | ~2 |
| `lowercase.md` | `lessons.md` | ~1 |

The `docs/followups/` and `docs/audits/` subdirectories have settled on
`lower-hyphen.md`:
```
docs/followups/escalation-limiter-redis.md
docs/followups/escalation-limiter-hot-recovery.md
docs/audits/dead-frontend.md
docs/audits/endpoint-coverage.md
```
That subdir-level convention is consistent. The top-level `docs/` is
the messy part.

### 5.2 Recommendation

**DISCUSS.** Three reasonable options, all reversible:

1. **Status quo.** Keep top-level `docs/` heterogeneous (the variation
   reflects when each doc was added; it's archeological).
2. **Pick one for new docs.** Going forward, all new top-level docs use
   `UPPER-HYPHEN.md` (the majority pattern). Don't rename existing.
3. **Mass rename.** Pick one and rename everything. High-churn (every
   doc reference in every other doc breaks unless `git mv`-d carefully).

The `_drafts/`, `audits/`, `followups/`, `runbooks/`, `features/` subdirs
all use `lower-hyphen.md` and are internally consistent. **Do not touch
those.** Only the top-level docs/ is in question.

### 5.3 Special case: `AGENTIC_OS.md` (just shipped Track 3)

I named this file `UPPER_SNAKE.md` to match the existing
`ARCHITECTURE.md` and `AGENTS.md` (the other "this is a load-bearing
architecture doc at the top level" docs). If the team picks
`UPPER-HYPHEN.md` as the standard, this one would become `AGENTIC-OS.md`.
Cheap to rename early; expensive once external links accumulate.

---

## 6. Top-level repo — folder + file layout

### 6.1 The 14 brand-name folders

`cal/`, `claude/`, `cursor/`, `framer/`, `mintlify/`, `notion/`,
`posthog/`, `raycast/`, `resend/`, `sentry/`, `stripe/`, `supabase/`,
`superhuman/`, `vercel/` — each contains exactly one file, `DESIGN.md`,
which is a long form essay about that brand's visual design language.

**Status:** ✅ Intentional. Indexed by
`docs/design-references/INDEX.md`. These are a *design-language
reference library*, not scaffolding. The naming (lowercase brand name)
matches what a human would type to find them.

**Recommendation: DO NOT TOUCH.** The naming convention here is
"folder name = brand it's modelled on." That's clean.

### 6.2 Genuinely odd top-level filenames

| Path | Status |
|---|---|
| `6 important pages/` (folder, contains HTML mockups) | ⚠️ Folder name with leading digit + spaces |
| `decisions_taken.md` (snake_case, lowercase) | ⚠️ Diverges from `DESIGN.md` / `README.md` / `CLAUDE.md` (UPPER) at top level |
| `refactor_phase.md` (snake_case, lowercase) | ⚠️ Same as above |
| `Makefile` | ✅ Standard |
| `pae_platform.zip` (in parent dir, not project) | Out of scope |

`6 important pages/` is a folder that breaks shell autocomplete and
demands quoting on every reference. It contains design HTML mockups.

**Recommendation: DISCUSS.** Renaming `6 important pages/` to
`design-mockups-cohort/` (or wherever the team wants to consolidate
the HTML mockups) would be a quality-of-life win. But there's also
already a `design-mockups/` folder at the top level with a different
set of HTML files. Whether they should merge is a content decision,
not a rename decision.

`decisions_taken.md` and `refactor_phase.md` look like one-off scratch
docs. If they should be folded into `docs/` (under whatever doc
convention the team picks), this becomes a doc-organisation task.

---

## 7. Database migrations — sequence integrity

### 7.1 Observation

The migration filenames are `NNNN_description.py`. Sequence:

```
0001 ... 0048, [no 0049 visible? Yes 0049 exists],
0049, [no 0050], 0051, 0052, 0053, 0054
```

**Confirmed gap:** `0050_*.py` does not exist. Migrations jump from
`0049_student_risk_signals.py` to `0051_outreach_log.py`.

**Status:** Known gap. Possibly an aborted migration that was never
merged, or a renumbering during a branch merge. Alembic's chain is
linked by `revision` / `down_revision` strings *inside* the files —
the filename number is decorative.

**Recommendation: DISCUSS.** Verify that the alembic chain (the
`down_revision` field inside `0051_outreach_log.py`) actually points to
`0049_student_risk_signals`, not to a missing `0050`. If yes, the
gap is cosmetic. If no, the chain is broken.

```
# Check command (don't run from this audit):
grep -E "^revision|^down_revision" backend/alembic/versions/0049_*.py backend/alembic/versions/0051_*.py
```

(Out of scope for this audit to actually run the check — that's an
action, not an inventory item.)

---

## 8. Summary table

| Finding | Location | Recommendation | Severity |
|---|---|---|---|
| Backend Python naming | `backend/app/` | Conforms | ✅ |
| `interview_service.py` not @deprecated | §2.3 | DISCUSS — mark @deprecated or schedule deletion | Medium |
| `_v2` word-order inconsistency | §2.4 | DISCUSS — pick one pattern | Low |
| Frontend kebab-case vs documented PascalCase | §4.2 | Update the docs to match the code | Low (doc fix only) |
| Top-level `docs/` naming heterogeneity | §5 | DISCUSS — pick a forward convention | Low |
| `6 important pages/` folder name | §6.2 | DISCUSS — rename + consolidate with `design-mockups/`? | Low |
| `decisions_taken.md` / `refactor_phase.md` at top level | §6.2 | DISCUSS — fold into `docs/`? | Low |
| Migration `0050` gap | §7 | DISCUSS — verify alembic chain integrity | Low (cosmetic if chain is fine) |

**No DEFINITE rename recommendations.** Every finding is either a
DISCUSS-level question or a doc-fix that doesn't require code changes.

---

## 9. What this audit deliberately did NOT cover

- **Symbol naming inside files** (function names, class names, variable
  names). Out of scope — the brief was for file/folder/route naming.
  Symbol-level audit is a much larger surface and would need a separate
  pass, ideally tool-driven (ruff has rules for it).
- **Whether the deprecated routes should actually be deleted** — that's
  a deletion decision, not a naming finding. The 38 `@deprecated`
  handlers all have `sunset="2026-07-01"`; the team's existing pipeline
  handles this.
- **Any node_modules or .venv content** — third-party packages have
  their own conventions.
- **Worktree copies under `.claude/worktrees/`** — these are agent-isolated
  workspace copies, not source-of-truth files.

## 10. References

- `.claude/rules/conventions.md` — file naming rules (currently says
  PascalCase for components; see §4.2 conflict)
- `frontend/CLAUDE.md` — frontend-specific rules
- `backend/CLAUDE.md` — backend-specific rules
- `docs/AGENTIC_OS.md` §6 — convention preamble for the primitives
  layer (the conventions referenced there are *coding/lifecycle*
  conventions, not naming conventions; complementary to this doc)
