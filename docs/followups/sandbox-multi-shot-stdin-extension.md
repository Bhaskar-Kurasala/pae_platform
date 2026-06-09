# Sandbox multi-shot stdin (test_inputs) — schema accepts, executor single-shot

**Status:** Open. Pass 3d §E.3.2 RunInSandboxInput declares `test_inputs: list[str]` with one stdin string per test. D11.5 validates the field shape (list[str], capped at 20 elements) but the executor runs the subprocess once with `stdin=DEVNULL`. Multi-shot stdin support is deferred.
**Created:** 2026-05-07 (D11.5 closure).
**Triage:** D14b follow-up if practice_curator generates exercises that use stdin (CLI-style problems). Otherwise D17 cleanup.
**Cross-references:** `app/schemas/sandbox.py::SandboxRequest.test_inputs`; `app/sandbox/executor.py` (currently passes `stdin=asyncio.subprocess.DEVNULL`); pass-3d-tool-implementations.md §E.3.2.

## What

The schema accepts:

```python
test_inputs: list[str] = Field(
    default_factory=list,
    max_length=20,
    description=(
        "Per-test stdin strings, one per element. Empty list means "
        "the subprocess runs once with /dev/null stdin (current "
        "single-shot behavior). Multi-shot stdin support is a "
        "future extension; D11.5 implements the empty-list path "
        "and validates the shape."
    ),
)
```

The executor currently ignores `test_inputs` content; the subprocess always gets `stdin=DEVNULL`. Tests pass `test_inputs=[]` (default) and don't exercise the multi-shot path.

## Two implementation options when this lands

**Option A — sequential subprocess invocations.** For each `test_input` element, spawn a fresh subprocess with that string piped to stdin. Aggregate stdout/stderr/exit_code per test. Returns a result-per-input or aggregated summary.

Cost: N × (subprocess spawn time + Python startup). At ~150ms per Python startup × 20 inputs = 3s pure overhead. Not great.

**Option B — single subprocess, multi-line stdin.** Concatenate `test_inputs` with separators; subprocess reads all inputs from stdin in sequence. Student code reads via `input()` calls; output is interleaved.

Cost: one subprocess, but: (1) student code has to handle "multiple inputs" semantically (each `input()` call gets the next line); (2) output attribution per test is harder (which output came from which input?); (3) timeout enforcement applies to the whole batch, not per-test.

**Option C (recommended) — depends on consumer needs.**
- If practice_curator generates "given input X, output should be Y" CLI-style problems with one stdin per test case, Option A's per-input-result shape is what consumers want.
- If senior_engineer or a code-grading flow batch-tests one program against multiple inputs and wants total pass/fail counts, Option B's batched shape is cheaper.
- Most likely answer: implement Option A and let the consumer decide whether to batch upstream.

## Why D11.5 ships single-shot

1. **No D11.5 consumer needs multi-shot.** D11.5.5 (senior_engineer integration) is review-shaped; pytest-based test running uses `run_tests`, not `run_in_sandbox` with test_inputs.
2. **Schema acceptance is the contract; runtime fails clean if test_inputs is non-empty.** Currently the field is silently ignored (single-shot regardless). Worth adding an explicit raise — see "interim hardening" below.
3. **Without a consumer, the Option A vs Option B choice is speculative.** Better to wait for a real use case.

## Interim hardening

Currently the executor silently ignores non-empty `test_inputs`. That's a footgun — a caller passing test_inputs and expecting per-test results gets a single-shot result with no error. **Worth adding an explicit raise** in a follow-up commit (small, defensive, no consumer impact since no consumer is using it yet):

```python
if request.test_inputs:
    raise NotImplementedError(
        "test_inputs (multi-shot stdin) is not yet implemented; D11.5 "
        "ships single-shot only. See "
        "docs/followups/sandbox-multi-shot-stdin-extension.md."
    )
```

This matches the pattern used for `language="node"` and `network_access=True`.

**Triage on this hardening**: defer to whichever D-stage next touches the executor body, OR ship as a one-liner in D11.5.5 prep work.

## Triage signals

Promote from "open follow-up" to "active work" when:
- D14b practice_curator design includes CLI-style problems with stdin
- Production curriculum adds problems that consume stdin
- Production audit shows callers passing non-empty test_inputs and getting silently-ignored results

## Cross-references

- [backend/app/schemas/sandbox.py](../../backend/app/schemas/sandbox.py) — `test_inputs` field accepted at schema layer
- [backend/app/sandbox/executor.py](../../backend/app/sandbox/executor.py) — `stdin=DEVNULL` site; would be replaced by Option A or B
- pass-3d-tool-implementations.md §E.3.2 — original spec
