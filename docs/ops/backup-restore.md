# Backup & Restore Runbook

## PostgreSQL

### Manual backup

```bash
docker compose exec db pg_dump -U $POSTGRES_USER $POSTGRES_DB > backup-$(date +%Y%m%d).sql
```

### Restore

```bash
docker compose exec -T db psql -U $POSTGRES_USER $POSTGRES_DB < backup-YYYYMMDD.sql
```

### Automated backups

Set `PG_BACKUP_SCHEDULE` in your hosting environment. Recommended: daily at 02:00 UTC,
retain 7 days.

For managed hosting (Railway, Render, Supabase): enable the built-in daily snapshot feature
and set retention to 7 days.

## Redis

Redis data (conversation history, sessions) is ephemeral by design. No backup needed.

- Conversation history TTL: 1 hour — acceptable data loss window.
- Session loss = users re-login (< 30s UX impact).
- Interview sessions TTL: 2 hours — acceptable loss; user can restart.

If you need Redis persistence for audit purposes, enable AOF in `redis.conf`:
```
appendonly yes
appendfsync everysec
```

## Alembic migrations

Every schema change has a migration in `backend/alembic/versions/`.

To verify the DB is at the expected revision:
```bash
docker compose exec backend uv run alembic current
docker compose exec backend uv run alembic history
```

To apply pending migrations after a restore:
```bash
docker compose exec backend uv run alembic upgrade head
```

## Disaster recovery checklist

1. Restore DB from latest backup (see PostgreSQL section above)
2. `docker compose exec backend uv run alembic upgrade head`
3. `docker compose restart backend worker`
4. Verify: `curl http://localhost:8000/health/ready`
5. Smoke test: login, load a course, run one agent action

Recovery time objective (RTO): < 30 minutes with a recent backup.
Recovery point objective (RPO): < 24 hours with daily backups.

## Environment variables required after restore

Ensure these are set in your `.env` (or hosting secrets) before restarting:

| Variable | Purpose |
|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` | DB credentials |
| `SECRET_KEY` | JWT signing key — must match what issued existing tokens |
| `ANTHROPIC_API_KEY` | Claude API access |
| `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` | Payment processing |
| `REDIS_URL` | Cache + session store |
