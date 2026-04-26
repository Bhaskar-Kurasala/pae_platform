"""TailoredResumeAgent — generates a JD-tailored resume from verified evidence.

Used by the tailored-resume orchestrator (services/tailored_resume_service.py),
not by the MOA chat dispatcher. Registration with the registry is for
discoverability and admin tooling only — the agent never receives free-text
chat input.
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

_PROMPT = (Path(__file__).parent / "prompts" / "tailored_resume.md").read_text()


@register
class TailoredResumeAgent(BaseAgent):
    """Generates a JD-tailored resume payload (JSON) from a verified profile."""

    name = "tailored_resume"
    description = (
        "Generates a JD-tailored, ATS-safe resume from the student's verified "
        "platform evidence. Cites only allowlisted skills and self-attested entries."
    )
    trigger_conditions = [
        "tailor my resume",
        "generate tailored resume",
        "resume for this jd",
    ]
    model = "claude-sonnet-4-6"

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def _invoke(self, llm: Any, *, evidence: dict[str, Any], parsed_jd: dict[str, Any], evidence_allowlist: list[str], regenerate_feedback: list[str]) -> tuple[str, Any]:
        feedback_block = ""
        if regenerate_feedback:
            feedback_block = (
                "\n\nIMPORTANT — your previous attempt was rejected for these reasons. "
                "Fix them now:\n- " + "\n- ".join(regenerate_feedback)
            )

        user_message = (
            "EVIDENCE (the only facts you may cite):\n"
            f"{json.dumps(evidence, indent=2)}\n\n"
            "EVIDENCE_ALLOWLIST (allowed values for any bullet's evidence_id):\n"
            f"{json.dumps(sorted(evidence_allowlist))}\n\n"
            "PARSED JD:\n"
            f"{json.dumps(parsed_jd, indent=2)}\n\n"
            "Generate the tailored resume JSON now."
            + feedback_block
        )
        response = await llm.ainvoke([
            SystemMessage(content=_PROMPT),
            HumanMessage(content=user_message),
        ])
        return normalize_llm_content(response.content), response

    async def generate(
        self,
        *,
        evidence: dict[str, Any],
        parsed_jd: dict[str, Any],
        evidence_allowlist: set[str],
        regenerate_feedback: list[str] | None = None,
    ) -> dict[str, Any]:
        """Direct entrypoint used by the orchestrator.

        Returns ``{"content": <parsed-json>, "input_tokens": int, "output_tokens": int, "model": str}``.
        Raises if the LLM call itself fails after retries.
        """
        llm = build_llm(max_tokens=1800, tier="smart")
        raw_text, response = await self._invoke(
            llm,
            evidence=evidence,
            parsed_jd=parsed_jd,
            evidence_allowlist=list(evidence_allowlist),
            regenerate_feedback=regenerate_feedback or [],
        )
        parsed = extract_json_object(raw_text)
        if not parsed:
            log.warning("tailored_resume.json_extraction_failed", raw_len=len(raw_text))
            parsed = {}

        usage = getattr(response, "usage_metadata", None) or {}
        input_tokens = int(usage.get("input_tokens", 0)) if isinstance(usage, dict) else 0
        output_tokens = int(usage.get("output_tokens", 0)) if isinstance(usage, dict) else 0

        return {
            "content": parsed,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "model": model_for("smart"),
        }

    async def execute(self, state: AgentState) -> AgentState:
        """BaseAgent integration — only used if invoked through MOA. The
        orchestrator calls :meth:`generate` directly with structured inputs."""
        evidence = state.context.get("evidence")
        parsed_jd = state.context.get("parsed_jd")
        evidence_allowlist = state.context.get("evidence_allowlist")
        if not evidence or not parsed_jd or not evidence_allowlist:
            return state.model_copy(
                update={
                    "response": "Tailored resume generation requires evidence, "
                    "parsed_jd, and evidence_allowlist in context."
                }
            )
        result = await self.generate(
            evidence=evidence,
            parsed_jd=parsed_jd,
            evidence_allowlist=set(evidence_allowlist),
        )
        return state.model_copy(
            update={
                "response": json.dumps(result["content"]),
                "metadata": {
                    "input_tokens": result["input_tokens"],
                    "output_tokens": result["output_tokens"],
                    "model": result["model"],
                },
            }
        )
