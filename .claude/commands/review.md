---
name: review
description: Code review workflow — checks quality, security, patterns, tests
argument-hint: [file-or-directory]
---

# /review — Code Review

Perform a thorough code review of the specified files or the current diff.

## What to Check
1. **Correctness** — Does it do what it claims? Edge cases?
2. **Security** — No secrets, SQL injection, proper auth, input validation
3. **Patterns** — Follows route → service → repository? Uses Pydantic schemas?
4. **Performance** — No N+1 queries, proper indexes, async where needed
5. **Types** — Full type coverage? No `Any`? mypy passes?
6. **Tests** — Tests exist? Test behavior not implementation?
7. **Logging** — Uses structlog? Proper log levels?
8. **Docs** — Docstrings on public functions?

## Process
1. If a file/directory is specified, review those files
2. If no argument, review `git diff main` (changes since main branch)
3. Run linter: `uv run ruff check .` and `pnpm lint`
4. Run type check: `uv run mypy app/`
5. Run tests: `uv run pytest -x`
6. Report findings by severity (Critical → Warning → Suggestion)

## Output
For each issue:
- **File:Line** — `path/to/file.py:42`
- **Severity** — Critical | Warning | Suggestion
- **Issue** — What's wrong
- **Fix** — How to fix it
