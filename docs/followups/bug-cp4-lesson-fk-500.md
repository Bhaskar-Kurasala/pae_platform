# BUG-CP4-LESSON-FK-500 — POST /me/lessons/{nonexistent}/complete returns 500

**Status:** Open. **Severity: MEDIUM** (user-visible 5xx on stale
URLs; not data-corrupting, not security-relevant; not strictly
launch-blocking but should fix before launch).
**Origin:** D18 Phase B CP4 error-mode authoring, 2026-05-09.
**Surfaced by:** test_cp4_error_modes.py
(@pytest.mark.xfail strict=True, Convention A).

## What this is

`POST /api/v1/students/me/lessons/{nonexistent_uuid}/complete` raises
an unhandled `asyncpg.exceptions.ForeignKeyViolationError` (wrapped
by SQLAlchemy as `IntegrityError`) when the supplied `lesson_id`
doesn't reference an existing row in `lessons`. FastAPI projects
the unhandled exception as 500 Internal Server Error.

The expected behavior is 404 Not Found (or 422 Unprocessable Entity)
— the request is well-formed but the resource doesn't exist.

## Stack trace (abbreviated)

```
File "/app/app/api/v1/routes/students.py", line 45, in complete_lesson
    return await service.complete_lesson(lesson_id, current_user)
File "/app/app/services/progress_service.py", line 280, in complete_lesson
sqlalchemy.exc.IntegrityError: <ForeignKeyViolationError>:
    insert or update on table "student_progress" violates
    foreign key constraint "student_progress_lesson_id_fkey"
```

## Surface area

  * Any client passing a `lesson_id` that doesn't exist —
    plausibly hit by frontend caching old lesson references
    after schema migrations or content removal.
  * NOT a security issue: the user is operating on `/me/...` so
    can only damage their own progress; the FK violation prevents
    data corruption.

## Fix scope (preliminary)

Two viable options:

**Option α — Pre-validate lesson exists.**
`progress_service.complete_lesson` should check
`lesson_repo.get_active(lesson_id)` returns a non-None row before
calling `pg_insert`. If None, raise `HTTPException(404, "Lesson not
found")`.

**Option β — Catch IntegrityError + re-raise as 404.**
Wrap the `db.execute(stmt)` call with try/except IntegrityError;
on FK violation, re-raise as `HTTPException(404)`. Cheaper but less
explicit about the contract.

**Recommendation:** Option α. Explicit pre-check matches the existing
pattern (`_require_student` etc.) and produces a clean 404 with a
helpful detail. Option β is a one-liner and acceptable as a
backstop.

## Verification when fix lands

1. Drop `@pytest.mark.xfail` from
   `test_cp4_error_modes.py::test_complete_lesson_missing_lesson_id_returns_404_or_422`.
2. Run under runner overlay; expect PASS with status in
   `(404, 422, 400)`.

## Related observation (separate finding)

While diagnosing this bug, backend logs surfaced a **separate
pre-existing best-effort signup-grace failure**:

```
ERROR: <class 'asyncpg.exceptions.PostgresSyntaxError'>:
    syntax error at or near ":"
[SQL: INSERT INTO free_tier_grants (id, user_id, grant_type,
    granted_at, expires_at, metadata) VALUES
    ($1, $2, 'signup_grace', $3, $4, :meta::jsonb)]
event: auth.signup_grace_failed
```

The `:meta::jsonb` in the SQL string suggests a query that mixes
SQLAlchemy's `text()` named-parameter syntax with positional
placeholders — Postgres receives the raw `:meta` and chokes. This
is silently failing on every signup (the auth service catches the
exception via the "Best-effort" wrapper); free-tier grants aren't
being created.

**Severity: MEDIUM-LOW** for the signup-grace bug (silent failure;
free-tier-grants probably reads as "no grant exists" downstream;
launch impact depends on whether free-tier-grants is a launch-day
feature). Worth registering separately if it surfaces user-visible
issues; for now, captured here as a side-finding.

## Cross-references

  * `backend/tests/playwright/journeys/test_cp4_error_modes.py` —
    the xfailed test.
  * `backend/app/services/progress_service.py:280` — the
    `pg_insert` call where the FK violation surfaces.
  * `backend/app/api/v1/routes/students.py:45` — the route handler
    that projects the unhandled exception.
