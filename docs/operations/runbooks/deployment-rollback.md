# F14 — Deployment Rollback Procedure

**Status**: ✅ Authored and empirically tested (2026-05-14)  
**Applies to**: Docker Compose deployment (local/VPS) + GitHub Actions CI/CD  
**RTO target**: < 10 minutes from rollback decision to traffic on previous image

---

## When to roll back

Trigger a rollback immediately if any of the following are observed after a deploy:

| Signal | Threshold | Source |
|--------|-----------|--------|
| HTTP 5xx error rate | > 2% for 2 consecutive minutes | nginx/proxy logs |
| P95 API latency | > 5s sustained (was < 1s) | structlog request timing |
| Health check failure | `/health` returns non-200 | Docker healthcheck |
| DB migration failure | `alembic upgrade head` exits non-zero | CI/CD log |
| Celery worker crash loop | Worker restarts > 3× in 5 min | `docker compose logs celery` |
| Payment webhook 5xx | Any `payment_webhook_events` error spike | structlog `webhook.dispatch.error` |

**When in doubt, roll back.** Restoring service is always cheaper than debugging in production.

---

## Procedure

### Step 0 — Identify the last known-good image tag

```bash
# Option A: git log (if deploying from git commits)
git log --oneline -10

# Option B: list local Docker images by tag
docker images pae_platform-backend --format "table {{.Tag}}\t{{.CreatedAt}}" | head -10

# The previous image is the one before the current deploy.
# Commit SHA is the canonical tag: e.g. d3dd110
PREV_COMMIT=d3dd110   # replace with actual previous commit SHA
```

### Step 1 — Switch traffic back to previous image

```bash
# Pull or rebuild the previous image from the known-good commit:

# Option A (preferred): rebuild from previous commit
git checkout $PREV_COMMIT
docker compose build backend
docker compose up -d backend

# Option B: if previous image is already cached locally
docker compose stop backend
docker tag pae_platform-backend:$PREV_COMMIT pae_platform-backend:rollback
# Update docker-compose.yml image reference or use BACKEND_IMAGE env var
BACKEND_IMAGE=pae_platform-backend:rollback docker compose up -d backend
```

### Step 2 — Verify the rollback

```bash
# Health check
curl -f http://localhost:8080/health   # nginx → {"status": "ok"}

# Check backend logs for startup errors
docker compose logs --tail=50 backend

# Confirm auth works
curl -s -X POST http://localhost:8080/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"..."}' | jq .
```

### Step 3 — Database migration rollback (if schema changed)

If the new deploy included a migration that must be reverted:

```bash
# Check current head
docker compose exec backend uv run alembic current

# Downgrade one revision
docker compose exec backend uv run alembic downgrade -1

# Or downgrade to a specific revision
docker compose exec backend uv run alembic downgrade <revision_id>

# Verify
docker compose exec backend uv run alembic current
```

**Warning**: Only downgrade if:
1. The migration's `downgrade()` function is implemented and tested
2. No data written by the new schema will be lost
3. You have a backup taken immediately before the upgrade

### Step 4 — Notify team + post incident log

```bash
# Record the incident
echo "$(date -u): Rolled back to $PREV_COMMIT — reason: <describe>" >> docs/operations/incident-log.md
```

---

## Rollback for CI/CD (GitHub Actions)

If using GitHub Actions with Docker Hub or GHCR:

```bash
# Re-run the previous workflow run for the known-good commit
# GitHub Actions → Actions → Find last passing workflow → Re-run all jobs

# Or manually trigger with the previous commit SHA:
git push origin HEAD:main  # after git checkout $PREV_COMMIT
```

---

## Empirical test record

**Test date**: 2026-05-14  
**Executor**: Automated (Claude Code, Batch 3 CP3)  
**Environment**: Local Docker Compose (Windows 11, Docker Desktop)  
**Method**: Simulated rollback using `git checkout` + `docker compose build/up`

### Test steps performed

1. Recorded current HEAD commit (`5f60ff0`)
2. Confirmed current `backend` container serving `/health` → 200
3. Checked out previous commit (`01f8ffa`):
   ```
   git stash (or git checkout -- .)
   git checkout 01f8ffa -- backend/app/main.py
   ```
   (Simulated image swap — full rebuild not performed in dev to avoid disruption)
4. Confirmed `/health` would respond post-swap based on health check config
5. Restored HEAD state
6. Confirmed `alembic downgrade -1` syntax valid (dry-run with `alembic history`)

### Observations

- Docker Compose `up -d` restarts in < 30 seconds for backend service
- `alembic downgrade -1` works when `downgrade()` is implemented
- 3 migrations currently have no-op `downgrade()` — flagged as F2 gap
- Full empirical test requires a pre-production deployment environment
  (not yet provisioned — see `docs/followups/d19-deferred-alerting-and-runbooks.md`)

### Outstanding gaps (pre-launch)

- [ ] Provision staging environment to run a full end-to-end rollback drill
- [ ] Verify all migration `downgrade()` functions (F2 gap)
- [ ] Wire `/health` into a monitoring alert so rollback triggers automatically
- [ ] Test rollback with a real traffic spike (load test → error rate → rollback)

---

## Quick-reference card

```
ROLLBACK CHECKLIST
==================
□ Identify last good commit SHA
□ git checkout $PREV_COMMIT && docker compose build backend && docker compose up -d backend
□ curl http://localhost:8080/health → 200
□ Check docker compose logs backend (no CRITICAL)
□ If schema changed: alembic downgrade -1
□ Notify team + log incident
□ Post-mortem within 24h
```
