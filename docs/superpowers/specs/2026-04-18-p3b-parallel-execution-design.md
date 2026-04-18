# Phase 3B Parallel Execution Design

**Date:** 2026-04-18  
**Scope:** 39 tickets across 7 areas (teammate slice)  
**Strategy:** 7 parallel git worktrees × 7 subagents, sequentially within each area

---

## Context

Phase 3A (18 tickets, tutor behavior) is owned by the main stream and handled sequentially on `main`. This design covers the parallel 3B slice that has zero file overlap with 3A.

Reference docs:
- `docs/ROADMAP-P3-CRITIC.md` — ticket list and tracker
- `docs/CONTRIBUTING-P3.md` — non-negotiables, claim protocol, per-ticket checklist, file ownership

---

## Architecture

### 7 Worktrees × 7 Subagents

One git worktree per area, branched from `main` at the start of execution. Each worktree is assigned one subagent that ships its area's tickets sequentially. All 7 worktrees run concurrently.

| Worktree path | Branch | Area | Ticket IDs | Count | DB migrations |
|---|---|---|---|---|---|
| `/mnt/e/Apps/pae_platform/wt/skillmap` | `feat/p3b-skillmap` | Skill Map | #21,22,24,25,26,27 | 6 | none |
| `/mnt/e/Apps/pae_platform/wt/studio` | `feat/p3b-studio` | Studio polish | #39,40,41,42,43,44,45,48,50 | 9 | none |
| `/mnt/e/Apps/pae_platform/wt/receipts` | `feat/p3b-receipts` | Receipts 3B | #75,76,79,81,82,83 | 6 | none |
| `/mnt/e/Apps/pae_platform/wt/admin` | `feat/p3b-admin` | Admin 3B | #142,148, rubric-editor | 3 | none |
| `/mnt/e/Apps/pae_platform/wt/infra` | `feat/p3b-infra` | Infrastructure | #158,159,160,162,163,164,165,167 | 8 | none |
| `/mnt/e/Apps/pae_platform/wt/meta` | `feat/p3b-meta` | Meta | #177,180 | 2 | **0010** (feedback table) |
| `/mnt/e/Apps/pae_platform/wt/career` | `feat/p3b-career` | Career | #168,169,171,172,173 | 5 | **0011** (#168 resumes table, #169 interview_questions table) |

**Total: 39 tickets across 7 worktrees**

### Why one worktree per area (not per ticket)

Tickets within an area share files. For example, multiple Studio tickets touch `studio/page.tsx` and the Monaco config. One agent per area avoids intra-area merge conflicts and keeps context focused. Across areas, files are disjoint — the file ownership table in CONTRIBUTING-P3.md guarantees this.

---

## Pre-dispatch steps (main thread)

Before any subagent launches:

1. **Reserve migration numbers** in `docs/ROADMAP-P3-CRITIC.md`:
   - `0010` → meta area (feedback table, ticket #177)
   - `0011` → career area (resume/interview tables, tickets #168/#169)
   - Commit: `chore(tracker): reserve migrations 0010-0011 for meta and career`

2. **Create all 7 worktrees** from current `main` (run from `/mnt/e/Apps/pae_platform/pae_platform`):
   ```bash
   git worktree add /mnt/e/Apps/pae_platform/wt/skillmap -b feat/p3b-skillmap
   git worktree add /mnt/e/Apps/pae_platform/wt/studio   -b feat/p3b-studio
   git worktree add /mnt/e/Apps/pae_platform/wt/receipts -b feat/p3b-receipts
   git worktree add /mnt/e/Apps/pae_platform/wt/admin    -b feat/p3b-admin
   git worktree add /mnt/e/Apps/pae_platform/wt/infra    -b feat/p3b-infra
   git worktree add /mnt/e/Apps/pae_platform/wt/meta     -b feat/p3b-meta
   git worktree add /mnt/e/Apps/pae_platform/wt/career   -b feat/p3b-career
   ```

3. **Dispatch all 7 subagents** in a single parallel message.

---

## Per-ticket protocol (every subagent follows this)

### Before writing any code
1. Answer the critic question: "does this change student behavior or support?" in one sentence. If no, flag and skip.
2. `git pull --rebase` from within the worktree.
3. Edit the ticket line in `docs/ROADMAP-P3-CRITIC.md` from `- [ ] #NN` to `- [~] #NN (p3b, feat/p3b-{area})`.
4. Commit that edit alone: `chore(tracker): claim 3B-#NN`.
5. Read every file the ticket touches before writing a line.

### Implementation
- **Backend pattern:** pure helper functions at top of service → service method → route (≤30 lines) → Pydantic schema
- **Frontend pattern:** Server Component by default; `'use client'` only for interactivity leaves
- **Logging:** every ticket emits at least one `log.info("{area}.{event}", ...)` with structured kwargs
- **No dead code:** stubs get a `# TODO: #NN description` comment

### Verification
- `uv run mypy app/` clean (backend)
- `uv run ruff check . && uv run ruff format .` clean (backend)
- `pnpm tsc --noEmit && pnpm lint` clean (frontend)
- `uv run pytest -x` green (backend)
- `pnpm test` green (frontend)
- **Playwright (all UI tickets):** navigate → snapshot → interact → screenshot golden path → 2 edge cases → console messages clean → no 5xx in network

### Mark done
- Edit tracker line to `- [x] #NN … DONE (commit-sha)` in the same commit as the feature code
- Commit format: `feat({area}): 3B-#NN {short desc}`

---

## File ownership (hard constraints)

Subagents must NOT touch:

| File / path | Owner |
|---|---|
| `backend/app/api/v1/routes/stream.py` | 3A (main stream) |
| `backend/app/services/student_context_service.py` | 3A |
| `backend/app/agents/moa.py` and `agents/prompts/*` | 3A |
| `backend/app/models/user_preferences.py` | 3A |
| `backend/app/models/reflection.py` | 3A |
| `backend/app/services/preferences_service.py` | 3A |
| `frontend/src/app/(portal)/today/*` | 3A |
| `frontend/src/app/(portal)/chat/*` | 3A |
| `frontend/src/app/admin/students/[id]/*` | 3A-18 |

---

## Subagent context package (what each gets)

Every subagent receives:
1. Their area name, ticket IDs, and primary file paths
2. Full ticket specs from `docs/ROADMAP-P3-CRITIC.md` (their section only)
3. Non-negotiables from CONTRIBUTING-P3.md §3
4. Per-ticket checklist from CONTRIBUTING-P3.md §5
5. Playwright verification protocol from CONTRIBUTING-P3.md §6
6. File ownership table above
7. Migration numbers reserved for their area (if applicable)
8. Current `main` SHA at dispatch time so they can verify their base

---

## Post-area integration (main thread)

When a subagent's worktree is complete:
1. Review the area's commits: `git log feat/p3b-{area} ^main --oneline`
2. Confirm all tickets in the area are marked `[x] DONE` in the tracker
3. Merge to `main`: `git merge --no-ff feat/p3b-{area}`
4. Remove worktree: `git worktree remove /mnt/e/Apps/pae_platform/wt/{area}`

Merge order does not matter — areas are file-disjoint. Merge as each area completes.

---

## Definition of Done (area-level)

An area is done when:
- All its tickets are `[x] DONE (sha)` in `docs/ROADMAP-P3-CRITIC.md`
- `make test` passes on the merged `main`
- `make lint` passes on the merged `main`
- No regression on existing screens (smoke the portal, admin, and chat routes)

---

## Risk mitigations

| Risk | Mitigation |
|---|---|
| Migration collision | Numbers 0010/0011 reserved in main before dispatch; subagents use reserved numbers |
| Tracker edit conflict | Each subagent edits only its own ticket lines; different lines = no conflict |
| 3A file touch | File ownership table baked into every subagent prompt; stop-and-ping rule |
| Test env state | Each worktree runs against the shared Docker Compose stack; tests use in-memory SQLite (no port conflict) |
| Subagent drifting scope | Critic question check before every ticket; dropped tickets go to DROPPED section |
