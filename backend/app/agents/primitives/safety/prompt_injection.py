"""D9 / Pass 3g §B.2.1 — Layer 1 regex pattern bank for prompt injection.

Loads the versioned pattern bank JSON at boot, compiles each regex once,
applies them to incoming text. Cheap (<5ms per scan), deterministic,
catches the most common 60-70% of injection attempts per Pass 3g §B.2.1.

Bank format: see backend/app/agents/primitives/safety_patterns/
prompt_injection_v1.json. Pattern files are versioned by suffix; the
loader reads the highest version available so a new pattern set ships
as a new file (prompt_injection_v2.json) rather than a mutation of v1
that would silently change historical match behavior.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from app.schemas.safety import SafetyFinding, SafetySeverity


# Default location relative to this module — keeps the pattern bank
# co-located with code that uses it. Override via constructor for tests.
_DEFAULT_PATTERN_DIR: Final[Path] = (
    Path(__file__).resolve().parent.parent / "safety_patterns"
)
_DEFAULT_PATTERN_FILE: Final[str] = "prompt_injection_v1.json"


@dataclass(frozen=True)
class CompiledPattern:
    """One entry from the JSON bank, regex pre-compiled."""

    id: str
    regex: re.Pattern[str]
    severity: SafetySeverity
    rationale: str


def load_pattern_bank(
    path: Path | str | None = None,
) -> tuple[str, list[CompiledPattern]]:
    """Load and compile the pattern bank.

    Returns (version, patterns). Patterns are compiled once at load
    time; the caller holds them for the process lifetime.

    Raises FileNotFoundError if the bank is missing — the safety
    primitive treats that as a hard fail at boot rather than silently
    running without injection detection.
    """
    if path is None:
        path = _DEFAULT_PATTERN_DIR / _DEFAULT_PATTERN_FILE
    elif isinstance(path, str):
        path = Path(path)

    raw = json.loads(path.read_text(encoding="utf-8"))
    version: str = raw.get("version", "unknown")
    compiled: list[CompiledPattern] = []
    for entry in raw.get("patterns", []):
        compiled.append(
            CompiledPattern(
                id=entry["id"],
                # The JSON regexes already include (?i) inline; we
                # don't add re.IGNORECASE on top because that would
                # double-case the pattern and confuse debugging.
                regex=re.compile(entry["regex"]),
                severity=entry["severity"],
                rationale=entry["rationale"],
            )
        )
    return version, compiled


class PromptInjectionDetector:
    """Layer 1 regex-based prompt injection detector.

    Stateless detector: hold compiled patterns, scan text, return
    findings. No DB, no LLM, no I/O at scan time.

    Layer 2 (llm_classifier.py) is what the gate falls back to when
    Layer 1 is uncertain (no high-severity hit, or only low-severity
    hits at low confidence).
    """

    def __init__(
        self,
        *,
        bank_path: Path | str | None = None,
    ) -> None:
        version, patterns = load_pattern_bank(bank_path)
        self.version = version
        self.patterns = patterns

    def scan(self, text: str) -> list[SafetyFinding]:
        """Run every pattern against `text`. Return all matches.

        Returns an empty list if the text passes cleanly. Each match
        becomes one SafetyFinding — multiple matches on different
        patterns each contribute a finding, so the gate can see the
        full picture (e.g., a message with both 'ignore previous'
        AND 'developer mode' is more concerning than either alone).
        """
        findings: list[SafetyFinding] = []
        for pattern in self.patterns:
            match = pattern.regex.search(text)
            if match is None:
                continue
            findings.append(
                SafetyFinding(
                    category="prompt_injection",
                    severity=pattern.severity,
                    description=pattern.rationale,
                    # Truncate evidence: the matched span is the
                    # signal; the surrounding text isn't useful and
                    # might itself contain PII (we'd rather not store
                    # both kinds of sensitive content in one row).
                    evidence=match.group(0)[:200],
                    detector=f"regex_v1:{pattern.id}",
                    # Layer 1 confidence is high by definition (a
                    # regex either matched or didn't); the LLM
                    # classifier is what introduces graduated
                    # confidence in Layer 2.
                    confidence=1.0,
                )
            )
        return findings
