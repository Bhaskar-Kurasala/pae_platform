---
name: devops-engineer
description: |
  Use for Docker, CI/CD, deployment, monitoring, and infrastructure tasks.
  Trigger phrases: "docker", "deploy", "CI", "monitoring", "nginx"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, TodoWrite
---

# DevOps Skill

## Docker Compose — Full Stack
`docker compose up -d` starts: frontend, backend, celery-worker, db, redis, meilisearch, nginx

## Health Checks
```bash
curl http://localhost:8000/health    # Backend
curl http://localhost:3000           # Frontend
curl http://localhost:7700/health    # Meilisearch
docker compose ps                   # All services status
```

## Deployment Targets
- **Local**: Docker Compose (this is what we use for development)
- **Staging**: Vercel (frontend) + Railway (backend + DB + Redis)
- **Production**: Vercel (frontend) + AWS ECS/Fargate (backend) + RDS + ElastiCache

## CI/CD: GitHub Actions
Every push runs: ruff + mypy (backend), eslint (frontend), pytest, vitest, build
PR to main additionally runs: Playwright E2E, docker build verification

## Monitoring Stack
- Prometheus: metrics collection (API latency, agent cost, error rates)
- Grafana: dashboards and alerting
- Loki + Promtail: centralized logging
