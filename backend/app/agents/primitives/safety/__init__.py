"""D9 / Pass 3g — safety primitive public surface.

Re-exports the symbols agents and tests import. Internal helpers
(detector implementation details, the LLM classifier's parsing
machinery) stay private to their modules so refactors don't break
callers.

Wired into AgenticBaseAgent.run() in D9 Checkpoint 3 — until then
the gate is reachable but un-integrated.
"""

from app.agents.primitives.safety.abuse_patterns import (
    AbusePatternDetector,
    AccountAgeLookup,
    IncidentLookup,
    IncidentSummary,
)
from app.agents.primitives.safety.gate import (
    INPUT_LENGTH_CAP,
    SafetyGate,
    get_default_gate,
    reset_default_gate,
)
from app.agents.primitives.safety.llm_classifier import (
    LlmClassifierResult,
    LlmInjectionClassifier,
)
from app.agents.primitives.safety.output_scanners import (
    scan_all_outputs,
    scan_copyright,
    scan_harmful_content,
    scan_jailbreak_success,
    scan_off_topic_drift,
    scan_pii_diff,
)
from app.agents.primitives.safety.pii_detector import (
    PiiDetector,
    PiiHit,
)
from app.agents.primitives.safety.prompt_injection import (
    CompiledPattern,
    PromptInjectionDetector,
    load_pattern_bank,
)
from app.agents.primitives.safety.streaming import (
    StreamingScanResult,
    scan_streaming,
)

__all__ = [
    # Gate
    "SafetyGate",
    "get_default_gate",
    "reset_default_gate",
    "INPUT_LENGTH_CAP",
    # Layer 1
    "PromptInjectionDetector",
    "CompiledPattern",
    "load_pattern_bank",
    # Layer 2
    "LlmInjectionClassifier",
    "LlmClassifierResult",
    # Layer 3
    "AbusePatternDetector",
    "IncidentLookup",
    "AccountAgeLookup",
    "IncidentSummary",
    # PII
    "PiiDetector",
    "PiiHit",
    # Output scanners
    "scan_all_outputs",
    "scan_pii_diff",
    "scan_harmful_content",
    "scan_jailbreak_success",
    "scan_off_topic_drift",
    "scan_copyright",
    # Streaming
    "scan_streaming",
    "StreamingScanResult",
]
