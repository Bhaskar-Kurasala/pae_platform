"""D11.5 — sandbox agent-specific tools.

Per Pass 3d §E.3.2/§E.3.3, the two sandbox tools agents invoke when
they need to execute student code:

  • run_in_sandbox  — single-shot Python (or Node, when implemented)
                       execution with resource limits + capture.
  • run_tests       — wraps run_in_sandbox with a framework-specific
                       test harness (pytest in D11.5; unittest/jest/
                       vitest deferred).

Importing this package side-effect-registers both tools with
`app.agents.primitives.tools.registry`. Capability-gated: only agents
that declare the tool in their capability tool list AND have the
required permission (`execute:code_sandbox`) can invoke.
"""

from app.agents.tools.agent_specific.sandbox import (  # noqa: F401
    run_in_sandbox,
    run_tests,
)


__all__ = [
    "run_in_sandbox",
    "run_tests",
]
