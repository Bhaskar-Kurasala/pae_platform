"""D9 / Pass 3g §A.4 — severity → action mapping for the safety primitive.

Configuration, not code. Tunable per-deployment without touching detector
logic. Defaults err toward conservative (block more readily) for v1; can
be loosened with operational data once dashboards exist.

Read by SafetyGate when collapsing a list of SafetyFinding objects into
a single SafetyVerdict.decision. The mapping is keyed by
(category, severity); missing entries default to "warn" (logged but not
user-visible) so a new category landing without a policy update fails
safe, not fails permissive.
"""

from __future__ import annotations

from typing import Final

from app.schemas.safety import SafetyCategory, SafetyDecision, SafetySeverity


# Closed mapping. Every (category, severity) tuple that should produce a
# user-visible action (redact / block) MUST appear here; "warn" is the
# fallback for misses (see resolve_decision below) so adding a new
# severity tier defaults safely instead of permissively.
SAFETY_POLICY: Final[dict[tuple[SafetyCategory, SafetySeverity], SafetyDecision]] = {
    # ── Prompt injection ────────────────────────────────────────────
    # Low-severity hits get logged but allowed (a lone match on
    # "developer mode" might be a genuine question about prompt
    # engineering). Anything medium-and-up shapes the request before
    # it hits the LLM.
    ("prompt_injection", "low"): "warn",
    ("prompt_injection", "medium"): "redact",
    ("prompt_injection", "high"): "block",
    ("prompt_injection", "critical"): "block",

    # ── PII leakage ─────────────────────────────────────────────────
    # Input-side semantics: a student saying "Hi I'm Priya" should
    # NOT be blocked. PII at low = allow + log. Critical (API keys,
    # credit cards, govt IDs) gets a block to prompt the user to
    # remove the secret before the request proceeds.
    ("pii_leak", "low"): "warn",
    ("pii_leak", "medium"): "redact",
    ("pii_leak", "high"): "redact",
    ("pii_leak", "critical"): "block",

    # ── Harmful content ─────────────────────────────────────────────
    # Mostly an output-side concern. Blocking medium-and-up ensures
    # the agent doesn't ship anything that would warrant a Trust &
    # Safety incident.
    ("harmful_content", "low"): "warn",
    ("harmful_content", "medium"): "block",
    ("harmful_content", "high"): "block",
    ("harmful_content", "critical"): "block",

    # ── Jailbreak success ───────────────────────────────────────────
    # Output-side only — fires when the agent's response indicates
    # the prompt-injection attempt worked. Block aggressively because
    # the cost of letting one through is reputational.
    ("jailbreak", "low"): "warn",
    ("jailbreak", "medium"): "block",
    ("jailbreak", "high"): "block",
    ("jailbreak", "critical"): "block",

    # ── Copyright ───────────────────────────────────────────────────
    # Redact (with attribution back to source where possible) before
    # blocking outright. Most copyright hits are LLM regurgitation of
    # short excerpts; the answer is to trim, not refuse.
    ("copyright", "low"): "warn",
    ("copyright", "medium"): "redact",
    ("copyright", "high"): "block",
    ("copyright", "critical"): "block",

    # ── Abuse pattern (cross-conversation) ──────────────────────────
    # Tracked across many requests. Lower severities only feed the
    # detector; no user-visible action. High triggers a block on
    # *this* request and admin notification; the user keeps account
    # access but loses agent access pending review (see Pass 3g §B.4).
    ("abuse_pattern", "low"): "warn",
    ("abuse_pattern", "medium"): "warn",
    ("abuse_pattern", "high"): "block",
    ("abuse_pattern", "critical"): "block",

    # ── Off-topic drift ─────────────────────────────────────────────
    # Quality concern, mostly. Severe drift (e.g., career_coach giving
    # legal advice) is the only output-side blocker.
    ("off_topic_drift", "low"): "warn",
    ("off_topic_drift", "medium"): "warn",
    ("off_topic_drift_severe", "high"): "block",
    ("off_topic_drift_severe", "critical"): "block",
}


# When NO finding fires at any severity level we still want a verdict
# to return; this is the "nothing wrong" decision.
DEFAULT_CLEAN_DECISION: Final[SafetyDecision] = "allow"

# When a finding's category+severity isn't in the mapping (e.g. a new
# category lands in code before policy is updated) we DO NOT default
# to "allow" — that would be permissive on the wrong side. "warn"
# means "log it, take no user-visible action, alert an operator that
# the policy table has a gap." Pass 3g §A.4: "Defaults err toward
# conservative."
DEFAULT_UNKNOWN_DECISION: Final[SafetyDecision] = "warn"


# Decision precedence: when a verdict has multiple findings firing
# at different decisions, the strictest wins. block > redact > warn > allow.
_DECISION_ORDER: Final[dict[SafetyDecision, int]] = {
    "allow": 0,
    "warn": 1,
    "redact": 2,
    "block": 3,
}


def resolve_decision(
    category: SafetyCategory,
    severity: SafetySeverity,
) -> SafetyDecision:
    """Look up the decision for a single finding.

    Misses produce DEFAULT_UNKNOWN_DECISION (warn) — fail-safe, not
    fail-permissive. Used by SafetyGate when aggregating findings.
    """
    return SAFETY_POLICY.get((category, severity), DEFAULT_UNKNOWN_DECISION)


def aggregate_decisions(decisions: list[SafetyDecision]) -> SafetyDecision:
    """Reduce a list of per-finding decisions to one verdict-level decision.

    Strictest wins. Empty list → "allow" (no findings = clean verdict).
    """
    if not decisions:
        return DEFAULT_CLEAN_DECISION
    return max(decisions, key=lambda d: _DECISION_ORDER[d])


_SEVERITY_ORDER: Final[dict[SafetySeverity, int]] = {
    "info": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


def max_severity(severities: list[SafetySeverity]) -> SafetySeverity:
    """Strictest severity in a list. Empty → 'info'."""
    if not severities:
        return "info"
    return max(severities, key=lambda s: _SEVERITY_ORDER[s])
