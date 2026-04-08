# Production AI Engineering Platform

## Project Overview
A git-based learning platform with 18+ AI agents for teaching production GenAI.
Next.js 15 frontend + FastAPI backend + LangGraph agent orchestration + PostgreSQL + Redis.

## Quick Commands
```
# Frontend
cd frontend && pnpm dev              # Start Next.js dev server (port 3000)
cd frontend && pnpm lint             # ESLint + Prettier check
cd frontend && pnpm test             # Vitest unit tests
cd frontend && pnpm build            # Production build

# Backend
cd backend && uv run uvicorn app.main:app --reload   # FastAPI dev (port 8000)
cd backend && uv run pytest -x                       # Run tests, stop first fail
cd backend && uv run ruff check .                    # Lint
cd backend && uv run mypy app/                       # Type check
cd backend && uv run alembic upgrade head             # Run DB migrations

# Full Stack
docker compose up -d                 # Start all services
docker compose logs -f               # Follow logs
make test                            # Run ALL tests (frontend + backend)
make lint                            # Lint everything
```

## Architecture
@docs/ARCHITECTURE.md

## Code Style
- Python: ruff format, type hints on ALL functions, async by default
- TypeScript: strict mode, no `any`, Prettier + ESLint
- Tests: pytest (backend), Vitest (frontend), min 80% coverage
- Commits: conventional commits (feat:, fix:, docs:, test:, chore:)
- PRs: squash merge, require 1 review, CI must pass

## IMPORTANT Rules
- NEVER commit secrets or API keys. Use .env files (git-ignored).
- NEVER use print() for logging. Use structlog.
- NEVER write synchronous database calls. Always async.
- ALWAYS add Pydantic schemas for API request/response.
- ALWAYS write tests before marking a task complete.
- ALWAYS run `make lint` before committing.
- When in doubt, check @docs/ADR/ for architecture decisions.

## Monorepo Layout
```
production-ai-engineering-platform/
├── CLAUDE.md                    # This file (root context)
├── frontend/                    # Next.js 15 application
│   ├── CLAUDE.md               # Frontend-specific context
│   └── src/
├── backend/                     # FastAPI application
│   ├── CLAUDE.md               # Backend-specific context
│   └── app/
├── .claude/                     # Claude Code config
│   ├── settings.json           # Hooks
│   ├── skills/                 # 8 development skills
│   ├── agents/                 # 5 subagents
│   └── commands/               # 6 slash commands
├── docker-compose.yml           # Full stack local dev
├── docs/                        # Architecture, ADRs, API docs
└── .github/workflows/           # CI/CD
```

## File References
@README.md
@docs/ARCHITECTURE.md
@docs/AGENTS.md
@docs/API.md
@docs/DATABASE.md
@frontend/CLAUDE.md
@backend/CLAUDE.md

## Lessons Learned (Updated by Claude after corrections)
@docs/lessons.md
