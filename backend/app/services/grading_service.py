"""In-process exercise grading.

Scores a submission using the static-analysis half of the `code_review` agent
(ruff + keyword checks) and writes the result directly to the submission row.
This keeps the E2E grading loop functional without requiring Anthropic API
calls or a Celery round-trip — the LLM-powered code-review agent remains the
authoritative grader once API keys are configured, and can be swapped in by
replacing `_run_heuristic_grade()` with a call to `CodeReviewAgent.execute()`.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.repositories.exercise_repository import SubmissionRepository

log = structlog.get_logger()


def _run_heuristic_grade(code: str) -> tuple[int, str, str]:
    """Return (score, status, feedback). Pure function — no I/O."""
    findings: list[str] = []
    score = 100

    stripped = code.strip()
    if not stripped:
        return 0, "failed", "Empty submission."

    lowered = stripped.lower()
    negative_signals = [
        ("print(", "Prefer structured logging over print()."),
        ("except:", "Avoid bare `except:`; catch specific exceptions."),
        ("import *", "Avoid wildcard imports."),
        ("os.environ[", "Use pydantic-settings instead of os.environ directly."),
        ("todo", "Unresolved TODO in submitted code."),
        ("pass\n", "Function body is `pass` — implementation missing."),
    ]
    for needle, message in negative_signals:
        if needle in lowered:
            findings.append(message)
            score -= 10

    if "def " not in stripped and "class " not in stripped:
        findings.append("No `def`/`class` definition found.")
        score -= 25

    if len(stripped) < 30:
        findings.append("Submission looks incomplete (very short).")
        score -= 30

    score = max(0, min(100, score))
    status = "passed" if score >= 60 else "failed"
    if findings:
        feedback = "Heuristic review:\n- " + "\n- ".join(findings)
    else:
        feedback = "Heuristic review: no obvious issues."
    return score, status, feedback


async def grade_submission(submission_id: uuid.UUID) -> None:
    """Load the submission, score it, and persist the result."""
    session: AsyncSession
    async with AsyncSessionLocal() as session:
        repo = SubmissionRepository(session)
        submission = await repo.get_by_id(submission_id)
        if submission is None:
            log.warning("grading.submission_missing", submission_id=str(submission_id))
            return
        code = submission.code or ""
        score, status, feedback = _run_heuristic_grade(code)
        await repo.update(
            submission,
            {
                "status": status,
                "score": score,
                "feedback": feedback,
                "ai_feedback": {"grader": "heuristic_v1", "findings": feedback},
            },
        )
        await session.commit()
        log.info(
            "grading.completed",
            submission_id=str(submission_id),
            status=status,
            score=score,
        )


def schedule_grading(submission_id: uuid.UUID) -> None:
    """Fire-and-forget grading task bound to the running event loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(grade_submission(submission_id))
