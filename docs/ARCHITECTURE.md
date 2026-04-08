# Architecture — Production AI Engineering Platform

## System Overview

A git-based learning platform with 18+ AI agents that automates content creation,
student learning, career support, and community engagement. One human (you) injects
knowledge; the system turns it into a self-serving learning machine.

## 7-Layer Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: PRESENTATION                                       │
│  Next.js 15 · Tailwind · shadcn/ui · React Query · Zustand  │
│  Public pages · Student portal · Admin dashboard · Agent chat│
├─────────────────────────────────────────────────────────────┤
│  Layer 2: API GATEWAY                                        │
│  FastAPI · JWT/OAuth2 · Rate limiting · OpenAPI generation   │
│  WebSockets for real-time agent chat                         │
├─────────────────────────────────────────────────────────────┤
│  Layer 3: AGENT ORCHESTRATION                                │
│  LangGraph MOA · 18 specialized agents · Tool registry       │
│  Agent memory (Redis short-term + Postgres long-term)        │
├─────────────────────────────────────────────────────────────┤
│  Layer 4: BUSINESS LOGIC                                     │
│  Celery tasks · Learning engine · Payment processing         │
│  GitHub integration · Exercise grading · Notifications       │
├─────────────────────────────────────────────────────────────┤
│  Layer 5: DATA                                               │
│  PostgreSQL 16 · Redis 7 · Pinecone · MinIO/S3 · Meilisearch│
├─────────────────────────────────────────────────────────────┤
│  Layer 6: INFRASTRUCTURE                                     │
│  Docker Compose · Nginx · Gunicorn+Uvicorn · Prometheus      │
│  Grafana · Loki · GitHub Actions CI/CD                       │
├─────────────────────────────────────────────────────────────┤
│  Layer 7: EXTERNAL INTEGRATIONS                              │
│  YouTube API · GitHub API · Stripe · Discord · Claude API    │
│  SendGrid · OpenAI (fallback) · Gumroad                     │
└─────────────────────────────────────────────────────────────┘
```

## Agent Architecture

All 18 agents are LangGraph nodes coordinated by the Master Orchestrator Agent (MOA).

### Agent Categories
- **Creation** (5): Content Ingestion, Curriculum Mapper, MCQ Factory, Coding Assistant, Student Buddy, Deep Capturer
- **Learning** (5): Socratic Tutor, Code Review, Spaced Repetition, Knowledge Graph, Adaptive Path
- **Analytics** (3): Adaptive Quiz, Project Evaluator, Progress Report
- **Career** (3): Mock Interview, Portfolio Builder, Job Match
- **Engagement** (3): Disrupt Prevention, Peer Matching, Community Celebrator

### Agent Communication Flow
```
Student Request → API Gateway → MOA → [Route to Agent] → Agent executes
                                  ↓                         ↓
                            Evaluate response          Log action
                                  ↓                         ↓
                         Deliver to student          Update metrics
```

## Data Flow
```
You create content → YouTube upload / GitHub push
                          ↓
                   Content Ingestion Agent
                          ↓
                   Curriculum Mapper Agent
                          ↓
                   MCQ Factory Agent
                          ↓
            Content available in Knowledge Base
                          ↓
         Students learn via portal + AI agents
                          ↓
         Progress tracked, exercises graded, paths adapted
```

## Key Technical Decisions
See `docs/ADR/` for detailed Architecture Decision Records.
- ADR-001: Next.js 15 over Remix (App Router + RSC + Vercel deployment)
- ADR-002: LangGraph over CrewAI (stateful orchestration, tool use, evaluation)
- ADR-003: PostgreSQL over MongoDB (relational integrity, JSONB flexibility)
- ADR-004: Celery over FastAPI BackgroundTasks (reliability, retry, monitoring)
- ADR-005: Pinecone over Chroma (managed service, scale, production-ready)
