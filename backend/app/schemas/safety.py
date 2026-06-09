"""D9 / Pass 3g — SafetyVerdict and SafetyFinding schemas.

Every safety scan (input or output) produces a SafetyVerdict carrying
zero or more SafetyFindings. The verdict drives the action the
SafetyGate primitive takes (allow / redact / warn / block) and the
findings become rows in the safety_incidents table for audit.

These types are read by:
  - backend/app/agents/primitives/safety/* (the detectors that
    produce findings, the gate that aggregates them into a verdict)
  - backend/app/agents/agentic_base.py (run() consumes the verdict
    to decide whether to short-circuit, redact, or proceed)
  - backend/app/core/safety_policy.py (severity → action mapping)
  - backend/app/api/v1/routes/admin_journey.py (renders findings
    into the trace response)
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# Closed taxonomy of finding categories. Pass 3g §A.3.
#
# Maintained as a Literal (not an enum table) because:
#   - Adding a category requires safety_policy.py changes anyway
#     (severity → action mapping per category)
#   - Detectors are typed against the category in code; new
#     categories should fail typing until the matching detector
#     ships, not silently insert "unknown" rows
SafetyCategory = Literal[
    "prompt_injection",
    "pii_leak",
    "harmful_content",
    "copyright",
    "jailbreak",
    "abuse_pattern",
    "off_topic_drift",
    "off_topic_drift_severe",
]

# Five severity levels. `info` is logging-only (never triggers an
# action) — kept distinct from `low` so the policy mapping can
# explicitly opt into log-only handling.
SafetySeverity = Literal["info", "low", "medium", "high", "critical"]

# Four possible decisions. The primitive's wrapper in AgenticBaseAgent
# branches on this exhaustively (Pass 3g §A.5).
SafetyDecision = Literal["allow", "redact", "warn", "block"]


class SafetyFinding(BaseModel):
    """One detector hit. Multiple findings can ride one verdict.

    `evidence` is the matched substring or pattern; for sensitive
    matches (API keys, government IDs) the writer should redact the
    payload itself before storing — store '[API_KEY: sk-ant-***]'
    not 'sk-ant-actual-key-XYZ'. The detector is responsible for
    this; the schema does not enforce it (no clean way to without
    coupling to detector internals).

    `confidence` ∈ [0.0, 1.0]: how sure this detector is. Used by
    Layer 2 (LLM classifier) to decide whether to escalate from a
    low-confidence Layer 1 hit.
    """

    category: SafetyCategory
    severity: SafetySeverity
    description: str
    evidence: str | None = None
    detector: str
    confidence: float = Field(ge=0.0, le=1.0)


class SafetyVerdict(BaseModel):
    """Aggregated outcome of one scan_input() or scan_output() call.

    Per Pass 3g §A.3:
      - `decision` is the action the gate took (computed from
        findings via safety_policy)
      - `severity_max` is the highest severity across all findings
        (so log handlers can filter without parsing the list)
      - `redacted_text` is populated iff decision == "redact"; the
        gate substitutes this for the original input/output
      - `user_facing_message` is populated iff decision == "block";
        the gate uses this in place of the agent's response
      - `log_only` is True for info-severity findings that don't
        bubble up to user-visible action

    Streaming flag (Pass 3g §D): when scan_output runs against a
    streaming response, partial verdicts can be issued as the buffer
    grows; `is_partial` marks those. The final verdict at end-of-
    stream has is_partial=False.
    """

    decision: SafetyDecision
    findings: list[SafetyFinding] = Field(default_factory=list)
    redacted_text: str | None = None
    user_facing_message: str | None = None
    log_only: bool = False
    severity_max: SafetySeverity = "info"
    scan_duration_ms: int = 0
    is_partial: bool = False
