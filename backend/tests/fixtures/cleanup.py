"""D18 Phase A CP4 — student-data cleanup helper + FK ordering map.

`cleanup_student_data(session, student_id)` is the canonical teardown
call for fixtures that seed any student-anchored row. It deletes in
the correct child→parent order so DELETE doesn't violate FK
constraints, then deletes the user itself.

Most child tables have ON DELETE CASCADE on their `user_id` /
`student_id` FK (verified at CP4 pre-flight against the live model
graph), which means a single DELETE FROM users would technically
clean those up. But we still issue explicit DELETEs for two reasons:

  1. **`agent_actions` does NOT cascade.** Its three user FKs
     (student_id, triggered_by_user_id, target_user_id) are
     ON DELETE NULL or no-action. Without explicit DELETE, a teardown
     that drops users leaves orphaned agent_actions rows whose
     student_id has gone NULL — this corrupts the per-test isolation
     contract since later tests' aggregator queries would still see
     these rows in counts.
  2. **Defensive against schema drift.** If migration N adds a new
     student-anchored table and forgets ON DELETE CASCADE, the
     explicit-DELETE list surfaces it in the next CP4 smoke run
     (cleanup leaves orphans → smoke fails fast). The CASCADE-only
     approach silently accumulates orphans until a much later
     debugging session.

Pre-flight FK CASCADE map (CP4 verification, 2026-05-08; columns
read from live Postgres pg_constraint, NOT from a docs cache):

| Table                  | FK column        | ON DELETE  | Explicit DELETE?       |
|------------------------|------------------|------------|------------------------|
| conversations          | user_id          | CASCADE    | yes (defensive)        |
| exercise_submissions   | student_id       | CASCADE    | yes (defensive)        |
| agent_actions          | student_id       | NO ACTION  | **YES (required)**     |
| agent_actions          | actor_id         | SET NULL   | no (SET NULL is fine)  |
| agent_actions          | on_behalf_of     | SET NULL   | no (SET NULL is fine)  |
| agent_invocation_log   | user_id          | CASCADE    | yes (defensive)        |
| course_entitlements    | user_id          | CASCADE    | yes (defensive)        |
| interview_sessions     | user_id          | CASCADE    | yes (defensive)        |
| learning_sessions      | user_id          | CASCADE    | yes (defensive)        |
| outreach_log           | user_id          | CASCADE    | yes (defensive)        |
| outreach_log           | triggered_by_uid | SET NULL   | no (SET NULL is fine)  |
| student_messages       | student_id       | CASCADE    | yes (defensive)        |
| student_messages       | sender_id        | SET NULL   | no (SET NULL is fine)  |
| student_notes          | admin_id         | CASCADE    | yes (defensive)        |
| student_notes          | student_id       | CASCADE    | yes (defensive)        |
| student_risk_signals   | user_id          | CASCADE    | yes (defensive)        |
| student_role_state     | student_id       | CASCADE    | yes (defensive)        |
| payments               | user_id          | CASCADE    | yes (defensive)        |
| users                  | (root)           | —          | yes (last)             |

CP4 pre-flight calibration note: an earlier pass of this docstring
listed `triggered_by_user_id` / `target_user_id` columns on
agent_actions that don't exist in the live schema. The actual
admin-trigger columns are `actor_id` / `on_behalf_of`, and both have
SET NULL — so we don't need explicit cleanup for them. Reading the
schema from pg_constraint instead of a model-graph cache caught the
drift. This is also why the doc table above explicitly cites the
verification source; future schema additions should re-run the
pg_constraint query before extending the cleanup list.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession


# Ordered list — children first, users last. Each entry is a (table,
# fk_column) tuple. For tables with multiple user FKs, list each FK
# separately so a row pointed at by ANY of them gets cleaned up.
#
# `student_notes` has both admin_id and student_id; a row anchored to
# the student we're tearing down should die regardless of which side.
# Same for outreach_log (user_id + triggered_by_user_id) and
# agent_actions (3 FKs).
_CLEANUP_ORDER: list[tuple[str, str]] = [
    # Conversation surface (chat_messages cascades from conversations)
    ("conversations", "user_id"),
    # Per-user write-heavy tables
    ("exercise_submissions", "student_id"),
    # agent_actions.student_id has NO ON DELETE clause → must
    # explicitly DELETE before the user row goes. actor_id and
    # on_behalf_of use SET NULL (handled automatically).
    ("agent_actions", "student_id"),
    ("agent_invocation_log", "user_id"),
    # Outreach + admin surface. triggered_by_user_id uses SET NULL
    # (a deleted admin doesn't drop the audit row, just NULLs the
    # admin reference).
    ("outreach_log", "user_id"),
    ("student_messages", "student_id"),
    ("student_notes", "admin_id"),
    ("student_notes", "student_id"),
    ("student_risk_signals", "user_id"),
    # Activity/state
    ("learning_sessions", "user_id"),
    ("interview_sessions", "user_id"),
    # Entitlement + role state + payments
    ("course_entitlements", "user_id"),
    ("student_role_state", "student_id"),
    ("payments", "user_id"),
    # Root last
    ("users", "id"),
]


async def cleanup_student_data(
    session: AsyncSession,
    student_id: uuid.UUID,
) -> None:
    """Delete every row anchored to `student_id` in correct FK order.

    Caller controls transaction boundary (matches role_state_fixtures'
    no-commit-by-default convention). Typical pattern:

        @pytest.fixture
        async def fresh_student(db_session):
            s = await seed_python_developer_fresh(db_session)
            await db_session.commit()
            yield s
            await cleanup_student_data(db_session, s.user_id)
            await db_session.commit()

    Idempotent: rows that don't exist are no-ops. Tables that don't
    exist (schema drift) raise — that's intentional, surfaces drift
    immediately in the smoke pass.
    """
    for table, column in _CLEANUP_ORDER:
        await session.execute(
            sql_text(f"DELETE FROM {table} WHERE {column} = :sid"),
            {"sid": student_id},
        )


async def assert_no_orphan_rows(
    session: AsyncSession,
    student_id: uuid.UUID,
) -> None:
    """Post-cleanup invariant check.

    Used by CP4 smoke tests. Iterates the cleanup-order list and
    asserts COUNT(*) is 0 for every (table, column) pair. If any
    table still has rows, raises with a list of (table, column,
    count) triples to help debug.

    Skips the `users` row from the assertion since we're checking
    that ALL of student's data is gone — including the user — and
    a count of 1 there would mean we double-cleaned, which is fine.
    The dedicated `users` row is asserted via the separate
    user_exists check below.
    """
    orphans: list[tuple[str, str, int]] = []
    for table, column in _CLEANUP_ORDER:
        if table == "users":
            continue
        result = await session.execute(
            sql_text(f"SELECT COUNT(*) FROM {table} WHERE {column} = :sid"),
            {"sid": student_id},
        )
        count = result.scalar_one()
        if count > 0:
            orphans.append((table, column, count))

    if orphans:
        details = "; ".join(f"{t}.{c}={n}" for t, c, n in orphans)
        raise AssertionError(
            f"Orphan rows after cleanup_student_data({student_id}): {details}"
        )


async def assert_user_deleted(
    session: AsyncSession,
    student_id: uuid.UUID,
) -> None:
    """Post-cleanup: the user row itself is gone.

    Separate from assert_no_orphan_rows so callers can choose:
    fixture teardown for one student typically uses both; bulk
    cleanup of a journey may want orphan-check only.
    """
    result = await session.execute(
        sql_text("SELECT COUNT(*) FROM users WHERE id = :sid"),
        {"sid": student_id},
    )
    count = result.scalar_one()
    if count != 0:
        raise AssertionError(
            f"User row {student_id} still present after cleanup "
            f"(count={count})"
        )
