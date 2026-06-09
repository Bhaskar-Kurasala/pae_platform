# Architecture — Production AI Engineering Platform

## System Overview

A git-based learning platform with **~28 AI agents** that automates content creation,
student learning, career support, and community engagement. One human (you) injects
knowledge; the system turns it into a self-serving learning machine.

**Current stats:**
- ~28 AI agents across two registries (17 legacy `@register` + 11 agentic `AgenticBaseAgent`)
- 58 route modules under `app/api/v1/routes/`
- 76 Alembic migrations through revision 0075 (PostgreSQL)
- 64 frontend routes (Next.js App Router · `page.tsx` files)
- ~2,700 backend tests across ~290 test files

## 7-Layer Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: PRESENTATION                                       │
│  Next.js 16 · Tailwind 4 · shadcn/ui · React Query · Zustand│
│  64 routes: public · student portal · admin dashboard        │
├─────────────────────────────────────────────────────────────┤
│  Layer 2: API GATEWAY                                        │
│  FastAPI · JWT auth · slowapi rate limiting · OpenAPI docs   │
│  58 route modules: auth, courses, lessons, exercises,        │
│  students, webhooks, agents, agentic, admin, career, …       │
├─────────────────────────────────────────────────────────────┤
│  Layer 3: AGENT ORCHESTRATION                                │
│  LangGraph MOA (legacy) + AgenticBaseAgent · ~28 agents     │
│  Redis conversation history (1h TTL) · agent_actions logging │
├─────────────────────────────────────────────────────────────┤
│  Layer 4: BUSINESS LOGIC                                     │
│  Celery tasks · Learning engine · Payment processing         │
│  GitHub/Stripe webhooks · Exercise grading · Notifications   │
├─────────────────────────────────────────────────────────────┤
│  Layer 5: DATA                                               │
│  PostgreSQL 16 (76 migrations) · Redis 7 (cache + sessions)  │
│  Pinecone (RAG, Phase 6) · MinIO/S3 · Meilisearch           │
├─────────────────────────────────────────────────────────────┤
│  Layer 6: INFRASTRUCTURE                                     │
│  Docker Compose · Nginx · Gunicorn+Uvicorn · GitHub Actions  │
├─────────────────────────────────────────────────────────────┤
│  Layer 7: EXTERNAL INTEGRATIONS                              │
│  Claude API (anthropic) · Stripe · GitHub · SendGrid         │
│  YouTube (TODO) · Pinecone (TODO) · job boards (TODO)        │
└─────────────────────────────────────────────────────────────┘
```

## Database Schema (core / initial-schema tables)

The platform now spans 76 Alembic migrations through revision 0075; the schema
has grown well beyond the original set. The table below documents the core
tables created in the initial schema (see `backend/alembic/versions/` for the
full, current schema):

| Table | Purpose |
|---|---|
| `users` | Students and admins; UUID PK, soft delete |
| `courses` | Course catalogue with slug, difficulty, price |
| `lessons` | Ordered lessons per course; YouTube video ID |
| `exercises` | Coding exercises with rubrics and test cases |
| `enrollments` | Student↔course with progress % and payment link |
| `student_progress` | Per-lesson watch time and completion status |
| `exercise_submissions` | Code submissions with AI feedback JSON |
| `quiz_results` | MCQ quiz results with answer snapshots |
| `mcq_bank` | Question bank with difficulty tags |
| `agent_actions` | Full audit log of every agent invocation |
| `payments` | Stripe payment records linked to enrollments |
| `notifications` | In-app notification queue |

All tables: UUID PKs, `created_at`, `updated_at`, soft delete where appropriate.

## Agent Architecture

~28 agents live in a **dual-registry** architecture:

- **Legacy path** — 17 agents registered via the `@register` decorator in
  `app/agents/registry.py` (`AGENT_REGISTRY`). The MOA (Master Orchestrator
  Agent, `app/agents/moa.py`) is a LangGraph `StateGraph` that classifies intent
  and dispatches to the right agent. Wired to `routes/agents.py` and
  `routes/stream.py`.
- **Agentic path** — 11 agents subclassing `AgenticBaseAgent`, auto-registered
  via `__init_subclass__` and loaded by `app/agents/_agentic_loader.py`.
  Dispatched via the canonical `/api/v1/agentic/{flow}/chat` endpoint.

The legacy intent-classification flow below applies to the MOA / `@register`
path.

### Intent Classification Flow
```
Student request
    │
    ▼
keyword_route() — fast O(1) lookup on 15 keyword patterns
    │ miss
    ▼
claude-haiku-4-5 — LLM classifier (lists all legacy agents)
    │
    ▼
run_agent(routed_to) — single generic node dispatches to registry
    │
    ▼
agent.run() — execute → evaluate → log_action
    │
    ▼
Response + evaluation_score + conversation_id
```

## API Route Groups

There are 58 route modules under `app/api/v1/routes/`. The table below shows the
core groups; see the routes directory for the full set (agentic, career,
readiness, billing, etc.).

| Prefix | Routes | Auth |
|---|---|---|
| `/health` | GET /health | None |
| `/api/v1/auth` | POST /register, /login · GET /me | Mixed |
| `/api/v1/courses` | GET / · GET /:id · POST / · PUT /:id · DELETE /:id | Mixed |
| `/api/v1/lessons` | GET /courses/:id/lessons · GET /:id · POST · PUT /:id | Mixed |
| `/api/v1/exercises` | GET /:id · POST /:id/submit | Auth |
| `/api/v1/students` | GET /me/progress · POST /me/lessons/:id/complete | Auth |
| `/api/v1/webhooks` | POST /github · /stripe · /youtube | Signature |
| `/api/v1/agents` | POST /chat · GET /list | Auth |
| `/api/v1/admin` | GET /stats · /agents/health · /students | Admin |

## Security

- **Auth**: JWT (HS256), 30-min access token, 7-day refresh token
- **Rate limiting**: slowapi middleware; 10/min on register, 20/min on login
- **CORS**: configured via `settings.cors_origins` (default: localhost:3000)
- **Webhook verification**: HMAC-SHA256 for GitHub; Stripe timestamp+v1
- **Secrets**: all via `.env` (git-ignored); Pydantic Settings validation at startup

## Key Technical Decisions
See `decisions_taken.md` (root) for the full running ADR log. Recent entries:
- ADR-001: Full Platform Scope
- ADR-002: Design Aesthetic
- ADR-003: Live Agent Demo on Landing Page
- ADR-004: Deployment Target
- ADR-005: Pinecone RAG vs. Local Fallback
