"""Intent-before-debug detector (P3 3A-5).

Students paste errors and expect a fix. The tutor should first ask
"what were you trying to do?" — teaches debugging, not dependency.

This module is a pure helper: a detector that inspects the student's message
for error-paste patterns (Python tracebacks, JS stack traces, common error
lines) and the overlay string to append to the tutor's system prompt when a
paste is spotted.

Kept separate from `stream.py` so it can be unit-tested without the streaming
machinery.
"""

from __future__ import annotations

import re


# Agents that do hands-on coding work. Only these get the overlay; the
# conceptual tutors (socratic, student_buddy) are allowed to dive in.
# D11 cutover (Checkpoint 4) absorbed coding_assistant + code_review
# into senior_engineer.
_CODING_AGENTS: frozenset[str] = frozenset(
    {"senior_engineer", "studio_tutor"}
)

# Patterns that are strong signals of a pasted error. Case-insensitive. We
# deliberately err on the side of precision — a false positive annoys the
# student with an unnecessary "what were you trying to do?" preface.
_ERROR_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Python traceback header — unambiguous.
    re.compile(r"traceback \(most recent call last\)", re.IGNORECASE),
    # `File "foo.py", line N, in bar` — Python frame line.
    re.compile(r'file "[^"]+", line \d+', re.IGNORECASE),
    # Common Python exception names at the start of a line.
    re.compile(
        r"^\s*(valueerror|typeerror|keyerror|attributeerror|"
        r"indexerror|runtimeerror|importerror|modulenotfounderror|"
        r"nameerror|syntaxerror|zerodivisionerror|assertionerror|"
        r"filenotfounderror|unicodeerror|recursionerror)\s*:",
        re.IGNORECASE | re.MULTILINE,
    ),
    # Node/JS stack frames — `at fn (file:line:col)`.
    re.compile(r"\n\s*at [\w.$<>]+\s*\([^)]+:\d+:\d+\)", re.IGNORECASE),
    # Generic `Error:` / `error:` / `Exception:` lines — common in Go, Rust,
    # compilers, linters. Requires a colon and some following text to avoid
    # matching prose like "error handling is important".
    re.compile(r"(?:^|\n)\s*(?:error|exception|fatal)\s*:\s+\S", re.IGNORECASE),
)

# The overlay the tutor appends to its system prompt when an error paste is
# detected on a coding-oriented agent. We intentionally allow the tutor to
# still look at the error — the rule is *ask first, then help*, not *refuse
# to look*.
INTENT_BEFORE_DEBUG_OVERLAY = (
    "\n\n---\nThe student's message contains a pasted error or stack trace. "
    "Before proposing a fix or diagnosing the error, your FIRST reply MUST "
    "open with one short question about what they were trying to do "
    "(the goal, the expected behavior, or the change they just made). "
    "Keep the question to one sentence, then wait for their answer. "
    "You may briefly acknowledge the error you see, but do not offer a fix, "
    "code, or step-by-step diagnosis until they respond. "
    "Rationale (do not quote back): this teaches debugging as a skill, not "
    "dependence on a fix-it bot."
)


def detects_error_paste(message: str) -> bool:
    """Return True if `message` looks like a pasted error or stack trace.

    Matches Python tracebacks, JS stack frames, and generic `Error:` /
    `Exception:` / `Fatal:` lines. Case-insensitive. Empty or whitespace-only
    messages are never a paste.
    """
    if not message or not message.strip():
        return False
    return any(pattern.search(message) for pattern in _ERROR_PATTERNS)


def should_apply_intent_overlay(agent_name: str, message: str) -> bool:
    """Gate: overlay applies only for coding agents with a detected paste."""
    if agent_name not in _CODING_AGENTS:
        return False
    return detects_error_paste(message)
