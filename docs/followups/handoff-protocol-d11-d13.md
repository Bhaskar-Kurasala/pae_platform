# Handoff protocol — D11/D13 dependency

**Status:** Open — **decision required by D11**.
**Created:** 2026-05-02 (D9 Checkpoint 3 sign-off).
**Blocked by:** D11 (senior_engineer ships with first non-trivial
`handoff_targets`).

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
