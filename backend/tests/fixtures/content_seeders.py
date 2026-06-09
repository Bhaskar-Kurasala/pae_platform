"""D18 Phase A retrofit-3A — content seeders.

Per-test inline lesson + capstone seeding for journeys that need a
populated content surface. The playwright_test template is
intentionally content-empty (1 synthetic CP4 capstone-harness lesson;
0 published catalog lessons); seeding inline-per-test preserves the
template's "empty by default" property while letting content-coupled
journeys assert against real DB state.

Pattern parity with role_state_fixtures.py:
  * Helpers don't commit; the caller owns the transaction.
  * Returns identifiers (UUIDs) the test can assert on.
  * Idempotent where it makes sense (uniqueness via per-call uuid;
    `seed_minimal_lesson_chain` is parameterized so re-calls produce
    distinct rows but with predictable per-position content shape).

Schema verified live (Pattern 22 discipline) at retrofit-3 time
2026-05-08:
  * lessons: course_id (CASCADE) + slug (indexed) + "order" (reserved
    word, must quote) + title + is_published default false but
    `get_active` filter only checks `is_deleted` — non-published
    lessons ARE retrievable via `/api/v1/lessons/{id}`. Seeders
    set is_published=True anyway for realism.
  * exercises: lesson_id (CASCADE) + "order" (reserved word) +
    is_capstone default false + pass_score default 70.
  * No `state` column on lessons (CP3 prompt's "state='published'"
    framing was wrong; the column is `is_published` boolean).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class SeededLessonChain:
    """Identifiers for a seeded lesson chain on a course."""

    course_id: uuid.UUID
    course_slug: str
    lesson_ids: list[uuid.UUID] = field(default_factory=list)


@dataclass
class SeededCapstoneBundle:
    """Identifiers for a seeded capstone exercise + its parent lesson."""

    course_id: uuid.UUID
    course_slug: str
    lesson_id: uuid.UUID
    capstone_exercise_id: uuid.UUID


_LESSON_CONTENT_TEMPLATE = (
    "# Test lesson {n}\n\n"
    "This is fixture-seeded lesson content for journey-test {n}.\n\n"
    "```python\n"
    "# Sample code block — assertions can match this shape\n"
    "def test_marker_{n}() -> None:\n"
    '    return "lesson-{n}"\n'
    "```\n"
)


async def _resolve_course_id(
    session: AsyncSession, course_slug: str
) -> uuid.UUID:
    """Resolve a course slug to its UUID. Raises if not found."""
    course_id = (
        await session.execute(
            sql_text("SELECT id FROM courses WHERE slug = :s"),
            {"s": course_slug},
        )
    ).scalar_one_or_none()
    if course_id is None:
        raise ValueError(
            f"course slug {course_slug!r} not found; the playwright_test "
            f"template seeds 11 catalog courses (verify via "
            f"`SELECT slug FROM courses`)."
        )
    return course_id


async def seed_minimal_lesson_chain(
    session: AsyncSession,
    *,
    course_slug: str,
    n: int = 1,
    starting_order: int = 1000,
) -> SeededLessonChain:
    """Seed `n` published lessons on `course_slug`.

    Lessons get fixed-shape titles + content (per-position template)
    so tests can match content shape without worrying about flake.
    `starting_order` defaults high (1000) so seeded lessons sit
    after any existing course lessons by `order`.

    Returns SeededLessonChain with lesson_ids in position order.

    Cleanup: lessons CASCADE on course delete; tests that delete
    the user don't auto-cascade to lessons (no FK from users).
    Tests that need to remove their seeded lessons should DELETE
    by id explicitly, OR rely on per-suite playwright_test reset
    if the FK ordering doesn't matter.
    """
    course_id = await _resolve_course_id(session, course_slug)
    lesson_ids: list[uuid.UUID] = []
    for i in range(n):
        position = starting_order + i
        lesson_id = uuid.uuid4()
        await session.execute(
            sql_text(
                """
                INSERT INTO lessons
                  (id, course_id, title, slug, content, "order",
                   is_published, duration_seconds,
                   created_at, updated_at)
                VALUES
                  (:id, :cid, :title, :slug, :content, :ord,
                   TRUE, 600, now(), now())
                """
            ),
            {
                "id": lesson_id,
                "cid": course_id,
                "title": f"Test lesson {position}",
                "slug": f"r3-test-lesson-{lesson_id.hex[:8]}",
                "content": _LESSON_CONTENT_TEMPLATE.format(n=position),
                "ord": position,
            },
        )
        lesson_ids.append(lesson_id)
    return SeededLessonChain(
        course_id=course_id,
        course_slug=course_slug,
        lesson_ids=lesson_ids,
    )


async def seed_minimal_capstone_bundle(
    session: AsyncSession,
    *,
    course_slug: str,
) -> SeededCapstoneBundle:
    """Seed one published capstone-eligible lesson + capstone exercise.

    Mirrors the CP4 `_ensure_capstone_exercise` shape but distinct
    enough to coexist with the CP4 fixture's harness lesson (uses
    starting_order 2000 so doesn't collide).

    Returns SeededCapstoneBundle with capstone_exercise_id usable in
    POST /api/v1/exercises/{id}/submit.
    """
    course_id = await _resolve_course_id(session, course_slug)
    lesson_id = uuid.uuid4()
    capstone_exercise_id = uuid.uuid4()

    await session.execute(
        sql_text(
            """
            INSERT INTO lessons
              (id, course_id, title, slug, content, "order",
               is_published, duration_seconds, created_at, updated_at)
            VALUES
              (:id, :cid, 'Retrofit-3 capstone harness lesson',
               :slug, :content, 2000, TRUE, 1200, now(), now())
            """
        ),
        {
            "id": lesson_id,
            "cid": course_id,
            "slug": f"r3-capstone-lesson-{lesson_id.hex[:8]}",
            "content": (
                "# Capstone harness\n\n"
                "Fixture-seeded capstone for journey (c) tests.\n"
            ),
        },
    )
    await session.execute(
        sql_text(
            """
            INSERT INTO exercises
              (id, lesson_id, title, description, is_capstone,
               "order", points, pass_score, created_at, updated_at)
            VALUES
              (:id, :lid, 'Retrofit-3 capstone exercise',
               'Test fixture capstone for retrofit-3.', TRUE,
               2000, 100, 70, now(), now())
            """
        ),
        {"id": capstone_exercise_id, "lid": lesson_id},
    )
    return SeededCapstoneBundle(
        course_id=course_id,
        course_slug=course_slug,
        lesson_id=lesson_id,
        capstone_exercise_id=capstone_exercise_id,
    )


async def seed_lesson_with_progress_state(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    course_slug: str,
    state: str = "in_progress",
    n: int = 1,
) -> SeededLessonChain:
    """Composite: seed n lessons + create student_progress rows.

    `state` ∈ {"in_progress", "completed"} — matches the
    student_progress.status column's values per `complete_lesson`
    service code (which writes status='completed').

    Useful for journey (b) variants:
      * resuming a partially-completed lesson (state='in_progress')
      * navigating after completion (state='completed')

    Returns the underlying SeededLessonChain. The student_progress
    rows CASCADE on either user or lesson delete.
    """
    if state not in ("in_progress", "completed"):
        raise ValueError(
            f"state must be 'in_progress' or 'completed'; got {state!r}"
        )
    chain = await seed_minimal_lesson_chain(
        session, course_slug=course_slug, n=n
    )
    completed_at_clause = "now()" if state == "completed" else "NULL"
    for lid in chain.lesson_ids:
        await session.execute(
            sql_text(
                f"""
                INSERT INTO student_progress
                  (id, student_id, lesson_id, status, completed_at,
                   watch_time_seconds, last_position_seconds,
                   created_at, updated_at)
                VALUES
                  (:id, :sid, :lid, :status, {completed_at_clause},
                   60, 30, now(), now())
                ON CONFLICT (student_id, lesson_id) DO UPDATE
                SET status = EXCLUDED.status,
                    completed_at = EXCLUDED.completed_at
                """
            ),
            {
                "id": uuid.uuid4(),
                "sid": user_id,
                "lid": lid,
                "status": state,
            },
        )
    return chain


async def cleanup_seeded_lessons(
    session: AsyncSession,
    *,
    lesson_ids: list[uuid.UUID],
) -> None:
    """DELETE lessons by id; CASCADE handles exercises + progress + etc.

    For tests that don't want to wait for per-suite reset to clear
    their content. Idempotent — missing ids no-op.
    """
    if not lesson_ids:
        return
    await session.execute(
        sql_text("DELETE FROM lessons WHERE id = ANY(:ids)"),
        {"ids": lesson_ids},
    )


__all__ = [
    "SeededCapstoneBundle",
    "SeededLessonChain",
    "cleanup_seeded_lessons",
    "seed_lesson_with_progress_state",
    "seed_minimal_capstone_bundle",
    "seed_minimal_lesson_chain",
]
