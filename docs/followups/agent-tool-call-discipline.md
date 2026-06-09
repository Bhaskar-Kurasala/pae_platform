# Agent → tool call discipline — patterns from CP3 pre-flight bug catches

**Status:** Open — D17 cleanup territory. Two patterns documented here,
both surfaced during D12 CP3 pre-flight verification (2026-05-06).
**Cross-references:**
[asyncpg-rollback-discipline.md](./asyncpg-rollback-discipline.md) (sibling
meta-pattern doc; covers transaction-state hygiene),
[tests/test_agents/test_study_planner_v2_tool_calls.py](../../backend/tests/test_agents/test_study_planner_v2_tool_calls.py)
(the regression pin for both bugs).

## Pattern 1: Broad-except hides tool-call signature mismatches

### Instance: `study_planner_v2._log_mode_inference` (D12 CP3 Part F.1)

The agent called `log_event` with parameter names that don't exist on
`LogEventInput`:

```python
# WRONG — caught by D12 CP3 pre-flight
await executor.call(
    "log_event",
    {
        "event_type": "mode_inferred",     # ← not a LogEventInput field
        "agent": "study_planner",          # ← not a LogEventInput field
        "payload": {...},                  # ← not a LogEventInput field
    },
)
```

`LogEventInput` declares `model_config = ConfigDict(extra="forbid")` and
accepts only `event_name`, `properties`, `severity`. Pydantic raised
`ValidationError`. The `except Exception` in `_log_mode_inference`
swallowed it and logged at `debug` level only.

**Net effect:** The mode_inferred telemetry the prompt promised silently
never fired. The agent appeared to work end-to-end. Observability was
broken in a way that wouldn't surface until D17 dashboards tried to query
the data and got empty results.

### Why this is subtle

Broad-except wrappers around tool calls are reasonable for *operational*
errors — network blips, transient DB unavailability, asyncpg state
recovery. They are NOT reasonable for *programming* errors — signature
mismatches, type errors, missing required fields. These should fail loudly
during development, not be swallowed as if they were transient.

The CP2 stub-LLM smoke didn't catch the bug because the smoke verified
"Supervisor routes here" and "the prompt loads," not "tool calls succeed."
The bug was dormant under happy-path testing.

### Mitigation options (D17 triage)

1. **Differentiate exception types**: re-raise `pydantic.ValidationError`,
   `AttributeError`, `TypeError`; catch only operational exceptions
   (`asyncio.TimeoutError`, `ConnectionError`, asyncpg-specific errors).
   Programming errors should fail tests, not log silently.
2. **Severity escalation**: when the broad except catches a
   development-time exception class, log at `error` (not `debug`) so the
   signal isn't lost in routine debug noise.
3. **CI gate**: scan agent modules for `except Exception` immediately
   wrapping `executor.call(...)` and warn during code review. Pair with a
   convention: tool calls that may legitimately fail (e.g., DB-backed
   reads where the row may not exist) belong inside the tool's own
   fail-soft path, not the agent's.

### Triage

D17 cleanup. The fix lives at the meta-level (exception hygiene
convention). For D12 the local fix landed (CP3 Part F.1) plus a unit
test pinning the corrected shape so future signature drift fails CI.

---

## Pattern 2: Stub-LLM smoke doesn't exercise post-LLM dispatch

### Instance: `study_planner_v2._commit_plan` (D12 CP3 Part F.2)

The agent passed `output.mode` (one of `weekly_plan`, `session_plan`,
`adherence_check`) to the `commit_plan` tool whose `plan_type` Literal
accepts only `weekly` | `session`:

```python
# WRONG — caught by D12 CP3 pre-flight
plan_type = output.mode  # "weekly_plan", "session_plan", "adherence_check"
await executor.call("commit_plan", {"plan_type": plan_type, ...})
```

Pydantic Literal validation rejected all three values. `_commit_plan`'s
caller — the agent's `run()` — does NOT wrap this call in a broad except
(write paths are documented as "raise on failure"). The result: every
study_planner run that reached the commit step crashed with
`ValidationError`. The bug was a 100% reproducible run-killer, dormant
only because no test had triggered it.

### Why CP2 stub-LLM smoke missed it

The CP2 smoke fed the agent a stub LLM whose response did NOT round-trip
through `_parse_output(...)` to produce a real `StudyPlannerOutput`. The
smoke verified:

- Supervisor routed to `study_planner` ✓
- Prompt loaded ✓
- LLM call shape (system + user message structure) ✓

The smoke did NOT verify:

- `_parse_output` correctly produces a `StudyPlannerOutput` from the
  stubbed response shape
- The output's `mode` field flowed cleanly into `_commit_plan`
- `_commit_plan` successfully invoked the `commit_plan` tool

CP2's smoke stopped at the LLM boundary. The bugs lived past it.

### Discipline (D13+)

For agents with non-trivial post-LLM dispatch — multi-mode outputs, write
tools, downstream cascades — CP2 stub-LLM smoke must include stub
responses that exercise each post-LLM path. Concrete shape:

- **Multi-mode agents**: stub at least one response per mode that hits
  every mode-specific branch in the agent's `run()`.
- **Write-tool callers**: confirm the stub response unmarshals to the
  expected output schema and the resulting tool args validate against
  the tool's input schema.
- **Don't conflate "the LLM call fired" with "the agent works"**.

### Triage

Apply to D13 onward. Retroactive smoke extension for D10/D11 agents not
needed — those have already passed real-LLM verification, which is a
strict superset.

---

---

## Pattern 3: Mock-based unit tests hide tool-API drift

### Instance: study_planner_v2, career_coach_v2, resume_reviewer_v2 (caught D12 CP3 Part H)

CP2 wrote three D12 agents with bespoke `ToolExecutor` instantiation:

```python
# WRONG — what CP2 wrote
executor = ToolExecutor(
    session=ctx.session,
    user_id=ctx.user_id,        # ← rejected by real signature
    permissions=...,            # ← rejected by real signature
)
await executor.call("log_event", {...})  # ← .call() doesn't exist
```

The real [`ToolExecutor.__init__`](../../backend/app/agents/primitives/tools.py)
takes `(session, *, max_retries, retry_backoff_seconds)` and the dispatch
method is `execute(tool_name, args, context: ToolCallContext)`. Three
contract violations stacked:

1. Wrong constructor kwargs (`user_id`, `permissions` not accepted)
2. Wrong method name (`.call()` doesn't exist; real method is `.execute()`)
3. Missing required `ToolCallContext` argument that carries user_id/permissions

CP2 unit tests were written against the same fictional API:

```python
# WRONG — what CP2 tests wrote
class _MockExecutor:
    def __init__(self, **_kwargs: Any) -> None:    # accepts ANY kwargs
        pass
    async def call(self, tool_name, args) -> Any:  # method exists in mock only
        ...
```

`MagicMock` and `**kwargs`-permissive mocks accept any constructor shape and
any method call. **Both the agent code AND the test code matched a
fictional API; the mismatch with the real API was invisible**. CP2 stub-LLM
smoke also bypassed the real executor (it stopped at the LLM boundary, per
Pattern 2 above), so the bug landed dormant until D12 CP3 real-MiniMax smoke
tried to actually invoke a tool.

### Discipline (D13+)

For agents with tool calls, every agent should have at least one
**real-instantiation integration test** (not mocked) that exercises the
tool dispatch layer end-to-end. The test must:

- Instantiate the agent (no agent mock)
- Build a real `AgentContext` with a real `AsyncSession` (or skip cleanly)
- Call `agent.tool_call(name, args, ctx)` on a known-safe tool (e.g.
  `log_event`, which has no DB side effect beyond an audit row)
- Assert the call returns `ToolCallResult.status == "ok"`

Catches:
- Constructor signature drift (Bug 5.1)
- Method name drift (Bug 5.2)
- Missing context argument (Bug 5.3)
- Other API contract mismatches that mocks paper over

### Mitigation

Add the real-instantiation integration test pattern to the migration
template (Pass 3c §A.10) so D13+ migrations include it by default. The
template should provide the boilerplate so each new agent's CP2 ships
with a real-instantiation test alongside the mocked unit tests.

### Triage

D13 onward applies the discipline by default. Retroactive integration
tests for D10 (billing_support) and D11 (senior_engineer) at D17 cleanup —
neither uses ToolExecutor directly so the urgency is low, but adding tests
catches future migrations of those agents to tool-aware shapes.

### Cross-reference

- [tests/test_agents/test_study_planner_v2_tool_calls.py::TestRealToolExecutorIntegration](../../backend/tests/test_agents/test_study_planner_v2_tool_calls.py)
- [tests/test_agents/test_career_coach_v2_tool_calls.py](../../backend/tests/test_agents/test_career_coach_v2_tool_calls.py)
- [tests/test_agents/test_resume_reviewer_v2_tool_calls.py](../../backend/tests/test_agents/test_resume_reviewer_v2_tool_calls.py)

---

## Pattern 4: Bundle migrations multiply template errors

### Instance: D12 career bundle (caught throughout CP3)

D12 migrated four agents in one deliverable, written from a templated
approach in CP2. The template misremembered `ToolExecutor`'s API. The
error propagated to **three of four agents identically** (the fourth,
tailored_resume, doesn't use ToolExecutor — it delegates to the service).

CP2 verification couldn't catch the template error because both available
verification paths bypass real tool dispatch:

- Stub-LLM smoke: stopped at the LLM boundary (Pattern 2)
- Mocked unit tests: accepted the fictional API silently (Pattern 3)

The error was dormant for the duration of CP1, CP2, and the first half of
CP3 — only surfacing when real-MiniMax verification tried to actually
invoke tools. Three agents broke identically. The cost (in CP3 verification
churn) was bigger than fixing one agent end-to-end before writing the
remaining three.

### Discipline (D14, D15 — also bundle migrations)

For bundle migrations, **verify the FIRST agent end-to-end including real
tool dispatch BEFORE writing the second agent**. Catches template errors
at agent #1 cost, not at agent #N cost.

Concretely, in CP2 of bundle deliverables:

1. Write the first agent's `_v2.py` + prompt
2. Run real-instantiation integration test (Pattern 3)
3. Run a real-MiniMax smoke for the first agent
4. **Only then** write the second agent from the now-validated template
5. The remaining N-1 agents can use the validated template confidently

This trades CP2 wall-clock for CP3 cost-and-rework predictability. Bundle
migrations have higher template risk than single migrations because
template errors propagate to every agent.

### Single vs. bundle migration evidence

- D11 (single agent: senior_engineer) — stub smoke caught real bugs,
  CP3 verification clean.
- D12 (four agents: career bundle) — stub smoke certified bugs as fine,
  CP3 verification hit Bugs 1, 2, 3, 5, 6 across multiple agents.

The pattern isn't "Claude was sloppy in D12"; it's "stub-smoke-then-mock
verification methodology has a known gap that single migrations
accidentally compensate for (one agent → fewer chances for template
errors), and bundle migrations expose."

### Triage

Applies to D14, D15 (next bundle migrations on the roadmap). Not a
retroactive concern for D10, D11, D12 — those are already shipped or
in-flight with the lessons learned.

## Cross-references

- [tests/test_agents/test_study_planner_v2_tool_calls.py](../../backend/tests/test_agents/test_study_planner_v2_tool_calls.py)
  — regression pin: 6 unit tests covering Bugs 1+2 and the H.2 integration test
- [tests/test_agents/test_career_coach_v2_tool_calls.py](../../backend/tests/test_agents/test_career_coach_v2_tool_calls.py)
  — H.2 integration test for career_coach
- [tests/test_agents/test_resume_reviewer_v2_tool_calls.py](../../backend/tests/test_agents/test_resume_reviewer_v2_tool_calls.py)
  — H.2 integration test for resume_reviewer
- [backend/app/agents/study_planner_v2.py](../../backend/app/agents/study_planner_v2.py)
  — `_log_mode_inference` (Bug 1 fix), `_commit_plan` (Bug 2 fix), `_safe_tool` (Bug 5 fix)
- [backend/app/agents/career_coach_v2.py](../../backend/app/agents/career_coach_v2.py)
  — `_safe_tool` (Bug 5 fix)
- [backend/app/agents/resume_reviewer_v2.py](../../backend/app/agents/resume_reviewer_v2.py)
  — `_safe_tool` (Bug 5 fix)
- [backend/app/agents/agentic_base.py](../../backend/app/agents/agentic_base.py)
  — `tool_call` helper (line 496) — the canonical helper CP2 should have used
- [backend/app/agents/tools/universal/log_event.py](../../backend/app/agents/tools/universal/log_event.py)
  — `LogEventInput` with `extra="forbid"`; defines the contract Bug 1 violated
- [backend/app/agents/tools/agent_specific/study_planner/commit_plan.py](../../backend/app/agents/tools/agent_specific/study_planner/commit_plan.py)
  — `CommitPlanInput.plan_type: Literal["weekly", "session"]`; the contract Bug 2 violated
- [log-event-observability-sink.md](./log-event-observability-sink.md) —
  the related concern about log_event having no DB sink yet
