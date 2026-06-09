"""D11.5 — SandboxRequest / SandboxResult schema tests (Pass 3d
§E.3.2 contract).

Pure validation tests; no execution, no LLM cost.
Pins the spec contract: language Literal["python", "node"],
test_inputs, network_access, timeout 1-60s, memory 64-1024MB,
duration_ms (was runtime_ms), timed_out (was timeout_killed),
truncated (single flag), memory_used_mb.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.sandbox import SandboxRequest, SandboxResult


# ── SandboxRequest ─────────────────────────────────────────────────


class TestSandboxRequest:
    def test_minimal_request_uses_defaults(self) -> None:
        req = SandboxRequest(code="print('hi')")
        assert req.language == "python"
        assert req.timeout_seconds == 10
        assert req.memory_limit_mb == 256
        assert req.test_inputs == []
        assert req.network_access is False

    def test_full_request_validates(self) -> None:
        req = SandboxRequest(
            code="x = 1",
            language="python",
            test_inputs=["1\n2\n", "3\n"],
            network_access=False,
            timeout_seconds=20,
            memory_limit_mb=512,
        )
        assert req.timeout_seconds == 20
        assert req.memory_limit_mb == 512
        assert req.test_inputs == ["1\n2\n", "3\n"]

    def test_node_language_accepted_at_schema_level(self) -> None:
        """language='node' is valid in the schema; the executor raises
        NotImplementedError when actually invoked. Schema layer is the
        spec contract; executor is the Path A surface."""
        req = SandboxRequest(code="console.log('hi')", language="node")
        assert req.language == "node"

    def test_unknown_language_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SandboxRequest(code="x = 1", language="rust")  # type: ignore[arg-type]

    def test_timeout_seconds_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SandboxRequest(code="x = 1", timeout_seconds=0)

    def test_timeout_seconds_above_60_rejected(self) -> None:
        """Pass 3d §E.3.2 ceiling is 60s."""
        with pytest.raises(ValidationError):
            SandboxRequest(code="x = 1", timeout_seconds=61)

    def test_timeout_seconds_at_60_accepted(self) -> None:
        req = SandboxRequest(code="x = 1", timeout_seconds=60)
        assert req.timeout_seconds == 60

    def test_memory_below_floor_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SandboxRequest(code="x = 1", memory_limit_mb=63)

    def test_memory_above_1024_rejected(self) -> None:
        """Pass 3d §E.3.2 ceiling is 1024MB."""
        with pytest.raises(ValidationError):
            SandboxRequest(code="x = 1", memory_limit_mb=1025)

    def test_memory_at_1024_accepted(self) -> None:
        req = SandboxRequest(code="x = 1", memory_limit_mb=1024)
        assert req.memory_limit_mb == 1024

    def test_code_over_100kb_rejected(self) -> None:
        oversized = "x" * 100_001
        with pytest.raises(ValidationError):
            SandboxRequest(code=oversized)

    def test_code_at_100kb_exact_accepted(self) -> None:
        at_limit = "x" * 100_000
        req = SandboxRequest(code=at_limit)
        assert len(req.code) == 100_000

    def test_test_inputs_empty_list_default(self) -> None:
        req = SandboxRequest(code="x = 1")
        assert req.test_inputs == []

    def test_test_inputs_over_max_length_rejected(self) -> None:
        """Cap test_inputs at 20 elements to bound audit row size."""
        with pytest.raises(ValidationError):
            SandboxRequest(code="x = 1", test_inputs=["x"] * 21)

    def test_extra_fields_rejected(self) -> None:
        """extra='forbid' — catches accidental param drift."""
        with pytest.raises(ValidationError):
            SandboxRequest(code="x = 1", network_allowed=True)  # type: ignore[call-arg]


# ── SandboxResult ──────────────────────────────────────────────────


class TestSandboxResult:
    def test_clean_execution_result(self) -> None:
        """Happy path: print returned cleanly, no failure flags."""
        result = SandboxResult(
            stdout="hello\n",
            stderr="",
            exit_code=0,
            duration_ms=42,
            memory_used_mb=12,
        )
        assert result.timed_out is False
        assert result.oom_killed is False
        assert result.sandbox_escaped is False
        assert result.truncated is False
        assert result.exception_traceback is None
        assert result.language == "python"
        assert result.memory_used_mb == 12

    def test_minimal_result_with_only_duration(self) -> None:
        """The only required field is duration_ms."""
        result = SandboxResult(duration_ms=0)
        assert result.stdout == ""
        assert result.stderr == ""
        assert result.exit_code is None
        assert result.memory_used_mb == 0

    def test_timeout_kill_result(self) -> None:
        result = SandboxResult(
            stdout="",
            stderr="",
            exit_code=None,
            duration_ms=10_000,
            timed_out=True,
        )
        assert result.timed_out is True
        assert result.exit_code is None

    def test_truncated_flag_set_explicitly(self) -> None:
        """The truncated flag is independent of stdout/stderr length;
        it's a structured signal even when reading the strings would
        also indicate truncation via the trailing marker."""
        result = SandboxResult(
            stdout="x" * 50_000,
            duration_ms=10,
            truncated=True,
        )
        assert result.truncated is True

    def test_exception_capture_result(self) -> None:
        traceback_text = (
            'Traceback (most recent call last):\n'
            '  File "<stdin>", line 1, in <module>\n'
            "ValueError: bad\n"
        )
        result = SandboxResult(
            stdout="",
            stderr=traceback_text,
            exit_code=1,
            duration_ms=20,
            exception_traceback=traceback_text,
        )
        assert result.exception_traceback == traceback_text
        assert result.exit_code == 1

    def test_escape_flag_independent_of_other_flags(self) -> None:
        """sandbox_escaped + timed_out can both be True (e.g., an
        infinite loop trying to read /etc/shadow)."""
        result = SandboxResult(
            duration_ms=10_000,
            timed_out=True,
            sandbox_escaped=True,
        )
        assert result.timed_out is True
        assert result.sandbox_escaped is True

    def test_stdout_at_50kb_exact_accepted(self) -> None:
        result = SandboxResult(stdout="x" * 50_000, duration_ms=10)
        assert len(result.stdout) == 50_000

    def test_stdout_over_50kb_rejected(self) -> None:
        """The schema rejects oversized strings; the executor MUST
        truncate before returning. Pinning here forces the executor's
        implementation to honor the cap."""
        with pytest.raises(ValidationError):
            SandboxResult(stdout="x" * 50_001, duration_ms=10)

    def test_stderr_over_50kb_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SandboxResult(stderr="x" * 50_001, duration_ms=10)

    def test_exception_traceback_over_20kb_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SandboxResult(
                duration_ms=10,
                exception_traceback="x" * 20_001,
            )

    def test_negative_duration_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SandboxResult(duration_ms=-1)

    def test_negative_memory_used_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SandboxResult(duration_ms=10, memory_used_mb=-1)

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SandboxResult(duration_ms=10, was_compiled=True)  # type: ignore[call-arg]

    def test_legacy_field_names_rejected(self) -> None:
        """The schema has been renamed per Pass 3d §E.3.2; old names
        should hard-fail to catch any caller still using them."""
        with pytest.raises(ValidationError):
            # runtime_ms was renamed to duration_ms
            SandboxResult(runtime_ms=10)  # type: ignore[call-arg]
        with pytest.raises(ValidationError):
            # timeout_killed was renamed to timed_out
            SandboxResult(duration_ms=10, timeout_killed=True)  # type: ignore[call-arg]

    def test_exit_code_can_be_explicit_nonzero(self) -> None:
        """sys.exit(2) → exit_code=2; a clean (non-killed) failure exit."""
        result = SandboxResult(duration_ms=20, exit_code=2)
        assert result.exit_code == 2
        assert result.timed_out is False
        assert result.oom_killed is False

    def test_node_language_accepted_in_result(self) -> None:
        """When the executor eventually supports Node.js, the result
        echoes language='node'. Schema accepts this today."""
        result = SandboxResult(duration_ms=10, language="node")
        assert result.language == "node"
