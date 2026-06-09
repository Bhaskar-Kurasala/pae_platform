# Anthropic tool-use protocol — speculative pattern shipped, proper protocol due in D11

**Status:** Open — D11 forces resolution.
**Created:** 2026-05-03 (D10 Checkpoint 3 sign-off, after the
phantom-escalation discovery).
**Cross-references:** Pass 3c E1 (billing_support spec — instructs
LLM to call lookup tools), Pass 3c E2 (senior_engineer spec — D11
deliverable that needs the proper protocol),
[billing_support.py](../../backend/app/agents/billing_support.py)
(the speculative pattern), Pass 3d §F.1 (the four billing tools).

## What was shipped in D10

billing_support's prompt instructs the LLM to call four tools
(lookup_order_history, lookup_active_entitlements,
lookup_refund_status, escalate_to_human). Anthropic's tool-use
protocol — where the LLM emits structured `tool_use` blocks in its
response and the host loops to handle them — is **not yet wired
through `AgenticBaseAgent`**. Wiring it properly is a multi-day
deliverable: tool-call message formatting, response-loop handling,
parallel tool execution, error surfacing back to the LLM, etc.

D10 Checkpoint 3 took a pragmatic shortcut for billing_support:

1. **Speculative read calls.** The agent's `run()` calls all three
   read-only lookup tools (orders, entitlements, refunds) at the
   start of every invocation, regardless of whether the question
   needs them. Results land in the LLM prompt's context block as
   compact JSON.
2. **Post-LLM escalation dispatch.** For the one write tool
   (`escalate_to_human`), the agent inspects the LLM's structured
   output. If the LLM emits `suggested_action="contact_support"`
   AND a non-null `escalation_ticket_id`, the agent fires the tool
   itself, **OVERWRITES the LLM's ticket id with the real one**
   from the tool's return, and on tool failure nulls the ticket id
   + appends a support-email fallback to the answer text. See
   `_dispatch_escalation_if_requested` in `billing_support.py`
   and the regression tests in
   [tests/test_agents/test_billing_support.py](../../backend/tests/test_agents/test_billing_support.py).

## Why the speculative pattern works for billing_support

Three properties make speculative reads safe for this agent:

- **Cheap.** Each read is an indexed DB query, ~5-15ms. Three
  calls add ~15-45ms to a ~1500ms Haiku response — sub-3% relative,
  invisible to students.
- **Idempotent.** SELECT statements have no side effects.
  Speculatively running them on every call is wasteful at most,
  never harmful.
- **User-scoped.** All three queries filter on `user_id`. They can't
  leak data across students or do anything beyond what the
  caller's permissions already allow.
- **Bounded result size.** Each tool returns at most ~20 records
  (`lookup_order_history` caps at 20; entitlements + refunds are
  naturally small). The LLM's prompt context stays bounded.

For escalation specifically, post-LLM dispatch works because:

- The decision (escalate yes/no) is the LLM's; the dispatch
  (firing the tool, getting a real ticket) is the host's
- The student gets a single LLM round-trip for latency
- The phantom-ticket failure mode is closed by the
  always-overwrite-with-real-ticket contract

## Why this pattern does NOT work for D11+

D11 ships `senior_engineer` which calls
[Pass 3d §E.3 sandbox tools](../architecture/pass-3d-tool-implementations.md)
— `run_static_analysis`, `run_in_sandbox`, `run_tests`. These have
the opposite properties:

- **Expensive.** Each `run_in_sandbox` call is a 3–15-second E2B
  invocation that costs real money.
- **Side effects.** A sandbox run can write files, hit the network
  (when explicitly allowed), consume the student's daily cost
  budget. Speculative calls would burn budget on questions that
  don't need them.
- **Not user-scoped in the same way.** The sandbox doesn't take
  a `student_id`; cross-student isolation is enforced by the
  sandbox's own ephemeral nature.
- **Conditional.** Whether to run a sandbox call depends on the
  student's question content (no point running tests if the
  question is "what's a closure?"). Only the LLM has the context
  to decide.

D11 is **forced** to wire proper Anthropic tool-use because
speculative-call shortcuts wouldn't be safe.

## Migration plan: when D11 lands proper tool-use, retrofit billing_support

Once D11 ships the proper tool-use protocol in `AgenticBaseAgent`
(probably as a new helper like `self.run_with_tools(messages,
tools, ctx)` that loops on tool_use blocks):

1. **Remove `_gather_lookup_data` from billing_support.py.**
   Speculative reads come out; the LLM decides what to call.
2. **Remove `_dispatch_escalation_if_requested`.** The post-LLM
   escalation dispatch hack goes; the LLM emits a `tool_use`
   block for `escalate_to_human` and the protocol handler fires
   it inline.
3. **Update the agent's `run()`** to use the new helper and pass
   the four billing tools in.
4. **Keep the regression tests** — they pin the contract that
   "the LLM's claimed ticket id is never trusted; the real
   tool result is always authoritative." That contract holds
   under both the post-LLM dispatch shape and the proper
   tool-use shape.
5. **Update Pass 3c E1's prompt** to remove the explicit
   instruction "use lookup tools before answering" — the LLM
   sees the tools directly in its system context and the protocol
   handles invocation; the prompt instruction becomes redundant.

## Why we're not doing it now

D11 isn't planned to start until D10 closes. Wiring the proper
protocol as part of D10 Checkpoint 3 would (a) double D10's scope,
(b) couple billing_support's correctness to a brand-new untested
infrastructure, (c) delay closing the four-tool gap that
billing_support needs to actually work.

The pragmatic shortcut + the regression tests + this followup doc
together give us:

- A working billing_support today (real tool calls, no phantom tickets)
- A clear migration path when the proper protocol lands
- A pinned contract (the LLM's claimed ticket is never trusted)
  that survives the migration

## Cross-references

- [backend/app/agents/billing_support.py](../../backend/app/agents/billing_support.py)
  — `_gather_lookup_data` (speculative reads),
  `_dispatch_escalation_if_requested` (post-LLM escalation dispatch)
- [backend/tests/test_agents/test_billing_support.py](../../backend/tests/test_agents/test_billing_support.py)
  — three pin tests covering the LLM-trust contract:
  phantom-ticket replaced with real, tool-failure null + support
  email surfaced, no-escalation when LLM doesn't request one
- [docs/architecture/pass-3c-agent-migration-playbook.md](../architecture/pass-3c-agent-migration-playbook.md)
  E1 — billing_support's spec (the prompt that instructs the LLM
  to call the tools)
- [docs/architecture/pass-3d-tool-implementations.md](../architecture/pass-3d-tool-implementations.md)
  §F.1 — billing tool spec; §E.3 — sandbox tools that force D11
  to wire proper tool-use

## Tag

**Non-blocking; pragmatic shortcut with documented migration path.**
D10 ships speculative + post-LLM dispatch. D11 wires the proper
protocol naturally because sandbox tools demand it. Retrofit
billing_support during D11 sign-off or as a focused mini-deliverable
between D11 and D12.
