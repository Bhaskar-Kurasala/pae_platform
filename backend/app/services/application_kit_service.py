"""Application Kit service — bundle resume + tailored variant + JD + mock + autopsy.

A kit is the bottom-of-funnel artifact in Job Readiness: the user picks the
pieces they want included, we resolve them into a frozen `manifest` dict
(snapshot of the source rows at build time), render a PDF, and persist the
row so it's downloadable forever (even if the source rows mutate).

The build flow is sequential — validate refs, insert a `building` row, resolve
+ render, then flip status to `ready`. On any exception during resolve/render
we mark the row `failed` and re-raise so the caller can return a 500.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application_kit import ApplicationKit
from app.models.jd_library import JdLibrary
from app.models.mock_interview import MockSessionReport
from app.models.portfolio_autopsy_result import PortfolioAutopsyResult
from app.models.resume import Resume
from app.models.tailored_resume import TailoredResume
from app.models.user import User
from app.schemas.application_kit import BuildKitRequest
from app.services import pdf_renderer

log = structlog.get_logger()


def _isoformat(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def build_manifest(
    *,
    resume: Resume | None,
    tailored: TailoredResume | None,
    jd: JdLibrary | None,
    mock_report: MockSessionReport | None,
    autopsy: PortfolioAutopsyResult | None,
    label: str,
    target_role: str | None,
) -> dict[str, Any]:
    """Build a JSON-safe manifest dict from the resolved source rows.

    Each section is OPTIONAL — missing rows are simply omitted from the
    returned dict (no key, no null). All datetimes are isoformatted; no
    SQLAlchemy objects leak through.
    """
    manifest: dict[str, Any] = {
        "label": label,
        "target_role": target_role,
        "built_at": datetime.now(UTC).isoformat(),
    }

    if resume is not None:
        manifest["resume"] = {
            "id": str(resume.id),
            "title": resume.title or "",
            "summary": resume.summary or "",
            "bullets": list(resume.bullets or []),
            "skills_snapshot": list(resume.skills_snapshot or []),
            "ats_keywords": list(resume.ats_keywords or []),
        }

    if tailored is not None:
        manifest["tailored_resume"] = {
            "id": str(tailored.id),
            "jd_text": tailored.jd_text or "",
            "content": dict(tailored.content or {}),
        }

    if jd is not None:
        manifest["jd"] = {
            "id": str(jd.id),
            "title": jd.title,
            "company": jd.company,
            # `last_fit_score` is a float in the DB; coerce to int for the
            # snapshot so JSON consumers don't get surprised by precision
            # noise. None becomes 0 — a missing score is "no signal."
            "fit_score": int(jd.last_fit_score) if jd.last_fit_score is not None else 0,
            "verdict": jd.verdict or "",
        }

    if mock_report is not None:
        manifest["mock_report"] = {
            "session_id": str(mock_report.session_id),
            "headline": mock_report.headline or "",
            "verdict": mock_report.verdict or "",
            "strengths": list(mock_report.strengths or []),
            "weaknesses": list(mock_report.weaknesses or []),
        }

    if autopsy is not None:
        manifest["autopsy"] = {
            "id": str(autopsy.id),
            "headline": autopsy.headline,
            "overall_score": int(autopsy.overall_score),
            "what_worked": list(autopsy.what_worked or []),
            "what_to_do_differently": list(autopsy.what_to_do_differently or []),
        }

    return manifest


async def list_kits_for_user(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    limit: int = 20,
) -> list[ApplicationKit]:
    """Return up to *limit* kits for *user_id*, newest first."""
    result = await db.execute(
        select(ApplicationKit)
        .where(ApplicationKit.user_id == user_id)
        .order_by(ApplicationKit.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_kit_for_user(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    kit_id: uuid.UUID,
) -> ApplicationKit | None:
    """Fetch a kit by id, scoped to *user_id*. Returns None if not owned."""
    result = await db.execute(
        select(ApplicationKit).where(
            ApplicationKit.id == kit_id,
            ApplicationKit.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def delete_kit_for_user(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    kit_id: uuid.UUID,
) -> bool:
    """Delete a kit. Returns True if deleted, False if not owned/missing."""
    kit = await get_kit_for_user(db, user_id=user_id, kit_id=kit_id)
    if kit is None:
        return False
    await db.delete(kit)
    await db.commit()
    return True


async def _load_owned(
    db: AsyncSession,
    model: Any,
    *,
    user_id: uuid.UUID,
    obj_id: uuid.UUID | None,
    kind: str,
) -> Any | None:
    """Fetch *obj_id* if owned by *user_id*. 404 if it exists for someone else
    (or not at all). Returns None when *obj_id* is None.
    """
    if obj_id is None:
        return None
    result = await db.execute(
        select(model).where(model.id == obj_id, model.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{kind} not found or not owned by user",
        )
    return row


async def _load_mock_report(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID | None,
) -> MockSessionReport | None:
    """Fetch the report for a session, after verifying the session belongs to
    *user_id*. The report row itself has no user_id column — ownership is
    derived via the parent InterviewSession.
    """
    if session_id is None:
        return None
    from app.models.interview_session import InterviewSession

    sess = await db.execute(
        select(InterviewSession).where(
            InterviewSession.id == session_id,
            InterviewSession.user_id == user_id,
        )
    )
    if sess.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mock interview session not found or not owned by user",
        )
    rep = await db.execute(
        select(MockSessionReport).where(
            MockSessionReport.session_id == session_id
        )
    )
    return rep.scalar_one_or_none()


async def _latest_resume_for_user(
    db: AsyncSession, *, user_id: uuid.UUID
) -> Resume | None:
    """Pick the user's most recently-updated Resume for the snapshot.

    The kit doesn't take a `base_resume_id` from the request — students have
    one canonical resume in the current product, so we resolve it server-side.
    """
    result = await db.execute(
        select(Resume)
        .where(Resume.user_id == user_id)
        .order_by(Resume.updated_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def build_kit(
    db: AsyncSession,
    *,
    user: User,
    request: BuildKitRequest,
) -> ApplicationKit:
    """Build, persist, and render an Application Kit row.

    Flow:
      1. Validate every referenced row is owned by *user* (404 otherwise).
      2. Insert a kit row with status='building'.
      3. Build the manifest snapshot dict.
      4. Render the PDF.
      5. Flip status to 'ready', stash the PDF, set generated_at.
      6. On any exception during 3-5: mark 'failed' and re-raise.
    """
    user_id = user.id

    # -- 1. Resolve all refs (raises HTTPException on bad ownership) --------
    resume = await _latest_resume_for_user(db, user_id=user_id)
    tailored = await _load_owned(
        db, TailoredResume,
        user_id=user_id, obj_id=request.tailored_resume_id, kind="Tailored resume",
    )
    jd = await _load_owned(
        db, JdLibrary,
        user_id=user_id, obj_id=request.jd_library_id, kind="JD",
    )
    autopsy = await _load_owned(
        db, PortfolioAutopsyResult,
        user_id=user_id, obj_id=request.autopsy_id, kind="Autopsy",
    )
    mock_report = await _load_mock_report(
        db, user_id=user_id, session_id=request.mock_session_id
    )

    # -- 2. Insert building row ---------------------------------------------
    kit = ApplicationKit(
        user_id=user_id,
        label=request.label,
        target_role=request.target_role,
        base_resume_id=resume.id if resume else None,
        tailored_resume_id=request.tailored_resume_id,
        jd_library_id=request.jd_library_id,
        mock_session_id=request.mock_session_id,
        autopsy_id=request.autopsy_id,
        manifest={},
        status="building",
    )
    db.add(kit)
    await db.commit()
    await db.refresh(kit)

    try:
        # -- 3. Build manifest snapshot --------------------------------------
        manifest = build_manifest(
            resume=resume,
            tailored=tailored,
            jd=jd,
            mock_report=mock_report,
            autopsy=autopsy,
            label=request.label,
            target_role=request.target_role,
        )

        # -- 4. Render PDF --------------------------------------------------
        pdf_bytes = pdf_renderer.render_application_kit(manifest)

        # -- 5. Flip to ready -----------------------------------------------
        kit.manifest = manifest
        kit.pdf_blob = pdf_bytes
        kit.status = "ready"
        kit.generated_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(kit)

        log.info(
            "application_kit.ready",
            user_id=str(user_id),
            kit_id=str(kit.id),
            sections=sorted(
                k for k in manifest
                if k not in {"label", "target_role", "built_at"}
            ),
            pdf_bytes=len(pdf_bytes),
        )
        return kit

    except Exception as exc:
        log.exception(
            "application_kit.build_failed",
            user_id=str(user_id),
            kit_id=str(kit.id),
            error=str(exc),
        )
        kit.status = "failed"
        await db.commit()
        raise
