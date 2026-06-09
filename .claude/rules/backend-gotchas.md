---
paths:
  - "backend/**"
---

# Backend Gotchas (hard-won lessons)

These are recurring traps in this codebase. Migrated from `docs/lessons.md`;
loaded only when working under `backend/`.

## Use `sa.JSON`, not `postgresql.JSONB`, for model columns
The in-memory SQLite test DB can't render `postgresql.JSONB` in DDL. Use
`sa.JSON` everywhere — it works in both SQLite (tests) and PostgreSQL (prod).
Only reach for `JSONB` if you need its operators (containment/indexing), and
then guard it at the dialect level.

## `ChatAnthropic` / LangChain constructor kwargs and mypy
The correct API-key field is `anthropic_api_key` (a `SecretStr`). mypy can't
introspect these Pydantic-based LangChain constructors, so add a targeted
`# type: ignore[call-arg]` rather than disabling mypy. Check
`Model.model_fields.keys()` to find real field names.

## Reset slowapi rate-limiter state between tests
`slowapi`'s default in-memory storage persists across tests, so repeated
`/register` or `/login` calls trip the limit and cascade into 429/401s. Add an
`autouse=True` conftest fixture that clears the limiter storage between tests,
and pass `X-Forwarded-For` so `get_remote_address` is consistent.

## Use `-> Any` for optional third-party client helpers
A helper like `_get_redis_optional()` that returns a third-party client should
be typed `-> Any`, not `-> object | None` — `object` blocks `.get()`/`.setex()`
attribute access. This is a legitimate use of `Any` (deliberately hiding the
type to suppress import errors gracefully).
