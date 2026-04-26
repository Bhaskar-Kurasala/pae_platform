"""Hallucination validator for tailored resume output.

Two-pass check:
  Pass 1 (deterministic, free): every bullet's `evidence_id` must be in the
  evidence allowlist. This catches the common failure where the LLM cites
  a skill the student doesn't actually have.

  Pass 2 (LLM, ~₹0.40): a Haiku verifier reads the EVIDENCE block + the
  generated content and flags any prose claim that's not traceable to
  the evidence. Catches narrative hallucinations the deterministic pass
  misses (fabricated employers, invented metrics, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.llm_factory import build_llm, model_for
from app.services.career_service import extract_json_object, normalize_llm_content

log = structlog.get_logger()

_VERIFIER_SYSTEM = (
    "You are a strict resume fact-checker. Compare a generated resume against "
    "the EVIDENCE block. Flag any claim — skill, employer, metric, project — "
    "that is not traceable to EVIDENCE. Return ONLY a JSON object."
)

_VERIFIER_TEMPLATE = """EVIDENCE (the only facts the resume is allowed to cite):
{evidence_json}

GENERATED RESUME:
{content_json}

Return ONLY this JSON:
{{
  "valid": <true | false>,
  "violations": ["<short description of each unsupported claim>"]
}}
"""


@dataclass
class ValidationResult:
    passed: bool
    violations: list[str] = field(default_factory=list)
    deterministic_failures: list[str] = field(default_factory=list)
    llm_failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "violations": self.violations,
            "deterministic_failures": self.deterministic_failures,
            "llm_failures": self.llm_failures,
        }


def _deterministic_check(
    content: dict[str, Any],
    *,
    evidence_allowlist: set[str],
) -> list[str]:
    """Walk every bullet and confirm `evidence_id` is in the allowlist."""
    failures: list[str] = []
    bullets = content.get("bullets", [])
    if not isinstance(bullets, list):
        return ["bullets field is not a list"]

    for i, b in enumerate(bullets):
        if not isinstance(b, dict):
            failures.append(f"bullet[{i}] is not an object")
            continue
        evidence_id = str(b.get("evidence_id") or "").strip().lower()
        if not evidence_id:
            failures.append(f"bullet[{i}] missing evidence_id")
            continue
        if evidence_id not in evidence_allowlist:
            failures.append(
                f"bullet[{i}] cites unknown evidence_id '{evidence_id}'"
            )
    return failures


async def _llm_check(
    *,
    content: dict[str, Any],
    evidence: dict[str, Any],
) -> list[str]:
    """Haiku-based prose-level fact check. Failures returned as strings."""
    import json as _json

    try:
        llm = build_llm(max_tokens=400, tier="fast")
        response = await llm.ainvoke([
            SystemMessage(content=_VERIFIER_SYSTEM),
            HumanMessage(
                content=_VERIFIER_TEMPLATE.format(
                    evidence_json=_json.dumps(evidence, indent=2),
                    content_json=_json.dumps(content, indent=2),
                )
            ),
        ])
    except Exception as exc:
        log.warning("hallucination_validator.llm_failed", error=str(exc))
        # If the verifier itself fails, do not fail the user — the
        # deterministic pass is still authoritative.
        return []

    parsed = extract_json_object(normalize_llm_content(response.content))
    if not parsed:
        return []

    if parsed.get("valid") is True:
        return []
    violations = parsed.get("violations") or []
    if not isinstance(violations, list):
        return []
    return [str(v) for v in violations if v]


async def validate(
    content: dict[str, Any],
    *,
    evidence: dict[str, Any],
    evidence_allowlist: set[str],
    skip_llm_check: bool = False,
) -> ValidationResult:
    """Run both passes and return a structured result.

    *skip_llm_check* short-circuits the second pass — used in tests and as
    a circuit breaker if the cost cap has been hit.
    """
    deterministic = _deterministic_check(
        content, evidence_allowlist=evidence_allowlist
    )
    llm_failures: list[str] = []
    if not skip_llm_check and not deterministic:
        # Only run the (paid) LLM pass if the cheap pass already cleared.
        llm_failures = await _llm_check(content=content, evidence=evidence)

    passed = not deterministic and not llm_failures
    return ValidationResult(
        passed=passed,
        violations=[*deterministic, *llm_failures],
        deterministic_failures=deterministic,
        llm_failures=llm_failures,
    )


# Exposed for tests
__all__ = ["ValidationResult", "validate", "model_for"]
