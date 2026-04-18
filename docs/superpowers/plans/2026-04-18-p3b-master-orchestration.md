# Phase 3B Master Orchestration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Set up 7 git worktrees, reserve migrations, and dispatch 7 parallel area subagents for the 39 Phase 3B tickets.

**Architecture:** One worktree per area, branched from main. Each area subagent works sequentially through its tickets following the per-ticket protocol in CONTRIBUTING-P3.md. All 7 agents run concurrently. Coordinator merges each area to main when the subagent signals completion.

**Tech Stack:** git worktrees, bash, Claude subagents

---

## Task 1: Reserve migration numbers in tracker

**Files:**
- Modify: `docs/ROADMAP-P3-CRITIC.md`

- [ ] **Step 1: Check current highest migration**

```bash
cd /mnt/e/Apps/pae_platform/pae_platform
ls backend/alembic/versions/ | sort | tail -3
```
Expected output ends with `0009_submission_sharing.py`. Confirm 0009 is highest.

- [ ] **Step 2: Add migration reservation block to tracker**

In `docs/ROADMAP-P3-CRITIC.md`, find the "Cross-cutting new tables" section and add directly above it:

```markdown
## Migration number reservations (3B)

| Number | Area | Ticket | Purpose |
|---|---|---|---|
| 0010 | meta | #177 | feedback table |
| 0011 | career | #168/#169 | resumes + interview_questions tables |

Next available: 0012
```

- [ ] **Step 3: Commit**

```bash
git add docs/ROADMAP-P3-CRITIC.md
git commit -m "chore(tracker): reserve migrations 0010-0011 for meta and career"
```

---

## Task 2: Create all 7 worktrees

**Files:** git worktrees (not repo files)

- [ ] **Step 1: Create worktrees from current main**

```bash
cd /mnt/e/Apps/pae_platform/pae_platform
git worktree add /mnt/e/Apps/pae_platform/wt/skillmap  -b feat/p3b-skillmap
git worktree add /mnt/e/Apps/pae_platform/wt/studio    -b feat/p3b-studio
git worktree add /mnt/e/Apps/pae_platform/wt/receipts  -b feat/p3b-receipts
git worktree add /mnt/e/Apps/pae_platform/wt/admin     -b feat/p3b-admin
git worktree add /mnt/e/Apps/pae_platform/wt/infra     -b feat/p3b-infra
git worktree add /mnt/e/Apps/pae_platform/wt/meta      -b feat/p3b-meta
git worktree add /mnt/e/Apps/pae_platform/wt/career    -b feat/p3b-career
```

- [ ] **Step 2: Verify all worktrees exist**

```bash
git worktree list
```

Expected: 8 entries (main + 7 new branches).

---

## Task 3: Dispatch 7 parallel area subagents

Send a single message with all 7 Agent tool calls in parallel. Each subagent receives:
- Their worktree path
- Their area's plan file path
- The operating constraints from CONTRIBUTING-P3.md

Area plans are at:
- `docs/superpowers/plans/2026-04-18-p3b-skillmap.md`
- `docs/superpowers/plans/2026-04-18-p3b-studio.md`
- `docs/superpowers/plans/2026-04-18-p3b-receipts.md`
- `docs/superpowers/plans/2026-04-18-p3b-admin.md`
- `docs/superpowers/plans/2026-04-18-p3b-infra.md`
- `docs/superpowers/plans/2026-04-18-p3b-meta.md`
- `docs/superpowers/plans/2026-04-18-p3b-career.md`

- [ ] **Step 1: Dispatch all 7 agents in one parallel message**

Invoke `superpowers:dispatching-parallel-agents` skill and send 7 Agent tool calls simultaneously. Each agent prompt includes their plan file path and worktree path (see spec `docs/superpowers/specs/2026-04-18-p3b-parallel-execution-design.md` for full context package).

---

## Task 4: Integrate completed areas

When a subagent signals its area is complete:

- [ ] **Step 1: Review commits**

```bash
git log feat/p3b-{area} ^main --oneline
```

Confirm all expected tickets show `[x] DONE` commits.

- [ ] **Step 2: Verify tracker**

In `docs/ROADMAP-P3-CRITIC.md`, confirm all tickets in the area show `[x]`.

- [ ] **Step 3: Run test suite from main**

```bash
cd /mnt/e/Apps/pae_platform/pae_platform
git merge --no-ff feat/p3b-{area}
make test
make lint
```

Expected: all tests green, lint clean.

- [ ] **Step 4: Remove the worktree**

```bash
git worktree remove /mnt/e/Apps/pae_platform/wt/{area}
```

Repeat Task 4 for each area as it completes. Merge order does not matter — areas are file-disjoint.
