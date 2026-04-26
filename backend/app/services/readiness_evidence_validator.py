"""Evidence validator for readiness verdicts and JD match scores.

Generalizes the resume agent's two-pass hallucination_validator into a
shape that works for any structured output whose claims carry
``evidence_id`` strings. The diagnostic and JD decoder both validate
their LLM outputs through this module.

Two passes — exactly as in hallucination_validator:

  Pass 1 (deterministic, free): every claim's ``evidence_id`` must be in
  the snapshot's evidence_allowlist. Catches the common failure where
  the LLM cites a signal the student doesn't actually have.

  Pass 2 (LLM, ~₹0.4): a Haiku verifier reads the snapshot summary + the
  generated claims and flags any prose claim that isn't grounded.
  Catches narrative hallucinations the deterministic pass misses
  (fabricated metrics, invented projects, etc.).

Output is a ``ValidationResult`` with the same surface as the resume
agent's so the orchestrators can treat them uniformly. Cost-cap callers
short-circuit the LLM pass via ``skip_llm_check``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.llm_factory import build_llm
from app.services.career_service import (
    extract_json_object,
    normalize_llm_content,
)

log = structlog.get_logger()

_VERIFIER_SYSTEM = (
    "You are a strict evidence fact-checker for a career-readiness agent. "
    "Compare a generated set of claims against the SNAPSHOT block — the "
    "only verified data the agent is allowed to cite. Flag any claim that "
    "is not traceable to SNAPSHOT. You will not flatter, hedge, or "
    "rationalize away missing evidence. Return ONLY a JSON object."
)

_VERIFIER_TEMPLATE = """SNAPSHOT (the only facts the agent may cite):
{snapshot_json}

GENERATED CLAIMS:
{claims_json}

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
    claims: list[dict[str, Any]],
    *,
    evidence_allowlist: set[str],
    label: str,
) -> list[str]:
    """Walk every claim and confirm ``evidence_id`` is in the allowlist."""
    failures: list[str] = []
    if not isinstance(claims, list):
        return [f"{label} field is not a list"]
    if not claims:
        # An empty claims list is allowed for thin-data outputs (e.g. a
        # match score where snapshot_too_thin is True). The caller is
        # responsible for refusing to render an empty-evidence verdict
        # in normal flows.
        return failures
    for i, claim in enumerate(claims):
        if not isinstance(claim, dict):
            failures.append(f"{label}[{i}] is not an object")
            continue
        evidence_id = str(claim.get("evidence_id") or "").strip().lower()
        if not evidence_id:
            failures.append(f"{label}[{i}] missing evidence_id")
            continue
        if evidence_id not in {e.lower() for e in evidence_allowlist}:
            failures.append(
                f"{label}[{i}] cites unknown evidence_id '{evidence_id}'"
            )
    return failures


async def _llm_check(
    *,
    claims: list[dict[str, Any]],
    snapshot_summary: dict[str, Any],
) -> list[str]:
    import json as _json

    try:
        llm = build_llm(max_tokens=400, tier="fast")
        response = await llm.ainvoke([
            SystemMessage(content=_VERIFIER_SYSTEM),
            HumanMessage(
                content=_VERIFIER_TEMPLATE.format(
                    snapshot_json=_json.dumps(snapshot_summary, indent=2),
                    claims_json=_json.dumps(claims, indent=2),
                )
            ),
        ])
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "readiness_evidence_validator.llm_failed", error=str(exc)
        )
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


async def validate_claims(
    claims: list[dict[str, Any]],
    *,
    evidence_allowlist: set[str],
    snapshot_summary: dict[str, Any],
    skip_llm_check: bool = False,
    label: str = "evidence",
) -> ValidationResult:
    """Run both passes and return a structured result.

    *skip_llm_check* short-circuits the second pass — used in tests and
    as a circuit breaker once the cost cap has been hit during a
    session.
    """
    deterministic = _deterministic_check(
        claims, evidence_allowlist=evidence_allowlist, label=label
    )
    llm_failures: list[str] = []
    if not skip_llm_check and not deterministic:
        # Only run the (paid) LLM pass if the cheap pass already cleared.
        llm_failures = await _llm_check(
            claims=claims, snapshot_summary=snapshot_summary
        )

    passed = not deterministic and not llm_failures
    return ValidationResult(
        passed=passed,
        violations=[*deterministic, *llm_failures],
        deterministic_failures=deterministic,
        llm_failures=llm_failures,
    )


__all__ = ["ValidationResult", "validate_claims"]
