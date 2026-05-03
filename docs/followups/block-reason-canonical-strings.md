# Canonical block_reason strings for dashboards

**Status:** Open — non-blocking, useful for **Pass 3i §G dashboards**.
**Created:** 2026-05-02 (D9 Checkpoint 3 sign-off).
**Blocked by:** nothing — small standardization task.

## What D9 ships

`AgentResult.block_reason` is a free-form string. The dispatch layer
uses some canonical short strings (Pass 3f §A.3 reasons):

- `"agent_not_in_tier"`
- `"agent_unavailable"`
- `"agent_unknown"`
- `"cost_exhausted"`
- `"entitlement_revoked"`

But the specialist-error path (Pass 3b §7.1 Failure Class C) surfaces
the **stringified exception** as `block_reason` — e.g.
`"RuntimeError: simulated specialist failure"`. The safety primitive
adds two more short forms:

- `"safety_input"` (when input was blocked by the gate)
- `"safety_output:{severity}"` (e.g. `"safety_output:critical"`)
- `"specialist_error"` (intent — but the actual code uses
  `call_result.error` which is the raw exception message)

The orchestrator decline path uses:
- `"supervisor_decline:{decline_reason}"` (e.g.
  `"supervisor_decline:out_of_scope"`)
- `"safety_input:{severity}"`
- `"supervisor_output_invalid"`
- `"no_active_entitlement"`

## Why this matters for Pass 3i §G dashboards

Pass 3i §G calls for operational dashboards including:
- "How many requests are denied at each layer per day?"
- "What's the decline-rate by reason?"
- "Which agents have the highest block rate, and what reasons dominate?"

These dashboards `GROUP BY block_reason`. With the current mix of
canonical short strings + stringified exception messages, the GROUP
BY produces a long tail of one-of-a-kind exception strings ("RuntimeError:
connection timeout to ...", "ValueError: bad input", etc.) which
are individually uninformative for trends.

The fix is to standardize block_reason to a closed taxonomy and
move the per-incident detail into a separate field.

## Proposed canonical taxonomy

```python
class BlockReason(StrEnum):
    # Entitlement layer (Pass 3f §A)
    ENTITLEMENT_REVOKED = "entitlement_revoked"
    AGENT_NOT_IN_TIER = "agent_not_in_tier"
    AGENT_UNAVAILABLE = "agent_unavailable"
    AGENT_UNKNOWN = "agent_unknown"
    COST_EXHAUSTED = "cost_exhausted"
    NO_ACTIVE_ENTITLEMENT = "no_active_entitlement"

    # Safety layer (Pass 3g §A)
    SAFETY_INPUT_BLOCK = "safety_input_block"
    SAFETY_OUTPUT_BLOCK = "safety_output_block"
    SAFETY_INPUT_LENGTH = "safety_input_length"

    # Supervisor (Pass 3b §7.1)
    SUPERVISOR_DECLINE = "supervisor_decline"          # detail in decline_reason
    SUPERVISOR_OUTPUT_INVALID = "supervisor_output_invalid"

    # Dispatch (Pass 3b §5)
    SPECIALIST_ERROR = "specialist_error"              # detail in error_message
    SPECIALIST_TIMEOUT = "specialist_timeout"
    HANDOFF_LIMIT = "handoff_depth_exhausted"

    # Chain dispatch
    CHAIN_STEP_FAILED = "chain_step_failed"            # detail in step_index + reason
    CHAIN_BUDGET_EXHAUSTED = "chain_budget_exhausted"
```

And shift incident detail to a separate field:

```python
class AgentResult(BaseModel):
    blocked: bool
    block_reason: BlockReason | None        # canonical short string
    block_detail: str | None                # free-form: exception
                                            #            message,
                                            #            decline_reason,
                                            #            chain step idx, etc.
    # ... existing fields ...
```

## What this earns

- Dashboards `GROUP BY block_reason` produce stable, low-cardinality
  facets.
- Time-series alerting on "spike in `cost_exhausted`" or "spike in
  `specialist_error`" works without string-cleaning steps.
- Operational runbooks can reference reasons by their short name
  ("if you see SPECIALIST_ERROR climb, check..."). 

## When to do this

Not D9. The taxonomy lands cleanly during Pass 3i §G dashboard work
because that's the consumer. If we standardize before the consumer
exists, we'll likely guess wrong about which detail field shapes
matter. Better to ship D9 with the current free-form strings,
collect 2-4 weeks of production data, then design the taxonomy
against actual usage patterns.

The migration is straightforward when it lands:
1. Introduce `BlockReason` enum + `block_detail` field on AgentResult
2. Update every block_reason= site to populate both fields
3. Backfill historical agent_actions if necessary (probably not — old
   rows can stay free-form, dashboards filter to recent data)

## Cross-references

- `backend/app/agents/dispatch.py` — current block_reason call sites
- `backend/app/agents/agentic_base.py::_maybe_safety_scan_output` —
  safety block_reason call sites
- `backend/app/services/agentic_orchestrator.py` — orchestrator
  block_reason call sites
- Pass 3i §G dashboards — the consumer
- D9 Checkpoint 3 status report — Deviation #8 sign-off context

## Tag

**Non-blocking; revisit during Pass 3i §G dashboard work.** Adding
this to the queue as a small refactor to surface during the
observability pass rather than a behavior-changing task.
