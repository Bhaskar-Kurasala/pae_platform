"""Career API routes — resume, interview questions, JD fit, learning plan.

Covers tickets #168, #169, #171, #172, #173.
Routes ≤30 lines each; business logic delegated to career_service.
"""

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.career import (
    FitScoreRequest,
    FitScoreResponse,
    InterviewQuestionItem,
    LearningPlanResponse,
    ResumeResponse,
)
from app.services.career_service import (
    compute_fit_score,
    compute_skill_gap,
    extract_jd_skills,
    generate_learning_plan,
    generate_resume_summary,
    get_or_create_resume,
    get_student_skill_map,
    search_interview_questions,
)

log = structlog.get_logger()
router = APIRouter(prefix="/career", tags=["career"])


@router.get("/resume", response_model=ResumeResponse)
async def get_my_resume(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ResumeResponse:
    """Return (and lazily generate) the current user's resume summary."""
    resume = await get_or_create_resume(db, user_id=current_user.id)
    if not resume.summary:
        skill_map = await get_student_skill_map(db, user_id=current_user.id)
        resume.summary = await generate_resume_summary(skill_map=skill_map)
        await db.commit()
    return ResumeResponse.model_validate(resume, from_attributes=True)


@router.post("/fit-score", response_model=FitScoreResponse)
async def analyze_jd_fit(
    body: FitScoreRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FitScoreResponse:
    """Compute fit score and skill gap for a pasted job description."""
    skill_map = await get_student_skill_map(db, user_id=current_user.id)
    jd_skills = extract_jd_skills(body.jd_text)
    fit_score = compute_fit_score(skill_map, jd_skills)
    skill_gap = compute_skill_gap(skill_map, jd_skills)
    matched = [s for s in jd_skills if s not in skill_gap]
    log.info(
        "career.fit_score_computed",
        user_id=str(current_user.id),
        fit_score=fit_score,
        gap_count=len(skill_gap),
    )
    return FitScoreResponse(
        fit_score=fit_score,
        matched_skills=matched,
        skill_gap=skill_gap,
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
    plan = await generate_learning_plan(skill_gap=skill_gap, jd_title=body.jd_title)
    return LearningPlanResponse(plan=plan, skill_gap=skill_gap)


@router.get("/interview-questions", response_model=list[InterviewQuestionItem])
async def search_questions(
    q: str = Query("", description="Search query"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[InterviewQuestionItem]:
    """Search the interview question bank by keyword."""
    items = await search_interview_questions(db, query=q)
    return [InterviewQuestionItem.model_validate(i, from_attributes=True) for i in items]
