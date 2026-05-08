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

### Pattern 16: Real-LLM harness setup must call BOTH loaders

`load_agentic_agents()` populates the agent registry by importing each agent module so its `__init_subclass__` hook fires; `ensure_tools_loaded()` populates the tool registry by importing each `@tool`-decorated function. The two registries are independent. Production paths (FastAPI startup at `app/main.py`, Celery worker boot at `app/core/celery_app.py`) call BOTH. Out-of-process harnesses that drive `call_agent` directly (CP3 verification scripts, ad-hoc diagnostics) commonly only call the agent loader and silently get `Tool 'memory_recall' not registered` failures the moment the agent's `run()` invokes a universal tool.

**Discipline**: every out-of-process harness or test fixture that invokes `call_agent` must call both `load_agentic_agents()` and `ensure_tools_loaded()` at startup. The two-line pairing is canonical; pin it in CP3 harness templates so it isn't reinvented per migration.

**Provenance**: D13 CP3 first attempt — Phase 1 hit `Tool 'memory_recall' not registered. Available: <none>` because the harness only loaded agents. The cascade ate the dispatch budget on a retry path; root cause was 4 hours into the diagnostic. See `docs/followups/agentic-loader-fastapi-startup.md` for the production-side wire-up.

### Pattern 17: First-flip primitive verification before agent-level CP3 phases

When a migration is the FIRST to flip a primitive flag (`uses_self_eval`, `uses_proactive`, etc.), the corresponding code path has never executed in production. Unit tests for those primitives exist (D7-era Critic tests, D7b-era proactive tests) but commonly stub the LLM or transport, missing real-provider integration gaps. Running the agent's CP3 verification IS NOT a substitute for primitive verification; failures under the agent's call path are 5+ frames deep, surface intermittently across retry paths, and burn the dispatch budget on diagnostic.

**Discipline**: at CP1, identify which primitives the agent flips for the first time. For each, write a standalone smoke that drives the primitive's real-provider integration directly (e.g., `Critic.evaluate(request="x", response="y")` against the real LLM, with `parsed_ok` asserted non-None). Run BEFORE CP3's agent-level phases. Cost: one cheap LLM call per primitive; payoff: bugs surface in seconds instead of half-hours.

**Provenance**: D13 mock_interview was the first v2 agent with `uses_self_eval=True`. Bugs 18 (Critic `build_llm(temperature=…)` TypeError) and 19 (Critic max_tokens=400 too small for MiniMax thinking blocks) both surfaced via agent-level CP3 retries, costing 2 stop-and-fix iterations at ~₹1 each. Standalone Critic smoke would have caught both in seconds.

### Pattern 18: Provider-aware tier collapse + MiniMax structured-output latency multiplier

Two related sub-patterns. Both stem from MiniMax M2.7 having different cost/latency characteristics than Anthropic models, despite sharing the `build_llm` abstraction.

**Sub-pattern 18a — tier collapse:** `build_llm(tier="fast")` is meaningful only on the Anthropic route, where it resolves to Haiku. Under MiniMax (`MINIMAX_API_KEY` set), both `tier="fast"` and `tier="smart"` collapse to MiniMax M2.7 (`llm_factory.py:77-78` documents this explicitly: *"MiniMax doesn't offer a separate fast model in this stack, so when MINIMAX_API_KEY is set both tiers route to the configured MiniMax model."*). Callers that reason about budget/latency assuming a Haiku-shaped output (no thinking blocks, tight responses, ~3s elapsed) are silently routed through M2.7 (~38% thinking-block tokens, ~16-31s elapsed, 40× per-call cost).

**Sub-pattern 18b — structured-output latency multiplier:** MiniMax structured-output agents (those producing nested Pydantic outputs with multiple required fields) consistently land at 2-3x their spec `typical_latency_ms` estimates because of thinking-block overhead. Pass 3c spec values are Anthropic-era and undersize MiniMax dispatch budgets across the board. This is platform-wide for structured-output agents, not Critic-specific.

**Discipline:**
- For tier-collapse (18a): when a caller declares a tier, audit whether their downstream assumptions (max_tokens budget, expected elapsed, expected output shape) actually hold under EVERY provider route the tier collapses to. If the assumption is Haiku-specific — and the caller is structurally fast-path infrastructure (Critic, classifier, intake-question selector) — bypass `build_llm` and construct `ChatAnthropic` directly when an Anthropic key is set, with the abstract-tier path as fallback. The architectural answer is provider-aware capability metadata, but the inline answer is direct construction.
- For latency multiplier (18b): treat spec `typical_latency_ms` values as Anthropic-era estimates. At CP1, set `timeout_override_seconds` preemptively at **spec × 4-5 multiplier** (rounded to a clean number). **Do NOT skip the override and rely on the formula budget** — D14b CP3 burned ~₹0.33 in calibration timeouts because the spec's 8000ms × 3 = 30s floor was insufficient. Tighten post-CP3 ONLY when **n ≥ 5 measurements exist**; tightening formula is **`observed_p95 × 1.30` OR `observed_max × 1.50`, whichever is larger**. At n=2-4, MiniMax tail-latency spread is wider than `observed_max × 1.30` absorbs (D14c CP4 evidence below). Never tighten on small samples alone.

**Provenance:**
- 18a: D13 Bug 19 — Critic was sized for Haiku (max_tokens=400); under MiniMax-only configuration the thinking block consumed the entire budget and the text block came back empty. Interim fix bumped max_tokens to 2048 (~₹0.20/Critic-call). Architectural fix routes Critic directly to Haiku via `ChatAnthropic` when `ANTHROPIC_API_KEY` is set (~₹0.005/Critic-call). See `docs/followups/critic-tier-routing-architectural.md`.
- 18b (preemptive sizing): Multiple data points across the engagement: D12 career_coach (90s spec, 150s override needed), D12 tailored_resume (60s spec, 120s override needed), D13 mock_interview (12000ms spec → 60s override after Critic added), D14b practice_curator (8000ms spec → 60s override after CP3 timeouts). The pattern holds across both single-shot and multi-turn agents, both Critic-enabled and Critic-free agents. Spec is Anthropic-era; override discipline is the post-MiniMax reality.
- 18b (tightening-formula refinement, D14c CP4): D14c set `timeout_override_seconds=90` preemptively at CP1 (= spec 20000ms × 4.5). CP3 measured 4 phases: P1 51.81s, P2 57.48s (rubric-grounded paths), P3 15.18s, P4 15.79s (refusal paths) — `observed_max × 1.30 = 75s`. CP4 attempted to tighten 90 → 75; the post-cutover smoke on the **same Phase 1 payload that ran 51.81s in CP3 timed out at 75.05s**, a 22s spread on identical input at n=2. Held at 90s preemptive. Lesson: `observed_max × 1.30` is an acceptable target *value* but not a safe tightening threshold at small n; MiniMax tail latency is wider than the n=2-4 max captures. Wait for n ≥ 5 before tightening.
- 18b (D15 reinforcement, multiple CPs): CP3 ran 4 real-LLM phases at career_coach (60s preemptive) + study_planner (existing 30s); all phases within budget, no tail timeouts. CP4 ran 4 real-LLM phases (with multi-turn for mock_interview) at the per-agent calibrated values; all within budget, again no tail timeouts. CP5 ran 1 e2e smoke phase at career_coach + 1 at study_planner; within budget. **Ten more deliverable data points across D14b, D14c, D15 confirm the pattern holds**: spec × 4-5 preemptive at CP1 is the safe default; MiniMax tail-latency under structured-output workloads is consistently wider than spec multiplied by typical safety factors. Pattern 18b ages well.

- **18b (D17b ITEM 3 prompt-size extension):** the original framing applied 18b to *LLM provider changes* (Anthropic → MiniMax). D17b ITEM 3's first attempt extended `study_planner.md` by ~80 lines for the prompt-side lead-in section. Real-LLM verification timed out 3 of 6 study_planner phases at the agent's existing 30s dispatch ceiling — the prompt addition pushed the LLM call's response generation past the budget that fit the pre-D17b prompt size. Switching to deterministic post-LLM composition (Path E) eliminated the prompt growth and timeouts dissolved. **Canonical extension:** Pattern 18b applies preemptively when **prompt size changes materially**, not only when the LLM provider changes. Pre-flight calibration (or a deliberate timeout bump in the same commit as the prompt change) is required when adding ≥ 50 lines to any agent prompt. The mechanism is the same — the LLM has more context to ingest + more constraints to satisfy + more output to generate to honor the new instructions — but the trigger is prompt size, not provider. D17b ITEM 3 evidence at study_planner: pre-D17b prompt 109 lines / 30s budget held; D17b prompt-side attempt 191 lines / 30s budget broke 50% of the time; D17b Path E (no prompt change, prepend post-LLM) restored the 30s budget. Provider stayed MiniMax across all three measurements; prompt size was the variable.

### Pattern 19: Capability adapter signatures should accept both Pydantic and dict from start

Adapter functions wired into capabilities (D13.5 `validation_input_adapter`) and tool-call argument builders (D12+ `_safe_tool` helpers) commonly receive dict-shaped data from the dispatch layer, NOT Pydantic instances. The dispatch layer normalizes outputs to dict via `model_dump(mode="json")` for audit + transport; adapters and helpers that assume Pydantic input crash on attribute access against a dict.

**Discipline:** when authoring an adapter callable or a tool-call argument builder for a v2 agent:
- Type the input as `SourceModel | dict[str, Any]` from the start
- At runtime, branch on `isinstance(input, SourceModel)` to extract fields; for the dict branch, use `.get()` with explicit type checks
- Defensive `TypeError` for non-dict / non-model inputs catches accidental misuse early
- Unit-test both shapes — pass a typed model AND a dict to the same adapter; both should produce the same output

The Pydantic-only signature is appealing for type safety but doesn't survive contact with dispatch-layer normalization. Dual-shape from start is the canonical pattern.

**Provenance:** D13.5 Stage 2 — `tailored_resume_to_reviewer_input` adapter was originally typed `(output: TailoredResumeOutput) -> ResumeReviewerInput`; live verification crashed because `call_agent` returned the producer's output as a dict. Widened to `TailoredResumeOutput | dict[str, Any]`. D14b CP2 surfaced the analog at the tool-call layer: `_safe_tool` passes dict-shaped args even when the tool's input schema is Pydantic; the wrong field name (`limit` vs `days`) was silently swallowed by the helper's exception handler before reaching the tool body. Both data points point to the same lesson: dispatch is dict-shaped; agent-side helpers should be dict-shape-tolerant from the start.

### Pattern 20: Closure-baseline test slices may miss latent assertion drift

Closure-time test baselines that run a narrow slice may miss tests that count or enumerate the capability registry. Future closures should either (a) run the full `tests/test_agents/` slice or (b) explicitly run `test_checkpoint3_dispatch.py::TestCapabilityRegistry::*` as a sentinel for any capability-list change.

**Discipline:** at every migration's CP1 (when capability is added) and CP4 (when cutover lands):
- Run `tests/test_agents/test_checkpoint3_dispatch.py::TestCapabilityRegistry` explicitly as part of the baseline
- Update the `migrated` set + declaration count in `test_thirteen_declarations` as part of CP1's working tree
- The repair is mechanical — counting failure means the test is a sentinel doing its job; treat it as a CP1 maintenance task, not a finding

**Provenance:** Three data points:
- D13 closure: mock_interview's `available_now=True` flip silently broke `test_thirteen_declarations` + `test_failure_class_b_invalid_target_falls_back`; D13's narrow closure slice missed both.
- D13.5 Stage 2: same tests still broken when broader slice ran; surfaced as part of D13.5's stale-assertion repair pass.
- D14b CP1: D14b's own capability addition triggered the same shape; caught and repaired in the same CP1 working tree.

The pattern is "every capability-list change touches this same test"; codify as a CP1 maintenance step, not a finding to be rediscovered.

### Pattern 21: Verification posture for content-generating-direct-to-user agents

Agents that produce output students directly consume (vs. coaching/review/evaluation that's processed by humans or downstream agents) require Phase 5-style subjective quality observation across Literal allowlist diversity. Schema invariants are necessary but not sufficient for these agents.

**Discipline:** at CP3, beyond the standard schema invariant verification:
- 3-4 real-LLM calls covering each major Literal value + the optional-input path (e.g., D14b practice_curator: easy/medium/hard × coding/system_design/all-empty)
- Subjective review captures pedagogical/content-quality observations as **informational** (not gating) findings: are exercises solvable, is content domain-appropriate, are hints progressive, do test cases match the problem
- Gating threshold: "clearly broken" (unsolvable, off-topic, unsafe) — not "imperfect"
- If a specific Literal value produces structurally wrong-shaped output (e.g., debugging-type exercise lacks broken starter_code, system_design exercise that's actually a coding problem), surface as prompt-quality finding; the relevant per-type prompt section is the prime suspect

**Discipline applies to:** D14b practice_curator (5 exercise types × 3 difficulties); D14c project_evaluator (rubric-grounded evaluations become portfolio entries — see D14c extension below); future agents like D17 mcq_factory (multiple choice questions → student-facing), D17 portfolio_builder (portfolio prose → student-facing).

**D14c extension — rubric-grounding check for evaluation agents:** when the agent's output is rubric-graded content that becomes a portfolio entry or graded artifact, Phase 5 quality observation MUST verify rubric-grounding at the dimension-by-dimension level: each output `dimension_name` matches a key in the source rubric, each `rubric_criterion` is a quote/paraphrase of the actual rubric language, evidence cites concrete artifacts (file names, function names, PR URLs) rather than generic praise. Gating threshold: "clearly invented" — dimension_name doesn't appear in rubric content, rubric_criterion is fabricated. Originally Pattern 21 was framed as "DOES NOT apply to content-processing agents"; D14c surfaced that evaluation agents producing portfolio entries straddle the line and DO need quality observation, just with rubric-fidelity as the load-bearing axis instead of pedagogical quality.

**Provenance:** D14b practice_curator CP3 + CP4 established the canonical pattern (4 real-LLM calls covered easy/medium/hard difficulty + coding/system_design exercise types + the all-empty optional-input path; subjective Phase 5 captured exercises as pedagogically sound). D14c project_evaluator CP3 extended with the rubric-grounding axis (4 phases: rubric-grounded × 2 + D-E refusal + D-4 refusal; Phase 6 verified every dimension_name matches an actual rubric key, every rubric_criterion is a direct quote/paraphrase, narrative_feedback references actual code/PR/self_explanation content rather than generic praise). Zero invented dimensions across either rubric-grounded phase; calibrated non-soft scores (P1=0.72, P2=0.53 with honest weakness call-outs) validated trust-contract-aligned behavior.

### Pattern 22: Spec-vs-schema reconciliation at CP1 pre-authoring

When a Pass 3 spec wording references a table, column, or tool name against a schema that doesn't exist in the actual codebase, fix at CP1 pre-authoring rather than encoding the leaky abstraction into agent code, tool names, or tests. Surface the decision point at the CP1 **pre-authoring** report (before any code ships), not at CP2 schema audit (after tools have been written against the spec name).

**Discipline:** at CP1, before authoring schemas or capability declarations, cross-reference every spec-named entity (table, column, tool, FK target) against the actual codebase models:
- `grep` for the named table/column in `app/models/`
- If the spec entity doesn't exist as named, identify the actual schema location (often a renamed predecessor or a field that lives on a different table than the spec assumes)
- Surface a pre-authoring decision-points report: "spec says X, actual schema is Y, recommend renaming spec entity to Z" — pause for founder confirmation before authoring
- Locked-decision document the rename so future readers see why the deliverable diverges from spec wording

**Why CP1 pre-authoring, not CP2 schema audit:** CP2 schema audit catches drift in *the SQL the tool emits* against the live DB. It does NOT catch the case where the tool was named correctly per spec but the spec's name is wrong relative to actual schema. By CP2, the misleading name is already encoded in the input schema, the capability declaration, the prompt's section names, and any partial test coverage — fixing it requires multi-file rename work. At CP1 pre-authoring it's a single decision before any code is written.

**Provenance:** D14c CP1 — Pass 3c E9 spec referenced rubric storage at "course's `course_content`" against a `course_content` table that doesn't exist in the codebase. Actual rubric storage is `exercises.rubric` (JSON, nullable) per-capstone. Spec named the rubric reader `read_rubric_for_course` taking a course_id; reality required `read_rubric_for_capstone` taking an exercise_id. Surfaced at CP1 pre-authoring decision report; locked decisions D-1 (tool rename), D-2 (drop spec's `rubric_id` input — implied by submission), D-3 (`project_submission_id` maps to `exercise_submissions.id`) made before any agent code shipped. Pre-authoring discipline saved the multi-file rename cost a CP2-time discovery would have incurred. Single-data-point promotion is justified because the failure mode is concrete and the rule is simple.

**Reciprocal extension (D15 CP4):** when extending an SQL JOIN in a tool, synchronously update every test fixture that exercises that SQL — including legacy stub-smoke tests authored against the pre-extension schema. CP3's Bug-24 fix added JOINs through `lessons → courses → course_entitlements → student_role_state`, but the legacy `test_read_active_capstone.py` and `test_read_capstone_status.py` throwaway-schema fixtures still declared the pre-CP3 minimal `exercises + exercise_submissions` shape. Tests passed at CP3 closure (the 6 new entitlement-filter tests use the live DB); the staleness surfaced only at CP4 regression-slice run. Rule: a CP that changes a tool's SQL shape MUST run not just the new tests but every test that imports the changed tool, even when those tests are in unrelated files. Cross-reference Pattern 27 (test fixture staleness as code evolves).

### Pattern 23: Follow-up doc framing drifts from current code as the codebase evolves

Follow-up docs that name specific code paths, columns, table names, or
function signatures become stale as the code evolves around them. The
doc reads correctly against the codebase at write time, but a future
reader following the doc's references against current code finds
either renamed symbols, removed columns, or shifted invariants.

**Discipline:** when authoring a follow-up doc, prefer:
- *Behavioral* descriptions over *symbolic* references when the
  symbol is volatile ("the tool that reads the student's most recent
  capstone" vs. `read_capstone_status.py`'s SQL line 78).
- *Provenance commits* over symbolic references ("commit 21ff4f6
  established this") so the reader can `git show` against a fixed
  state.
- *Reciprocal cross-reference* in the doc the symbol lives in:
  "this column is referenced at `docs/followups/foo.md`."
- When symbolic references are unavoidable (the doc IS the canonical
  reference for a SQL-shape decision), restate the framing at the top
  of the doc + version it ("framing as of [date]; if you're reading
  later, run `git log -- this/path` to confirm symbols still exist").

**Why this matters:** follow-up docs accumulate. By D17 there will be
50+. A doc that named `senior_engineer.execute(state)` when the
agent's signature was `execute(self, state)` reads as wrong against
the post-D11 `execute(self, input, ctx)` AgenticBaseAgent surface,
even though the doc's *intent* is still correct.

**Provenance:**
- D14c CP2a (curriculum_mapper finding) — the follow-up doc named
  `curriculum_mapper.py`'s capability declaration; D17 cleanup
  deleted the file. Doc still references the deleted file.
- D17a Item C (eval-row-writer column-length) — the doc named the
  audit_log column with a length constraint that was widened
  immediately after the doc was written.
- D16 CP1 finding (h) (inactivity_sweep docstring) — the task
  docstring claimed `disrupt_prevention` "consumes these via the
  chat/agents surface"; CP1 grep confirmed no consumer existed.
  Same drift shape, different artifact (a *task module docstring*
  rather than a follow-up doc). Extends the canonical statement:
  framing-drift discipline applies equally to follow-up docs, task
  docstrings, and code comments — anywhere prose makes claims about
  code paths that future code can invalidate.
- D17b ITEM 2.C pre-flight (tailored_resume_v2 `uses_tools`
  comment) — the agent class's `uses_tools = True   # 2 read tools:
  lookup_jd_decoded, lookup_base_resume` comment claimed
  `lookup_jd_decoded` was a live consumer. Pre-flight grep confirmed
  zero `run()`-side invocations; the JD content path goes through
  `generate_tailored_resume(jd_id=...)` service code instead. The
  comment was stale post some-earlier refactor. Reframed ITEM 2.C
  scope to defense-in-depth (no consumer to update) before
  implementation.
- D17b ITEM 4.A pre-flight (eval-row-writer-defensive-fix.md
  sub-item 2 framing) — the doc said "future redesign could add an
  explicit `failure_class` enum"; the prompt's phrasing rebroadcast
  this as "convert string field to typed enum." Pre-flight schema
  inspection confirmed the column doesn't exist yet — additive
  add-column, not migration. Reframed before authoring the
  migration.
- D17b ITEM 4.B pre-flight (eval-row-writer-defensive-fix.md
  sub-item 3 framing) — the doc framed the consolidation as "a
  single writer with a discriminator field." Pre-flight inspection
  showed the two writers target *different tables* with *different
  columns*; only the persistence envelope (try/except + add + flush
  + log) is shared. Reframed to "extract shared envelope; leave
  per-table row construction in each writer" before authoring.
- N=6 across follow-up docs + code comments + task docstrings + agent
  class comments + prompt rebroadcasts of doc framing. Discipline
  ages strongly: every deliverable touching docs older than ~1
  deliverable has surfaced at least one drift instance.

**Tightened canonical statement (post-D17b N=6):**
**Pre-flight verification of follow-up doc claims against current
code is MANDATORY, not optional, on any deliverable that consumes a
follow-up doc older than ~1 deliverable.** Expect drift; design
pre-flight checkpoints to surface it explicitly. The cost of pre-flight
verification is near-zero (read-only inspection); the cost of
implementing against stale framing is rework + the architectural
risk of encoding the wrong shape into a commit. Six instances across
the engagement consistently show pre-flight surfaces drift that
re-shapes implementation before it lands.

Operational pre-flight checks for follow-up-doc-driven work:
- Every named code symbol (function, column, file, table, agent
  class) referenced in the doc gets a grep check against current
  code. Renamed / removed / drifted: surface at pre-flight closure
  before implementation.
- Every shape claim ("returns X", "the column is TEXT(2000)", "the
  consumer is Y") gets verified at the source. The doc's claim may
  have been correct at write time and stale now.
- Surface the reframe as a STOP and seek explicit founder approval
  before encoding into a commit, even when the reframe seems obvious.
  The N=6 evidence shows reframes consistently shift implementation
  shape (additive vs migration; shared envelope vs single writer;
  defense-in-depth vs consumer-update).

### Pattern 24: docker-compose volume mount asymmetry

When the dev container bind-mounts only some of the source directories
(`app/`, `alembic/`) but the developer adds new files in unmounted
sibling directories (`tests/`, `scripts/`), the new files appear to
exist on the host but are invisible to the container without `docker
cp` or a rebuild. This produces "test passed locally but not in
container" confusion that's actually a mount-asymmetry bug, not a
code bug.

**Discipline:**
- Audit `docker inspect <container> --format '{{range .Mounts}}{{.Source}}
  -> {{.Destination}}{{println}}{{end}}'` early when adding files in
  new directories. Confirm the directory is bind-mounted, not just
  baked into the image.
- For test-fixture directories that need to be visible to the
  container BUT live in `tests/`, the operationally cheap workaround
  is `docker cp` per file change. The proper fix is updating
  `docker-compose.yml` to bind-mount `tests/`.
- When you find an asymmetry, register it loudly in the contributing
  guide so the next contributor doesn't burn the same hour.

**Provenance:** D15 CP1+ — the backend container bind-mounts
`backend/app/` and `backend/alembic/` but NOT `backend/tests/`. New
test files at `backend/tests/test_models/test_role_models.py` had to
be `docker cp`'d for every iteration. Captured as a follow-up at
`docs/followups/phase-1-audit-test-dsn-resolution.md` (TEST_PG_DSN
resolution issue surfaced the mount-asymmetry context). N=1
high-value operational finding; promoted to canonical at D15 closure.

### Pattern 25: Round-trip content references through the discovery tool

Heuristic content-fabrication detection (regex for "Production RAG",
"MLOps", generic content names) misses the failure mode where a tool
returns *real* platform content the calling student doesn't have
access to. The agent grounds in what the tool returned; the LLM
output looks plausible; the heuristic detector sees only canonical
content names and clears.

**Discipline:** runtime grounding verification must round-trip every
extracted content reference through the discovery tool's accessible
set, not just heuristic-fabrication-detect. Concretely, the verifier:

- Re-derives the student's accessible-titles set from the live DB
  (replicating the `read_student_accessible_content` SQL) — sidesteps
  any audit-write gap on the agent's tool-call audit.
- Extracts candidate content references from the agent's full JSON
  output via two regex shapes:
  1. Platform-prefixed capstone title patterns (e.g., `D\d+[a-z]?\s+CP\d+...`).
  2. Parenthetical Title Case phrases adjacent to content keywords
     (`capstone`, `exercise`, `notebook`, `lesson`, `submission`,
     `course`, `problem`).
- Suppresses known role-identity phrases ("Python Developer", "Senior
  GenAI Engineer", platform vocabulary) so legitimate role framing
  doesn't trip false positives.
- Flags any extracted name not in the accessible set as a runtime
  grounding violation.

**Two facets** of the pattern:
1. **Verifier requirement** — verification must round-trip through the
   discovery tool, not just look for fabricated-shaped strings.
2. **Verifier design** — regex shapes + suppression list. The
   suppression list is hand-validated against legitimate output during
   verifier authoring; expansion is a known long-tail effort.

**Provenance:**
- D15 CP3 — Bug 24 fabrication ("D14c CP3 Phase 2: Multi-Agent Eval
  Harness" referenced for python_developer student with no
  entitlement) was a real platform capstone, not a fabricated one.
  Heuristic detection missed it; manual inspection caught it.
- D15 CP3 verifier at `tests/fixtures/runtime_grounding_verifier.py`
  is the canonical implementation. Reused at CP4 + CP5 for all
  agent verification.
- N=1 with two facets; promoted to canonical at D15 closure.

### Pattern 26: Runtime backstop for derivative fields

When an output field can be deterministically computed from other
LLM-produced fields OR from authoritative runtime state, the agent's
runtime backstop computes it server-side rather than asking the LLM.
The LLM's emission is informative but not load-bearing; the backstop
preserves the LLM's judgment-bearing values (evidence narration,
explanation text) and overwrites the derivative values (sums, pass
booleans, copy-from-context fields) with canonically-computed values.

**Discipline:** when adding a new optional output field, ask:
1. Can this field be computed from other fields in the same output
   plus authoritative runtime state?
2. If yes — do not rely on the LLM. Add a runtime backstop that
   computes the canonical value after the LLM emits, before the
   agent returns. Preserve the LLM's narrative content; replace its
   derivative values.
3. If no (the field genuinely requires the LLM's judgment) — the
   prompt instruction is the only enforcement. Document this in the
   prompt's "Hard constraints" section.

This pattern composes with Pattern 22 (server-side coercion of LLM
output before validation) — the backstops sit at the same layer.

**Three canonical examples in D15 CP4:**
1. **practice_curator** — `Exercise.source` (`curated`/`generated`) +
   `curated_exercise_id` are derivative of whether the LLM's emitted
   title matches an entry in `accessible_curated_problems`. Runtime
   backstop `_infer_exercise_source` performs the title match and
   sets the field; prompt says "set source = curated/generated" but
   the backstop is the load-bearing enforcement.
2. **project_evaluator** — `TransitionGateStatus.passes_threshold` is
   derivative of `overall_score >= capstone_threshold_required`.
   Runtime backstop `_enforce_gate_status` recomputes from
   authoritative `gate_def` + `overall_score`. The LLM's
   `transition_gate_status` is overwritten entirely; the prompt
   instruction is informative.
3. **mock_interview** — `SessionVerdict.weighted_score` is derivative
   of `sum(weight × score)` across `dimension_scores`; `passed` is
   derivative of `weighted_score >= mock_interview_pass_threshold`.
   Runtime backstop `_enforce_session_verdict` normalizes weights
   from the gate definition (LLM may have emitted wrong weights) and
   recomputes. Preserves the LLM's per-dimension `evidence` strings.

**Why three in one checkpoint earns canonical promotion:** when a
single deliverable produces three independent instances of the same
discipline applied to different field shapes, the discipline is
generalizable, not coincidental. Pattern is load-bearing for any
future deliverable that adds derivative fields.

**Provenance:** D15 CP4 — practice_curator + project_evaluator +
mock_interview backstops at `_infer_exercise_source`,
`_enforce_gate_status`, `_enforce_session_verdict`. N=3 in one
checkpoint; promoted to canonical at D15 closure.

### Pattern 27: Test fixture staleness as code evolves

Test fixtures encoded against initial state become brittle when the
production state evolves. Two failure shapes:

1. **Data-evolution staleness** — fixture asserts an invariant that
   was true at deploy time but evolves with normal product behavior.
   E.g., "all backfilled students sit at python_developer" is true
   at CP1 backfill; once any student transitions, it's wrong. The
   assertion was over-strict at write time, not stale-by-evolution
   in the wrong direction.
2. **Schema-evolution staleness** — fixture builds a throwaway
   schema reflecting the SQL shape at write time. A later CP changes
   the SQL (adds JOINs, renames columns); the fixture doesn't
   regenerate; tests that import the changed SQL fail with
   "column doesn't exist."

**Discipline:**
- For data-evolution: write invariants for properties that hold
  across normal data evolution. "At least N students at python_developer"
  is robust; "ALL students at python_developer" is brittle.
- For schema-evolution: when a CP changes SQL shape, run the broader
  test slice (not just the new tests) to surface stale fixtures
  before closure. Update fixtures atomically with the SQL change in
  the same commit.
- CP closures should run not just the new test slice but adjacent
  agent slices + a sample of the legacy test surface that imports
  any changed tool.

**Cross-reference Pattern 20** (closure-baseline test slices may miss
latent assertion drift): Pattern 27 is the field-data sibling of
Pattern 20's capability-registry-assertion-drift case. Pattern 20
fires when the count of capability declarations drifts; Pattern 27
fires when fixture-encoded values drift.

**Provenance:**
- D15 CP3 (data-evolution) — `test_backfill_all_students_start_at_python_developer`
  was over-strict; loosened to `>= 129 students at python_developer`
  to admit normal progression. Surfaced at CP3 closure baseline run.
- D15 CP4 (schema-evolution) — `test_read_active_capstone.py` and
  `test_read_capstone_status.py` throwaway-schema fixtures lacked
  the `lessons + courses + course_entitlements + student_role_state`
  tables that CP3's Bug-24 fix added to the SQL. Surfaced at CP4
  regression-slice run; fixtures rebuilt at CP4 closure.
- N=2 with different shapes (data + schema evolution); promoted to
  canonical at D15 closure.

### Pattern 28: Functional audit before gap-closure for already-built infrastructure

When a deliverable's prompt assumes infrastructure gaps that haven't
been functionally verified, the deliverable risks shipping scaffolding
on top of code that's already shipped. The work is real; the work is
in the wrong place.

**Discipline:** deliverables that touch already-built infrastructure
should start with a functional audit (CP1-style read-only investigation),
not assumed-gap-closure. The audit's findings determine the rest of the
deliverable's scope. Concretely:

- For each surface the deliverable plans to extend, write down the
  pre-audit assumption ("the cockpit doesn't read X") and the audit
  result ("the cockpit was already migrated to read X via LD-1..LD-5
  annotations").
- Severity-classify gaps that are confirmed (HIGH = launch blocker,
  MEDIUM = pre-launch fix, LOW = post-launch defer). The deliverable's
  shape is determined by the count + severity of confirmed gaps, not
  by the pre-audit assumption.
- Stop conditions on the audit checkpoint: too-many-HIGH gaps mean the
  scope assumption was wrong; zero gaps mean the deliverable is
  largely deferred (and that's fine — verification IS the deliverable).
- Audit cost is near-zero (read-only code inspection); spending a
  near-zero budget to right-size the engineering scope is a
  near-infinite ROI ratio.

**Why this matters:** the original D16 plan was 8+ hours of
new-agent + new-MCP-server work that the audit revealed was already
shipped. The reframe became: 1 launch-blocker (Celery Fly apps), 3
small audit-trail gaps, 1 schema cleanup, plus the WhatsApp gap that
WAS real. Without CP1, the deliverable would have shipped duplicate
infrastructure.

**Provenance:**
- D16 CP1 (functional retention engine audit) — the original plan
  assumed gaps in F1+F3+F4+F5+F8+F9+F10+F11; CP1 confirmed all 8
  surfaces shipped + working. Reframed scope from "new agents +
  Email MCP + proactive layer" to "verify what's there + close
  targeted gaps." Engagement shape changed materially based on
  audit findings.
- N=1 (this engagement); promoted to canonical at D16 closure with
  strong N=1 evidence per the founder's CP1 acknowledgement note
  ("D16's entire shape changed because we audited first").
- Discipline statement: "Deliverables that touch already-built
  infrastructure should start with functional audit, not
  assumed-gap-closure."

### Pattern 29: Scaffolded-but-inert detection

A schema can ship with all its tables created, models defined, and
ORM imports wired — and still have zero data flowing into it because
the writer code never landed (or was retired) without the schema
being dropped. The cluster looks live (tables exist, code imports
the models) but is functionally dead.

**Two variants:**

1. **No-writer-found:** the schema shipped but the writer was never
   authored. Reader endpoints (if any) silently return empty / stale
   data. The reader's downstream consumers degrade silently because
   "empty rows" is a valid shape.
2. **Writer-retired-without-drop:** the writer was authored, then
   superseded (e.g., the cockpit migrated to read from primary tables
   instead of the denormalized cluster). The cluster's seed/snapshot
   data persists indefinitely, drifting from primary-table truth.

**Discipline:**
- At schema-design time, every CREATE TABLE migration commits to a
  writer path within the same release cycle, or the migration
  explicitly notes "demo-seed-only, no writer planned, drop migration
  scheduled at NNNN" in the migration docstring.
- At reader-migration time (e.g., cockpit moves from denorm to live
  primary-table reads), the dropping-the-old-tables migration is
  scheduled in the same PR or as an explicit follow-up doc with a
  pre-drop checklist.
- CI improvement candidate: a check that grep-asserts every model in
  `app/models/` has at least one writer call site under
  `app/services/` or `app/tasks/`. Any model with zero writers is
  surfaced; if intentional (demo seed, future-proofing), it goes on
  an allowlist in the check.
- Every architectural audit run (Pattern 28-style functional audit)
  should explicitly check for this shape: for each table cluster the
  audit covers, grep for the writer; if absent, classify as
  scaffolded-but-inert and severity-rate (HIGH if a reader silently
  returns wrong data; MEDIUM if dormant-but-cleanup-pending; LOW if
  documented intent).

**Why this matters:** scaffolded-but-inert tables are a slow-burn
correctness risk. The reader endpoint returns 200 OK; the response
shape is well-formed; consumers degrade based on "empty cohort" or
"stale snapshot" assumptions that may not hold. The bug doesn't
surface in tests because the test fixtures populate the tables. It
surfaces in production when an admin sees a cohort count that doesn't
match what they know is true.

**Provenance:**
- D16 CP1 finding (d) — `admin_console_*` cluster (8 tables, mig 0039)
  identified as scaffolded-but-inert. CP2.d verification confirmed
  the reader at `/api/v1/admin/console/v1` was already migrated to
  read from primary tables (LD-1..LD-5 annotations). This is the
  variant-2 case (writer-retired-without-drop). Drop migration tracked
  at `d16-followup-admin-console-drop-migration.md`.
- D17b ITEM 2.C pre-flight (`lookup_jd_decoded` tool) — the tool is
  registered in the universal tool registry and reachable via the
  LLM tool-use protocol, but no agent's `run()` invokes it. The
  `tailored_resume_v2:22` `uses_tools` comment claims it's a live
  consumer (Pattern 23 drift); the actual JD content path goes
  through `generate_tailored_resume(jd_id=...)` service code.
  This is the **third variant** of the pattern: not a missing writer
  (the read tool exists) and not a retired writer (no migration
  history) — a **registered-but-unconsumed tool** that the LLM could
  theoretically discover and call but no production prompt surfaces
  to it. Defense-in-depth fix at ITEM 2.C added the missing
  student_id filter, so a future consumer wiring up the tool
  inherits a safe contract.
- N=2; promoted from candidate to **canonical** at D17b closure.
  The third variant (registered-but-unconsumed tool) is documented
  alongside the two original variants. Both observed instances came
  from architectural audits (D16 CP1 + D17b ITEM 2.C pre-flight),
  reinforcing that this pattern surfaces under audit-style
  investigation more reliably than under feature-driven work.

**Three variants (post-D17b):**
1. **No-writer-found:** schema shipped without writer; reader (if any)
   silently degrades.
2. **Writer-retired-without-drop:** writer was authored, then
   superseded; cluster's data persists indefinitely.
3. **Registered-but-unconsumed tool:** tool registered in the registry
   and reachable via LLM tool-use, but no agent `run()` invokes it
   today. Stale `uses_tools` comments or pre-deletion-of-consumer
   shapes commonly produce this. The leak surface is "the LLM might
   discover and call it"; defense-in-depth fixes apply the same
   guardrails an active consumer would have required.

### Pattern 30 (candidate): Deterministic composition over prompt-side judgment for state-aware response decoration

When an agent's response needs to vary based on deterministic state
signals (e.g., "open with welcome-back framing if days_since_last_session
≥ 5"), the natural first instinct is to put the firing logic in the
prompt: surface the signals to the LLM, write a prompt section telling
it which template to fill. D17b ITEM 3 evidence shows two failure modes
of the prompt-side approach:

1. **Tone-competition.** Existing prompt instructions ("be honest,
   direct, no sycophancy", "ground every assessment in data", etc.)
   compete with the new state-aware decoration instructions. The LLM
   is biased toward the dominant tone — the older, longer, more
   internally-reinforced part of the prompt usually wins. D17b ITEM 3's
   first attempt: 4 of 4 trigger phases failed to fire the lead-in
   framing on career_coach; the LLM consistently led with deficit
   analysis (matching the dominant tone) instead of welcome / mock-pass
   / gate-cleared opener.
2. **Prompt-size-driven timeout drift.** Adding the decoration logic
   grows the prompt; the LLM's response generation takes longer
   proportional to ingestion + constraint count + output overhead.
   D17b ITEM 3's first attempt added ~80 lines to study_planner; 3 of
   6 phases timed out at the existing 30s dispatch ceiling. Pattern
   18b territory (extended at D17b ITEM 3 to cover prompt-size
   changes, not just provider changes).

**Discipline:** when the firing decision can be computed
deterministically from structured state, do the composition outside
the LLM:

- The LLM receives only the inputs it needs to produce its core
  output (career analysis, study plan, etc.) — exactly what the
  pre-decoration prompt asked for.
- A pre-LLM tool call aggregates the state signals into a structured
  contract object (Pattern 26 shape).
- A post-LLM `compose_*_opener(signals, ...) -> str | None` function
  applies the deterministic firing rules and returns either a
  templated opener or None.
- The agent's `run()` prepends `f"{opener}\n\n"` to the user-visible
  field (typically `payload["answer"]`) when not None; healthy-state
  path passes through unchanged.

**Trade-offs accepted:**
- Lead-in copy is templated, not LLM-generated organic. Mitigated by
  the LLM-generated content immediately following the opener: the
  natural prose bridge makes the seam invisible in production.
- Future tone iteration requires code change, not prompt change. The
  templates live in code; updating them is a small focused commit
  rather than a prompt edit. Acceptable when templates are short and
  isolated in a dedicated composer module.
- Templates feel slightly more mechanical than free-form riffs. Per
  D17b ITEM 3 verification, the templates landed verbatim in
  production runs and read coherently in context — so the trade-off
  was demonstrated worth it.

**Provenance:**
- D17b ITEM 3 (Path E `compose_lead_in_opener`) — the original
  prompt-side approach demonstrated both failure modes in 7-phase
  real-LLM verification (4/4 career_coach trigger phases failed to
  fire; 3/6 study_planner phases timed out from prompt growth). The
  deterministic post-LLM composition approach (Path E) resolved both
  simultaneously: 13 deterministic unit tests pin trigger correctness;
  4-phase real-LLM verification confirms verbatim opener prepending +
  control-phase baseline preservation. Cost ~₹0 (no LLM judgment on
  firing).
- N=1; **promote to canonical if** D18 testing or post-launch
  iteration surfaces the same shape (state-aware response decoration
  considered for prompt vs. deterministic post-LLM composition). The
  pattern's force depends on observing the trade-off resolution work
  the same way more than once.

**Cross-reference:**
- Pattern 26 (runtime backstop discipline; structured fields over
  excavation): the aggregator + deterministic composer together are
  the canonical Pattern 26 shape for response decoration.
- Pattern 18b (prompt-size extension): the prompt-side failure mode
  that motivated Pattern 30 is also a Pattern 18b instance; the two
  patterns reinforce.

## Application guide

When starting a new agent migration (D13+), walk these patterns in order and confirm each is addressed:

**At CP1** (capability + schema):
- Pattern 22: spec-vs-schema reconciliation — cross-reference every spec-named entity against `app/models/` BEFORE authoring; surface mismatches at pre-authoring report, not CP2 audit
- Pattern 1: scope is narrow (capability flip + schema + tools registered, no agent class yet)
- Pattern 5: every fail-soft DB read tool has the asyncpg-rollback wrapper
- Pattern 7: decide speculative-reads vs native-tool-use; if speculative, list the read set in the agent's run()
- Pattern 13: calibrate `typical_latency_ms` against the active provider; document in the capability docstring
- Pattern 14: estimate output token budget; don't blanket-apply smart-tier default to lightweight agents
- Pattern 18b (preemptive sizing): set `timeout_override_seconds` at spec × 4-5 multiplier; do NOT skip the override

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
- Pattern 21: for content-generating-direct-to-user OR rubric-graded-evaluation agents, Phase 5/6 quality observation captures domain-quality findings as informational; rubric-graded agents add the dimension-by-dimension rubric-grounding check (D14c extension)

**At CP4** (cutover):
- Pattern 1: atomic — rename _v2 → canonical, delete legacy, drop AGENT_REGISTRY entry, remove MOA routes
- Pattern 2: retirement-pin test asserts AGENT_REGISTRY no longer contains the agent
- Pattern 3: data backfill (if any) lands as a separate `data(...)` commit
- Pattern 18b (tightening): only tighten `timeout_override_seconds` when n ≥ 5 measurements exist; tightening formula is `observed_p95 × 1.30` OR `observed_max × 1.50`, whichever is larger; never tighten on small samples — D14c CP4 evidence shows MiniMax tail-latency spread defeats `observed_max × 1.30` at n=2-4

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
