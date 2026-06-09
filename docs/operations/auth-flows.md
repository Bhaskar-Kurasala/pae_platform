# Auth Flows — Operations Reference

Canonical reference for CP2 auth hardening (Batch 1). Covers registration, verification, login security, password reset, OAuth, and supporting infrastructure.

---

## 1. Registration Flow (D-B)

**Endpoint:** `POST /api/v1/auth/register`

Always returns `202 Accepted` — never `409`. The response body is identical regardless of the internal branch taken.

```json
{ "message": "If this email is new, a verification link has been sent." }
```

**Internal branches (all return 202):**

| Condition | Action |
|---|---|
| New email | Create user, run side-effects |
| Existing active user | No-op |
| Existing soft-deleted user | No-op |

**Side-effects on new registration** — all best-effort, never block the 202 response:

- `cohort_event(kind="signup")` — analytics event
- `grant_signup_grace()` — inserts 24h free-tier window into `free_tier_grants` (raw SQL, not a model)
- `send_email_verification()` — creates an `auth_token` of type `email_verify` (24h TTL) and sends email

New users start with `is_verified=False`.

---

## 2. Email Verification (A2)

**Endpoint:** `POST /api/v1/auth/verify-email`

```json
{ "token": "<raw_token>" }
```

**Validation chain:**

1. Token exists in `auth_tokens`
2. `token_type == "email_verify"`
3. Not expired (TTL: 24h)
4. Not already used (`used_at IS NULL`)

**On success:** sets `is_verified=True`, marks token consumed (one-use, sets `used_at`).

**400** on: missing token, wrong type, expired, or already used.

**Grandfathered users:** Migration `0069` sets `is_verified=True` for all users created before CP2. No verification email is required for pre-existing accounts.

---

## 3. Login Security Gate (D-C)

**Endpoint:** `POST /api/v1/auth/login`

Gate order is fixed (Pattern 35) — evaluated top to bottom, first failure short-circuits:

```
1. is_locked()         → 423 Too Many Requests
2. verify_password()   → 401  (increments failed_login_count)
3. is_active           → 403
4. is_verified         → 403
5. (pass)              → issue tokens, record_successful_login()
```

**Lockout mechanics:**

- 5 consecutive failures trigger lockout: `locked_until = now + 15min`
- Sliding window — each failed attempt *while locked* extends `locked_until` by another 15min
- `record_successful_login()` resets `failed_login_count=0` and `locked_until=None`

**Model constants** (on `User`):**

```python
_LOCKOUT_MAX_ATTEMPTS = 5
_LOCKOUT_DURATION_MINUTES = 15
```

---

## 4. Password Reset (A1)

### Request

**Endpoint:** `POST /api/v1/auth/password-reset/request`
Rate-limited: 5 requests/minute.

Always returns `202` — no email-existence leakage:

```json
{ "message": "If that email is registered, a reset link has been sent." }
```

Creates an `auth_token` of type `password_reset` (TTL: 1h) and sends reset email.

### Confirm

**Endpoint:** `POST /api/v1/auth/password-reset/confirm`

```json
{
  "token": "<raw_token>",
  "new_password": "<new_pw>"
}
```

- `new_password` is re-validated against D-D complexity rules
- On success: updates `hashed_password`, calls `record_successful_login()` (clears any lockout)
- Token is consumed (one-use)
- **400** for expired, used, or wrong-type token

---

## 5. Password Complexity (D-D)

Enforced at the schema layer via `UserCreate.validate_password_complexity` (`@field_validator`). The service is never called if validation fails.

**Rules:**

- `len(password) >= 12`
- Not in `_COMMON_PASSWORDS` frozenset (19 entries)

**Response on failure:** `422 Unprocessable Entity`

> **Note:** `"admin12345678"` is intentionally absent from `_COMMON_PASSWORDS`. Test fixtures use it as the admin password — do not add it to the blocklist.

---

## 6. OAuth Auto-Verification

**Endpoints:**
- `POST /api/v1/auth/oauth/github/callback`
- `POST /api/v1/auth/oauth/google/callback`

| Condition | `is_verified` | Other effects |
|---|---|---|
| New OAuth user | Set to `True` (provider verified email) | User created |
| Existing user | Unchanged | `avatar_url`, `github_username` updated |

OAuth users have `hashed_password=None`. Password-based login will fail at `verify_password()`.

---

## 7. AuthToken Model

**Table:** `auth_tokens`

```
uuid PK
user_id     FK → users
token_hash  TEXT   -- SHA-256 hex digest of raw token
token_type  TEXT   -- "email_verify" | "password_reset" | "email_change"
expires_at  DATETIME
used_at     DATETIME (nullable)
ip_address  TEXT (nullable)
```

**Key behaviors:**

- Raw token is **never stored** — only `sha256(raw_token).hexdigest()`
- `is_valid()` = `not is_expired() AND not is_used()`
- `cleanup_expired()` — deletes tokens where `expires_at < now() - 7 days` (background job)

**TTLs:**

| `token_type` | TTL |
|---|---|
| `email_verify` | 24h |
| `password_reset` | 1h |
| `email_change` | 1h |

---

## 8. Email Rate Limiting (D-F / G1)

**Function:** `check_email_rate_limit(user_id, token_type)`

- **Limit:** 5 sends per `user_id` per `token_type` per hour (types are independent)
- **Backend:** Redis `INCR` with TTL on a namespaced key
- **Key format:** `namespaced_key("email_rate", user_id, token_type, hour_bucket)`
- **Fail-open:** if Redis is unavailable, the send is permitted and a warning is logged — email is never silently blocked due to infra failure

---

## 9. OAuth Callback URLs (A4)

All redirect/callback URLs are built from `settings.public_base_url`. Never hardcoded.

**Relevant functions:**

```python
_frontend_dashboard()     # post-auth success redirect
_frontend_error()         # post-auth failure redirect
_github_callback_url()    # registered with GitHub OAuth app
_google_callback_url()    # registered with Google OAuth app
```

**Configuration:** Set `PUBLIC_BASE_URL` in `.env` for each deployment environment. Mismatch between this value and the URL registered with the OAuth provider will cause callback failures.

---

## 10. Test Infrastructure Notes

### `_auto_verify_registered_users` fixture

Location: `conftest.py` (autouse, session or function scope)

Patches `AuthService.register` to set `is_verified=True` immediately after user creation. This lets all existing test helpers call `register → login` without a verification step.

**To test unverified state:** bypass the patched service by creating the user directly via ORM:

```python
user = User(..., is_verified=False)
db_session.add(user)
db_session.commit()
```

### SQLite test DB coverage

| Table | In `Base.metadata` | Available in SQLite test DB |
|---|---|---|
| `auth_tokens` | Yes | Yes |
| `free_tier_grants` | No (raw SQL) | No — `OperationalError` swallowed by best-effort wrapper |

Do not add assertions that depend on `free_tier_grants` being populated in unit tests. Integration tests against Postgres are required to verify grant creation.
