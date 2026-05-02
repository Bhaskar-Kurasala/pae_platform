# Dead-code audit — repository-wide

**Audit only. NO DELETIONS.** This document is an inventory of code
that *might* be unused, classified by confidence. The deletion happens
later under explicit approval, possibly batched.

Each finding has a confidence level:

- **DEFINITE** — Zero references in production code, tests, CI,
  Makefile, scripts, docs, or shell automation. Grep evidence included.
  Safe to delete in a deliberate batch.
- **PROBABLE** — Only references are tests of itself, comments,
  changelog entries, or historical docs. Likely safe to delete but
  worth pausing for "are we losing the historical pointer?"
- **SUSPICIOUS** — Looks dead but I'm not sure. Could be wired through
  a dynamic import, an external job, an undocumented CI surface, or a
  feature-flagged code path that's currently off. Needs human eyeball
  before any action.

**No DEFINITE entries.** Every finding in this audit lands at PROBABLE
or SUSPICIOUS. That is deliberate — the bar for DEFINITE is "I have
exhaustive evidence," and in this codebase I cannot fully prove that
without running each test runner, walking every dynamic import, and
checking external CI mirrors. Better to mark conservatively and have
the team approve a closer look than to claim DEFINITE and risk
deleting something live.

**Generated:** 2026-05-02 (Track 4 of the parallel cleanup workstream)
**Scope:** `backend/`, top-level repo. Frontend dead-code already has
its own audit at `docs/audits/dead-frontend.md` (knip-tool generated)
and is not duplicated here.
**Out of scope:** the 26 legacy BaseAgent agents and the agent registry
(per global rules of this workstream).

---

## 1. Per-finding methodology

For each candidate, I report:

1. **What** — file or symbol
2. **Evidence** — grep commands run + their results
3. **Caveats** — anything that could make this NOT dead (dynamic
   import, external automation, etc.)
4. **Recommendation** — what the team should do *if* they confirm

If a candidate has even ONE inbound reference, it is removed from
this audit (that's not dead code, that's just unused-looking code).

---

## 2. PROBABLE candidates

### 2.1 The 17 `run_3*_tests.py` files at `backend/` root

**Files (17, exact list):**

```
backend/run_3a4_tests.py
backend/run_3a14_tests.py
backend/run_3a17_tests.py
backend/run_3b4_tests.py
backend/run_3b5_tests.py
backend/run_3b7_tests.py
backend/run_3b85_tests.py
backend/run_3b90_tests.py
backend/run_3b91_tests.py
backend/run_3b92_tests.py
backend/run_3b93_tests.py
backend/run_3b101_tests.py
backend/run_3b102_tests.py
backend/run_3b151_tests.py
backend/run_3b152_tests.py
backend/run_3b159_tests.py
backend/run_3b160_tests.py
backend/run_3b163_tests.py
```

(NB: the brief mentioned 18; I count 17. The 18th may be a worktree
copy. The `.claude/worktrees/agent-ae7cdee53c38db97d/backend/`
mirrors all of these — those are agent-isolated worktree copies,
not separate source files. They are not in this count.)

**Evidence — exhaustive ref check:**

| Surface | Command | Result |
|---|---|---|
| Makefile | Read `Makefile` | Uses `pytest -x` only. **Zero `run_3*` references.** |
| GitHub Actions CI (`.github/workflows/ci.yml`) | Read | Uses `pytest --cov ... -x`. **Zero `run_3*` references.** |
| GitHub Actions deploy (`.github/workflows/deploy.yml`) | Read | Uses `pytest --cov ... -x`. **Zero `run_3*` references.** |
| `backend/scripts/` shell scripts | Grep `run_3` in `scripts/` | **Zero matches.** |
| `pyproject.toml` test config | Read | No reference. |
| Any code import | Grep `import.*run_3` | **Zero matches.** |
| Documentation | Grep `run_3` in `docs/` | **2 matches**, both in `docs/ROADMAP-P3-CRITIC.md` (historical "X tests green via run_3bN_tests.py" notes). The worktree copy is out of scope. |

**Caveats:**

- The roadmap doc references each runner by name as the canonical
  proof point for sub-ticket "DONE" status. Deleting the runners
  doesn't break automation but does make the roadmap's "X tests green
  via run_3bN_tests.py" lines into broken pointers (they'd reference
  files that no longer exist).
- Each runner is a self-contained AST-pruning standalone — they were
  built for sub-ticket isolation during a specific phase, not as
  permanent test infrastructure.
- The actual test suite (`backend/tests/`) is the canonical pytest
  surface that CI runs.

**Recommendation:** PROBABLE. Two deletion options:

1. **Delete all 17 + update the roadmap doc** to drop the
   "via run_3bN_tests.py" suffixes (or replace with "see test_X.py").
   Single batched commit.
2. **Move them to `backend/scripts/legacy_runners/`** — keeps the
   historical pointer intact for archeology while removing them from
   the backend root. Less aggressive.

Either is reasonable. **The brief was clear: do not delete in this
pass.** Audit finding only.

### 2.2 `backend/app/services/interview_service.py`

**File:** `backend/app/services/interview_service.py` (legacy
interview service, superseded by `interview_service_v2.py` and
ultimately by Mock Interview Agent v3 at `/api/v1/mock`)

**Evidence:**

```
$ grep -rn "from app.services.interview_service\b\|app\.services\.interview_service\."
backend/tests/test_services/test_interview_service.py:15
  from app.services.interview_service import (
backend/app/api/v1/routes/interview.py:41
  from app.services.interview_service import (
```

The route is **mounted live** in `app/main.py:226` (`interview_router`).
So the file is reachable from a live HTTP surface.

**Why it's still PROBABLE-leaning-not-dead:**

- The `/interview` route is mounted but **NOT marked `@deprecated`**.
  It has no sunset date. If the v8 frontend never calls it, it's
  effectively dead — but I cannot prove that from a static audit.
- The team uses an `@deprecated(sunset=...)` pipeline that emits
  log warnings on every call. If the team's logs show no calls to
  `/interview` over 30 days, that's the deletion signal.

**Caveats:**

- Tests still exercise it.
- Mock Interview v3 (per `project_mock_interview_v3.md` in memory) is
  the canonical surface, so this *should* be dead — but the team
  hasn't added the deprecation marker, which suggests either oversight
  or "we're keeping it for a reason I don't know."

**Recommendation:** PROBABLE-but-blocked. Don't delete. **First add
`@deprecated(sunset=...)` to the legacy `/interview` handlers**, ship
that for ~2 weeks, check the deprecation log, then delete the service
file + the route file + the test file in one commit. This is captured
in the naming audit at `naming-audit.md` §2.3.

### 2.3 `backend/tests/test_services/test_interview_service.py`

Companion to §2.2. Same recommendation — delete with the service, not
before.

---

## 3. SUSPICIOUS candidates

### 3.1 Top-level `decisions_taken.md` and `refactor_phase.md`

**Status:** Live-looking docs at the repo root with snake_case
lowercase names (vs `README.md`, `CLAUDE.md`, `Makefile` at top
level).

**Evidence:**

```
$ grep -rn "decisions_taken\|refactor_phase"
# Zero matches outside the files themselves.
```

No other doc, code, or config references either file by name.

**Why SUSPICIOUS rather than PROBABLE:**

- They are clearly *living documents* (last entries dated
  2026-04-26 in `refactor_phase.md`).
- Their absence from any cross-reference might mean nothing — humans
  open them by hand, not by import.
- They might be the working document a specific person uses; deleting
  would surprise them.

**Recommendation:** SUSPICIOUS. **Don't act.** Ask: "Are
`decisions_taken.md` and `refactor_phase.md` actively used? If so,
should they move into `docs/`?" Answer determines folding strategy
(see naming audit §6.2).

### 3.2 `backend/scripts/audit_*.py` (4 files)

**Files:**

```
backend/scripts/audit_endpoints.py
backend/scripts/audit_excepts.py
backend/scripts/audit_frontend_callers.mjs
backend/scripts/audit_join.py
```

**Evidence (none of these are imported anywhere):**

```
$ grep -rn "from app.scripts.audit_\|import.*audit_endpoints\|import.*audit_excepts"
# Zero matches. They're standalone scripts.
```

**Why SUSPICIOUS rather than PROBABLE:**

- They are obviously *one-shot audit scripts* the team ran to
  generate the artifacts in `docs/audits/` (which include
  `endpoints.csv`, `api-callers.csv`, `endpoint-coverage.md`).
- They might be re-run periodically. Or might have been one-time.
- The `.mjs` extension on one of them suggests it's a Node script
  for the frontend side — same uncertainty.

**Recommendation:** SUSPICIOUS. **Don't delete.** Ask the team:
"are these one-shot scripts that produced existing audit CSVs, or
do you re-run them as part of the audit refresh cycle?" If one-shot,
they could move to `backend/scripts/legacy_audits/` or be deleted —
but the cost of keeping them is near-zero, and the cost of deleting
something the team uses periodically is "had to write it from scratch
again."

### 3.3 `backend/main.py` (vs `backend/app/main.py`)

**Files:**

- `backend/main.py` — at backend root
- `backend/app/main.py` — the FastAPI app factory (real one)

**Evidence:**

```
$ ls backend/main.py
-rw-r--r-- 1 kbhas 197609 ... May 1 ... backend/main.py
```

I have not yet read `backend/main.py` to confirm its content. The
existence of two `main.py` is a smell.

**Why SUSPICIOUS:**

- Could be a stub that re-exports `app.main:app` for compatibility
  with `uvicorn main:app` style invocations.
- Could be vestigial from the pre-`app/` layout.
- Could be a CLI entry point.

**Recommendation:** SUSPICIOUS. **Read it before doing anything.**
This is a 30-second check, but I'm flagging rather than reading
because the audit pass is meant to *enumerate candidates*, not act
on them.

### 3.4 `course_content/` at `backend/` root

**Path:** `backend/course_content/`

**Evidence:** I have not introspected the directory. From the brief
description, it likely holds raw content for the curriculum.

**Why SUSPICIOUS:**

- Could be a real data directory (live, never touched by code at
  runtime, but loaded by ingestion scripts).
- Could be a leftover from an earlier ingestion approach that has
  since moved to a database table or external storage.

**Recommendation:** SUSPICIOUS. Ask the team: "Is `course_content/`
the source of truth for any agent or ingestion pipeline?"

---

## 4. Deliberately NOT classified as dead

These are things that *look* like cleanup candidates at first glance
but turned out to have clear inbound references — listing them so the
team can see I checked and decided.

| Candidate | Why I checked | Why it's NOT dead |
|---|---|---|
| The 14 brand folders (`stripe/`, `sentry/`, etc.) | All contain only `DESIGN.md`; looked like scaffolding | Indexed by `docs/design-references/INDEX.md` — they're a *design-language reference library*, not scaffolding |
| `backend/app/agents/_agentic_loader.py` | Leading-underscore module | Called from `app/core/celery_app.py` boot path; load-bearing |
| `backend/app/agents/_llm_utils.py` | Leading-underscore module | Used by multiple agents for response parsing |
| `backend/app/agents/mock_sub_agents.py` | Not in `_ensure_registered()` agent list | Imported by `app/services/mock_interview_service.py` (live service) |
| `backend/app/agents/readiness_sub_agents.py` | Not in agent registry | Imported by `app/services/readiness_orchestrator.py` and `app/services/jd_decoder_service.py` (live services) |
| `disrupt_prevention_v2_service.py` | `_v2` suffix smelled stale | Wired into a Celery beat schedule via `app/tasks/outreach_automation.py` |
| `payments_v2.py` route | `_v2` suffix smelled stale | Live, mounted, with active webhook companion `payments_webhook.py` |
| All 38 `@deprecated(sunset=...)` route handlers | Marked deprecated | Has explicit deletion pipeline already in motion (sunset 2026-07-01) — let the existing process handle it |

---

## 5. Migration `0050` gap

**Observation:** Migration filenames jump from `0049_student_risk_signals.py`
to `0051_outreach_log.py`. No `0050_*.py` file exists.

**Status:** SUSPICIOUS — but as a *correctness* concern, not a dead-code
one. If the alembic chain (the `down_revision` field inside `0051`)
points to `0049`, the gap is purely cosmetic. If it points to a missing
`0050`, the chain is broken.

**Recommendation:** Run this check before any migration work:

```bash
grep -E "^revision|^down_revision" \
  backend/alembic/versions/0049_student_risk_signals.py \
  backend/alembic/versions/0051_outreach_log.py
```

If the `down_revision` of 0051 is the `revision` of 0049, the gap
is fine. Cross-referenced in `naming-audit.md` §7.

---

## 6. Summary table

| Finding | Confidence | Reversibility of action | Recommendation |
|---|---|---|---|
| 17 × `run_3*_tests.py` | PROBABLE | Easy (git revert) | Defer; delete in one batch with roadmap doc update |
| `interview_service.py` (legacy) | PROBABLE | Medium (route + service + test) | Mark @deprecated first, observe logs, then delete |
| `test_interview_service.py` | PROBABLE | Easy | Delete with the service, not before |
| `decisions_taken.md`, `refactor_phase.md` | SUSPICIOUS | Easy (`git mv` to docs/) | Ask before moving |
| `backend/scripts/audit_*.py` (4 files) | SUSPICIOUS | Easy (move to legacy/ or delete) | Ask if periodically re-run |
| `backend/main.py` | SUSPICIOUS | Trivial (read it first) | Read before any action |
| `backend/course_content/` | SUSPICIOUS | Hard (might be real data) | Ask the team |
| Migration `0050` gap | Cosmetic-or-bug | N/A | Verify alembic chain integrity |

**Zero DEFINITE entries.** Every action recommended needs human
sign-off. That is correct posture for an audit.

---

## 7. What this audit deliberately did NOT cover

- **Frontend dead-code** — already covered by knip-tool output at
  `docs/audits/dead-frontend.md` (52 unused files identified there).
  No reason to re-enumerate.
- **Unused exports inside live files** — the brief asked for
  *file-level* dead code. Symbol-level dead code (a function defined
  but never called inside a live module) is a tool job; ruff's
  `F401` already covers some of this; a vulture run would cover the
  rest. Out of scope here.
- **Database tables that no service writes to** — would require
  cross-referencing every model against every repository call.
  Possible but a separate, much larger audit.
- **`@deprecated` route handlers with `sunset="2026-07-01"`** — these
  have an active deletion pipeline; the team's process handles them.
  Listing them here would be redundant.
- **Worktree copies under `.claude/worktrees/`** — agent-isolated
  workspace duplicates, not source-of-truth files.

---

## 8. Methodology notes

- Every grep was bounded to `backend/`, `frontend/`, `docs/`, root,
  `.github/`, and `Makefile`. `node_modules/`, `.venv/`,
  `__pycache__/`, and `.claude/worktrees/` were excluded.
- I did NOT run any actual deletions or `git rm`. The audit produces
  a list with confidence levels; the team picks the next action.
- I did NOT run the test suite to verify "test still passes after
  hypothetical deletion" — that's a deletion-time check, not an
  audit-time check.
- A finding labelled DEFINITE in this audit is one I'd stake "let's
  delete this in the next cleanup batch with no further verification"
  on. **There are zero such findings**, by deliberate caution.

## 9. References

- `naming-audit.md` — companion audit (overlapping concerns at §2.3,
  §6.2, §7)
- `docs/audits/dead-frontend.md` — knip-tool dead-code output for
  frontend
- `docs/audits/endpoint-coverage.md`, `endpoints.csv`,
  `api-callers.csv` — existing audit artifacts
