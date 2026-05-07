"""D11.5 / Pass 3d §E.3.2 — run_in_sandbox tool.

Thin @tool wrapper around `app.sandbox.executor.execute`. The tool
surface delegates straight to the executor; the work of resource
isolation and security primitives lives in app/sandbox/.

Permissions: execute:code_sandbox per Pass 3d spec.

Capability gating: agents must include this tool in their capability's
tool list to invoke. The executor itself imposes the resource limits
and security profile.
"""

from __future__ import annotations

from app.agents.primitives.tools import tool
from app.sandbox.executor import execute as _execute
from app.schemas.sandbox import SandboxRequest, SandboxResult


@tool(
    name="run_in_sandbox",
    description=(
        "Execute Python code in a resource-limited sandbox. Returns "
        "stdout, stderr, exit code, duration, memory used, plus "
        "failure-mode flags (timed_out, oom_killed, sandbox_escaped, "
        "truncated). Network access is NOT supported in the current "
        "Path A implementation; passing network_access=True raises. "
        "Node.js execution is also not yet implemented."
    ),
    input_schema=SandboxRequest,
    output_schema=SandboxResult,
    requires=("execute:code_sandbox",),
    cost_estimate=0.0,
    # Tool-call timeout is the upper bound at the tool surface; the
    # actual sandbox execution has its own timeout_seconds field.
    # 65s = 60s spec ceiling + 5s headroom for tool/audit overhead.
    timeout_seconds=65.0,
)
async def run_in_sandbox(args: SandboxRequest) -> SandboxResult:
    """Delegate to the sandbox executor and return the structured
    result. Exceptions from the executor (NotImplementedError for
    Node.js or network_access=True; SandboxExecutionError for spawn
    failures) propagate to the caller."""
    return await _execute(args)


__all__ = ["run_in_sandbox"]
