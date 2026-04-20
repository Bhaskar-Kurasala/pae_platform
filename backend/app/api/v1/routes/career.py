"""Career API routes — resume, interview questions, JD fit, learning plan, JD library.

Covers tickets #168, #169, #171, #172, #173, #175.
Routes ≤30 lines each; business logic delegated to career_service.
"""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.career import (
    FitScoreRequest,
    FitScoreResponse,
    InterviewQuestionItem,
    JdLibraryItem,
    LearningPlanResponse,
    ResumeRegenerateRequest,
    ResumeResponse,
    SaveJdRequest,
)
from app.services.career_service import (
    compute_fit_score,
    compute_skill_gap,
    compute_three_bucket_gap,
    compute_verdict,
    delete_jd_from_library,
    extract_jd_skills,
    generate_learning_plan,
    get_jd_library,
    get_or_create_resume,
    get_student_skill_map,
    regenerate_resume,
    save_jd_to_library,
    search_interview_questions,
)

log = structlog.get_logger()
router = APIRouter(prefix="/career", tags=["career"])


@router.get("/resume", response_model=ResumeResponse)
async def get_my_resume(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ResumeResponse:
    """Return the current user's full structured resume, generating it on first call."""
    resume = await regenerate_resume(db, user_id=current_user.id, force=False)
    data = {
        "id": resume.id,
        "title": resume.title,
        "summary": resume.summary,
        "bullets": resume.bullets or [],
        "skills_snapshot": resume.skills_snapshot,
        "linkedin_blurb": resume.linkedin_blurb,
        "ats_keywords": resume.ats_keywords or [],
        "verdict": resume.verdict,
    }
    return ResumeResponse.model_validate(data)


@router.post("/resume/regenerate", response_model=ResumeResponse)
async def regenerate_my_resume(
    body: ResumeRegenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ResumeResponse:
    """Force-regenerate the user's resume via Claude and return the full result."""
    resume = await regenerate_resume(db, user_id=current_user.id, force=body.force)
    log.info(
        "career.resume.regenerate_route",
        user_id=str(current_user.id),
        force=body.force,
    )
    data = {
        "id": resume.id,
        "title": resume.title,
        "summary": resume.summary,
        "bullets": resume.bullets or [],
        "skills_snapshot": resume.skills_snapshot,
        "linkedin_blurb": resume.linkedin_blurb,
        "ats_keywords": resume.ats_keywords or [],
        "verdict": resume.verdict,
    }
    return ResumeResponse.model_validate(data)


@router.post("/fit-score", response_model=FitScoreResponse)
async def analyze_jd_fit(
    body: FitScoreRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FitScoreResponse:
    """Compute fit score, three-bucket gap analysis, and verdict for a pasted JD."""
    skill_map = await get_student_skill_map(db, user_id=current_user.id)
    jd_skills = extract_jd_skills(body.jd_text)
    fit_score = compute_fit_score(skill_map, jd_skills)
    skill_gap = compute_skill_gap(skill_map, jd_skills)
    matched = [s for s in jd_skills if s not in skill_gap]
    proven, unproven, missing = compute_three_bucket_gap(skill_map, jd_skills)
    verdict = compute_verdict(fit_score, proven, unproven, missing)
    log.info(
        "career.fit_score_computed",
        user_id=str(current_user.id),
        fit_score=fit_score,
        gap_count=len(skill_gap),
        verdict=verdict.verdict,
    )
    return FitScoreResponse(
        fit_score=fit_score,
        matched_skills=matched,
        skill_gap=skill_gap,
        verdict=verdict,
    )


@router.post("/learning-plan", response_model=LearningPlanResponse)
async def get_learning_plan_for_jd(
    body: FitScoreRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LearningPlanResponse:
    """Generate a 4-week learning plan to close the skill gap for a JD."""
    skill_map = await get_student_skill_map(db, user_id=current_user.id)
    jd_skills = extract_jd_skills(body.jd_text)
    skill_gap = compute_skill_gap(skill_map, jd_skills)
    proven, unproven, missing = compute_three_bucket_gap(skill_map, jd_skills)
    fit_score = compute_fit_score(skill_map, jd_skills)
    verdict = compute_verdict(fit_score, proven, unproven, missing)
    plan = await generate_learning_plan(skill_gap=skill_gap, jd_title=body.jd_title)
    return LearningPlanResponse(plan=plan, skill_gap=skill_gap, verdict=verdict)


@router.get("/interview-questions", response_model=list[InterviewQuestionItem])
async def search_questions(
    q: str = Query("", description="Search query"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[InterviewQuestionItem]:
    """Search the interview question bank by keyword."""
    items = await search_interview_questions(db, query=q)
    return [InterviewQuestionItem.model_validate(i, from_attributes=True) for i in items]


# ---------------------------------------------------------------------------
# JD Library routes
# ---------------------------------------------------------------------------


@router.post("/jd-library", response_model=JdLibraryItem, status_code=status.HTTP_201_CREATED)
async def save_jd(
    body: SaveJdRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JdLibraryItem:
    """Save a job description to the user's personal JD library.

    If a JD with the same title already exists for this user it is updated.
    A fit score and verdict are automatically computed from the JD text.
    """
    skill_map = await get_student_skill_map(db, user_id=current_user.id)
    jd_skills = extract_jd_skills(body.jd_text)
    fit_score = compute_fit_score(skill_map, jd_skills)
    proven, unproven, missing = compute_three_bucket_gap(skill_map, jd_skills)
    verdict_obj = compute_verdict(fit_score, proven, unproven, missing)

    item = await save_jd_to_library(
        db,
        user_id=current_user.id,
        title=body.title,
        company=body.company,
        jd_text=body.jd_text,
        fit_score=fit_score,
        verdict=verdict_obj.verdict,
    )
    log.info(
        "career.jd_library.route_saved",
        user_id=str(current_user.id),
        jd_id=str(item.id),
        verdict=verdict_obj.verdict,
    )
    return JdLibraryItem.model_validate(item, from_attributes=True)


@router.get("/jd-library", response_model=list[JdLibraryItem])
async def list_jd_library(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[JdLibraryItem]:
    """Return all saved JDs for the authenticated user, newest first."""
    items = await get_jd_library(db, user_id=current_user.id)
    return [JdLibraryItem.model_validate(i, from_attributes=True) for i in items]


@router.delete("/jd-library/{jd_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_jd_from_library(
    jd_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a saved JD from the user's library."""
    deleted = await delete_jd_from_library(db, user_id=current_user.id, jd_id=jd_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="JD not found in your library.",
        )
