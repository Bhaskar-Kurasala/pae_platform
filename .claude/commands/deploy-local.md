---
name: deploy-local
description: Build and deploy the full stack locally with Docker Compose
---

# /deploy-local — Local Deployment

## Steps
1. Verify Docker is running: `docker info`
2. Copy env file if not exists: `cp -n .env.example .env`
3. Build all images: `docker compose build`
4. Start all services: `docker compose up -d`
5. Wait for services to be healthy: `docker compose ps`
6. Run database migrations: `docker compose exec backend uv run alembic upgrade head`
7. Run health checks:
   - `curl -s http://localhost:8000/health | jq .`
   - `curl -s http://localhost:3000 -o /dev/null -w '%{http_code}'`
   - `curl -s http://localhost:7700/health | jq .`
8. Report status

## If Something Fails
- Check logs: `docker compose logs {service-name}`
- Rebuild single service: `docker compose build {service-name} && docker compose up -d {service-name}`
- Reset database: `docker compose down -v && docker compose up -d`
- Port conflict: check `lsof -i :3000` / `lsof -i :8000`

## Services and Ports
| Service | Port | Health Check |
|---------|------|-------------|
| Frontend | 3000 | GET / |
| Backend | 8000 | GET /health |
| PostgreSQL | 5432 | pg_isready |
| Redis | 6379 | redis-cli ping |
| Meilisearch | 7700 | GET /health |
| Nginx | 80 | GET / |
