"""LLM-based JD parser for tailored resume generation.

Returns a richer structure than the legacy regex-based ``extract_jd_skills``
in career_service. Used only by the tailoring path; existing fit-score and
JD-library flows continue to use the keyword extractor.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from tenacity import retry, stop_after_attempt, wait_exponential

from app.agents.llm_factory import build_llm, model_for
from app.services.career_service import extract_json_object, normalize_llm_content

log = structlog.get_logger()

_SYSTEM_PROMPT = (
    "You are a precise job-description parser. Read the provided JD and return a "
    "single JSON object describing it — no markdown fences, no preamble, no thinking text. "
    "Be conservative: if a field is genuinely unclear from the JD, leave the string empty "
    "or the list empty rather than inventing a value."
)

_USER_TEMPLATE = """Parse this job description into structured fields.

JOB DESCRIPTION:
---
{jd_text}
---

Return ONLY this JSON shape:
{{
  "role": "<canonical job title, e.g. 'Junior Python Developer'>",
  "company": "<company name if stated, else empty string>",
  "seniority": "<one of: intern | junior | mid | senior | staff | unspecified>",
  "company_stage": "<one of: startup | scaleup | enterprise | unspecified>",
  "must_haves": ["<3-8 hard requirements lifted from the JD>"],
  "nice_to_haves": ["<0-6 soft / preferred requirements>"],
  "key_responsibilities": ["<3-6 short responsibility phrases>"],
  "tone_signals": ["<3-5 phrases capturing the JD's voice — formal, scrappy, mission-driven, etc.>"]
}}
"""


@dataclass
class ParsedJd:
    role: str = ""
    company: str = ""
    seniority: str = "unspecified"
    company_stage: str = "unspecified"
    must_haves: list[str] = field(default_factory=list)
    nice_to_haves: list[str] = field(default_factory=list)
    key_responsibilities: list[str] = field(default_factory=list)
    tone_signals: list[str] = field(default_factory=list)
    # Token usage carried back to the orchestrator for cost accounting.
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # token/model fields are runtime metadata — strip them from the JSON
        # we persist on the TailoredResume row.
        d.pop("input_tokens", None)
        d.pop("output_tokens", None)
        d.pop("model", None)
        return d


def _coerce_str_list(raw: Any, *, max_len: int) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        if len(out) >= max_len:
            break
    return out


def _coerce_enum(raw: Any, allowed: tuple[str, ...]) -> str:
    if isinstance(raw, str) and raw.strip().lower() in allowed:
        return raw.strip().lower()
    return "unspecified"


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
async def _invoke_llm(jd_text: str) -> tuple[str, Any]:
    llm = build_llm(max_tokens=900, tier="fast")
    response = await llm.ainvoke([
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=_USER_TEMPLATE.format(jd_text=jd_text)),
    ])
    return normalize_llm_content(response.content), response


async def parse_jd(jd_text: str) -> ParsedJd:
    """Parse *jd_text* into a structured :class:`ParsedJd`.

    Falls back to an empty parse on any error — never raises. The orchestrator
    decides whether to proceed with a degraded parse or surface an error.
    """
    if not jd_text.strip():
        return ParsedJd()

    try:
        raw_text, response = await _invoke_llm(jd_text)
    except Exception as exc:  # network / rate-limit / etc.
        log.warning("jd_parser.llm_failed", error=str(exc))
        return ParsedJd()

    parsed = extract_json_object(raw_text)
    if not parsed:
        log.warning("jd_parser.json_extraction_failed", raw_len=len(raw_text))
        return ParsedJd()

    usage = getattr(response, "usage_metadata", None) or {}
    input_tokens = int(usage.get("input_tokens", 0)) if isinstance(usage, dict) else 0
    output_tokens = int(usage.get("output_tokens", 0)) if isinstance(usage, dict) else 0

    return ParsedJd(
        role=str(parsed.get("role") or "").strip(),
        company=str(parsed.get("company") or "").strip(),
        seniority=_coerce_enum(
            parsed.get("seniority"),
            ("intern", "junior", "mid", "senior", "staff", "unspecified"),
        ),
        company_stage=_coerce_enum(
            parsed.get("company_stage"),
            ("startup", "scaleup", "enterprise", "unspecified"),
        ),
        must_haves=_coerce_str_list(parsed.get("must_haves"), max_len=8),
        nice_to_haves=_coerce_str_list(parsed.get("nice_to_haves"), max_len=6),
        key_responsibilities=_coerce_str_list(parsed.get("key_responsibilities"), max_len=6),
        tone_signals=_coerce_str_list(parsed.get("tone_signals"), max_len=5),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model_for("fast"),
    )
