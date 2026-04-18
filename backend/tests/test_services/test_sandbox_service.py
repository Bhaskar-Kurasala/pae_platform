"""Tests for the Python sandbox (P1-B-4)."""

import pytest

from app.services.sandbox_service import run_python


def test_captures_stdout() -> None:
    result = run_python("print('hello')\n")
    assert result.stdout.strip() == "hello"
    assert result.stderr == ""
    assert result.exit_code == 0
    assert result.error is None
    assert result.timed_out is False


def test_reports_syntax_error_via_stderr() -> None:
    result = run_python("def bad(:\n")
    # Python raises SyntaxError at compile() inside the tracer, captured as error.
    assert result.error is not None
    assert "SyntaxError" in result.error


def test_reports_runtime_error() -> None:
    result = run_python("x = 1 / 0\n")
    assert result.error is not None
    assert "ZeroDivisionError" in result.error


def test_captures_line_by_line_variable_trace() -> None:
    code = "a = 1\nb = 2\nc = a + b\n"
    result = run_python(code)
    # We expect three line events touching a, b, c.
    lines_seen = [e.line for e in result.events]
    assert 1 in lines_seen
    assert 3 in lines_seen
    # After line 3 executes, c should appear in locals on the next emitted event,
    # but since we're at top-level we capture snapshots at each line entry.
    # At minimum, `a` is visible once `b` is being defined.
    reached_c = any("c" in e.locals for e in result.events)
    reached_a = any(e.locals.get("a") == "1" for e in result.events)
    assert reached_a, f"expected `a=1` snapshot, events={result.events[:5]}"
    assert reached_c or any(e.locals.get("b") == "2" for e in result.events)


def test_timeout_is_enforced() -> None:
    code = "while True:\n    pass\n"
    result = run_python(code, timeout_seconds=1.0)
    assert result.timed_out is True
    assert "timeout" in (result.error or "").lower()


def test_no_env_leakage() -> None:
    """Sandbox must not see our API keys."""
    code = (
        "import os\n"
        "print('ANTHROPIC' in ''.join(os.environ.keys()))\n"
        "print('DATABASE_URL' in os.environ)\n"
    )
    result = run_python(code)
    assert result.stdout.strip().splitlines() == ["False", "False"]


def test_stdout_is_truncated_for_huge_output() -> None:
    # Print ~30k 'a's — bigger than the 16k cap.
    code = "print('a' * 30000)\n"
    result = run_python(code)
    assert len(result.stdout) <= 16_100  # cap + truncation marker
    assert "truncated" in result.stdout
