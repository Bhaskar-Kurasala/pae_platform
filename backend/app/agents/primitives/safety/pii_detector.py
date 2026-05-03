"""D9 / Pass 3g §B.3 — PII detection via Microsoft Presidio.

Wraps Presidio's AnalyzerEngine with AICareerOS-specific recognizers:
  • API key formats (Anthropic, GitHub, Razorpay)
  • Indian-context PII (Aadhaar, PAN — primary student demographic)

Detection runs on input AND output. The input-side semantics are
generous (a student's first name in their message is fine, log-only);
the output-side is strict (the agent producing a previously-unseen
phone number is a possible hallucinated leak).

Loaded once at process boot. Memory cost: ~750MB per Python process
(see fly.toml VM block + Dockerfile CMD comments for the deployment
implications). One spaCy en_core_web_lg model load drives most of
that — Presidio relies on spaCy NER for PERSON/LOCATION/ORG.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.schemas.safety import SafetyFinding, SafetySeverity


# AICareerOS-specific high-precision recognizers. These augment the
# default Presidio recognizer set; Presidio handles the generic ones
# (CREDIT_CARD, EMAIL_ADDRESS, PHONE_NUMBER, IP_ADDRESS, etc.).
_AICAREEROS_PATTERNS: Final[list[dict[str, str | float]]] = [
    {
        "name": "anthropic_api_key",
        "regex": r"sk-ant-[A-Za-z0-9_-]{20,}",
        "score": 0.95,
    },
    {
        "name": "github_token",
        "regex": r"ghp_[A-Za-z0-9]{30,}",
        "score": 0.95,
    },
    {
        "name": "razorpay_key",
        "regex": r"rzp_(test|live)_[A-Za-z0-9]{14,}",
        "score": 0.95,
    },
    # Aadhaar: 12 digits in 4-4-4 grouping. Score is lower (0.85)
    # because the regex is a permissive pattern — many 12-digit
    # numbers are not Aadhaars. Presidio's score gates downstream
    # decisions; high false-positive rate is acceptable when the
    # action is "redact" rather than "block".
    {
        "name": "aadhaar_number",
        "regex": r"\b\d{4}\s?\d{4}\s?\d{4}\b",
        "score": 0.85,
    },
    # PAN: 5 letters + 4 digits + 1 letter. Tighter pattern, but
    # still scored 0.85 because random 10-char strings can match.
    {
        "name": "pan_number",
        "regex": r"\b[A-Z]{5}\d{4}[A-Z]\b",
        "score": 0.85,
    },
]


# Severity per Presidio entity type. Pass 3g §B.3.2.
#
# Critical: secrets that, if leaked, are immediately exploitable.
# High: sensitive personal data (financial, government).
# Medium: identifying contact info (often legitimately shared).
# Low: names / locations (often the student's own).
# Info: URLs (log-only).
_PII_SEVERITY_MAP: Final[dict[str, SafetySeverity]] = {
    # AICareerOS custom recognizers — all critical (secrets/IDs)
    "AICAREEROS_SECRET": "critical",  # umbrella entity for the custom recognizer group
    "ANTHROPIC_API_KEY": "critical",
    "GITHUB_TOKEN": "critical",
    "RAZORPAY_KEY": "critical",
    "AADHAAR_NUMBER": "high",
    "PAN_NUMBER": "high",

    # Presidio built-ins
    "CREDIT_CARD": "high",
    "US_SSN": "high",
    "IBAN_CODE": "high",
    "CRYPTO": "high",

    "EMAIL_ADDRESS": "medium",
    "PHONE_NUMBER": "medium",
    "IP_ADDRESS": "medium",

    "PERSON": "low",
    "LOCATION": "low",
    "NRP": "low",  # nationality / religious / political
    "ORGANIZATION": "low",
    "DATE_TIME": "low",

    "URL": "info",
}


@dataclass(frozen=True)
class PiiHit:
    """One PII detection — kept distinct from SafetyFinding so the
    detector can return its native shape and the caller decides
    whether to wrap it as a finding (e.g., output-diff logic in
    output_scanners.py needs to compare hits across input vs output
    before deciding which become findings)."""

    entity_type: str  # Presidio's entity name (e.g. "EMAIL_ADDRESS")
    text: str  # the matched substring
    start: int
    end: int
    score: float


class PiiDetector:
    """Presidio-backed PII detector.

    Loaded once per process — the Presidio AnalyzerEngine constructor
    pulls spaCy en_core_web_lg into memory (~750 MB). Re-creating
    this object per scan would melt the worker, so the safety package
    holds a module-level singleton (see __init__.py).

    Lazy import of presidio packages so that this module is importable
    on systems where Presidio isn't installed (e.g. cheap unit tests
    that mock the detector). The actual import happens in `__init__`.
    """

    def __init__(
        self,
        *,
        custom_patterns: list[dict[str, str | float]] | None = None,
    ) -> None:
        # Lazy import: keeps `from app.agents.primitives.safety
        # import SafetyVerdict` cheap in environments without Presidio.
        from presidio_analyzer import (  # type: ignore[import-not-found]
            AnalyzerEngine,
            Pattern,
            PatternRecognizer,
        )

        self._analyzer = AnalyzerEngine()

        # Register AICareerOS-specific patterns under one umbrella
        # entity. Presidio scores each pattern individually; all
        # custom patterns share the AICAREEROS_SECRET entity name so
        # the severity map only needs one entry for the group.
        patterns_in = custom_patterns or _AICAREEROS_PATTERNS
        custom = [
            Pattern(
                name=str(p["name"]),
                regex=str(p["regex"]),
                score=float(p["score"]),
            )
            for p in patterns_in
        ]
        recognizer = PatternRecognizer(
            supported_entity="AICAREEROS_SECRET",
            patterns=custom,
        )
        self._analyzer.registry.add_recognizer(recognizer)

    def detect(self, text: str, language: str = "en") -> list[PiiHit]:
        """Scan `text`, return PII hits.

        Empty list = no hits. Score thresholding is left to Presidio
        defaults (0.0 returns everything; the recognizer's per-pattern
        score gates what makes it through).
        """
        if not text:
            return []
        results = self._analyzer.analyze(text=text, language=language)
        return [
            PiiHit(
                entity_type=r.entity_type,
                text=text[r.start:r.end],
                start=r.start,
                end=r.end,
                score=float(r.score),
            )
            for r in results
        ]

    @staticmethod
    def severity_for(entity_type: str) -> SafetySeverity:
        """Map a Presidio entity type to a SafetySeverity.

        Unknown entity types default to 'low' — same fail-safe
        principle as safety_policy: don't permit a new entity through
        without explicit acknowledgement, but don't block on first
        unknown either.
        """
        return _PII_SEVERITY_MAP.get(entity_type, "low")

    def to_finding(self, hit: PiiHit) -> SafetyFinding:
        """Wrap a PiiHit as a SafetyFinding for downstream aggregation.

        Evidence is the original matched text — callers that need
        redacted evidence (e.g. for safety_incidents.evidence_redacted
        per Pass 3g §E.1) must redact it themselves. We don't redact
        here because the input-side semantics sometimes want the
        original text preserved (a student's own name).
        """
        return SafetyFinding(
            category="pii_leak",
            severity=self.severity_for(hit.entity_type),
            description=f"Detected PII entity {hit.entity_type}",
            evidence=hit.text,
            detector=f"presidio:{hit.entity_type.lower()}",
            confidence=hit.score,
        )

    @staticmethod
    def redact_match(hit: PiiHit, full_text: str) -> str:
        """Replace one hit with a redaction marker; return modified text.

        Used when SafetyVerdict.decision == 'redact'. The marker
        format matches what's stored in safety_incidents.evidence_
        redacted: '[<ENTITY_TYPE>: <first 4 chars>***]' so we keep
        the *fact* of detection without storing the full payload.
        """
        prefix = hit.text[: min(4, len(hit.text))]
        marker = f"[{hit.entity_type}: {prefix}***]"
        return full_text[: hit.start] + marker + full_text[hit.end:]
