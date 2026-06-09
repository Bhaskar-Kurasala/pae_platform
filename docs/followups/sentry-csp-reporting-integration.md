# Sentry CSP Reporting Integration

## Current State

CSP violations are logged to structlog only (`csp.violation` key).
Sentry is initialised in `frontend/src/lib/sentry.ts` with `integrations: []` — the
Sentry CSP tunnel / CSP reporting endpoint is not wired.

## What Sentry Offers

Sentry can receive CSP violation reports directly via its tunnel endpoint
(`/api/<project_id>/security/?sentry_key=<dsn_public_key>`). This gives:
- Violations correlated with user sessions and breadcrumbs
- Automatic grouping by `blocked-uri` + `violated-directive`
- Integration with error volume dashboards

## Wiring Plan

### Option A — Sentry as CSP report destination (preferred)

Add a second `report-uri` to the CSP header pointing at Sentry's security endpoint:

```
report-uri /api/v1/csp-report https://o<org_id>.ingest.sentry.io/api/<project_id>/security/?sentry_key=<public_key>
```

Multiple URIs are space-separated. Both our backend logger and Sentry will receive every report.

Steps:
1. Find your Sentry project DSN in Sentry → Project Settings → Client Keys (DSN).
2. Extract `https://o<org>.ingest.sentry.io/api/<project_id>/security/?sentry_key=<pubkey>`.
3. Append it (space-separated) to `report-uri` in both `middleware.ts` and `nginx.conf`.
4. Verify in Sentry → Issues → Security Reports tab within 24 h.

### Option B — Sentry `@sentry/nextjs` integration

The `@sentry/nextjs` package ships a `SentrySessionReplay` and `BrowserTracing` integration
but does NOT natively consume CSP reports. Option A is simpler and does not require code changes.

## Environment Variables Needed

```bash
NEXT_PUBLIC_SENTRY_DSN=https://...@o<org>.ingest.sentry.io/<project_id>
SENTRY_ORG=your-org-slug
SENTRY_PROJECT=your-project-slug
```

These are already expected by the existing `frontend/src/lib/sentry.ts` initialisation.

## Priority

Low — structlog captures violations adequately for the Report-Only phase.
Upgrade to Sentry when switching to enforcing mode (see `docs/followups/csp-enforcing-mode-cutover.md`).
