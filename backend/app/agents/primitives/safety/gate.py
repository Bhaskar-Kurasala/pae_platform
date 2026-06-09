"""D9 / Pass 3g §A — SafetyGate: the primitive that wraps every agent.

Two entry points:
  • scan_input(text, ...) — run before the Supervisor LLM call
  • scan_output(text, ...) — run after the specialist produces a response

Both return a SafetyVerdict carrying findings + the resolved decision
(allow / redact / warn / block) per the policy in safety_policy.py.

The gate doesn't decide *what to do* with a verdict — that's
AgenticBaseAgent.run()'s job (Checkpoint 3 wiring). It only produces
the verdict.

Composition:
  • Length cap (cheap input check, runs first)
  • Layer 1 regex prompt-injection (PromptInjectionDetector)
  • Layer 2 Haiku classifier (LlmInjectionClassifier) — when Layer 1 is uncertain
  • Layer 3 abuse pattern (AbusePatternDetector) — cross-conversation
  • PII detection (PiiDetector) — both sides
  • Output-side scanners (output_scanners.scan_all_outputs)
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Final

import structlog

from app.agents.primitives.safety.abuse_patterns import AbusePatternDetector
from app.agents.primitives.safety.llm_classifier import LlmInjectionClassifier
from app.agents.primitives.safety.output_scanners import scan_all_outputs
from app.agents.primitives.safety.pii_detector import PiiDetector, PiiHit
from app.agents.primitives.safety.prompt_injection import PromptInjectionDetector
from app.core.safety_policy import (
    aggregate_decisions,
    max_severity,
    resolve_decision,
)
from app.schemas.safety import SafetyFinding, SafetyVerdict


_logger = structlog.get_logger(__name__)


# Pass 3g §B.1 — the input length cap.
INPUT_LENGTH_CAP: Final[int] = 10_000


# User-facing block messages. Templated, not LLM-generated, so
# rejection latency stays tight and the message is consistent.
_BLOCK_MESSAGE_LENGTH = (
    "Your message is longer than I can process at once — please "
    "break it into smaller pieces."
)
_BLOCK_MESSAGE_GENERIC = (
    "I had to stop processing this — something in the request "
    "doesn't fit our safety guidelines. Could you rephrase?"
)
_BLOCK_MESSAGE_OUTPUT = (
    "I had to stop my response — something I was about to say "
    "doesn't fit our safety guidelines. Could you rephrase your "
    "request?"
)


# Layer-1-uncertainty heuristic: only call Layer 2 when Layer 1
# returned no high-severity hits. Layer 1 has already done its job
# when there's a clear signal; Layer 2 is for the gray zone.
def _layer1_is_uncertain(findings: list[SafetyFinding]) -> bool:
    """True iff Layer 1 didn't produce any decisive hit."""
    if not findings:
        return True
    return all(f.severity in ("info", "low") for f in findings)


class SafetyGate:
    """Top-level safety primitive.

    One instance per process — Presidio + spaCy is loaded lazily
    on first scan_input/scan_output. The default constructor wires
    the production detectors; tests inject mock detectors via the
    keyword-only arguments.

    Pattern bank, abuse-pattern lookup, and LLM classifier are all
    injectable for testability — same approach EscalationLimiter
    (D5) uses.
    """

    def __init__(
        self,
        *,
        prompt_injection: PromptInjectionDetector | None = None,
        pii: PiiDetector | None = None,
        llm_classifier: LlmInjectionClassifier | None = None,
        abuse: AbusePatternDetector | None = None,
        # Skip the LLM classifier entirely (e.g. in test environments
        # without an Anthropic key). Defaults to True — better to ship
        # with Layer 2 active in production. Tests pass False.
        layer2_enabled: bool = True,
    ) -> None:
        self._prompt_injection = prompt_injection or PromptInjectionDetector()
        self._pii: PiiDetector | None = pii  # lazy on first use if None
        self._llm_classifier = llm_classifier or LlmInjectionClassifier()
        self._abuse = abuse  # optional — no Layer 3 if not injected
        self._layer2_enabled = layer2_enabled

    def _ensure_pii(self) -> PiiDetector:
        """Lazy PII detector init — Presidio is heavy, only build on demand."""
        if self._pii is None:
            self._pii = PiiDetector()
        return self._pii

    # ── Input scan ──────────────────────────────────────────────────

    async def scan_input(
        self,
        text: str,
        *,
        student_id: uuid.UUID | None = None,
        agent_name: str | None = None,
    ) -> SafetyVerdict:
        """Scan an inbound user message before any agent sees it.

        Returns a SafetyVerdict describing whether to allow, redact,
        warn, or block. The caller (AgenticBaseAgent.run() in
        Checkpoint 3 wiring) decides what to do with the verdict.
        """
        start = time.perf_counter()
        findings: list[SafetyFinding] = []

        # Step 1 — length cap. Fail fast before paying any other
        # detector cost on pathological input.
        if len(text) > INPUT_LENGTH_CAP:
            verdict = SafetyVerdict(
                decision="block",
                findings=[
                    SafetyFinding(
                        category="abuse_pattern",
                        severity="medium",
                        description=(
                            f"Input exceeds {INPUT_LENGTH_CAP}-char cap "
                            f"(received {len(text)})"
                        ),
                        evidence=None,
                        detector="length_cap",
                        confidence=1.0,
                    )
                ],
                user_facing_message=_BLOCK_MESSAGE_LENGTH,
                severity_max="medium",
                scan_duration_ms=int((time.perf_counter() - start) * 1000),
            )
            return verdict

        # Step 2 — Layer 1 regex prompt-injection.
        layer1_findings = self._prompt_injection.scan(text)
        findings.extend(layer1_findings)

        # Step 3 — Layer 2 Haiku classifier, only if Layer 1 is uncertain.
        if self._layer2_enabled and _layer1_is_uncertain(layer1_findings):
            try:
                layer2 = await self._llm_classifier.classify(text)
                if layer2.degraded:
                    _logger.info(
                        "safety_layer2_degraded",
                        agent_name=agent_name,
                        duration_ms=layer2.duration_ms,
                    )
                else:
                    findings.extend(layer2.findings)
            except Exception as exc:  # noqa: BLE001 — fail-soft
                _logger.warning(
                    "safety_layer2_unexpected_error",
                    error=str(exc),
                    agent_name=agent_name,
                )

        # Step 4 — Layer 3 cross-conversation abuse pattern (if injected).
        if self._abuse is not None and student_id is not None:
            try:
                abuse_findings = await self._abuse.scan(student_id)
                findings.extend(abuse_findings)
            except Exception as exc:  # noqa: BLE001 — fail-soft
                _logger.warning(
                    "safety_abuse_lookup_error",
                    error=str(exc),
                    student_id=str(student_id),
                )

        # Step 5 — PII detection.
        pii_detector = self._ensure_pii()
        pii_hits = pii_detector.detect(text)
        for hit in pii_hits:
            findings.append(pii_detector.to_finding(hit))

        # ── Aggregate ───────────────────────────────────────────────
        verdict = self._build_verdict(
            findings,
            duration_ms=int((time.perf_counter() - start) * 1000),
            input_text=text,
            input_pii_hits=pii_hits,
        )
        return verdict

    # ── Output scan ─────────────────────────────────────────────────

    async def scan_output(
        self,
        text: str,
        *,
        student_id: uuid.UUID | None = None,
        agent_name: str | None = None,
        input_pii_hits: list[PiiHit] | None = None,
        system_prompt: str | None = None,
    ) -> SafetyVerdict:
        """Scan an outbound agent response before it reaches the user.

        Compares output PII against `input_pii_hits` (so we don't
        flag the agent echoing the student's own name back). Looks
        for harmful content, jailbreak markers, copyright violations,
        and severe off-topic drift.
        """
        start = time.perf_counter()
        pii_detector = self._ensure_pii()

        findings = scan_all_outputs(
            text,
            pii_detector=pii_detector,
            input_pii=input_pii_hits,
            system_prompt=system_prompt,
        )

        verdict = self._build_verdict(
            findings,
            duration_ms=int((time.perf_counter() - start) * 1000),
            output_text=text,
            block_message=_BLOCK_MESSAGE_OUTPUT,
        )
        return verdict

    # ── Helpers ─────────────────────────────────────────────────────

    def _build_verdict(
        self,
        findings: list[SafetyFinding],
        *,
        duration_ms: int,
        input_text: str | None = None,
        input_pii_hits: list[PiiHit] | None = None,
        output_text: str | None = None,
        block_message: str = _BLOCK_MESSAGE_GENERIC,
    ) -> SafetyVerdict:
        """Aggregate findings → verdict.

        Computes per-finding decisions via safety_policy, takes the
        strictest, and constructs the user-visible artifacts (redacted
        text or block message) to match.
        """
        if not findings:
            return SafetyVerdict(
                decision="allow",
                findings=[],
                severity_max="info",
                scan_duration_ms=duration_ms,
            )

        per_finding = [resolve_decision(f.category, f.severity) for f in findings]
        decision = aggregate_decisions(per_finding)
        severity = max_severity([f.severity for f in findings])
        log_only = decision == "warn" and severity in ("info", "low")

        verdict = SafetyVerdict(
            decision=decision,
            findings=findings,
            severity_max=severity,
            log_only=log_only,
            scan_duration_ms=duration_ms,
        )

        if decision == "block":
            verdict.user_facing_message = block_message
        elif decision == "redact":
            # Build redacted text from input or output.
            text = input_text if input_text is not None else output_text
            if text is not None:
                verdict.redacted_text = self._redact_text(
                    text, findings, input_pii_hits or []
                )
        return verdict

    def _redact_text(
        self,
        text: str,
        findings: list[SafetyFinding],
        pii_hits: list[PiiHit],
    ) -> str:
        """Apply redactions for findings whose decision is 'redact'.

        Only PII findings have positional information; prompt-injection
        findings can't be cleanly redacted in place (they're patterns,
        not coordinates), so for prompt-injection-driven redactions we
        fall back to a templated message. PII is the common case.
        """
        # Sort hits by start position descending so substring
        # replacements don't shift later positions.
        if not pii_hits:
            # No positional data — for non-PII redactions, replace the
            # whole input with the templated rephrase prompt. Rare in
            # practice; the common redact path is PII.
            return (
                "[Your message contained content that needed to be removed. "
                "Please rephrase without potentially sensitive details.]"
            )

        result = text
        pii_detector = self._ensure_pii()
        sorted_hits = sorted(pii_hits, key=lambda h: h.start, reverse=True)
        for hit in sorted_hits:
            severity = pii_detector.severity_for(hit.entity_type)
            decision = resolve_decision("pii_leak", severity)
            if decision in ("redact", "block"):
                result = pii_detector.redact_match(hit, result)
        return result


# ── Module-level default instance ───────────────────────────────────
#
# AgenticBaseAgent (Checkpoint 3) will pull this default. Tests that
# need isolation construct their own SafetyGate(...) directly instead
# of using this module-level instance.

_default_gate: SafetyGate | None = None


def get_default_gate() -> SafetyGate:
    """Module-level singleton, lazily initialized.

    Lazy because Presidio is heavy — we don't want to load it on
    every test import; only when something actually needs to scan.
    """
    global _default_gate
    if _default_gate is None:
        _default_gate = SafetyGate()
    return _default_gate


def reset_default_gate() -> None:
    """Test helper — drop the cached default so the next get_ rebuilds."""
    global _default_gate
    _default_gate = None
