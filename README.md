# Production AI Engineering Platform

## Complete Setup & Development Guide

> **What is this?** A git-based learning platform with 18+ AI agents for teaching production GenAI systems. One human (you — Senior Gen AI Engineer, 9+ years) injects knowledge. The system automates content creation, student learning, career support, and revenue operations.

---

## Architecture at a Glance

```
┌─────────────────────────────────────────────────────────┐
│  PRESENTATION    Next.js 15 · Tailwind · shadcn/ui     │
├─────────────────────────────────────────────────────────┤
│  API GATEWAY     FastAPI · JWT/OAuth2 · Rate Limiting   │
├─────────────────────────────────────────────────────────┤
│  AGENTS          LangGraph MOA · 18 agents · Tools      │
├─────────────────────────────────────────────────────────┤
│  BUSINESS LOGIC  Celery · Payments · GitHub · Grading   │
├─────────────────────────────────────────────────────────┤
│  DATA            PostgreSQL · Redis · Pinecone · S3     │
├─────────────────────────────────────────────────────────┤
│  INFRA           Docker · Nginx · Prometheus · GH Actions│
├─────────────────────────────────────────────────────────┤
│  EXTERNAL        YouTube · GitHub · Stripe · Claude API │
└─────────────────────────────────────────────────────────┘
```

---

## Quick Start (Zero to Running in 10 Minutes)

### Prerequisites
```bash
# macOS
brew install node pnpm git docker
curl -LsSf https://astral.sh/uv/install.sh | sh
npm install -g @anthropic-ai/claude-code

# Verify
node --version    # >= 22
pnpm --version    # >= 9
uv --version      # >= 0.5
docker --version
claude --version
```

### Step 1: Clone & Configure
```bash
git clone <your-repo-url> production-ai-engineering-platform
cd production-ai-engineering-platform
cp .env.example .env
# Edit .env — fill in ANTHROPIC_API_KEY at minimum
```

### Step 2: Install Claude Code Plugins
```bash
claude /plugin install superpowers
npx get-shit-done-cc@latest
claude plugin install bmad@bmad-method
```

### Step 3: Start Everything
```bash
docker compose up -d --build
docker compose exec backend uv run alembic upgrade head
make status
```

### Step 4: Verify
```bash
curl http://localhost:8000/health   # → {"status": "ok"}
curl http://localhost:3000          # → Next.js page
curl http://localhost:7700/health   # → Meilisearch ok
```

### Step 5: Start Developing
```bash
claude  # Start Claude Code session
# Then: /plan Phase 0 foundation
```

---

## Project Structure
```
production-ai-engineering-platform/
│
├── CLAUDE.md                          # Root context for Claude Code
├── Makefile                           # make dev, make test, make lint
├── docker-compose.yml                 # Full stack local dev
├── .env.example                       # Environment template
├── .gitignore
│
├── .claude/                           # Claude Code configuration
│   ├── settings.json                  # Hooks (auto-lint, secret detection)
│   ├── skills/                        # 8 development skills
│   │   ├── platform-architect/SKILL.md
│   │   ├── agent-developer/SKILL.md
│   │   ├── api-developer/SKILL.md
│   │   ├── frontend-developer/SKILL.md
│   │   ├── test-engineer/SKILL.md
│   │   ├── devops-engineer/SKILL.md
│   │   ├── ux-designer/SKILL.md
│   │   └── database-admin/SKILL.md
│   ├── agents/                        # 5 subagents
│   │   ├── architect.md               # Plans, designs, writes ADRs
│   │   ├── implementer.md             # Writes code in worktrees
│   │   ├── tester.md                  # Writes and runs tests
│   │   ├── reviewer.md                # Code review
│   │   └── documenter.md              # Documentation
│   ├── commands/                      # 5 slash commands
│   │   ├── implement.md               # /implement [feature]
│   │   ├── plan.md                    # /plan [feature/phase]
│   │   ├── agent-create.md            # /agent-create [name]
│   │   ├── review.md                  # /review [file/dir]
│   │   └── deploy-local.md            # /deploy-local
│   └── rules/
│       └── conventions.md             # Commit style, naming, comments
│
├── frontend/                          # Next.js 15 application
│   ├── CLAUDE.md                      # Frontend-specific context
│   ├── Dockerfile
│   ├── package.json
│   └── src/
│       ├── app/                       # App Router pages
│       │   ├── (public)/              # Landing pages (no auth)
│       │   ├── (portal)/              # Student portal (auth required)
│       │   └── (admin)/               # Admin dashboard
│       ├── components/
│       │   ├── ui/                    # shadcn/ui base
│       │   ├── features/             # CourseCard, AgentChat, etc.
│       │   └── layouts/              # PortalLayout, AdminLayout
│       ├── lib/
│       │   ├── api-client.ts          # Auto-gen from OpenAPI
│       │   └── hooks/
│       ├── stores/                    # Zustand stores
│       └── types/                     # Generated TypeScript types
│
├── backend/                           # FastAPI application
│   ├── CLAUDE.md                      # Backend-specific context
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic/                       # DB migrations
│   └── app/
│       ├── main.py                    # FastAPI factory
│       ├── api/v1/routes/             # Route handlers
│       │   ├── auth.py
│       │   ├── courses.py
│       │   ├── lessons.py
│       │   ├── exercises.py
│       │   ├── quizzes.py
│       │   ├── agents.py
│       │   ├── students.py
│       │   ├── admin.py
│       │   ├── webhooks.py
│       │   └── payments.py
│       ├── core/                      # Config, security, DB, Redis
│       ├── services/                  # Business logic
│       ├── agents/                    # 18+ AI agents
│       │   ├── base_agent.py
│       │   ├── moa.py                # Master Orchestrator
│       │   ├── socratic_tutor.py
│       │   ├── code_review.py
│       │   └── prompts/              # System prompts (markdown)
│       ├── models/                    # SQLAlchemy models
│       ├── schemas/                   # Pydantic schemas
│       ├── repositories/             # DB access layer
│       └── tasks/                    # Celery async tasks
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── AGENTS.md
│   ├── API.md
│   ├── DATABASE.md
│   ├── ADR/                          # Architecture Decision Records
│   └── lessons.md                    # Updated by Claude after corrections
│
├── nginx/
│   └── nginx.conf
│
├── monitoring/                        # Prometheus + Grafana configs
│
└── .github/workflows/
    └── ci.yml                         # Lint + test + build on push/PR
```

---

## Development Commands

| Command | What it does |
|---------|-------------|
| `make dev` | Start all Docker services |
| `make test` | Run all tests (backend + frontend) |
| `make lint` | Lint everything (ruff + mypy + eslint) |
| `make format` | Auto-format all code |
| `make deploy-local` | Build + start + migrate + health check |
| `make migrate` | Run database migrations |
| `make logs` | Follow all service logs |
| `make clean` | Stop everything, remove volumes |

---

## Claude Code Workflow

### Daily Development
```bash
# Start a session
claude

# Plan a feature
/plan student dashboard with progress tracking

# Implement it
/implement student dashboard page

# Review your work
/review frontend/src/app/(portal)/dashboard/

# Deploy locally
/deploy-local
```

### Parallel Development (Multiple Features)
```bash
# Terminal 1 — Frontend
claude --worktree feat-student-portal

# Terminal 2 — Backend APIs
claude --worktree feat-api-routes

# Terminal 3 — AI Agents
claude --worktree feat-socratic-tutor

# Terminal 4 — Infrastructure
claude --worktree feat-docker-monitoring

# Terminal 5 — Tests
claude --worktree feat-test-coverage
```

Each worktree is fully isolated. When done, create a PR from each worktree branch.

### Creating a New AI Agent
```bash
claude
/agent-create spaced-repetition "Schedules optimal review times using SM-2 algorithm"
```

This scaffolds: agent class, system prompt, tests, registry entry, and docs.

---

## The 18 AI Agents

| # | Agent | Category | Trigger |
|---|-------|----------|---------|
| 0 | Master Orchestrator (MOA) | Core | Every interaction |
| 1 | Content Ingestion | Creation | YouTube upload / GitHub push |
| 2 | Curriculum Mapper | Creation | After content ingestion |
| 3 | MCQ Factory | Creation | After curriculum mapping |
| 4 | Coding Assistant | Creation | Student PR opened |
| 5 | Student Buddy | Creation | Student asks for help |
| 6 | Deep Capturer | Creation | Weekly schedule |
| 7 | Socratic Tutor | Learning | Student learning question |
| 8 | Code Review | Learning | Student code submission |
| 9 | Spaced Repetition | Learning | Daily per-student schedule |
| 10 | Knowledge Graph | Learning | After quiz/exercise completion |
| 11 | Adaptive Path | Learning | After assessment scores |
| 12 | Adaptive Quiz | Analytics | Quiz session start |
| 13 | Project Evaluator | Analytics | Capstone submission |
| 14 | Progress Report | Analytics | Weekly + on-demand |
| 15 | Mock Interview | Career | Student request |
| 16 | Portfolio Builder | Career | Milestone completion |
| 17 | Job Match | Career | Weekly scan |
| 18 | Disrupt Prevention | Engagement | Engagement score drop |
| 19 | Peer Matching | Engagement | New student + weekly |
| 20 | Community Celebrator | Engagement | Milestone completion |

---

## Phase-by-Phase Implementation

### Phase 0: Foundation (Week 1)
Scaffolding, Docker, CI/CD, database schema. No business logic.
**Gate:** `docker compose up` works, `make test` passes, CI green.

### Phase 1: Auth + Landing Pages (Week 2)
JWT auth, OAuth, P1–P6 pages, email capture, Stripe.
**Gate:** User can register, login, view pages, make test payment.

### Phase 2: Student Portal (Week 3–4)
Dashboard, course view, video + code sync, progress tracking, exercises.
**Gate:** Student can browse, watch, code, submit, see progress.

### Phase 3: First 5 Agents (Week 5–7)
BaseAgent, MOA, Content Ingestion, Socratic Tutor, Code Review, Spaced Repetition, Adaptive Quiz.
**Gate:** Student can chat with tutor, get code reviews, take quizzes.

### Phase 4: Full Agent Ecosystem (Week 8–10)
Remaining 13+ agents, admin dashboard, mock interviews, portfolio, community.
**Gate:** All agents operational, admin metrics, interviews working.

### Phase 5: Polish + Launch (Week 11–12)
Performance, security audit, load testing, documentation, launch.
**Gate:** Lighthouse >90, tests pass, 0 critical issues, docs complete.

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Frontend | Next.js 15 + TypeScript + Tailwind + shadcn/ui | App Router, RSC, streaming, Vercel-native |
| Backend | FastAPI + Pydantic v2 | Async, auto-OpenAPI, type-safe |
| Agents | LangGraph + Claude API | Stateful multi-agent orchestration |
| Database | PostgreSQL 16 | JSONB flexibility + relational integrity |
| Cache | Redis 7 | Sessions, rate limiting, agent memory |
| Search | Meilisearch | Typo-tolerant full-text search |
| Vectors | Pinecone | Managed vector DB for RAG agents |
| Queue | Celery + Redis | Reliable async task processing |
| Auth | JWT + OAuth2 (GitHub, Google) | Standard, stateless, extensible |
| Payments | Stripe | Subscriptions + one-time + webhooks |
| CI/CD | GitHub Actions | Lint + test + build on every push |
| Infra | Docker Compose + Nginx | Single-command local dev |
| Monitoring | Prometheus + Grafana + Loki | Metrics, dashboards, logs |

---

## Contributing

1. Create a worktree: `claude --worktree feat-your-feature`
2. Plan: `/plan your feature description`
3. Implement: `/implement your feature`
4. Test: `make test`
5. Review: `/review`
6. Create PR from worktree branch
7. CI must pass before merge
