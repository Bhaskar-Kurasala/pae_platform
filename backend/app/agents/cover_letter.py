"""CoverLetterAgent — bundled with the tailored resume.

Generates a 250-word, plain-text cover letter that draws only on the
tailored resume's content + the parsed JD. No new claims.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from tenacity import retry, stop_after_attempt, wait_exponential

from app.agents.base_agent import AgentState, BaseAgent
from app.agents.llm_factory import build_llm, model_for
from app.agents.registry import register
from app.services.career_service import extract_json_object, normalize_llm_content

log = structlog.get_logger()

_PROMPT = (Path(__file__).parent / "prompts" / "cover_letter.md").read_text()


@register
class CoverLetterAgent(BaseAgent):
    """Generates a cover letter that pairs with the tailored resume."""

    name = "cover_letter"
    description = (
        "Generates a 250-word cover letter aligned with a tailored resume "
        "and parsed JD. Bundled with every tailored-resume generation."
    )
    trigger_conditions = ["cover letter", "write a cover letter"]
    model = "claude-sonnet-4-6"

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def _invoke(self, llm: Any, *, resume_content: dict[str, Any], parsed_jd: dict[str, Any], intake_answers: dict[str, Any]) -> tuple[str, Any]:
        user_message = (
            "TAILORED RESUME CONTENT:\n"
            f"{json.dumps(resume_content, indent=2)}\n\n"
            "PARSED JD:\n"
            f"{json.dumps(parsed_jd, indent=2)}\n\n"
            "INTAKE ANSWERS:\n"
            f"{json.dumps(intake_answers, indent=2)}\n\n"
            "Generate the cover letter JSON now."
        )
        response = await llm.ainvoke([
            SystemMessage(content=_PROMPT),
            HumanMessage(content=user_message),
        ])
        return normalize_llm_content(response.content), response

    async def generate(
        self,
        *,
        resume_content: dict[str, Any],
        parsed_jd: dict[str, Any],
        intake_answers: dict[str, Any],
    ) -> dict[str, Any]:
        llm = build_llm(max_tokens=900, tier="smart")
        raw_text, response = await self._invoke(
            llm,
            resume_content=resume_content,
            parsed_jd=parsed_jd,
            intake_answers=intake_answers,
        )
        parsed = extract_json_object(raw_text)
        if not parsed or "body" not in parsed:
            log.warning("cover_letter.json_extraction_failed", raw_len=len(raw_text))
            parsed = {"body": "", "subject_line": ""}

        usage = getattr(response, "usage_metadata", None) or {}
        input_tokens = int(usage.get("input_tokens", 0)) if isinstance(usage, dict) else 0
        output_tokens = int(usage.get("output_tokens", 0)) if isinstance(usage, dict) else 0

        return {
            "content": {
                "body": str(parsed.get("body") or ""),
                "subject_line": str(parsed.get("subject_line") or ""),
            },
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "model": model_for("smart"),
        }

    async def execute(self, state: AgentState) -> AgentState:
        resume_content = state.context.get("resume_content")
        parsed_jd = state.context.get("parsed_jd", {})
        intake_answers = state.context.get("intake_answers", {})
        if not resume_content:
            return state.model_copy(
                update={
                    "response": "Cover letter generation requires resume_content in context."
                }
            )
        result = await self.generate(
            resume_content=resume_content,
            parsed_jd=parsed_jd,
            intake_answers=intake_answers,
        )
        return state.model_copy(
            update={
                "response": result["content"]["body"],
                "metadata": {
                    "input_tokens": result["input_tokens"],
                    "output_tokens": result["output_tokens"],
                    "model": result["model"],
                    "subject_line": result["content"]["subject_line"],
                },
            }
        )
