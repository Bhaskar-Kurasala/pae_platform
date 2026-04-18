"""Senior-engineer simulation agent (P2-04).

Given a student's code, returns a structured PR-style review. Distinct from
``code_review`` — this one is pair-programmer voice, not a grader: fewer
rubric mechanics, more "what would I say at the next PR sync?" framing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.base_agent import AgentState, BaseAgent
from app.agents.registry import register

log = structlog.get_logger()

_PROMPT = (Path(__file__).parent / "prompts" / "senior_engineer.md").read_text()

_VALID_VERDICTS = {"approve", "request_changes", "comment"}
_VALID_SEVERITIES = {"nit", "suggestion", "concern", "blocking"}


def _clean_text_blocks(raw: Any) -> str:
    """Concatenate text blocks from an Anthropic extended-thinking response."""
    if isinstance(raw, list):
        parts: list[str] = []
        for block in raw:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p)
    return str(raw)


def _extract_json(raw: str) -> dict[str, Any]:
    """Best-effort extraction of JSON from the LLM response.

    LLMs sometimes wrap JSON in ```json ... ``` fences even when told not to.
    Handle both cases, plus leading/trailing prose.
    """
    text = raw.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif text.startswith("```"):
        text = text.split("```", 1)[1].split("```", 1)[0].strip()
    else:
        # Some models add a sentence before the JSON. Locate the first {.
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    try:
        result = json.loads(text)
        return result if isinstance(result, dict) else {}
    except json.JSONDecodeError:
        return {}


def _sanitize_review(data: dict[str, Any]) -> dict[str, Any]:
    """Coerce the LLM's review dict into the documented shape."""
    verdict = data.get("verdict")
    if verdict not in _VALID_VERDICTS:
        verdict = "comment"

    headline = str(data.get("headline", "")).strip()[:240] or "Review complete."
    strengths_raw = data.get("strengths", [])
    strengths = [str(s).strip() for s in strengths_raw if str(s).strip()][:3] \
        if isinstance(strengths_raw, list) else []

    comments_out: list[dict[str, Any]] = []
    for c in data.get("comments", []) if isinstance(data.get("comments"), list) else []:
        if not isinstance(c, dict):
            continue
        line_raw = c.get("line", 1)
        try:
            line = max(1, int(line_raw))
        except (TypeError, ValueError):
            line = 1
        severity = c.get("severity", "suggestion")
        if severity not in _VALID_SEVERITIES:
            severity = "suggestion"
        message = str(c.get("message", "")).strip()
        if not message:
            continue
        suggested = c.get("suggested_change")
        comments_out.append(
            {
                "line": line,
                "severity": severity,
                "message": message[:500],
                "suggested_change": str(suggested) if suggested else None,
            }
        )

    next_step = str(data.get("next_step", "")).strip()[:400] or (
        "Keep going — there's nothing blocking you right now."
    )

    # Enforce verdict↔severity consistency: if any blocking, verdict must be
    # request_changes. If all nits/suggestions and verdict is request_changes,
    # downgrade to comment.
    has_blocking = any(c["severity"] == "blocking" for c in comments_out)
    if has_blocking:
        verdict = "request_changes"
    elif verdict == "request_changes" and not has_blocking:
        verdict = "comment"

    return {
        "verdict": verdict,
        "headline": headline,
        "strengths": strengths,
        "comments": comments_out,
        "next_step": next_step,
    }


@register
class SeniorEngineerAgent(BaseAgent):
    name = "senior_engineer"
    description = (
        "Simulates a senior AI-engineering teammate reviewing the student's code "
        "as a pull request. Returns structured JSON: verdict, line-level comments, "
        "next step."
    )
    trigger_conditions = [
        "senior review",
        "review this PR",
        "what would a senior say",
        "pair review",
    ]
    model = "claude-sonnet-4-6"

    def _build_llm(self, max_tokens: int = 1500) -> Any:
        from app.agents.llm_factory import build_llm
        return build_llm(max_tokens=max_tokens)

    async def execute(self, state: AgentState) -> AgentState:
        code = str(state.context.get("code") or state.task or "").strip()
        problem_context = str(state.context.get("problem_context") or "").strip()

        if not code:
            review = _sanitize_review(
                {
                    "verdict": "comment",
                    "headline": "No code to review.",
                    "strengths": [],
                    "comments": [],
                    "next_step": "Paste the code you want reviewed and try again.",
                }
            )
            return state.model_copy(
                update={"response": json.dumps(review), "context": {**state.context, "review": review}}
            )

        llm = self._build_llm()
        user_content = (
            "Code to review:\n\n```python\n" + code + "\n```\n\n"
            "Return JSON only — no prose, no markdown fence."
        )
        if problem_context:
            user_content = (
                f"Problem context (what the student is trying to do): {problem_context}\n\n"
                + user_content
            )

        messages: list[Any] = [
            SystemMessage(content=_PROMPT),
            HumanMessage(content=user_content),
        ]

        response = await llm.ainvoke(messages)
        raw_text = _clean_text_blocks(response.content)
        parsed = _extract_json(raw_text)
        if not parsed:
            log.warning("senior_engineer.parse_failed", raw_preview=raw_text[:200])
            parsed = {
                "verdict": "comment",
                "headline": "Review produced unparseable output.",
                "comments": [],
                "next_step": "Try again — the reviewer's response didn't parse cleanly.",
            }
        review = _sanitize_review(parsed)

        return state.model_copy(
            update={
                "response": json.dumps(review),
                "context": {**state.context, "review": review},
            }
        )

    async def evaluate(self, state: AgentState) -> AgentState:
        """Score: 1.0 if review has a valid verdict and at least one comment OR
        zero comments with verdict=approve. 0.5 on fallback/parse failure.
        """
        try:
            review = json.loads(state.response or "{}")
        except json.JSONDecodeError:
            return state.model_copy(update={"evaluation_score": 0.3})
        verdict = review.get("verdict")
        comments = review.get("comments", [])
        if verdict not in _VALID_VERDICTS:
            score = 0.3
        elif verdict == "approve" and not comments:
            score = 1.0
        elif comments:
            score = 1.0
        else:
            score = 0.6
        return state.model_copy(update={"evaluation_score": score})
