"""D11.5 / Pass 3d §E.3.3 — run_tests tool.

Thin @tool wrapper around `app.sandbox.test_runner.run_tests`. Wraps
run_in_sandbox with a framework-specific test harness; pytest is
implemented in D11.5, unittest/jest/vitest raise NotImplementedError.

Permissions: execute:code_sandbox per Pass 3d spec — same as
run_in_sandbox, since run_tests is conceptually a sandbox use-case
specialization.
"""

from __future__ import annotations

from app.agents.primitives.tools import tool
from app.sandbox.test_runner import (
    RunTestsInput,
    RunTestsOutput,
    run_tests as _run_tests,
)


@tool(
    name="run_tests",
    description=(
        "Execute a test suite (pytest in D11.5) against student code "
        "in a resource-limited sandbox. Returns per-test pass/fail "
        "counts, individual test results, combined output, and a "
        "timed_out flag. Composes student code as a 'student' module "
        "the test code can import. Frameworks unittest/jest/vitest "
        "and language='node' are deferred and raise."
    ),
    input_schema=RunTestsInput,
    output_schema=RunTestsOutput,
    requires=("execute:code_sandbox",),
    cost_estimate=0.0,
    # 65s like run_in_sandbox — same dispatch boundary.
    timeout_seconds=65.0,
)
async def run_tests(args: RunTestsInput) -> RunTestsOutput:
    """Delegate to test_runner.run_tests; propagate NotImplementedError
    for deferred framework/language combinations."""
    return await _run_tests(args)


__all__ = ["run_tests"]
