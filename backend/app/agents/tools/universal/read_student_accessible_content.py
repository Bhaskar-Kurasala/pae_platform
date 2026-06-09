"""D15 CP2 / Pass 3c — read_student_accessible_content universal tool.

The runtime content discovery tool. Returns the courses + curated
problems + notebooks the student has actual access to RIGHT NOW
(via course_entitlements), optionally filtered to a single role.

Architecturally critical per D-E (runtime content discovery, not
author-time baking): agents NEVER reference specific content in their
prompts. They call this tool, ground recommendations in the returned
lists, and fall back to role-identity-only reasoning when the lists
are empty.

Schema dependencies:
  * course_entitlements   — authoritative "what does student X have
                            access to right now" (D10 entitlement layer)
  * courses               — joined for slug + title + role_id (added by
                            D15 CP2b migration 0063)
  * lessons               — joined to find exercises under accessible
                            courses
  * exercises             — projected with is_capstone flag for
                            practice_curator's bank-vs-generative
                            decision
  * lesson_resources      — projected for accessible_notebooks; the
                            table is empty on dev DB at CP2 ship, which
                            is captured honestly by content_schema_
                            completeness="partial".

content_schema_completeness flag — load-bearing signal for agents:
  "complete"  — student has accessible courses, problems, AND notebooks
                for the requested role. Agents ground in all three.
  "partial"   — student has SOME content for the role (e.g. courses +
                problems but no notebooks, or courses but no problems).
                Agents ground in what's present and acknowledge the gap.
  "minimal"   — student has only the role identity (no accessible
                courses for the requested role). Agents reason in
                role-identity terms only; never invent content names.

When `role_slug` is None, the tool returns ALL accessible content
across roles (used by career_coach for cross-role progress views).
content_schema_completeness in that case reflects the union: complete
iff every content type is non-empty across the catalog.

Permissions: read:student_data
"""

from __future__ import annotations

import uuid
from typing import Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text as sql_text

from app.agents.primitives.communication import get_active_session
from app.agents.primitives.tools import tool

log = structlog.get_logger().bind(
    layer="tools.universal.read_student_accessible_content"
)

ContentCompleteness = Literal["complete", "partial", "minimal"]


# ── Input ─────────────────────────────────────────────────────────────


class ReadStudentAccessibleContentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID = Field(
        description="The student whose accessible content to discover.",
    )
    role_slug: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Optional role filter. When set, only courses (and their "
            "lessons / exercises / resources) tagged for this role are "
            "returned. When None, returns the union across roles."
        ),
    )


# ── Output sub-types ──────────────────────────────────────────────────


class AccessibleCourseRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: uuid.UUID
    course_slug: str
    course_title: str
    role_slug: str | None = Field(
        description=(
            "The course's role tag, or None if the course is "
            "orthogonal to the linear role progression (electives, "
            "test fixtures, future content)."
        ),
    )


class AccessibleCuratedProblemRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise_id: uuid.UUID
    title: str
    role_slug: str | None
    is_capstone: bool


class AccessibleNotebookRecord(BaseModel):
    """Projection of lesson_resources rows the student has access to.

    The dev DB has 0 rows in lesson_resources at CP2 ship. The output
    type exists so when content authoring catches up the schema is
    already honored end-to-end.
    """

    model_config = ConfigDict(extra="forbid")

    notebook_id: uuid.UUID
    title: str
    course_id: uuid.UUID
    role_slug: str | None


# ── Output ────────────────────────────────────────────────────────────


class ReadStudentAccessibleContentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    found: bool = Field(
        description=(
            "True iff the student has any active entitlements. False "
            "collapses every list to empty — agents read found first."
        ),
    )
    student_id: uuid.UUID
    filtered_to_role_slug: str | None = Field(
        description=(
            "Echoes the input role_slug so callers (and the agent's "
            "downstream prompt builder) can confirm what was filtered."
        ),
    )
    accessible_courses: list[AccessibleCourseRecord] = Field(default_factory=list)
    accessible_curated_problems: list[AccessibleCuratedProblemRecord] = Field(
        default_factory=list
    )
    accessible_notebooks: list[AccessibleNotebookRecord] = Field(
        default_factory=list,
        description=(
            "lesson_resources rows accessible to the student. Empty list "
            "when no notebooks are authored yet (current dev DB state) "
            "is REPORTED HONESTLY; agents read content_schema_completeness "
            "to decide whether to mention notebooks at all."
        ),
    )
    content_schema_completeness: ContentCompleteness = Field(
        description=(
            "complete = courses + problems + notebooks all non-empty. "
            "partial = some content types non-empty, others empty. "
            "minimal = no accessible content for the requested role "
            "(student should be redirected to role-identity reasoning)."
        ),
    )


# ── Helpers ───────────────────────────────────────────────────────────


def _classify_completeness(
    courses: list[AccessibleCourseRecord],
    problems: list[AccessibleCuratedProblemRecord],
    notebooks: list[AccessibleNotebookRecord],
) -> ContentCompleteness:
    """Three-way classification with explicit semantics.

    minimal: student has zero accessible courses for the request.
             Whether problems/notebooks are present or not is
             irrelevant — without a course they can't be reached
             through the entitlements layer.
    complete: every content type non-empty.
    partial: courses present, but at least one of problems/notebooks
             empty.
    """
    if not courses:
        return "minimal"
    if courses and problems and notebooks:
        return "complete"
    return "partial"


# ── Implementation ────────────────────────────────────────────────────


@tool(
    name="read_student_accessible_content",
    description=(
        "Returns the courses, curated problems, and notebooks the "
        "student has access to via active course_entitlements, "
        "optionally filtered by role. Agents ground recommendations "
        "in this output and read content_schema_completeness to "
        "decide whether to reference specific content (complete) or "
        "fall back to role-identity-only reasoning (minimal/partial)."
    ),
    input_schema=ReadStudentAccessibleContentInput,
    output_schema=ReadStudentAccessibleContentOutput,
    requires=("read:student_data",),
    cost_estimate=0.0,
    timeout_seconds=10.0,
)
async def read_student_accessible_content(
    args: ReadStudentAccessibleContentInput,
) -> ReadStudentAccessibleContentOutput:
    session = get_active_session()
    if session is None:
        raise RuntimeError(
            "read_student_accessible_content called without an active "
            "session. The tool body relies on the contextvar set by "
            "call_agent."
        )

    role_filter = args.role_slug
    bind_params: dict[str, object] = {"sid": args.student_id}
    if role_filter is not None:
        bind_params["role_slug"] = role_filter

    # Common entitlement predicate — matches D10 lookup_active_entitlements.
    # The role-filter clause is appended only when role_slug is set so
    # the same query handles the unfiltered case without a sentinel.
    role_filter_clause_courses = (
        "AND r.slug = :role_slug" if role_filter is not None else ""
    )

    try:
        course_rows = (
            await session.execute(
                sql_text(
                    f"""
                    SELECT
                        c.id, c.slug, c.title, r.slug
                    FROM course_entitlements ce
                    JOIN courses c ON c.id = ce.course_id
                    LEFT JOIN roles r ON r.id = c.role_id
                    WHERE ce.user_id = :sid
                      AND ce.revoked_at IS NULL
                      AND (ce.expires_at IS NULL OR ce.expires_at > now())
                      {role_filter_clause_courses}
                    ORDER BY r.sequence_order NULLS LAST, c.slug
                    """
                ),
                bind_params,
            )
        ).all()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "read_student_accessible_content.courses_query_failed",
            error=str(exc),
            student_id=str(args.student_id),
        )
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        return ReadStudentAccessibleContentOutput(
            found=False,
            student_id=args.student_id,
            filtered_to_role_slug=role_filter,
            content_schema_completeness="minimal",
        )

    accessible_courses = [
        AccessibleCourseRecord(
            course_id=row[0],
            course_slug=row[1] or "",
            course_title=row[2] or "",
            role_slug=row[3],
        )
        for row in course_rows
    ]

    # Short-circuit when the student has no entitled courses (or none
    # matching the filter). Problems + notebooks live UNDER courses,
    # so without an accessible course they're definitionally empty.
    if not accessible_courses:
        return ReadStudentAccessibleContentOutput(
            found=False,
            student_id=args.student_id,
            filtered_to_role_slug=role_filter,
            accessible_courses=[],
            accessible_curated_problems=[],
            accessible_notebooks=[],
            content_schema_completeness="minimal",
        )

    accessible_course_ids = [rec.course_id for rec in accessible_courses]

    # ── Exercises (curated problems) ─────────────────────────────────
    # JOIN through lessons → courses; filter by the same accessible
    # course IDs. is_capstone projected raw so practice_curator can
    # filter for non-capstone problems when generating practice
    # recommendations.
    try:
        problem_rows = (
            await session.execute(
                sql_text(
                    """
                    SELECT
                        e.id, e.title, r.slug, e.is_capstone
                    FROM exercises e
                    JOIN lessons l ON l.id = e.lesson_id
                    JOIN courses c ON c.id = l.course_id
                    LEFT JOIN roles r ON r.id = c.role_id
                    WHERE c.id = ANY(:course_ids)
                      AND (e.is_deleted IS NULL OR e.is_deleted = FALSE)
                    ORDER BY e.is_capstone, e."order"
                    """
                ),
                {"course_ids": accessible_course_ids},
            )
        ).all()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "read_student_accessible_content.problems_query_failed",
            error=str(exc),
            student_id=str(args.student_id),
        )
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        problem_rows = []

    accessible_curated_problems = [
        AccessibleCuratedProblemRecord(
            exercise_id=row[0],
            title=row[1] or "",
            role_slug=row[2],
            is_capstone=bool(row[3]),
        )
        for row in problem_rows
    ]

    # ── Notebooks (lesson_resources) ─────────────────────────────────
    # The dev DB has 0 rows at CP2 ship. The query is in place for the
    # day notebooks are authored. content_schema_completeness reports
    # "partial" honestly until then.
    try:
        notebook_rows = (
            await session.execute(
                sql_text(
                    """
                    SELECT
                        lr.id, lr.title, lr.course_id, r.slug
                    FROM lesson_resources lr
                    JOIN courses c ON c.id = lr.course_id
                    LEFT JOIN roles r ON r.id = c.role_id
                    WHERE lr.course_id = ANY(:course_ids)
                    ORDER BY lr.course_id, lr."order"
                    """
                ),
                {"course_ids": accessible_course_ids},
            )
        ).all()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "read_student_accessible_content.notebooks_query_failed",
            error=str(exc),
            student_id=str(args.student_id),
        )
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        notebook_rows = []

    accessible_notebooks = [
        AccessibleNotebookRecord(
            notebook_id=row[0],
            title=row[1] or "",
            course_id=row[2],
            role_slug=row[3],
        )
        for row in notebook_rows
    ]

    completeness = _classify_completeness(
        accessible_courses, accessible_curated_problems, accessible_notebooks
    )

    return ReadStudentAccessibleContentOutput(
        found=True,
        student_id=args.student_id,
        filtered_to_role_slug=role_filter,
        accessible_courses=accessible_courses,
        accessible_curated_problems=accessible_curated_problems,
        accessible_notebooks=accessible_notebooks,
        content_schema_completeness=completeness,
    )


__all__ = [
    "AccessibleCourseRecord",
    "AccessibleCuratedProblemRecord",
    "AccessibleNotebookRecord",
    "ContentCompleteness",
    "ReadStudentAccessibleContentInput",
    "ReadStudentAccessibleContentOutput",
    "read_student_accessible_content",
]
