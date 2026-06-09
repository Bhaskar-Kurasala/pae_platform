# mock_interview script-driver session_id propagation

**Status:** Open. Triage → D17 or post-launch (Playwright testing).
**Created:** 2026-05-08 (D15 CP4 → CP5 closure).
**Severity:** Test-infra observation; production path unaffected.

## What this is

`mock_interview` has `uses_self_eval=True`. The `AgenticBaseAgent`
execute() path runs the agent's `run(input, ctx)` inside a Critic-retry
loop (`evaluate_with_retry`). When the standalone real-LLM script driver
at `backend/scripts/d15_cp4_three_agent_real_llm.py` runs a multi-turn
session by repeatedly invoking `call_agent("mock_interview", payload, …)`,
the `input.session_id` arrives as `None` on every turn even when the
harness puts a string UUID in `payload["session_id"]`.

The agent's `run()` then generates a fresh UUID per invocation
(`session_id = input.session_id or uuid.uuid4()`), so each turn writes
to a different session-scoped memory key, prior_turns recall yields
nothing, and the gate-target persistence (CP4) can't recover on Turn 2+.

Net effect for CP4 Phase 4: per-turn agent calls succeed cleanly, but
the multi-turn driver can't reliably reach `turn_kind="session_summary"`
within the cost budget, and `session_verdict` consequently doesn't
populate end-to-end via the real-LLM driver.

## Why production isn't affected

The standard chat path threads session_id through the orchestrator's
session memory (`Conversation` model + `mock_interview:session:*`
memory keys), not through the `payload["session_id"]` field directly.
The orchestrator reads prior turns from memory before dispatching to
`mock_interview`, so even if `payload["session_id"]` were dropped, the
agent recovers session continuity from prior_turns.

The script driver bypasses the orchestrator and calls `call_agent`
directly. That's the only path observed to hit this.

## Where the field is dropped

Inconclusive at CP4 closure. The narrowest reading: somewhere in the
`call_agent` → `run_agentic` → `_validate_input` chain, the dispatcher
fails to surface `payload["session_id"]` as `MockInterviewInput.session_id`.
Direct schema validation works (`MockInterviewInput.model_validate({"mode":
..., "session_id": "<uuid>"})` parses correctly), so the bug is in the
dispatcher's payload-handling rather than the schema.

Candidate root causes (not investigated to ground):

- The `Pydantic.extra="ignore"` config silently drops fields the
  dispatcher's wrapping schema considers extra (when wrapping happens
  upstream of `MockInterviewInput.model_validate`).
- `call_agent`'s `_to_jsonable(payload)` projection at the audit path
  may strip non-canonical keys that the per-agent input_schema
  declares but the audit shape doesn't.
- `safety_classifier_timeout` retries the agent dispatch and the
  retry-payload is reconstructed without session_id.

## CP4 architecture verification path

CP4 architecture is verified deterministically by 24 stub-smoke tests
at `backend/tests/test_agents/test_cp4_schema_and_backstops.py`. Two of
those tests directly exercise `_enforce_session_verdict`:

- `test_enforce_session_verdict_canonical_with_zero_scores_when_llm_omits`
- `test_enforce_session_verdict_uses_llm_dimension_scores_when_present`

Both pass. The backstop produces a canonical `SessionVerdict` with all
four canonical dimensions, weights summing to 1.0, recomputed
`weighted_score`, and a `transition_target` populated when
`turn_kind=session_summary` and a valid gate is provided.

Production multi-turn invocations through the standard chat path will
exercise this code path correctly via the orchestrator's session
memory threading. The script driver is the only known caller hitting
the field-drop edge case.

## Triage

- **D17 cleanup**: investigate `_to_jsonable` + `_validate_input`
  payload field handling; add a regression test that round-trips a
  `session_id`-bearing payload through `call_agent` and asserts the
  agent saw it. ~2 hour spike.
- **Playwright testing**: production-path multi-turn session through
  the orchestrator naturally exercises session continuity via
  `Conversation` + memory, not via `payload["session_id"]`. Confirms
  the production path is unaffected.

If D17 deems this low-impact (and Playwright confirms production is
clean), defer indefinitely with this doc as the canonical record of
the test-infra finding.

## Cross-references

- `mock_interview.py` — `_detect_gate_prep_target` + `_enforce_session_verdict`
- `tests/test_agents/test_cp4_schema_and_backstops.py` — backstop pin tests
- `migration-verification-discipline.md` — Pattern 27 (test fixture
  staleness as code evolves) is the closest sibling, though this is a
  field-propagation question, not a fixture-staleness one.
