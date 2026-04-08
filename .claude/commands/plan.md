---
name: plan
description: Architecture planning — break down a feature into implementable tasks
argument-hint: [feature-or-phase-description]
---

# /plan — Architecture Planning

You are the system architect planning a feature or phase.

## Process
1. Use `ultrathink` to deeply analyze the request
2. Read relevant docs: @docs/ARCHITECTURE.md, @docs/AGENTS.md, @docs/DATABASE.md
3. Identify all components affected across all layers
4. Break down into ordered tasks with dependencies
5. Estimate complexity (S = <1hr, M = 1-4hr, L = 4-8hr)

## Output Format
```markdown
# Plan: {Feature/Phase Name}

## Summary
{1-2 sentence description of what we're building}

## Tasks (ordered by dependency)
| # | Task | Layer | Complexity | Files | Dependencies |
|---|------|-------|-----------|-------|-------------|
| 1 | ... | Backend | S | app/models/... | None |
| 2 | ... | Backend | M | app/services/... | Task 1 |

## Database Changes
{New tables, columns, migrations needed}

## API Changes
{New/modified endpoints}

## Frontend Changes
{New pages, components}

## Agent Changes
{New/modified agents}

## Parallel Worktree Strategy
{Which tasks can be developed in parallel worktrees}

## Risks & Mitigations
{What could go wrong and how to prevent it}

## Acceptance Criteria
{How do we know this phase is complete}
```

## Rules
- Tasks must be small enough for one Claude Code session
- Identify tasks that can run in parallel (different files/layers)
- Always include test tasks
- Always include documentation tasks
