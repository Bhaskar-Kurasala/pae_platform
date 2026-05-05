# Output-Text Projection Convention for AgenticBaseAgent Migrations

## Status

Open convention; applied per-agent for now.

## Convention

`AgenticBaseAgent`'s dispatch layer (`dispatch._extract_text` in
`backend/app/agents/dispatch.py`) reads from a fixed list of
top-level keys to project the canonical-endpoint `response` field.
The current readable list is:

```python
['output_text', 'answer', 'response', 'text']
```

Every migrated agent's output schema must either:

1. **Include one of these as a top-level string field** in the
   declared output schema, OR
2. **Provide a projector** (typically a static method) that
   composes the structured output into one of these keys before
   returning from `run()`.

## Examples

- **billing_support (option 1):** `BillingSupportOutput.answer` is a
  string field declared in the schema. Dispatch's `_extract_text`
  reads it directly.
- **senior_engineer (option 2):** `SeniorEngineerOutput` has
  mode-specific shape — three modes (`pr_review`, `chat_help`,
  `rubric_score`) each populate different field groups. No single
  field carries the readable response across all modes.
  `_compose_answer_text()` static method composes mode-appropriately
  and `run()` stamps `payload["answer"]` after `model_dump()`.

## Why this matters

Without the projector, `dispatch._extract_text` returns empty
string and the canonical endpoint's `response.response_text` is
empty even though the agent ran successfully. **Students see
blank responses despite the agent reasoning correctly** — exactly
the failure mode that surfaced during D11 CP2's stub smoke
before the projector was added.

It's also a silent failure: HTTP 200, structured output present
in `agent_actions.output_data`, no log warnings. Without a
deliberate test or smoke catching it, the gap could ship to
production undetected.

## Long-term resolution

Two viable paths:

1. **Add an `OutputTextProjectable` protocol/mixin** that
   `AgenticBaseAgent` expects of all subclasses. Make
   `output_text(self, structured_output) -> str` part of the
   class contract; raise at instantiation if the subclass
   doesn't implement it. Compile-time discipline.
2. **Document this convention prominently in the migration
   template** at Pass 3c §A.10 (the migration checklist).
   Soft-enforce via PR review; agent smoke tests catch
   violations.

Both are mechanical changes; pick one when D14/D15/D16 surface
the same friction. Lean: option 2 first (cheap), upgrade to
option 1 if more than 1-2 agents miss the convention before D17.

## Triage

Each agent migration must apply the convention until formalized.
**Future migrations that need this:**

- D12: career_coach, study_planner, resume_reviewer,
  tailored_resume
- D13: mock_interview
- D14: practice_curator, project_evaluator
- D15: content_ingestion
- D16: interrupt_agent

Each of these needs to either:

- Declare a top-level `answer`/`output_text`/`response`/`text`
  field in their output schema (option 1), or
- Provide an `_compose_answer_text`-style projector that the
  `run()` method calls before returning (option 2).

## Cross-references

- `backend/app/agents/dispatch.py::_extract_text` — the
  projection list source
- Pass 3c §A.10 — migration checklist that should mention this
  convention
- `backend/app/schemas/agents/billing_support.py` —
  `BillingSupportOutput.answer` (option 1 example)
- `backend/app/agents/senior_engineer_v2.py` —
  `_compose_answer_text` (option 2 example)
- `backend/app/schemas/agents/senior_engineer.py` —
  `SeniorEngineerOutput` (no top-level readable field; depends on
  the projector)
