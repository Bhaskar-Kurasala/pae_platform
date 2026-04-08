---
name: platform-architect
description: |
  Use when making architecture decisions, designing new features,
  reviewing system design, or writing Architecture Decision Records (ADRs).
  Trigger phrases: "architecture", "design", "ADR", "system design", "scalability"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, TodoWrite
---

# Platform Architecture Skill

## System Layers (top to bottom)
1. **Presentation** — Next.js 15, Tailwind, shadcn/ui
2. **API Gateway** — FastAPI, JWT auth, rate limiting
3. **Agent Orchestration** — LangGraph MOA, 18 agents, tool registry
4. **Business Logic** — Celery tasks, learning engine, payments
5. **Data** — PostgreSQL, Redis, Pinecone, MinIO/S3
6. **Infrastructure** — Docker, Nginx, Prometheus, GitHub Actions
7. **External** — YouTube, GitHub, Stripe, Discord, Claude API

## Architecture Decision Record (ADR) Template
```markdown
# ADR-{NNN}: {Title}
**Status:** Proposed | Accepted | Deprecated | Superseded
**Date:** YYYY-MM-DD
**Context:** What is the issue?
**Decision:** What did we decide?
**Consequences:** What are the trade-offs?
**Alternatives Considered:** What else did we evaluate?
```

## Key Principles
- Async everywhere (FastAPI, SQLAlchemy, Redis, Celery)
- Type safety end-to-end (Pydantic → OpenAPI → TypeScript)
- Agents as LangGraph nodes (stateful, evaluable, logged)
- Feature flags for gradual rollout
- Soft delete for all user data
- UUID primary keys for distributed safety

## When to Write an ADR
- Choosing between two viable technologies
- Changing an existing pattern
- Adding a new external dependency
- Any decision that would surprise a future developer
