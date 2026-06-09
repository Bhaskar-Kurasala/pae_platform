# Runbook — Secret rotation

**Owner:** Bhaskar
**Severity:** P1 (security hygiene; P0 if there's an active leak)
**SLA target:** A new JWT secret is live in production within 30 minutes
once you decide to rotate.

This runbook is **process docs only** — no actual secrets live in this
file or in any tracked file in the repo. The repo's `.env` is gitignored;
production secrets live in Fly secrets storage.

---

## When to rotate

| Trigger | Window | Notes |
|---|---|---|
| Quarterly hygiene rotation | 90 days | Calendar reminder. Same procedure as below; users get a forced re-login. |
| Suspected JWT leak | Immediate | Treat as a security incident — rotate first, investigate after. |
| Engineer departure with `fly secrets list` access | Within 24h | Includes contractors. |
| Anthropic / Razorpay key exposed in a log line | Immediate | Different keys, same urgency. |
| Major framework CVE (e.g. JWT library RCE) | Within the CVE's recommended window | After patching, rotate to invalidate any tokens minted by the vulnerable code. |

---

## 1 — Generate a new 32-byte JWT secret

A 32-byte (256-bit) random secret is the minimum for HS256. Anything
shorter is a weakening attack vector.

Generate locally — never copy the output into chat, email, or a ticket.

### Option A — Python (preferred; matches our stack)

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
# → e.g. y7iYr1Gc8nP… (44 base64-url chars)
```

`token_urlsafe(32)` returns 32 random bytes URL-safe-base64-encoded.
The resulting string is 43 chars long (no padding). Anything longer is
also fine.

### Option B — OpenSSL

```bash
openssl rand -base64 32
# → e.g. y7iYr1Gc8nP…=
```

### Option C — `/dev/urandom` (no deps)

```bash
head -c 32 /dev/urandom | base64
```

**All three produce equivalent output.** Pick whichever your shell has.

---

## 2 — Sanity-check the value

Before pushing it to production, confirm it would survive the
`production_required` validator (PR3/D2.2):

| Property | Required? |
|---|---|
| Length ≥ 32 chars | Yes |
| Not equal to any of the literal dev defaults | Yes |
| Doesn't start with the substring `changeme` | Yes |
| Doesn't contain a space | Recommended (Fly's secrets system handles them, but shell pasting gets gnarly) |

Quick check:

```bash
NEW="<paste-secret>"
[ ${#NEW} -ge 32 ] && echo "OK: long enough" || echo "FAIL: too short"
```

---

## 3 — Roll the secret in production

We do **rotate-with-grace** — a window where both old and new secrets
verify, so existing user sessions don't all log out at once.

> **NOTE:** The current backend uses a single `secret_key` setting and
> validates with one HS256 secret. Multi-secret verification is not yet
> implemented (filed as a follow-up below). Until that lands, rotation
> is a *hard cutover* — every active user gets logged out and must
> sign in again. Schedule the rotation for a low-traffic window (US
> 03:00–05:00 UTC) and post a banner.

### 3.1 — Hard-cutover procedure (current state)

```bash
# 1. Set the new secret as a Fly secret on the API app.
fly secrets set JWT_SECRET_KEY="<new-secret>" -a pae-platform

# 2. Fly automatically rolls the API machines (~30s).
fly status -a pae-platform

# 3. Watch logs for clean startup.
fly logs -a pae-platform | grep -E "app.startup|FATAL"

# 4. Hit /health/ready (PR3/C6.1) to confirm.
curl -fsSL https://app.example.com/health/ready
```

### 3.2 — Confirm old tokens are rejected

```bash
# Old token from before the rotation. Should now return 401.
curl -i https://app.example.com/api/v1/today/summary \
    -H "Authorization: Bearer <old-token>"
# Expect: HTTP/1.1 401 Unauthorized
```

If the old token still works, the rotation didn't take effect — the
`secret_key` env var didn't propagate. Check `fly secrets list` and
re-deploy if needed.

### 3.3 — Notify users

If this was an incident-driven rotation: post a status banner saying
"signed out; please sign back in". Avoid revealing the underlying
reason (security through normal disclosure channels — incident
post-mortem 24–72h later).

---

## 4 — Other secrets

Same procedure applies to:

| Secret | Fly env var name | Where it lives |
|---|---|---|
| Anthropic API key | `ANTHROPIC_API_KEY` | Fly secrets, Anthropic console |
| Razorpay key + secret | `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` | Fly secrets, Razorpay dashboard |
| Razorpay webhook secret | `RAZORPAY_WEBHOOK_SECRET` | Fly secrets, Razorpay dashboard |
| Neon DB password | `DATABASE_URL` (rotated by Neon's "Reset password" button on the role) | Fly secrets, Neon dashboard |
| R2 access keys | `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` (on the **backup** app) | Fly secrets on `pae-platform-backup` |
| Sentry DSN | `SENTRY_DSN` (PR3/C5.1) | Fly secrets, Sentry project settings |
| PostHog project API key | `POSTHOG_PROJECT_API_KEY` (PR3/C3.1) | Fly secrets, PostHog project settings |

Procedure for each:
1. Generate / regenerate at the upstream provider.
2. `fly secrets set <NAME>=<value> -a pae-platform` (or `pae-platform-backup` for backup-only secrets).
3. Verify with a representative request (see test column in the table below).

| Secret | Test |
|---|---|
| `ANTHROPIC_API_KEY` | Trigger an LLM call (`POST /api/v1/senior-review`). |
| `RAZORPAY_KEY_*` | Open the catalog and start a checkout — Razorpay JS will fail loudly on a bad key. |
| `RAZORPAY_WEBHOOK_SECRET` | Replay a webhook from the Razorpay dashboard — check it processes. |
| `DATABASE_URL` | `/health/ready` returns `db: "ok"`. |
| `R2_*` (backup app) | `fly machine run … --command /home/backup/backup.sh -a pae-platform-backup` and check Fly logs for `[backup] success`. |
| `SENTRY_DSN` | Send a test event from Sentry's project settings. |
| `POSTHOG_PROJECT_API_KEY` | Click around the demo user; events should land in PostHog. |

---

## 5 — Local dev secrets

Local dev uses `.env` at the repo root (gitignored). Expected layout:

```env
ENVIRONMENT=development
SECRET_KEY=local-dev-secret-not-secure
ANTHROPIC_API_KEY=sk-ant-…
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/platform
REDIS_HOST=localhost
REDIS_PORT=6381
```

**Never copy a production secret into your local `.env`.** Local dev
runs against the local Postgres + Redis containers — there's no need.

---

## 6 — Multi-secret rotation (filed follow-up)

The current backend uses a single `secret_key`. To support a no-downtime
rotation, we need to:

1. Add a `secret_keys: list[str]` setting (primary first, deprecated old
   keys after).
2. `verify_token` tries each key in order; the first one that decodes
   wins.
3. `create_token` always signs with `secret_keys[0]`.
4. After 7 days (longer than the longest token expiry), drop the old
   keys from the list.

This is a small change but out of scope for PR3/D2. File when needed.
For now, document the hard-cutover procedure (§3.1) and pick low-traffic
windows.

---

## 7 — Rotation log

Append a one-liner here every rotation. (Last 12 months.)

| Date | Operator | Secret | Reason | Notes |
|---|---|---|---|---|
| (first rotation pending) | | | | |
