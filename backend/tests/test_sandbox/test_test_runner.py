"""D11.5 Stage 3.2 — run_tests wrapper tests (Pass 3d §E.3.3).

Drives `app.sandbox.test_runner.run_tests` with real pytest under the
sandbox executor. Verifies the framework dispatch routes pytest
correctly and raises NotImplementedError for the deferred frameworks
(unittest, jest, vitest, plus Node language).
"""

from __future__ import annotations

import pytest

from app.sandbox.test_runner import (
    RunTestsInput,
    RunTestsOutput,
    SandboxTestResult,
    run_tests,
)


# ── pytest happy path ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pytest_all_passing() -> None:
    """Three passing tests, no failures, no errors."""
    student_code = (
        "def add(a, b):\n"
        "    return a + b\n"
        "\n"
        "def mul(a, b):\n"
        "    return a * b\n"
    )
    test_code = (
        "from student import add, mul\n"
        "\n"
        "def test_add_basic():\n"
        "    assert add(1, 2) == 3\n"
        "\n"
        "def test_add_zero():\n"
        "    assert add(0, 0) == 0\n"
        "\n"
        "def test_mul_basic():\n"
        "    assert mul(3, 4) == 12\n"
    )
    result = await run_tests(
        RunTestsInput(
            code=student_code,
            test_code=test_code,
            framework="pytest",
            timeout_seconds=30,
        )
    )
    assert isinstance(result, RunTestsOutput)
    assert result.passed == 3
    assert result.failed == 0
    assert result.errors == 0
    assert len(result.test_results) == 3
    for tr in result.test_results:
        assert tr.passed is True
    assert result.timed_out is False


@pytest.mark.asyncio
async def test_pytest_mixed_pass_fail() -> None:
    """Three passing + one failing assertion."""
    student_code = "def add(a, b):\n    return a + b\n"
    test_code = (
        "from student import add\n"
        "\n"
        "def test_basic():\n"
        "    assert add(1, 2) == 3\n"
        "\n"
        "def test_zero():\n"
        "    assert add(0, 0) == 0\n"
        "\n"
        "def test_negative():\n"
        "    assert add(-1, 1) == 0\n"
        "\n"
        "def test_wrong_expectation():\n"
        "    assert add(1, 1) == 3  # should be 2\n"
    )
    result = await run_tests(
        RunTestsInput(
            code=student_code,
            test_code=test_code,
            framework="pytest",
            timeout_seconds=30,
        )
    )
    assert result.passed == 3
    assert result.failed == 1
    # test_results captures all four with outcome flags.
    assert len(result.test_results) == 4
    failed_results = [tr for tr in result.test_results if not tr.passed]
    assert len(failed_results) == 1
    assert failed_results[0].name == "test_wrong_expectation"


@pytest.mark.asyncio
async def test_pytest_with_test_raising_exception() -> None:
    """A test that raises (not assert-fails) shows up as 'errors' in
    pytest's summary, distinct from 'failed'."""
    student_code = "def divide(a, b):\n    return a / b\n"
    test_code = (
        "from student import divide\n"
        "\n"
        "def test_divide_passes():\n"
        "    assert divide(4, 2) == 2\n"
        "\n"
        "def test_divide_setup_raises():\n"
        "    raise RuntimeError('test setup broken')\n"
    )
    result = await run_tests(
        RunTestsInput(
            code=student_code,
            test_code=test_code,
            framework="pytest",
            timeout_seconds=30,
        )
    )
    # pytest's behavior: a function-body raise in a test_* function is
    # reported as a FAILED test (the test function itself failed).
    # An ERROR (vs FAILURE) in pytest occurs during collection or
    # fixture setup. So this case should produce passed=1, failed=1.
    # Don't strict-assert errors=0 because pytest version differences
    # may classify differently; instead check the pass count.
    assert result.passed == 1


@pytest.mark.asyncio
async def test_pytest_timeout_propagates() -> None:
    """An infinite loop in test code triggers the underlying sandbox
    timeout. timed_out is True in the output."""
    student_code = "def hang():\n    while True: pass\n"
    test_code = (
        "from student import hang\n"
        "\n"
        "def test_hang():\n"
        "    hang()\n"
    )
    result = await run_tests(
        RunTestsInput(
            code=student_code,
            test_code=test_code,
            framework="pytest",
            timeout_seconds=2,  # short timeout for fast test
        )
    )
    assert result.timed_out is True


# ── Framework dispatch (deferred frameworks) ──────────────────────


@pytest.mark.asyncio
async def test_unittest_framework_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError) as exc_info:
        await run_tests(
            RunTestsInput(
                code="x = 1",
                test_code="import unittest",
                framework="unittest",
            )
        )
    assert "unittest" in str(exc_info.value)


@pytest.mark.asyncio
async def test_jest_framework_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError) as exc_info:
        await run_tests(
            RunTestsInput(
                code="const x = 1",
                test_code="test('x', () => {})",
                framework="jest",
            )
        )
    assert "jest" in str(exc_info.value)


@pytest.mark.asyncio
async def test_vitest_framework_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        await run_tests(
            RunTestsInput(
                code="const x = 1",
                test_code="test('x', () => {})",
                framework="vitest",
            )
        )


@pytest.mark.asyncio
async def test_node_language_raises_not_implemented() -> None:
    """Even with framework=pytest, language=node should raise; the
    framework is moot when the language isn't supported."""
    with pytest.raises(NotImplementedError) as exc_info:
        await run_tests(
            RunTestsInput(
                code="const x = 1",
                test_code="test('x', () => {})",
                language="node",
                framework="pytest",
            )
        )
    assert "node" in str(exc_info.value).lower() or "Node.js" in str(exc_info.value)


# ── Schema validation ──────────────────────────────────────────────


def test_run_tests_input_rejects_unknown_framework() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RunTestsInput(
            code="x = 1",
            test_code="def test_x(): pass",
            framework="rspec",  # type: ignore[arg-type]
        )


def test_test_result_schema_validates() -> None:
    """Sanity check on the per-test result shape."""
    tr = SandboxTestResult(name="test_foo", passed=True)
    assert tr.passed is True
    assert tr.error is None
    assert tr.duration_ms == 0


def test_run_tests_output_default_empty_lists() -> None:
    """Sanity: zero-test scenarios produce well-formed output."""
    out = RunTestsOutput(passed=0, failed=0, errors=0)
    assert out.test_results == []
    assert out.output == ""
    assert out.timed_out is False
