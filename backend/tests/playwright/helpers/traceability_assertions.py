"""D18 Phase A CP5 — traceability assertions.

Four assertions that verify side-effect rows landed in the DB after
a Phase B journey runs an action through the UI. Each asserts:
  * row exists matching the criteria (positive case)
  * raises AssertionError with helpful detail otherwise (which fields
    matched, which differed) — the message is the diagnostic, so
    investigators don't need to re-query manually.

All assertions take an explicit `since_seconds_ago` recency window
(default 60s) so a long-running test that produces multiple rows
can still scope the check to "the action that just happened."
Phase B journey tests should commit between the action and the
assertion — these helpers query against the same db_session the
fixture committed to.

Schema verification (CP5 pre-flight, against live Postgres):
  * outreach_log: user_id / channel / triggered_by / sent_at
  * agent_actions: student_id / agent_name / status / created_at
  * student_messages: student_id / sender_id / created_at
  * student_notes: student_id / admin_id / created_at

Convention: positional `db_session`; keyword everything else.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession


def _since(seconds_ago: int) -> datetime:
    return datetime.now(UTC) - timedelta(seconds=seconds_ago)


async def assert_outreach_log_entry(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    channel: str,
    triggered_by: str | None = None,
    since_seconds_ago: int = 60,
) -> None:
    """Assert at least one outreach_log row exists matching criteria.

    On absence, the AssertionError message lists the closest matching
    rows in the recency window so investigators can see whether the
    write happened at all (vs landed with different fields).

    Filtering:
      * user_id (required)
      * channel (required exact match)
      * triggered_by (optional; 'system' / 'admin' / etc.)
      * sent_at >= now() - since_seconds_ago

    Note we filter on `sent_at` (the business-event timestamp), not
    `created_at`, since outreach scheduling can backfill historical
    rows; tests want to see "outreach happened in this window" not
    "row was inserted in this window."
    """
    cutoff = _since(since_seconds_ago)
    where_clauses = [
        "user_id = :uid",
        "channel = :ch",
        "sent_at >= :cutoff",
    ]
    params: dict[str, object] = {"uid": user_id, "ch": channel, "cutoff": cutoff}
    if triggered_by is not None:
        where_clauses.append("triggered_by = :tb")
        params["tb"] = triggered_by

    sql = (
        f"SELECT COUNT(*) FROM outreach_log "
        f"WHERE {' AND '.join(where_clauses)}"
    )
    matched = (await db_session.execute(sql_text(sql), params)).scalar_one()
    if matched > 0:
        return

    # Build a helpful diff: fetch all rows for this user in the window
    # and report what was found, so the AssertionError is actionable.
    rows = (
        await db_session.execute(
            sql_text(
                """
                SELECT channel, triggered_by, sent_at
                FROM outreach_log
                WHERE user_id = :uid AND sent_at >= :cutoff
                ORDER BY sent_at DESC
                LIMIT 5
                """
            ),
            {"uid": user_id, "cutoff": cutoff},
        )
    ).all()
    near_miss = (
        ", ".join(f"({r.channel}, by={r.triggered_by}, at={r.sent_at.isoformat()})" for r in rows)
        if rows
        else "no rows in window"
    )
    raise AssertionError(
        f"assert_outreach_log_entry: no row matching "
        f"user_id={user_id}, channel={channel!r}, "
        f"triggered_by={triggered_by!r}, "
        f"within {since_seconds_ago}s. Recent rows in window: {near_miss}"
    )


async def assert_agent_action_logged(
    db_session: AsyncSession,
    *,
    student_id: uuid.UUID,
    agent_name: str,
    status: str = "completed",
    since_seconds_ago: int = 60,
) -> None:
    """Assert an agent_actions row exists for this student + agent within window.

    Filters: student_id (exact), agent_name (exact), status (exact),
    created_at >= cutoff.
    """
    cutoff = _since(since_seconds_ago)
    matched = (
        await db_session.execute(
            sql_text(
                """
                SELECT COUNT(*) FROM agent_actions
                WHERE student_id = :sid
                  AND agent_name = :name
                  AND status = :status
                  AND created_at >= :cutoff
                """
            ),
            {
                "sid": student_id,
                "name": agent_name,
                "status": status,
                "cutoff": cutoff,
            },
        )
    ).scalar_one()
    if matched > 0:
        return

    rows = (
        await db_session.execute(
            sql_text(
                """
                SELECT agent_name, status, created_at
                FROM agent_actions
                WHERE student_id = :sid AND created_at >= :cutoff
                ORDER BY created_at DESC
                LIMIT 5
                """
            ),
            {"sid": student_id, "cutoff": cutoff},
        )
    ).all()
    near_miss = (
        ", ".join(f"({r.agent_name}, status={r.status}, at={r.created_at.isoformat()})" for r in rows)
        if rows
        else "no rows in window"
    )
    raise AssertionError(
        f"assert_agent_action_logged: no row matching "
        f"student_id={student_id}, agent_name={agent_name!r}, "
        f"status={status!r}, within {since_seconds_ago}s. "
        f"Recent rows in window: {near_miss}"
    )


async def assert_student_message_thread(
    db_session: AsyncSession,
    *,
    admin_id: uuid.UUID,
    student_id: uuid.UUID,
    expected_message_count: int,
) -> None:
    """Assert the in-app DM thread between admin and student has exactly N messages.

    Counts student_messages rows where student_id matches AND either:
      * the row's sender_id is admin_id, OR
      * the sender_role identifies an admin and student_id is the
        target.

    The schema doesn't directly model "thread between two parties"
    via thread_id alone (thread_id groups messages but doesn't pin
    the admin); using student_id + sender_id as the join is more
    explicit.
    """
    actual = (
        await db_session.execute(
            sql_text(
                """
                SELECT COUNT(*) FROM student_messages
                WHERE student_id = :sid
                  AND (sender_id = :aid OR sender_role IN ('admin', 'instructor'))
                """
            ),
            {"sid": student_id, "aid": admin_id},
        )
    ).scalar_one()
    if actual == expected_message_count:
        return
    raise AssertionError(
        f"assert_student_message_thread: expected "
        f"{expected_message_count} messages between admin {admin_id} "
        f"and student {student_id}, found {actual}."
    )


async def assert_student_note_count(
    db_session: AsyncSession,
    *,
    student_id: uuid.UUID,
    count: int,
    admin_id: uuid.UUID | None = None,
) -> None:
    """Assert the student_notes table has exactly `count` rows for this student.

    Optionally filter by admin_id (notes authored by a specific admin);
    omit to count all admin notes on the student.
    """
    where = "student_id = :sid"
    params: dict[str, object] = {"sid": student_id}
    if admin_id is not None:
        where += " AND admin_id = :aid"
        params["aid"] = admin_id
    actual = (
        await db_session.execute(
            sql_text(f"SELECT COUNT(*) FROM student_notes WHERE {where}"),
            params,
        )
    ).scalar_one()
    if actual == count:
        return
    raise AssertionError(
        f"assert_student_note_count: expected {count} notes for "
        f"student {student_id}"
        + (f" (admin {admin_id})" if admin_id else "")
        + f", found {actual}."
    )


__all__ = [
    "assert_agent_action_logged",
    "assert_outreach_log_entry",
    "assert_student_message_thread",
    "assert_student_note_count",
]
