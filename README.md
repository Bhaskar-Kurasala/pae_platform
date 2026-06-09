# Production AI Engineering Platform

> A git-based learning platform with **~28 AI agents** for teaching production GenAI systems. One human injects knowledge; the system automates content creation, student learning, career support, and revenue operations.

[![CI](https://github.com/Bhaskar-AIE/pae_platform/actions/workflows/ci.yml/badge.svg)](https://github.com/Bhaskar-AIE/pae_platform/actions)

---

## Quick Start (5 minutes)

### Prerequisites
```bash
brew install node pnpm git docker
curl -LsSf https://astral.sh/uv/install.sh | sh
# Verify
node --version  # >= 22
pnpm --version  # >= 9
uv --version    # >= 0.5
```

### 1. Clone & Configure
```bash
git clone https://github.com/Bhaskar-AIE/pae_platform.git
cd pae_platform/platform-config-files
cp .env.example .env      # Edit and add ANTHROPIC_API_KEY at minimum
```

### 2. Start Everything
```bash
docker compose up -d --build
docker compose exec backend uv run alembic upgrade head
```

### 3. Verify
```bash
curl http://localhost:8080/health   # via nginx → {"status": "ok"}
open http://localhost:3002          # Next.js landing page (docker maps 3000 → 3002)
open http://localhost:8080/docs     # FastAPI OpenAPI docs via nginx

# For local uvicorn dev (no docker):
#   backend  → http://localhost:8000
#   frontend → http://localhost:3000 (pnpm dev)
```

### 4. Develop
```bash
# Backend (hot reload)
cd backend && uv run uvicorn app.main:app --reload

# Frontend (hot reload)
cd frontend && pnpm dev
```

---

## Architecture at a Glance

```
┌─────────────────────────────────────────────────────────────┐
│  PRESENTATION    Next.js 16 · Tailwind 4 · shadcn/ui        │
│  64 routes: public / student portal / admin dashboard        │
├─────────────────────────────────────────────────────────────┤
│  API GATEWAY     FastAPI · JWT · slowapi rate limiting       │
│  58 route modules · OpenAPI docs at /docs                    │
├─────────────────────────────────────────────────────────────┤
│  AGENTS          LangGraph MOA + AgenticBaseAgent · ~28      │
│  Legacy @register registry + agentic /agentic/{flow}/chat    │
├─────────────────────────────────────────────────────────────┤
│  BUSINESS LOGIC  Celery · Stripe webhooks · GitHub webhooks  │
├─────────────────────────────────────────────────────────────┤
│  DATA            PostgreSQL 16 (76 migrations) · Redis 7     │
├─────────────────────────────────────────────────────────────┤
│  INFRA           Docker Compose · Nginx · GitHub Actions CI  │
└─────────────────────────────────────────────────────────────┘
```

---

## Development Commands

| Command | What it does |
|---|---|
| `make dev` | Start all Docker services |
| `make test` | Backend (~2,700 tests) + frontend (Vitest) |
| `make lint` | ruff + mypy + eslint |
| `make build` | Build Docker images |
| `make migrate` | Apply DB migrations |
| `make logs` | Follow all service logs |
| `make clean` | Stop everything, remove volumes |

---

## The AI Agents

Agents live in a **dual-registry** architecture (~28 total).

**Legacy `@register` agents (17)** — routed by the MOA LangGraph in `app/agents/moa.py`:

| Category | Agents |
|---|---|
| **Creation** | content_ingestion, curriculum_mapper, mcq_factory, student_buddy, deep_capturer |
| **Learning** | socratic_tutor, spaced_repetition, knowledge_graph, adaptive_path |
| **Analytics** | adaptive_quiz, progress_report |
| **Career** | portfolio_builder, job_match, cover_letter |
| **Engagement** | disrupt_prevention, peer_matching, community_celebrator |

**Agentic `AgenticBaseAgent` agents (11)** — dispatched via `/api/v1/agentic/{flow}/chat`,
auto-registered through `__init_subclass__` and loaded by `app/agents/_agentic_loader.py`.
Classes: `CareerCoachAgent`, `SeniorEngineerAgent` (absorbed code_review +
coding_assistant), `MockInterviewAgent`, `ProjectEvaluatorAgent`,
`ResumeReviewerAgent`, `TailoredResumeShimAgent`, `StudyPlannerAgent`,
`PracticeCuratorAgent`, `BillingSupportAgent`, `Supervisor`, `LearningCoach`.
See [`docs/AGENTS.md`](docs/AGENTS.md) for the file mapping.

Full details: [`docs/AGENTS.md`](docs/AGENTS.md)

---

## Project Status

| Phase | Status | What it covers |
|---|---|---|
| 0 — Foundation | ✅ | Docker, DB schema, CI/CD skeleton |
| 1 — Core API | ✅ | Auth, courses, lessons, exercises, webhooks |
| 2 — Frontend | ✅ | Landing, student portal, admin dashboard |
| 3 — Agent Framework | ✅ | MOA, 3 initial agents, chat API+UI |
| 4 — All Agents | ✅ | ~28 agents (dual registry), admin monitoring |
| 5 — Polish | ✅ | Security, caching, tests, docs |
| 6 — Pinecone + YouTube | 🔲 | Real RAG, content pipeline |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16 + TypeScript + Tailwind 4 + shadcn/ui |
| Backend | FastAPI + Pydantic v2 + slowapi |
| Agents | LangGraph + Claude API (claude-sonnet-4-6) |
| Database | PostgreSQL 16 + SQLAlchemy 2.0 async |
| Cache | Redis 7 (sessions + course list cache) |
| Queue | Celery + Redis |
| Auth | JWT (HS256) + OAuth2 |
| Payments | Stripe (webhooks wired) |
| CI/CD | GitHub Actions |
| Infra | Docker Compose + Nginx |

---

## Contributing

```bash
# 1. Create feature branch
git checkout -b feat/your-feature

# 2. Develop with hot reload
cd backend && uv run uvicorn app.main:app --reload
cd frontend && pnpm dev

# 3. Test
make test && make lint

# 4. Commit
git add -A && git commit -m "feat: your feature"
git push origin feat/your-feature
```

See [`CLAUDE.md`](CLAUDE.md) for Claude Code workflow and agent development guide.
