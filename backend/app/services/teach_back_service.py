"""Teach-back evaluation service (P2-11).

Feynman technique in code: if you can't explain it plainly, you don't own it.
This service takes a concept + the student's plain-language explanation and
asks Claude to evaluate whether a beginner would actually understand — using
a structured rubric so the feedback is specific, not vibes.

No persistence here — the artifact is the *next* conversation the student has
with the material. Logging can be layered on later.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.llm_factory import build_llm

log = structlog.get_logger()


@dataclass(frozen=True)
class RubricScore:
    score: int               # 1-5
    evidence: str            # one specific sentence, cited to the explanation


@dataclass(frozen=True)
class TeachBackEvaluation:
    accuracy: RubricScore             # is what they said technically right?
    completeness: RubricScore         # did they leave out something load-bearing?
    beginner_clarity: RubricScore     # would someone new understand this?
    would_beginner_understand: bool
    missing_ideas: list[str]          # concepts they skipped
    best_sentence: str                # their strongest line (teaches them what "good" looks like)
    follow_up: str                    # one probing question for deeper ownership

    def to_dict(self) -> dict:
        return {
            "accuracy": asdict(self.accuracy),
            "completeness": asdict(self.completeness),
            "beginner_clarity": asdict(self.beginner_clarity),
            "would_beginner_understand": self.would_beginner_understand,
            "missing_ideas": list(self.missing_ideas),
            "best_sentence": self.best_sentence,
            "follow_up": self.follow_up,
        }


_SYSTEM = """\
You are a teach-back evaluator. A student has explained a concept in their own words;
your job is to judge whether that explanation would actually help a beginner understand.

Rules:
- Score 1-5 on each rubric axis. Be honest. Inflating scores wastes the student's time.
- Every rubric score MUST include evidence: one sentence that cites something the student
  wrote (or conspicuously omitted).
- "would_beginner_understand" is a yes/no gut check. A C+ explanation where a beginner
  would still be confused → false. Don't hedge.
- "best_sentence" must be quoted verbatim from their explanation. If nothing was good,
  return an empty string.
- "missing_ideas" is 1-3 concrete concepts they skipped that you'd expect in a correct
  explanation. Empty list if coverage was complete.
- "follow_up" is ONE question that probes deeper ownership — not a hint, not a quiz.

Return ONLY JSON with these keys:
{
  "accuracy": {"score": int, "evidence": str},
  "completeness": {"score": int, "evidence": str},
  "beginner_clarity": {"score": int, "evidence": str},
  "would_beginner_understand": bool,
  "missing_ideas": [str, ...],
  "best_sentence": str,
  "follow_up": str
}
"""


def _strip_code_fence(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
    return raw.strip()


def parse_evaluation(raw: str) -> TeachBackEvaluation:
    """Parse an LLM JSON response into a validated TeachBackEvaluation.

    Pure function — lives outside the async flow so it's unit-testable.
    Raises ValueError on malformed input.
    """
    cleaned = _strip_code_fence(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc

    def _score(key: str) -> RubricScore:
        block = data.get(key)
        if not isinstance(block, dict):
            raise ValueError(f"missing rubric key: {key}")
        score_raw = block.get("score")
        if not isinstance(score_raw, int) or not (1 <= score_raw <= 5):
            raise ValueError(f"{key}.score must be an int 1-5")
        evidence = block.get("evidence")
        if not isinstance(evidence, str):
            raise ValueError(f"{key}.evidence must be a string")
        return RubricScore(score=score_raw, evidence=evidence)

    missing_raw = data.get("missing_ideas", [])
    if not isinstance(missing_raw, list) or not all(isinstance(x, str) for x in missing_raw):
        raise ValueError("missing_ideas must be a list of strings")

    would = data.get("would_beginner_understand")
    if not isinstance(would, bool):
        raise ValueError("would_beginner_understand must be a bool")

    best = data.get("best_sentence", "")
    follow = data.get("follow_up", "")
    if not isinstance(best, str) or not isinstance(follow, str):
        raise ValueError("best_sentence / follow_up must be strings")

    return TeachBackEvaluation(
        accuracy=_score("accuracy"),
        completeness=_score("completeness"),
        beginner_clarity=_score("beginner_clarity"),
        would_beginner_understand=would,
        missing_ideas=list(missing_raw),
        best_sentence=best,
        follow_up=follow,
    )


async def evaluate_explanation(
    concept: str,
    explanation: str,
    reference_notes: str | None = None,
) -> TeachBackEvaluation:
    """Ask Claude to evaluate a student's plain-language explanation of a concept.

    `reference_notes` is optional source material the student was taught from;
    passing it anchors accuracy scoring.
    """
    prompt_parts = [
        f"Concept being taught back: {concept}",
    ]
    if reference_notes:
        prompt_parts.append(
            "Source material the student saw (for accuracy calibration):\n"
            f"{reference_notes}"
        )
    prompt_parts.append(f"Student's explanation:\n{explanation}")
    human = "\n\n".join(prompt_parts)

    llm = build_llm(max_tokens=800)
    messages: list[Any] = [SystemMessage(content=_SYSTEM), HumanMessage(content=human)]
    response = await llm.ainvoke(messages)
    raw = str(response.content)
    try:
        return parse_evaluation(raw)
    except ValueError as exc:
        log.warning("teach_back.parse_failed", error=str(exc), raw=raw[:400])
        raise
