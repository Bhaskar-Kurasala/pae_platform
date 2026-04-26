"""Sub-agents for the readiness diagnostic + JD decoder.

Each class is a thin LLM wrapper:

  * loads its system prompt from ``app/agents/prompts/readiness_*.md``
  * builds messages, invokes the configured tier
  * extracts a single JSON object from the response
  * returns the parsed dict + token usage so the orchestrator can write
    one ``agent_invocation_log`` row per call

Sub-agents do not commit to the DB, do not enforce cost caps, and do
not retry on validation failure. The orchestrators
(``jd_decoder_service``, ``readiness_orchestrator``) drive those
behaviors so cost-cap and retry policy live in one place per agent.

Classes:
  * JDAnalyst             — JD decoder analysis (commit 4)
  * MatchScorer           — JD match score (commit 4)
  * DiagnosticInterviewer — conversational diagnostic (commit 6)
  * VerdictGenerator      — final headline + evidence (commit 7)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.llm_factory import Tier, build_llm, model_for
from app.services.career_service import (
    extract_json_object,
    normalize_llm_content,
)

log = structlog.get_logger()

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def _usage_from(response: Any) -> tuple[int, int]:
    usage = getattr(response, "usage_metadata", None) or {}
    if isinstance(usage, dict):
        return int(usage.get("input_tokens", 0)), int(
            usage.get("output_tokens", 0)
        )
    return 0, 0


@dataclass
class SubAgentResult:
    parsed: dict[str, Any]
    raw_text: str
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    succeeded: bool
    error: str | None = None


# ---------------------------------------------------------------------------
# JD Analyst
# ---------------------------------------------------------------------------


class JDAnalyst:
    """Adds template-filler / culture-signal / seniority interpretation
    on top of the structured ``parse_jd`` output.

    Uses the smart tier (Sonnet) — the analysis is the decoder's most
    differentiated output and benefits from the stronger reasoning.
    """

    name = "jd_analyst"
    tier: Tier = "smart"
    max_tokens = 1100

    def __init__(self) -> None:
        self.system_prompt = _load_prompt("readiness_jd_analyst")

    async def run(
        self,
        *,
        jd_text: str,
        parsed_jd: dict[str, Any],
    ) -> SubAgentResult:
        import json as _json

        user_prompt = (
            "JD TEXT:\n---\n"
            + jd_text.strip()
            + "\n---\n\nPARSED JD (from upstream parser, for reference only):\n"
            + _json.dumps(parsed_jd, indent=2)
        )

        started = time.monotonic()
        try:
            llm = build_llm(max_tokens=self.max_tokens, tier=self.tier)
            response = await llm.ainvoke(
                [
                    SystemMessage(content=self.system_prompt),
                    HumanMessage(content=user_prompt),
                ]
            )
        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.monotonic() - started) * 1000)
            log.warning("jd_analyst.llm_failed", error=str(exc))
            return SubAgentResult(
                parsed={},
                raw_text="",
                model=model_for(self.tier),
                tokens_in=0,
                tokens_out=0,
                latency_ms=latency_ms,
                succeeded=False,
                error=str(exc)[:512],
            )

        latency_ms = int((time.monotonic() - started) * 1000)
        raw_text = normalize_llm_content(response.content)
        parsed = extract_json_object(raw_text) or {}
        tokens_in, tokens_out = _usage_from(response)
        return SubAgentResult(
            parsed=parsed,
            raw_text=raw_text,
            model=model_for(self.tier),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            succeeded=bool(parsed),
        )


# ---------------------------------------------------------------------------
# Match Scorer
# ---------------------------------------------------------------------------


class MatchScorer:
    """Scores the snapshot's match against a decoded JD.

    Output is validated by ``readiness_evidence_validator.validate_claims``
    — the orchestrator handles the validate-and-retry loop.
    """

    name = "match_scorer"
    tier: Tier = "smart"
    max_tokens = 900

    def __init__(self) -> None:
        self.system_prompt = _load_prompt("readiness_match_scorer")

    async def run(
        self,
        *,
        snapshot_summary: dict[str, Any],
        evidence_allowlist: set[str],
        jd_analysis: dict[str, Any],
    ) -> SubAgentResult:
        import json as _json

        user_prompt = (
            "SNAPSHOT (the only facts you may cite):\n"
            + _json.dumps(snapshot_summary, indent=2)
            + "\n\nALLOWED EVIDENCE IDS (every chip's evidence_id MUST be one of these):\n"
            + _json.dumps(sorted(evidence_allowlist), indent=2)
            + "\n\nDECODED JD:\n"
            + _json.dumps(jd_analysis, indent=2)
            + "\n\nReturn the JSON described in the system prompt."
        )

        started = time.monotonic()
        try:
            llm = build_llm(max_tokens=self.max_tokens, tier=self.tier)
            response = await llm.ainvoke(
                [
                    SystemMessage(content=self.system_prompt),
                    HumanMessage(content=user_prompt),
                ]
            )
        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.monotonic() - started) * 1000)
            log.warning("match_scorer.llm_failed", error=str(exc))
            return SubAgentResult(
                parsed={},
                raw_text="",
                model=model_for(self.tier),
                tokens_in=0,
                tokens_out=0,
                latency_ms=latency_ms,
                succeeded=False,
                error=str(exc)[:512],
            )

        latency_ms = int((time.monotonic() - started) * 1000)
        raw_text = normalize_llm_content(response.content)
        parsed = extract_json_object(raw_text) or {}
        tokens_in, tokens_out = _usage_from(response)
        return SubAgentResult(
            parsed=parsed,
            raw_text=raw_text,
            model=model_for(self.tier),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            succeeded=bool(parsed),
        )


# ---------------------------------------------------------------------------
# Diagnostic Interviewer
# ---------------------------------------------------------------------------


class DiagnosticInterviewer:
    """The conversational layer of the readiness diagnostic.

    Fast tier (Haiku) — turns must feel responsive (<1.5s target). One
    JSON object per turn with the agent's reply and three control
    signals (``ready_for_verdict``, ``invoke_jd_decoder``,
    ``jd_text_excerpt``). The orchestrator drives turn count, JD
    routing, and finalization.
    """

    name = "diagnostic_interviewer"
    tier: Tier = "fast"
    max_tokens = 400

    def __init__(self) -> None:
        self.system_prompt = _load_prompt("readiness_interviewer")

    async def run(
        self,
        *,
        snapshot_summary: dict[str, Any],
        prior_session_hint: str | None,
        transcript: list[dict[str, str]],
        student_message: str,
        turn_number: int,
    ) -> SubAgentResult:
        import json as _json

        # Compose a compact turn context the prompt's "Inputs" section
        # describes. Transcript turns are included as
        # role/content/turn_index dicts.
        context = {
            "turn_number": turn_number,
            "snapshot": snapshot_summary,
            "prior_session_hint": prior_session_hint or "",
            "transcript": transcript,
            "student_message": student_message,
        }
        user_prompt = (
            "TURN CONTEXT:\n"
            + _json.dumps(context, indent=2)
            + "\n\nReturn the JSON described in the system prompt — "
            "one object, no markdown fences, no preamble."
        )

        started = time.monotonic()
        try:
            llm = build_llm(max_tokens=self.max_tokens, tier=self.tier)
            response = await llm.ainvoke(
                [
                    SystemMessage(content=self.system_prompt),
                    HumanMessage(content=user_prompt),
                ]
            )
        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.monotonic() - started) * 1000)
            log.warning(
                "diagnostic_interviewer.llm_failed", error=str(exc)
            )
            return SubAgentResult(
                parsed={},
                raw_text="",
                model=model_for(self.tier),
                tokens_in=0,
                tokens_out=0,
                latency_ms=latency_ms,
                succeeded=False,
                error=str(exc)[:512],
            )

        latency_ms = int((time.monotonic() - started) * 1000)
        raw_text = normalize_llm_content(response.content)
        parsed = extract_json_object(raw_text) or {}
        tokens_in, tokens_out = _usage_from(response)
        return SubAgentResult(
            parsed=parsed,
            raw_text=raw_text,
            model=model_for(self.tier),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            succeeded=bool(parsed),
        )


# ---------------------------------------------------------------------------
# Verdict Generator
# ---------------------------------------------------------------------------


class VerdictGenerator:
    """Final synthesis: transcript + snapshot → headline / evidence /
    next-action.

    Smart tier (Sonnet) — runs once per session at finalize time. Output
    is validated by ``readiness_evidence_validator.validate_claims``;
    the orchestrator drives the validate-and-retry loop.
    """

    name = "verdict_generator"
    tier: Tier = "smart"
    max_tokens = 900

    def __init__(self) -> None:
        self.system_prompt = _load_prompt("readiness_verdict")

    async def run(
        self,
        *,
        snapshot_summary: dict[str, Any],
        evidence_allowlist: set[str],
        transcript: list[dict[str, str]],
        prior_verdict_summaries: list[dict[str, Any]],
        jd_match_score: dict[str, Any] | None,
    ) -> SubAgentResult:
        import json as _json

        user_prompt = (
            "SNAPSHOT (the only facts you may cite):\n"
            + _json.dumps(snapshot_summary, indent=2)
            + "\n\nALLOWED EVIDENCE IDS (every chip's evidence_id MUST be one of these):\n"
            + _json.dumps(sorted(evidence_allowlist), indent=2)
            + "\n\nCONVERSATION TRANSCRIPT (interviewer + student):\n"
            + _json.dumps(transcript, indent=2)
            + "\n\nPRIOR VERDICTS (oldest first; may be empty):\n"
            + _json.dumps(prior_verdict_summaries, indent=2)
            + "\n\nJD MATCH SCORE (may be null):\n"
            + _json.dumps(jd_match_score, indent=2)
            + "\n\nReturn the JSON described in the system prompt — "
            "one object, no markdown fences, no preamble."
        )

        started = time.monotonic()
        try:
            llm = build_llm(max_tokens=self.max_tokens, tier=self.tier)
            response = await llm.ainvoke(
                [
                    SystemMessage(content=self.system_prompt),
                    HumanMessage(content=user_prompt),
                ]
            )
        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.monotonic() - started) * 1000)
            log.warning("verdict_generator.llm_failed", error=str(exc))
            return SubAgentResult(
                parsed={},
                raw_text="",
                model=model_for(self.tier),
                tokens_in=0,
                tokens_out=0,
                latency_ms=latency_ms,
                succeeded=False,
                error=str(exc)[:512],
            )

        latency_ms = int((time.monotonic() - started) * 1000)
        raw_text = normalize_llm_content(response.content)
        parsed = extract_json_object(raw_text) or {}
        tokens_in, tokens_out = _usage_from(response)
        return SubAgentResult(
            parsed=parsed,
            raw_text=raw_text,
            model=model_for(self.tier),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            succeeded=bool(parsed),
        )


__all__ = [
    "SubAgentResult",
    "JDAnalyst",
    "MatchScorer",
    "DiagnosticInterviewer",
    "VerdictGenerator",
]
