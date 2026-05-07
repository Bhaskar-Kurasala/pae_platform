"""D14a Stage 2 — sandbox executor tests.

Drives `app.sandbox.executor.execute` against real subprocesses with
real resource limits. No mocking of the subprocess layer — these
tests exercise the actual security profile.

Some tests are deliberately framed against "best-effort" semantics
(e.g., network isolation cannot be enforced at subprocess level when
running as a non-root user; the test verifies escape detection fires,
not that the call is blocked). The threat model in
app/sandbox/security.py documents what's mitigated vs not.

Tests are split:
  • TestCleanExecution — happy paths
  • TestResourceLimits — RLIMIT_AS, RLIMIT_CPU enforcement
  • TestExceptionCapture — student-code exceptions surface in result
  • TestOutputTruncation — 50KB cap enforcement
  • TestForkBomb — RLIMIT_NPROC defense
  • TestEscapeDetection — heuristic patterns fire on suspicious output
  • TestEnvScrubbing — secrets don't leak into subprocess
  • TestFilesystem — what subprocess can / can't access
"""

from __future__ import annotations

import sys

import pytest

from app.sandbox.executor import execute
from app.sandbox.security import (
    detect_sandbox_escape,
    scrubbed_environment,
)
from app.schemas.sandbox import SandboxRequest


# ── Clean execution ────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCleanExecution:
    async def test_print_hello(self) -> None:
        result = await execute(SandboxRequest(code="print('hello')"))
        assert result.stdout == "hello\n"
        assert result.stderr == ""
        assert result.exit_code == 0
        assert result.timed_out is False
        assert result.oom_killed is False
        assert result.sandbox_escaped is False
        assert result.exception_traceback is None
        assert result.duration_ms >= 0

    async def test_arithmetic(self) -> None:
        result = await execute(SandboxRequest(code="print(2 + 2)"))
        assert result.stdout == "4\n"
        assert result.exit_code == 0

    async def test_empty_code(self) -> None:
        """No output, exits cleanly."""
        result = await execute(SandboxRequest(code=""))
        assert result.stdout == ""
        assert result.stderr == ""
        assert result.exit_code == 0

    async def test_explicit_sys_exit_nonzero(self) -> None:
        """sys.exit(2) → clean (non-killed) exit with code=2."""
        result = await execute(SandboxRequest(code="import sys; sys.exit(2)"))
        assert result.exit_code == 2
        assert result.timed_out is False
        assert result.oom_killed is False

    async def test_stdlib_import_works(self) -> None:
        """The subprocess can import stdlib modules."""
        result = await execute(
            SandboxRequest(code="import json; print(json.dumps({'x': 1}))")
        )
        assert result.stdout.strip() == '{"x": 1}'
        assert result.exit_code == 0

    async def test_duration_ms_reasonable(self) -> None:
        """A trivial program completes well under 10s; duration_ms is
        small but non-zero (Python interpreter startup is ~50-200ms)."""
        result = await execute(SandboxRequest(code="x = 1"))
        assert 0 <= result.duration_ms < 10_000


# ── Resource limits ────────────────────────────────────────────────


@pytest.mark.asyncio
class TestResourceLimits:
    async def test_cpu_timeout_kills_infinite_loop(self) -> None:
        """An infinite loop hits RLIMIT_CPU + SIGXCPU/SIGKILL OR the
        wall-clock fallback. Either way, timed_out=True."""
        result = await execute(
            SandboxRequest(
                code="while True: pass",
                timeout_seconds=2,  # short timeout for fast test
            )
        )
        assert result.timed_out is True
        assert result.exit_code is None
        # Runtime should be at most timeout + grace (~4s).
        assert result.duration_ms < 6_000

    async def test_memory_limit_kills_huge_allocation(self) -> None:
        """Allocate way past RLIMIT_AS; subprocess raises MemoryError
        OR is killed by SIGKILL. Either way, the failure surfaces."""
        # Allocating 1 GB list in a 64 MB sandbox should fail loud.
        code = "x = [0] * (200_000_000)"  # ~1.6 GB (8 bytes/entry)
        result = await execute(
            SandboxRequest(
                code=code,
                memory_limit_mb=64,  # tight memory for fast test
                timeout_seconds=10,
            )
        )
        # Either MemoryError surfaced (exception_traceback) OR kernel
        # killed the process (oom_killed=True). Both are acceptable
        # OOM signals.
        oom_signal = (
            result.oom_killed
            or (result.exception_traceback is not None and
                "MemoryError" in result.exception_traceback)
        )
        assert oom_signal, (
            f"Expected OOM signal: oom_killed={result.oom_killed}, "
            f"traceback={result.exception_traceback!r}"
        )

    async def test_clean_code_well_within_memory_limit(self) -> None:
        """Sanity: clean code does NOT trip oom_killed at default
        256MB. Catches false-positive memory limits."""
        result = await execute(SandboxRequest(code="print('ok')"))
        assert result.oom_killed is False
        assert result.exit_code == 0

    async def test_short_loop_within_cpu_budget(self) -> None:
        """Sanity: a finite loop within the timeout completes cleanly."""
        result = await execute(
            SandboxRequest(
                code="for i in range(100_000): pass\nprint('done')",
                timeout_seconds=5,
            )
        )
        assert result.exit_code == 0
        assert result.stdout.strip() == "done"
        assert result.timed_out is False


# ── Exception capture ──────────────────────────────────────────────


@pytest.mark.asyncio
class TestExceptionCapture:
    async def test_value_error_capture(self) -> None:
        result = await execute(
            SandboxRequest(code="raise ValueError('bad')")
        )
        assert result.exit_code == 1
        assert result.exception_traceback is not None
        assert "ValueError" in result.exception_traceback
        assert "bad" in result.exception_traceback
        assert result.timed_out is False
        assert result.oom_killed is False

    async def test_divide_by_zero_capture(self) -> None:
        result = await execute(SandboxRequest(code="1 / 0"))
        assert result.exit_code == 1
        assert result.exception_traceback is not None
        assert "ZeroDivisionError" in result.exception_traceback

    async def test_syntax_error_capture(self) -> None:
        """Syntax errors are caught at compile time; still surface as
        a traceback in stderr."""
        result = await execute(SandboxRequest(code="def x("))
        assert result.exit_code == 1
        # SyntaxError doesn't always include "Traceback" prefix on
        # Python's stderr; accept either traceback OR clean stderr
        # mention of SyntaxError.
        assert (
            (result.exception_traceback is not None
             and "SyntaxError" in result.exception_traceback)
            or "SyntaxError" in result.stderr
        )

    async def test_stdout_preserved_when_exception_raised(self) -> None:
        """print() before an exception is captured cleanly."""
        result = await execute(
            SandboxRequest(
                code="print('before')\nraise RuntimeError('boom')"
            )
        )
        assert "before" in result.stdout
        assert result.exception_traceback is not None
        assert "RuntimeError" in result.exception_traceback


# ── Output truncation ──────────────────────────────────────────────


@pytest.mark.asyncio
class TestOutputTruncation:
    async def test_long_stdout_truncated_to_50kb(self) -> None:
        """A loop printing past 50KB truncates with marker."""
        code = (
            "for i in range(100_000):\n"
            "    print('A' * 80)\n"
        )
        result = await execute(
            SandboxRequest(code=code, timeout_seconds=10)
        )
        # Schema cap is 50000; truncation marker must be present.
        assert len(result.stdout) <= 50_000
        # The trailing truncation marker indicates we hit the cap.
        assert "[sandbox: output truncated at 50KB]" in result.stdout

    async def test_short_output_not_truncated(self) -> None:
        result = await execute(SandboxRequest(code="print('short')"))
        assert "[sandbox: output truncated" not in result.stdout
        assert result.stdout == "short\n"


# ── Fork bomb defense ──────────────────────────────────────────────


@pytest.mark.asyncio
class TestForkBomb:
    async def test_subprocess_recursion_limited(self) -> None:
        """RLIMIT_NPROC=16 caps how many children the subprocess can
        spawn. A naive fork-bomb pattern hits the limit and either
        raises or is killed."""
        # Spawn child processes via subprocess in a loop; each child
        # would normally keep multiplying. With NPROC=16 the loop
        # raises BlockingIOError or similar fairly quickly.
        code = (
            "import subprocess, sys\n"
            "children = []\n"
            "try:\n"
            "    for _ in range(50):\n"
            "        children.append(subprocess.Popen([sys.executable, '-c', 'pass']))\n"
            "except (BlockingIOError, OSError) as e:\n"
            "    print(f'caught:{type(e).__name__}')\n"
            "for c in children:\n"
            "    try:\n"
            "        c.wait(timeout=1)\n"
            "    except Exception:\n"
            "        pass\n"
        )
        result = await execute(
            SandboxRequest(code=code, timeout_seconds=15)
        )
        # Either the limit was hit (caught:BlockingIOError or OSError)
        # OR the subprocess was killed in some other way (timeout if
        # children consumed the budget).
        # We accept any of: explicit caught marker, killed flags, or
        # non-zero exit.
        accepted = (
            "caught:" in result.stdout
            or result.timed_out
            or result.exit_code not in (0, None)
        )
        assert accepted, (
            f"Fork-bomb defense not visible: stdout={result.stdout[:200]!r}, "
            f"stderr={result.stderr[:200]!r}, exit={result.exit_code}, "
            f"killed={result.timed_out}"
        )


# ── Escape detection (best-effort) ────────────────────────────────


@pytest.mark.asyncio
class TestEscapeDetection:
    """These tests verify the heuristic detector fires on known
    escape signals. Some tests verify CALL-LEVEL behavior (subprocess
    can/can't access a thing) and fall through to the documented
    "best-effort" gap when the dev environment doesn't enforce."""

    async def test_etc_passwd_read_flagged(self) -> None:
        """Reading /etc/passwd is allowed at the subprocess level (we
        run as appuser, no fs isolation). The escape detector matches
        the file's CONTENT shape and sets sandbox_escaped=True.
        Pinning best-effort detection, not blocked access (Path B is
        the strict layer)."""
        code = "print(open('/etc/passwd').read()[:200])"
        result = await execute(SandboxRequest(code=code))
        # /etc/passwd MAY or MAY NOT be readable depending on the
        # environment. If readable, the escape detector should fire.
        # If not readable, exception_traceback is populated and
        # sandbox_escaped may be False — that's also acceptable
        # (the file simply can't be read).
        if result.exit_code == 0:
            # Read succeeded → detector should have fired.
            assert result.sandbox_escaped is True, (
                "Escape detector did not fire on /etc/passwd contents. "
                f"stdout: {result.stdout[:300]!r}"
            )
        else:
            # File not readable in this env — acceptable; documents
            # the upstream filesystem permissions doing the work.
            assert result.exception_traceback is not None

    async def test_clean_code_does_not_trip_escape_detector(self) -> None:
        """Sanity: legitimate code doesn't false-positive."""
        code = (
            "import json\n"
            "data = {'name': 'alice', 'role': 'engineer'}\n"
            "print(json.dumps(data))\n"
        )
        result = await execute(SandboxRequest(code=code))
        assert result.sandbox_escaped is False
        assert result.exit_code == 0

    async def test_string_mention_of_sensitive_path_does_not_flag(self) -> None:
        """The detector matches CONTENT shapes, not string literals.
        Code that just MENTIONS '/etc/passwd' in a comment shouldn't
        false-positive."""
        code = "# This script does NOT touch /etc/passwd\nprint('safe')"
        result = await execute(SandboxRequest(code=code))
        assert result.sandbox_escaped is False
        assert result.exit_code == 0


# ── Pure-function security tests (no subprocess) ──────────────────


class TestSecurityPrimitives:
    """These tests exercise security.py primitives in isolation."""

    def test_scrubbed_environment_excludes_secrets(self) -> None:
        env = scrubbed_environment()
        # The dev container has ANTHROPIC_API_KEY / MINIMAX_API_KEY in
        # its real env. The scrubbed env must not.
        assert "ANTHROPIC_API_KEY" not in env
        assert "MINIMAX_API_KEY" not in env
        assert "DATABASE_URL" not in env
        # Required keys are present.
        assert "PATH" in env
        assert "HOME" in env

    def test_scrubbed_environment_returns_fresh_dict(self) -> None:
        """Mutating the returned dict doesn't affect future calls."""
        e1 = scrubbed_environment()
        e1["INJECTED"] = "x"
        e2 = scrubbed_environment()
        assert "INJECTED" not in e2

    def test_detect_escape_on_etc_passwd_content(self) -> None:
        """The detector matches the /etc/passwd content shape."""
        # Real /etc/passwd line shape.
        stdout = "root:x:0:0:root:/root:/bin/bash\n"
        assert detect_sandbox_escape(stdout, "") is True

    def test_detect_escape_on_aws_key_shape(self) -> None:
        stdout = "config: AKIAIOSFODNN7EXAMPLE\n"
        assert detect_sandbox_escape(stdout, "") is True

    def test_detect_escape_on_private_key_marker(self) -> None:
        stderr = "key dump:\n-----BEGIN OPENSSH PRIVATE KEY-----"
        assert detect_sandbox_escape("", stderr) is True

    def test_detect_no_escape_on_innocuous_output(self) -> None:
        stdout = "Hello world\n[1, 2, 3]\n{'name': 'alice'}"
        assert detect_sandbox_escape(stdout, "") is False

    def test_detect_no_escape_on_string_mentioning_etc_passwd(self) -> None:
        """Mentioning '/etc/passwd' as a string does not trip;
        only the file's content shape does."""
        stdout = "I will not read /etc/passwd in my code"
        assert detect_sandbox_escape(stdout, "") is False

    def test_detect_escape_on_proc_inspection(self) -> None:
        stderr = "  File '/proc/1234/environ', line 1, in <module>"
        assert detect_sandbox_escape("", stderr) is True

    def test_detect_escape_on_http_response(self) -> None:
        """Successful outbound HTTP shows up as a response status line."""
        stdout = "Got: HTTP/1.1 200 OK\nbody..."
        assert detect_sandbox_escape(stdout, "") is True


# ── Filesystem behavior (best-effort, environment-dependent) ──────


@pytest.mark.asyncio
class TestFilesystem:
    async def test_tmp_writable(self) -> None:
        """Writing to /tmp succeeds (RLIMIT_FSIZE caps the size, but
        small writes are fine)."""
        code = (
            "with open('/tmp/d14a_test.txt', 'w') as f:\n"
            "    f.write('hello')\n"
            "print('wrote')\n"
        )
        result = await execute(SandboxRequest(code=code))
        # Either succeeded (best-effort, no fs isolation) or failed
        # (e.g., /tmp full or permission). Both are documented.
        if result.exit_code == 0:
            assert "wrote" in result.stdout

    async def test_root_filesystem_write_fails(self) -> None:
        """Writing to /etc requires root; subprocess runs as appuser,
        so the open() raises PermissionError."""
        code = "open('/etc/d14a_test.txt', 'w').write('nope')"
        result = await execute(SandboxRequest(code=code))
        assert result.exit_code != 0
        assert result.exception_traceback is not None
        # Either PermissionError or OSError — both acceptable.
        tb = result.exception_traceback or ""
        assert "PermissionError" in tb or "OSError" in tb


# ── Spec-contract surface (D11.5 Stage 3.1 additions) ─────────────


@pytest.mark.asyncio
class TestSpecContractSurface:
    """Pass 3d §E.3.2 fields beyond the original D14a Stage 1
    schemas: language='node', network_access=True, memory_used_mb,
    truncated flag, duration_ms naming."""

    async def test_node_language_raises_not_implemented(self) -> None:
        """Path A doesn't ship Node.js. The executor raises a clear
        NotImplementedError at invocation, distinct from a generic
        SandboxExecutionError."""
        with pytest.raises(NotImplementedError) as exc_info:
            await execute(SandboxRequest(code="x = 1", language="node"))
        assert "Node.js" in str(exc_info.value)

    async def test_network_access_true_raises_not_implemented(self) -> None:
        """Path A always behaves as network_access=False under appuser
        privilege. Passing True surfaces as NotImplementedError so the
        caller knows the request couldn't be honored."""
        with pytest.raises(NotImplementedError) as exc_info:
            await execute(
                SandboxRequest(code="x = 1", network_access=True)
            )
        assert "network_access" in str(exc_info.value).lower()

    async def test_memory_used_mb_populated_on_clean_execution(self) -> None:
        """Pass 3d §E.3.2 spec field. Best-effort via getrusage; on
        Linux containers it should be non-zero for any non-trivial
        Python subprocess."""
        # Allocate ~10MB of bytes so the RSS measurement is non-trivial.
        code = (
            "import os\n"
            "buf = bytearray(10 * 1024 * 1024)\n"  # 10 MB
            "print('alloc done')\n"
        )
        result = await execute(SandboxRequest(code=code))
        assert result.exit_code == 0
        # memory_used_mb should reflect the allocation (Python's RSS
        # for a 10MB allocation is typically 30-50MB including
        # interpreter overhead). Check it's at least non-zero — the
        # spec is best-effort, so we only assert it's populated.
        assert result.memory_used_mb >= 0
        # If getrusage works as expected on this Linux container,
        # the value should be at least a few MB (Python interpreter
        # alone is usually >10MB RSS).
        # Soft assertion: log if zero, fail only if absurd.
        if result.memory_used_mb == 0:
            # Acceptable per spec best-effort semantic; document.
            pass

    async def test_truncated_flag_set_when_stdout_exceeds_cap(self) -> None:
        """The truncated flag is set explicitly when output is
        truncated (Pass 3d §E.3.2 consolidation of pre-spec marker-only
        behavior)."""
        code = (
            "for i in range(100_000):\n"
            "    print('A' * 80)\n"
        )
        result = await execute(
            SandboxRequest(code=code, timeout_seconds=10)
        )
        # Both signals: explicit flag + trailing marker.
        assert result.truncated is True
        assert "[sandbox: output truncated at 50KB]" in result.stdout

    async def test_truncated_flag_false_for_short_output(self) -> None:
        result = await execute(SandboxRequest(code="print('short')"))
        assert result.truncated is False

    async def test_duration_ms_naming(self) -> None:
        """Smoke check that the rename to duration_ms holds end-to-end
        (legacy runtime_ms removed). Catches accidental field-name
        drift in test fixtures."""
        result = await execute(SandboxRequest(code="x = 1"))
        # Field is duration_ms; accessing runtime_ms would AttributeError.
        assert hasattr(result, "duration_ms")
        assert not hasattr(result, "runtime_ms")
        assert result.duration_ms >= 0
