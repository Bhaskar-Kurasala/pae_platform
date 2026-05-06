"""Inner LLM-call helper for the tailored-resume pipeline.

Renamed from tailored_resume.py → tailored_resume_llm.py at D12 CP1
(α-1 naming resolution). At D12 CP4 cutover the legacy `BaseAgent`
inheritance + `@register` decorator + MOA-shaped `execute(state)` method
were removed: this module is no longer reachable through the legacy
MOA endpoint, only through `tailored_resume_service.generate_tailored_resume(...)`
which calls `TailoredResumeLLM.generate(...)` directly with structured inputs.

This file is NOT the chat-path agent. The chat-path agent is
`app.agents.tailored_resume_v2.TailoredResumeShimAgent` (AgenticBaseAgent),
which delegates to `tailored_resume_service.py`, which delegates to
this helper. The class is intentionally a plain async helper — no
agent base class, no registry, no MOA contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from tenacity import retry, stop_after_attempt, wait_exponential

from app.agents.llm_factory import build_llm, model_for
from app.services.career_service import extract_json_object, normalize_llm_content

log = structlog.get_logger()

_PROMPT = (Path(__file__).parent / "prompts" / "tailored_resume.md").read_text()


class TailoredResumeLLM:
    """LLM-call helper for the tailored-resume service pipeline.

    Generates a JD-tailored resume payload (JSON) from a verified profile.
    Direct-call only — no MOA registration, no AgenticBaseAgent contract.
    The `tailored_resume_service` module is the canonical caller.

    Renamed from `TailoredResumeAgent` at D12 CP4 cutover to remove the
    "Agent" suffix that misleadingly implied MOA-reachability.
    """

    name = "tailored_resume"
    model = "claude-sonnet-4-6"

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def _invoke(
        self,
        llm: Any,
        *,
        evidence: dict[str, Any],
        parsed_jd: dict[str, Any],
        evidence_allowlist: list[str],
        regenerate_feedback: list[str],
    ) -> tuple[str, Any]:
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
        """Direct entrypoint used by tailored_resume_service.

        Returns ``{"content": <parsed-json>, "input_tokens": int, "output_tokens": int, "model": str}``.
        Raises if the LLM call itself fails after retries.
        """
        # D12 CP3 Phase 4 (Bug 16 sibling): bumped 1800 → 8192. Same
        # rationale as career_coach. The tailored_resume pipeline has
        # multiple inner LLM calls (JD parse, evidence allowlist,
        # tailoring, cover letter, validation); each gets the headroom.
        llm = build_llm(max_tokens=8192, tier="smart")
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
        # Use the live model from response_metadata so MiniMax calls record
        # MiniMax pricing rather than Sonnet pricing (D12 CP3 Part C).
        # Convention matches agentic_base.py: prefer "model", fall back to
        # "model_name", then to the static model_for("smart") sentinel.
        # Model resolved from response_metadata, not from configured llm.model.
        # Tracks the model that actually ran (per MiniMax's claim), not the model
        # we configured. Same in 99% of cases; differs only on auto-fallback or
        # version mismatch — and in those cases response_metadata is the more
        # honest signal.
        _resp_meta = getattr(response, "response_metadata", {}) or {}
        live_model: str = (
            (_resp_meta.get("model") or _resp_meta.get("model_name"))
            if isinstance(_resp_meta, dict)
            else None
        ) or model_for("smart")

        return {
            "content": parsed,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "model": live_model,
        }


# D12 CP4 cutover: the legacy `TailoredResumeAgent` name is kept as a
# module-level alias for one release cycle so any in-flight imports
# (e.g. from tests during the cutover commit) don't fail to resolve.
# Remove this alias in a follow-up cleanup pass once the codebase is
# fully on TailoredResumeLLM.
TailoredResumeAgent = TailoredResumeLLM


__all__ = [
    "TailoredResumeAgent",
    "TailoredResumeLLM",
]
