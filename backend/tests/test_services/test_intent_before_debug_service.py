"""Pure-function tests for the intent-before-debug detector (P3 3A-5).

Students pasting errors should get a "what were you trying to do?" question
first, but only when routed to a coding agent. These tests lock in the
patterns we detect and the agent gate so copy drift or a stray regex doesn't
silently break the behavior.
"""

from __future__ import annotations

import pytest

from app.services.intent_before_debug_service import (
    INTENT_BEFORE_DEBUG_OVERLAY,
    detects_error_paste,
    should_apply_intent_overlay,
)


# --- detects_error_paste ---------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        # Canonical Python traceback
        'Traceback (most recent call last):\n  File "app.py", line 42, in run\n    foo()\nValueError: bad input',
        # Exception line without the full traceback header
        "KeyError: 'anthropic_api_key'",
        # Mixed case traceback header
        "traceback (most recent call last):",
        # JS stack frame
        "TypeError: undefined is not a function\n    at handler (/app/index.js:12:7)",
        # Node-ish Error: line
        "Error: ECONNREFUSED 127.0.0.1:5432",
        # Generic compiler/lint fatal
        "fatal: unable to access repository",
        # Frame-only paste (sometimes students snip just the frame)
        'File "main.py", line 9, in <module>',
        # ImportError on a line of its own
        "ImportError: cannot import name 'Foo' from 'bar'",
        # ModuleNotFoundError with leading whitespace (happens when pasting
        # from a tool that indents)
        "    ModuleNotFoundError: No module named 'redis'",
    ],
)
def test_detects_error_paste_positive(message: str) -> None:
    assert detects_error_paste(message) is True


@pytest.mark.parametrize(
    "message",
    [
        # Prose about errors is not a paste
        "what is error handling in Python?",
        "I'm worried about exception safety in my async code",
        "can you explain why traceback is useful for debugging?",
        # Empty / whitespace
        "",
        "   \n\n",
        # Short question that happens to contain "error" without a colon
        "is this an error or expected behavior",
        # Code that mentions Error in a class name but isn't a paste
        "class ValidationError(Exception): pass  # how should I use this?",
    ],
)
def test_detects_error_paste_negative(message: str) -> None:
    assert detects_error_paste(message) is False


# --- should_apply_intent_overlay (agent gate) -----------------------------


def test_overlay_applies_for_coding_assistant() -> None:
    paste = "Traceback (most recent call last):\nValueError: x"
    assert should_apply_intent_overlay("coding_assistant", paste) is True


def test_overlay_applies_for_studio_tutor() -> None:
    paste = "ZeroDivisionError: division by zero"
    assert should_apply_intent_overlay("studio_tutor", paste) is True


def test_overlay_applies_for_code_review() -> None:
    paste = "KeyError: 'missing'"
    assert should_apply_intent_overlay("code_review", paste) is True


def test_overlay_skipped_for_socratic_tutor() -> None:
    # Conceptual agents should not get the paste-intercept treatment even
    # when the student happens to paste an error — the socratic framing is
    # already handling intent differently.
    paste = "Traceback (most recent call last):\nValueError: x"
    assert should_apply_intent_overlay("socratic_tutor", paste) is False


def test_overlay_skipped_for_student_buddy() -> None:
    paste = "TypeError: cannot unpack"
    assert should_apply_intent_overlay("student_buddy", paste) is False


def test_overlay_skipped_when_no_paste() -> None:
    assert (
        should_apply_intent_overlay("coding_assistant", "can you help me refactor?")
        is False
    )


# --- Overlay copy ----------------------------------------------------------


def test_overlay_copy_anchors() -> None:
    # Guard against prompt drift — the overlay must keep the two load-bearing
    # directives: (1) ask about intent first, (2) do not offer a fix yet.
    assert "FIRST reply" in INTENT_BEFORE_DEBUG_OVERLAY
    assert "what they were trying to do" in INTENT_BEFORE_DEBUG_OVERLAY
    assert "do not offer a fix" in INTENT_BEFORE_DEBUG_OVERLAY.lower()
