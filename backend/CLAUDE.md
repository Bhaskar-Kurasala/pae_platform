# Backend — FastAPI

## Stack
FastAPI + SQLAlchemy 2.0 (async) + Alembic + Celery + Redis + PostgreSQL 16 + LangGraph

## Commands
```
uv run uvicorn app.main:app --reload            # Dev server on :8000
uv run pytest -x                                 # Tests (stop on first failure)
uv run pytest --cov=app --cov-report=html        # Coverage report
uv run ruff check . && uv run ruff format .      # Lint + format
uv run mypy app/                                 # Type check
uv run alembic revision --autogenerate -m 'desc' # New migration
uv run alembic upgrade head                       # Apply migrations
uv run celery -A app.core.celery_app worker -l info  # Start Celery worker
```

## Architecture Pattern
```
Routes (thin controllers) → Services (business logic) → Repositories (DB access) → Models
                                                        ↘ Agents (LangGraph nodes)
Schemas (Pydantic v2) validate ALL inputs and outputs at every boundary.
```

## File Structure
```
app/
├── main.py                 # FastAPI app factory, middleware, startup
├── api/v1/routes/          # Route handlers (thin — delegate to services)
├── core/                   # Config, security, database, redis, celery
├── services/               # Business logic (agent orchestrator, payments, etc.)
├── agents/                 # All 18+ AI agents (each extends BaseAgent)
│   ├── base_agent.py       # Abstract base with execute(), evaluate(), log()
│   ├── moa.py              # Master Orchestrator Agent (LangGraph)
│   └── prompts/            # System prompts for each agent (markdown files)
├── models/                 # SQLAlchemy models
├── schemas/                # Pydantic request/response schemas
├── repositories/           # Database access layer (async queries)
└── tasks/                  # Celery async tasks
```

## Rules
- ALL functions MUST have type hints (mypy strict mode, no `Any`).
- ALL DB calls MUST be async (AsyncSession from SQLAlchemy 2.0).
- ALL external API calls MUST have retry logic (tenacity decorator).
- ALL agents MUST extend `BaseAgent` and implement `async execute()`.
- NEVER import from routes in services (clean dependency direction).
- Use `structlog` for ALL logging — never `print()` or `logging.getLogger()`.
- Use FastAPI dependency injection for services and repositories.
- Every new endpoint needs: Pydantic schema, pytest, OpenAPI docs.
- Database: UUID primary keys, created_at/updated_at, soft delete.
