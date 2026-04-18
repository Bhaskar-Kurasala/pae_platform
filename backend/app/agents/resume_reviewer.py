# ADD TO registry.py: import app.agents.resume_reviewer  # noqa: F401

import re
from pathlib import Path
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from tenacity import retry, stop_after_attempt, wait_exponential

from app.agents.base_agent import AgentState, BaseAgent
from app.agents.registry import register
from app.core.config import settings

log = structlog.get_logger()

_PROMPT = (Path(__file__).parent / "prompts" / "resume_reviewer.md").read_text()

_ASK_FOR_RESUME = (
    "I'd be happy to review your resume for AI engineering roles! "
    "Please share your resume text directly in the chat (paste it as plain text). "
    "I'll give you a scored review with specific line-item improvements."
)


@register
class ResumeReviewerAgent(BaseAgent):
    """Reviews resumes for AI engineering roles with scored, structured feedback.

    Expects `resume_text` in context. If not provided, prompts the student.
    Returns: overall score, top 3 strengths, critical issues, and 5 before/after
    line-item improvements focused on AI/ML roles.
    """

    name = "resume_reviewer"
    description = (
        "Reviews resumes for AI engineering roles: overall score 0-100, "
        "top strengths, critical issues, and 5 specific before/after line-item improvements."
    )
    trigger_conditions = [
        "review my resume",
        "resume feedback",
        "improve cv",
        "resume critique",
        "check my resume",
    ]
    model = "claude-sonnet-4-6"

    def _build_llm(self, max_tokens: int = 1024):
        from app.agents.llm_factory import build_llm
        return build_llm(max_tokens=max_tokens)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _call_llm(self, llm: Any, resume_text: str) -> str:
        messages: list[Any] = [
            SystemMessage(content=_PROMPT),
            HumanMessage(
                content=(
                    f"Please review the following resume for AI engineering roles:\n\n"
                    f"---\n{resume_text}\n---\n\n"
                    "Structure your review exactly as specified in the system prompt: "
                    "Overall Score, Top 3 Strengths, Critical Issues, and Line-Item Improvements "
                    "with before/after examples."
                )
            ),
        ]
        response = await llm.ainvoke(messages)
        return str(response.content)

    async def execute(self, state: AgentState) -> AgentState:
        resume_text: str = state.context.get("resume_text", "").strip()

        # If no resume provided, ask the student to share it
        if not resume_text:
            self._log.info("resume_reviewer.no_resume_provided", student_id=state.student_id)
            return state.model_copy(update={"response": _ASK_FOR_RESUME})

        if settings.minimax_api_key or settings.anthropic_api_key:
            try:
                llm = self._build_llm()
                response_text = await self._call_llm(llm, resume_text)
            except Exception as exc:
                self._log.warning("resume_reviewer.llm_failed", error=str(exc))
                response_text = self._fallback_response()
        else:
            response_text = self._fallback_response()

        return state.model_copy(update={"response": response_text})

    def _fallback_response(self) -> str:
        return (
            "## Overall Score: 0/100\n\n"
            "Resume review service is temporarily unavailable (LLM not configured). "
            "Please try again later or contact support@pae.dev.\n\n"
            "## Top 3 Strengths\n\n"
            "Unable to assess — LLM unavailable.\n\n"
            "## Critical Issues\n\n"
            "Unable to assess — LLM unavailable.\n\n"
            "## Line-Item Improvements\n\n"
            "Unable to generate improvements — LLM unavailable."
        )

    async def evaluate(self, state: AgentState) -> AgentState:
        """Score based on whether response contains a numerical score and before/after examples."""
        response = state.response or ""
        # Check for "Overall Score: X/100" pattern
        has_score = bool(re.search(r"Overall Score[:\s]+\d+/100", response, re.IGNORECASE))
        # Check for "Before:" / "After:" or similar before/after patterns
        has_before_after = (
            "before:" in response.lower()
            or "original:" in response.lower()
            or "improved:" in response.lower()
        )
        score = 0.9 if (has_score and has_before_after) else (0.6 if has_score else 0.3)
        return state.model_copy(update={"evaluation_score": score})
