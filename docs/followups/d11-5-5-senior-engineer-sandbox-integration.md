# D11.5.5 — senior_engineer ↔ sandbox tool integration

**Status:** Deferred. D11.5 ships sandbox infrastructure (run_in_sandbox + run_tests tools, registered, capability-gated, ToolExecutor-integrated). senior_engineer was shipped at D11 with explicit LLM-only design — capability description, module docstring, and prompt all forbid execution claims. **D11.5 does NOT retrofit senior_engineer** because doing so requires a UX/quality decision beyond infrastructure plumbing.
**Created:** 2026-05-07 (D11.5 Stage 3.4 audit).
**Triage:** Post-D14 if any D14 deliverable needs senior_engineer execution. If D14b/D14c don't trigger the question, defer to D17 cleanup or production-data signal.
**Cross-references:** D11 senior_engineer commit (`cc9b632`); D11.5 sandbox infrastructure; `prompts/senior_engineer.md`; `capability.py` senior_engineer entry; pass-3d-tool-implementations.md §B (lists senior_engineer as a sandbox consumer).

## State as of D11.5 Stage 3.4 audit

State (d) — sandbox tools absent from senior_engineer entirely. Definitive evidence across four inspection points:

| Inspection point | Finding |
|---|---|
| `capability.py` senior_engineer entry | Description says: *"v1 is LLM-only — does NOT execute code, run tests, or run static analysis (sandbox tools land in D14)."* No tool list field references run_in_sandbox or run_tests |
| `senior_engineer.py` agent class | Module docstring: *"Sandbox tools (run_in_sandbox, run_static_analysis, run_tests) per Pass 3d §E.3 are deferred to D14. The deployed prompt explicitly forbids execution claims; the agent reasons about code as text only."* No sandbox tool_call invocations |
| `prompts/senior_engineer.md` | Line 15: *"You do NOT have access to a code execution sandbox. Do not claim to have run the code, run tests, or executed static analyzers."* Lines 23-26 give explicit "do not say I ran/executed" examples |
| `tools/agent_specific/senior_engineer/` | Two tools only (`lookup_prior_reviews`, `lookup_prior_submissions`); no sandbox tool exists |

senior_engineer's `inputs_optional=["test_results"]` indicates D11 expected test results to be passed IN as context (caller-driven), not produced via tool (LLM-driven).

## Why D11.5 doesn't retrofit

Adding `run_in_sandbox` + `run_tests` to senior_engineer's capability tool list raises a UX/quality question that's beyond infrastructure plumbing:

1. **Pure tool registration without prompt change** — adds capability surface area but the prompt-aligned LLM won't invoke it (the prompt forbids execution claims). Degenerate state: tool present, never used.
2. **Tool registration + prompt rewrite** — real D11 behavior change. Requires:
   - Decision on whether senior_engineer should execute on demand
   - Updated prompt allowing execution claims with appropriate guardrails (don't over-claim, don't execute speculatively, don't claim execution without invoking the tool)
   - Live verification under MiniMax that the LLM uses the tool sensibly
   - Coordination with current senior_engineer consumers that expect no-execution behavior

Either choice is downstream of "ship the sandbox infrastructure." D11.5's deliverable is the infrastructure; D11.5.5 is the senior_engineer consumer wiring with proper UX consideration.

## Required investigation for D11.5.5

1. **Decision: LLM-driven vs caller-driven execution.**
   - LLM-driven: senior_engineer's prompt explicitly invites the LLM to invoke `run_tests` when test execution would help its review. Requires prompt rewrite + guardrails.
   - Caller-driven: D11.5.5 may not be needed at all — whichever flow drives senior_engineer (chat path, CP-evaluator path, etc.) calls `run_tests` upstream and passes results in via `test_results` input field. senior_engineer's prompt stays unchanged.
2. **If LLM-driven**: write the prompt rewrite. Pin the new behavior with stub-smoke tests that verify the LLM invokes the tool when appropriate but doesn't claim execution it didn't do. Live-LLM verification under MiniMax.
3. **If caller-driven**: identify which upstream flows would benefit from passing test results to senior_engineer. Wire them. No senior_engineer changes.
4. **Coordination check**: any current senior_engineer test that asserts "no execution claims in output" needs review before LLM-driven option lands.

## Why this isn't a D17 cleanup item

D17 is reserved for production-readiness backfills. The senior_engineer ↔ sandbox question is product-shaped (does the agent's UX include execution?), not a tech-debt item. If a D14 deliverable surfaces a concrete need for senior_engineer to execute (e.g., D14c project_evaluator wants to delegate execution to senior_engineer), this becomes D14-prerequisite work. Otherwise it stays here as a registered deferral.

## Cross-references

- [backend/app/agents/senior_engineer.py](../../backend/app/agents/senior_engineer.py) — D11-shipped agent class with explicit "deferred to D14" docstring
- [backend/app/agents/prompts/senior_engineer.md](../../backend/app/agents/prompts/senior_engineer.md) — prompt with explicit execution-claim prohibitions
- [backend/app/agents/capability.py](../../backend/app/agents/capability.py) — senior_engineer capability entry
- [backend/app/agents/tools/agent_specific/sandbox/](../../backend/app/agents/tools/agent_specific/sandbox/) — D11.5 sandbox tools registered and ready for whichever agent consumes them
- D11.5 closure commit (pending) — full Stage 3.4 audit + Option 1 deferral rationale
