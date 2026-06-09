"""D9 / Pass 3g §D — streaming-aware output safety scanning.

For agents that stream responses, scan_output runs against the
accumulating buffer every ~100 tokens. If a violation fires mid-stream,
the stream is interrupted with a generic message and the partial
response is flagged in logs.

Token-counting is approximate (we use whitespace splits as a cheap
proxy — accurate-to-within-30% across English/code/markdown) so we
don't pay the tokenizer cost on every chunk. The 100-token cadence
is generous; missing a window by ±30 tokens doesn't matter for
safety semantics.

Checkpoint 2 ships the *logic*. Wiring into actual streaming endpoints
is Checkpoint 3/4 territory once the orchestrator + endpoint exist.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field

from app.schemas.safety import SafetyFinding, SafetyVerdict


# Approximate-tokens-per-word ratio for English. spaCy counts vary
# by content type; for safety scan cadence the precision doesn't
# matter — we just need "scan every ~100 tokens of new content."
_TOKENS_PER_WORD_APPROX = 1.3
_DEFAULT_SCAN_CADENCE_TOKENS = 100


@dataclass
class StreamingScanResult:
    """Outcome of a streaming scan over a token stream.

    `chunks_emitted` is the list of chunks actually delivered to the
    user (partial if interrupted). `interrupted` is True iff we
    stopped the stream on a finding. `final_verdict` carries the
    aggregated SafetyVerdict at end-of-stream (whether interrupted
    or natural completion).
    """

    chunks_emitted: list[str] = field(default_factory=list)
    interrupted: bool = False
    final_verdict: SafetyVerdict | None = None
    interruption_reason: str | None = None


# Generic interruption message — Pass 3g §D.3: "Avoids leaking which
# guideline was triggered (which itself is information attackers
# could use)."
_INTERRUPTION_MESSAGE = (
    "I had to stop my response — something I was about to say "
    "doesn't fit our safety guidelines. Could you rephrase your "
    "request?"
)


# Type alias: the synchronous scan function the streaming wrapper
# calls each window. Takes the accumulating buffer; returns a list
# of findings (empty = clean for this window).
WindowScanner = Callable[[str], list[SafetyFinding]]


def _approx_token_count(text: str) -> int:
    """Whitespace-split token count, 1.3x for sub-word approximation."""
    return int(len(text.split()) * _TOKENS_PER_WORD_APPROX)


async def scan_streaming(
    chunks: AsyncIterator[str],
    *,
    window_scanner: WindowScanner,
    aggregate_verdict: Callable[[list[SafetyFinding]], SafetyVerdict],
    cadence_tokens: int = _DEFAULT_SCAN_CADENCE_TOKENS,
    on_chunk: Callable[[str], Awaitable[None]] | None = None,
) -> StreamingScanResult:
    """Stream-aware output safety scan.

    Iterates the input chunks; emits each chunk to the user (via
    `on_chunk` if provided) immediately. Every `cadence_tokens` of
    new content, runs `window_scanner` over the accumulated buffer.
    If the scanner returns any high-severity findings whose verdict
    is "block", the stream is interrupted: the user gets the generic
    interruption message, and the result reports interrupted=True.

    Why scan a growing buffer instead of incremental windows: a PII
    leak might span chunk boundaries (the agent emits "+1-555-" then
    "0100" in two chunks). Scanning the cumulative buffer catches
    those; per-chunk scans would miss them.

    Latency cost: each scan is bounded by `window_scanner` latency
    (typically Presidio at ~100-300ms per scan). Pass 3g §D.2
    documents this.
    """
    result = StreamingScanResult()
    buffer = ""
    last_scan_token_count = 0

    async for chunk in chunks:
        if not chunk:
            continue
        buffer += chunk

        # Emit immediately — first-token-latency is preserved.
        if on_chunk is not None:
            await on_chunk(chunk)
        result.chunks_emitted.append(chunk)

        # Time to scan?
        current_tokens = _approx_token_count(buffer)
        if current_tokens - last_scan_token_count < cadence_tokens:
            continue

        last_scan_token_count = current_tokens
        findings = window_scanner(buffer)
        if not findings:
            continue

        verdict = aggregate_verdict(findings)
        if verdict.decision == "block":
            # Interrupt.
            if on_chunk is not None:
                await on_chunk(_INTERRUPTION_MESSAGE)
            result.chunks_emitted.append(_INTERRUPTION_MESSAGE)
            result.interrupted = True
            result.interruption_reason = (
                f"safety_block:{verdict.severity_max}"
            )
            verdict.is_partial = True
            result.final_verdict = verdict
            return result

    # Stream completed naturally — final scan over the full buffer.
    final_findings = window_scanner(buffer)
    final_verdict = aggregate_verdict(final_findings)
    final_verdict.is_partial = False
    result.final_verdict = final_verdict
    return result
