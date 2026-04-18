"""Portfolio autopsy service (P2-12).

A project retro, the way a senior engineer would run it: go through the thing
you just built, name what you'd do differently, score it against the axes that
actually matter in production.

Design goals:
- Not a grade. An autopsy. The student finished the project; the question is
  what they now know that they didn't when they started.
- Scored across four axes that mirror how real engineers review real shipped
  work: architecture, failure-handling, observability, and scope discipline.
- Explicit "what I would do differently" list — the single artifact that
  separates "I built a thing" from "I built a thing and learned something."
- Deterministic JSON schema so the frontend can render structured feedback and
  the row can be persisted as a portfolio receipt.

Pure `parse_autopsy` is unit-testable without hitting the LLM.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.llm_factory import build_llm

log = structlog.get_logger()


_AXES = ("architecture", "failure_handling", "observability", "scope_discipline")


@dataclass(frozen=True)
class AutopsyAxis:
    score: int              # 1-5
    assessment: str         # one sentence, cited to the project


@dataclass(frozen=True)
class AutopsyFinding:
    issue: str              # what's wrong / what's missing
    why_it_matters: str     # production consequence, not abstract critique
    what_to_do_differently: str  # the concrete change next time


@dataclass(frozen=True)
class PortfolioAutopsy:
    headline: str                             # one-sentence verdict
    overall_score: int                        # 0-100, derived from axes
    architecture: AutopsyAxis
    failure_handling: AutopsyAxis
    observability: AutopsyAxis
    scope_discipline: AutopsyAxis
    what_worked: list[str]                    # 1-3 things to repeat
    what_to_do_differently: list[AutopsyFinding]  # 2-5 concrete next-time changes
    production_gaps: list[str]                # blockers to actually shipping this
    next_project_seed: str                    # one-sentence "try this next"

    def to_dict(self) -> dict:
        return {
            "headline": self.headline,
            "overall_score": self.overall_score,
            "architecture": asdict(self.architecture),
            "failure_handling": asdict(self.failure_handling),
            "observability": asdict(self.observability),
            "scope_discipline": asdict(self.scope_discipline),
            "what_worked": list(self.what_worked),
            "what_to_do_differently": [asdict(f) for f in self.what_to_do_differently],
            "production_gaps": list(self.production_gaps),
            "next_project_seed": self.next_project_seed,
        }


_SYSTEM = """\
You are a senior engineer running a project autopsy. The student has shipped
something — your job is to tell them, honestly, what they'd do differently if
they built it again now. Not a grade. An autopsy.

Rules:
- Be specific. "Improve error handling" is useless. "The webhook handler
  re-raises on JSON decode errors, which will cause Stripe to retry forever —
  swallow + log + 200" is useful.
- Score 1-5 on four axes. 3 is "would-pass-review with notes". 5 is "I would
  deploy this on Monday." 1 is "this will page someone at 3am."
- Every axis assessment must cite something specific in the code or design.
- "what_worked" — 1 to 3 things. If nothing worked, say so; don't invent praise.
- "what_to_do_differently" — 2 to 5 findings. Each needs (issue, why_it_matters,
  what_to_do_differently). The "why" MUST be a production consequence, not a
  style nit.
- "production_gaps" — blockers to actually running this in prod (missing auth,
  no retries on external calls, unbounded memory, etc.). Empty list if none.
- "next_project_seed" — one sentence naming the specific next project that
  would stretch them. Pick something that builds on this, not a random topic.
- No emoji. No "great job!". No hedging. The student paid for honesty.
- Keep each `assessment` / `why_it_matters` / `what_to_do_differently` to ONE
  sentence. This is a scannable retro, not a manifesto.

Return ONLY JSON with these keys:
{
  "headline": str,
  "overall_score": int,
  "architecture":       {"score": int, "assessment": str},
  "failure_handling":   {"score": int, "assessment": str},
  "observability":      {"score": int, "assessment": str},
  "scope_discipline":   {"score": int, "assessment": str},
  "what_worked": [str, ...],
  "what_to_do_differently": [
    {"issue": str, "why_it_matters": str, "what_to_do_differently": str}, ...
  ],
  "production_gaps": [str, ...],
  "next_project_seed": str
}
"""


def _strip_code_fence(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
    return raw.strip()


def _extract_json_object(raw: str) -> str:
    """Pull the first balanced {...} block out of a string.

    LLMs with extended thinking sometimes prepend a preamble before the JSON
    payload. We strip code fences first, then — if the result still doesn't
    parse — scan for the first top-level object.
    """
    cleaned = _strip_code_fence(raw)
    if cleaned.startswith("{"):
        return cleaned
    depth = 0
    start = -1
    for i, ch in enumerate(cleaned):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start != -1:
                return cleaned[start : i + 1]
    return cleaned


def _response_to_text(content: Any) -> str:
    """Flatten a LangChain response.content into plain text.

    `ChatAnthropic` with extended thinking returns a list of content blocks
    (some dicts with `type: "thinking"`, others with `type: "text"`). Older /
    non-thinking calls return a plain string. This normaliser handles both.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                btype = block.get("type")
                if btype in ("text", "output_text"):
                    text_val = block.get("text")
                    if isinstance(text_val, str):
                        parts.append(text_val)
                # Skip "thinking" blocks — they're the scratchpad, not the answer.
        return "\n".join(parts)
    return str(content)


def _axis(data: dict[str, Any], key: str) -> AutopsyAxis:
    block = data.get(key)
    if not isinstance(block, dict):
        raise ValueError(f"missing axis: {key}")
    score = block.get("score")
    if not isinstance(score, int) or not (1 <= score <= 5):
        raise ValueError(f"{key}.score must be an int 1-5")
    assessment = block.get("assessment")
    if not isinstance(assessment, str) or not assessment.strip():
        raise ValueError(f"{key}.assessment must be a non-empty string")
    return AutopsyAxis(score=score, assessment=assessment)


def _findings(raw: Any) -> list[AutopsyFinding]:
    if not isinstance(raw, list):
        raise ValueError("what_to_do_differently must be a list")
    if not (2 <= len(raw) <= 5):
        raise ValueError("what_to_do_differently must have 2-5 entries")
    out: list[AutopsyFinding] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"what_to_do_differently[{idx}] must be an object")
        issue = item.get("issue")
        why = item.get("why_it_matters")
        do = item.get("what_to_do_differently")
        for fname, fval in (("issue", issue), ("why_it_matters", why), ("what_to_do_differently", do)):
            if not isinstance(fval, str) or not fval.strip():
                raise ValueError(f"what_to_do_differently[{idx}].{fname} must be a non-empty string")
        out.append(
            AutopsyFinding(
                issue=issue,  # type: ignore[arg-type]
                why_it_matters=why,  # type: ignore[arg-type]
                what_to_do_differently=do,  # type: ignore[arg-type]
            )
        )
    return out


def _string_list(raw: Any, name: str, *, min_len: int = 0, max_len: int = 10) -> list[str]:
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise ValueError(f"{name} must be a list of strings")
    if not (min_len <= len(raw) <= max_len):
        raise ValueError(f"{name} must have {min_len}-{max_len} entries")
    return list(raw)


def parse_autopsy(raw: str) -> PortfolioAutopsy:
    """Parse an LLM JSON response into a validated PortfolioAutopsy.

    Pure function — unit-testable without hitting the LLM.
    Raises ValueError on malformed input.
    """
    cleaned = _extract_json_object(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("autopsy payload must be an object")

    headline = data.get("headline")
    if not isinstance(headline, str) or not headline.strip():
        raise ValueError("headline must be a non-empty string")

    overall = data.get("overall_score")
    if not isinstance(overall, int) or not (0 <= overall <= 100):
        raise ValueError("overall_score must be an int 0-100")

    next_seed = data.get("next_project_seed")
    if not isinstance(next_seed, str) or not next_seed.strip():
        raise ValueError("next_project_seed must be a non-empty string")

    return PortfolioAutopsy(
        headline=headline,
        overall_score=overall,
        architecture=_axis(data, "architecture"),
        failure_handling=_axis(data, "failure_handling"),
        observability=_axis(data, "observability"),
        scope_discipline=_axis(data, "scope_discipline"),
        what_worked=_string_list(data.get("what_worked", []), "what_worked", min_len=1, max_len=3),
        what_to_do_differently=_findings(data.get("what_to_do_differently")),
        production_gaps=_string_list(
            data.get("production_gaps", []), "production_gaps", min_len=0, max_len=8
        ),
        next_project_seed=next_seed,
    )


async def run_autopsy(
    *,
    project_title: str,
    project_description: str,
    code: str | None = None,
    what_went_well_self: str | None = None,
    what_was_hard_self: str | None = None,
) -> PortfolioAutopsy:
    """Ask Claude to run a production-grade autopsy on the student's project.

    `project_title` and `project_description` are required so the LLM knows the
    scope and goal. `code` is optional — if absent, feedback focuses on the
    design; if present, the reviewer cites specific lines.

    Self-report fields are optional anchors. Providing them sharpens the
    "what I would do differently" list — the student's blind spots surface
    by contrast with their self-assessment.
    """
    prompt_parts: list[str] = [
        f"Project title: {project_title}",
        f"Project description:\n{project_description}",
    ]
    if code:
        prompt_parts.append(f"Code:\n```\n{code}\n```")
    if what_went_well_self:
        prompt_parts.append(f"Student's self-report — what went well:\n{what_went_well_self}")
    if what_was_hard_self:
        prompt_parts.append(f"Student's self-report — what was hard:\n{what_was_hard_self}")

    human = "\n\n".join(prompt_parts)
    llm = build_llm(max_tokens=3000)
    messages: list[Any] = [SystemMessage(content=_SYSTEM), HumanMessage(content=human)]
    response = await llm.ainvoke(messages)
    raw = _response_to_text(response.content)
    try:
        return parse_autopsy(raw)
    except ValueError as exc:
        log.warning("portfolio_autopsy.parse_failed", error=str(exc), raw=raw[:500])
        raise
