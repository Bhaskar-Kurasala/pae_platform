"""Sandbox executor — subprocess-based Python code execution.

Public entry point: `execute(request: SandboxRequest) -> SandboxResult`.

Implementation shape:
  • asyncio.create_subprocess_exec spawns Python with -I (isolated mode)
    + -B (don't write bytecode) + -c <student code>.
  • preexec_fn applies rlimits per app/sandbox/security.py.
  • subprocess env is the scrubbed minimal env (PATH + HOME + UTF-8).
  • stdout/stderr captured separately, truncated to 50KB each (the
    SandboxResult schema cap; oversize would raise ValidationError so
    we truncate eagerly with a marker line).
  • Wall-clock fallback timeout via asyncio.wait_for at
    timeout_seconds + 2 (kernel kill via RLIMIT_CPU is the primary;
    this catches the case where the kernel kill is slow).
  • Exit code captured; killed-by-signal detected via subprocess
    returncode (negative = signal, abs value = signal number).
  • Exception traceback extracted from stderr by matching the
    canonical "Traceback (most recent call last):" prefix.

Per-rlimit kill detection:
  • RLIMIT_CPU sends SIGXCPU (24); if subprocess didn't catch it,
    SIGKILL (9) follows at the hard limit.
  • RLIMIT_AS makes mmap/brk return ENOMEM; Python typically raises
    MemoryError (so it manifests as exception_traceback). Sometimes
    the kernel sends SIGKILL when the process can't recover; we map
    SIGKILL with no other signal context to oom_killed.
  • Wall-clock timeout via asyncio.wait_for sends SIGTERM, then SIGKILL.
"""

from __future__ import annotations

import asyncio
import os
import re
import resource
import signal
import sys
import time

import structlog

from app.sandbox.exceptions import SandboxExecutionError
from app.sandbox.security import (
    detect_sandbox_escape,
    make_resource_limit_setter,
    scrubbed_environment,
)
from app.schemas.sandbox import SandboxRequest, SandboxResult

log = structlog.get_logger().bind(layer="sandbox.executor")


# Truncation marker appended to stdout/stderr when output exceeded the
# 50KB cap. Marker is short and identifiable so consumers can detect
# truncation deterministically.
_TRUNCATE_MARKER = "\n…[sandbox: output truncated at 50KB]"
_OUTPUT_CAP_BYTES = 50_000

# Wall-clock fallback is the asyncio.wait_for ceiling that fires when
# RLIMIT_CPU's kernel kill is slow. +2 is enough headroom that we
# don't race the kernel; it's not so large that a hung subprocess
# delays the agent meaningfully.
_WALL_CLOCK_GRACE_SECONDS = 2

# Match Python's traceback header anywhere in stderr. The traceback
# may be prefixed by other stderr noise (e.g., warnings) so we don't
# anchor at start of string.
_TRACEBACK_HEADER_RE = re.compile(
    r"Traceback \(most recent call last\):.*",
    re.DOTALL,
)


async def execute(request: SandboxRequest) -> SandboxResult:
    """Execute `request.code` in a resource-limited Python subprocess.

    Returns a `SandboxResult` capturing stdout, stderr, exit code,
    duration, memory used, and failure-mode flags. Exceptions raised
    in student code are CAPTURED (in `exception_traceback`), not
    re-raised; this function only raises `SandboxExecutionError` for
    infrastructure-level failures (e.g., subprocess spawn failed) and
    `NotImplementedError` for spec features Path A doesn't support
    (Node.js, network_access=True).
    """
    if request.language == "node":
        raise NotImplementedError(
            "Node.js execution not yet implemented; D11.5 ships Python "
            "only. See docs/followups/sandbox-language-extension-node.md."
        )
    if request.language != "python":
        raise SandboxExecutionError(
            f"Sandbox does not support language={request.language!r}."
        )
    if request.network_access:
        raise NotImplementedError(
            "network_access=True not yet implemented; Path A always "
            "behaves as network_access=False under appuser privilege. "
            "Container-level enforcement (Path B / E2B) is the proper "
            "layer. See "
            "docs/followups/sandbox-path-b-e2b-or-container.md."
        )

    preexec = make_resource_limit_setter(
        memory_mb=request.memory_limit_mb,
        cpu_seconds=request.timeout_seconds,
    )
    env = scrubbed_environment()

    # Use Python's isolated mode (-I) which:
    #   • disables PYTHON* environment variable processing (defense-
    #     in-depth: the subprocess can't be influenced by env vars
    #     even if our scrubber misses one)
    #   • uses safe sys.path (no current working directory injection)
    # -B disables bytecode (.pyc) writes; redundant with
    # PYTHONDONTWRITEBYTECODE but belt-and-suspenders.
    cmd = [sys.executable, "-I", "-B", "-c", request.code]

    log.debug(
        "sandbox.execute.starting",
        language=request.language,
        timeout_seconds=request.timeout_seconds,
        memory_limit_mb=request.memory_limit_mb,
        code_length=len(request.code),
    )

    start = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            preexec_fn=preexec,
            # Restrict cwd to /tmp so student code's relative-path
            # opens land somewhere bounded.
            cwd="/tmp",
        )
    except Exception as exc:  # noqa: BLE001
        raise SandboxExecutionError(
            f"Failed to spawn sandbox subprocess: {type(exc).__name__}: {exc}"
        ) from exc

    timed_out_via_walltime = False
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=request.timeout_seconds + _WALL_CLOCK_GRACE_SECONDS,
        )
    except asyncio.TimeoutError:
        timed_out_via_walltime = True
        # Kill the subprocess; communicate() may still return partial
        # output we want to capture for diagnostics.
        try:
            proc.kill()
        except ProcessLookupError:
            pass  # Already dead; kernel beat us.
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=2.0,
            )
        except asyncio.TimeoutError:
            stdout_bytes, stderr_bytes = b"", b""

    duration_ms = int((time.monotonic() - start) * 1000)

    # Capture peak memory usage for child processes via getrusage.
    # ru_maxrss on Linux is in KB; on macOS it's in bytes. The container
    # is Linux. RUSAGE_CHILDREN aggregates across all reaped children
    # since process start, so for a single-shot subprocess this is the
    # peak RSS of THIS subprocess (no other children at this point in
    # the parent's lifetime ... unless tests run in parallel and reuse
    # the parent process). Best-effort per Pass 3d §E.3.2 spec.
    memory_used_mb = 0
    try:
        rusage = resource.getrusage(resource.RUSAGE_CHILDREN)
        # ru_maxrss is in KB on Linux. Convert to MB; floor at 0.
        memory_used_mb = max(0, rusage.ru_maxrss // 1024)
    except Exception:  # noqa: BLE001
        pass  # leave at 0 per spec best-effort semantic

    # Decode + truncate stdout/stderr; track truncation flag.
    stdout, stdout_truncated = _decode_and_truncate(stdout_bytes)
    stderr, stderr_truncated = _decode_and_truncate(stderr_bytes)
    truncated = stdout_truncated or stderr_truncated

    # Determine exit_code + kill flags.
    returncode = proc.returncode
    exit_code: int | None
    timed_out = False
    oom_killed = False

    if returncode is None:
        exit_code = None
    elif returncode < 0:
        # Killed by signal: returncode = -signal_number.
        signum = -returncode
        exit_code = None
        if timed_out_via_walltime or signum in (signal.SIGXCPU, signal.SIGTERM):
            timed_out = True
        elif signum == signal.SIGKILL:
            # SIGKILL with no other context → could be OOM (kernel
            # killer) OR walltime fallback's escalated SIGKILL. The
            # walltime fallback already set timed_out if it ran;
            # if not, treat SIGKILL as OOM.
            if timed_out_via_walltime:
                timed_out = True
            else:
                oom_killed = True
    else:
        exit_code = returncode

    # Promote walltime-fallback to timed_out even if the proc had
    # already exited cleanly mid-cleanup (rare race).
    if timed_out_via_walltime:
        timed_out = True

    # Extract traceback from stderr if student code raised.
    exception_traceback: str | None = None
    tb_match = _TRACEBACK_HEADER_RE.search(stderr)
    if tb_match is not None:
        # Cap at the schema's 20KB limit.
        exception_traceback = tb_match.group(0)[:20_000]

    sandbox_escaped = detect_sandbox_escape(stdout, stderr)

    log.debug(
        "sandbox.execute.complete",
        duration_ms=duration_ms,
        memory_used_mb=memory_used_mb,
        exit_code=exit_code,
        timed_out=timed_out,
        oom_killed=oom_killed,
        sandbox_escaped=sandbox_escaped,
        truncated=truncated,
        had_exception=exception_traceback is not None,
    )

    return SandboxResult(
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        duration_ms=duration_ms,
        memory_used_mb=memory_used_mb,
        timed_out=timed_out,
        truncated=truncated,
        oom_killed=oom_killed,
        sandbox_escaped=sandbox_escaped,
        exception_traceback=exception_traceback,
        language=request.language,
    )


def _decode_and_truncate(raw: bytes) -> tuple[str, bool]:
    """Decode bytes as UTF-8 (replace errors) and truncate at the cap.

    Returns (text, was_truncated). The cap is checked on the DECODED
    string length, not byte length, because the schema cap is on str
    length. Truncation appends a marker so consumers can detect it
    deterministically (in addition to the structured truncated flag).
    """
    text = raw.decode("utf-8", errors="replace")
    if len(text) <= _OUTPUT_CAP_BYTES:
        return text, False
    # Reserve room for the marker so the final string fits under the cap.
    head_len = _OUTPUT_CAP_BYTES - len(_TRUNCATE_MARKER)
    return text[:head_len] + _TRUNCATE_MARKER, True


__all__ = ["execute"]
