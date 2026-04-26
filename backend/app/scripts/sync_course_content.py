"""Sync the ``course_content/`` filesystem tree into the database.

Reads each ``course.yaml`` and ``week.yaml`` and upserts:
  - ``courses`` (keyed by ``slug``)
  - ``lessons`` (keyed by ``(course_id, slug)``)
  - ``lesson_resources`` (keyed by ``(course_id, lesson_id, kind, path)``)

Idempotent: rerun freely after editing YAML; rows are reconciled, not appended.
Resources for a lesson that no longer appear in YAML are deleted; lessons that
disappear are soft-deleted (we don't hard-delete to preserve student progress
references).

Run from ``backend/``:

    uv run python -m app.scripts.sync_course_content
    uv run python -m app.scripts.sync_course_content --course python --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.course import Course
from app.models.lesson import Lesson
from app.models.lesson_resource import LessonResource

logger = structlog.get_logger(__name__)

CONTENT_ROOT = Path(__file__).resolve().parents[3] / "course_content"


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a YAML mapping at top level")
    return data


async def _upsert_course(session: AsyncSession, course_dir: Path) -> Course:
    spec = _load_yaml(course_dir / "course.yaml")
    slug = spec["slug"]

    existing = await session.scalar(select(Course).where(Course.slug == slug))
    if existing is None:
        course = Course(
            slug=slug,
            title=spec["title"],
            description=spec.get("description"),
            difficulty=spec.get("difficulty", "beginner"),
            estimated_hours=spec.get("estimated_hours", 0),
            github_repo_url=spec.get("github_repo_url"),
            is_published=spec.get("is_published", True),
        )
        session.add(course)
        await session.flush()
        logger.info("course.created", slug=slug, id=str(course.id))
        return course

    existing.title = spec["title"]
    existing.description = spec.get("description")
    existing.difficulty = spec.get("difficulty", existing.difficulty)
    existing.estimated_hours = spec.get("estimated_hours", existing.estimated_hours)
    if "github_repo_url" in spec:
        existing.github_repo_url = spec["github_repo_url"]
    if "is_published" in spec:
        existing.is_published = spec["is_published"]
    await session.flush()
    logger.info("course.updated", slug=slug, id=str(existing.id))
    return existing


async def _upsert_lesson(
    session: AsyncSession,
    course: Course,
    lesson_spec: dict[str, Any],
) -> Lesson:
    slug = lesson_spec["slug"]
    duration_seconds = int(lesson_spec.get("duration_min", 0)) * 60

    stmt = select(Lesson).where(Lesson.course_id == course.id, Lesson.slug == slug)
    existing = await session.scalar(stmt)

    if existing is None:
        lesson = Lesson(
            course_id=course.id,
            slug=slug,
            title=lesson_spec["title"],
            description=lesson_spec.get("description"),
            order=lesson_spec["order"],
            duration_seconds=duration_seconds,
            is_published=True,
            is_free_preview=lesson_spec.get("is_free_preview", False),
        )
        session.add(lesson)
        await session.flush()
        logger.info("lesson.created", course=course.slug, slug=slug, id=str(lesson.id))
        return lesson

    existing.title = lesson_spec["title"]
    existing.description = lesson_spec.get("description")
    existing.order = lesson_spec["order"]
    existing.duration_seconds = duration_seconds
    existing.is_published = True
    if "is_free_preview" in lesson_spec:
        existing.is_free_preview = lesson_spec["is_free_preview"]
    if existing.is_deleted:
        existing.is_deleted = False
        existing.deleted_at = None
    await session.flush()
    logger.info("lesson.updated", course=course.slug, slug=slug, id=str(existing.id))
    return existing


def _resource_key(r: LessonResource) -> tuple[str, str | None]:
    return (r.kind, r.path or r.url)


async def _reconcile_resources(
    session: AsyncSession,
    course: Course,
    lesson: Lesson | None,
    week_dir: Path,
    specs: list[dict[str, Any]],
) -> None:
    """Reconcile resource rows for a single lesson (or course-level)."""
    stmt = select(LessonResource).where(
        LessonResource.course_id == course.id,
        LessonResource.lesson_id == (lesson.id if lesson else None),
    )
    existing_rows = (await session.scalars(stmt)).all()
    existing_by_key: dict[tuple[str, str | None], LessonResource] = {
        _resource_key(r): r for r in existing_rows
    }

    seen_keys: set[tuple[str, str | None]] = set()
    for order, spec in enumerate(specs, start=1):
        kind = spec["kind"]
        path = spec.get("path")
        url = spec.get("url")

        if path:
            full = (week_dir / path).resolve()
            if not full.exists():
                logger.warning(
                    "resource.missing_file",
                    course=course.slug,
                    lesson=lesson.slug if lesson else None,
                    path=str(full),
                )

        key = (kind, path or url)
        seen_keys.add(key)
        existing = existing_by_key.get(key)

        if existing is None:
            session.add(
                LessonResource(
                    course_id=course.id,
                    lesson_id=lesson.id if lesson else None,
                    kind=kind,
                    title=spec["title"],
                    description=spec.get("description"),
                    path=path,
                    url=url,
                    order=spec.get("order", order),
                    is_required=spec.get("is_required", False),
                    metadata_=spec.get("metadata"),
                )
            )
        else:
            existing.title = spec["title"]
            existing.description = spec.get("description")
            existing.path = path
            existing.url = url
            existing.order = spec.get("order", order)
            existing.is_required = spec.get("is_required", False)
            existing.metadata_ = spec.get("metadata")

    for key, row in existing_by_key.items():
        if key not in seen_keys:
            await session.delete(row)
            logger.info(
                "resource.deleted",
                course=course.slug,
                lesson=lesson.slug if lesson else None,
                kind=row.kind,
                path=row.path,
            )

    await session.flush()


async def _sync_week(session: AsyncSession, course: Course, week_dir: Path) -> set[str]:
    spec = _load_yaml(week_dir / "week.yaml")
    seen_lesson_slugs: set[str] = set()

    lesson_specs: list[dict[str, Any]] = list(spec.get("lessons", []))
    checkpoint = spec.get("checkpoint")
    if checkpoint:
        lesson_specs.append(checkpoint)

    for lesson_spec in lesson_specs:
        lesson = await _upsert_lesson(session, course, lesson_spec)
        seen_lesson_slugs.add(lesson.slug)
        await _reconcile_resources(
            session, course, lesson, week_dir, lesson_spec.get("resources", [])
        )

    extras = spec.get("extra_resources", [])
    if extras:
        await _reconcile_resources(session, course, None, week_dir, extras)

    return seen_lesson_slugs


async def _soft_delete_missing_lessons(
    session: AsyncSession, course: Course, kept_slugs: set[str]
) -> None:
    stmt = select(Lesson).where(Lesson.course_id == course.id, Lesson.is_deleted.is_(False))
    rows = (await session.scalars(stmt)).all()
    for row in rows:
        if row.slug not in kept_slugs:
            row.is_deleted = True
            row.deleted_at = datetime.now(UTC)
            logger.info(
                "lesson.soft_deleted",
                course=course.slug,
                slug=row.slug,
                id=str(row.id),
            )
    await session.flush()


async def sync_course(session: AsyncSession, course_dir: Path) -> None:
    course = await _upsert_course(session, course_dir)
    seen_lesson_slugs: set[str] = set()
    for week_dir in sorted(p for p in course_dir.iterdir() if p.is_dir()):
        if not (week_dir / "week.yaml").exists():
            continue
        seen_lesson_slugs |= await _sync_week(session, course, week_dir)
    await _soft_delete_missing_lessons(session, course, seen_lesson_slugs)


async def main(course_filter: str | None, dry_run: bool) -> None:
    if not CONTENT_ROOT.exists():
        raise SystemExit(f"course_content not found at {CONTENT_ROOT}")

    course_dirs = [
        p
        for p in CONTENT_ROOT.iterdir()
        if p.is_dir() and (p / "course.yaml").exists()
    ]
    if course_filter:
        course_dirs = [p for p in course_dirs if p.name == course_filter]
        if not course_dirs:
            raise SystemExit(f"No course directory matched --course={course_filter}")

    async with AsyncSessionLocal() as session:
        for course_dir in sorted(course_dirs):
            logger.info("sync.course.start", slug=course_dir.name)
            await sync_course(session, course_dir)
        if dry_run:
            logger.info("sync.dry_run.rollback")
            await session.rollback()
        else:
            await session.commit()
            logger.info("sync.committed")


def cli() -> None:
    parser = argparse.ArgumentParser(description="Sync course_content/ to database")
    parser.add_argument("--course", help="Limit to a single course slug")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the sync but rollback at the end (no DB writes persisted)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.course, args.dry_run))


if __name__ == "__main__":
    cli()
