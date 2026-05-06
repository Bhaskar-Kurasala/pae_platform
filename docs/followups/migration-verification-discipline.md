# Migration verification discipline — patterns from D10, D11, D12

**Status:** Open. Canonical patterns for D13+ migrations.
**Created:** 2026-05-07 (D12 closure).
**Cross-references:** `agent-tool-call-discipline.md` (Patterns 1-4 from D12), `schema-aware-server-side-validation.md`, `llm-output-token-budget-calibration.md`, `minimax-throughput-platform-characteristics.md`.

## Patterns 1-4 (registered in `agent-tool-call-discipline.md`)

1. **Broad-except hides tool-call signature mismatches.** Differentiate exception types in `try/except`; re-raise programming errors (Pydantic, AttributeError, TypeError); only swallow operational errors.
2. **Stub-LLM smoke doesn't exercise post-LLM dispatch.** CP2 stub responses must round-trip through `_parse_output` → output schema → write paths.
3. **Mock-based unit tests hide tool-API drift.** Every agent with tool calls must have one real-instantiation integration test (the H.2 pattern).
4. **Bundle migrations multiply template errors.** Verify the FIRST agent end-to-end before writing the rest of the bundle.

## Pattern 5: Prompt schema-shorthand drops Literal allowlists

Prompts that describe Pydantic schemas using shorthand like `"list of X objects (field_a, field_b)"` cannot communicate Literal allowlists through field names alone. Models guess and miss.

**Discipline**: every Literal-typed field must have its allowlist enumerated inline in the prompt's output schema section, in canonical pipe-separated form.

Caught in: D12 CP3 Phase 2 (Bug 14).

## Pattern 6: Prompt schema-shorthand drops nested-object field types

Same shape as Pattern 5 but for nested Pydantic objects. `"DailyBlock objects (day_of_week, duration_minutes, focus_area, specific_target)"` doesn't tell the model whether `day_of_week` is a string, integer, or enum, and what `duration_minutes` ranges are valid.

**Discipline**: enumerate every field's type and constraint per nested object class. The reading is verbose but catches a class of silent bugs that Pydantic surfaces as runtime ValidationErrors.

Caught in: D12 CP3 Phase 4 (Bug 15).

## Pattern 7: Prompts can't reliably enforce string max_length under non-Anthropic providers

Even with explicit "HARD LIMIT" framing, MiniMax overshoots `max_length` ~50% of the time on string fields. Server-side enforcement is required.

**Discipline**: for any agent producing structured output through Pydantic validation, route the parsed dict through `parsing_helpers.truncate_to_schema(...)` before `model_validate`.

Caught in: D12 CP3 Phase 4 (Bug 17). See `schema-aware-server-side-validation.md`.

## Pattern 8: SDK-level timeouts compose with orchestrator-level timeouts

`_LLM_TIMEOUT_S` in `llm_factory.py` is the per-attempt SDK timeout. It composes with `max_retries` (so SDK-level retries can multiply latency) AND with the orchestrator wrapper's `agent_call_timeout_seconds`. Misconfiguration causes the wrapper budget to be irrelevant — the SDK gives up first.

**Discipline**: when calibrating `typical_latency_ms` for a new agent, verify the SDK-level timeout is at least 1.5x the expected single-call P50. If not, raise `_LLM_TIMEOUT_S` (was 30s, now 90s after D12). Drop `max_retries` to 1 so retry loops can't burn the wrapper budget.

Caught in: D12 CP3 Phase 4 (Bug 11 root cause).

## Per-checkpoint verification protocol

For D13+ migrations, the checkpoint protocol is:

**CP1 (capability):** Schema landed, migrations applied, capability flipped, follow-up docs registered for any deferrals.

**CP2 (implementation):**
- Write the v2 agent class with `tool_call(name, args, ctx)` helper, dict-aware `_extract_text`, `_parse_output` with `truncate_to_schema`, and Option B `handoff_request=None` enforcement.
- Write the prompt with: architectural framing ("you are a structured-output producer"), Available context section, Pattern 5 + 6 enumerations, hard-constraint reminders.
- **Run real-LLM smoke for the first agent** before writing the rest of any bundle (Pattern 4).
- Write the H.2 real-instantiation integration test (Pattern 3).
- Write the F.3-style mocked unit tests for tool dispatch.

**CP3 (verification):**
- Phase 1: schema audit per tool reader, fix mismatches, sibling-check D10/D11.
- Phase 2: parser + prompt + Literal allowlist (Bug 10, 14, 15) — diagnostic-first if measurements are missing.
- Phase 3: per-agent timeout resolver calibrated from measurement.
- Phase 4: real-MiniMax verification, Bug 16 (`max_tokens`), Bug 17 (server-side truncation), 5 verification calls (4 individual + 1 chain).

**CP4 (cutover):**
- Pre-cutover state capture and checklist surface.
- Test suite finalization (delete orphaned test files, characterize collection errors).
- Cutover commit (single or split as appropriate).
- Post-cutover regression smoke (4 calls, same inputs as CP3).
- Closure report.

## Cost guidance

D12 closed at ~₹3.40 cumulative LLM cost. Most went to CP3 Phase 4 iterations on Bug 16/17. With the patterns documented here, D13+ should fit in **₹1.50-2.00 per agent** (single-agent migration; bundle migrations cost more due to per-agent verification). Allocate ₹2.50 as the safe budget for a single-agent migration; ₹4.00 for a bundle of 3-4 agents.

## Triage for retroactive application to D10/D11

D10 (billing_support) and D11 (senior_engineer) shipped without these disciplines. They work in production but may surface Bug 17-flavored issues if their prompts ever overshoot. **D17 cleanup**: backfill `truncate_to_schema` to billing_support + senior_engineer parsers; audit their prompts against Pattern 5/6.
