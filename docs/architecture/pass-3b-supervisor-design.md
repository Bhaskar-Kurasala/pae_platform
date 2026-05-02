---
title: Pass 3b — The Supervisor Agent
status: Final — canonical design for the Supervisor agent and AICareerOS coordination layer
date: After Pass 3a Addendum sign-off, before D9 implementation
authored_by: Architect Claude (Opus 4.7)
purpose: Design the Supervisor agent — the keystone agent that turns 14 specialist agents into a coordinated OS. Defines the data contract, decision logic, dispatch layer, policy enforcement, error handling, observability, testing, and migration path from the legacy MOA.
supersedes: nothing
superseded_by: nothing — this is the canonical Supervisor design
informs: Pass 3c (agent migration playbook), Pass 3d (tool implementations), Pass 3f (entitlement enforcement), every future agent migration
implemented_by: D9 (first implementation deliverable post-architecture)
---

# Pass 3b — The Supervisor Agent

> The Supervisor is the agent that turns 14 specialist agents into a coordinated OS. It is the most important new component in AICareerOS. This document is the design contract that D9 implements.

> Read alongside: Pass 3a Addendum (the canonical 16-agent roster), AGENTIC_OS.md (the D1–D8 foundation), and the Track 5 precondition gaps audit (specifically PG-1 and PG-5).

---

## 0. Why this pass exists

Pass 2 confirmed AICareerOS does not coordinate agents today. Each request hits one agent. That agent is blind to every other agent. The current MOA — a 2-node LangGraph — is a router, not an orchestrator. The product vision ("agents that coordinate, share memory, identify needs, proactively nudge, personalize") cannot be delivered by routing alone.

The Supervisor is the agent that turns 14 specialist agents into a coordinated OS. It does five things no current code does:

1. **Decides who handles a request** — including chains of agents, not just single agents
2. **Prepares context** — pulls from memory bank, student state, prior agent outputs, conversation thread
3. **Dispatches and monitors** — invokes specialists via `call_agent` (D4), watches for failure
4. **Coordinates handoffs** — when agent A says "this needs B," supervisor decides whether to actually hand off
5. **Enforces policy** — entitlements, safety, cost, abuse limits — at the boundary, not per agent

If the Supervisor is well-designed, every other agent migration becomes mechanical. If it's poorly designed, every agent migration inherits the error. That is why this pass is paid for in Opus reasoning.

---

## 1. What the Supervisor is NOT

Architectural pitfalls explicitly avoided. Each one was tempting and each was rejected.

**Not a god agent.** The Supervisor does not reason about pedagogy, code quality, careers, or any specialist domain. It reasons only about routing, coordination, and policy. The moment it starts having opinions about Python code or interview prep, it has overstepped and the design is wrong.

**Not a workflow engine.** The Supervisor is not a DAG executor running predefined pipelines. Predefined pipelines (cron-driven, deterministic) are Celery's job. The Supervisor handles per-request, per-student, dynamic decisions where the "right next step" depends on context the moment it's asked.

**Not a deterministic state machine.** It's an LLM-based agent making real decisions. Heavy constraint via structured outputs and policy gates, but at its core it interprets a student request and chooses what to do. Policy says "what it can't do." Reasoning fills the gap between request and action.

**Not the only entry point.** Some agent invocations bypass the Supervisor entirely — Celery jobs running `progress_report`, webhook handlers triggering `content_ingestion`, admin endpoints triggering specific agents directly. The Supervisor is the entry point for **student-initiated requests**, not for background or operator-initiated ones.

**Not transparent.** The Supervisor's decisions are visible in `agent_call_chain` — every routing decision creates an audit row. Operators and the Critic (D5) can see why a student request went to one agent vs. another.

**Not infallible.** When the Supervisor fails (parses badly, picks an unavailable agent, hits a cost ceiling), the request degrades gracefully — falls back to a default agent (Learning Coach), returns a polite error, escalates to admin inbox. Failure modes are designed in, not added later.

---

## 2. Architectural placement

### Before (current)

```
Student request
    │
    ▼
FastAPI route (e.g., /agents/stream)
    │ get_current_user (JWT)
    │ NO entitlement check
    ▼
AgentOrchestratorService.chat()
    │ load Redis history (1h TTL)
    │ build AgentState
    ▼
MOA graph (classify_intent → run_agent → END)
    │ keyword route OR Haiku classifier
    ▼
ONE specialist agent (BaseAgent.run)
    │ no shared memory
    │ no awareness of other agents
    ▼
Response → Redis history → return
```

### After (Pass 3b target)

```
Student request
    │
    ▼
FastAPI route (the canonical /api/v1/agentic/{flow}/chat from PG-5)
    │ get_current_user (JWT)
    │ require_course_entitlement (Pass 3f)
    │ rate_limit_per_user
    ▼
AgenticOrchestratorService (replaces AgentOrchestratorService)
    │ load conversation thread (DB-backed, persistent)
    │ load student model snapshot from MemoryStore (D2)
    │ construct SupervisorContext
    ▼
Supervisor (AgenticBaseAgent, uses_memory=True, uses_tools=True, uses_inter_agent=True)
    │ reads SupervisorContext + memory + recent agent_actions
    │ reasons about request
    │ outputs RouteDecision (structured)
    ▼
Dispatch layer
    │ Single-agent dispatch  →  call_agent(specialist) (D4)
    │ Chain dispatch         →  sequence of call_agent() with state passing
    │ Decline                →  graceful refusal with reason
    │ Escalate               →  human admin via student_inbox
    ▼
Specialist agent(s) run
    │ each writes to agent_memory via memory_curator hook
    │ each writes to agent_actions
    │ each can return handoff signals
    ▼
Response composition
    │ if chain: stitch outputs
    │ supervisor optionally summarizes for the student
    ▼
Persist conversation turn → return
```

The Supervisor is the *only* layer that sees the full request shape. Specialists see what the Supervisor hands them. This is critical for keeping specialists narrow.

---

## 3. The Supervisor's data contract

### 3.1 Inputs — `SupervisorContext`

```python
class SupervisorContext(BaseModel):
    # Identity
    student_id: UUID
    request_id: UUID  # unique per student request, propagates to call_chain
    conversation_id: UUID  # persistent thread id, not Redis
    actor_id: UUID  # for DISC-57 actor identity (admin-on-behalf-of cases)
    actor_role: Literal["student", "admin", "system"]

    # The actual request
    user_message: str
    attachments: list[AttachmentRef] = []  # code, files, JD text, etc.
    explicit_agent_request: str | None = None  # student typed "/career_coach" or used a UI button

    # Policy gates (computed before Supervisor runs)
    entitlements: list[EntitlementSummary]  # active courses, what's unlocked
    rate_limit_remaining: RateLimitState
    cost_budget_remaining_today: Decimal  # in INR

    # Student model snapshot (NOT the full memory bank — a curated snapshot)
    student_snapshot: StudentSnapshot

    # Conversation thread (last N turns from DB, NOT Redis)
    thread_summary: str | None  # rolling summary > 10 turns old
    recent_turns: list[ConversationTurn]  # last 5 turns verbatim

    # Recent agent activity (for awareness, not full history)
    recent_agent_actions: list[AgentActionSummary]  # last 10 across all agents in last 7 days

    # Available capabilities
    available_agents: list[AgentCapability]  # filtered by entitlement
    available_tools: list[ToolName]  # supervisor's own tools, not specialists'
```

**`StudentSnapshot`** is the curated student model. Not the full memory bank — a pre-computed, cached, per-student summary that updates lazily.

```python
class StudentSnapshot(BaseModel):
    # Course context
    active_courses: list[CourseRef]
    current_focus: ConceptRef | None  # what they're working on right now
    progress_summary: ProgressSummary  # % complete, weeks active, last session

    # Mastery and gaps (from user_skill_states + student_misconceptions)
    strong_concepts: list[ConceptRef]  # top 5 by mastery
    weak_concepts: list[ConceptRef]  # bottom 5 by mastery
    open_misconceptions: list[MisconceptionRef]  # last 30 days

    # Behavioral signals (from student_risk_signals + recent activity)
    risk_state: Literal["healthy", "at_risk", "critical"] | None
    energy_signal: Literal["fresh", "tired", "frustrated"] | None  # from recent interactions
    streak_days: int

    # Goals
    active_goal_contract: GoalContractSummary | None  # weekly hours, target role
    capstone_status: CapstoneStatus | None

    # Preferences (from memory bank, scope=user)
    preferences: dict[str, Any]  # tutoring_mode, communication_tone, response_length, etc.
```

This snapshot is computed by `student_snapshot_service` with a 5-minute Redis cache. The Supervisor never queries DB tables directly — it always reads through this snapshot. **This is load-bearing for performance at 1,000 students.**

**`AgentCapability`** is the registry view the Supervisor sees:

```python
class AgentCapability(BaseModel):
    name: str
    description: str  # one-paragraph summary, written for the Supervisor's reasoning
    inputs_required: list[str]  # e.g., ["code", "problem_context"] for senior_engineer
    inputs_optional: list[str]
    outputs_provided: list[str]
    typical_latency_ms: int
    typical_cost_inr: Decimal
    requires_entitlement: bool
    available_now: bool  # might be false if rate-limited or cost-exhausted
    handoff_targets: list[str]  # agents this one commonly hands off to
```

Each agent declares its capability when it registers. **This decouples the Supervisor from agent implementations** — adding an agent is a registration change, not a Supervisor change.

**`AgentActionSummary`** is the awareness window:

```python
class AgentActionSummary(BaseModel):
    agent_name: str
    action_type: str
    occurred_at: datetime
    summary: str  # 1-sentence summary of what happened, written by memory_curator on insert
    score: float | None  # critic score if available
    triggered_followup: bool  # did this lead to another agent call
```

The summary string is critical. Without it, the Supervisor would either get full agent outputs (too expensive in tokens) or only metadata (uninformative).

### 3.2 Outputs — `RouteDecision`

```python
class RouteDecision(BaseModel):
    # The decision
    action: Literal["dispatch_single", "dispatch_chain", "decline", "escalate", "ask_clarification"]

    # If dispatch_single
    target_agent: str | None = None
    constructed_context: dict[str, Any] | None = None

    # If dispatch_chain
    chain_plan: list[ChainStep] | None = None

    # If decline
    decline_reason: Literal["out_of_scope", "entitlement_required", "rate_limited",
                            "cost_exhausted", "safety_blocked"] | None = None
    decline_message: str | None = None  # student-facing
    suggested_next_action: str | None = None

    # If escalate
    escalation_reason: str | None = None
    admin_inbox_summary: str | None = None

    # If ask_clarification
    clarification_questions: list[str] | None = None
    expected_clarifications: list[str] | None = None

    # Reasoning (for audit + debugging)
    reasoning: str  # 2-3 sentence explanation, always required
    confidence: Literal["high", "medium", "low"]

    # Metadata
    primary_intent: str
    secondary_intents: list[str] = []
```

```python
class ChainStep(BaseModel):
    step_number: int
    target_agent: str
    constructed_context: dict[str, Any]
    pass_outputs_from_steps: list[int] = []  # which prior step outputs to inject
    on_failure: Literal["abort_chain", "continue", "fallback_to_default"]
    timeout_ms: int = 30000
```

### 3.3 Why this contract is the right one

**The Supervisor never invokes specialists directly.** It returns a decision; the dispatch layer executes the decision. Separation enables unit testing without specialists, and dispatch testing without an LLM.

**The output is fully structured.** The Supervisor speaks Pydantic, not free text. Critic (D5) validates decisions structurally.

**The decision is auditable.** Every `RouteDecision` is logged with reasoning. When a student says "the OS sent me to the wrong agent," we can read the Supervisor's logged reasoning and tell whether it was a routing error, a context error, or a specialist error.

---

## 4. Decision logic

### 4.1 The decision tree

The Supervisor reasons in this order. The order matters — earlier checks short-circuit later ones.

**Step 1 — Policy gates.** Before any reasoning about what the student wants, check what's allowed:

- Account active?
- At least one active course entitlement?
- Within rate limits?
- Cost budget remaining today?
- Input passed safety pre-checks?

These are not LLM decisions. Computed before the Supervisor LLM call and injected into context. Defense in depth: orchestrator enforces too, dispatch layer enforces too.

**Step 2 — Intent classification.** Fixed taxonomy of ~15 labels (`tutoring_question`, `code_review_request`, `career_advice`, `interview_practice`, `progress_check`, `billing_question`, `study_planning`, `clarification_needed`, `out_of_scope`, etc.). Multiple intents allowed in `secondary_intents`.

**Step 3 — Specialist matching.** Read `available_agents`, match intent to capabilities. `AgentCapability.description` is written for the Supervisor's reasoning, not for humans.

**Step 4 — Chain decision.** Defaults to single. Chain only when:
- Student request explicitly contains multiple actions
- Primary intent inherently requires multiple agents
- Student model indicates a follow-up should happen

**Chain length cap: 3 steps maximum** in v1.

**Step 5 — Context construction.** Pull from `student_snapshot`, `recent_agent_actions`, conversation thread, request body. Build `constructed_context` dict. Never invent context fields. If a required input is missing, return `ask_clarification` instead of dispatching with bad context.

**Step 6 — Self-check.** Before finalizing: am I about to dispatch to an unavailable agent? Construct a chain longer than 3? Is my reasoning consistent with my action?

### 4.2 The supervisor prompt — structural blueprint

Full prompt lives in `backend/app/agents/prompts/supervisor.md`. Structural blueprint:

```
[Role definition]
You are the Supervisor of AICareerOS — a learning operating system for engineers
becoming senior GenAI engineers. You do not tutor, review code, or give career
advice. Your only job is to decide which specialist agent or agents handle each
student request, and to refuse requests that cannot be served.

[The taxonomy — fixed, exhaustive]
[list of 15 intents with one-line definitions]

[The agents — capability descriptions]
[dynamically rendered AgentCapability list]

[The decision protocol — 6 steps]

[Hard constraints]
You MUST:
- Output a valid RouteDecision matching the schema exactly
- Set action="decline" if the student has zero active entitlements
- Never invent an agent name not on the available list
- Never construct a chain longer than 3 steps
- Always provide reasoning of 2-3 sentences
- Never fabricate context fields not provided in your inputs

You MUST NOT:
- Answer the student's question yourself (you route, you don't tutor)
- Dispatch to an agent listed as available_now=false
- Mix your reasoning into the constructed_context
- Pass sensitive PII into chain contexts (filter through allowed fields only)

[Examples — 6-8 worked examples]

[Output format reminder]
Return only the RouteDecision JSON. No prose before or after.
```

Three improvements over the current MOA classifier:
- **Agent list is dynamic** (built fresh from registry; drift becomes structurally impossible)
- **Taxonomy is fixed** (closed set, easier to evaluate, easier to audit)
- **Refusal is a first-class output** (Supervisor itself decides not to dispatch when entitlements are missing)

### 4.3 Model choice

**Sonnet 4.6, not Haiku.**

Rejected Haiku because:
- The Supervisor reads non-trivial context. Haiku struggles with reasoning over this much context.
- Refusing well requires nuance Haiku doesn't reliably produce.
- Chain decisions weigh tradeoffs Haiku doesn't reliably navigate.
- Cost is bounded: ~5,000 calls/day at 1k students × ~0.40 INR/call ≈ ~60,000 INR/month at full capacity. Right cost for orchestration quality.
- Haiku is right for narrow specialists, not for a coordinator.

Override: if Supervisor latency >3s p95, add a Haiku fast-path classifier for obvious cases. **Not built in v1.** Premature optimization.

---

## 5. The dispatch layer

The Supervisor decides; the dispatch layer executes. Separation matters for testability and reliability.

### 5.1 Single-agent dispatch

```python
async def dispatch_single(decision: RouteDecision, ctx: SupervisorContext) -> AgentResult:
    # 1. Validate decision against current state
    if not is_agent_available(decision.target_agent):
        return _fallback_dispatch(ctx, reason="target_unavailable")

    # 2. Build AgentInput for the specialist
    agent_input = AgentInput(
        student_id=ctx.student_id,
        request_id=ctx.request_id,
        task=ctx.user_message,
        context=decision.constructed_context,
        conversation_history=ctx.recent_turns,
    )

    # 3. Call via D4's call_agent primitive
    result = await call_agent(
        agent_name=decision.target_agent,
        input=agent_input,
        parent_request_id=ctx.request_id,
        timeout_ms=DEFAULT_SPECIALIST_TIMEOUT_MS,
    )

    # 4. Process handoff signal if specialist returned one
    if result.handoff_request:
        return await _process_handoff(result.handoff_request, ctx, result)

    return result
```

Three things D4 alone doesn't have:
- Validation that the target is currently available (state may have changed)
- Handoff signal processing
- Fallback handling on specialist failure

### 5.2 Chain dispatch

```python
async def dispatch_chain(decision: RouteDecision, ctx: SupervisorContext) -> ChainResult:
    chain_results = []
    accumulated_context = decision.chain_plan[0].constructed_context

    for step in decision.chain_plan:
        for prior_step_idx in step.pass_outputs_from_steps:
            prior_output = chain_results[prior_step_idx - 1].output_summary
            accumulated_context[f"step_{prior_step_idx}_output"] = prior_output

        agent_input = AgentInput(..., context=accumulated_context)

        try:
            result = await call_agent(
                agent_name=step.target_agent,
                input=agent_input,
                parent_request_id=ctx.request_id,
                timeout_ms=step.timeout_ms,
            )
            chain_results.append(result)

        except AgentFailure as exc:
            if step.on_failure == "abort_chain":
                return _build_partial_chain_result(chain_results, exc, aborted_at=step)
            elif step.on_failure == "continue":
                chain_results.append(_build_failed_step_result(exc))
                continue
            elif step.on_failure == "fallback_to_default":
                fallback_result = await call_agent(DEFAULT_AGENT, ...)
                chain_results.append(fallback_result)

    return _stitch_chain_results(chain_results, decision)
```

Stitching uses each specialist's `output_summary` field via templating. LLM-quality stitching is opt-in (Supervisor does a final "compose response" call as the chain's last step) — not the default.

### 5.3 Handoff protocol

```python
class HandoffRequest(BaseModel):
    target_agent: str
    reason: str
    suggested_context: dict[str, Any]
    handoff_type: Literal["mandatory", "suggested"]
```

Dispatch layer doesn't blindly follow handoff requests. It re-invokes the Supervisor with the handoff context, and the Supervisor decides whether to honor it. Prevents:
- **Loops** (Supervisor sees the call chain via `agent_call_chain`, refuses cyclic handoffs)
- **Cost runaway** (refuses repeated handoffs in a short window)

**All routing decisions go through the Supervisor.** Specialists request, Supervisor decides.

---

## 6. Policy enforcement

The Supervisor is where policy is enforced — but enforcement is layered, not concentrated. Defense in depth.

### 6.1 Entitlement gating (the Pass 2 H1 fix)

Three layers:

1. **Route-level dependency:** the canonical agentic endpoint (PG-5) has a `require_active_entitlement` FastAPI dependency that returns 402 if the student has zero active courses. This is the outermost gate.

2. **SupervisorContext computation:** the orchestrator populates `entitlements` in the context. If empty, the Supervisor's prompt forces `decline` with `entitlement_required`.

3. **Dispatch layer check:** before invoking any specialist, the dispatch layer verifies the student still has an active entitlement (in case it was revoked between Supervisor decision and dispatch — refunds, fraud holds). If revoked, dispatch returns `decline_message` instead of calling the specialist.

Why three layers? Each catches a different failure mode. Route gate is fast and cheap (no LLM). Supervisor gate handles the "soft" message (better UX than a bare 402). Dispatch gate catches race conditions. Removing any one of them is fine in theory but creates fragility.

### 6.2 Rate limiting

Per-student, per-window. Three windows enforced:

- **Burst:** 10 agent calls / 1 minute. Catches accidental rapid-fire (frontend retry storm, automation bug).
- **Hourly:** 100 agent calls / 1 hour. Catches sustained abuse.
- **Daily cost ceiling:** 50 INR / day per student. Catches the actual financial risk — a student who somehow bypasses call-count limits but generates expensive Sonnet calls.

The orchestrator computes remaining budget before each Supervisor call. Supervisor sees `rate_limit_remaining` and `cost_budget_remaining_today` in context and declines with appropriate messaging when exhausted.

The cost ceiling is the most important of the three. At 1,000 students × 50 INR/day = 50,000 INR/day = 1.5L INR/month maximum cost exposure. That's a real number a startup can underwrite. Without this ceiling, a single rogue student could rack up unbounded costs.

These thresholds are **configurable per-tier** via `course_entitlements.tier` (added in Pass 3f schema). Premium tiers can have higher ceilings. Default tier is the numbers above.

### 6.3 Safety pre-check

Before the Supervisor LLM call, the orchestrator runs an input-side safety check:

- Prompt injection regex (looks for jailbreak phrases, role-confusion patterns, "ignore previous instructions" variants)
- PII detection (does the student message contain something that looks like a credit card number, SSN, or other identifier they shouldn't be sharing with an AI?)
- Length cap (10,000 characters max — anything longer is either copy-paste of large content or an attack)

This is a **partial implementation of `safety_guardian`** from the original Pass 3a. The full `safety_guardian` agent gets designed in Pass 3g. For Supervisor v1, we ship the regex + length-cap subset. It catches 80% of obvious problems and is a five-minute build.

If safety pre-check flags input as problematic:
- High severity (jailbreak attempt, PII): block with `safety_blocked` + log incident
- Medium severity (length cap, suspicious patterns): redact + continue with warning to student
- Low severity (typo-level): allow + log

Output-side safety is the specialist's responsibility (or gets added in Pass 3g). The Supervisor doesn't see specialist outputs, so it can't do output-side checks itself.

### 6.4 Cost ceiling enforcement during chains

A subtle issue: a chain plan might be approved at the start, but during execution, Step 1 might consume more cost than expected, leaving Step 2 and 3 over-budget.

Solution: before each chain step, the dispatch layer re-checks remaining budget. If a step would push the student over their daily ceiling, the chain aborts mid-flight with a `partial_completion` result and the student gets what was completed plus a "the rest of your request couldn't be processed because [reason]" message.

This is fail-safe, not fail-pretty. UX could be improved but cost protection comes first.

---

## 7. Error handling and graceful degradation

The Supervisor is the most critical agent in the system — when it fails, every student request fails. So its failure modes need to be designed in, not added later.

### 7.1 The five failure classes

**Failure Class A: Supervisor LLM fails to return valid JSON**

The Critic (D5) catches malformed output and triggers retry. After 2 failed attempts, the Supervisor escalates per existing D5 patterns. But "Supervisor escalation" is not the same as a normal agent escalation — there's no fallback Supervisor.

Resolution: when Supervisor escalation triggers, fall back to a **deterministic routing strategy**:
1. Check if the user message matches any keyword in a curated keyword map (similar to current MOA's `_KEYWORD_MAP`)
2. If yes, dispatch to that agent
3. If no, dispatch to `learning_coach` (the canonical default)

Student sees a normal response (slightly less smart routing, but functional). Operator sees a logged Supervisor escalation with the full failure context. `agent_escalations` row written. Notification fires (within rate limit).

The keyword map is maintained as a **safety net**, not a primary routing mechanism. It's expected to handle ~80% of common requests adequately when the Supervisor is down. Edge cases get learning_coach, which is the safest default agent for unclassified requests.

**Failure Class B: Supervisor returns valid JSON but specifies an invalid agent**

E.g., `target_agent: "tutor_v3"` (doesn't exist), or `target_agent: "knowledge_graph"` (retired in Pass 3a). The dispatch layer's validation catches this.

Resolution: dispatch layer rejects, falls back to `learning_coach`, logs the invalid agent name as a hallucination incident (high-priority for prompt improvement). Student sees normal response.

This is preventable by the Supervisor prompt's "you must only dispatch to agents on this list" constraint, but LLMs hallucinate. We catch it deterministically rather than trusting prompt discipline.

**Failure Class C: Specialist times out or errors during dispatch**

E.g., Supervisor dispatched to `senior_engineer`, which threw an exception or hit the 30-second timeout.

Resolution: D5's `evaluate_with_retry` handles per-specialist retry. After exhaustion, the dispatch layer:
- For single dispatch: returns a graceful error to the student ("I had trouble processing your request — try again or rephrase")
- For chain dispatch: applies the step's `on_failure` policy (`abort_chain`, `continue`, `fallback_to_default`)

In both cases, an `agent_escalations` row is written with the specialist name and the failure context. The Supervisor is not at fault here, but its decision context is logged so we can later see "the Supervisor tends to dispatch to senior_engineer in cases where senior_engineer fails — maybe its routing for those cases is wrong."

**Failure Class D: Cost ceiling exhausted mid-chain**

Chain Step 1 used more cost than expected, leaving Step 2 over-budget.

Resolution: chain aborts mid-flight. Student sees what was completed plus a clear message ("the rest of your request couldn't be processed because you've reached your daily limit — your full daily allowance resets at midnight UTC"). Partial result written to conversation thread. No error from the student's perspective; just incomplete service.

**Failure Class E: Memory/storage layer unavailable**

Postgres down, Redis down, embedding service down. The Supervisor reads from these to construct context.

Resolution: graceful degradation per layer:
- Postgres unavailable: Supervisor runs without `student_snapshot` and `recent_agent_actions` (treat them as empty). Routing quality degrades but doesn't fail.
- Redis unavailable: conversation thread degrades to in-flight only (last 5 turns from current request). Memory effectively returns to "1-hour-or-less."
- Embedding service unavailable: semantic recall returns empty. Memory recall by exact key still works.

In all cases, the Supervisor operates on degraded inputs but still produces decisions. Student sees slightly worse routing quality. Operator sees alerts on the underlying infrastructure (handled by existing observability, not the Supervisor's concern).

**The principle:** the Supervisor should never be the reason a student's request fails completely. It should always produce *some* answer, possibly degraded, possibly with caveats. Total request failure is reserved for upstream issues (auth, payment, account lock).

### 7.2 What gets logged on every Supervisor invocation

Every Supervisor call writes:

1. **One `agent_actions` row** for the Supervisor itself (via existing BaseAgent infrastructure)
2. **One `agent_call_chain` row** as the parent for any subsequent specialist calls (D4 infrastructure)
3. **The full `RouteDecision` JSON** in `agent_actions.output_data`, including reasoning
4. **The `SupervisorContext` summary** in `agent_actions.input_data` — but the *summary*, not the full context (full context is reconstructable from `student_id` + timestamp from underlying tables)
5. **Cost in INR** (existing token-counting infrastructure)
6. **Decision quality flags** if the Critic is sampling: routing-quality score, reasoning-quality score

This is enough for offline analysis: "show me all decisions where Supervisor confidence was 'low' last week," "show me all chains that aborted mid-flight," "show me agents the Supervisor never dispatches to."

---

## 8. The Supervisor's tool kit

The Supervisor is an `AgenticBaseAgent` with `uses_tools=True`.

### 8.1 Read-only tools (called during reasoning)

| Tool | Purpose |
|---|---|
| `read_student_full_profile` | If `student_snapshot` doesn't include enough detail, fetch full profile (rare; usually snapshot is enough) |
| `read_recent_agent_chain` | If reasoning about a multi-turn flow, see the call chain from prior turns |
| `read_specific_memory` | Look up a specific memory by key when student references it ("you said earlier that...") |
| `check_capability_real_time` | Verify an agent's `available_now` status hasn't changed since context was constructed |

These tools are cheap (sub-second), read-only, and side-effect-free. The Supervisor calls them sparingly — most decisions are made from `SupervisorContext` alone. Tools are for the edge cases.

### 8.2 Action tools (called to execute decisions)

| Tool | Purpose |
|---|---|
| `dispatch_agent` | Wraps `call_agent` (D4) with Supervisor-specific telemetry. Single-agent dispatch. |
| `dispatch_chain` | Executes a chain plan, handling step ordering, output passing, on_failure policy |
| `compose_decline` | Builds a structured decline response with appropriate messaging per `decline_reason` |
| `compose_clarification` | Builds a clarification request with the questions the Supervisor wants answered |
| `escalate_to_admin` | Writes to `student_inbox` with admin-facing summary; sends notification per existing notification infra |

The Supervisor's `RouteDecision` output drives which tool gets called. The dispatch layer that lives between Supervisor and these tools is what enforces validation (e.g., no invalid agent names, no chains over 3 steps).

### 8.3 What the Supervisor explicitly does NOT have

- ❌ `direct_database_write` — Supervisor never writes to DB directly. All writes go through specialists or the dispatch layer.
- ❌ `send_email` / `send_sms` — communication is via student_inbox or specialist agents (interrupt_agent), not directly.
- ❌ `modify_entitlements` — Supervisor reads entitlement state, never modifies.
- ❌ `invoke_llm_directly` — Supervisor uses LLM via its own AgenticBaseAgent.execute(); it doesn't call LLMs as tools to "answer the student directly."

This last one matters most. The temptation will be to give the Supervisor a "just answer simple questions yourself" tool. Resist. The moment the Supervisor answers questions, it becomes a generalist tutor, and its routing job suffers. Routing is a separate job from tutoring.

### 8.4 Tool implementation phasing

Pass 3d will design and implement the actual tool bodies. For Supervisor v1 in D9, only the action tools are required:
- `dispatch_agent` (wraps call_agent — already exists in D4)
- `dispatch_chain` (new but mechanical)
- `compose_decline` (new but mechanical — basically templating)
- `compose_clarification` (new but mechanical)
- `escalate_to_admin` (new — wires to student_inbox)

Read-only tools can be deferred. The Supervisor can operate on `SupervisorContext` alone for v1; tool-based context enrichment is v2 polish.

---

## 9. Observability — debugging a single student's journey

At 1,000 students with multi-agent chains and proactive flows, you need to be able to answer: "what did the system do for student X today, and why?"

### 9.1 The trace query

Given a `student_id`, an operator should be able to reconstruct:

1. Every Supervisor decision (with reasoning)
2. Every specialist invocation (which agent, what context, what output summary)
3. Every chain (visualized as a tree or sequence)
4. Every memory write/read
5. Every escalation, decline, or clarification request
6. Cost per request and per day

The data model already supports this:
- `agent_actions` rows for every agent invocation (Supervisor + specialists)
- `agent_call_chain` rows linking related calls (D4)
- `agent_memory` rows for memory operations (D2)
- `agent_evaluations` rows for Critic scores (D5)
- `agent_escalations` rows for escalations (D5)

What's missing: an admin UI surface to render this as a coherent timeline.

### 9.2 The admin trace endpoint (PG-7 + PG-8 from Track 5)

Two endpoints needed in D9:

```
GET /api/v1/admin/students/{student_id}/journey
  ?from=<timestamp>
  &to=<timestamp>
  &include=actions,chains,memory,escalations
```

Returns a structured timeline of everything the OS did for that student in the window. Used by:
- Admin UI (existing /admin/students/[id] page, expanded)
- Critic (when scoring a sampled action, fetches the full context)
- Customer support ("the student says X happened, can you check?")

```
GET /api/v1/admin/agents/{agent_name}/recent-decisions
  ?limit=50
```

Returns recent Supervisor decisions that dispatched to this agent. Used by:
- Operators monitoring routing quality
- Critic sampling
- Investigating "why is X agent getting hit so much?"

These endpoints address PG-7 (admin "list recent escalations") and PG-8 (admin "trace") from Track 5. They're part of D9's scope.

### 9.3 The dashboard queries that should "just work"

A small set of SQL queries that should be answerable without any new infrastructure once D9 ships:

- "How many requests did the Supervisor decline last week, broken down by `decline_reason`?"
- "Which agents are dispatched most/least often?"
- "What's the average chain length, and how does it correlate with Critic score?"
- "Which agents have the highest escalation rate, and what's the reason distribution?"
- "What's the per-student cost distribution? P50, P95, P99?"

These queries become the operational dashboard for AICareerOS. They're not built in D9 — they're enabled by D9. Building them is a small additional pass (probably folded into Pass 3i scale + observability).

### 9.4 PostHog event taxonomy

Existing PostHog integration captures events. The Supervisor adds these:

- `supervisor.decision` (one per invocation, properties: action, primary_intent, target_agent, confidence, latency_ms, cost_inr)
- `supervisor.decline` (one per decline, properties: decline_reason, student_id_hashed)
- `supervisor.escalate` (one per escalation, properties: escalation_reason)
- `supervisor.chain_dispatch` (one per chain, properties: chain_length, primary_intent)
- `supervisor.chain_aborted` (one per abort, properties: aborted_at_step, reason)

Property naming follows existing conventions (snake_case, hashed user IDs for privacy).

---

## 10. Testing strategy

The Supervisor is too important to test only via integration. Layered testing:

### 10.1 Unit tests (no LLM)

Test the deterministic parts:
- `RouteDecision` schema validation (valid decisions parse, invalid fail)
- Dispatch layer: given a `RouteDecision`, does the right tool get called with the right args?
- Chain dispatch: given a chain plan, does state pass between steps correctly?
- Policy gates: given various entitlement/rate/cost states, does the gate enforce correctly?
- Failure handling: given a specialist exception, does the fallback fire?

These run fast, in CI, no API keys needed. Following the pattern D7's tests established (uses_self_eval=False on test agents, _StubLLM for the LLM call, mocked tools).

### 10.2 Prompt evaluation tests (with LLM, gated)

Test the Supervisor's actual decision quality on a curated set of test cases:

- Single-intent requests → expect single dispatch to expected agent
- Multi-intent requests → expect chain or single+suggestion
- Out-of-scope requests → expect decline with `out_of_scope`
- Unentitled requests → expect decline with `entitlement_required`
- Ambiguous requests → expect `ask_clarification`
- Edge cases: empty messages, very long messages, prompt injection attempts, requests in non-English, requests with attached code

For each test case: a list of acceptable decisions (because there's often more than one right answer). The test passes if the Supervisor's decision is in the acceptable set.

These tests run in CI when ANTHROPIC_API_KEY is set; skipped otherwise. Cost ~10-30 INR per full run. Run on PR for any change to the Supervisor prompt or the agent capability registry.

### 10.3 Critic-based regression detection

Once the Critic (D5) is sampling Supervisor decisions in production, baseline scores per intent class are tracked. A prompt change that drops `tutoring_question` routing quality from 0.85 to 0.65 average shows up as a regression alert. This is automated quality monitoring, not just unit tests.

### 10.4 E2E tests via the existing Playwright surface

Track 5 established the pattern. Add Supervisor-specific E2E tests:
- Hit the canonical `/api/v1/agentic/{flow}/chat` endpoint with a known request, assert the right agent ran (verifiable via `/api/v1/admin/students/{student_id}/journey`)
- Verify entitlement gating: unentitled user gets 402, entitled user gets routed
- Verify cost ceiling: simulate exhausted budget, verify decline message

These tests live alongside the Track 5 spec file and grow with each implementation deliverable.

---

## 11. Migration path from MOA

The current MOA is in `backend/app/agents/moa.py`. It's 2-node LangGraph + keyword router + Haiku classifier. The Supervisor replaces it. The migration cannot be a flag-flip — it has to be staged.

### 11.1 Phase 1 — Coexistence (D9 ships)

The Supervisor lands as a new agent invokable via the new canonical endpoint `/api/v1/agentic/{flow}/chat`. The old MOA stays alive at `/api/v1/agents/chat` and `/api/v1/agents/stream` for any UI surfaces still calling them.

D8's `example_learning_coach` becomes the first agent reachable via the Supervisor (the canonical pattern). Other agents stay on legacy `BaseAgent`, reachable via legacy MOA.

This is the safest possible rollout: no existing functionality changes; new functionality is purely additive.

### 11.2 Phase 2 — Selective routing (D11–D12)

As specialist agents migrate to `AgenticBaseAgent`, they become reachable via the Supervisor's roster. The frontend is gradually pointed at the new endpoint for those flows. The legacy MOA keeps serving anything not yet migrated.

This phase happens flow-by-flow, not big-bang. E.g., when senior_engineer migrates (D11), the practice review flow points at the new endpoint; everything else stays on legacy.

### 11.3 Phase 3 — Cutover (D17 or thereabouts)

When all 14 specialist agents are migrated and reachable via the Supervisor, the legacy MOA is marked `@deprecated` (using the existing 38-handler deprecation pipeline). After the standard 2-week sunset window with logged usage, the MOA file and its routes are deleted.

Total MOA lifetime in coexistence: roughly the duration of the agent migration deliverables. Not weeks of overlapping logic permanently.

### 11.4 What gets deleted at cutover

- `backend/app/agents/moa.py` (the StateGraph + keyword router)
- `backend/app/services/agent_orchestrator.py` (replaced by `AgenticOrchestratorService`)
- `backend/app/api/v1/routes/agents.py` (legacy /chat, /stream, /list — the new endpoint replaces them)

These files become inert at Phase 3 and get removed cleanly. No dead code carried forward.

---

## 12. Open questions explicitly deferred to later passes

| Question | Deferred to |
|---|---|
| Exact entitlement schema per tier (which tier unlocks which agents at which cost ceiling) | Pass 3f |
| The 11 D3 stub bodies + new tools the Supervisor's specialists will need | Pass 3d |
| The curriculum knowledge graph schema and how Supervisor queries it via specialists | Pass 3e |
| Output-side safety checks (PII detection, content moderation, prompt-injection-success markers) | Pass 3g |
| The interrupt_agent's specific intervention rules and timing | Pass 3h |
| Connection pool sizing, Redis memory budget, Postgres query optimization | Pass 3i |

---

## 13. Implementation handoff to D9

D9 will be the first implementation deliverable that builds the Supervisor.

### 13.1 D9 scope (must include)

**New files:**
- `backend/app/agents/supervisor.py` — `Supervisor(AgenticBaseAgent)` with prompt
- `backend/app/agents/prompts/supervisor.md` — the prompt
- `backend/app/services/agentic_orchestrator.py` — replaces `AgentOrchestratorService` for new endpoint
- `backend/app/services/student_snapshot_service.py` — computes and caches `StudentSnapshot`
- `backend/app/schemas/supervisor.py` — Pydantic models for `SupervisorContext`, `RouteDecision`, `ChainStep`, `StudentSnapshot`, `AgentCapability`
- `backend/app/api/v1/routes/agentic.py` — the canonical `/api/v1/agentic/{flow}/chat` endpoint
- `backend/app/api/v1/dependencies/entitlement.py` — extend with `require_active_entitlement` (or wherever the right placement is per Pass 3f)
- `backend/app/agents/dispatch.py` — the dispatch layer (single + chain + handoff handling)
- `backend/tests/test_agents/test_supervisor.py` — unit tests
- `frontend/e2e/supervisor.spec.ts` — E2E tests

**New tables (additive migration 0055):**
- Possibly `student_snapshots` (cached, recomputable — could also be Redis-only)
- Possibly extensions to `agent_actions` to add `summary` column for memory_curator's 1-sentence summaries
- Possibly indexes on `agent_call_chain` for the trace query performance

**Wired changes:**
- PG-1 fix — `_agentic_loader` called from FastAPI lifespan
- Capability registration — every existing agent gets a basic `AgentCapability` declaration (most won't be migrated yet, but registered)
- `learning_coach` (D8) reachable through new endpoint

**Out of D9 scope:**
- Migration of any specialist beyond learning_coach (those are D10+)
- Real bodies for specialist tools (those are D10+ via Pass 3d's design)
- Curriculum graph (Pass 3e + D15)
- Interrupt agent / proactive layer (Pass 3h + D16)

### 13.2 D9 success criteria

D9 is "done" when:

1. A student with an active course entitlement can hit `/api/v1/agentic/{flow}/chat` and get routed to learning_coach via the Supervisor
2. A student without entitlements gets a 402 with structured `decline_message`
3. The Supervisor's decision is logged in `agent_actions` with reasoning
4. The trace endpoint `/api/v1/admin/students/{student_id}/journey` returns a coherent timeline
5. Unit tests cover all five failure classes from §7.1
6. E2E test exists for: entitled happy path, unentitled 402, Supervisor escalation fallback to keyword routing
7. PG-1 fix verified — webhooks subscribed in FastAPI process
8. Cost ceiling verified — synthetic test that exhausts budget and gets graceful decline

---

## 14. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Supervisor over-routes to chains, increasing latency + cost | Medium | Medium | Chain length cap of 3, observability shows chain rate, can tighten via prompt |
| Supervisor under-routes (always picks default), wasting specialists | Low | Medium | Critic sampling catches routing-quality regressions |
| Supervisor hallucinates agent names | Medium | Low | Dispatch layer validates; falls back to default; logged for prompt improvement |
| Student snapshot service becomes performance bottleneck | Medium | High | 5-minute Redis cache; recompute is async; falls back to empty snapshot under load |
| Cost ceiling miscalibrated (too tight: students hit limit; too loose: bills explode) | High | Medium | Start at 50 INR/day; observe distribution; adjust per-tier in Pass 3f |
| Migration from MOA creates parallel-routing bugs | Medium | High | Per-flow gradual migration; legacy MOA unchanged until cutover |
| Supervisor prompt drift over time degrades routing quality | High | Medium | Critic sampling + regression test suite catch drift; prompt versioned |

The two highest-impact risks are the snapshot performance (mitigated by caching) and the migration parallel-routing (mitigated by phased rollout). Both are managed by design choices already in this pass.

---

## 15. What this design earns

If D9 ships this design, here's what changes:

**For the student:**
- Their request goes to the right agent more reliably (real reasoning, not keyword match)
- They can ask multi-step things and get them done in one turn
- They get refused gracefully when something is out of scope, not cryptic 500s
- They never silently hit a paywall they didn't know existed
- Cost limits protect them from runaway bills

**For the operator:**
- Every routing decision is auditable with reasoning
- Routing quality is measurable and trends visible
- A single student's journey can be traced end-to-end
- Specialists stay narrow and focused; new agents plug in without architectural changes
- The system is debuggable when things go wrong

**For future contributors:**
- The agent layer is genuinely extensible — declare a capability, get routed traffic
- The scope of each layer (Supervisor, dispatch, specialists) is enforced by design
- Failure modes are documented and tested
- The Supervisor can be improved (prompt changes, model upgrades) without touching specialists

This is the layer that makes "AICareerOS" different from "26 chatbots in a registry."
