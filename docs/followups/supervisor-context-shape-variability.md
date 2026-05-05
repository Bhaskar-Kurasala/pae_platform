# Supervisor Context Shape Variability vs Agent Input Schemas

## Status

Open. Workaround applied per-agent at D10 CP2 (billing_support) and
D11 CP2 (senior_engineer).

## Pattern

Each agent's spec defines its expected input shape (per Pass 3c
E*). The Supervisor constructs context via an LLM call whose
`constructed_context` dict shape is decided per-call, and that
shape doesn't always match the agent's expected fields.

Examples observed in production migrations so far:

- **billing_support's `grace_period` field (D10 CP2 surface)** — the
  Supervisor sometimes omitted the `grace_period` field even when
  entitlement was free-tier and the agent needed to know about
  signup grace.
- **senior_engineer's `code` field (D11 CP2)** — the Supervisor's
  `constructed_context` used `"question"` as the key name instead
  of `"code"` for code-flavored requests, because
  `supervisor.md`'s in-prompt examples lean on `question` and
  `task` more than on shape-specific keys per agent.

## Workaround applied (per agent)

- Input schemas use `extra="ignore"` instead of `extra="forbid"`.
- Multiple field names accepted as synonyms with prioritized
  resolution (e.g., `resolved_code()` picks
  `code → question → task → user_message`).
- Fail-honest fallback when no recognized field is populated —
  the agent returns a chat_help-shaped output asking the student
  to re-share, rather than raising (raise → `specialist_error` →
  500).

## Why this isn't ideal

- **Hides Supervisor prompt regressions.** If `supervisor.md`
  drifts further from agent shapes, no signal until students
  complain. The agent silently absorbs the mismatch.
- **Each agent migration adds boilerplate field-resolution
  logic.** D11 reuses the pattern; D12's career bundle (4 agents)
  will need it 4 more times.
- **Couples agent input schemas to Supervisor prompt history.**
  An agent's input schema reflects what Supervisor *currently*
  emits, not what the agent *should* receive.

## Long-term resolution

Make Supervisor prompt shape-aware: include per-agent input
examples in `supervisor.md` so the LLM's `constructed_context`
matches each agent's expected shape. When this ships, per-agent
input schemas can tighten back to strict (`extra="forbid"`,
required fields enforced).

The technical work:

1. Per-agent input examples added to `supervisor.md` showing the
   exact `constructed_context` shape Supervisor should emit for
   each `target_agent`. Agents with `inputs_required=["code"]`
   get an example with `{"code": "..."}`; agents with
   `inputs_required=["question"]` get `{"question": "..."}`.
2. Optional: pin via a Supervisor pin-test that verifies
   `constructed_context` keys for each routed agent match the
   target's `inputs_required` declaration.
3. Migrate per-agent input schemas back to `extra="forbid"` once
   the supervisor prompt is verified shape-stable.

## Triage

Triage to **D17** (operational dashboards + Supervisor prompt
evolution) **OR** post-launch when production data shows where
Supervisor shape mismatches actually bite. Not blocking; the
workaround handles all known cases.

If a future migration (D12, D13, D14, D15, D16) hits a third
agent that needs the workaround, that's stronger signal that the
long-term resolution should be brought forward.

## Cross-references

- Pass 3b §4.2 — Supervisor prompt construction
- Pass 3c E1, E2 — agent specs that diverged from what Supervisor
  emits
- `backend/app/agents/billing_support.py` — D10 CP2 deviation
  (grace_period handling, BillingSupportInput shape tolerances)
- `backend/app/agents/senior_engineer_v2.py` —
  `SeniorEngineerInput.resolved_code()` + D11 CP2 deviation
- `backend/app/agents/prompts/supervisor.md` — the source of
  the `constructed_context` shape decisions
