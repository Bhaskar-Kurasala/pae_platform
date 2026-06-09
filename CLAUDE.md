# Production AI Engineering Platform

## Project Overview
A git-based learning platform with ~28 AI agents (dual registry) for teaching
production GenAI. Next.js 16 frontend + FastAPI backend + LangGraph agent
orchestration + PostgreSQL + Redis.

## Quick Commands
```
# Frontend
cd frontend && pnpm dev              # Start Next.js dev server (port 3000)
cd frontend && pnpm lint             # ESLint
cd frontend && pnpm test             # Vitest unit tests
cd frontend && pnpm build            # Production build

# Backend
cd backend && uv run uvicorn app.main:app --reload   # FastAPI dev (port 8000)
cd backend && uv run pytest -x                       # Run tests, stop first fail
cd backend && uv run ruff check .                    # Lint
cd backend && uv run mypy app/                       # Type check
cd backend && uv run alembic upgrade head            # Run DB migrations

# Full Stack
docker compose up -d                 # Start all services
make test                            # Run ALL tests (frontend + backend)
make lint                            # Lint everything
```

## Code Style
- Python: ruff format, type hints on ALL functions, async by default
- TypeScript: strict mode, no `any`, Prettier + ESLint
- Tests: pytest (backend), Vitest (frontend)
- Commits: conventional commits (feat:, fix:, docs:, test:, chore:)
- PRs: squash merge, require 1 review, CI must pass

## IMPORTANT Rules
- NEVER commit secrets or API keys. Use .env files (git-ignored).
- NEVER use print() for logging. Use structlog.
- NEVER write synchronous database calls. Always async.
- ALWAYS add Pydantic schemas for API request/response.
- ALWAYS write tests before marking a task complete.
- ALWAYS run `make lint` before committing.
- When in doubt, check `decisions_taken.md` for architecture decisions (ADR log).

## Monorepo Layout
```
pae_platform/
├── CLAUDE.md            # This file (root context)
├── frontend/            # Next.js 16 app  (frontend/CLAUDE.md loads on demand)
├── backend/             # FastAPI app     (backend/CLAUDE.md loads on demand)
├── .claude/             # Claude Code config: skills/, agents/, commands/,
│                        #   hooks/, rules/, settings.json
├── docker-compose.yml   # Full stack local dev
├── docs/                # Architecture, operations, references
└── .github/workflows/   # CI/CD
```

## Reference Docs (read on demand — not eager-loaded)
- `docs/ARCHITECTURE.md` — system design, 7-layer architecture, agent registry
- `docs/AGENTS.md` — full dual-registry agent catalog
- `decisions_taken.md` — ADR / decision log
- `README.md` — quick start + stack overview
- `backend/CLAUDE.md`, `frontend/CLAUDE.md` — auto-load when you work in those dirs.
  Path-scoped rules in `.claude/rules/` add more guidance for matching files.

> Note: project-specific learnings are now captured automatically via Auto Memory
> (`~/.claude/projects/<repo>/memory/`). The historical `docs/lessons.md` is
> retained for reference; durable backend gotchas live in
> `.claude/rules/backend-gotchas.md` (loads only for `backend/**`).

## gstack (REQUIRED — global install)

**Before doing ANY work, verify gstack is installed:**

```bash
test -d ~/.claude/skills/gstack/bin && echo "GSTACK_OK" || echo "GSTACK_MISSING"
```

If GSTACK_MISSING: STOP. Do not proceed. Tell the user:

> gstack is required for all AI-assisted work in this repo.
> Install it:
> ```bash
> git clone --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack
> cd ~/.claude/skills/gstack && ./setup --team
> ```
> Then restart your AI coding tool.

Do not skip skills, ignore gstack errors, or work around missing gstack.

Using gstack skills: After install, skills like /qa, /ship, /review, /investigate,
and /browse are available. Use /browse for all web browsing.
Use ~/.claude/skills/gstack/... for gstack file paths (the global path).
