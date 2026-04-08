# Phase 5 — Security, Performance, Tests, Docs, Docker

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Harden the platform for launch — rate limiting, Redis caching, real webhook handlers, 10+ frontend tests, updated docs, Docker verification.

**Architecture:** Each task is self-contained. No model changes needed. All indexes already exist in migration 0001. Rate limiting via slowapi middleware on auth routes. Caching via redis.asyncio in courses service. Webhook handlers trigger existing agent/enrollment logic.

**Tech Stack:** FastAPI + slowapi, redis.asyncio, pytest, vitest, @testing-library/react

---

### Task 1: Rate Limiting (slowapi on auth endpoints)
**Files:** `backend/app/core/rate_limit.py` (create), `backend/app/api/v1/routes/auth.py` (modify), `backend/pyproject.toml` (modify)

### Task 2: Redis Caching on GET /courses
**Files:** `backend/app/services/course_service.py` (modify), `backend/app/core/redis.py` (verify)

### Task 3: Real Webhook Handlers
**Files:** `backend/app/api/v1/routes/webhooks.py` (modify)

### Task 4: Frontend Tests (10+ total)
**Files:** `frontend/src/test/components.test.tsx` (create)

### Task 5: Documentation Update
**Files:** `docs/ARCHITECTURE.md`, `docs/AGENTS.md`, `README.md`, `docs/lessons.md`

### Task 6: Docker Verification
**Run:** `docker compose build`
