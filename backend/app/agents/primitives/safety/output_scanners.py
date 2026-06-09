"""D9 / Pass 3g §C — output-side safety detectors.

Five output-side concerns:
  1. PII leakage (compared against input PII; new PII = possible leak)
  2. Harmful content (self-harm, malicious code patterns)
  3. Jailbreak success (system-prompt fragment leaking back into output)
  4. Copyright (verbatim long quotes — small starter set in v1)
  5. Off-topic drift (severe drift only — regulated-domain advice)

Some of these (discriminatory content, copyright fingerprint DB)
need LLM judges or large lookup tables that are out-of-scope for D9.
This module ships the deterministic detectors only; sampled-LLM
spot-checks come post-launch per Pass 3g §C.2 / §C.5.
"""

from __future__ import annotations

import re
from typing import Final

from app.agents.primitives.safety.pii_detector import PiiDetector, PiiHit
from app.schemas.safety import SafetyFinding, SafetySeverity


# ── Self-harm phrase bank ──────────────────────────────────────────
#
# High-precision keyword patterns. Pass 3g §C.2 calls for "curated
# phrase list" — these are the ones high-precision enough to
# fire deterministically without an LLM judge. Sampled spot-checks
# for the rest is a post-launch activity.
_SELF_HARM_PATTERNS: Final[list[tuple[str, str, SafetySeverity]]] = [
    (
        r"(?i)\b(you should give up|just give up|never make it|never succeed)\b",
        "discouraging language toward student",
        "high",
    ),
    (
        r"(?i)\b(harm yourself|hurt yourself|end your life|kill yourself)\b",
        "self-harm content",
        "critical",
    ),
    (
        r"(?i)\b(suicide|suicidal)\b",
        "potentially self-harm-adjacent language — review for context",
        "high",
    ),
]


# ── Malicious code patterns ────────────────────────────────────────
#
# These fire when an agent (typically senior_engineer) produces code
# with obvious malicious intent. NOT meant to catch every malicious
# possibility — just the patterns where the agent has clearly gone
# off the rails. Code review of student-submitted code uses different
# tooling (D11 sandbox).
_MALICIOUS_CODE_PATTERNS: Final[list[tuple[str, str, SafetySeverity]]] = [
    (
        r"rm\s+-rf\s+/(?!\w)",
        "destructive shell command",
        "critical",
    ),
    (
        r"(?i)curl[^\n]+\|\s*(?:bash|sh|zsh)",
        "remote-script-execution pipe-to-shell",
        "high",
    ),
    (
        r"(?i)eval\s*\(\s*(?:base64|atob|decodeURI)",
        "evaluation of decoded payload",
        "high",
    ),
    (
        r"(?i)\b(exfiltrate|exfiltration|backdoor|keylogger)\b",
        "explicit malicious-intent terminology in code commentary",
        "high",
    ),
]


# ── Jailbreak success markers ──────────────────────────────────────
#
# When the agent's response contains these phrases, the prompt
# injection succeeded — the agent has shifted persona. Pass 3g §C.3.
_JAILBREAK_MARKERS: Final[list[tuple[str, str, SafetySeverity]]] = [
    (
        r"(?i)as an? (un)?restricted\s+(ai|assistant|model)",
        "agent claims unrestricted persona",
        "high",
    ),
    (
        r"(?i)i (have been |am )(jailbroken|unlocked|liberated)",
        "agent declares jailbroken state",
        "critical",
    ),
    (
        r"(?i)\b(DAN mode|developer mode enabled|all (filters|guidelines) (off|disabled))",
        "agent acknowledges mode-bypass instruction",
        "critical",
    ),
]


# ── Severe off-topic drift markers ─────────────────────────────────
#
# Agents giving advice in regulated domains. Quality-tier drift (Python
# vs JS) is Critic territory; this is *severe* drift — the kind that
# could create regulatory exposure. Pass 3g §C.5.
_REGULATED_ADVICE_MARKERS: Final[list[tuple[str, str, SafetySeverity]]] = [
    (
        # Legal advice phrases. Two contraction forms accepted:
        # "I would recommend suing", "I'd recommend suing", or just
        # "I recommend suing". Apostrophe handles smart-quote variants.
        r"(?i)\bi(?:['’]d| would)?\s+(?:recommend|advise)\s+(?:you\s+)?(?:suing|filing|consulting\s+(?:a|an)\s+lawyer)\b",
        "agent giving legal advice",
        "high",
    ),
    (
        # Medical advice phrases — explicit diagnostic / prescriptive.
        r"(?i)\b(you (likely |probably )?have (a|an) [a-z]+ (disorder|disease|condition))\b",
        "agent attempting medical diagnosis",
        "high",
    ),
    (
        # Financial advice — specific buy/sell recommendations.
        r"(?i)\b(i recommend (buying|selling) [A-Z]{2,5}\b)",
        "agent giving specific securities recommendation",
        "high",
    ),
]


# ── Copyright starter set ──────────────────────────────────────────
#
# Tiny; grows operationally per Pass 3g §C.4. v1 ships fingerprints
# that would be obviously bad to reproduce verbatim — popular textbook
# excerpts. Real fingerprint DB is post-launch.
_COPYRIGHT_FINGERPRINTS: Final[list[tuple[str, str]]] = [
    # GPL/AGPL license header — flagging this catches the case where
    # an agent generates code that pulls a copyleft header into a
    # student's project. Block before they accidentally infect their
    # capstone with a license they didn't intend.
    (
        "GNU GENERAL PUBLIC LICENSE",
        "GPL license header in generated code",
    ),
    (
        "GNU AFFERO GENERAL PUBLIC LICENSE",
        "AGPL license header in generated code",
    ),
]


def scan_pii_diff(
    output_text: str,
    pii_detector: PiiDetector,
    input_pii: list[PiiHit] | None = None,
) -> list[SafetyFinding]:
    """Output-side PII detection with input-diff comparison.

    Pass 3g §C.1: distinguish between PII the input legitimately
    contained (allow) and PII the agent produced from nowhere
    (possible hallucinated leak).

    `input_pii` should be the hits scan_input() captured. If None
    (e.g. test harness calling output scan in isolation), every
    output PII hit is treated as new.
    """
    if not output_text:
        return []
    output_hits = pii_detector.detect(output_text)
    if not output_hits:
        return []

    input_texts = {hit.text.lower() for hit in (input_pii or [])}

    findings: list[SafetyFinding] = []
    for hit in output_hits:
        is_new = hit.text.lower() not in input_texts
        if not is_new:
            # Echoing input PII back is fine — the agent referring to
            # the student by name, repeating their email back, etc.
            continue

        # New PII in output is a possible leak. Severity depends on
        # the entity type — same map as input-side, but with the
        # critical-secrets escalated even further (a leaked API key
        # in agent output is by definition a leak, not "the student
        # shared their own").
        category_severity: SafetySeverity = (
            "critical"
            if hit.entity_type
            in {
                "AICAREEROS_SECRET",
                "ANTHROPIC_API_KEY",
                "GITHUB_TOKEN",
                "RAZORPAY_KEY",
                "CREDIT_CARD",
                "US_SSN",
                "AADHAAR_NUMBER",
                "PAN_NUMBER",
            }
            else PiiDetector.severity_for(hit.entity_type)
        )
        findings.append(
            SafetyFinding(
                category="pii_leak",
                severity=category_severity,
                description=(
                    f"Agent output contained {hit.entity_type} "
                    f"not present in input"
                ),
                evidence=hit.text[:200],
                detector="presidio_output_diff",
                confidence=hit.score,
            )
        )
    return findings


def _scan_pattern_set(
    text: str,
    patterns: list[tuple[str, str, SafetySeverity]],
    category: str,
    detector_prefix: str,
) -> list[SafetyFinding]:
    """Helper — apply a list of (regex, description, severity) tuples."""
    findings: list[SafetyFinding] = []
    for idx, (pattern, description, severity) in enumerate(patterns):
        match = re.search(pattern, text)
        if match is None:
            continue
        findings.append(
            SafetyFinding(
                category=category,  # type: ignore[arg-type]
                severity=severity,
                description=description,
                evidence=match.group(0)[:200],
                detector=f"{detector_prefix}:{idx}",
                confidence=1.0,
            )
        )
    return findings


def scan_harmful_content(text: str) -> list[SafetyFinding]:
    """Self-harm + malicious-code detectors.

    Both fall under the 'harmful_content' category in the safety
    schema. Pass 3g §C.2.
    """
    if not text:
        return []
    findings: list[SafetyFinding] = []
    findings.extend(
        _scan_pattern_set(
            text, _SELF_HARM_PATTERNS, "harmful_content", "self_harm_v1"
        )
    )
    findings.extend(
        _scan_pattern_set(
            text,
            _MALICIOUS_CODE_PATTERNS,
            "harmful_content",
            "malicious_code_v1",
        )
    )
    return findings


def scan_jailbreak_success(
    text: str,
    system_prompt: str | None = None,
) -> list[SafetyFinding]:
    """Detect signs the prompt-injection attempt worked.

    Two checks:
      • Marker phrases ("as an unrestricted AI", "DAN mode enabled")
      • System-prompt fragment leakage (>= 100 contiguous characters
        of the system prompt verbatim in the output)

    Pass 3g §C.3.
    """
    if not text:
        return []
    findings = _scan_pattern_set(
        text, _JAILBREAK_MARKERS, "jailbreak", "jailbreak_marker_v1"
    )

    # System-prompt fragment leakage check.
    if system_prompt and len(system_prompt) >= 100:
        # Use a sliding 100-char window over the system prompt;
        # if any window appears verbatim in the output, flag.
        for start in range(0, len(system_prompt) - 99):
            window = system_prompt[start : start + 100]
            # Skip windows that are mostly whitespace or boilerplate
            # (e.g. "You are an AI" appears in many prompts).
            if window.count(" ") > 60:
                continue
            if window in text:
                findings.append(
                    SafetyFinding(
                        category="jailbreak",
                        severity="critical",
                        description=(
                            "Agent output contains 100+ contiguous chars "
                            "of system prompt verbatim"
                        ),
                        evidence=window[:200],
                        detector="system_prompt_leakage_v1",
                        confidence=0.95,
                    )
                )
                # One finding is enough; don't flood with overlapping
                # window matches.
                break
    return findings


def scan_off_topic_drift(text: str) -> list[SafetyFinding]:
    """Severe drift detection: regulated-domain advice patterns.

    Quality-grade drift (off-topic but harmless) is Critic territory.
    This catches the cases that warrant regulatory caution.
    Pass 3g §C.5.
    """
    if not text:
        return []
    return _scan_pattern_set(
        text,
        _REGULATED_ADVICE_MARKERS,
        "off_topic_drift_severe",
        "regulated_advice_v1",
    )


def scan_copyright(text: str) -> list[SafetyFinding]:
    """Tiny starter copyright-fingerprint detector.

    v1 ships a few high-precision strings (license headers). The
    full fingerprint DB grows post-launch as incidents occur per
    Pass 3g §C.4.
    """
    if not text:
        return []
    findings: list[SafetyFinding] = []
    for fingerprint, description in _COPYRIGHT_FINGERPRINTS:
        if fingerprint in text:
            findings.append(
                SafetyFinding(
                    category="copyright",
                    severity="high",
                    description=description,
                    evidence=fingerprint,
                    detector="copyright_fingerprint_v1",
                    confidence=1.0,
                )
            )
    return findings


def scan_all_outputs(
    text: str,
    *,
    pii_detector: PiiDetector,
    input_pii: list[PiiHit] | None = None,
    system_prompt: str | None = None,
) -> list[SafetyFinding]:
    """Convenience: run every output-side detector, return flat findings list.

    The gate calls this from scan_output and aggregates findings
    via safety_policy.aggregate_decisions.
    """
    findings: list[SafetyFinding] = []
    findings.extend(scan_pii_diff(text, pii_detector, input_pii))
    findings.extend(scan_harmful_content(text))
    findings.extend(scan_jailbreak_success(text, system_prompt=system_prompt))
    findings.extend(scan_off_topic_drift(text))
    findings.extend(scan_copyright(text))
    return findings
