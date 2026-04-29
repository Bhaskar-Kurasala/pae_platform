# Admin account management

How to promote, demote, or audit admin users in production. Pairs with
`docs/runbooks/secret-rotation.md` and `docs/runbooks/oncall.md`.

---

## Why this is a runbook, not a UI

Promoting a user to admin gives them the keys to:

- Every student's progress, learning data, and chat transcripts (`/admin/students`)
- The platform's full activity feed (`/admin/audit-log`)
- Manual agent triggers and content moderation (`/admin/agents`)
- The at-risk students list (`/admin/at-risk`) — pre-PII surfaced for outreach

That's a **trust-the-operator** action. Building a "self-serve admin invite" UI for it would be a security regression: any compromised admin account could promote arbitrary attackers. So promotion stays a deliberate, audited DB operation, run by someone with shell access to production.

If/when we eventually build a UI: it should require **two existing admins to co-sign** a promotion, and write to the `audit-log` with both their user ids. That's a real feature, not in this PR.

---

## TL;DR — promote one user

```bash
# 1. The person to promote first creates a normal account at /register.
# 2. The platform owner (you) runs:
fly postgres connect --app pae-platform-db <<EOF
UPDATE users SET role='admin' WHERE email='new.admin@yourdomain.com'
RETURNING email, role, updated_at;
EOF

# 3. The new admin signs out + signs back in. Their JWT now carries
#    role=admin and they can see /admin/* routes.
```

That's it. Keep reading for the why and the safety rails.

---

## The role column

`users.role` is a `String(50)` defaulting to `"student"`. Three values are recognized in code today:

| Value | Where it's checked |
|---|---|
| `student` | Default for every register. No special routes. |
| `admin` | `app/api/v1/routes/admin.py::_require_admin` gates every `/api/v1/admin/*` route. Returns 403 for non-admins. |
| `service` | Used by `agent_actions.actor_role` for system-initiated runs (Celery, scheduled jobs). Never assigned to a human. |

There are NO other roles. Don't invent `superadmin` or `editor` without an ADR — the dependency tree of code that branches on `role` is small precisely because we only have two human values.

---

## Production flow — promoting a user

### Pre-flight: confirm the person exists

```bash
fly postgres connect --app pae-platform-db <<EOF
SELECT email, role, is_active, created_at
FROM users
WHERE email='new.admin@yourdomain.com';
EOF
```

If you get zero rows, they haven't registered yet. Send them to the `/register` page first. **Never** create a user via direct INSERT — it bypasses `auth_service.register()`'s password-hashing, default-cohort assignment, and the `auth.signed_up` PostHog event.

### Promote

```bash
fly postgres connect --app pae-platform-db <<EOF
UPDATE users
SET role='admin', updated_at=NOW()
WHERE email='new.admin@yourdomain.com'
RETURNING id, email, role, updated_at;
EOF
```

The `RETURNING` clause is your audit trail — copy the output to wherever you're tracking admin grants (e.g. an internal Notion page).

### Verify

The new admin must **sign out and back in** for their JWT to refresh with the new role claim. Until they do, their existing session still says `role=student` and they'll get 403s on `/admin/*`.

After they re-login, have them hit:

```bash
curl https://pae-platform.fly.dev/api/v1/admin/stats \
  -H "Authorization: Bearer $THEIR_TOKEN"
```

A 200 with stats JSON = success. A 403 = they didn't fully sign out (cached JWT).

---

## Demoting an admin

Same shape, opposite direction:

```bash
fly postgres connect --app pae-platform-db <<EOF
UPDATE users
SET role='student', updated_at=NOW()
WHERE email='former.admin@yourdomain.com'
RETURNING id, email, role, updated_at;
EOF
```

**Important:** demotion only takes effect on next JWT refresh. The current access token (issued when they were admin) is valid for up to 30 minutes by default — they retain admin powers for that window. If you're demoting because of a security incident, ALSO:

1. Reset their password (forces a re-login):
   ```sql
   UPDATE users SET hashed_password='!revoked!' WHERE email='...';
   ```
2. Revoke any active refresh tokens. We don't have a `refresh_tokens` table yet (refresh JWT is stateless), so the practical revoke is rotating `SECRET_KEY` per the secret-rotation runbook — that invalidates ALL active sessions platform-wide, but it's the correct nuclear option for a breach.

---

## Auditing — who is currently admin?

Run this monthly. Copy the output to your internal tracking.

```bash
fly postgres connect --app pae-platform-db <<EOF
SELECT email, full_name, created_at, updated_at
FROM users
WHERE role='admin' AND is_active=true
ORDER BY updated_at DESC;
EOF
```

Three things to look for:

1. **Anyone you don't recognize.** Investigate immediately.
2. **`updated_at` recently changed for someone you didn't promote.** Possible incident — check `agent_actions` audit log for the role change.
3. **Inactive admins (`is_active=false` with `role='admin'`).** Demote them. An inactive admin account is a dormant attack surface.

---

## Local development

For dev-only smoke testing (the flow we just used):

```bash
# Register two test accounts via the API
curl -X POST http://localhost:8080/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"student@pae.dev","password":"Student123!","full_name":"Test Student"}'

curl -X POST http://localhost:8080/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@pae.dev","password":"Admin123!","full_name":"Test Admin"}'

# Promote the admin one
docker exec pae_platform-db-1 psql -U postgres -d platform \
  -c "UPDATE users SET role='admin' WHERE email='admin@pae.dev';"
```

Pydantic's email validator rejects `.test` / `.invalid` / other reserved TLDs. Use a real-looking domain (`.dev`, `.com`) for local accounts.

---

## What admin can see

This is the value of the role — the screens locked behind `_require_admin`:

| Screen | What it shows |
|---|---|
| `/admin` (console) | Top-line stats: active students, daily LLM cost, error rate |
| `/admin/at-risk` | Students with low engagement scores — your outreach list |
| `/admin/students` | Full student roster + per-student timeline |
| `/admin/students/{id}/timeline` | Per-student activity feed (lessons, exercises, chat sessions) |
| `/admin/pulse` | Real-time activity heatmap |
| `/admin/audit-log` | Every agent_action and admin_action with actor + target |
| `/admin/feedback` | User-submitted feedback queue |
| `/admin/confusion` | Confusion heatmap — concepts students keep getting wrong |
| `/admin/content-performance` | Per-lesson completion + abandonment rates |
| `/admin/agents` | Manual agent invocation (e.g. force a re-grade) |
| `/admin/courses` | Course CRUD |

The PR3/C7.1 `llm.call` events feed `daily LLM cost` on the console page directly — no extra PostHog query needed.

---

## When something goes wrong

**"I promoted them but they still see 403."**
They didn't fully sign out. Cookie + localStorage both need clearing. Have them open DevTools → Application → Storage → Clear site data, then re-login.

**"The UPDATE returned 0 rows."**
Email mismatch (case-sensitive in some Postgres collations) or the user never registered. Confirm with the pre-flight SELECT.

**"I demoted them but they're still seeing /admin/* pages."**
Their access token is still cached client-side. Their NEXT API call will get 403, but the static admin shell stays rendered until then. Tell them to navigate (Ctrl+L → /today) to force a router transition; the auth guard will redirect.
