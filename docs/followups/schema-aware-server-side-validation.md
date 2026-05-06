# Schema-aware server-side validation

**Status:** Open. Architecture pattern from D12 CP3 Phase 4 Bug 17.
**Created:** 2026-05-07 (D12 closure).
**Cross-references:** `app/agents/parsing_helpers.py::truncate_to_schema`, `tests/test_agents/test_truncate_to_schema.py`, `agent-tool-call-discipline.md` (Pattern 5).

## What we learned

Prompt-level constraint emphasis (e.g. "HARD LIMIT: 200 characters") is **unreliable under MiniMax**. Three iterations on resume_reviewer surfaced different `max_length` overshoots even with explicit framing in the prompt. The principle adopted in Bug 17's architectural fix:

> **Schema is canonical. LLM produces best-effort. Server enforces.**

The `truncate_to_schema` helper in `app/agents/parsing_helpers.py` walks the parsed JSON dict, traverses Pydantic field metadata recursively, and truncates string overshoots before `model_validate` runs. This makes max_length non-compliance a recoverable parse-time fix instead of a 5xx error to the user.

## Current scope (D12 v2 agents)

- String `max_length` truncation only.
- Wired into all four D12 v2 `_parse_output` functions.
- 16 unit tests (`test_truncate_to_schema.py`) cover string boundaries, None handling, nested BaseModel recursion, list[BaseModel] recursion, Optional / `T | None` unwrapping, and Union ambiguity (skip + warn).

## Future scope

D13+ agents and D17 cleanup work should extend the helper:

1. **Literal allowlist coercion.** When the LLM produces `"low confidence"` for a `Literal["low", "medium", "high"]` field, snap to the closest member instead of failing validation.
2. **Required-field synthesis.** For absent required string fields, synthesize a default ("[no data]") so other valid fields aren't lost. Risky — needs careful framing to avoid silent quality degradation.
3. **Type coercion.** `int → str`, `str ("3") → int 3`, `str ("true") → bool` where the schema expects the target type and the LLM produced something parseable.
4. **Structural correction.** When the LLM nests an object that should be flat (or vice versa), reshape if the field set matches.

Each addition deserves its own test pin and a careful framing of "when to coerce vs. when to fail." The current truncation-only scope is intentionally minimal because truncation is unambiguous (always safe to drop trailing chars).

## Triage

D13+ migrations: extend per-agent. D17 cleanup: backfill the helper to D10/D11 agents (billing_support, senior_engineer, learning_coach) if their prompts have any `max_length` overshoots in production telemetry.

## Related architectural decisions

- `parsing_helpers.truncate_to_schema` is shared, not per-agent — one source of truth.
- It runs **before** Pydantic `model_validate`, not after — Pydantic errors are caught only on truncation logic bugs, not on overshoots.
- It returns a NEW dict (does not mutate input) — caller can fall back to original on helper failure.
- Logs at debug level on truncation hits (each emit). Verbose, but useful for production observability ("how often is the LLM overshooting?"). If verbosity becomes a problem, downgrade to a single counter increment.
