# Architecture — Production AI Engineering Platform

## System Overview

A git-based learning platform with **20 AI agents** that automates content creation,
student learning, career support, and community engagement. One human (you) injects
knowledge; the system turns it into a self-serving learning machine.

**Current stats (Phase 5 complete):**
- 20 registered AI agents
- 19 API endpoints across 8 route groups
- 12 database tables (PostgreSQL)
- 15 frontend routes (Next.js App Router)
- 84 backend tests · 28 frontend tests · 81% backend coverage

## 7-Layer Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: PRESENTATION                                       │
│  Next.js 16 · Tailwind 4 · shadcn/ui · React Query · Zustand│
│  15 routes: public · student portal · admin dashboard        │
├─────────────────────────────────────────────────────────────┤
│  Layer 2: API GATEWAY                                        │
│  FastAPI · JWT auth · slowapi rate limiting · OpenAPI docs   │
│  8 route groups: auth, courses, lessons, exercises,          │
│  students, webhooks, agents, admin                           │
├─────────────────────────────────────────────────────────────┤
│  Layer 3: AGENT ORCHESTRATION                                │
│  LangGraph MOA · 20 agents in 5 categories · AGENT_REGISTRY │
│  Redis conversation history (1h TTL) · agent_actions logging │
├─────────────────────────────────────────────────────────────┤
│  Layer 4: BUSINESS LOGIC                                     │
│  Celery tasks · Learning engine · Payment processing         │
│  GitHub/Stripe webhooks · Exercise grading · Notifications   │
├─────────────────────────────────────────────────────────────┤
│  Layer 5: DATA                                               │
│  PostgreSQL 16 (12 tables) · Redis 7 (cache + sessions)      │
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

## Database Schema (12 tables)

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

20 agents organized in 5 categories, all registered via `@register` decorator in
`app/agents/registry.py`. The MOA (Master Orchestrator Agent) is a LangGraph
`StateGraph` that classifies intent and dispatches to the right agent.

### Intent Classification Flow
```
Student request
    │
    ▼
keyword_route() — fast O(1) lookup on 15 keyword patterns
    │ miss
    ▼
claude-haiku-4-5 — LLM classifier (lists all 20 agents)
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
See `docs/ADR/` for full Architecture Decision Records.
- ADR-001: Next.js 16 over Remix
- ADR-002: LangGraph over CrewAI (stateful orchestration)
- ADR-003: PostgreSQL over MongoDB
- ADR-004: Celery over FastAPI BackgroundTasks
- ADR-005: Pinecone over Chroma (managed, production-ready)
