# Sandbox test-framework extensions — unittest, jest, vitest

**Status:** Open. Pass 3d §E.3.3 RunTestsInput declares `framework: Literal["pytest", "unittest", "jest", "vitest"]`. D11.5 implements pytest only; the other three frameworks raise `NotImplementedError` with explicit follow-up reference.
**Created:** 2026-05-07 (D11.5 closure).
**Triage:**
  • **unittest**: D17 cleanup. Most Python testing in the AICareerOS curriculum uses pytest; unittest is rare. Implement when a deliverable specifically needs it.
  • **jest / vitest**: paired with the Node.js sandbox extension (`sandbox-language-extension-node.md`). Don't implement until Node executor lands.
**Cross-references:** `app/sandbox/test_runner.py::run_tests` dispatch; pass-3d-tool-implementations.md §E.3.3.

## What

The schema accepts all four framework values. Dispatch in `run_tests`:

```python
if args.framework == "pytest":
    return await _run_pytest(args)
if args.framework in ("unittest", "jest", "vitest"):
    raise NotImplementedError(
        f"Framework {args.framework!r} is deferred (D11.5 ships pytest only). "
        "See docs/followups/sandbox-test-framework-extension.md."
    )
```

Each deferred framework needs:

1. **Composition harness.** `_PYTEST_HARNESS_TEMPLATE` builds a synthetic `student` module + writes test code to `/tmp/test_d11_5_<pid>.py` for pytest discovery. Each new framework needs an analogous harness:
   - **unittest**: similar to pytest but invokes `unittest.main()` or `python -m unittest test_file`. Output parsing differs (unittest's verbose output is line-oriented but with different markers than pytest).
   - **jest**: requires Node sandbox first. Composition: write package.json + test file + run `jest --json` for structured output.
   - **vitest**: similar to jest. `vitest run --reporter=json` for structured output.
2. **Output parser.** `_extract_count` regexes match pytest's "X passed, Y failed" summary line. Each framework has its own summary format.
3. **Per-test result extraction.** `_PER_TEST_RE` matches pytest's `path::test_name PASSED|FAILED` format. unittest, jest, and vitest each use different formats.

## Why D11.5 ships pytest only

1. **Pass 3d spec doesn't mandate unittest/jest/vitest as v1.** The Literal accepts them; the v1 implementation can be Python-pytest-only with a deferral.
2. **Consumer agnosticism.** D11.5 doesn't have a known consumer that requires non-pytest frameworks. D11.5.5 (senior_engineer) is Python; D14b/D14c haven't designed yet.
3. **Speculative implementation costs more than wait-for-consumer.** Adding three framework runners now means writing harnesses without input data on what edge cases matter. Each framework also has its own "exit code semantics" question — e.g., does a setup failure count as failed or errored? — that's better answered when a real consumer surfaces real edge cases.

## Migration discipline (when each framework lands)

For each new framework:
1. Write the composition harness in `app/sandbox/test_runner.py` as `_run_<framework>` alongside `_run_pytest`.
2. Add a new regex for that framework's summary line and per-test result.
3. Update the dispatch's elif to route the framework.
4. Add tests in `tests/test_sandbox/test_test_runner.py` mirroring the pytest test set:
   - All passing
   - Mixed pass/fail
   - Test that raises (errors path)
   - Timeout propagation
   - Empty test code
5. Update this doc to mark the framework resolved.

The Node-language frameworks (jest, vitest) ALSO need the Node executor — see `sandbox-language-extension-node.md`. Order is: Node executor → jest/vitest harnesses.

## Triage signals

Promote a specific framework from "open follow-up" to "active work" when:
- A specific deliverable (D14b, D14c, or another) needs it
- Production curriculum adds content using that framework

## Cross-references

- [backend/app/sandbox/test_runner.py](../../backend/app/sandbox/test_runner.py) — dispatch + raise sites
- [backend/tests/test_sandbox/test_test_runner.py](../../backend/tests/test_sandbox/test_test_runner.py) — pytest tests as the template for future framework tests
- [docs/followups/sandbox-language-extension-node.md](sandbox-language-extension-node.md) — paired follow-up for Node-language frameworks
- pass-3d-tool-implementations.md §E.3.3 — original spec
