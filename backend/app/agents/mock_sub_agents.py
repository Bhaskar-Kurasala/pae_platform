"""Mock interview v3 sub-agents.

Four cooperating sub-agents — each has its own system prompt and model tier:

  - MockQuestionSelector  → Sonnet — picks next question with adaptation + memory
  - MockInterviewer       → Haiku  — live conversation; reacts/probes/moves on
  - MockScorer            → Sonnet — per-answer rubric eval with confidence
  - MockAnalyst           → Sonnet — post-session synthesis

Each agent returns a (parsed_json, llm_response) tuple via its `.invoke()`
method so the orchestrator can record token usage + cost. None of the four
register with the MOA chat dispatcher — they're orchestrator-only.
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

_PROMPTS_DIR = Path(__file__).parent / "prompts"

_QUESTION_SELECTOR_PROMPT = (_PROMPTS_DIR / "mock_question_selector.md").read_text()
_INTERVIEWER_PROMPT = (_PROMPTS_DIR / "mock_interviewer.md").read_text()
_SCORER_PROMPT = (_PROMPTS_DIR / "mock_scorer.md").read_text()
_ANALYST_PROMPT = (_PROMPTS_DIR / "mock_analyst.md").read_text()


def _usage_from(response: Any) -> tuple[int, int]:
    """Extract (input_tokens, output_tokens) from a LangChain response."""
    usage = getattr(response, "usage_metadata", None) or {}
    if isinstance(usage, dict) and (usage.get("input_tokens") or usage.get("output_tokens")):
        return int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
    meta = getattr(response, "response_metadata", {}) or {}
    raw = meta.get("usage", {}) if isinstance(meta, dict) else {}
    return int(raw.get("input_tokens", 0)), int(raw.get("output_tokens", 0))


# ---------------------------------------------------------------------------
# QuestionSelector
# ---------------------------------------------------------------------------


class MockQuestionSelector:
    sub_agent_name = "question_selector"
    tier = "smart"

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def invoke(
        self,
        *,
        mode: str,
        target_role: str,
        level: str,
        jd_text: str | None,
        evidence: dict[str, Any],
        weakness_ledger: list[dict[str, Any]],
        rolling_overall: float | None,
        prior_questions: list[str],
        is_warmup: bool,
    ) -> tuple[dict[str, Any], Any]:
        """Pick the next question. Returns (parsed_json, raw_response)."""
        user_payload = {
            "mode": mode,
            "target_role": target_role,
            "level": level,
            "jd_text": jd_text,
            "evidence": evidence,
            "weakness_ledger": weakness_ledger,
            "rolling_overall": rolling_overall,
            "prior_questions": prior_questions,
            "is_warmup": is_warmup,
        }
        llm = build_llm(max_tokens=600, tier=self.tier)
        response = await llm.ainvoke(
            [
                SystemMessage(content=_QUESTION_SELECTOR_PROMPT),
                HumanMessage(content=json.dumps(user_payload, indent=2)),
            ]
        )
        text = normalize_llm_content(response.content)
        parsed = extract_json_object(text)
        if not parsed:
            log.warning("mock.selector.parse_failed", raw=text[:300])
            parsed = _selector_fallback(mode=mode, is_warmup=is_warmup)
        return parsed, response


# ---------------------------------------------------------------------------
# Interviewer
# ---------------------------------------------------------------------------


class MockInterviewer:
    sub_agent_name = "interviewer"
    tier = "fast"

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=0.5, max=4),
        reraise=True,
    )
    async def invoke(
        self,
        *,
        mode: str,
        voice_enabled: bool,
        question: str,
        rubric_hint: str,
        candidate_answer: str,
        transcript: list[dict[str, str]],
        probe_count_on_question: int,
    ) -> tuple[dict[str, Any], Any]:
        """React to the candidate's answer in real time."""
        user_payload = {
            "mode": mode,
            "voice_enabled": voice_enabled,
            "current_question": question,
            "rubric_hint": rubric_hint,
            "candidate_answer": candidate_answer,
            "transcript": transcript[-12:],  # last 6 turn pairs
            "probe_count_on_question": probe_count_on_question,
        }
        llm = build_llm(max_tokens=300, tier=self.tier)
        response = await llm.ainvoke(
            [
                SystemMessage(content=_INTERVIEWER_PROMPT),
                HumanMessage(content=json.dumps(user_payload, indent=2)),
            ]
        )
        text = normalize_llm_content(response.content)
        parsed = extract_json_object(text)
        if not parsed:
            log.warning("mock.interviewer.parse_failed", raw=text[:300])
            parsed = {
                "reply": "Walk me through that — I want to make sure I follow.",
                "next_action": "probe",
                "confidence": 0.4,
            }
        return parsed, response


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------


class MockScorer:
    sub_agent_name = "scorer"
    tier = "smart"

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def invoke(
        self,
        *,
        mode: str,
        level: str,
        question: str,
        answer: str,
        rubric: list[dict[str, str]],
        prior_session_context: str,
    ) -> tuple[dict[str, Any], Any]:
        """Score one answer. Returns (parsed_json, raw_response)."""
        user_payload = {
            "mode": mode,
            "level": level,
            "question": question,
            "answer": answer,
            "rubric": rubric,
            "prior_session_context": prior_session_context,
        }
        llm = build_llm(max_tokens=900, tier=self.tier)
        response = await llm.ainvoke(
            [
                SystemMessage(content=_SCORER_PROMPT),
                HumanMessage(content=json.dumps(user_payload, indent=2)),
            ]
        )
        text = normalize_llm_content(response.content)
        parsed = extract_json_object(text)
        if not parsed:
            log.warning("mock.scorer.parse_failed", raw=text[:300])
            parsed = _scorer_fallback(rubric=rubric)
        return parsed, response


# ---------------------------------------------------------------------------
# Analyst
# ---------------------------------------------------------------------------


class MockAnalyst:
    sub_agent_name = "analyst"
    tier = "smart"

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def invoke(
        self,
        *,
        session_meta: dict[str, Any],
        transcript: list[dict[str, Any]],
        evaluations: list[dict[str, Any]],
        patterns: dict[str, Any],
        prior_reports: list[dict[str, Any]],
        weakness_ledger: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], Any]:
        """Synthesize the post-mortem report."""
        user_payload = {
            "session_meta": session_meta,
            "transcript": transcript,
            "evaluations": evaluations,
            "patterns": patterns,
            "prior_reports": prior_reports[-3:],
            "weakness_ledger": weakness_ledger,
        }
        llm = build_llm(max_tokens=1800, tier=self.tier)
        response = await llm.ainvoke(
            [
                SystemMessage(content=_ANALYST_PROMPT),
                HumanMessage(content=json.dumps(user_payload, indent=2, default=str)),
            ]
        )
        text = normalize_llm_content(response.content)
        parsed = extract_json_object(text)
        if not parsed:
            log.warning("mock.analyst.parse_failed", raw=text[:300])
            parsed = _analyst_fallback(evaluations=evaluations)
        return parsed, response


# ---------------------------------------------------------------------------
# Fallbacks — used only when LLM is unavailable / output unparseable
# ---------------------------------------------------------------------------


def _selector_fallback(*, mode: str, is_warmup: bool) -> dict[str, Any]:
    text = {
        "behavioral": "Walk me through your most recent project.",
        "technical_conceptual": "Pick a concept you've used recently and explain how you'd defend it in code review.",
        "live_coding": "Write a function that returns the first non-repeating character in a string.",
        "system_design": "[deferred] system_design mode is Phase 2.",
    }.get(mode, "Tell me about something you've built recently.")
    return {
        "question": {
            "text": text,
            "difficulty": 0.2 if is_warmup else 0.5,
            "source": "library",
            "mode": mode,
            "rubric_hint": "general clarity + structure",
            "references_weakness": None,
        },
        "confidence": 0.5,
        "needs_human_review": True,
        "selection_reasoning": "Fallback: LLM unavailable or output unparseable.",
    }


def _scorer_fallback(*, rubric: list[dict[str, str]]) -> dict[str, Any]:
    criteria = [
        {
            "name": item.get("name", f"criterion_{i}"),
            "score": 5,
            "rationale": "Fallback evaluation — model unavailable.",
        }
        for i, item in enumerate(rubric)
    ] or [{"name": "overall", "score": 5, "rationale": "Fallback."}]
    return {
        "criteria": criteria,
        "overall": 5.0,
        "would_pass": False,
        "confidence": 0.4,
        "needs_human_review": True,
        "feedback": "I'd recommend a human review on this one. The scoring model was unavailable.",
        "follow_up_concept": None,
        "weakness_signals": [],
    }


def _analyst_fallback(*, evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "headline": "Session captured — the analysis model was unavailable for synthesis.",
        "verdict": "needs_human_review",
        "rubric_summary": {},
        "strengths": [],
        "weaknesses": [],
        "next_action": {
            "label": "Review your transcript",
            "detail": "The model was unable to produce a synthesis. Re-run the report from the session detail page.",
            "target_url": None,
        },
        "patterns_commentary": "",
        "analyst_confidence": 0.3,
        "needs_human_review": True,
        "weakness_ledger_updates": [],
        "_evaluations_count": len(evaluations),
    }
