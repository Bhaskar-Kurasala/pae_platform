# Production AI Engineering Platform

> A git-based learning platform with **20 AI agents** for teaching production GenAI systems. One human injects knowledge; the system automates content creation, student learning, career support, and revenue operations.

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
│  15 routes: public / student portal / admin dashboard        │
├─────────────────────────────────────────────────────────────┤
│  API GATEWAY     FastAPI · JWT · slowapi rate limiting       │
│  8 route groups · OpenAPI docs at /docs                      │
├─────────────────────────────────────────────────────────────┤
│  AGENTS          LangGraph MOA · 20 agents · AGENT_REGISTRY  │
│  5 categories: Creation, Learning, Analytics, Career, Engage │
├─────────────────────────────────────────────────────────────┤
│  BUSINESS LOGIC  Celery · Stripe webhooks · GitHub webhooks  │
├─────────────────────────────────────────────────────────────┤
│  DATA            PostgreSQL 16 (12 tables) · Redis 7 (cache) │
├─────────────────────────────────────────────────────────────┤
│  INFRA           Docker Compose · Nginx · GitHub Actions CI  │
└─────────────────────────────────────────────────────────────┘
```

---

## Development Commands

| Command | What it does |
|---|---|
| `make dev` | Start all Docker services |
| `make test` | Backend (84 tests) + frontend (28 tests) |
| `make lint` | ruff + mypy + eslint |
| `make build` | Build Docker images |
| `make migrate` | Apply DB migrations |
| `make logs` | Follow all service logs |
| `make clean` | Stop everything, remove volumes |

---

## The 20 AI Agents

| Category | Agents |
|---|---|
| **Creation** | content_ingestion, curriculum_mapper, mcq_factory, coding_assistant, student_buddy, deep_capturer |
| **Learning** | socratic_tutor, spaced_repetition, knowledge_graph, adaptive_path |
| **Analytics** | adaptive_quiz, project_evaluator, progress_report |
| **Career** | mock_interview, portfolio_builder, job_match |
| **Engagement** | disrupt_prevention, peer_matching, community_celebrator, code_review |

Full details: [`docs/AGENTS.md`](docs/AGENTS.md)

---

## Project Status

| Phase | Status | What it covers |
|---|---|---|
| 0 — Foundation | ✅ | Docker, DB schema, CI/CD skeleton |
| 1 — Core API | ✅ | Auth, courses, lessons, exercises, webhooks |
| 2 — Frontend | ✅ | Landing, student portal, admin dashboard |
| 3 — Agent Framework | ✅ | MOA, 3 initial agents, chat API+UI |
| 4 — All Agents | ✅ | 20 agents, admin monitoring |
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
