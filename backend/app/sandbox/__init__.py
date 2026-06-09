"""D14a — sandbox infrastructure for student code execution.

Process-based isolation (Path A) with resource limits, environment
scrubbing, and best-effort network restriction. Container-based
isolation (Path B) is documented as future work in
docs/followups/sandbox-path-b-container-isolation.md.

The package is consumed via:

  • app.agents.tools.agent_specific.sandbox.execute_in_sandbox
    (the @tool wrapper agents invoke through the canonical tool surface)
  • app.sandbox.executor.execute (direct call for tests)

Threat model and what's NOT mitigated by this package live in
app/sandbox/security.py's module docstring.

Public API:
  • execute(request: SandboxRequest) -> SandboxResult — main entry point
  • SandboxExecutionError, SandboxTimeoutError, SandboxResourceError —
    exception types raised when the executor itself can't run (distinct
    from "student code raised an exception" which is captured in the
    SandboxResult.exception_traceback field).
"""

from __future__ import annotations

from app.sandbox.exceptions import (
    SandboxError,
    SandboxExecutionError,
    SandboxResourceError,
    SandboxTimeoutError,
)


__all__ = [
    "SandboxError",
    "SandboxExecutionError",
    "SandboxResourceError",
    "SandboxTimeoutError",
]
