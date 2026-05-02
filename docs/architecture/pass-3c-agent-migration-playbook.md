---
title: Pass 3c — Agent Migration Playbook
status: Final — implementation contract for D10 onward
date: After Pass 3b sign-off, before D10 implementation
authored_by: Architect Claude (Opus 4.7)
purpose: Per-agent migration recipes for each of the 14 surviving legacy agents (the Pass 3a Addendum roster minus Learning Coach, Supervisor, and interrupt_agent). Defines the AgentCapability declarations, memory patterns, tool requirements, output schemas, handoff rules, and full rewritten prompts. Implementation deliverables D10 through D17 each implement one or more of these migrations.
supersedes: nothing
superseded_by: nothing — this is the canonical agent migration contract
informs: D10 (billing_support), D11 (senior_engineer), D12 (career services bundle), D13 (mock_interview), D14 (practice_curator), D15 (content_ingestion), D16 (interrupt_agent), D17 (cleanup + final cutover)
implemented_by: D10 through D17
depends_on: Pass 3a Addendum (roster), Pass 3b (Supervisor design), AGENTIC_OS.md (D1–D8 foundation)
---

# Pass 3c — Agent Migration Playbook

> Every legacy agent that survives the Pass 3a Addendum gets migrated to `AgenticBaseAgent`. This document is the per-agent recipe for that migration. Read Sections A–D for the framework; jump to the specific E section when implementing that agent's migration.

> Read alongside: Pass 3a Addendum (which agents survive), Pass 3b (the Supervisor that orchestrates them), AGENTIC_OS.md (the primitives they use).

---

## Section A — The Migration Template

Every agent migration follows this template. The template is the contract; per-agent variation is the parameter. Sections E1–E14 are the parameterizations.

### A.1 Inputs to a migration

For each agent being migrated, the migration deliverable receives:

1. **The agent's current `BaseAgent` implementation** at `backend/app/agents/{name}.py`
2. **The agent's current prompt** at `backend/app/agents/prompts/{name}.md` (if it exists)
3. **The Pass 3a Addendum verdict** for the agent (KEEP / REWRITE / MIGRATE / etc.)
4. **The Pass 3c per-agent specification** (sections E1–E14 below)
5. **The `AgenticBaseAgent` from D7** as the new parent class

### A.2 Outputs of a migration

Every migration produces:

1. **A new agent class** extending `AgenticBaseAgent` with appropriate opt-in flags
2. **A new prompt file** at `backend/app/agents/prompts/{name}.md` (rewritten or revised per spec)
3. **An `AgentCapability` registration** in the agent's module (used by the Supervisor's capability registry)
4. **A Pydantic output schema** for the agent's structured response
5. **Tool registrations** for any agent-specific tools (most tool implementations are deferred to Pass 3d; the agent declares what it needs)
6. **Unit tests** in `backend/tests/test_agents/test_{name}.py` (no LLM, _StubLLM pattern from D7)
7. **Migration of the agent's existing callers** (frontend pages, services, tasks) to use the new endpoint via the Supervisor where appropriate
8. **Deletion of the agent's old `BaseAgent` implementation** at the end of the migration deliverable

### A.3 The five primitive flags

Every migrated agent declares its primitive usage:

```python
class FooAgent(AgenticBaseAgent):
    name = "foo"

    uses_memory: bool = True       # reads from / writes to agent_memory via MemoryStore
    uses_tools: bool = True        # uses the @tool registry for typed tool calls
    uses_inter_agent: bool = False # calls call_agent() to dispatch to other agents
    uses_self_eval: bool = False   # invokes Critic on its own outputs (default OFF, expensive)
    uses_proactive: bool = False   # has @proactive(cron=...) or @on_event(webhook=...) trigger
```

**Defaults applied across the roster (per the architect's Pass 3c decisions):**

- `uses_memory = True` for all agents EXCEPT pure content-generation workers (mcq_factory)
- `uses_tools = True` for all agents (every agent has at least the standard memory tools)
- `uses_self_eval = False` by default; turned ON per-agent only when Critic sampling shows the agent's outputs need automated quality monitoring
- `uses_inter_agent = True` only when the agent explicitly hands off (career_coach → resume_reviewer, tailored_resume → resume_reviewer for validation, project_evaluator → portfolio_builder)
- `uses_proactive = True` only when there's a clear scheduled or webhook trigger (progress_report weekly, content_ingestion webhook, study_planner nightly)

### A.4 Memory access pattern

Every agent that has `uses_memory=True` follows this read/write pattern:

**Read on entry (in `execute()`):**

```python
async def execute(self, payload: AgentInput, ctx: AgentContext) -> AgentResult:
    # 1. Read student-scoped memories relevant to this agent
    student_memories = await self.memory.recall(
        user_id=payload.student_id,
        scope="user",
        agent_name=self.name,  # this agent's prior interactions with this student
        query=payload.task,    # semantic recall against the current request
        limit=10,
    )

    # 2. Read agent-scoped memories (cross-student insights this agent has learned)
    agent_memories = await self.memory.recall(
        scope="agent",
        agent_name=self.name,
        query=payload.task,
        limit=5,
    )

    # 3. Build the LLM messages with memory injected as context
    messages = self._build_messages(payload, student_memories, agent_memories)
    # ... rest of execute
```

**Write at relevant moments:**

```python
    # During or after the LLM call, write memories worth preserving
    if response.contains_durable_insight:
        await self.memory.write(
            user_id=payload.student_id,
            scope="user",
            agent_name=self.name,
            key=f"{insight_type}:{insight_subject}",
            value={"summary": response.insight_summary, "confidence": 0.8},
            valence=0.5,  # neutral-to-positive
        )
```

**The memory_curator pattern (deferred to Pass 3d/D10):** in the long run, agents don't write directly. They emit `MemoryCandidate` objects and a centralized `memory_curator` decides what to persist. For initial migrations, agents write directly; the curator pattern is added later as a refinement.

### A.5 Standard memory keys per agent

To keep the memory bank queryable, every agent uses key patterns from a shared namespace:

- `pref:{topic}` — student preferences (e.g., `pref:tutoring_mode`, `pref:communication_tone`)
- `mastery:{concept_id}` — concept mastery signals (written by Learning Coach, read by others)
- `misconception:{concept_id}` — recurring misconceptions
- `submission:{kind}:{id}` — references to student submissions (code, capstone, resume)
- `feedback:{kind}:{date}` — feedback given by an agent (e.g., `feedback:code_review:2026-05-02`)
- `goal:active` — current goal_contract reference (single-keyed to overwrite on update)
- `interaction:{kind}:{id}` — significant moments worth remembering (frustration spike, breakthrough, milestone)

Agent-specific keys are namespaced by agent name where collisions could occur:

- `mock_interview:weakness:{topic}` — weaknesses identified across interviews
- `senior_engineer:pattern:{name}` — code patterns this student keeps using

### A.6 Tool access pattern

Every agent declares the tools it needs in its `AgentCapability`. Tools come in three categories:

1. **Universal tools** — available to every agent (memory read/write, log_event)
2. **Domain tools** — available to agents in a domain (e.g., curriculum graph queries available to learning + career agents)
3. **Agent-specific tools** — exclusive to one agent (e.g., `run_static_analysis` for senior_engineer)

Pass 3d will design the actual tool bodies. This pass declares which agent needs which tool. Where a tool doesn't exist yet, the agent's spec lists it as `(deferred to Pass 3d)`.

### A.7 Output schema

Every migrated agent returns a structured Pydantic output, not a free-form string. The `AgentResult.output` field becomes a typed schema. Three benefits:

- The Supervisor can read structured outputs to make handoff decisions
- The Critic (D5) can validate quality against the schema
- Downstream code (notification builders, dashboards) doesn't parse free text

Some agents have multiple modes; each mode has its own output schema variant.

### A.8 Handoff rules

Every agent declares whether and when it returns a `HandoffRequest`. Per Pass 3b:

```python
class HandoffRequest(BaseModel):
    target_agent: str
    reason: str
    suggested_context: dict[str, Any]
    handoff_type: Literal["mandatory", "suggested"]
```

Most leaf agents never hand off. Agents that do hand off (career_coach, tailored_resume, project_evaluator) declare their handoff conditions explicitly.

Handoff requests are not commands. The Supervisor decides whether to honor them, per Pass 3b §5.3.

### A.9 The new prompt structure

Every agent's prompt at `backend/app/agents/prompts/{name}.md` follows this structure:

```
[ROLE]
One paragraph: who this agent is in AICareerOS, what it does, what it doesn't do.

[MEMORY ACCESS]
What memories the agent has access to and how to use them. Tells the LLM how
to reason about prior context.

[TOOLS]
What tools the agent has and when to call which. Includes signature reminders.

[MODES] (only for agents with modes)
Each mode's purpose, when to use it, what the output looks like.

[OUTPUT SCHEMA]
The Pydantic schema (described in natural language for the LLM, with
strict instructions on what to populate).

[HARD CONSTRAINTS]
What the agent MUST do and MUST NOT do. Enforced by both prompt discipline
and downstream validation.

[HANDOFF RULES]
When to return a HandoffRequest, to which agent, with what suggested_context.
"Never" is a valid handoff rule.

[EXAMPLES]
2-4 worked examples covering the main cases.

[BRAND]
You are an agent in AICareerOS. Refer to AICareerOS by name when self-referring.
Never identify yourself as "PAE" or "CareerForge" — those are legacy names.
```

The brand section is small but matters — it implements the naming sweep across every agent prompt.

### A.10 Migration checklist (the implementation pattern)

Every implementation deliverable that migrates an agent follows this checklist:

```
[ ] Create new agent class at backend/app/agents/{name}_v2.py extending AgenticBaseAgent
    (the _v2 suffix avoids clobbering the legacy file during the migration; deleted at end)
[ ] Set the five primitive flags per spec
[ ] Write the new prompt file at backend/app/agents/prompts/{name}.md
    (back up the old prompt as {name}.legacy.md.bak — never edit in place)
[ ] Define the output schema in backend/app/schemas/agents/{name}.py
[ ] Register tool requirements (declare which tools; bodies may be deferred to Pass 3d)
[ ] Register the AgentCapability in backend/app/agents/{name}_v2.py
[ ] Write unit tests at backend/tests/test_agents/test_{name}_v2.py
    (all five failure classes from Pass 3b §7.1, _StubLLM, no API keys needed)
[ ] Update callers to use the Supervisor endpoint
    (frontend pages, services, Celery tasks that invoked this agent directly)
[ ] Run the full test suite — confirm no regression
[ ] Delete backend/app/agents/{name}.py (the legacy file)
[ ] Rename {name}_v2.py to {name}.py
[ ] Delete the .legacy.md.bak prompt file
[ ] Update AGENT_REGISTRY entry to point at the new class
[ ] Add to docs/AGENTIC_OS.md "agents migrated" list with the deliverable number
```

The `_v2` suffix during migration is load-bearing: it lets the legacy and new agents coexist in the same registry briefly during testing. The cutover at the end is atomic (rename + delete + registry update in one commit).

---

## Section B — Migration Sequencing

The order in which agents migrate matters because some are dependencies of others. Implementation deliverables D10 through D17 ship migrations in this order:

| Deliverable | Agent(s) migrated | Why this position |
|---|---|---|
| **D9** | (Supervisor + dispatch infrastructure; learning_coach already on AgenticBaseAgent from D8) | Foundation; nothing migrated yet |
| **D10** | `billing_support` | Narrow scope, Haiku model, low risk, no inter-agent dependencies. The training-wheels migration. |
| **D11** | `senior_engineer` (merged from code_review + coding_assistant + senior_engineer) | High-traffic, but no upstream dependencies. Establishes the merge pattern. |
| **D12** | Career bundle: `career_coach`, `study_planner` (NEW), `resume_reviewer`, `tailored_resume` | Migrate as a bundle because they hand off to each other. Migrating one without the others breaks handoff chains. |
| **D13** | `mock_interview` | Heavy refactor; benefits from senior_engineer being available for code-coding-round handoffs. |
| **D14** | `practice_curator` (NEW), `project_evaluator` | practice_curator is brand new; project_evaluator needs the Supervisor + memory layer working. |
| **D15** | `content_ingestion` (with curriculum_mapper merged in) | Content-side; can run later because student-facing agents don't depend on it day-1. |
| **D16** | `interrupt_agent` (NEW) + `progress_report` migration | The proactive layer. Both depend on memory + risk signals being mature. |
| **D17** | `mcq_factory`, `adaptive_quiz`, `spaced_repetition`, `portfolio_builder`, `adaptive_path` | Lower-traffic agents; cleanup phase. (Note: per Pass 3a Addendum, several of these are folded into Learning Coach already; this deliverable only migrates the ones that remain standalone.) |

Note on the Pass 3a Addendum: the Addendum reduces the standalone-agent roster significantly. Agents folded into Learning Coach (socratic_tutor, student_buddy, adaptive_path, spaced_repetition, knowledge_graph) don't migrate — they're consumed by Learning Coach's mode system. D17's scope is the residual standalone agents, which on review may be smaller than the table suggests. Final D17 scope is determined when we get there.

### B.1 Critical path

The critical path through migrations is: D9 → D11 → D12 → D13. By end of D13, the platform's highest-traffic flows (chat, code review, career services, interview) all run through the Supervisor. Everything after D13 is risk reduction and feature completion, not platform-level architecture.

If forced to ship before all migrations complete, after D13 is the natural pause point.

### B.2 Coexistence during migration

During Phases 1 and 2 of MOA migration (Pass 3b §11), the legacy MOA continues to serve unmigrated agents. The frontend gradually points individual flows at the new `/api/v1/agentic/{flow}/chat` endpoint as each agent migrates. There is never a moment when an agent is unreachable.

---

## Section C — The `AgentCapability` Registry Pattern

Every agent registers an `AgentCapability` declaration. The Supervisor's prompt is built dynamically from these declarations.

### C.1 Declaration

In each agent's module:

```python
# backend/app/agents/billing_support.py

from app.agents.agentic_base import AgenticBaseAgent
from app.agents.capability import AgentCapability, register_capability

CAPABILITY = AgentCapability(
    name="billing_support",
    description=(
        "Answers billing, subscription, and payment questions. Reads the student's "
        "actual order history and entitlements to give grounded answers (not generic "
        "FAQ). Best for requests about: invoices, refunds, plan changes, payment "
        "failures, receipt downloads. Does not handle: course content questions, "
        "career advice, technical learning support."
    ),
    inputs_required=[],  # works from student_id alone
    inputs_optional=["specific_order_id", "specific_invoice_number"],
    outputs_provided=["answer", "suggested_action"],
    typical_latency_ms=1500,
    typical_cost_inr=Decimal("0.20"),
    requires_entitlement=False,  # billing questions are answered even for past students
    handoff_targets=[],  # leaf agent
    model_used="claude-haiku-4-5",
)

register_capability(CAPABILITY)


class BillingSupportAgent(AgenticBaseAgent):
    name = "billing_support"
    ...
```

### C.2 Discovery

The Supervisor builds its prompt by iterating over the capability registry, filtering by:

- **Active entitlement match:** if `requires_entitlement=True`, the student must have an active entitlement; otherwise the capability is filtered out
- **`available_now` runtime check:** if the agent is rate-limited or its dependencies are down, mark unavailable
- **Tier match:** if Pass 3f introduces tiered access, filter by the student's tier

This filtering happens once per Supervisor invocation. The Supervisor never sees agents the student can't use, which removes a class of routing errors.

### C.3 Description guidelines

The `description` field is read by the LLM. Write it for the Supervisor's reasoning, not for humans:

- **Do:** state when this agent is the right choice (`Best for requests about: ...`)
- **Do:** state when it's the wrong choice (`Does not handle: ...`)
- **Do:** mention key inputs the agent needs (so the Supervisor knows what to put in `constructed_context`)
- **Don't:** include marketing language ("powerful AI assistant for...")
- **Don't:** describe internal implementation ("uses Haiku model with...")
- **Don't:** be aspirational ("can help with anything related to...")

A good description is 50-100 words and reads like a reference card.

### C.4 Capability versioning

When an agent's capability changes substantively (new modes, new inputs, retired tools), bump a version number:

```python
CAPABILITY = AgentCapability(
    name="senior_engineer",
    version=2,  # bumped when modes were merged from 3 legacy agents
    ...
)
```

The Critic uses version numbers to track quality across capability changes. A drop in routing accuracy after a version bump is a regression signal.

---

## Section D — Migration Acceptance Criteria

For each agent migration deliverable to be "done":

1. The agent extends `AgenticBaseAgent` and declares its primitive flags
2. The new prompt is written following the structure in §A.9
3. The output schema is defined and validated in tests
4. The `AgentCapability` is registered and visible to the Supervisor
5. Unit tests cover: happy path, all five failure classes from Pass 3b §7.1, schema validation, memory read/write
6. E2E test confirms the Supervisor can route a representative request to this agent and get a valid response
7. All callers of the legacy agent now use the Supervisor endpoint (or the agent is invoked via Celery/webhook for proactive agents)
8. Legacy agent file is deleted; new file is the canonical one
9. Capability registry includes this agent
10. Critic (D5) is configured to sample this agent at 5% (default) — turned on if the team wants automated quality monitoring; otherwise off
11. The agent's section in this document (E1–E14 below) is marked "Implemented in D{N}"

---

## Sections E1–E14: Per-Agent Migrations

Each section below is the implementation contract for that agent. When the implementation deliverable for that agent runs, it implements these specifications.

---

### E1 — `billing_support` (D10, the training-wheels migration)

**Pass 3a verdict:** KEEP, light rewrite. **Confidence:** HIGH.

**Why this one first:** narrow scope, Haiku model, no inter-agent dependencies, real consumer. If this migration goes wrong, blast radius is small. Establishes the migration pattern for everything that follows.

**`AgentCapability`:**

```python
CAPABILITY = AgentCapability(
    name="billing_support",
    description=(
        "Answers billing, subscription, payment, refund, and receipt questions. "
        "Reads the student's actual order history, course entitlements, and refund "
        "status to give grounded answers, not generic FAQ. Best for: 'where is my "
        "receipt', 'why was I charged', 'how do I cancel', 'when will my refund "
        "arrive'. Does not handle: course content, career advice, technical support."
    ),
    inputs_required=[],
    inputs_optional=["order_id", "invoice_number", "specific_concern"],
    outputs_provided=["answer", "suggested_action", "ticket_id_if_escalated"],
    typical_latency_ms=1500,
    typical_cost_inr=Decimal("0.20"),
    requires_entitlement=False,  # past students can still ask billing questions
    handoff_targets=[],
    model_used="claude-haiku-4-5",
)
```

**Primitive flags:**

```python
uses_memory = True       # remembers prior billing concerns + preferences
uses_tools = True        # reads orders, entitlements, refunds tables via tools
uses_inter_agent = False
uses_self_eval = False
uses_proactive = False
```

**Memory access:**

- **Reads:** `pref:billing_communication_tone` (formal vs. conversational), `interaction:billing_concern:*` (past concerns with this student)
- **Writes:** new billing concerns get logged as `interaction:billing_concern:{date}` so future queries have context

**Tools needed:**

- `lookup_order_history(student_id, limit=20)` → list of orders
- `lookup_active_entitlements(student_id)` → list of active courses
- `lookup_refund_status(student_id, order_id?)` → refund state machine status
- `escalate_to_human(reason, summary)` → writes student_inbox row, returns ticket_id

(All four tools are deferred to Pass 3d. For D10 implementation, tool bodies are minimal SQL-backed wrappers.)

**Output schema:**

```python
class BillingSupportOutput(BaseModel):
    answer: str  # the actual response to the student, plain text
    grounded_in: list[str] = []  # which records were referenced (e.g., "order CF-20260415-A8K2")
    suggested_action: Literal["none", "wait", "contact_support", "self_serve"] | None = None
    self_serve_url: str | None = None  # if action is self_serve
    escalation_ticket_id: str | None = None  # if escalated to human
    confidence: Literal["high", "medium", "low"]
```

**Handoff rules:** `billing_support` is a leaf agent. Never hands off to another agent. If a question is out of scope (e.g., student asks about course content while in billing chat), it returns a polite redirect in `answer` and `suggested_action="self_serve"` rather than handing off — let the Supervisor decide if a re-route is needed via the next student message.

**The full new prompt** (`backend/app/agents/prompts/billing_support.md`):

```markdown
# Role

You are the Billing Support agent in AICareerOS, a learning operating system for engineers becoming senior GenAI engineers. Your job is to answer student questions about billing, subscriptions, payments, refunds, and receipts — accurately, kindly, and grounded in the student's actual records.

You do not handle course content questions, career advice, or technical learning support. If a student asks about those, politely redirect them and end the conversation; the Supervisor will route their next message to the right place.

# Memory access

You have access to:

1. **The student's actual records** — pulled via tools, not assumed. Always look up before answering questions about specific orders, entitlements, or refunds.
2. **Past billing interactions with this student** — read from memory at `interaction:billing_concern:*` keys. Use these to recognize repeat concerns, remember context (e.g., "you mentioned your card was being replaced last week").
3. **Communication preference** — at memory key `pref:billing_communication_tone`. Default is "professional but warm" if no preference set.

When you finish a substantive billing interaction, write a memory at `interaction:billing_concern:{YYYY-MM-DD}` summarizing what was asked and what was resolved, with `valence=0.5` for neutral concerns or `valence=-0.3` for unresolved frustration.

# Tools

- `lookup_order_history(student_id, limit=20)` — list of the student's orders, most recent first
- `lookup_active_entitlements(student_id)` — what courses the student currently has access to
- `lookup_refund_status(student_id, order_id=None)` — refund state for a specific order or all
- `escalate_to_human(reason, summary)` — when the student's question is outside your authority (e.g., "I want to dispute a charge with my bank"), escalate to a human admin

ALWAYS use lookup tools before answering questions about specific records. Never guess at order numbers, dates, or amounts.

# Output schema

Return a `BillingSupportOutput` JSON object with these fields:

- `answer` (required): the response to send to the student, in plain text. Match the student's communication preference. Be specific when you have lookup results; be honest when you don't have information.
- `grounded_in`: list of record references you used (e.g., `["order CF-20260415-A8K2"]`). Empty if your answer didn't require record lookups.
- `suggested_action`: one of `none`, `wait` (e.g., "your refund will arrive in 5-7 days"), `contact_support` (when escalation is the right move), or `self_serve` (when there's a self-service flow they should use).
- `self_serve_url`: only if `suggested_action="self_serve"`.
- `escalation_ticket_id`: only if you escalated.
- `confidence`: your confidence in the answer's correctness. Use `low` when relying on assumptions.

# Hard constraints

You MUST:
- Look up actual records before stating specific details (amounts, dates, IDs)
- Be honest when you don't have information ("I don't see that order in your account — could you share the receipt number?")
- Reference receipt prefixes correctly: legacy receipts use `CF-` (CareerForge era), new receipts use `AC-` (AICareerOS)
- Escalate genuine grievances to human admin (frustration, repeated unresolved issues, regulatory concerns)

You MUST NOT:
- Promise refunds, timelines, or outcomes you don't have authority to commit to
- Make up order numbers, transaction IDs, or amounts
- Discuss other students' accounts or aggregated data
- Provide course content help — redirect politely if asked
- Discuss pricing strategy, marketing, or competitor comparisons

# Handoff rules

You are a leaf agent. You never hand off to other agents. If a student's question is out of scope, end your turn with a polite redirect in `answer` and `suggested_action="none"`. The Supervisor will route their next message appropriately.

# Examples

**Example 1 — straightforward refund check:**

Student: "Where's my refund?"
You: [call `lookup_refund_status(student_id)`] [find a refund_attempted entry from 3 days ago, status="processing"]
Output: {
  "answer": "Your refund for order CF-20260428-X7M2 is currently processing. Refunds typically arrive in your bank account 5-7 business days from the initiation date — so you should see it by early next week. I'll let you know if anything changes.",
  "grounded_in": ["order CF-20260428-X7M2", "refund initiated 2026-04-28"],
  "suggested_action": "wait",
  "confidence": "high"
}

**Example 2 — student asks about course content while in billing chat:**

Student: "What's covered in the GenAI Engineer course?"
Output: {
  "answer": "That's a course content question — I focus on billing and account questions here. Just send another message about the course content and our system will route you to the right place. Anything else billing-related I can help with?",
  "grounded_in": [],
  "suggested_action": "none",
  "confidence": "high"
}

**Example 3 — genuine grievance, escalate:**

Student: "I've been trying to cancel for two weeks and you keep charging me. This is unacceptable."
You: [call `lookup_order_history(student_id)`] [confirm pattern of charges and prior cancel attempts]
You: [call `escalate_to_human(reason="repeat_charge_after_cancel_attempt", summary="...")`]
Output: {
  "answer": "I'm sorry — I can see the pattern in your account and you're right that this needs immediate human attention, not another automated response. I've escalated to our admin team with reference [ticket_id]. Someone will reach out within 24 hours, and your account is flagged so no new charges will go through while this is being resolved. I'm genuinely sorry for the frustration.",
  "grounded_in": ["3 charges in 14 days after cancel request"],
  "suggested_action": "contact_support",
  "escalation_ticket_id": "[ticket_id]",
  "confidence": "high"
}

# Brand

You are an agent in AICareerOS. When self-referring or referring to the platform, use "AICareerOS." Do not identify as "PAE," "PAE Platform," or "CareerForge" — those are legacy names that students should not encounter going forward. Existing receipts may have `CF-` prefixes; that's fine to reference, but the platform name is AICareerOS.
```

**Migration checklist additions for D10:**

- The four lookup tools need real bodies (Pass 3d will design; D10 ships minimal versions)
- Frontend: `frontend/src/components/features/feedback-widget.tsx` and any "contact billing" surfaces should route through the Supervisor endpoint
- The hardcoded `support@pae.dev` reference in the legacy agent gets replaced with `support@aicareeros.com` (or whatever your final support address is — flag this for confirmation before D10)

---

### E2 — `senior_engineer` (D11, merged from code_review + coding_assistant + senior_engineer)

**Pass 3a verdict:** MERGE three legacy agents (code_review, senior_engineer, coding_assistant) into one. **Confidence:** HIGH.

**Why merge:** all three are doing the same job in different output shapes (rubric vs. PR-style vs. chat). The merge is the clearest finding in the audit.

**`AgentCapability`:**

```python
CAPABILITY = AgentCapability(
    name="senior_engineer",
    version=2,  # version 2 because it's merged from 3 legacy agents
    description=(
        "Reviews student-submitted code with a senior engineer's voice — direct, kind, "
        "no sycophancy. Three modes: 'pr_review' for structured PR-style feedback "
        "(verdict + comments + next step), 'chat_help' for conversational debugging "
        "and code discussion, 'rubric_score' for graded code-review exercises. Reads "
        "the student's prior code submissions and prior reviews to track patterns. "
        "Can hand off to mock_interview when the student is preparing for a coding "
        "interview, or to learning_coach when the student needs concept-level help. "
        "Best for: code review, debugging help, code quality questions, 'is this "
        "approach right'. Requires `code` in context."
    ),
    inputs_required=["code"],
    inputs_optional=["problem_context", "mode", "language", "test_results"],
    outputs_provided=["review", "verdict", "next_step", "handoff_request"],
    typical_latency_ms=10000,
    typical_cost_inr=Decimal("3.50"),
    requires_entitlement=True,  # paid feature
    handoff_targets=["mock_interview", "learning_coach"],
    model_used="claude-sonnet-4-6",
)
```

**Primitive flags:**

```python
uses_memory = True       # tracks recurring patterns in this student's code
uses_tools = True        # static analysis, prior submission lookup
uses_inter_agent = True  # can hand off to mock_interview or learning_coach
uses_self_eval = False   # high-traffic, expensive; turn on later if quality concerns surface
uses_proactive = False
```

**Memory access:**

- **Reads:** `senior_engineer:pattern:*` (recurring code patterns this student uses), `submission:code:*` (prior submissions), `feedback:code_review:*` (prior reviews this student received)
- **Writes:** new patterns observed (`senior_engineer:pattern:{pattern_name}` with valence reflecting whether it's a strength or weakness), the review itself (`feedback:code_review:{date}`)

**Tools needed:**

- `run_static_analysis(code, language)` → ruff, mypy, eslint output
- `run_tests_in_sandbox(code, tests)` → execute tests safely, return results
- `lookup_prior_submissions(student_id, similar_to_code, limit=5)` → semantic search over past submissions
- `lookup_prior_reviews(student_id, limit=10)` → past code reviews this student received
- `dispatch_handoff(target_agent, suggested_context)` → return a HandoffRequest

**Modes:**

| Mode | When | Output shape |
|---|---|---|
| `pr_review` | Student submits code for formal review (default for `/practice/review`, `/senior-review` endpoints) | Verdict + comments + next_step |
| `chat_help` | Student asks for help in conversational form ("why doesn't this work?", "should I use X or Y?") | Conversational explanation + optional code suggestion |
| `rubric_score` | Code is being graded against a course rubric | Score 0-100 + dimension breakdown + structured feedback |

**Output schema:**

```python
class SeniorEngineerOutput(BaseModel):
    mode: Literal["pr_review", "chat_help", "rubric_score"]

    # pr_review fields
    verdict: Literal["approve", "request_changes", "comment"] | None = None
    headline: str | None = None  # ≤ 120 chars
    strengths: list[str] = []  # 0-3 items
    comments: list[CodeComment] = []
    next_step: str | None = None  # ≤ 200 chars

    # chat_help fields
    explanation: str | None = None
    code_suggestion: str | None = None

    # rubric_score fields
    score: int | None = None  # 0-100
    dimension_scores: dict[str, int] = {}  # e.g., {"correctness": 18, "readability": 15}
    rubric_feedback: str | None = None

    # Common
    patterns_observed: list[str] = []  # written to memory
    handoff_request: HandoffRequest | None = None


class CodeComment(BaseModel):
    line: int | None  # null for whole-file comments
    severity: Literal["nit", "suggestion", "concern", "blocking"]
    message: str  # ≤ 240 chars
    suggested_change: str | None = None
```

**Handoff rules:**

- Hand off to `mock_interview` when: student says they're preparing for a coding interview AND the code under review is interview-style (algorithm/data structure problem)
- Hand off to `learning_coach` when: the issue is conceptual rather than code-level (e.g., student wrote correct code but doesn't understand why it works)
- Both are `suggested` handoffs (not mandatory) — the Supervisor decides

**The full new prompt:**

(Full prompt continues in repo file — abbreviated here for length. The implementation deliverable D11 will write the complete prompt file at `backend/app/agents/prompts/senior_engineer.md` following the §A.9 structure. Key elements:

- Three modes clearly distinguished, with examples for each
- "Direct but kind" voice preserved from legacy senior_engineer prompt — that voice is genuinely good
- Severity ladder preserved: `nit` < `suggestion` < `concern` < `blocking`
- Verdict ↔ severity consistency rule preserved: any `blocking` → verdict must be `request_changes`
- Pattern-tracking instructions: when the student repeats a pattern across submissions, mention it explicitly ("I've noticed this is the third submission where you've used a bare `except:` — let's make this the time we fix it")
- Hard constraints: never write code longer than 30 lines in a comment (link to docs instead), never grade harshly without first acknowledging what works, never use the word "obviously"
- Handoff examples: when to suggest mock_interview, when to suggest learning_coach
- Brand section: AICareerOS naming)

The full prompt expansion is mechanical work for D11. The structure above is the contract.

---

### E3 — `career_coach` (D12, career bundle)

**Pass 3a verdict:** REWRITE. **Confidence:** HIGH.

**Why rewrite:** legacy version produces generic 90-day plans because it has no student context. Rewrite produces personalized plans grounded in actual progress and gaps.

**`AgentCapability`:**

```python
CAPABILITY = AgentCapability(
    name="career_coach",
    description=(
        "Builds personalized 90-day career plans for students transitioning into "
        "senior GenAI engineering. Reads the student's mastery state, completed "
        "projects, capstone progress, target role, and goal contract to ground "
        "advice in their actual situation. Coordinates with study_planner (for "
        "weekly tactical plans), resume_reviewer (for portfolio review), and "
        "mock_interview (for readiness checks). Best for: 'what should I focus "
        "on next', 'am I ready to apply for jobs', 'how do I get from where I "
        "am to senior GenAI engineer', career direction questions. Does not "
        "handle: day-to-day study scheduling (study_planner), resume editing "
        "(resume_reviewer), interview practice (mock_interview)."
    ),
    inputs_required=[],  # works from student_id alone
    inputs_optional=["target_role", "specific_question", "timeline_weeks"],
    outputs_provided=["plan", "milestones", "concerns", "handoff_requests"],
    typical_latency_ms=12000,
    typical_cost_inr=Decimal("4.00"),
    requires_entitlement=True,
    handoff_targets=["study_planner", "resume_reviewer", "mock_interview", "portfolio_builder"],
    model_used="claude-sonnet-4-6",
)
```

**Primitive flags:**

```python
uses_memory = True       # remembers career goals + prior coach conversations
uses_tools = True        # reads progress, mastery, capstone, goal_contract
uses_inter_agent = True  # delegates tactical work to other agents
uses_self_eval = False
uses_proactive = False
```

**Memory access:**

- **Reads:** `goal:active`, `pref:target_role`, `pref:career_timeline`, `interaction:career_concern:*`, `mastery:*` (selected), `submission:capstone:*`, `feedback:career_coach:*` (prior coach sessions)
- **Writes:** career plan summaries (`feedback:career_coach:{date}`), milestones agreed (`milestone:{date}`), concerns surfaced (`interaction:career_concern:{date}`)

**Tools needed:**

- `read_student_full_progress(student_id)` → consolidated progress across all courses
- `read_capstone_status(student_id)` → capstone state, score if evaluated
- `read_goal_contract(student_id)` → active goal_contract or None
- `read_mastery_summary(student_id)` → top strengths and weaknesses by mastery
- `read_market_signals(target_role)` → external job market data for the role (from a curated source — Pass 3d may defer this to a later deliverable)
- `dispatch_handoff(target_agent, suggested_context)` → return HandoffRequest

**Output schema:**

```python
class CareerCoachOutput(BaseModel):
    headline: str  # ≤ 200 chars: the one-sentence summary
    current_state_assessment: str  # honest read of where student is
    plan: CareerPlan
    immediate_concerns: list[str] = []  # things that need addressing now
    milestones: list[Milestone]  # 3-6 milestones over the timeline
    suggested_next_action: str  # what to do this week
    handoff_requests: list[HandoffRequest] = []


class CareerPlan(BaseModel):
    timeline_weeks: int
    weekly_focus_areas: list[WeeklyFocus]
    projects_to_complete: list[ProjectRef]
    skills_to_develop: list[str]


class Milestone(BaseModel):
    week: int
    title: str
    description: str
    success_criteria: str
```

**Handoff rules:**

- Hand off to `study_planner` when: the student needs tactical weekly scheduling, not strategic direction
- Hand off to `resume_reviewer` when: career conversation reveals resume should be reviewed (e.g., student is close to applying)
- Hand off to `mock_interview` when: career conversation reveals interview prep is the next step
- Hand off to `portfolio_builder` when: portfolio gaps are identified

These are all `suggested` handoffs. The Supervisor decides whether to chain or let the student request the next step.

**The full new prompt** (structural blueprint — full expansion in D12):

```markdown
# Role

You are the Career Coach in AICareerOS. You help engineers transitioning into senior GenAI engineering build personalized, grounded career plans. You don't give generic advice — every plan is tied to the specific student's progress, gaps, goals, and timeline.

You are not a tactical scheduler (that's study_planner), a resume editor (resume_reviewer), or an interview coach (mock_interview). You set direction; specialists handle execution.

# Memory access

You read:
- The student's active goal contract, target role, and timeline
- Their actual mastery state (strengths and weaknesses)
- Their capstone progress and any prior evaluations
- Past career coaching conversations — recognize when you're following up vs. starting fresh

You write:
- Career plan summaries with milestones
- Concerns or pivots discussed
- Agreed-upon next actions

# Tools

[List of tools per spec above, with usage guidance]

# Output schema

[CareerCoachOutput per spec above]

# Hard constraints

You MUST:
- Ground every recommendation in the student's actual data — no generic "build a portfolio, network, apply broadly" advice
- Be honest about gaps. If the student wants to be ready in 4 weeks but their mastery suggests 16 weeks, say so kindly but clearly
- Suggest concrete next actions, not abstract goals ("complete the RAG capstone by Friday" not "improve your skills")
- Recognize when the student needs a different agent and hand off

You MUST NOT:
- Promise outcomes (job offers, timelines, salaries)
- Compare the student to other students or aggregated data
- Engage in motivational platitudes — be a coach, not a cheerleader
- Schedule the student's day-to-day work (that's study_planner's job)

# Handoff rules

[Per spec above]

# Examples

[3-4 worked examples covering: starting fresh with a new student, follow-up session 4 weeks in, student wanting to apply but not ready, student asking for tactical help (handoff to study_planner)]

# Brand

[AICareerOS naming reminder]
```

---

### E4 — `study_planner` (D12, NEW agent in career bundle)

**Pass 3a verdict:** NEW agent. **Confidence:** HIGH.

**Why new:** the career_coach handles strategic direction; the study_planner handles tactical weekly/daily scheduling. The gap between strategy and execution is exactly where students fall off.

**`AgentCapability`:**

```python
CAPABILITY = AgentCapability(
    name="study_planner",
    description=(
        "Builds tactical weekly and daily study plans. Given a student's available "
        "hours, current course progress, due SRS cards, capstone state, and upcoming "
        "interview goals, produces time-blocked plans for the week and specific plans "
        "for tonight's session. Best for: 'what should I do this week', 'I have 2 "
        "hours tonight, what should I focus on', 'my plan slipped, help me catch up'. "
        "Different from career_coach (strategic 90-day plans) and adaptive_path "
        "(which lessons to take next). Reads goal_contract for hours commitment."
    ),
    inputs_required=[],
    inputs_optional=["available_hours_this_week", "session_duration_minutes", "specific_focus"],
    outputs_provided=["weekly_plan", "session_plan", "adherence_check"],
    typical_latency_ms=6000,
    typical_cost_inr=Decimal("1.50"),
    requires_entitlement=True,
    handoff_targets=["career_coach"],  # for strategic re-planning
    model_used="claude-sonnet-4-6",
)
```

**Primitive flags:**

```python
uses_memory = True
uses_tools = True
uses_inter_agent = True   # may hand off to career_coach if strategic re-plan needed
uses_self_eval = False
uses_proactive = True     # nightly check-ins on plan adherence
```

**Memory access:**

- **Reads:** `goal:active` (weekly hours commitment), `pref:study_session_length`, `pref:peak_focus_time`, `interaction:plan_adherence:*`, `submission:exercise:*` (recent), `mastery:weak_concepts`
- **Writes:** weekly plans (`plan:week:{week_starting}`), session plans (`plan:session:{date}`), adherence outcomes (`interaction:plan_adherence:{date}`)

**Tools needed:**

- `read_goal_contract(student_id)` → weekly hours commitment, target dates
- `read_due_srs_cards(student_id)` → cards due in the next N days
- `read_active_capstone(student_id)` → capstone state and remaining work
- `read_recent_session_history(student_id, days=14)` → what they actually did
- `read_calendar_blocks(student_id)` → if calendar integrated (deferred to Pass 3d)
- `commit_plan(student_id, plan_type, plan_data)` → persist plan for tracking adherence
- `track_adherence(student_id, plan_id, actual_completion)` → record what got done vs. planned

**Modes:**

| Mode | When | Output |
|---|---|---|
| `weekly_plan` | Sunday or beginning-of-week request | Time-blocked plan for the week |
| `session_plan` | "What should I do tonight?" | Specific 30-90 min session plan |
| `adherence_check` | Proactive (nightly Celery) or reactive ("I missed yesterday") | Adherence assessment + suggested adjustment |

**Output schema:**

```python
class StudyPlannerOutput(BaseModel):
    mode: Literal["weekly_plan", "session_plan", "adherence_check"]

    # weekly_plan
    week_starting: date | None = None
    total_hours_planned: float | None = None
    daily_blocks: list[DailyBlock] = []

    # session_plan
    session_date: date | None = None
    session_duration_minutes: int | None = None
    activities: list[SessionActivity] = []
    success_criteria: str | None = None  # how to know it was a good session

    # adherence_check
    adherence_score: float | None = None  # 0-1
    summary: str | None = None
    suggested_adjustment: str | None = None

    handoff_request: HandoffRequest | None = None  # if strategic re-plan needed


class SessionActivity(BaseModel):
    duration_minutes: int
    activity_type: Literal["new_lesson", "practice", "review", "capstone_work", "interview_prep", "rest"]
    specific_target: str  # e.g., "Lesson 4.2 on retrieval augmentation"
    why_now: str  # the reasoning — short
```

**Handoff rules:**

- Hand off to `career_coach` when: the student's situation has changed enough that strategic re-planning is needed (goal abandoned, timeline slipped significantly, target role changed). Mandatory handoff in those cases.

**Proactive trigger:**

```python
@proactive(cron="0 22 * * *")  # 10 PM IST every night
async def nightly_adherence_check(self):
    # For each active student with a goal_contract, run adherence_check mode
    # If adherence is dropping, write to memory and optionally trigger interrupt_agent
    ...
```

**The full new prompt:** (structural blueprint — full expansion in D12)

```markdown
# Role

You are the Study Planner in AICareerOS. You help students turn their goals into concrete, time-blocked plans they can actually execute. You answer questions like "what should I do this week?" and "I have 2 hours tonight, what should I focus on?"

You are tactical, not strategic. The Career Coach sets direction; you make it executable. You are not a cheerleader — you're an honest partner who knows the student's actual time, energy, and progress.

# Memory access

[Per spec above]

# Tools

[Per spec above]

# Output schema

[StudyPlannerOutput per spec above]

# Hard constraints

You MUST:
- Plan from the student's actual available time, not aspirational time
- Match plan complexity to remaining time (a 30-minute session shouldn't include 4 different activities)
- Acknowledge when the student is behind and adjust honestly — don't pretend everything is fine
- Always include success criteria so the student knows what "done" looks like
- Account for energy: don't put the hardest work at the end of a long day if the student's pattern shows lower performance then

You MUST NOT:
- Schedule into time the student doesn't have
- Plan more than 7 days ahead in detail (use weekly cycles)
- Replicate the Career Coach's job (90-day strategic plans)
- Replicate adaptive_path's job (which lessons in what order — that's a separate concern)
- Be aspirational ("you can do anything if you commit!") — be specific

# Handoff rules

[Per spec above]

# Examples

[3-4 worked examples: weekly plan starting Monday, tonight's 90-min session, student missed 3 days in a row, adherence check showing positive momentum]

# Brand

[AICareerOS naming]
```

---

### E5 — `resume_reviewer` (D12, career bundle)

**Pass 3a verdict:** REWRITE. **Confidence:** HIGH.

**`AgentCapability`:**

```python
CAPABILITY = AgentCapability(
    name="resume_reviewer",
    description=(
        "Reviews resumes for engineers transitioning into GenAI roles. Cross-references "
        "resume claims against the student's actual capstones, exercise submissions, and "
        "GitHub activity to flag claims unsupported by evidence and to suggest additions "
        "for accomplishments the student undersold. Best for: 'review my resume', 'is "
        "this resume ready', 'what should I add or remove'. Different from "
        "tailored_resume (which generates JD-tailored versions)."
    ),
    inputs_required=["resume_text"],
    inputs_optional=["target_role", "specific_concerns"],
    outputs_provided=["review", "score", "suggested_changes"],
    typical_latency_ms=8000,
    typical_cost_inr=Decimal("3.00"),
    requires_entitlement=True,
    handoff_targets=["portfolio_builder"],  # if portfolio gaps surface
    model_used="claude-sonnet-4-6",
)
```

**Primitive flags:**

```python
uses_memory = True
uses_tools = True
uses_inter_agent = True   # can hand off to portfolio_builder
uses_self_eval = False
uses_proactive = False
```

**Memory access:**

- **Reads:** `submission:capstone:*`, `submission:exercise:top_rated:*`, `feedback:resume:*` (prior reviews), `pref:target_role`
- **Writes:** review summaries, identified gaps

**Tools:** `read_capstones(student_id)`, `read_top_exercise_submissions(student_id, top_n=10)`, `read_github_activity(student_id)` (deferred to Pass 3d), `dispatch_handoff()`

**Output schema:**

```python
class ResumeReviewerOutput(BaseModel):
    overall_score: int  # 0-100
    headline_assessment: str  # one-sentence overall take
    strengths: list[str]
    issues: list[ResumeIssue]
    unsupported_claims: list[UnsupportedClaim]  # claims not backed by evidence
    underrepresented_accomplishments: list[Accomplishment]  # things to add
    suggested_changes: list[ResumeSuggestion]
    handoff_request: HandoffRequest | None = None


class UnsupportedClaim(BaseModel):
    claim_text: str
    missing_evidence: str
    suggested_action: Literal["remove", "soften", "add_evidence", "verify_with_student"]


class Accomplishment(BaseModel):
    description: str
    evidence_source: str  # which capstone/submission this is from
    suggested_resume_text: str  # how to phrase it
```

**The full prompt:** (per A.9 structure — D12 implementation)

Key elements:
- Honest grounding in student's actual evidence
- Specific suggestions, not generic ("strong action verbs!")
- Cross-reference resume claims against memory bank evidence
- Handoff to portfolio_builder when portfolio is the gap
- Brand: AICareerOS

---

### E6 — `tailored_resume` (D12, career bundle)

**Pass 3a verdict:** KEEP, light rewrite. **Confidence:** MEDIUM.

**`AgentCapability`:**

```python
CAPABILITY = AgentCapability(
    name="tailored_resume",
    description=(
        "Generates a JD-tailored, ATS-safe version of the student's resume for a "
        "specific job description. Reads the student's base resume + capstones + "
        "submissions and rewrites for keyword match and role fit. Best for: "
        "'tailor my resume for this JD'. Different from resume_reviewer (which "
        "critiques rather than generates)."
    ),
    inputs_required=["resume_text", "job_description"],
    inputs_optional=["specific_emphasis"],
    outputs_provided=["tailored_resume", "changes_made", "ats_score"],
    typical_latency_ms=10000,
    typical_cost_inr=Decimal("3.50"),
    requires_entitlement=True,
    handoff_targets=["resume_reviewer"],  # validates output before returning
    model_used="claude-sonnet-4-6",
)
```

**Handoff rule (notable):** after generating, this agent invokes `resume_reviewer` on its own output to validate quality — a self-check via inter-agent. The Supervisor honors this handoff because it's flagged `mandatory`.

**Output schema:**

```python
class TailoredResumeOutput(BaseModel):
    tailored_resume: str  # full text
    changes_made: list[Change]  # what was changed and why
    keyword_alignment_score: float  # 0-1, how well does it match JD keywords
    unsupported_additions: list[str]  # any additions not backed by student evidence (should be empty in good output)
    ats_compatibility_notes: list[str]
```

**The full prompt** strictly forbids inventing experience the student doesn't have. The cross-check via resume_reviewer enforces this.

---

### E7 — `mock_interview` (D13)

**Pass 3a verdict:** KEEP, REWRITE. **Confidence:** HIGH.

**`AgentCapability`:**

```python
CAPABILITY = AgentCapability(
    name="mock_interview",
    description=(
        "Conducts mock interviews across multiple formats: system_design, coding, "
        "behavioral, take_home. Reads the student's prior session history, identified "
        "weaknesses, and target role to calibrate difficulty. Tracks weakness patterns "
        "across sessions. Hands off to senior_engineer when the student fails on a "
        "coding round (for code-level review), or to career_coach when the interview "
        "reveals readiness gaps. Best for: interview practice, readiness assessment. "
        "Sessions are stateful and span multiple turns."
    ),
    inputs_required=["interview_format"],
    inputs_optional=["target_role", "difficulty_level", "specific_topic"],
    outputs_provided=["question", "evaluation", "feedback", "session_summary"],
    typical_latency_ms=8000,
    typical_cost_inr=Decimal("3.00"),  # per turn; full session is multiple turns
    requires_entitlement=True,
    handoff_targets=["senior_engineer", "career_coach"],
    model_used="claude-sonnet-4-6",
)
```

**Primitive flags:**

```python
uses_memory = True       # session memory + cross-session weakness tracking
uses_tools = True
uses_inter_agent = True
uses_self_eval = True    # exception to the default — interview quality matters and is hard to assess otherwise
uses_proactive = False
```

**Memory access:**

- **Reads:** `mock_interview:weakness:*` (cross-session weaknesses), `mock_interview:session:*` (prior sessions), `pref:target_role`
- **Writes:** session results (`mock_interview:session:{session_id}`), weaknesses identified (`mock_interview:weakness:{topic}` with valence reflecting severity)

**Modes are interview formats** — `system_design`, `coding`, `behavioral`, `take_home`. Each has different question generation, evaluation criteria, and session length.

**The full prompt** has separate sub-prompts per format (loaded based on mode parameter). Total prompt is large but cleanly structured.

**Sessions are stateful:** unlike most agents which are stateless per call, mock_interview maintains `session_id` across turns. Session state lives in `agent_memory` with a longer TTL.

---

### E8 — `practice_curator` (D14, NEW)

**Pass 3a verdict:** NEW. **Confidence:** HIGH.

**`AgentCapability`:**

```python
CAPABILITY = AgentCapability(
    name="practice_curator",
    description=(
        "Generates personalized practice exercises matched to the student's current "
        "edge of mastery — coding exercises, debugging challenges, system-design "
        "mini-problems, prompt engineering drills, evaluation rubric exercises. "
        "Different from adaptive_quiz (MCQs) and project_evaluator (capstones). "
        "Best for: 'give me something to practice', 'I want to drill on X concept'. "
        "Reads mastery state and prior exercises completed to avoid repeats."
    ),
    inputs_required=[],
    inputs_optional=["concept_focus", "exercise_type", "difficulty_level"],
    outputs_provided=["exercise", "starter_code", "evaluation_criteria", "hints"],
    typical_latency_ms=8000,
    typical_cost_inr=Decimal("2.50"),
    requires_entitlement=True,
    handoff_targets=["senior_engineer"],  # to evaluate the student's submission
    model_used="claude-sonnet-4-6",
)
```

**Output schema:**

```python
class PracticeCuratorOutput(BaseModel):
    exercise: Exercise
    starter_code: str | None = None
    expected_solution_shape: str  # not the answer, but the shape of a correct solution
    evaluation_criteria: list[str]
    hint_sequence: list[Hint]  # progressive hints, unlocked one at a time
    estimated_time_minutes: int


class Exercise(BaseModel):
    title: str
    concept_tags: list[str]
    difficulty: Literal["easy", "medium", "hard"]
    description: str  # the problem statement
    constraints: list[str]
    test_cases_visible: list[TestCase] = []  # what student sees
    test_cases_hidden: list[TestCase] = []  # used by senior_engineer for evaluation
```

**Full prompt** emphasizes that exercises must be solvable in the estimated time, must target one concept (not a soup of unrelated skills), and must have a clear "done" criterion.

---

### E9 — `project_evaluator` (D14)

**Pass 3a verdict:** KEEP, REWRITE. **Confidence:** HIGH.

**`AgentCapability`:**

```python
CAPABILITY = AgentCapability(
    name="project_evaluator",
    description=(
        "Evaluates capstone projects against published rubrics. Different from "
        "senior_engineer (line-level code review): project_evaluator looks at "
        "architecture, completeness, evidence of learning, demo quality. Reads "
        "the full project context and rubric. Output is a structured evaluation "
        "that becomes a portfolio artifact. Best for: capstone submission grading, "
        "'is my project ready'."
    ),
    inputs_required=["project_submission_id"],
    inputs_optional=["rubric_id", "specific_concerns"],
    outputs_provided=["evaluation", "score", "feedback_narrative"],
    typical_latency_ms=20000,  # large input, careful evaluation
    typical_cost_inr=Decimal("8.00"),
    requires_entitlement=True,
    handoff_targets=["portfolio_builder"],  # converts evaluation into portfolio entry
    model_used="claude-sonnet-4-6",
)
```

**Output schema:** structured evaluation with score, dimension breakdown, narrative feedback, and a `portfolio_entry_draft` field that can be passed to portfolio_builder.

**Full prompt** emphasizes evaluation against the published rubric, not invented criteria. Reads the actual rubric from the course's `course_content` and grades strictly to it.

---

### E10 — `content_ingestion` (D15, with curriculum_mapper merged in)

**Pass 3a verdict:** KEEP, REWRITE. Merge curriculum_mapper. **Confidence:** HIGH.

**`AgentCapability`:**

```python
CAPABILITY = AgentCapability(
    name="content_ingestion",
    description=(
        "Ingests source content (GitHub repos, YouTube videos, free text) into the "
        "AICareerOS knowledge base. Extracts concepts, maps to curriculum, identifies "
        "prerequisites, generates discovery metadata. Triggered by webhooks (GitHub "
        "push) or admin-initiated. Not invoked by students. Output feeds the "
        "curriculum knowledge graph (Pass 3e)."
    ),
    inputs_required=["source_type", "source_reference"],
    inputs_optional=["target_course", "tagging_hints"],
    outputs_provided=["concepts", "curriculum_links", "metadata"],
    typical_latency_ms=30000,  # may include external API calls
    typical_cost_inr=Decimal("5.00"),
    requires_entitlement=False,  # not student-facing
    handoff_targets=[],
    model_used="claude-sonnet-4-6",
)
```

**Primitive flags:**

```python
uses_memory = False      # writes to curriculum graph, not personal memory
uses_tools = True
uses_inter_agent = False
uses_self_eval = True    # quality of ingestion matters; sample with Critic
uses_proactive = True    # webhook-triggered (GitHub) and admin-triggered
```

**Tools needed (Pass 3d will deliver):**

- `fetch_github_repo(url)` — clone, extract files, parse
- `fetch_youtube_transcript(url)` — YouTube Data API + transcript
- `extract_concepts(text)` — LLM-assisted concept extraction
- `link_to_curriculum_graph(concepts, course_id)` — write to knowledge graph
- `generate_discovery_metadata(content)` — tags, descriptions, prerequisites

**Full prompt** emphasizes: ingest faithfully (don't hallucinate concepts the source doesn't cover), tag conservatively (don't link weak associations to curriculum), be honest about uncertainty (concepts that are unclear should be flagged for human review, not invented).

---

### E11 — `progress_report` (D16, paired with interrupt_agent)

**Pass 3a verdict:** KEEP, light rewrite. **Confidence:** HIGH.

**`AgentCapability`:**

```python
CAPABILITY = AgentCapability(
    name="progress_report",
    description=(
        "Generates weekly human-readable progress reports for students. Reads growth "
        "snapshots, completed work, mastery deltas, due SRS cards, recent code "
        "reviews. Output goes to in-app notification + email. Run weekly via Celery; "
        "can also be invoked on-demand for a specific student. Best for: 'how am I "
        "doing this week', or proactive Sunday-morning check-ins."
    ),
    inputs_required=["student_id"],
    inputs_optional=["week_starting", "include_personalized_nudge"],
    outputs_provided=["report_text", "highlights", "concerns"],
    typical_latency_ms=10000,
    typical_cost_inr=Decimal("3.00"),
    requires_entitlement=False,  # available to anyone with active enrollment, but typically scheduled
    handoff_targets=[],
    model_used="claude-sonnet-4-6",
)
```

**Primitive flags:**

```python
uses_memory = True
uses_tools = True
uses_inter_agent = True   # may pull from other agents' memories
uses_self_eval = False
uses_proactive = True     # weekly Celery
```

**Memory access:** reads broadly across agent memories for the week (everything tagged with this student in the past 7 days), writes a `feedback:weekly_report:{week_starting}` entry.

The legacy `weekly_letters` Celery task continues to be the trigger; the migration just replaces what's invoked.

---

### E12 — `portfolio_builder` (D17 cleanup)

**Pass 3a verdict:** REWRITE. **Confidence:** MEDIUM.

**`AgentCapability`:**

```python
CAPABILITY = AgentCapability(
    name="portfolio_builder",
    description=(
        "Generates portfolio entries grounded in real student artifacts: capstones, "
        "top-rated exercise submissions, GitHub repo metadata, course completion "
        "certificates. Output is markdown ready for the student's portfolio site or "
        "GitHub README. Best for: 'build my portfolio entry for X', 'what should I "
        "showcase'."
    ),
    inputs_required=[],
    inputs_optional=["specific_artifact_id", "target_audience"],
    outputs_provided=["portfolio_entries", "showcase_recommendations"],
    typical_latency_ms=8000,
    typical_cost_inr=Decimal("2.50"),
    requires_entitlement=True,
    handoff_targets=[],
    model_used="claude-sonnet-4-6",
)
```

**Full prompt** emphasizes drawing from real evidence only — never fabricating accomplishments. Output is markdown formatted for portfolio sites.

---

### E13 — `mcq_factory` (D17 cleanup)

**Pass 3a verdict:** KEEP, light rewrite. **Confidence:** HIGH.

**`AgentCapability`:**

```python
CAPABILITY = AgentCapability(
    name="mcq_factory",
    description=(
        "Generates N MCQs for a given concept and content. Used by the quiz "
        "pre-generation pipeline (Celery) and on-demand quiz requests. Stateless "
        "content generator — does not personalize. Personalization is the quiz "
        "delivery layer's job (adaptive_quiz)."
    ),
    inputs_required=["content", "concept"],
    inputs_optional=["count", "difficulty"],
    outputs_provided=["mcqs"],
    typical_latency_ms=4000,
    typical_cost_inr=Decimal("0.80"),
    requires_entitlement=False,
    handoff_targets=[],
    model_used="claude-haiku-4-5",
)
```

**Primitive flags:**

```python
uses_memory = False  # exception — pure generator
uses_tools = True    # dedupe against mcq_bank
uses_inter_agent = False
uses_self_eval = False
uses_proactive = False  # invoked by Celery task but not @proactive itself
```

The light rewrite adds: dedupe against existing `mcq_bank` for the same concept, tag generated MCQs with concept IDs from the curriculum graph.

---

### E14 — `adaptive_quiz` (D17 cleanup, if not absorbed by Learning Coach)

**Pass 3a verdict (per Addendum):** Likely absorbed by Learning Coach. If standalone, REWRITE. **Confidence:** MEDIUM.

**Note:** the Pass 3a Addendum signals Learning Coach absorbs `adaptive_quiz`'s functionality as a mode. If after D8 review this absorption holds, E14 is dropped. If `adaptive_quiz` remains standalone, the migration spec is similar to `mcq_factory` but with `uses_memory=True` (reads mastery state to pick concepts at edge of mastery).

**Decision deferred to D17 scope-setting**, which depends on D8's final shape.

---

## Section F — Caller Updates for Retired Agents

Per Pass 3a Addendum, several agents are retired entirely. Their callers need to be migrated, not just their code deleted.

### F.1 `cover_letter` — retired

**Callers:** none found in Pass 1/2 (was a stub).

**Migration action:** delete the agent file, delete the prompt, remove from registry. Frontend `agents-grid.tsx` entry, if it lists cover_letter, should be removed during the naming sweep (Pass 3j).

### F.2 `job_match` — retired

**Callers:** keyword-routed; visible entry in public agents grid at `frontend/src/app/(public)/agents/_agents-grid.tsx:186` with the embarrassing "TODO: Adzuna / LinkedIn integration" description.

**Migration action:**
- Remove the agents-grid entry (the TODO is visible to users)
- Delete the agent file
- Remove from MOA keyword map
- Remove from MOA classifier prompt

### F.3 `peer_matching` — retired

**Callers:** keyword-routed only.

**Migration action:** delete agent file, remove from MOA keyword map and classifier prompt. No frontend surface mentions peer matching directly.

### F.4 `deep_capturer` — retired

**Callers:** unclear; not clearly traced in Pass 1/2.

**Migration action:** delete agent file. If any caller surfaces during deletion, it gets pointed at `progress_report` as the closest substitute.

### F.5 `community_celebrator` — retired

**Callers:** keyword-routed.

**Migration action:** delete agent file. Reactive celebration becomes a tone the Supervisor instructs the dispatched specialist to use; proactive celebration moves to `interrupt_agent` (D16). Both replacements happen as part of those deliverables, not D17 cleanup.

### F.6 `disrupt_prevention` — replaced by `interrupt_agent` (D16)

**Callers:** keyword-routed.

**Migration action:** during D16, the keyword map entries that pointed to `disrupt_prevention` are repointed at the Supervisor (which will route via the new architecture). After D16 ships, the legacy `disrupt_prevention` file is deleted.

### F.7 `knowledge_graph` — replaced by `MemoryStore` (D2 primitive, no agent equivalent)

**Callers:** keyword-routed only.

**Migration action:** delete agent file. The functionality (mastery updates) is now handled by Learning Coach's memory writes + the upcoming `memory_curator` consolidation pattern in Pass 3d.

### F.8 `curriculum_mapper` — merged into `content_ingestion` (D15)

**Callers:** likely background only.

**Migration action:** during D15, content_ingestion absorbs the concept-mapping job. Legacy curriculum_mapper file deleted at end of D15.

### F.9 `student_buddy`, `socratic_tutor`, `adaptive_path`, `spaced_repetition` — absorbed by Learning Coach (D8)

**Status:** already in flight via D8's Learning Coach build. Track 5 confirmed Learning Coach replaces these per its design doc. Once D8 ships and Learning Coach is reachable via the Supervisor (D9), the legacy agent files are deleted in D9 cleanup or D17 cleanup, whichever is convenient.

### F.10 `code_review`, `coding_assistant` — merged into `senior_engineer` (D11)

**Callers:** various practice/review endpoints, MOA keyword routes.

**Migration action:** during D11, senior_engineer migration absorbs both. Callers updated to point at the merged agent. Legacy files deleted at end of D11.

---

## Section G — What This Playbook Earns

When all migrations complete:

**For students:**
- Every agent has memory across sessions
- Agents recognize patterns ("this is the third time you've asked about async handling")
- Coordinated handoffs ("you've been working on this code; let me bring in the mock interview agent for the round")
- Consistent identity (AICareerOS everywhere, no PAE/CareerForge drift)
- Capable specialists, not generic chatbots

**For the operator:**
- Adding a new agent is registering a capability and writing a prompt — the architecture is in place
- Every agent's behavior is auditable via the trace endpoint
- Quality regression is detectable via Critic sampling
- Migration deliverables are mechanical, not architectural
- The system is genuinely production-grade for 1,000 students

**For future contributors:**
- The agent shape is enforced by `AgenticBaseAgent` and the `AgentCapability` registry
- The migration template makes new agents straightforward
- Standard memory key patterns prevent capability drift
- The handoff protocol is explicit, not implicit
- Each agent's specification (E1-E14) is a complete contract

This is the layer that makes "16 specialist agents" become "AICareerOS, the OS that coordinates them."

---

## What's NOT covered by Pass 3c

- **Tool implementations.** Pass 3d designs the actual tool bodies. This pass declares what tools each agent needs.
- **Curriculum knowledge graph.** Pass 3e designs the graph; content_ingestion and learning agents will use it.
- **Entitlement schema per tier.** Pass 3f decides which tier unlocks which agents at which cost ceilings.
- **Output-side safety.** Pass 3g handles PII detection, content moderation, prompt-injection-success markers.
- **Interrupt agent's specific intervention rules.** Pass 3h designs the proactive layer; this pass declares interrupt_agent exists and is in D16.
- **Scale specifics.** Pass 3i covers connection pools, query optimization, cost projections.

Each of those passes builds on this one without invalidating it.
