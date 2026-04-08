# Lessons Learned

This file is updated by Claude Code after every correction.
When Claude makes a mistake and gets corrected, the lesson is recorded here
so it never repeats the same mistake.

Format:
```
## YYYY-MM-DD: {What went wrong}
**Context**: {What Claude was doing}
**Mistake**: {What it did wrong}
**Correction**: {What the right approach is}
**Rule**: {The general rule to follow}
```

---

## 2026-04-08: SQLite test DB doesn't support PostgreSQL-specific JSONB type

**Context**: Phase 1 — setting up in-memory SQLite test DB with SQLAlchemy models.
**Mistake**: Models used `postgresql.JSONB` which SQLite's DDL compiler can't render.
**Correction**: Replace `JSONB` with `sa.JSON` across all models — JSON works in both SQLite (tests) and PostgreSQL (production).
**Rule**: Use `sa.JSON` for all JSONB columns unless you need JSONB-specific operators (containment, indexing). If you do need them, use a conditional type or override at the dialect level.

## 2026-04-08: ChatAnthropic constructor kwargs don't match mypy expectations

**Context**: Phase 3 — building agents with `langchain-anthropic`.
**Mistake**: Used `model=`, `api_key=`, `max_tokens=` kwargs but mypy reported them as unexpected because the class uses `**kwargs` in `__init__`.
**Correction**: The correct field name is `anthropic_api_key` (a `SecretStr`). Add `# type: ignore[call-arg]` to suppress the false-positive — mypy can't introspect Pydantic model constructors properly for LangChain classes.
**Rule**: For third-party LangChain model classes, check `Model.model_fields.keys()` to find the actual field names. Add targeted `# type: ignore[call-arg]` rather than disabling mypy globally.

## 2026-04-08: Route groups can't both have root page.tsx (Next.js App Router)

**Context**: Phase 2 — creating admin and public route groups.
**Mistake**: Created both `(admin)/page.tsx` and `(public)/page.tsx` — both resolve to `/` since route groups don't add URL segments.
**Correction**: Route groups share the URL namespace. Use a regular directory (`admin/`) for the admin section; only use route groups when you need different layouts for the same URL pattern.
**Rule**: In Next.js App Router, `(group)/page.tsx` resolves to `/` — two groups can't both have `page.tsx` at their root. Use regular directories when routes have distinct URL paths.

## 2026-04-08: slowapi rate limiter accumulates state across tests

**Context**: Phase 5 — adding rate limiting to auth endpoints.
**Mistake**: After adding `slowapi` with default in-memory storage, tests that call `/register` more than 10 times in a session triggered the 10/minute rate limit, causing 429s that cascaded as 401s in login tests.
**Correction**: Add an `autouse=True` fixture to `conftest.py` that clears the limiter's in-memory storage dict between tests. Also pass `X-Forwarded-For` header so `get_remote_address` works consistently.
**Rule**: Rate limiting middleware uses persistent in-memory state. Always reset it in test fixtures. Consider using a test-specific key function or very high limits (`9999/minute`) in test environments.

## 2026-04-08: Generic `object` return type blocks attribute access on redis client

**Context**: Phase 5 — implementing Redis cache with an optional helper function.
**Mistake**: `_get_redis_optional() -> object | None` returned an `object`, which mypy correctly flagged when calling `.get()`, `.setex()`, `.delete()` on it.
**Correction**: Use `Any` as the return type for optional third-party client helpers that mypy can't fully type. This is a valid use case for `Any` — we're deliberately hiding the type because the function's whole point is to suppress import errors gracefully.
**Rule**: Use `-> Any` for optional dependency helpers that return third-party objects. Reserve `object` for truly generic cases where you want to restrict access to only `object` members.
