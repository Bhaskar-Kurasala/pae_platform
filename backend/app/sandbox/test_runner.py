"""D11.5 — Pass 3d §E.3.3 run_tests wrapper.

Composes student code + test code into a single executable script
and invokes the sandbox executor under the hood. Parses framework-
specific output to populate per-test results.

D11.5 implements Python pytest fully. Other frameworks
(unittest, jest, vitest) raise NotImplementedError at the framework
dispatch layer — they're deferred to a follow-up
(docs/followups/sandbox-test-framework-extension.md).

Public API:
  • run_tests(args: RunTestsInput) -> RunTestsOutput
  • RunTestsInput, RunTestsOutput, TestResult — schema types

Implementation strategy for pytest:
  1. Write student code to a tempfile module.
  2. Write test code to a tempfile module that imports the student module.
  3. Inject a small sys.path manipulation so the test can import.
  4. Use pytest's `--tb=short -p no:cacheprovider --json-report` if
     available, OR parse the standard pytest output for pass/fail
     counts. (D11.5 uses output-line parsing; pytest-json-report is a
     dependency we'd need to add. Keeping the dependency footprint
     small for now.)
  5. Combine into one Python script that pytest can run via
     `pytest -x test_file.py`.

Fallback: when pytest's structured output isn't available, we extract
counts from the canonical pytest summary line ("=== 3 passed, 1
failed in 0.45s ===") and surface them. Per-test detail (TestResult
list) is populated when pytest reports each test by line; otherwise
the list is best-effort.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.sandbox.executor import execute
from app.schemas.sandbox import SandboxRequest


class SandboxTestResult(BaseModel):
    """Per-test result. Populated when the framework's output reports
    each test individually."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=300)
    passed: bool
    error: str | None = Field(default=None, max_length=2000)
    duration_ms: int = Field(default=0, ge=0)


class RunTestsInput(BaseModel):
    """Pass 3d §E.3.3 RunTestsInput."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(
        max_length=100_000,
        description="Student code under test.",
    )
    test_code: str = Field(
        max_length=50_000,
        description=(
            "Test code that exercises the student code. For pytest, "
            "this is a Python module containing test_* functions."
        ),
    )
    language: Literal["python", "node"] = Field(default="python")
    framework: Literal["pytest", "unittest", "jest", "vitest"] = Field(
        default="pytest",
        description=(
            "Test framework. D11.5 implements pytest only; other "
            "frameworks raise NotImplementedError. See "
            "docs/followups/sandbox-test-framework-extension.md."
        ),
    )
    timeout_seconds: int = Field(default=30, ge=1, le=60)
    memory_limit_mb: int = Field(default=256, ge=64, le=1024)


class RunTestsOutput(BaseModel):
    """Pass 3d §E.3.3 RunTestsOutput."""

    model_config = ConfigDict(extra="forbid")

    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    errors: int = Field(ge=0)
    test_results: list[SandboxTestResult] = Field(default_factory=list)
    output: str = Field(
        default="",
        max_length=50_000,
        description="Combined stdout/stderr from the test run.",
    )
    timed_out: bool = Field(
        default=False,
        description=(
            "True when the test run exceeded its timeout. Propagated "
            "from the underlying SandboxResult."
        ),
    )


# ── Framework dispatch ────────────────────────────────────────────


async def run_tests(args: RunTestsInput) -> RunTestsOutput:
    """Top-level dispatch. Routes to the appropriate framework runner
    or raises NotImplementedError for deferred frameworks."""
    if args.language == "node":
        raise NotImplementedError(
            "Node.js test execution not yet implemented; D11.5 ships "
            "Python only. See "
            "docs/followups/sandbox-language-extension-node.md."
        )

    if args.framework == "pytest":
        return await _run_pytest(args)
    if args.framework in ("unittest", "jest", "vitest"):
        raise NotImplementedError(
            f"Framework {args.framework!r} is deferred (D11.5 ships "
            "pytest only). See "
            "docs/followups/sandbox-test-framework-extension.md."
        )
    raise NotImplementedError(
        f"Unknown framework {args.framework!r}."
    )


# ── pytest runner ─────────────────────────────────────────────────


# Composed Python script that:
#   1. Builds a synthetic `student` module from the student code so
#      the test's `from student import ...` resolves.
#   2. Writes the test code to /tmp/test_d11_5_<pid>.py so pytest can
#      discover and run it as a normal test file. Using `python -c`
#      mode (which the sandbox executor uses) leaves __file__ undefined,
#      so we can't point pytest at "this script"; the tempfile workaround
#      gives pytest something to load. The cwd is /tmp per the executor's
#      cwd setting, so the file is bounded.
#   3. Invokes pytest pointing at the tempfile.
_PYTEST_HARNESS_TEMPLATE = """\
# D11.5 pytest harness — composed from RunTestsInput.
import os
import sys
import types

_student_module = types.ModuleType('student')
_student_module.__file__ = '<student>'
exec(compile({student_code!r}, '<student>', 'exec'), _student_module.__dict__)
sys.modules['student'] = _student_module

_TEST_CODE = {test_code!r}

# Write test code to a /tmp file so pytest can discover it. Filename
# starts with 'test_' so pytest's default collector picks it up.
_test_path = f'/tmp/test_d11_5_{{os.getpid()}}.py'
with open(_test_path, 'w') as _f:
    _f.write(_TEST_CODE)

import pytest as _pytest
sys.exit(_pytest.main([_test_path, '-p', 'no:cacheprovider', '--tb=short', '-v']))
"""


# Pytest summary line patterns. These regex match canonical pytest
# output so we don't need pytest-json-report as a dep.
_SUMMARY_PASSED_RE = re.compile(r"(\d+) passed")
_SUMMARY_FAILED_RE = re.compile(r"(\d+) failed")
_SUMMARY_ERROR_RE = re.compile(r"(\d+) error")

# Per-test outcome lines in pytest -v output:
#   path/to/file.py::test_name PASSED  [ 50%]
#   path/to/file.py::test_name FAILED  [100%]
_PER_TEST_RE = re.compile(
    r"^[^:]+::([\w_\[\]<>.-]+)\s+(PASSED|FAILED|ERROR|SKIPPED)",
    re.MULTILINE,
)


async def _run_pytest(args: RunTestsInput) -> RunTestsOutput:
    """Compose code + test_code into a pytest harness, run in sandbox,
    parse output."""
    composed = _PYTEST_HARNESS_TEMPLATE.format(
        student_code=args.code,
        test_code=args.test_code,
    )

    sandbox_request = SandboxRequest(
        code=composed,
        language="python",
        timeout_seconds=args.timeout_seconds,
        memory_limit_mb=args.memory_limit_mb,
    )
    sandbox_result = await execute(sandbox_request)

    combined_output = sandbox_result.stdout + sandbox_result.stderr

    # Parse pytest output for counts.
    passed = _extract_count(_SUMMARY_PASSED_RE, combined_output)
    failed = _extract_count(_SUMMARY_FAILED_RE, combined_output)
    errors = _extract_count(_SUMMARY_ERROR_RE, combined_output)

    # Per-test results from the verbose lines.
    test_results: list[SandboxTestResult] = []
    for match in _PER_TEST_RE.finditer(combined_output):
        name = match.group(1)
        outcome = match.group(2)
        test_results.append(
            SandboxTestResult(
                name=name[:300],
                passed=(outcome == "PASSED"),
                error=outcome if outcome != "PASSED" else None,
                duration_ms=0,  # pytest -v doesn't expose per-test ms
            )
        )

    return RunTestsOutput(
        passed=passed,
        failed=failed,
        errors=errors,
        test_results=test_results,
        output=combined_output[:50_000],
        timed_out=sandbox_result.timed_out,
    )


def _extract_count(pattern: re.Pattern[str], text: str) -> int:
    """Extract the last integer match from pytest's summary line.

    pytest may emit multiple lines mentioning "passed" (e.g., during
    test collection). The summary line is canonically the last one,
    so we take the last match.
    """
    matches = pattern.findall(text)
    if not matches:
        return 0
    try:
        return int(matches[-1])
    except (ValueError, IndexError):
        return 0


__all__ = [
    "RunTestsInput",
    "RunTestsOutput",
    "SandboxTestResult",
    "run_tests",
]
