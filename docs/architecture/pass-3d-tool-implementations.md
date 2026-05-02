---
title: Pass 3d — Tool Implementations
status: Final — implementation contract for tools used across all agents
date: After Pass 3c sign-off, before D10 implementation
authored_by: Architect Claude (Opus 4.7)
purpose: Design the actual tools that agents use. Closes the gap left by D3 (which shipped 11 stubs raising NotImplementedError). Defines tool contracts (input/output schemas, side effects, failure modes), security model, MCP server strategy for external services, and the testing pattern. Each implementation deliverable D10–D17 implements the tools its agents need.
supersedes: nothing
superseded_by: nothing — this is the canonical tool contract
informs: D10 (billing_support tools), D11 (senior_engineer tools incl. code sandbox), D12 (career bundle tools), D13 (mock_interview tools), D14 (practice_curator + project_evaluator tools), D15 (content_ingestion + MCP servers), D16 (interrupt_agent tools), D17 (cleanup tools)
implemented_by: D10 through D17 (each deliverable implements the tools its in-scope agents need)
depends_on: D3 (tool registry primitive), Pass 3c (per-agent tool requirements), AGENTIC_OS.md (D1–D8 foundation)
---

# Pass 3d — Tool Implementations

> Pass 3c declared what tools each agent needs. This pass designs the tools themselves — their contracts, security model, where they live, and how they're built. The 11 D3 stubs become real bodies as their consuming agents migrate. New tools get designed here for implementation in subsequent deliverables.

> Read alongside: Pass 3c (the per-agent tool requirements), AGENTIC_OS.md §3 (the D3 tool registry primitive), Pass 3b §8 (the Supervisor's tool kit).

---

## Section A — The Tool Taxonomy

Tools split into three categories by scope and ownership:

### A.1 Universal tools

Available to every agent that has `uses_tools=True`. Live in `backend/app/agents/tools/universal/`. These are the building blocks every agent assumes are present:

- **Memory operations** — `memory_recall`, `memory_write`, `memory_forget`
- **Logging** — `log_event` (structured event logging beyond the auto-logged action row)
- **Self-introspection** — `read_own_capability` (an agent reads its own AgentCapability — useful in prompts that need to know typical_latency, etc.)

Universal tools are imported and registered automatically when an agent declares `uses_tools=True`. The agent doesn't list them in its capability declaration — they're implicit.

### A.2 Domain tools

Shared within a logical domain. Live in `backend/app/agents/tools/domain/{domain_name}/`. Three domains in scope for v1:

- **Curriculum** — concept queries, prerequisite lookups, lesson references. Used by Learning Coach, career_coach, study_planner, adaptive_quiz, practice_curator, content_ingestion.
- **Student state** — progress, mastery, submissions, goals, risk signals. Used by every personalization-aware agent.
- **Code execution** — sandbox for running student code safely. Used by senior_engineer, project_evaluator, practice_curator, mock_interview (coding rounds).

Domain tools are listed in agent capabilities. An agent imports the domain tools it needs.

### A.3 Agent-specific tools

Exclusive to one agent. Live in `backend/app/agents/tools/agent_specific/{agent_name}/`. Examples:

- `senior_engineer/run_static_analysis` — wraps ruff, mypy, eslint
- `billing_support/lookup_refund_status` — domain-specific to billing
- `mock_interview/generate_question_for_format` — interview-specific
- `content_ingestion/parse_github_repo` — content-specific

Agent-specific tools are listed in the agent's capability declaration and visible only to that agent's invocation context.

### A.4 The MCP servers

External service integrations are NOT tools. They are MCP servers that AICareerOS connects to. Tools may *invoke* MCP server methods, but the integration itself is an MCP server, not a tool file.

Mixed strategy per service:

| Service | Strategy | Rationale |
|---|---|---|
| **GitHub** | Use Anthropic's public MCP server | Mature, maintained, broad coverage. Used by content_ingestion (repo crawling), senior_engineer (read prior submissions if linked) |
| **YouTube** | Build our own | No mature public option. Need transcript + metadata extraction with our parsing rules. Used by content_ingestion |
| **Calendar (Google/Outlook)** | Build our own | Sensitive auth flow + write access. Used by study_planner if/when calendar integration ships |
| **Email** | Build our own | Sending emails to students must go through our notification rules + rate limits + content checks. Existing `outreach_automation` infrastructure stays; MCP is the agent-facing surface |
| **Code sandbox (E2B / Modal / custom)** | Build our own (custom) | Tight control over resource limits, timeouts, network isolation. Used by senior_engineer, project_evaluator, practice_curator |
| **Job boards (Adzuna, etc.)** | Defer | Pass 3a retired job_match. If we ever ship job matching, build our own MCP at that point |
| **Curriculum graph as a service** | Build our own (internal) | Postgres + GraphRAG layer; lives inside our infrastructure but exposed as MCP for clean agent access |

MCP servers live in `backend/app/mcp/{service_name}/`. Each is a small FastAPI subapp speaking the MCP protocol. The agentic OS connects to them as MCP clients.

---

## Section B — Tool Contracts

Every tool follows the D3 contract: pydantic input schema, pydantic output schema, async function, registered via `@tool`. This pass standardizes the contract details.

### B.1 The standard tool signature

```python
from app.agents.primitives.tools import tool
from pydantic import BaseModel, Field
from uuid import UUID

class FooInput(BaseModel):
    student_id: UUID = Field(..., description="The student this query is for")
    query: str = Field(..., max_length=1000, description="What to look up")
    limit: int = Field(default=10, ge=1, le=50, description="Max results")

class FooOutput(BaseModel):
    results: list[FooResult]
    total_available: int  # may exceed limit
    truncated: bool  # True if results were cut off
    timestamp: datetime  # when the query ran

@tool(
    name="foo_lookup",
    description="One sentence describing what this does and when to use it",
    input_schema=FooInput,
    output_schema=FooOutput,
    permissions={"read:student_data"},  # see Section C
    tags={"domain:student_state", "agent_specific:false"},
)
async def foo_lookup(input: FooInput) -> FooOutput:
    """
    Detailed docstring for human readers. Includes:
    - Side effects (reads what tables, writes what tables, calls what services)
    - Failure modes (what exceptions are raised, what the LLM sees on each)
    - Latency expectations
    - Cost (if it makes external calls)
    """
    # implementation
    ...
```

### B.2 Tool descriptions are LLM-facing

The `description` parameter is the LLM's guide to when to call this tool. Same writing rules as Pass 3b's `AgentCapability.description`:

- **Do** state when this tool is the right choice
- **Do** mention what inputs the LLM needs to assemble
- **Don't** describe internal implementation
- **Don't** be aspirational

A good tool description is 1-2 sentences:

> "Looks up the student's recent code submissions semantically related to the current task. Use when reasoning about whether the student has tackled similar problems before."

### B.3 Tool failure modes

Every tool can fail in three ways. Each is handled differently:

**Class 1: Permanent failure (NotImplementedError, ValidationError, TypeError)**

Per the D3 convention, these are NOT retried. The agent sees the exception and must handle it (typically by giving up on that approach and trying something else). The exception bubbles up unchanged.

**Class 2: Transient failure (network blip, DB lock, external service 5xx)**

Handled by D5's `evaluate_with_retry` at the agent level — the agent's full execute() retries, which re-runs the tool call. Tools themselves don't retry internally (avoids hidden duplication).

**Class 3: Authoritative refusal (permission denied, rate limit hit, PII detected in input)**

Tool returns a structured error response, not an exception:

```python
class ToolError(BaseModel):
    error_code: Literal["permission_denied", "rate_limited", "invalid_input", "service_unavailable"]
    user_facing_message: str  # what the agent can show the student if needed
    retry_after_seconds: int | None = None  # for rate_limited
```

Agents distinguish "tool unavailable" from "tool ran and returned an error" — the second case is normal data flow, not a failure.

### B.4 Tool latency expectations

Every tool declares a latency budget. Used by:

- The agent's prompt (tells the LLM "this tool is slow, don't call it speculatively")
- The Supervisor's chain planning (chains involving slow tools may exceed timeout)
- The observability layer (alert when actual latency exceeds budget by >2x)

Standard latency tiers:

- **Fast (< 100ms)** — pure DB reads with indexes, Redis lookups, in-memory operations
- **Medium (100ms - 2s)** — DB reads with joins, single LLM-assisted operations, MCP calls within our network
- **Slow (2s - 30s)** — external API calls (GitHub, YouTube), code execution, multi-step LLM operations
- **Very slow (> 30s)** — content ingestion of full repos, long-running sandbox executions

Tools longer than 30s should be Celery tasks invoked via a "fire and check later" tool, not synchronous tool calls.

### B.5 Tool idempotency

Tools split into:

- **Idempotent reads** — most lookup tools. Safe to retry, safe to call from multiple agents in parallel.
- **Idempotent writes** — `memory_write` (key-based, last-write-wins), `log_event` (with deduplication keys).
- **Non-idempotent writes** — `escalate_to_human` (creates a new ticket), `commit_plan` (creates a new plan record). These need explicit idempotency tokens to prevent duplicate side effects from retries.

Non-idempotent tools take an `idempotency_key` parameter. The tool checks for prior calls with the same key and returns the prior result if found. Pattern same as the webhook idempotency keys from D6.

---

## Section C — Tool Security Model

Tools are the surface where agents touch real systems. Security is enforced in layers.

### C.1 Permissions

Every tool declares the permissions it requires:

```python
@tool(
    ...
    permissions={"read:student_data", "write:agent_memory"},
)
```

Standard permissions:

- `read:student_data` — read tables containing student-identifying information
- `read:cohort_data` — read aggregated cross-student data (no PII)
- `write:agent_memory` — write to agent_memory table
- `write:notifications` — write to notification table
- `write:audit_log` — write to agent_actions / agent_call_chain
- `execute:code_sandbox` — submit code for sandboxed execution
- `external:github` — call GitHub MCP server
- `external:youtube` — call YouTube MCP server
- `external:email` — send transactional email
- `admin:escalation` — write to student_inbox with admin notification

### C.2 Permission grants

Permissions are granted to agents via their `AgenticBaseAgent` declaration:

```python
class CareerCoachAgent(AgenticBaseAgent):
    name = "career_coach"
    permissions: set[str] = {
        "read:student_data",
        "read:cohort_data",
        "write:agent_memory",
    }
```

When an agent invokes a tool, the tool registry checks the agent's permission set against the tool's required permissions. Mismatch → `PermissionDenied` (a permanent failure, not retried).

### C.3 The `actor_id` propagation

Every tool call carries the actor identity from the agent's `AgentContext` (the DISC-57 actor identity from base_agent's log_action). Used for:

- Audit logging (`agent_tool_calls` row already has `actor_id` column from D1)
- Permission decisions on tools that need actor-level checks (e.g., admin-on-behalf-of needs different permissions than student-direct)
- Telemetry and abuse detection

### C.4 PII handling

Tools that handle PII (anything containing student names, emails, phone numbers) follow these rules:

- **Inbound:** if a tool receives PII it doesn't need (e.g., a curriculum lookup somehow gets a student's email), it logs a `pii_leak_detected` event and proceeds with the PII redacted from logs (not from the function call).
- **Outbound:** tools that return PII to the agent's context include a `contains_pii: bool` flag in their output. Agents that pass tool outputs into chained calls to other agents must respect this flag — Pass 3g (safety beyond the critic) details how.

### C.5 Cost-bearing tools

Tools that incur cost (LLM calls, external API calls, sandbox runs) decrement the per-student daily cost budget:

- Each tool call's cost is logged in `agent_tool_calls.cost_inr` (column already exists in D1's schema)
- Before executing a cost-bearing tool, the registry checks remaining budget
- If exhausted: tool returns `ToolError(error_code="rate_limited", retry_after_seconds=...)` rather than running

Per-student daily budget is the same 50 INR ceiling from Pass 3b §6.2.

---

## Section D — Universal Tools (every agent gets these)

### D.1 `memory_recall`

```python
class MemoryRecallInput(BaseModel):
    user_id: UUID | None = None  # None for scope=agent or scope=global
    scope: Literal["user", "agent", "global"]
    agent_name: str | None = None  # filter by agent if specified
    query: str | None = None  # semantic query text; None for key-only lookup
    key_pattern: str | None = None  # e.g., "pref:*" for all preferences
    limit: int = 10
    min_confidence: float = 0.3

class MemoryRecallOutput(BaseModel):
    memories: list[MemoryRow]
    truncated: bool
```

**Status:** D2 already implements MemoryStore.recall(). Pass 3d's contribution is wrapping it as a tool with the standard schema. Implementation: thin wrapper, ~30 lines. Lives at `backend/app/agents/tools/universal/memory_recall.py`.

**Permissions:** `read:student_data` if scope=user; `read:cohort_data` if scope=agent or scope=global.

**Latency:** Fast (10-50ms typical).

### D.2 `memory_write`

```python
class MemoryWriteInput(BaseModel):
    user_id: UUID | None = None
    scope: Literal["user", "agent", "global"]
    agent_name: str
    key: str = Field(..., max_length=200)
    value: dict[str, Any]
    valence: float = Field(0.0, ge=-1.0, le=1.0)
    confidence: float = Field(0.8, ge=0.0, le=1.0)
    expires_at: datetime | None = None  # None = no expiry

class MemoryWriteOutput(BaseModel):
    memory_id: UUID
    was_update: bool  # True if existing key updated, False if new
```

**Status:** D2 wrapper. Same as D.1.

**Permissions:** `write:agent_memory`.

**Latency:** Fast (20-100ms — includes embedding generation).

### D.3 `memory_forget`

```python
class MemoryForgetInput(BaseModel):
    memory_id: UUID | None = None  # forget specific memory
    user_id: UUID | None = None  # OR forget all for user
    key_pattern: str | None = None  # OR forget by key pattern
    confirm: bool = False  # required True for bulk operations

class MemoryForgetOutput(BaseModel):
    forgotten_count: int
```

**Status:** D2 wrapper.

**Permissions:** `write:agent_memory`. The `confirm=True` requirement for bulk operations is a safety check against agents accidentally wiping student memory.

### D.4 `log_event`

```python
class LogEventInput(BaseModel):
    event_name: str = Field(..., regex=r"^[a-z_]+\.[a-z_]+$")  # e.g., "tutor.student_breakthrough"
    properties: dict[str, Any]
    severity: Literal["debug", "info", "warning", "error"] = "info"

class LogEventOutput(BaseModel):
    logged: bool
```

**Permissions:** `write:audit_log`.

**Implementation:** wraps structlog + PostHog. Already-instrumented agent actions don't need this; this is for *additional* events agents want to surface.

### D.5 `read_own_capability`

```python
class ReadOwnCapabilityInput(BaseModel):
    pass  # no args; identity comes from AgentContext

class ReadOwnCapabilityOutput(BaseModel):
    capability: AgentCapability
```

**Permissions:** none.

**Use case:** the Supervisor's prompt tells specialists "you have ~30 seconds to respond" — the specialist reads its own typical_latency_ms from this tool to know its budget.

---

## Section E — Domain Tools

### E.1 Curriculum domain

Lives at `backend/app/agents/tools/domain/curriculum/`. Used by Learning Coach, career_coach, study_planner, content_ingestion, practice_curator.

#### E.1.1 `read_curriculum_concept`

```python
class ReadConceptInput(BaseModel):
    concept_id: str | None = None  # exact lookup
    concept_name: str | None = None  # name-based lookup
    course_id: UUID | None = None  # scope to a course

class ReadConceptOutput(BaseModel):
    concept: ConceptRef
    description: str
    prerequisites: list[ConceptRef]  # what should be known first
    enables: list[ConceptRef]  # what this unlocks
    canonical_resources: list[ResourceRef]  # ingested content tagged to this concept
    common_misconceptions: list[str]
```

**Status:** new tool. Body deferred to Pass 3e (curriculum knowledge graph). For D10–D14, returns minimal data from existing tables (`courses`, `lessons`); Pass 3e enriches with graph data.

**Permissions:** none (curriculum is public knowledge).

**Latency:** Fast (DB lookup) → Medium (after GraphRAG).

#### E.1.2 `find_concepts_at_mastery_edge`

```python
class FindEdgeConceptsInput(BaseModel):
    student_id: UUID
    edge_definition: Literal["weak", "borderline", "review_due"] = "borderline"
    limit: int = 5

class FindEdgeConceptsOutput(BaseModel):
    concepts: list[EdgeConcept]


class EdgeConcept(BaseModel):
    concept: ConceptRef
    current_mastery: float  # 0-1
    last_assessed: datetime
    why_at_edge: str  # human-readable reason
```

**Status:** new tool. Reads `user_skill_states` + `srs_cards`. Implementation in D10 (when first needed) or D14 (practice_curator).

**Permissions:** `read:student_data`.

**Latency:** Medium.

#### E.1.3 `query_curriculum_graph`

```python
class QueryGraphInput(BaseModel):
    query: str  # natural language: "what comes after RAG fundamentals"
    starting_concept: str | None = None
    max_hops: int = Field(default=3, ge=1, le=5)

class QueryGraphOutput(BaseModel):
    answer: str  # graph-augmented response
    relevant_concepts: list[ConceptRef]
    relationship_paths: list[RelationshipPath]  # how concepts relate
```

**Status:** **deferred to Pass 3e + D15.** This is the GraphRAG entry point. Until Pass 3e ships, the tool returns a structured "not yet available" response with `error_code="service_unavailable"`.

### E.2 Student state domain

Lives at `backend/app/agents/tools/domain/student_state/`. Used by every personalization-aware agent.

#### E.2.1 `read_student_full_progress`

```python
class ReadProgressInput(BaseModel):
    student_id: UUID
    course_id: UUID | None = None  # None = all enrolled courses

class ReadProgressOutput(BaseModel):
    courses: list[CourseProgress]
    weeks_active: int
    total_hours_logged: float
    last_session: datetime | None


class CourseProgress(BaseModel):
    course: CourseRef
    completion_pct: float
    lessons_completed: int
    lessons_total: int
    current_lesson: LessonRef | None
    capstone_status: CapstoneStatus | None
```

**Status:** new tool aggregating existing tables (`courses`, `lessons`, `student_progress`, `growth_snapshots`). Implementation in D12 (career bundle) or earlier.

**Permissions:** `read:student_data`.

**Latency:** Medium (multi-table join).

#### E.2.2 `read_capstone_status`

Returns capstone state for a student, including any prior `project_evaluator` evaluations. Permissions: `read:student_data`. Latency: Fast.

#### E.2.3 `read_goal_contract`

Returns the active goal_contract row for a student. Permissions: `read:student_data`. Latency: Fast.

#### E.2.4 `read_mastery_summary`

Returns top-N strengths and bottom-N weaknesses by mastery score. Permissions: `read:student_data`. Latency: Fast.

#### E.2.5 `read_recent_session_history`

```python
class ReadSessionHistoryInput(BaseModel):
    student_id: UUID
    days_back: int = Field(default=14, ge=1, le=90)
    include_failed: bool = False

class ReadSessionHistoryOutput(BaseModel):
    sessions: list[SessionRecord]
    daily_summary: dict[date, DailySummary]
```

**Status:** new tool reading `learning_sessions` + recent `agent_actions`. Implementation in D12.

**Permissions:** `read:student_data`.

#### E.2.6 `read_due_srs_cards`

Returns SRS cards due in the next N days. Wraps the existing `srs_service`. Implementation already largely exists; tool is a thin wrapper. Permissions: `read:student_data`.

#### E.2.7 `read_student_risk_signals`

```python
class ReadRiskSignalsInput(BaseModel):
    student_id: UUID

class ReadRiskSignalsOutput(BaseModel):
    risk_state: Literal["healthy", "at_risk", "critical"] | None
    signals: list[RiskSignal]
    last_computed: datetime
```

**Status:** new tool reading `student_risk_signals` (the table risk-scoring-nightly writes to). Implementation in D16 (interrupt_agent's primary tool).

**Permissions:** `read:student_data`.

**Critical use:** this is the tool that closes the loop Pass 2 found broken — it lets agents read what risk-scoring computes.

### E.3 Code execution domain

Lives at `backend/app/agents/tools/domain/code_execution/`. Used by senior_engineer, project_evaluator, practice_curator, mock_interview.

#### E.3.1 `run_static_analysis`

```python
class StaticAnalysisInput(BaseModel):
    code: str = Field(..., max_length=50_000)
    language: Literal["python", "typescript", "javascript"]
    rules: Literal["strict", "default", "lenient"] = "default"

class StaticAnalysisOutput(BaseModel):
    issues: list[StaticIssue]
    summary: str
    runner_used: str  # e.g., "ruff 0.15"


class StaticIssue(BaseModel):
    line: int
    column: int | None
    severity: Literal["error", "warning", "info"]
    rule: str
    message: str
```

**Status:** D11 implements (senior_engineer's primary tool). Wraps subprocess calls to ruff (Python) and eslint (TS/JS).

**Permissions:** none.

**Latency:** Medium (1-3s for ruff on a typical submission).

#### E.3.2 `run_in_sandbox`

```python
class RunInSandboxInput(BaseModel):
    code: str = Field(..., max_length=100_000)
    language: Literal["python", "node"]
    test_inputs: list[str] = []  # stdin per test
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    memory_limit_mb: int = Field(default=256, ge=64, le=1024)
    network_access: bool = False  # default deny

class RunInSandboxOutput(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    memory_used_mb: int
    timed_out: bool
    truncated: bool  # output truncated due to size
```

**Status:** **major piece of new infrastructure.** D11 implements (needed for senior_engineer's "did the test pass?" judgment). Architectural choice for the sandbox itself:

**Sandbox implementation options:**

- **E2B (e2b.dev)** — managed code interpreter sandboxes, hosted, pay-per-execution
- **Modal Labs** — serverless containers, more general purpose
- **Custom Docker-based** — full control, requires building isolation/timeout/resource-limit infra ourselves

**Recommendation:** start with E2B for v1 (lowest engineering burden, fast to ship). Switch to custom Docker-based if/when usage volume makes E2B costs unfavorable. Migration is straightforward because the sandbox is wrapped by this tool — the tool's contract doesn't change.

**Permissions:** `execute:code_sandbox`.

**Cost:** charged per-execution to the student's daily budget.

**Security notes:** network_access=False by default. Agents may not flip this without explicit student-initiated request (e.g., "test my API client against this mock endpoint" — even then, it goes to a whitelisted mock, not arbitrary URLs). Sandbox runs are per-call ephemeral — no state persists.

**Latency:** Slow (3-15s).

#### E.3.3 `run_tests`

```python
class RunTestsInput(BaseModel):
    code: str
    test_code: str
    language: Literal["python", "node"]
    framework: Literal["pytest", "unittest", "jest", "vitest"]
    timeout_seconds: int = 30

class RunTestsOutput(BaseModel):
    passed: int
    failed: int
    errors: int
    test_results: list[TestResult]
    output: str
```

**Status:** D11 implements. Builds on `run_in_sandbox` with framework-specific test runners.

**Permissions:** `execute:code_sandbox`.

---

## Section F — Agent-Specific Tools

For each agent, the tools that only it uses. Implementation deliverable noted.

### F.1 `billing_support` tools (D10)

#### `lookup_order_history`

Reads the student's orders from the v2 payments tables. Returns orders most-recent-first. Permissions: `read:student_data`. Latency: Fast.

#### `lookup_active_entitlements`

Reads `course_entitlements` filtered to active. Permissions: `read:student_data`. Latency: Fast.

#### `lookup_refund_status`

Reads `refunds` and `payment_attempts` for a specific order or all of a student's. Permissions: `read:student_data`. Latency: Fast.

#### `escalate_to_human`

Writes a student_inbox row tagged for admin review with a structured summary. Permissions: `admin:escalation`. Latency: Fast.

### F.2 `senior_engineer` tools (D11)

#### `lookup_prior_submissions`

Semantic search over the student's past code submissions. Uses agent_memory's vector index on `submission:code:*` keys. Returns the N most semantically similar prior submissions. Permissions: `read:student_data`. Latency: Medium.

#### `lookup_prior_reviews`

Reads `feedback:code_review:*` from agent_memory for this student. Returns past reviews with their verdicts and key comments. Permissions: `read:student_data`. Latency: Fast.

(Plus the code execution domain tools — `run_static_analysis`, `run_in_sandbox`, `run_tests`.)

### F.3 Career bundle tools (D12)

career_coach, study_planner, resume_reviewer, tailored_resume share most tools from the student state domain plus:

#### `read_market_signals` (career_coach)

Returns external job market data for a target role. **Status: deferred.** Requires committing to a job-market data source (LinkedIn requires partnership; alternatives include Lightcast, Burning Glass, scraping). For v1, returns a static "data not available" response and the agent falls back to its general knowledge.

#### `commit_plan` (study_planner)

```python
class CommitPlanInput(BaseModel):
    student_id: UUID
    plan_type: Literal["weekly", "session"]
    plan_data: dict[str, Any]
    idempotency_key: str

class CommitPlanOutput(BaseModel):
    plan_id: UUID
    was_new: bool  # False if idempotency_key matched existing plan
```

Persists a plan to a new `study_plans` table for adherence tracking. Permissions: `write:agent_memory` (semantically; technically writes to study_plans which gets added in D12's migration).

#### `track_adherence` (study_planner)

Records plan completion vs. plan as written. Used by both reactive ("I did X") and proactive (nightly check) flows. Permissions: `write:agent_memory`.

### F.4 `mock_interview` tools (D13)

#### `generate_question_for_format`

Returns an interview question appropriate to format (system_design / coding / behavioral / take_home), difficulty level, and student's prior weaknesses. Note: for some formats, this tool wraps an LLM call; for behavioral, it pulls from a curated bank. Permissions: `read:cohort_data`.

#### `evaluate_response`

Format-specific evaluation. For coding rounds, may invoke `run_in_sandbox`. For system_design, evaluates against rubric. Permissions: vary by sub-mode.

#### `lookup_interview_history`

Reads past mock_interview sessions for this student. Permissions: `read:student_data`.

### F.5 `practice_curator` tools (D14)

#### `generate_exercise`

Creates a personalized exercise from a concept + difficulty. Wraps an LLM call with structured output. Permissions: none directly (LLM call).

#### `validate_exercise_solvability`

Checks that the generated exercise is actually solvable (sandbox-runs a reference solution if provided). Permissions: `execute:code_sandbox`.

### F.6 `project_evaluator` tools (D14)

#### `read_full_capstone`

Reads the full capstone submission including code, README, demo links. Permissions: `read:student_data`.

#### `read_published_rubric`

Reads the course's published capstone rubric. Permissions: `read:cohort_data`.

(Plus code execution domain tools.)

### F.7 `content_ingestion` tools (D15)

#### `parse_github_repo`

Calls the **GitHub MCP server** (Anthropic's public one). Returns parsed file tree, key files, README, language breakdown. Permissions: `external:github`.

#### `parse_youtube_content`

Calls our **own YouTube MCP server**. Returns transcript, metadata, thumbnail. Permissions: `external:youtube`.

#### `extract_concepts`

LLM-assisted concept extraction from raw content. Permissions: none (LLM call).

#### `link_to_curriculum_graph`

Writes extracted concepts and relationships to the curriculum graph. Permissions: `write:audit_log` + cohort-level write (a new permission added when GraphRAG ships).

### F.8 `interrupt_agent` tools (D16)

#### `read_student_full_context`

Aggregator tool: returns risk signals + recent activity + memory bank summary in one call. Used to inform intervention decisions. Permissions: `read:student_data`.

#### `check_recent_outreach`

Reads `outreach_log` (existing) to see if the student has been contacted recently. Returns timestamps and channels. Permissions: `read:student_data`.

#### `compose_dm`

Writes to `student_inbox` as in-app DM. Permissions: `write:notifications`.

#### `compose_email`

Calls our **own Email MCP server** to send transactional email. Permissions: `external:email`.

#### `schedule_followup`

Writes a row to a new `scheduled_outreach` table (added in D16) for future Celery dispatch. Permissions: `write:notifications`.

---

## Section G — MCP Servers

External service integrations, with the mixed strategy from the prompt question.

### G.1 GitHub MCP server — use Anthropic's public

**Connection:** `https://api.githubcopilot.com/mcp/` (or whichever URL the production GitHub MCP server is at — the implementation deliverable confirms the current canonical URL).

**Auth:** OAuth flow at platform setup time. Token stored encrypted in our config.

**Methods used:**
- `get_repository(owner, repo)` — metadata
- `list_files(owner, repo, path)` — file tree
- `get_file_contents(owner, repo, path)` — single file
- `search_code(query, repo)` — search within a repo

**Used by:** content_ingestion (D15), senior_engineer (when the student has a GitHub link to their work).

**Status:** **D15 wires it.** Tool body in `parse_github_repo` is the MCP client call.

### G.2 YouTube MCP server — build our own

**Lives at:** `backend/app/mcp/youtube/`

**Why our own:** no mature public option for YouTube's Data API + transcript extraction with our parsing rules.

**Methods exposed:**
- `get_video_metadata(video_id)` — title, description, channel, duration, upload date
- `get_transcript(video_id, language="en")` — transcript with timestamps
- `search_videos(query, max_results)` — search YouTube catalog
- `get_channel_videos(channel_id, max_results)` — list channel uploads

**Auth:** Google API key stored in config. Rate-limited per Google's quotas.

**Status:** **D15 builds.** Likely 200-400 lines of FastAPI subapp + MCP protocol adapter.

### G.3 Calendar MCP server — build our own (deferred)

**Lives at:** `backend/app/mcp/calendar/` (when built).

**Why our own:** sensitive auth (OAuth into Google/Outlook), write access (creating calendar events), needs our own permission gating.

**Status:** **deferred until study_planner integrates with calendars.** Not in v1 scope. study_planner v1 works without calendar integration; the integration is a v2 enhancement.

### G.4 Email MCP server — build our own

**Lives at:** `backend/app/mcp/email/`

**Why our own:** all student-facing emails go through our existing `outreach_automation` infrastructure (existing rate limits, content checks, unsubscribe handling). The MCP server is an agent-facing wrapper around that infrastructure.

**Methods exposed:**
- `send_transactional(to, template_name, template_vars, dedup_key)` — send templated email
- `send_in_app_dm(to, body, dedup_key)` — write to student_inbox (overlap with `compose_dm` tool — this is the underlying primitive)

**Auth:** internal service token; not exposed to non-AICareerOS clients.

**Status:** **D16 builds** when interrupt_agent ships.

### G.5 Code sandbox — custom built (or E2B-wrapped)

**Lives at:** `backend/app/sandbox/` (if custom) or `backend/app/mcp/sandbox/` (thin wrapper if E2B).

**Strategy decision deferred to D11:** start with E2B for speed, switch to custom if cost or control reasons emerge. The `run_in_sandbox` tool's contract is stable across the choice.

**Status:** **D11 builds the wrapper, makes the E2B-vs-custom call.**

### G.6 Curriculum graph as MCP — build our own (internal)

**Lives at:** `backend/app/mcp/curriculum_graph/`

**Why MCP:** even though it's internal infrastructure, exposing the curriculum graph via MCP gives us a clean contract for agents to query it. Switching from naive Postgres queries to GraphRAG-augmented queries (Pass 3e) becomes a server-side change with no agent code changes.

**Methods exposed:**
- `query_natural_language(query, starting_concept?)` — GraphRAG-augmented response
- `get_concept(concept_id)` — exact lookup
- `find_path(from_concept, to_concept)` — prerequisite path
- `find_neighbors(concept_id, hops)` — graph traversal

**Status:** **deferred to Pass 3e + D15.** Until Pass 3e ships, agents query existing tables directly via the curriculum domain tools (E.1).

---

## Section H — The Tool Testing Pattern

Every tool ships with unit tests. Pattern established by D3.

### H.1 Test categories

**Schema tests** — input/output schemas accept valid data, reject invalid. Run on every commit.

**Body tests with mocked dependencies** — tool body runs against mocked DB / mocked HTTP / mocked sandbox. Verifies logic without external dependencies. Run on every commit.

**Integration tests with real dependencies** — tool runs against a real test Postgres / real test sandbox / real MCP server (in test mode). Run nightly or on-demand. Skipped in fast CI loops.

### H.2 Standard test scaffolding

```python
# backend/tests/test_agents/test_tools/test_foo_lookup.py

import pytest
from app.agents.tools.domain.student_state.foo_lookup import foo_lookup, FooInput

@pytest.mark.asyncio
async def test_foo_lookup_happy_path(pg_session_with_seed):
    input = FooInput(student_id=SEED_STUDENT_ID, query="...", limit=5)
    output = await foo_lookup(input)
    assert len(output.results) <= 5
    assert output.truncated == (output.total_available > 5)

@pytest.mark.asyncio
async def test_foo_lookup_empty_result(pg_session):
    input = FooInput(student_id=NONEXISTENT_STUDENT_ID, query="...", limit=5)
    output = await foo_lookup(input)
    assert output.results == []
    assert output.total_available == 0

@pytest.mark.asyncio
async def test_foo_lookup_invalid_input():
    with pytest.raises(ValidationError):
        FooInput(student_id="not-a-uuid", query="x", limit=-1)

@pytest.mark.asyncio
async def test_foo_lookup_permission_denied(pg_session, agent_without_permission):
    input = FooInput(...)
    with pytest.raises(PermissionDenied):
        await foo_lookup(input)
```

### H.3 MCP server testing

For tools that call MCP servers, integration tests use a dedicated test mode of the MCP server (or VCR-style cassettes for replay). The MCP server's own unit tests are separate.

For external public MCP servers (GitHub), we don't have control over test mode — we use VCR cassettes recorded against the real server, refreshed periodically.

---

## Section I — Implementation Sequencing

Tools get built as their consuming agents migrate. Per Pass 3c sequencing:

| Deliverable | Tools built |
|---|---|
| **D10** (billing_support) | `lookup_order_history`, `lookup_active_entitlements`, `lookup_refund_status`, `escalate_to_human`. Plus the universal tools (`memory_recall`, `memory_write`, `memory_forget`, `log_event`, `read_own_capability`) since this is the first migration. |
| **D11** (senior_engineer) | `run_static_analysis`, `run_in_sandbox` (incl. sandbox infrastructure decision), `run_tests`, `lookup_prior_submissions`, `lookup_prior_reviews` |
| **D12** (career bundle) | `read_student_full_progress`, `read_capstone_status`, `read_goal_contract`, `read_mastery_summary`, `read_recent_session_history`, `commit_plan`, `track_adherence`. Career-coach-specific tools (deferred or stubbed). |
| **D13** (mock_interview) | `generate_question_for_format`, `evaluate_response`, `lookup_interview_history` |
| **D14** (practice_curator + project_evaluator) | `find_concepts_at_mastery_edge`, `read_due_srs_cards`, `generate_exercise`, `validate_exercise_solvability`, `read_full_capstone`, `read_published_rubric` |
| **D15** (content_ingestion + curriculum graph) | `parse_github_repo`, `parse_youtube_content`, `extract_concepts`, `link_to_curriculum_graph`, `query_curriculum_graph`. **YouTube MCP server built.** GitHub MCP server connection wired. |
| **D16** (interrupt_agent + progress_report) | `read_student_risk_signals`, `read_student_full_context`, `check_recent_outreach`, `compose_dm`, `compose_email`, `schedule_followup`. **Email MCP server built.** |
| **D17** (cleanup) | Any residual tools for portfolio_builder, mcq_factory cleanup. Deletion of tool stubs from D3 that were never used. |

---

## Section J — What's Deferred

Things this pass declares as out of scope, with explicit pointers:

- **Curriculum knowledge graph implementation** → Pass 3e + D15. The `query_curriculum_graph` tool exists in this pass as a contract; the body and the graph itself ship in Pass 3e/D15.
- **Job board integration** → on hold until you commit to a data source. Pass 3a retired job_match; if it returns, the tool design lives there.
- **Calendar MCP server** → deferred to a study_planner v2 enhancement.
- **Cost-bearing tool implementations** → the cost-tracking column already exists in `agent_tool_calls` (D1). Implementations log cost; the per-student-budget enforcement is a Pass 3i (scale + observability) concern.
- **PII redaction in tool outputs** → Pass 3g (safety beyond critic) handles output-side PII.

---

## Section K — What This Pass Earns

When all tools are implemented (D10 through D17 complete):

**For students:**
- Agents have actual capabilities, not LLM hallucinations dressed as actions
- Code review backed by real static analysis and test execution
- Career advice grounded in real progress data
- Memory operations that actually persist
- Email/DM communication that respects rate limits and content rules

**For the operator:**
- Every tool call is logged with cost, latency, and outcome
- Permission system makes "what can this agent do" enumerable
- Tool failures degrade gracefully (structured errors, not bare exceptions)
- External dependencies are bounded (MCP servers as the surface)

**For future contributors:**
- Adding a new tool is `@tool(schema, permissions, ...)` plus a function body
- Adding a new MCP server is a contained subapp at `backend/app/mcp/{name}/`
- The tool taxonomy (universal / domain / agent-specific) makes scope obvious
- Testing pattern is standardized

This is the layer that makes agents *capable*, not just *eloquent*.

---

## README.md update (paste this into docs/architecture/README.md)

The README should be updated to reflect Pass 3c and Pass 3d completion. Current content should be replaced with:

```markdown
# Architecture Decision Documents

This directory contains the architectural decision history for AICareerOS. Documents are numbered as "Pass" deliverables — each one a discrete decision point that builds on the previous.

## Reading order

1. **`docs/audits/pass-1-ground-truth.md`** — Structural snapshot of the codebase as of the audit. Observations only.
2. **`docs/audits/pass-2-hypothesis-verification.md`** — Five hypotheses about whether the codebase implements an "OS of learning." Code-level evidence.
3. **`pass-3a-agent-inventory.md`** — Original 24-agent roster. ⚠️ Superseded by the addendum but preserved for decision history.
4. **`pass-3a-addendum-after-d8.md`** — Corrected 16-agent roster after D1–D8 reconciliation. **Canonical agent contract.**
5. **`pass-3b-supervisor-design.md`** — The Supervisor agent: data contract, decision logic, dispatch layer, policy enforcement. **Canonical orchestration design.**
6. **`pass-3c-agent-migration-playbook.md`** — Per-agent migration recipes for the 14 surviving legacy agents. **Implementation contract for D10–D17.**
7. **`pass-3d-tool-implementations.md`** — Tool contracts (universal, domain, agent-specific), MCP server strategy, security model, testing pattern. **Implementation contract for tools.**
8. **`pass-3e-...` through `pass-3l-...`** — Subsequent architecture passes (forthcoming).

## Status reference

| Pass | Status | Document |
|---|---|---|
| Pass 1 | Final | `../audits/pass-1-ground-truth.md` |
| Pass 2 | Final | `../audits/pass-2-hypothesis-verification.md` |
| Pass 3a | Superseded | `pass-3a-agent-inventory.md` |
| Pass 3a Addendum | **Final — canonical** | `pass-3a-addendum-after-d8.md` |
| Pass 3b | **Final** | `pass-3b-supervisor-design.md` |
| Pass 3c | **Final** | `pass-3c-agent-migration-playbook.md` |
| Pass 3d | **Final** | `pass-3d-tool-implementations.md` |
| Pass 3e | In progress (next) | (drafting — curriculum knowledge graph + GraphRAG) |
| Pass 3f–3l | Not started | — |

## Implementation deliverables

The architecture passes drive a sequence of implementation deliverables:

- **D9** — Supervisor + canonical agentic endpoint + entitlement gating + PG-1 fix (drives from Pass 3b + 3a Addendum)
- **D10** — billing_support migration (drives from Pass 3c E1 + Pass 3d Section D + F.1)
- **D11** — senior_engineer migration + code sandbox infrastructure (drives from Pass 3c E2 + Pass 3d Section E.3 + F.2)
- **D12** — career bundle (career_coach, study_planner NEW, resume_reviewer, tailored_resume) (drives from Pass 3c E3-E6 + Pass 3d Section E.2 + F.3)
- **D13** — mock_interview migration (drives from Pass 3c E7 + Pass 3d Section F.4)
- **D14** — practice_curator NEW + project_evaluator (drives from Pass 3c E8-E9 + Pass 3d Section F.5-F.6)
- **D15** — content_ingestion + curriculum graph + MCP servers (drives from Pass 3c E10 + Pass 3d Section F.7 + Section G + Pass 3e)
- **D16** — interrupt_agent NEW + progress_report (drives from Pass 3c E11 + Pass 3d Section F.8 + Pass 3h)
- **D17** — final cleanup, residual migrations (drives from Pass 3c E12-E14 + Pass 3j)

## Companion documents

- `../AGENTIC_OS.md` — Architecture document for the agentic OS layer (D1–D8 foundation). Backwards-looking; describes what's built.
- `../audits/track-6-baseline.md` — Verification baseline at end of parallel cleanup workstream.
- `../followups/` — Open and resolved follow-ups, including known bugs (e.g., `agentic-loader-fastapi-startup.md` — P0).

## How to use this directory

When making a future architectural decision:
1. Draft as `pass-NN-{short-name}.md` with frontmatter (status, supersedes, superseded_by).
2. Update this README's reading order, status table, and implementation deliverables list.
3. Cross-link from any pass that builds on the new decision.
4. Mark superseded passes clearly at the top — never delete; preserve the decision trail.
```

When you can update the README, paste the block above into `docs/architecture/README.md`. It supersedes the prior content. Until then, the content above is the canonical reading order — it just isn't in the file yet.
