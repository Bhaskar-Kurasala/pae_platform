# Presentation & Documentation Rules

## Commit Messages
Always use conventional commits:
- `feat:` — new feature
- `fix:` — bug fix
- `docs:` — documentation only
- `test:` — adding/updating tests
- `chore:` — tooling, dependencies, CI
- `refactor:` — code restructuring without behavior change
- `style:` — formatting, linting fixes

Format: `{type}({scope}): {description}`
Example: `feat(agents): add socratic tutor agent with Bloom's taxonomy`

## File Naming
- Python: `snake_case.py`
- TypeScript: `kebab-case.tsx` for pages, `PascalCase.tsx` for components
- Tests: `test_{name}.py` (backend), `{name}.test.tsx` (frontend)
- Skills: `SKILL.md` in its own directory
- ADRs: `{NNN}-{title}.md` (e.g., `001-nextjs-over-remix.md`)

## Code Comments
Reserve for non-obvious decisions:
```python
# PRODUCTION INSIGHT: We use exponential backoff here because
# Claude API rate limits are per-minute, not per-second.
# Linear retry would hit the same rate limit window.
```

Do NOT comment obvious code:
```python
# BAD: Increment counter
counter += 1
```
