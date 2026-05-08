# Test suite bulk-run OOMs in dev container; by-directory workaround

**Status:** Open. Operational. D18 Phase A test infrastructure should
plan around this.
**Origin:** D17b ITEM 1 closure note (cumulative across the engagement
since D9's Presidio eager-load wired safety into worker boot). First
explicit observation at D17b: `pytest -q` against the full backend
suite consistently OOM-kills the dev container (exit 137).
**Created:** 2026-05-08 (D17b ITEM 5).

## What this is

Running the full backend test suite in one process (`docker compose
exec backend uv run pytest -q`) consistently dies with **exit code 137
(OOM kill)** after collecting/running roughly the first 7-15% of tests.
Memory ceiling is the dev container's `memory_mb` (currently 4096 per
`fly.toml` precedent + docker-compose default). The combination of:

- Presidio + spaCy `en_core_web_lg` (~750 MB resident at agent test
  collection per Pass 3g §H.3)
- pytest's per-test fixture accumulation across an async-heavy suite
- shared LLM-client / agent-class / tool-registry imports that don't
  release memory between tests

…cumulatively pushes resident past the cap when the suite tries to
hold everything in one process.

The workaround used across D17b ITEMs 1-4: **run by directory**. Each
of:

```
tests/test_services/
tests/test_models/
tests/test_schemas/
tests/test_routes/
tests/test_api/
tests/test_core/
tests/test_infra/
tests/test_contracts/
tests/test_agents/
tests/test_sandbox/
tests/test_chat_flashcards.py + test_notebook.py + test_notebook_summarize.py
```

stays under the cap when run as a separate `pytest` invocation.
Aggregating across them gives the engagement's "1383 passed / 45
pre-existing failures" numbers, just spread across multiple invocations.

## Why this matters

**Cross-test interaction effects are not exercised under by-directory
runs.** A test that mutates a global (e.g., the agent registry) and a
test in another directory that reads that global will both pass when
run separately and could fail when run together. We've seen this shape
once before: `test_tools` clearing the tool registry then leaving it
unrepopulated for the next module (handled today by the `_ensure_universal_tools_registered` autouse fixture in
`tests/test_agents/tools/universal/conftest.py`). Bulk-run-as-one would
catch any new instances of this shape; by-directory runs cannot.

## Operational impact

- **CI strategy** — single `pytest` job running the full suite would
  OOM in CI just as it does locally. CI must split into multiple
  parallel jobs, one per directory cluster, with bounded memory per
  job. Aggregation happens at the CI gate level.
- **Local developer flow** — running "the test suite" in one shot is
  not safe. The natural reflex (just type `pytest` and wait) doesn't
  work; the developer needs to either know to run by-directory or
  use a wrapper script that does it for them.
- **Test-authoring discipline** — new test files should explicitly
  not introduce cross-directory state dependencies, since the
  by-directory CI strategy can't guarantee they'll be exercised
  together.

## Three remediation paths (D18 Phase A)

**Path A — wrapper script.** Author `make test` / `pytest-wrapper.sh`
that runs the by-directory split, aggregates pass/fail counts, exits
non-zero if any sub-run fails. Lowest engineering cost; doesn't fix
the underlying memory issue but stops developers from hitting it. CI
calls the wrapper.

**Path B — bump container memory ceiling.** Raise `memory_mb` to
6144 or 8192 in dev compose. May allow the full-suite-in-one-shot to
fit, but is a moving target as the suite grows. Doesn't address the
memory-leak shape; just defers it.

**Path C — investigate the leak.** Profile what's accumulating across
tests; fix the root cause (likely a fixture not tearing down a
client / cache, or test-collection-time imports holding state). Most
correct; highest engineering cost; depends on the leak being
identifiable.

**Recommendation:** Path A immediately (unblocks D18 Phase A); Path C
opportunistically when the leak surfaces in another investigation.
Path B is defensive against the wrong axis.

## Cross-references

- D9 Checkpoint 1 + `docs/followups/celery-safety-memory-bump.md` —
  documents the Presidio resident-memory cost per worker process;
  same math applies to test-collection processes that import
  AgenticBaseAgent.
- D17b ITEM 1 closure (commit 94a093f) — first explicit observation +
  workaround documentation in a closure report.
- D17b ITEMs 2-4 closures — by-directory test-runs documented across
  the engagement; pattern observed consistently.

## Cross-pattern note

This is not Pattern 24 (docker-compose volume mount asymmetry) — that
pattern is about source-code mount inconsistency. This is a memory-
ceiling issue under the same image+mount combination. Distinct
operational concern.
