"""D18 Phase A retrofit-3A smoke — content_seeders.py.

Single smoke test verifying:
  * `seed_minimal_lesson_chain(course_slug="python-developer", n=2)`
    inserts 2 published lessons.
  * `seed_minimal_capstone_bundle(course_slug="python-developer")`
    inserts 1 lesson + 1 is_capstone=True exercise.
  * Retrieval via the course-detail endpoint
    `GET /api/v1/courses/{course_id}/lessons` returns the seeded
    lessons in `order` ascending.
  * `cleanup_seeded_lessons` removes them; FK CASCADE handles the
    exercise + any progress rows.

Pure DB + HTTP smoke; no LLM. Cost ~₹0.

Why through the HTTP endpoint AND raw DB:
  Pattern 22 — verify the rows are reachable via the consumer's
  API path (not just present in the table). A row that's in the
  table but invisible to `get_active`'s `is_deleted` filter would
  pass a SQL-only assertion but break Phase B journey-test
  expectations.
"""

from __future__ import annotations

import json
import os
import urllib.request

import pytest
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.fixtures.content_seeders import (
    cleanup_seeded_lessons,
    seed_minimal_capstone_bundle,
    seed_minimal_lesson_chain,
)

pytestmark = [pytest.mark.asyncio]

_API_BASE = os.environ.get("PLAYWRIGHT_API_BASE", "http://nginx/api/v1")


def _http_get_json(path: str) -> list | dict:
    """GET path off API_BASE; return parsed JSON. No auth (admin
    endpoints would 401; lessons-list-for-course is public)."""
    req = urllib.request.Request(url=f"{_API_BASE}{path}", method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


async def test_seed_minimal_lesson_chain_and_capstone_visible_to_api(
    db_session: AsyncSession,
) -> None:
    chain = await seed_minimal_lesson_chain(
        db_session, course_slug="python-developer", n=2,
    )
    bundle = await seed_minimal_capstone_bundle(
        db_session, course_slug="python-developer",
    )
    await db_session.commit()

    # ── Direct DB shape check ────────────────────────────────────
    lesson_count = (
        await db_session.execute(
            sql_text(
                "SELECT COUNT(*) FROM lessons "
                "WHERE id = ANY(:ids) AND is_published = TRUE"
            ),
            {"ids": chain.lesson_ids + [bundle.lesson_id]},
        )
    ).scalar_one()
    assert lesson_count == 3  # 2 chain + 1 capstone parent

    capstone_row = (
        await db_session.execute(
            sql_text(
                "SELECT is_capstone, pass_score "
                "FROM exercises WHERE id = :eid"
            ),
            {"eid": bundle.capstone_exercise_id},
        )
    ).one()
    assert capstone_row.is_capstone is True
    assert capstone_row.pass_score == 70

    # ── HTTP retrieval shape check ───────────────────────────────
    # GET /api/v1/courses/{course_id}/lessons returns ALL lessons
    # for this course (active, regardless of is_published per
    # the get_active filter — see Pattern 22 verification at
    # retrofit-3 time). Our 3 seeded lessons should be in there.
    listed = _http_get_json(f"/courses/{chain.course_id}/lessons")
    assert isinstance(listed, list)
    listed_ids = {r["id"] for r in listed}
    seeded_ids = {str(lid) for lid in chain.lesson_ids + [bundle.lesson_id]}
    missing = seeded_ids - listed_ids
    assert not missing, (
        f"seeded lesson ids missing from API listing: {missing}"
    )

    # ── Cleanup + post-cleanup invariant ─────────────────────────
    await cleanup_seeded_lessons(
        db_session,
        lesson_ids=chain.lesson_ids + [bundle.lesson_id],
    )
    await db_session.commit()

    remaining = (
        await db_session.execute(
            sql_text(
                "SELECT COUNT(*) FROM lessons WHERE id = ANY(:ids)"
            ),
            {"ids": chain.lesson_ids + [bundle.lesson_id]},
        )
    ).scalar_one()
    assert remaining == 0
    # Capstone exercise should have CASCADE-deleted with its parent lesson.
    capstone_after = (
        await db_session.execute(
            sql_text(
                "SELECT COUNT(*) FROM exercises WHERE id = :eid"
            ),
            {"eid": bundle.capstone_exercise_id},
        )
    ).scalar_one()
    assert capstone_after == 0
