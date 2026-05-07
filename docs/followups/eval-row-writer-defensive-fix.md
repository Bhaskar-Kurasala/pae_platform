# `_write_evaluation_row` defensive None-handling (Bug 22)

## What

`_write_evaluation_row` in [backend/app/agents/primitives/evaluation.py:1019](../../backend/app/agents/primitives/evaluation.py#L1019) was typed as `total_score: float` and clamped via `max(0.0, min(1.0, total_score))`. The agent-call-failed branch in `evaluate_with_retry` (line 855-866) legitimately passes `total_score=None` when the agent's `run()` raises before the Critic can score anything. The clamp crashed with `'<' not supported between instances of 'NoneType' and 'float'`, swallowed into `evaluate.write_evaluation_failed` log, and the eval row was lost.

## Why this surfaced now

D13's mock_interview is the first v2 agent with `uses_self_eval=True`, which activates the `evaluate_with_retry` path. D13 CP3 Phase 4 hit a `ValidationError` inside `agent.run()` (Bug 21 — handoff_request schema mismatch), which routed to the agent-call-failed branch and triggered the None-clamp crash.

D10/D11/D12 v2 agents all set `uses_self_eval=False`. D7-era unit tests for `Critic` stub the LLM and don't exercise the agent-call-failed branch with a None score. So Bug 22 was latent infrastructure brittleness.

## D13 CP3 minimal fix

Coerce None to 0.0 inside the writer (matches Critic's `parsed_ok=False` semantics — no score is treated as below-threshold). One-line defensive change at line 1042. Type signature widened to `total_score: float | None` to reflect actual call shape.

Pinned by [test_eval_row_writer_none_score.py](../../backend/tests/test_agents/test_eval_row_writer_none_score.py) — three tests covering the None case, the zero case, and the clamp-above-one case.

## What's NOT addressed (D17 cleanup)

- ~~The agent-call-failed branch's `verdict_reasoning` may be longer than the row's 2000-char column. Today it's truncated by the writer's existing `[:2000]` slice, but the truncation is silent.~~ **RESOLVED in commit 39c7564 (D17a)**: added `_truncate_with_warning` helper at `evaluation.py:1037`; both writers now emit a structlog `evaluate.row_field_truncated` event with original_len + field name when the 2000-char cap fires. Note on framing: the columns are PostgreSQL TEXT (unbounded), so the cap is application-level defensive guarding, not a column-length constraint as this doc originally implied.
- The eval-row schema doesn't distinguish "Critic flaked" from "agent raised before Critic ran" — both land as `total_score=0.0, passed=False`, and the only signal is `critic_reasoning`'s text. A future redesign could add an explicit `failure_class` enum.
- `_write_escalation_row` and `_write_evaluation_row` share enough structure that they could be refactored to a single writer with a discriminator field.

None of this blocks D13 ship. Sub-items 2 + 3 deferred — both require schema migration (failure_class enum) or cross-writer refactoring beyond D17a small-fix scope.

## Cross-references

- [backend/app/agents/primitives/evaluation.py:1019](../../backend/app/agents/primitives/evaluation.py#L1019) — `_write_evaluation_row` (post-fix).
- [backend/app/agents/primitives/evaluation.py:855-870](../../backend/app/agents/primitives/evaluation.py#L855-L870) — the call site that passes None.
- [backend/tests/test_agents/test_eval_row_writer_none_score.py](../../backend/tests/test_agents/test_eval_row_writer_none_score.py) — Bug 22 regression test.
- D13 CP3 Phase 4 closure — full Bug 22 history.
