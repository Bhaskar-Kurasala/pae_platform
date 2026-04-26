"""Orchestrator for the tailored resume + cover letter pipeline.

Sequence:
  1. Quota check (first-resume-free aware).
  2. JD parse (Haiku).
  3. Profile aggregate (BaseResume + intake_data + skill map + allowlist).
  4. Tailoring agent (Sonnet) → resume content.
  5. Hallucination validator. Up to 2 retries with feedback injected.
  6. Cover letter agent (Sonnet) → cover letter body.
  7. PDF render (WeasyPrint or fallback).
  8. Persist TailoredResume + GenerationLog.
  9. Optional MinIO upload (with BLOB fallback already on the row).
 10. Cost-cap circuit breaker — if accumulated cost exceeds ₹20, abort.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.cover_letter import CoverLetterAgent
from app.agents.llm_factory import estimate_cost_inr
from app.agents.tailored_resume import TailoredResumeAgent
from app.models.agent_invocation_log import (
    SOURCE_RESUME,
    STATUS_CAP_EXCEEDED,
    STATUS_FAILED,
    STATUS_SUCCEEDED,
)
from app.models.generation_log import GenerationLog
from app.models.resume import Resume
from app.services.agent_invocation_logger import log_invocation
from app.models.tailored_resume import TailoredResume
from app.models.user import User
from app.services.hallucination_validator import validate
from app.services.jd_parser import parse_jd
from app.services.pdf_renderer import (
    StudentInfo,
    render_cover_letter_pdf,
    render_resume_pdf,
)
from app.services.profile_aggregator import build_base_resume_bundle
from app.services.quota_service import check_quota, record_quota_block

log = structlog.get_logger()

COST_CAP_INR = 20.0
MAX_TAILORING_RETRIES = 2


class QuotaExceededError(Exception):
    def __init__(self, reason: str, reset_at: Any = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.reset_at = reset_at


class CostCapExceededError(Exception):
    """Raised when accumulated cost exceeds COST_CAP_INR mid-pipeline."""


@dataclass
class TailorResult:
    tailored_resume_id: uuid.UUID
    content: dict[str, Any]
    cover_letter: dict[str, Any]
    validation: dict[str, Any]
    cost_inr: float
    quota_after: dict[str, Any]


async def _persist_intake(
    db: AsyncSession,
    *,
    base_resume: Resume,
    intake_answers: dict[str, Any],
) -> None:
    """Merge the supplied intake answers into ``base_resume.intake_data``.

    We persist preferences + non-platform experience + education so future
    runs can skip questions the student has already answered.
    """
    existing = dict(base_resume.intake_data or {})
    prefs = dict(existing.get("preferences", {}))
    if intake_answers.get("target_role"):
        prefs["target_role"] = intake_answers["target_role"]
    if intake_answers.get("salary_expectation"):
        prefs["salary_expectation"] = intake_answers["salary_expectation"]
    if intake_answers.get("location_preference"):
        prefs["location"] = intake_answers["location_preference"]
    if intake_answers.get("availability"):
        prefs["availability"] = intake_answers["availability"]
    if prefs:
        existing["preferences"] = prefs

    if intake_answers.get("non_platform_experience"):
        existing.setdefault("non_platform_experience", []).append(
            {
                "id": f"npe_{uuid.uuid4().hex[:8]}",
                "raw": intake_answers["non_platform_experience"],
            }
        )
    if intake_answers.get("education"):
        existing.setdefault("education", []).append(
            {
                "id": f"edu_{uuid.uuid4().hex[:8]}",
                "raw": intake_answers["education"],
            }
        )

    base_resume.intake_data = existing
    await db.commit()
    await db.refresh(base_resume)


# Maps the legacy GenerationLog.event field onto the cost-only
# agent_invocation_log.status field. Lifecycle-only events (started,
# quota_blocked, downloaded) intentionally have no entry — they do not
# dual-write. See migration 0040 for the full rationale.
_EVENT_TO_STATUS: dict[str, str] = {
    "completed": STATUS_SUCCEEDED,
    "failed": STATUS_FAILED,
    "cap_exceeded": STATUS_CAP_EXCEEDED,
}


async def _log_event(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    event: str,
    tailored_resume_id: uuid.UUID | None = None,
    model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_inr: float | None = None,
    latency_ms: int | None = None,
    validation_passed: bool | None = None,
    error_message: str | None = None,
) -> None:
    """Persist a GenerationLog row + dual-write to agent_invocation_log
    when the event is cost-bearing.

    Lifecycle-only events (started, quota_blocked, downloaded) skip the
    dual-write — the new table is cost-only by design. Cost-bearing events
    (completed, failed, cap_exceeded) write to BOTH tables in the same
    transaction so the dual-write window stays consistent under failures.
    """
    db.add(
        GenerationLog(
            user_id=user_id,
            tailored_resume_id=tailored_resume_id,
            event=event,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_inr=cost_inr,
            latency_ms=latency_ms,
            validation_passed=validation_passed,
            error_message=error_message,
        )
    )
    status = _EVENT_TO_STATUS.get(event)
    if status is not None:
        # Resume agent does not yet split per-sub-agent (jd_parser,
        # tailoring agent, validator each have their own LLMs but the
        # legacy table folds them into one event). Use the synthetic
        # 'tailoring_agent' label to match the historical backfill — once
        # per-sub-agent observability is wired (Phase 2), this caller
        # site will split into multiple log_invocation calls.
        await log_invocation(
            db,
            user_id=user_id,
            source=SOURCE_RESUME,
            source_id=tailored_resume_id,
            sub_agent="tailoring_agent",
            model=model or "unknown",
            tokens_in=int(input_tokens or 0),
            tokens_out=int(output_tokens or 0),
            cost_inr=float(cost_inr or 0.0),
            latency_ms=latency_ms,
            status=status,
            error_message=error_message,
        )
    await db.commit()


async def generate_tailored_resume(
    db: AsyncSession,
    *,
    user: User,
    jd_text: str,
    intake_answers: dict[str, Any],
    jd_id: uuid.UUID | None = None,
) -> TailorResult:
    """Run the full tailored-resume pipeline.

    Raises:
      QuotaExceededError — if the user is over quota and not first-time.
      CostCapExceededError — if cost runs over ₹20 mid-pipeline.
    """
    started_at = time.monotonic()
    user_id = user.id
    log.info("tailored_resume.started", user_id=str(user_id), jd_chars=len(jd_text))

    # -- 1. Quota check ------------------------------------------------------
    quota = await check_quota(db, user_id=user_id)
    if not quota.allowed:
        await record_quota_block(db, user_id=user_id, reason=quota.reason)
        raise QuotaExceededError(reason=quota.reason, reset_at=quota.reset_at)

    await _log_event(db, user_id=user_id, event="started")

    accumulated_cost = 0.0

    def _bump_cost(model: str | None, inp: int, out: int) -> None:
        nonlocal accumulated_cost
        if not model:
            return
        accumulated_cost += estimate_cost_inr(model=model, input_tokens=inp, output_tokens=out)
        if accumulated_cost > COST_CAP_INR:
            raise CostCapExceededError(
                f"Cost cap exceeded: ₹{accumulated_cost:.2f} > ₹{COST_CAP_INR}"
            )

    try:
        # -- 2. JD parse -----------------------------------------------------
        parsed_jd = await parse_jd(jd_text)
        _bump_cost(parsed_jd.model, parsed_jd.input_tokens, parsed_jd.output_tokens)

        # -- 3. Persist intake + build bundle --------------------------------
        bundle = await build_base_resume_bundle(db, user_id=user_id)
        if intake_answers:
            await _persist_intake(
                db,
                base_resume=bundle.resume,
                intake_answers=intake_answers,
            )
            # Rebuild bundle so the new intake entries are in the allowlist.
            bundle = await build_base_resume_bundle(db, user_id=user_id)

        evidence = bundle.evidence_summary()

        # -- 4. Tailoring agent + 5. Validator loop --------------------------
        tailoring_agent = TailoredResumeAgent()
        feedback: list[str] = []
        last_content: dict[str, Any] = {}
        last_validation: Any = None
        for attempt in range(MAX_TAILORING_RETRIES + 1):
            res = await tailoring_agent.generate(
                evidence=evidence,
                parsed_jd=parsed_jd.to_dict(),
                evidence_allowlist=bundle.evidence_allowlist,
                regenerate_feedback=feedback,
            )
            _bump_cost(res["model"], res["input_tokens"], res["output_tokens"])
            last_content = res["content"]
            validation_result = await validate(
                last_content,
                evidence=evidence,
                evidence_allowlist=bundle.evidence_allowlist,
            )
            last_validation = validation_result
            if validation_result.passed:
                break
            log.warning(
                "tailored_resume.validation_failed",
                attempt=attempt,
                violations=validation_result.violations,
            )
            feedback = validation_result.violations[:6]

        # -- 6. Cover letter -------------------------------------------------
        cover_agent = CoverLetterAgent()
        cover_res = await cover_agent.generate(
            resume_content=last_content,
            parsed_jd=parsed_jd.to_dict(),
            intake_answers=intake_answers,
        )
        _bump_cost(cover_res["model"], cover_res["input_tokens"], cover_res["output_tokens"])

        # -- 7. PDF render ---------------------------------------------------
        student = StudentInfo(
            full_name=user.full_name or user.email or "Candidate",
            email=user.email or "",
            location=(bundle.intake_data.get("preferences", {}) or {}).get("location", ""),
        )
        resume_pdf_bytes = render_resume_pdf(
            content=last_content,
            student=student,
            intake_data=bundle.intake_data,
        )
        cover_pdf_bytes = render_cover_letter_pdf(
            body=cover_res["content"]["body"],
            student=student,
        )

        # -- 8. Persist TailoredResume --------------------------------------
        validation_dict = (
            last_validation.to_dict() if last_validation is not None else {"passed": False}
        )
        tailored = TailoredResume(
            user_id=user_id,
            base_resume_id=bundle.resume.id,
            jd_id=jd_id,
            jd_text=jd_text,
            jd_parsed=parsed_jd.to_dict(),
            intake_answers=intake_answers,
            content={
                **last_content,
                "cover_letter": cover_res["content"],
            },
            validation=validation_dict,
            pdf_blob=resume_pdf_bytes,
        )
        db.add(tailored)
        await db.commit()
        await db.refresh(tailored)

        # MinIO upload deferred — see IMPLEMENTATION_NOTES. Cover letter PDF
        # is regenerated on demand from `content.cover_letter.body`, so we
        # don't need a second blob column.
        _ = cover_pdf_bytes  # noqa: F841

        latency_ms = int((time.monotonic() - started_at) * 1000)
        await _log_event(
            db,
            user_id=user_id,
            tailored_resume_id=tailored.id,
            event="completed",
            model=res["model"],
            input_tokens=res["input_tokens"],
            output_tokens=res["output_tokens"],
            cost_inr=accumulated_cost,
            latency_ms=latency_ms,
            validation_passed=validation_dict.get("passed", False),
        )

        # Recompute quota for the response so the UI's chip stays accurate.
        new_quota = await check_quota(db, user_id=user_id)

        log.info(
            "tailored_resume.completed",
            user_id=str(user_id),
            tailored_resume_id=str(tailored.id),
            cost_inr=accumulated_cost,
            latency_ms=latency_ms,
            validation_passed=validation_dict.get("passed", False),
        )

        return TailorResult(
            tailored_resume_id=tailored.id,
            content=last_content,
            cover_letter=cover_res["content"],
            validation=validation_dict,
            cost_inr=accumulated_cost,
            quota_after={
                "remaining_today": new_quota.remaining_today,
                "remaining_month": new_quota.remaining_month,
            },
        )

    except CostCapExceededError as exc:
        log.error("tailored_resume.cost_cap_exceeded", user_id=str(user_id), cost=accumulated_cost)
        await _log_event(
            db,
            user_id=user_id,
            event="failed",
            cost_inr=accumulated_cost,
            error_message=str(exc),
        )
        raise
    except QuotaExceededError:
        raise
    except Exception as exc:
        log.exception("tailored_resume.failed", user_id=str(user_id), error=str(exc))
        await _log_event(
            db,
            user_id=user_id,
            event="failed",
            cost_inr=accumulated_cost,
            error_message=str(exc)[:500],
        )
        raise
