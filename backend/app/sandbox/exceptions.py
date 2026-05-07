"""Sandbox exception types.

Discriminates "the executor itself failed" (these exceptions) from
"the student's code raised" (captured in SandboxResult.exception_traceback).
The agent's tool surface should NEVER see these unless the sandbox
infrastructure itself is misconfigured — student-code failures land in
the SandboxResult, not in raised exceptions.
"""

from __future__ import annotations


class SandboxError(Exception):
    """Base for sandbox executor failures."""


class SandboxExecutionError(SandboxError):
    """The executor could not spawn or supervise the subprocess.

    Examples: temp file creation failed, asyncio.create_subprocess_exec
    raised before the subprocess started, kernel refused the rlimit
    setup. Distinct from "the subprocess started but timed out" (which
    sets timeout_killed=True in the result).
    """


class SandboxTimeoutError(SandboxError):
    """Reserved for infrastructure-level timeouts (e.g., subprocess
    cleanup hung). Per-execution timeouts ARE NOT raised — they manifest
    as SandboxResult(timeout_killed=True). This exception is for the
    case where even the kill failed."""


class SandboxResourceError(SandboxError):
    """The host environment doesn't support a primitive the executor
    requires (e.g., resource module unavailable, /tmp not writable)."""


__all__ = [
    "SandboxError",
    "SandboxExecutionError",
    "SandboxResourceError",
    "SandboxTimeoutError",
]
