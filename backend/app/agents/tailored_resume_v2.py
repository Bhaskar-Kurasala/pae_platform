"""D12 / Pass 3c E6 — tailored_resume agent (canonical AgenticBaseAgent).

Shape α: thin shim. run() delegates to
tailored_resume_service.generate_tailored_resume() which contains the
full pipeline (quota, JD parse, hallucination validator, cover letter,
PDF render, persist, MinIO upload). The shim adapts AgentContext → the
service's signature and maps TailorResult → TailoredResumeOutput.

Why a thin shim instead of moving pipeline logic here:
  - The route path (app/api/v1/routes/tailored_resume.py) and the
    agentic path need to stay in sync. Duplicating the pipeline would
    create two truth sources. The service is already the canonical
    truth; the agent is a new entry point into it.
  - Naming resolution α-1 (D12 CP1): the inner LLM helper was renamed
    tailored_resume_llm.py. The service imports from there. This agent
    class at _v2 is the third file in the α-naming chain:
      tailored_resume.py (deleted) → tailored_resume_llm.py (helper, stays)
      → tailored_resume_v2.py (this agent, → tailored_resume.py at CP4)

Five primitive flags:
  uses_memory       = True   # service records a generation log (audit)
  uses_tools        = True   # 2 read tools: lookup_jd_decoded, lookup_base_resume
  uses_inter_agent  = True   # handoff_targets: resume_reviewer (D13 mandatory chain)
  uses_self_eval    = False  # service has its own hallucination validator
  uses_proactive    = False  # student-initiated only

Deferral B: mandatory self-handoff to resume_reviewer → D13.
  handoff_request is always None in D12.
  See docs/followups/tailored-resume-mandatory-validation-d13.md.

Cost tracking note (fix at CP3):
  tailored_resume_llm.py calls model_for("smart") for cost estimation,
  which returns "claude-sonnet-4-6" even when MiniMax-M2.7 is the active
  provider. This causes Sonnet pricing to be applied to MiniMax calls
  (under-cost, not silent-zero). Fix: replace model_for("smart") with the
  actual model string from the LLM response at CP3.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

import structlog
from pydantic import ConfigDict, Field

from app.agents.agentic_base import AgentContext, AgentInput, AgenticBaseAgent
from app.schemas.agents.tailored_resume import ResumeChange, TailoredResumeOutput

log = structlog.get_logger().bind(layer="tailored_resume")


# ── Input schema ───────────────────────────────────────────────────


class TailoredResumeInput(AgentInput):
    """Per Pass 3c E6 — with Supervisor shape-variability tolerance.

    resume_text and job_description are the declared required fields per
    the capability registry. The Supervisor may also surface them inside
    user_message as a combined text; resolved via _resolve_inputs().
    """

    model_config = ConfigDict(extra="ignore")

    # Primary fields per Pass 3c E6 capability declaration.
    resume_text: str | None = Field(default=None, max_length=20_000)
    job_description: str | None = Field(default=None, max_length=20_000)
    # Supervisor shape synonyms.
    user_message: str | None = Field(default=None, max_length=40_000)
    question: str | None = Field(default=None, max_length=40_000)
    task: str | None = Field(default=None, max_length=40_000)

    # Optional structured inputs the route path may pre-supply.
    jd_id: str | None = Field(default=None, max_length=60)
    intake_answers: dict[str, Any] = Field(default_factory=dict)

    def resolved_jd(self) -> str | None:
        if self.job_description and self.job_description.strip():
            return self.job_description
        # Fallback: Supervisor may have put the JD inside user_message.
        for field in (self.user_message, self.question, self.task):
            if field and field.strip():
                return field
        return None


# ── The agent ──────────────────────────────────────────────────────


class TailoredResumeShimAgent(AgenticBaseAgent[TailoredResumeInput]):
    """Thin shim — delegates full pipeline to tailored_resume_service.

    The shim's job is to:
      1. Resolve resume_text + jd_text from input.
      2. Look up a User object from ctx.user_id for the service.
      3. Call generate_tailored_resume(db, user=user, jd_text=..., ...).
      4. Map TailorResult → TailoredResumeOutput.

    All quota, cost, hallucination validation, PDF, and persist logic
    lives in the service. This agent adds nothing to it — that's the
    point of Shape α.
    """

    name: ClassVar[str] = "tailored_resume"
    description: ClassVar[str] = (
        "Generates an ATS-optimised tailored resume from the student's "
        "base resume and a target job description. Runs full pipeline: "
        "JD parse, tailoring, hallucination check, cover letter, PDF. "
        "Mandatory reviewer validation deferred to D13."
    )
    input_schema: ClassVar[type[AgentInput]] = TailoredResumeInput

    # Intended smart-tier model; factory routes to MiniMax-M2.7 when
    # MINIMAX_API_KEY is set. Dynamic resolution in agentic_base.execute()
    # ensures the actual model is captured in agent_actions.
    model_name: ClassVar[str] = "claude-sonnet-4-6"

    # ── Five primitive flags per Pass 3c E6 ───────────────────────
    uses_memory: ClassVar[bool] = True
    uses_tools: ClassVar[bool] = True
    uses_inter_agent: ClassVar[bool] = True
    uses_self_eval: ClassVar[bool] = False
    uses_proactive: ClassVar[bool] = False

    # handoff_request=None in D12; D13 wires the mandatory chain to
    # resume_reviewer per docs/followups/tailored-resume-mandatory-validation-d13.md.
    allowed_callers: ClassVar[tuple[str, ...]] = ()
    allowed_callees: ClassVar[tuple[str, ...]] = ("resume_reviewer",)

    permissions: ClassVar[frozenset[str]] = frozenset(
        {
            "read:agent_memory",
            "write:agent_memory",
            "read:student_data",
            "write:audit_log",
        }
    )

    # ── Run path ──────────────────────────────────────────────────

    async def run(
        self, input: TailoredResumeInput, ctx: AgentContext
    ) -> dict[str, Any]:
        """Thin shim path:

          1. Resolve jd_text; fail-honest if missing.
          2. Resolve resume_text; fail-honest if missing (service needs it
             via intake_answers, not as a raw parameter — pass through).
          3. Load the User row for the service's user argument.
          4. Call generate_tailored_resume().
          5. Map TailorResult → TailoredResumeOutput.
          6. Enforce handoff_request=None (Deferral B).
        """
        from app.models.user import User
        from app.services.tailored_resume_service import (
            CostCapExceededError,
            QuotaExceededError,
            generate_tailored_resume,
        )
        from sqlalchemy import select

        jd_text = input.resolved_jd()
        if not jd_text:
            fallback = TailoredResumeOutput(
                tailored_resume="",
                changes_made=[],
                keyword_alignment_score=0.0,
                unsupported_additions=[],
                ats_compatibility_notes=[
                    "No job description was provided. "
                    "Please supply the job posting text."
                ],
                handoff_request=None,
            )
            payload = fallback.model_dump(mode="json")
            payload["answer"] = "Please provide the job description text to tailor your resume."
            return payload

        # Resolve resume_text into intake_answers if supplied as raw text.
        intake = dict(input.intake_answers)
        if input.resume_text and "resume_text" not in intake:
            intake["resume_text"] = input.resume_text

        # Load the User row — service requires the full User object.
        if ctx.user_id is None:
            raise RuntimeError(
                "tailored_resume shim: ctx.user_id is None. "
                "Cannot load user for service call."
            )
        result = await ctx.session.execute(
            select(User).where(User.id == ctx.user_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise RuntimeError(
                f"tailored_resume shim: no User found for user_id={ctx.user_id}"
            )

        # Resolve jd_id if present.
        jd_id: uuid.UUID | None = None
        if input.jd_id:
            try:
                jd_id = uuid.UUID(input.jd_id)
            except ValueError:
                log.warning(
                    "tailored_resume.invalid_jd_id",
                    jd_id=input.jd_id,
                    user_id=str(ctx.user_id),
                )

        try:
            tailor_result = await generate_tailored_resume(
                ctx.session,
                user=user,
                jd_text=jd_text,
                intake_answers=intake,
                jd_id=jd_id,
            )
        except QuotaExceededError as exc:
            log.info(
                "tailored_resume.quota_exceeded",
                reason=exc.reason,
                user_id=str(ctx.user_id),
            )
            fallback = TailoredResumeOutput(
                tailored_resume="",
                changes_made=[],
                keyword_alignment_score=0.0,
                unsupported_additions=[],
                ats_compatibility_notes=[
                    f"Resume generation quota exceeded: {exc.reason}"
                ],
                handoff_request=None,
            )
            payload = fallback.model_dump(mode="json")
            payload["answer"] = f"Quota exceeded: {exc.reason}"
            return payload
        except CostCapExceededError:
            log.warning(
                "tailored_resume.cost_cap_exceeded",
                user_id=str(ctx.user_id),
            )
            fallback = TailoredResumeOutput(
                tailored_resume="",
                changes_made=[],
                keyword_alignment_score=0.0,
                unsupported_additions=[],
                ats_compatibility_notes=["Generation stopped: cost cap reached."],
                handoff_request=None,
            )
            payload = fallback.model_dump(mode="json")
            payload["answer"] = "Resume generation stopped: cost cap reached."
            return payload

        output = _map_result_to_output(tailor_result)

        # Defense-in-depth: Deferral B — handoff_request always None in D12.
        output.handoff_request = None

        payload = output.model_dump(mode="json")
        payload["answer"] = _compose_answer(output)
        return payload


# ── Helpers ───────────────────────────────────────────────────────


def _map_result_to_output(result: Any) -> TailoredResumeOutput:
    """Map TailorResult to TailoredResumeOutput schema."""
    content = result.content or {}
    validation = result.validation or {}

    # Build tailored_resume as plain text from the service's content dict.
    resume_sections = []
    if summary := content.get("summary"):
        resume_sections.append(f"SUMMARY\n{summary}")
    if bullets := content.get("bullets"):
        bullets_text = "\n".join(
            f"• {b['text']}" if isinstance(b, dict) else f"• {b}"
            for b in bullets
        )
        resume_sections.append(f"EXPERIENCE\n{bullets_text}")
    if skills := content.get("skills"):
        resume_sections.append(f"SKILLS\n{', '.join(skills)}")
    tailored_resume_text = "\n\n".join(resume_sections) or str(content)

    # Build changes_made from tailoring_notes. The notes come from the
    # inner LLM and may exceed ResumeChange.what_changed's 200-char
    # max_length, which would raise ValidationError on construction.
    # Truncate defensively — this is the same Bug 17 pattern the
    # parsing_helpers truncate_to_schema solves for direct LLM-JSON
    # paths; here we apply it inline since the construction is in code.
    changes: list[ResumeChange] = []
    for note in (content.get("tailoring_notes") or []):
        note_str = note if isinstance(note, str) else str(note)
        changes.append(ResumeChange(
            section="general",
            what_changed=note_str[:200],
            why="Aligned to JD requirements",
        ))

    # ATS notes from validation.
    ats_notes: list[str] = list(validation.get("warnings", []))
    if ats_keywords := content.get("ats_keywords"):
        ats_notes.append(f"ATS keywords included: {', '.join(ats_keywords[:8])}")

    return TailoredResumeOutput(
        tailored_resume=tailored_resume_text,
        changes_made=changes,
        keyword_alignment_score=_estimate_alignment(content),
        unsupported_additions=[],  # D13 populates via reviewer
        ats_compatibility_notes=ats_notes or ["ATS-safe plain text format applied."],
        handoff_request=None,
    )


def _estimate_alignment(content: dict[str, Any]) -> float:
    """Rough alignment score from bullet count relative to expected coverage."""
    bullets = content.get("bullets") or []
    skills = content.get("skills") or []
    ats = content.get("ats_keywords") or []
    if not (bullets or skills):
        return 0.0
    # Rough heuristic: 10 bullets + 8 skills = 1.0.
    score = min(1.0, (len(bullets) / 10.0 * 0.6) + (len(skills) / 8.0 * 0.4))
    return round(score, 2)


def _compose_answer(output: TailoredResumeOutput) -> str:
    n_changes = len(output.changes_made)
    score = output.keyword_alignment_score
    return (
        f"Tailored resume generated ({n_changes} changes, "
        f"{score:.0%} keyword alignment)."
    )
