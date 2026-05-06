# Migration verification discipline — patterns from D10, D11, MiniMax activation, D12

**Status:** Open. Canonical patterns for D13+ migrations.
**Created:** 2026-05-07 (D12 closure, rewritten from git history).
**Cross-references:**
- `agent-tool-call-discipline.md` (D12-derived sibling patterns; extends Pattern 4)
- `asyncpg-rollback-discipline.md` (Pattern 5)
- `anthropic-tool-use-protocol.md` (Pattern 7 deferred-protocol context)
- `schema-aware-server-side-validation.md` (Pattern 11)
- `llm-output-token-budget-calibration.md` (Pattern 12)
- `minimax-throughput-platform-characteristics.md` (Pattern 14 background)
- `llm-latency-provider-awareness.md` (Pattern 13)

## What this is

D10 (billing_support, 2026-05-03 → 05-04), D11 (senior_engineer, 2026-05-04 → 05-05), MiniMax activation (2026-05-05), and D12 (career bundle, 2026-05-06 → 05-07) collectively migrated five agents to the AgenticBaseAgent surface and switched the active LLM provider. Across that arc, a set of disciplines emerged — some surfaced by bugs, some by architectural decisions, some by cumulative observation. This doc captures them as a numbered list so D13+ migrations can walk them in order rather than re-derive from history.

The patterns are sourced from primary commits (terminal SHAs `27b86ac` D10, `cc9b632` D11, `22eaa53` MiniMax activation, `c1f941a` D12) and the follow-up docs each commit referenced. Pattern numbering reflects the order of surfacing across the engagement, not severity or priority.

## Patterns

### Pattern 1: Per-checkpoint scope discipline (CP1 → CP2 → CP3 → CP4)

The migration template established in D10 (Pass 3c §A.10) and validated through D11 + D12 follows four checkpoints with narrow, sequential scope:

- **CP1 (capability):** flip `available_now`, declare output schema, register tools (universal + agent-specific), apply DB migrations. No agent class yet.
- **CP2 (implementation):** write the v2 agent class (AgenticBaseAgent subclass), deploy the canonical prompt, wire to `_agentic_loader`. Stub-LLM smoke. Legacy file coexists in AGENT_REGISTRY during this window.
- **CP3 (verification):** real-MiniMax verification, schema audit, prompt + parser fixes, timeout calibration, integration tests. The bug-surfacing checkpoint by design.
- **CP4 (cutover):** delete legacy, rename `_v2 → canonical`, drop registry entries + MOA routes, retirement-pin tests. Atomic.

**Discipline**: each checkpoint has a single deliverable shape. Scope creep across checkpoints is the most common cause of cutover slipping.

**Provenance**: D10 commits `16e6c43` (CP1) → `5834f84` (CP2) → `2032f69` (CP3) → `44bcdd4` (CP4 tests) → `27b86ac` (CP4 cutover); same shape D11 + D12.

### Pattern 2: Dual-registry coexistence during cutover window

D10 established the convention: the new AgenticBaseAgent class lives at `<agent>_v2.py` and registers via `_agentic_registry`; the legacy BaseAgent class at `<agent>.py` continues to register via `@register` to AGENT_REGISTRY. Two namespaces, two dispatch paths (`/api/v1/agents/chat` legacy MOA vs `/api/v1/agentic/{flow}/chat` canonical), no name collision.

The shim disappears at CP4: rename `_v2.py → <agent>.py` (overwriting legacy file), drop the AGENT_REGISTRY entry, drop legacy MOA keyword routes. Retirement-pin test asserts `AGENT_REGISTRY` no longer contains the agent name.

**Discipline**: don't try to make both paths reach the same code during the cutover window. Two implementations is fine; the `_v2` suffix is the load-bearing signal that this is migration-in-progress code.

**Provenance**: D10 closure commit `27b86ac`; D11 commit `115921f` follows the same shape; D12 commit `c1f941a` deviates only in that `tailored_resume_llm.py` is kept (it's the inner LLM helper, not the chat-path agent) — `@register` is dropped but the file stays.

### Pattern 3: Data migrations ship in a separate commit from the code that uses them

D11 produced two commits at closure: `115921f` (CP4 cutover code) and `cc9b632` (separate `data(agents):` commit consolidating `agent_name` rows from legacy values to `senior_engineer`). The shape is intentional — code is reviewable as one unit, data backfill as another, and rollback discipline is clearer (revert code without leaving stale data; or revert data without leaving stale code).

D12 has zero data backfills; the architectural change (career_coach + resume_reviewer renames at CP4) didn't require row-level updates because no historical `agent_actions` rows used those names yet (the v2 agents only landed at this commit).

**Discipline**: when a migration touches existing rows (`agent_actions.agent_name` rewrites, foreign-key consolidations, etc.), produce a `data(agents):` or `data(<scope>):` commit separate from the code change. Schema migrations in `alembic/versions/` ride with the code that depends on them.

**Provenance**: D11 commits `115921f` + `cc9b632`. D12 migration `0060_goal_contracts_schema_fix.py` rode with the D12 code commit because the schema column was net-new (no rows to backfill).

### Pattern 4: Bundle migrations multiply template errors

D12 migrated 4 agents in one deliverable (career_coach, study_planner, resume_reviewer, tailored_resume) using a templated CP2 approach. The template misremembered `ToolExecutor`'s API. The error propagated to **3 of 4 agents identically** (the 4th, tailored_resume, doesn't use ToolExecutor). CP2 stub-LLM smoke + mock-based unit tests both bypassed real tool dispatch, so the bug was dormant for the duration of CP1, CP2, and the first half of CP3.

D11 (single-agent migration of senior_engineer) caught real bugs at stub smoke because there was one agent to write, not four. D10 (single-agent migration of billing_support) similarly caught its bugs early.

**Discipline**: for bundle migrations, verify the FIRST agent end-to-end (real-LLM, real tool dispatch) BEFORE writing the second agent. Template errors caught at agent #1 cost are dramatically cheaper than template errors caught at agent #N cost during CP3 verification.

**Provenance**: D12 CP3 Bug 5 (ToolExecutor API mismatch). See `agent-tool-call-discipline.md` Pattern 4.

### Pattern 5: asyncpg-rollback discipline for fail-soft DB reads

Any function that catches DB exceptions inside an active asyncpg transaction MUST call `await session.rollback()` to recover the transaction state. Without rollback, downstream statements on the same session fail with `InFailedSQLTransactionError` (asyncpg-level) or `PendingRollbackError` (SQLAlchemy-level), often manifesting as confusing `specialist_error` failures far from the original failure site.

D10 surfaced this when `agentic_snapshot_service._load_goal_contract` had a column-name bug and a fail-soft `try/except`; the catch returned cleanly but the next session statement (an `agent_call_chain` INSERT) tripped `InFailedSQLTransactionError` and broke dispatch. Fix landed as a separate commit (`21ff4f6`) ahead of D10 CP3.

**Discipline**: every fail-soft DB read tool wraps `await session.rollback()` in its own try/except inside the outer except clause, so a rollback failure never shadows the original error. Pattern is documented in `asyncpg-rollback-discipline.md`. D12 Phase 1 audit verified all D12 tool readers comply.

**Provenance**: D10 commit `21ff4f6` (initial fix); D12 Phase 1 schema audit verified compliance across all four D12 v2 agents' tool readers. See `asyncpg-rollback-discipline.md`.

### Pattern 6: Phantom-emission contract — never trust LLM-emitted IDs for state writes

LLMs sometimes emit fictional IDs (escalation_ticket_id="TKT-FAKE-555") or non-null values where they should emit null. The agent must NOT trust these emissions for state-affecting decisions or for what gets written to the audit row.

D10's billing_support has an `escalate_to_human` tool. The LLM can request escalation by setting `suggested_action="contact_support"` in its output. The dispatch contract: gate the tool firing on `suggested_action="contact_support"` only (not on the LLM's emitted ticket_id), then OVERWRITE the LLM's `escalation_ticket_id` with the real value from the tool result. Symmetrically, when `suggested_action != "contact_support"`, force `escalation_ticket_id = None` to discard any phantom value the LLM hallucinated in the inverse direction.

The contract: `escalation_ticket_id` is non-null IF AND ONLY IF the agent actually fired the tool successfully. Neither direction trusts the LLM.

This pattern emerged twice — once in D10 CP3 (Q4 phantom-escalation) and once during MiniMax activation (commit `22eaa53`) when MiniMax's null-emission shape exposed an asymmetry in the original D10 fix. The D10 fix gated on `suggested_action="contact_support" AND ticket_id != None`; the second condition broke under MiniMax's null shape. Re-fix made the gate symmetric.

**Discipline**: for any tool that writes state (escalations, plan commits, memory writes), the gate is the LLM's INTENT (a discriminator field), not the LLM's EMITTED IDENTIFIER. After the tool fires, overwrite the LLM's emitted ID with the real one. In the inverse direction, force the field to None.

**Provenance**: D10 Checkpoint 3 commit `2032f69`; MiniMax activation commit `22eaa53` (symmetric fix). 5 pin tests in `test_billing_support.py`.

### Pattern 7: Speculative read-tools vs full Anthropic tool-use protocol — explicit tradeoff

D10's billing_support `run()` speculatively calls 3 read tools (lookup_order_history, lookup_active_entitlements, lookup_refund_status) at the start of every call rather than exposing them through Anthropic's native `tools=[...]` parameter. Reads are cheap (~5-15ms each, indexed); the LLM gets pre-fetched context in its system message; no multi-turn tool-use round-tripping.

D12 followed the same pattern (career_coach + study_planner + resume_reviewer + tailored_resume's inner LLM helper all use speculative reads, not native tool-use).

**Discipline**: prefer speculative reads when the read set is small (≤5 tools), each read is cheap (<50ms), and the agent's prompt fits the results in its system context. Reach for native Anthropic tool-use when the read set is large, expensive, or conditional (the LLM should pick which tools to fire). The migration plan for the latter is documented in `anthropic-tool-use-protocol.md`.

**Provenance**: D10 commit `2032f69`; same pattern across D11 and D12. `anthropic-tool-use-protocol.md` documents the migration path for agents that grow past the speculative-read complexity ceiling.

### Pattern 8: Real-LLM verification at CP3 with recorded fixtures + opt-in live tests

D11 CP3 (commit `1348b21`) fired three real-MiniMax calls during verification, captured the responses as test fixtures, and produced two kinds of test coverage:

1. **Always-on regex contracts** against the recorded fixtures (e.g., `test_pr_review_response_has_no_execution_claims` checks the recorded CP3 response has zero VIOLATION_PHRASES matches). These run cheaply in CI on every commit; pin the contract as it held when CP3 closed.
2. **Opt-in live-LLM assertions** marked `@pytest.mark.real_llm`, fired only when the founder explicitly runs them with `MINIMAX_API_KEY` set. They verify the contract still holds against the active provider.

D12 CP3 Phase 4 added a third kind: **diagnostic scripts** (`scripts/d12_cp3_phase4_*.py`) that bypass the orchestrator wrapper to measure pure-LLM behavior. Used to surface Bug 11 (SDK timeout root cause) and Bug 16 (max_tokens calibration).

**Discipline**: every CP3 produces (a) at least one recorded-fixture regex contract pinning a spec'd output property, (b) optionally an opt-in live-LLM test for the same property, (c) optionally a diagnostic script when measurements are needed. Don't ship CP3 without (a) — recorded fixtures are the cheap continuity guarantee.

**Provenance**: D11 commit `1348b21`; D12 commits `c1f941a` (D12 Phase 4 diagnostic scripts at `backend/scripts/`).

### Pattern 9: Stub-LLM smoke catches surface bugs cheap; misses post-LLM dispatch

CP2 stub-LLM smoke (a unit test that injects a fake LLM response and runs the agent's full path) caught real bugs in D10 and D11 — both single-agent migrations. In D12 (bundle migration), CP2 stub smoke verified Supervisor routing and prompt loading but did NOT exercise `_parse_output → output schema → write paths`. Bugs 1 + 2 (study_planner_v2 calling tools with wrong kwargs) were dormant past CP2 because the stub LLM didn't return mode-shaped output that triggered the post-LLM commit_plan path.

**Discipline**: CP2 stub-LLM smoke must include stub responses that exercise every post-LLM tool dispatch path. For multi-mode agents (study_planner's three modes, mock_interview's four formats), include at least one stub response per mode. Don't conflate "the LLM call fired" with "the agent works."

**Provenance**: D12 CP3 Part F (Bugs 1 + 2). See `agent-tool-call-discipline.md` Pattern 2.

### Pattern 10: Mock-based unit tests hide tool-API drift

Mocking `ToolExecutor` with `MagicMock` (which accepts any kwargs) hid the fact that D12's CP2 agents called `ToolExecutor(session=ctx.session, user_id=ctx.user_id, permissions=...)` against an actual constructor signature of `ToolExecutor(session, *, max_retries, retry_backoff_seconds)`. Both the agent code AND the test code matched a fictional API; the mismatch with the real API was invisible until D12 CP3 Phase 4 fired real calls.

**Discipline**: every agent with tool calls has at least one **real-instantiation integration test** (not mocked) that exercises the tool dispatch layer end-to-end. The test catches constructor signature drift, method name drift, missing context arguments, and other API contract mismatches that mocks paper over. The pattern lives at `tests/test_agents/test_<agent>_v2_tool_calls.py::test_real_tool_executor_integration` for each D12 agent.

**Provenance**: D12 CP3 Part H (Bug 5). See `agent-tool-call-discipline.md` Pattern 3.

### Pattern 11: Schema-aware server-side validation for non-Anthropic providers

Prompt-level constraint emphasis ("HARD LIMIT: 200 characters") is unreliable under MiniMax. D12 CP3 Phase 4 surfaced three iterations of `max_length` overshoots on resume_reviewer even with explicit framing. The architectural fix: route the parsed dict through `parsing_helpers.truncate_to_schema(...)` before `model_validate`. Schema is canonical; LLM produces best-effort; server enforces.

Two siblings of the same root cause (Pattern 5/6 in `agent-tool-call-discipline.md`):
- Prompt schema-shorthand drops Literal allowlists (D12 Bug 14): `"day_of_week"` without enumerating `"Mon"|"Tue"|...` produces integer guesses.
- Prompt schema-shorthand drops nested-object field types (D12 Bug 15): `"WeeklyFocus objects (week, theme, ...)"` without specifying field types produces shape guesses.

**Discipline**: for any agent producing structured output through Pydantic validation, route the parsed dict through `truncate_to_schema` before `model_validate`. For Literal allowlists, enumerate the values inline in the prompt's output schema section in canonical pipe-separated form (`"Mon" | "Tue" | ...`). For nested objects, enumerate every field's type and constraint per nested object class.

**Provenance**: D12 CP3 Phase 4 Bug 17 (architectural). See `schema-aware-server-side-validation.md` for full discussion + extension scope (Literal allowlist coercion, type coercion).

### Pattern 12: Multi-layer timeout composition

The orchestrator's `asyncio.wait_for` wrapper around `callee.run_agentic` is the FIRST line of defense, but it composes with two more layers:

1. **SDK-level per-attempt timeout** (`_LLM_TIMEOUT_S` in `llm_factory.py`) — 30s in D10/D11, raised to 90s in D12 CP3 Phase 4 Bug 11.
2. **SDK-level retry budget** (`_LLM_MAX_RETRIES`) — 3 in D10/D11, dropped to 1 in D12. With 3 retries × 30s timeout, a single LLM call could burn 90+ seconds before raising — making the orchestrator wrapper irrelevant.

D12 Bug 11's root cause was the SDK timeout, not the orchestrator wrapper. Career_coach took 45s under MiniMax; the SDK gave up at 30s, retried 3x, no useful response ever returned. The orchestrator wrapper never got a chance to fire.

**Discipline**: when calibrating `typical_latency_ms` for a new agent, verify the SDK-level timeout is at least 1.5x the expected single-call P50. If not, raise `_LLM_TIMEOUT_S`. Drop `max_retries` to 1 so retry loops can't burn the wrapper budget. The per-agent dispatch timeout (capability.resolve_timeout_seconds) is the correctness budget; the SDK timeout is the network-blip budget.

**Provenance**: D12 CP3 Phase 4 (Bug 11). See `agent-tool-call-discipline.md` Pattern 8.

### Pattern 13: Provider-aware capability metadata (latency + cost)

`AgentCapability.typical_latency_ms` is currently provider-agnostic — one number per agent. In production reality it's provider-specific: career_coach takes 45s on MiniMax vs. estimated 12-15s on Anthropic Sonnet. The numbers shipped today are MiniMax-flavored because that's the active provider; they don't apply if Anthropic fallback ever lands.

`AgentCapability.typical_cost_inr` has the same property — pricing is per-provider. The pricing table in `_PRICING_USD_PER_1M` captures both providers, but the AgentCapability metadata captures only one number.

**Discipline**: calibrate against the active provider during CP3. Document the provider context in the capability docstring. If multi-provider routing lands (Anthropic fallback for safety classifier, etc.), refactor to `typical_latency_ms_by_provider: dict[Literal["anthropic", "minimax"], int]`. D17 cleanup territory; not a near-term blocker.

**Provenance**: D12 CP3 Phase 4 (calibration table); MiniMax activation phase 1.1 audit (which missed parallel ChatAnthropic builders that bypassed `build_llm`, surfaced in commit `049a087`). See `llm-latency-provider-awareness.md` and `minimax-throughput-platform-characteristics.md`.

### Pattern 14: max_tokens calibrated from measurement, not defaults

`max_tokens` defaults set against Anthropic-era output sizes don't account for (a) MiniMax thinking blocks (~38% of output tokens) or (b) post-Bug-15 schema enumeration in prompts (explicit field type listings make models produce more comprehensive outputs). D12 CP3 Phase 4 Bug 16 surfaced this when career_coach truncated mid-JSON at `max_tokens=2048`.

The pure-LLM diagnostic pattern (`scripts/d12_cp3_phase2_diagnose_llm.py` for study_planner; `scripts/d12_cp3_phase4_career_coach_pure_llm.py` for career_coach) measured actual output token usage. The fix raised smart-tier default from 4096 → 8192 in `_DEFAULT_MAX_TOKENS_BY_TIER`, with all four D12 v2 agents explicitly requesting 8192.

**Rule of thumb**: `max_tokens >= 2 × (expected text-only output tokens) + 50% thinking margin`. Lightweight classifier-style agents (route decisions, structured-yes/no calls) keep low explicit values (e.g., 30 for the route classifier).

**Discipline**: for any new agent, run the pure-LLM diagnostic at CP2 stub-smoke time. Read `usage_metadata.output_tokens` from a representative call. Set production `max_tokens` to 2x measured + margin. Don't blanket-apply 8192 to lightweight agents.

**Provenance**: D12 CP3 Phase 4 Bug 16. See `llm-output-token-budget-calibration.md`.

### Pattern 15: Audit at the primitive layer, not just the abstraction layer

MiniMax activation Phase 1.1's audit grepped `estimate_cost_inr` and `model_name` callers — both correct grep targets for cost tracking, both blind to LLM clients that don't track cost. Two parallel `ChatAnthropic` constructors (in `supervisor.py` and `primitives/safety/llm_classifier.py`) bypassed `build_llm()` entirely. Phase 2 verification surfaced the gap: under MiniMax-only configuration, the canonical agentic endpoint returned 500 because the Supervisor was the first hop and crashed on missing `ANTHROPIC_API_KEY`.

The discipline going forward: when investigating any subsystem with an abstraction layer, grep BOTH the abstraction (`build_llm()`) AND the underlying primitive (`ChatAnthropic()`). The primitive grep is the one that catches the bypass.

**Discipline**: every CP3 schema/API audit greps both the named helper AND its underlying class/protocol. D12 Phase 1 audit followed this pattern (audited tool readers' `text(...)` queries against actual DB columns, not just the tool's interface contract).

**Provenance**: MiniMax activation commit `049a087`. The pattern is captured as Sibling 4 of the implicit-state-assumption meta-pattern in `asyncpg-rollback-discipline.md`.

## Application guide

When starting a new agent migration (D13+), walk these patterns in order and confirm each is addressed:

**At CP1** (capability + schema):
- Pattern 1: scope is narrow (capability flip + schema + tools registered, no agent class yet)
- Pattern 5: every fail-soft DB read tool has the asyncpg-rollback wrapper
- Pattern 7: decide speculative-reads vs native-tool-use; if speculative, list the read set in the agent's run()
- Pattern 13: calibrate `typical_latency_ms` against the active provider; document in the capability docstring
- Pattern 14: estimate output token budget; don't blanket-apply smart-tier default to lightweight agents

**At CP2** (agent class + prompt):
- Pattern 2: legacy and v2 coexist; suffix is `_v2`
- Pattern 4: if bundle migration, write the FIRST agent end-to-end and verify with real-LLM before writing the rest
- Pattern 6: write paths gate dispatch on intent (a discriminator), not on LLM-emitted IDs
- Pattern 9: CP2 stub-LLM smoke includes one stub per mode if the agent is multi-mode
- Pattern 10: include at least one real-instantiation integration test for tool dispatch
- Pattern 11: prompt enumerates Literal allowlists + nested-object field types; output goes through `truncate_to_schema` before `model_validate`
- Pattern 12: confirm SDK-level timeout is ≥ 1.5x expected P50; bump `_LLM_TIMEOUT_S` if needed

**At CP3** (verification):
- Pattern 8: real-LLM verification produces recorded fixtures + opt-in live tests + diagnostic scripts
- Pattern 11: server-side truncation verified live (helper fires when LLM overshoots; debug logs visible)
- Pattern 14: actual output token usage measured; max_tokens recalibrated if measurement diverges from estimate
- Pattern 15: schema/API audit greps both the abstraction and the primitive layer

**At CP4** (cutover):
- Pattern 1: atomic — rename _v2 → canonical, delete legacy, drop AGENT_REGISTRY entry, remove MOA routes
- Pattern 2: retirement-pin test asserts AGENT_REGISTRY no longer contains the agent
- Pattern 3: data backfill (if any) lands as a separate `data(...)` commit

## Cost guidance

D10 closed at unmeasured cost (no real-LLM verification — Anthropic key was not set during D10). D11 closed at ~₹0.30 (three real-MiniMax calls in CP3). D12 closed at ~₹3.40 (4-phase CP3 with iterative bug fixing across Bugs 16/17). With Patterns 1-15 documented here, D13+ should fit in **₹1.50-2.00 per single-agent migration**; allocate **₹2.50** as the safe budget.

Bundle migrations (D14 + D15 are bundle candidates) should budget per-agent (Pattern 4) and add ~30% margin for template-error verification.

## Triage for retroactive application to D10/D11

D10 (billing_support) and D11 (senior_engineer) shipped before Patterns 11, 14, and 15 were articulated. They work in production but may surface Pattern-11-flavored issues if their prompts ever overshoot string limits, and Pattern-14-flavored issues if their max_tokens defaults turn out to be tight under future schema expansions. **D17 cleanup territory**: backfill `truncate_to_schema` to billing_support + senior_engineer parsers; audit their prompts against Pattern 11 enumeration discipline; verify their `max_tokens` against measured output.

## Cross-references

- `agent-tool-call-discipline.md` — D12-derived sibling patterns (extends Patterns 4, 9, 10, 12 with code-level detail)
- `asyncpg-rollback-discipline.md` — Pattern 5 canonical statement
- `anthropic-tool-use-protocol.md` — Pattern 7 deferred-protocol context
- `schema-aware-server-side-validation.md` — Pattern 11 architectural detail
- `llm-output-token-budget-calibration.md` — Pattern 14 architectural detail
- `minimax-throughput-platform-characteristics.md` — Pattern 13 background data
- `llm-latency-provider-awareness.md` — Pattern 13 future scope
- `llm-cost-tracking-silent-zero.md` — Pattern 6 cost-tracking sibling instances
- `handoff-protocol-d11-d13.md` — Option B handoff convention used across D11 + D12
