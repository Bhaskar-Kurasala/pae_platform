---
name: implement
description: Full feature implementation workflow — plan → code → test → review
argument-hint: [feature-description]
---

# /implement — Feature Implementation Workflow

You are implementing a feature for the Production AI Engineering Platform.

## Workflow (follow in order)

### Step 1: Understand
- Read the feature description carefully
- Check relevant CLAUDE.md files (@CLAUDE.md, @frontend/CLAUDE.md, @backend/CLAUDE.md)
- Read existing code in the area you'll modify
- Identify dependencies and potential conflicts

### Step 2: Plan
- Use `ultrathink` to plan the implementation
- List all files that need to be created or modified
- Identify database changes needed
- Identify test files needed
- Decide if an ADR is warranted

### Step 3: Implement
- Create/modify files following existing patterns
- Write Pydantic schemas before routes
- Write services before routes
- Write tests alongside implementation
- Use conventional commit messages

### Step 4: Validate
- Run `cd backend && uv run ruff check . && uv run mypy app/` (if backend changes)
- Run `cd frontend && pnpm lint` (if frontend changes)
- Run `cd backend && uv run pytest -x` (if backend changes)
- Run `cd frontend && pnpm test` (if frontend changes)
- Fix any issues before proceeding

### Step 5: Commit
- Stage changes: `git add -p` (review each hunk)
- Commit: `git commit -m 'feat: {description}'`
- If in worktree, note that a PR should be created

## IMPORTANT
- Do NOT skip the validate step
- Do NOT commit without running tests
- If tests fail, fix them before committing
- If you're unsure about an architecture decision, create an ADR draft
