# Handoff protocol — D11/D13 dependency

**Status:** **Decision: Option B confirmed at D11; revisit at D13**
when mock_interview ships and provides the first real handoff target
on both sides. Cross-references: Pass 3b §5.3 (architecture spec),
D11 Checkpoint 1 readback (rationale), D13 prompt (revisit gate).
**Created:** 2026-05-02 (D9 Checkpoint 3 sign-off).
**Decided:** 2026-05-05 (D11 Checkpoint 1).
**Originally blocked by:** D11. Now blocked by: D13 (mock_interview
ships first real cross-side handoff target).

## What D9 shipped (the simplification)

D9's `dispatch.process_handoff` implements a deliberately reduced
version of Pass 3b §5.3. The reduction:

- **Mandatory handoffs** — direct invocation of the suggested target
  via a synthesized `dispatch_single` call. Skips re-invoking the
  Supervisor.
- **Suggested handoffs** — declined entirely (logged + return None).
- **Depth cap** — 1. A handoff cannot trigger another handoff.

Loops are prevented by construction: no Supervisor re-call ⇒ no
chance of cyclic re-routing.

## Why this is fine for D9 (but not later)

D9 ships only ONE specialist with `available_now=True` (Learning
Coach from D8). Learning Coach's `handoff_targets` is `["code_mentor"]`
— but `code_mentor` is not in the registry, so any handoff request
from Learning Coach is dropped at the registry-validation step in
`process_handoff`. The simplified protocol is *unexercisable* on
real specialists in D9.

## Why D11 forces a decision

D11 ships `senior_engineer`, which is the merged successor to
`code_review` + `coding_assistant`. Its `handoff_targets` per the
Pass 3a Addendum capability declaration are likely:

- `learning_coach` — "go study this concept that you're missing"
- `mock_interview` — "looks like coding-round interview prep"
  (when D13 lands)

The moment D11 deploys with real handoff_targets, the simplification
starts dropping signal:

- A senior_engineer review that flags "student needs to learn DI
  before this code makes sense" produces a *suggested* handoff to
  learning_coach. D9's logic declines suggested handoffs entirely
  → that signal is silently lost.
- A senior_engineer review that flags "you're prepping for a coding
  interview" produces a *suggested* handoff to mock_interview. Same
  drop.

Neither is broken-broken — the student still gets the senior_engineer
review. But the OS-of-learning experience suffers because the
between-agent coordination Pass 3b promised never fires.

## Two-option resolution menu for D11

### Option A — Implement full Pass 3b §5.3 protocol when D11 lands

The full protocol:
1. Specialist returns a `HandoffRequest` in its output.
2. Dispatch layer re-invokes the Supervisor with a synthesized
   "handoff_from_X to Y" context, including the partial chain and
   the specialist's reason.
3. Supervisor reads the handoff context AND the call chain from
   `agent_call_chain` (loop detection on edges).
4. Supervisor decides whether to honor the handoff (e.g. it might
   refuse if cost budget is low, or if the student already had a
   recent learning_coach interaction on this concept).
5. If honored, dispatch the new agent with the suggested context.

Cost: meaningful. The Supervisor re-invocation is a second Sonnet
call per request, doubling the orchestration cost on
handoff-triggering requests. Mitigation: handoff requests are rare
(specialists return them only when genuinely beneficial), so the
amortized cost is small.

Complexity: moderate. The orchestrator needs to thread a
"handoff_context" object through the second Supervisor call;
`SupervisorContext` needs an optional `parent_chain_summary` field;
the Supervisor's prompt needs an examples block for handoff
adjudication.

### Option B — Defer all handoff support until D13 ships mock_interview

Document senior_engineer's `handoff_targets` as
**informational-only** in D11 — the field exists in the capability
declaration and informs the Supervisor's chain-decision reasoning,
but specialist `HandoffRequest` returns are simply ignored.

Rationale: the Supervisor's prompt already uses
`handoff_targets` as a hint for chain dispatch (Example 3 in
`supervisor.md`). Static knowledge of "senior_engineer often hands
off to learning_coach" is useful even without the post-hoc handoff
mechanism — the Supervisor can build a 2-step chain *up-front* when
the request shape suggests one is needed, instead of relying on
specialists to ask for it after the fact.

Cost: ~zero. No code changes; just a documentation update to
senior_engineer's prompt + capability description.

Complexity: zero. The simplification stays in place; the field
becomes documentation rather than a mechanism.

When D13 ships mock_interview, revisit. By then we'll know:
- Whether up-front chain dispatch is sufficient in practice
- Which specialists generate the most handoff signal
- Whether the loss-of-signal is observable in production data
  (Critic scoring routing quality)

### Recommendation

**Option B for D11; revisit at D13 with production data.**

Reasoning: up-front chain dispatch is what the Supervisor is
already good at. Deferring the post-hoc handoff mechanism until
there's evidence it's needed avoids paying double-Sonnet cost for
a feature that may not move the needle. If at D13 we see
specialists frequently producing useful handoff signal that gets
dropped, Option A becomes the right call.

## Decision recorded at D11 Checkpoint 1

**Option B confirmed.** Three reasons:

1. The Supervisor's chain-construction logic already consumes
   `handoff_targets` as a hint, so multi-step chains can be built
   *up-front* when the request shape calls for one. The platform
   does not lose cross-agent coordination capability under Option B
   — it routes through chain construction instead of post-hoc
   handoff.
2. Option A doubles the orchestration cost on handoff-triggering
   requests (a second Sonnet call per request). Without production
   data showing that the post-hoc signal moves the needle, paying
   that cost now is speculative.
3. D11's scope already includes a six-call-site rewrite at cutover
   (services + routes that reference legacy `code_review` /
   `coding_assistant` agent names). Bundling the
   `parent_chain_summary` plumbing on top would push D11 past its
   intended size.

**What D11 ships under Option B:**

- `senior_engineer` capability declares
  `handoff_targets=["mock_interview", "learning_coach"]` —
  Supervisor reads this for up-front chain dispatch.
- `SeniorEngineerOutput.handoff_request` stays in the schema as
  `Optional[HandoffRequest] = None` (Pass 3c E2's spec preserved).
- `senior_engineer.md` prompt instructs the LLM to mention handoff
  suggestions as text in `next_step` ("If you'd benefit from
  conceptual help, our learning_coach can walk you through the
  pattern"). Structured `handoff_request` is **never populated** by
  the prompt.
- `dispatch.process_handoff` keeps its D9 simplification — suggested
  handoffs are declined, mandatory handoffs route directly. Since
  the prompt never returns one, neither path fires for senior_engineer.

**Forward compatibility for D13:** when mock_interview lands as the
first deliverable that benefits from genuine post-hoc handoff
(coding-round → senior_engineer for code review, then back), D13's
prompt updates flip senior_engineer's handoff instruction without
schema change. If by then production data shows up-front chains
suffice, Option B continues; if signal-loss is observable, D13
implements Option A.

## Forward-dependency note: HandoffRequest module location

`HandoffRequest` currently lives in `backend/app/schemas/supervisor.py`
(D9). D11 imports it from there into
`backend/app/schemas/agents/senior_engineer.py` so
`SeniorEngineerOutput.handoff_request: HandoffRequest | None` resolves
cleanly. The dependency direction (agents → supervisor schemas) is
awkward but not broken — it works because supervisor schemas have no
back-imports from agent schemas.

When D13 ships and `mock_interview` starts importing `HandoffRequest`
from agent code, the same pattern compounds: two agent modules
depending on a sibling-tier (supervisor) module. Consider extracting
to `schemas/handoff.py` as a leaf module before D13 starts importing
it heavily.

**Refactor cost:** mechanical — move the class, update 2-4 imports
(currently `dispatch.py`, `senior_engineer.py`, plus D13's future
`mock_interview.py`). No semantic change.

**Triage:** Optional cleanup during D13 — bundle with the handoff
Option A/B revisit so the schema-location decision is part of the
same conversation as the routing-protocol decision.

## Cross-references

- `backend/app/agents/dispatch.py::process_handoff` — the simplified
  v1 implementation
- Pass 3b §5.3 — the full protocol design
- Pass 3a Addendum — senior_engineer's role + handoff_targets
- D9 Checkpoint 3 status report — Deviation #7 sign-off context
- D11 deliverable spec — should reference this file when
  designing senior_engineer's output schema

## Tag

**Decision required by D11.** Not strictly a launch-blocker, but
shipping D11 without making this decision means handoff signals
silently drop, which is the kind of regression that's invisible
until someone debugs why "the specialists never coordinate."
