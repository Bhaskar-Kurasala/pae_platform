# Uptime alert (UptimeRobot)

D19.2 D-A Alert 2. The second of the two operational alerts shipped
at cohort-1 launch scope.

**Status:** founder-side prerequisite documented; agent-side
verification (`/health` returns 200) is shipped and tested as part
of D19.2 closure-time Phase B run.

## Founder-side prerequisite

The agent doesn't create accounts. The founder owns these steps
once before D19.2 launch:

1. **Sign up for UptimeRobot free tier:** https://uptimerobot.com/
   — 50 monitors, 5-min check interval, email alerts on the free
   tier. No credit card required.
2. **Create one HTTP(s) monitor:**
   - Type: HTTP(s)
   - URL: `https://<production-host>/health` (Fly.io production
     URL — typically `https://aicareeros.fly.dev/health` or the
     custom domain)
   - Friendly name: `aicareeros-prod-health`
   - Monitoring interval: 5 minutes (default)
   - HTTP method: GET
   - Expected status code: 200
3. **Set up alert contact:**
   - Email: founder's primary email
   - Notification when monitor goes DOWN: enabled
   - Notification when monitor comes UP again: enabled
4. **Capture the monitor ID** (visible in the URL after creation).
   No action required to feed it back into the codebase — the
   monitor pulls from production; the codebase doesn't push to
   UptimeRobot.

## What the monitor checks

The platform's existing `/health` endpoint
(`backend/app/api/v1/routes/health.py`) returns `{"status": "ok",
"version": "0.1.0"}` when the backend process is alive and the
FastAPI app is serving. It does **not** check downstream
dependencies (DB, Redis, etc.); that's the `/health/ready`
endpoint's job (see `fly.toml [http_service.checks]`).

UptimeRobot's monitor is the **liveness** signal — "is the box
on?" — so it points at `/health` rather than `/health/ready`.
The 5-min cadence + 5-min consecutive-failure threshold (default
in UptimeRobot) means the founder gets paged 5-10 minutes after
production goes fully unreachable.

## What to do when it fires

1. **Verify the alert isn't a UptimeRobot transient.** Check
   https://uptimerobot.com/ status page; if their probe is having
   regional issues, the alert may resolve on its own. (Rare; <1%
   of alerts.)
2. **Check Fly.io status:** `fly status -a <app-name>`. If
   machines are stopped / unhealthy, restart: `fly machine
   restart <id>`.
3. **Check production logs:** `fly logs -a <app-name>`. Recent
   crash → look for the unhandled exception → consult Sentry for
   the error event with full correlation IDs.
4. **If full outage persists >10 min:** founder-side
   communication to active cohort-1 users (in-platform message,
   Slack channel, email — whatever channel the cohort uses).

## Smoke test procedure

After UptimeRobot monitor is configured:

1. Temporarily change the monitor URL to a deliberately-broken path
   (e.g., `/health-DOES-NOT-EXIST`). Save.
2. Wait 5-10 minutes. Verify email arrives.
3. Restore the monitor URL to `/health`. Save.
4. Verify the "monitor is back UP" email arrives (UptimeRobot
   sends this when the monitor recovers).

Document the smoke completion timestamp in
`docs/operations/alerts/CHANGELOG.md`.

## Why not a self-hosted health-check

UptimeRobot free tier is $0/month; matches the D-E cost target.
A self-hosted external prober would need its own deployment +
its own uptime watchdog (the watchdog watches the watchman),
and "the watcher gets watched by Fly's own infrastructure" is
exactly the cyclic-dependency problem an external service
solves cleanly.

## Cross-references

- /health endpoint: [`backend/app/api/v1/routes/health.py`](../../../backend/app/api/v1/routes/health.py)
- Fly health check config: [`fly.toml`](../../../fly.toml) `[http_service.checks]`
- D19.1 substrate: [`docs/architecture/d19-1-observability-overview.md`](../../architecture/d19-1-observability-overview.md)
- Sentry review: [`docs/operations/sentry-review-process.md`](../sentry-review-process.md)
