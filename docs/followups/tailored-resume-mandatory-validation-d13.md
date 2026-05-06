# tailored_resume mandatory reviewer validation — deferred to D13

**Status:** Deferred. `TailoredResumeAgent` ships in D12 without triggering a
mandatory chain to `resume_reviewer`. The `handoff_request` field in
`TailoredResumeOutput` is always `None` in D12.
**Created:** 2026-05-06 (D12 CP1).
**Deliverable:** D13 (Supervisor mandatory-chain work, per Pass 3c E6 line 1095).
**Cross-references:** Pass 3c E6 line 1095; `backend/app/schemas/agents/tailored_resume.py`
(`handoff_request` field); D11 Option B handoff decision.

## What was decided in D12

`TailoredResumeOutput.handoff_request` is declared as `HandoffRequest | None = None`.
This is intentional — D13 reads this field to decide whether to wire the mandatory
chain. The field is there; D12 just never populates it.

**What D12 ships:**
- `handoff_request: HandoffRequest | None = None` in `TailoredResumeOutput`
- No logic in `TailoredResumeAgent.run()` that sets this field
- No Supervisor change for mandatory-chain honoring
- `unsupported_additions: list[str] = []` always empty (populated by D13 after
  reviewer validates the tailored resume)

## What D13 implements

Per Pass 3c E6 line 1095, the full mandatory-chain flow:

### Step 1 — `TailoredResumeAgent.run()` populates `handoff_request`

```python
from app.schemas.supervisor import HandoffRequest
from app.schemas.agents.tailored_resume import TailoredResumeOutput

# At the end of run(), after the LLM generates the tailored resume:
output = TailoredResumeOutput(
    tailored_resume=tailored_text,
    changes_made=changes,
    keyword_alignment_score=score,
    unsupported_additions=[],  # D13: reviewer populates this
    ats_compatibility_notes=ats_notes,
    handoff_request=HandoffRequest(
        target_agent="resume_reviewer",
        reason="Mandatory validation: tailored resume must be reviewed for "
               "unsupported claims before delivery to student.",
        suggested_context={
            "resume_text": tailored_text,
            "target_role": ctx.get("target_role"),
            "specific_concerns": ["unsupported_claims", "ats_compatibility"],
            "source": "tailored_resume_validation",
        },
        handoff_type="mandatory",  # key distinction from D11 optional handoffs
    ),
)
```

### Step 2 — Supervisor honors mandatory handoffs

The Supervisor must be updated (D13 scope) to distinguish `mandatory` from
`suggested` handoff types in `HandoffRequest`. Per Pass 3b §5.3, the dispatch
layer re-invokes the Supervisor with handoff context:

```python
# In dispatch.py or agentic_orchestrator.py (D13 decides the exact location):
if result.handoff_request and result.handoff_request.handoff_type == "mandatory":
    # Re-invoke Supervisor with the handoff context
    # Supervisor MUST honor mandatory (unlike suggested, which it can decline)
    mandatory_context = result.handoff_request.suggested_context
    reviewer_result = await dispatch_single("resume_reviewer", mandatory_context)
    # Merge reviewer's unsupported_claims back into the tailored resume output
    if reviewer_result.structured_output:
        output_dict["unsupported_additions"] = (
            reviewer_result.structured_output.get("unsupported_claims_text", [])
        )
```

### Step 3 — `ResumeReviewerAgent` returns unsupported claims

The reviewer runs with `source="tailored_resume_validation"` in context, which
signals it to focus only on unsupported claims (not a full review). It returns
`ResumeReviewerOutput` normally; the dispatch layer extracts
`unsupported_claims` and injects them into `tailored_resume.unsupported_additions`.

### Step 4 — Final delivery

The student sees a tailored resume with `unsupported_additions` populated —
a list of strings naming claims the reviewer couldn't verify from their
exercise submissions or capstone. This is the D13 safety guarantee: no
unverifiable content is silently delivered.

## Why this is D13 and not D12

Mandatory handoffs require two pieces of Supervisor work that D12 explicitly
does not touch:

1. **Supervisor must distinguish mandatory vs. suggested** — the current
   dispatch path (D11 Option B) treats all handoff requests as advisory and
   re-routes through the Supervisor. Making the Supervisor honor `mandatory`
   requires a prompt change + possibly a schema change to `RouteDecision`.

2. **D13 scope includes mock_interview → senior_engineer mandatory chain** —
   both mandatory chains land together so the Supervisor change is written
   once, tested once, and reviewed as a unit.

Shipping D12 without this is safe because:
- `unsupported_additions` defaults to `[]` (explicit empty, not missing)
- The field is documented as "D13 populates" in `TailoredResumeOutput`
- No student-facing promise is broken — the tailored resume is still
  individually reviewed in D12's route path (via `tailored_resume_service.py`)

## Architecture note — prompt source for tailored_resume (D12 CP3 Part E)

**Observation added 2026-05-06.**

`prompts/tailored_resume.md` is consumed by the **inner LLM helper**
(`tailored_resume_llm.py`), NOT directly by `TailoredResumeShimAgent`
(the `AgenticBaseAgent` subclass in `tailored_resume_v2.py`).

The call chain is:

```
TailoredResumeShimAgent.run()
  └── tailored_resume_service.generate_tailored_resume(session, user, ...)
        └── TailoredResumeAgent.generate(evidence, parsed_jd, ...)   ← tailored_resume_llm.py
              └── llm.ainvoke([SystemMessage(_PROMPT), HumanMessage(...)])
                    ↑ _PROMPT = (Path(__file__).parent / "prompts" / "tailored_resume.md").read_text()
```

The shim agent is a **pass-through** — it resolves JD text, loads the User
object, delegates entirely to the service, then maps the result to
`TailoredResumeOutput`. The shim does NOT call `prompts/tailored_resume.md`.

**Why this matters for D13:**

When D13 implements the mandatory chain, the `handoff_request` is populated
inside `TailoredResumeShimAgent.run()` — AFTER the service call returns —
not inside the LLM call that reads the prompt. The prompt instructs the LLM
to set `unsupported_additions: []`; the shim sets `handoff_request`. These
are independent fields at different layers. D13 should not attempt to make
the LLM in `tailored_resume_llm.py` emit the `HandoffRequest` — that would
couple structured handoff control to LLM output and require prompt-schema
alignment work that belongs at the agent layer, not the service layer.

## Cross-references

- Pass 3c E6 line 1095 — full mandatory-chain spec
- `backend/app/schemas/agents/tailored_resume.py` — `handoff_request` field
- `backend/app/schemas/supervisor.py::HandoffRequest` — `handoff_type` field
  (`"mandatory"` | `"suggested"`)
- D11 Option B decision — why handoffs go back through the Supervisor, not
  directly to the target agent
- `docs/followups/study-planner-proactive-d16.md` — parallel pattern for
  another deferred inter-agent wiring
- `backend/app/agents/tailored_resume_llm.py` — the inner LLM helper that
  reads `prompts/tailored_resume.md`; renamed from `tailored_resume.py` at D12 CP1 α-1
- `backend/app/agents/tailored_resume_v2.py` — the `AgenticBaseAgent` shim;
  delegates to service, not to the prompt
