# Sandbox Node.js execution — deferred

**Status:** Open. Pass 3d §E.3.2 RunInSandboxInput declares `language: Literal["python", "node"]`. D11.5 implements Python only; `language="node"` raises `NotImplementedError` at the executor.
**Created:** 2026-05-07 (D11.5 closure).
**Triage:** D14b/D14c follow-up if practice_curator generates Node.js exercises or project_evaluator validates Node.js capstones. Otherwise D17 cleanup.
**Cross-references:** `app/sandbox/executor.py` (raise site); `app/sandbox/test_runner.py` (run_tests dispatch raises for Node language too); pass-3d-tool-implementations.md §E.3.2.

## What

The schema accepts `language="node"`; the executor immediately raises:

```python
if request.language == "node":
    raise NotImplementedError(
        "Node.js execution not yet implemented; D11.5 ships Python "
        "only. See docs/followups/sandbox-language-extension-node.md."
    )
```

This pattern (accept at schema layer, raise at implementation) keeps the spec contract honest: callers see the schema declares Node support; the runtime tells them when it's available. When Node lands, callers don't need to update — only the executor changes.

## What Node.js execution would require

1. **Node binary in the application container.** Currently the container ships only Python. Adding Node adds image bytes (~30-50MB for Node alpine) and an apt/apk install line.
2. **`subprocess` invocation rewrite for Node.** Currently `[sys.executable, "-I", "-B", "-c", code]`. Node would be `[node_path, "-e", code]` or via tempfile `/tmp/code.js`. The `-I` (isolated mode) and `-B` (no bytecode) flags are Python-specific — Node's equivalent of `--no-deprecation` etc. would need investigation.
3. **`getrusage` is process-level, language-agnostic** — `memory_used_mb` capture works unchanged.
4. **Resource limits (`RLIMIT_*`) are process-level** — apply unchanged via `preexec_fn`.
5. **Escape detection patterns** — currently tuned for Python's traceback format and stdout shapes. Node tracebacks look different; the existing patterns probably still cover the secret-content + network-success cases (which match output shapes, not language-specific patterns), but a sweep with Node-specific test cases is required.
6. **Test framework dispatch in `run_tests`.** Currently routes `pytest` to `_run_pytest`. Node's jest/vitest dispatch is already stubbed (raises NotImplementedError). When Node lands, `_run_jest` and `_run_vitest` need composition harnesses similar to `_PYTEST_HARNESS_TEMPLATE`.

## Why D11.5 doesn't ship Node

1. No D11.5 consumer needs it. D11.5's stated downstream consumer (D11.5.5 senior_engineer integration) is Python-focused. D14b/D14c (practice_curator + project_evaluator) haven't shipped yet, so we don't know if they'll generate Node content.
2. Adding Node speculatively costs more than waiting for spec confirmation. Per pass-3d's stance: ship the smallest correct surface; extend when the consumer arrives.
3. Schema acceptance + clear NotImplementedError is the honest middle ground. Callers can plan; runtime fails loud when the plan diverges.

## Triage signals

Promote from "open follow-up" to "active work" when:
- D14b practice_curator design includes Node-language exercise generation
- D14c project_evaluator design includes Node-language capstone evaluation
- Production product roadmap adds JavaScript/TypeScript curriculum content with executable assignments

## Cross-references

- [backend/app/sandbox/executor.py](../../backend/app/sandbox/executor.py) — `language=="node"` raise site
- [backend/app/sandbox/test_runner.py](../../backend/app/sandbox/test_runner.py) — `language=="node"` raise site for run_tests
- [backend/app/schemas/sandbox.py](../../backend/app/schemas/sandbox.py) — schema accepts Node at the type level
- pass-3d-tool-implementations.md §E.3.2 — original spec
