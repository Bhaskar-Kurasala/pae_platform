---
title: Pass 3k/3l — Implementation Roadmap Synthesis
status: Final — the executable plan from architecture to shipping platform
date: After Pass 3j sign-off; closes the architecture engagement
authored_by: Architect Claude (Opus 4.7)
purpose: Convert Passes 3b through 3j from architectural decisions into executable implementation deliverables. Deliver the sequenced D9–D17 list with scope, success criteria, dependencies, risks, and review checkpoints. Provide the full Claude Code prompt for D9 (the keystone deliverable), templates for D10/D12/D13/D14/D16/D17, and placeholders for D11 and D15 (which will be prompt-written when their turn comes). Documents the modified engagement model — architect covers D9/D11/D15; founder handles the rest with templates.
supersedes: nothing
superseded_by: nothing — this is the final architecture document
informs: D9 ships first using the prompt below; subsequent deliverables follow the per-deliverable specs in Section B
implemented_by: D9 through D17 themselves; this pass is the pre-implementation contract
depends_on: every prior architecture pass — Pass 3b through 3j. Specifically: Pass 3b (Supervisor), Pass 3c (agent migration playbook), Pass 3d (tool implementations), Pass 3e (curriculum graph), Pass 3f (entitlement enforcement), Pass 3g (safety primitive), Pass 3h (interrupt agent + proactive loop), Pass 3i (scale + observability), Pass 3j (naming sweep + cleanup)
---

# Pass 3k/3l — Implementation Roadmap Synthesis

> Architecture is decided. This pass converts decisions into deliverables. Read alongside the prior passes — each deliverable cites the passes it implements.

> Engagement model: the architect (this Claude) covers D9, D11, and D15 in full — those have decisions sitting at the limit of what the architecture passes alone can drive. The founder handles D10, D12, D13, D14, D16, and D17 using the templates in this pass and the per-agent specifications in Pass 3c. The architect remains available for architectural questions on those deliverables; founder initiates based on need, not schedule.

---

## Section A — The Sequenced Deliverable List

Nine deliverables. Roughly 4-6 weeks of focused implementation work at typical Claude Code throughput, assuming prompt review cadence isn't the bottleneck. Each deliverable is reviewable in 1-3 hours after Claude Code reports completion.

### A.1 Critical path

```
D9  →  D10  →  D11  →  D12  →  D13  →  D14  →  D15  →  D16  →  D17
       ↓       ↓       ↓       ↓       ↓       ↓       ↓       ↓
    (founder)(architect)(founder)(founder)(founder)(architect)(founder)(founder)
       
   ◇ D9 ships before anything else: it's the foundation
   ◇ D11 ships before D14 (practice_curator) because senior_engineer is needed
   ◇ D12 ships before D13 because mock_interview hands off to senior_engineer
       AND because career_coach reasoning informs mock_interview prompt design
   ◇ D15 (curriculum graph) can run in parallel with D13/D14 if desired,
       but sequential is simpler operationally
   ◇ D16 ships after D15 (interrupt_agent reads risk signals enriched by graph)
   ◇ D17 is last by design (cleanup absorbs residual work from prior deliverables)
```

### A.2 Off-ramps

If launch pressure forces an early ship, viable pause points:

- **After D11** — students get Supervisor + entitlement + safety + a working Learning Coach + senior_engineer (code review). Career bundle, mock interviews, and proactive nudges are missing. **Minimum viable platform** for early access / closed beta. Saves ~50% of remaining implementation work.
- **After D13** — adds career bundle and mock interview. Missing: practice_curator (NEW agent), curriculum graph, proactive nudges, cleanup. **Open beta minimum**. Saves ~30% of remaining work.
- **After D15** — adds curriculum graph and content_ingestion. Missing: proactive nudges, cleanup. **Public launch minimum**. Saves ~15% of remaining work.

The off-ramp choice depends on what you're optimizing for. My honest read: aim for D17 if timeline allows. D9-D13 produces a usable platform; D14-D17 produces an *AICareerOS-the-OS* experience.

### A.3 Effort estimates (honest)

| Deliverable | Estimated effort | Why |
|---|---|---|
| D9 | 5-7 days | Largest single deliverable. Foundation must be right. |
| D10 | 2-3 days | Narrow scope, training-wheels migration |
| D11 | 4-6 days | Sandbox infrastructure adds real complexity |
| D12 | 4-6 days | Career bundle of 4 agents migrated together |
| D13 | 3-5 days | Stateful sessions are tricky but contained |
| D14 | 4-6 days | practice_curator NEW + project_evaluator together |
| D15 | 5-7 days | Curriculum graph schema + ingestion pipeline + tools |
| D16 | 3-5 days | interrupt_agent + Email MCP + dashboards |
| D17 | 3-5 days | Cleanup batch, runbooks, full dashboard set |

**Total: 33-50 days of focused implementation work.** At one deliverable per ~4 days, the platform is end-to-end shipped in ~6 weeks. If reviews/prompt-writing add overhead, 8 weeks is more realistic.

These are *Claude Code throughput* estimates, not calendar days. Calendar reality depends on review pace.

---

## Section B — Per-Deliverable Specifications

Each spec is "what gets built, how do we know it's done, what could go wrong."

### B.1 D9 — Foundation

**Architect role:** writes the full prompt (Section C below), reviews the report end-to-end, signs off.

**Implements:**
- Pass 3b (Supervisor + dispatch layer)
- Pass 3f (entitlement enforcement, three layers, free tier infrastructure, cost ceiling)
- Pass 3g (safety primitive: regex layer 1, Presidio integration, output safety)
- Pass 3e (curriculum graph schema only; population deferred to D15)
- Pass 3i (initial sizing, basic dashboards, trace endpoint)
- PG-1 fix (Track 5 finding) and EscalationLimiter Redis recovery (Track 2 follow-up)

**New files (~30 files):** see D9 prompt in Section C.

**New tables (3 migrations):**
- `0055_supervisor_v1.py` — `student_snapshots` (optional, decide during impl), index additions for trace endpoint
- `0056_curriculum_graph.py` — 6 tables from Pass 3e §B (concepts, concept_relationships, concept_resource_links, misconceptions, concept_candidates, student_concept_engagement). Empty until D15 populates.
- `0057_entitlement_tier.py` — `tier` column on `course_entitlements`, `free_tier_grants` table, `mv_student_daily_cost` materialized view
- `0058_safety_incidents.py` — `safety_incidents` table

**Success criteria:**
1. Student with active entitlement can hit `POST /api/v1/agentic/{flow}/chat` and get routed to Learning Coach via the Supervisor
2. Student without entitlements gets 402 with structured `decline_message`
3. Free-tier student (signed up in last 24h) can call billing_support via Supervisor; gets declined gracefully on senior_engineer
4. Supervisor's decision logged in `agent_actions` with reasoning
5. Trace endpoint `/api/v1/admin/students/{id}/journey` returns coherent timeline
6. All 5 failure classes from Pass 3b §7.1 covered by unit tests
7. E2E tests pass: entitled happy path, unentitled 402, free-tier path, Supervisor escalation fallback to keyword routing
8. PG-1 verified: webhooks subscribe in both Celery AND FastAPI processes
9. EscalationLimiter recovers from Redis outage by replaying from agent_escalations
10. Cost ceiling enforced: synthetic test exhausting budget gets graceful decline
11. Safety primitive blocks obvious prompt injection (regex layer)
12. Presidio detects PII in input; redacts in logs while allowing request
13. Materialized view `mv_student_daily_cost` refreshing every 60s via Celery beat
14. Basic Grafana dashboard shows: total agent calls, decline rate, cost ceiling hits

**Risks:**
- **Presidio model download bloats container size.** Mitigation: confirm container build process supports the +1.5GB; document in deployment notes.
- **PG-1 fix introduces double-loading in Celery.** Mitigation: idempotent loader (check if already loaded before re-running); explicit test for double-load.
- **Materialized view refresh contention.** Mitigation: `REFRESH MATERIALIZED VIEW CONCURRENTLY`; monitor refresh duration.
- **Trace endpoint slow on hot students.** Mitigation: index review per Pass 3i §B.5; consider replica routing as fast-follow if needed.

**Review checkpoints:**
- Mid-deliverable: confirm the Supervisor's `RouteDecision` structure validates correctly with synthetic inputs before specialists wire in
- Pre-merge: full E2E test pass; PG-1 webhook subscriber test passes in both processes; cost ceiling test scenario passes

---

### B.2 D10 — billing_support migration

**Architect role:** none. Founder writes prompt using Pass 3c E1 + the template in Section D.

**Implements:**
- Pass 3c E1 (billing_support agent migration)
- Pass 3d Section D (universal tools: memory_recall, memory_write, memory_forget, log_event, read_own_capability)
- Pass 3d Section F.1 (billing_support-specific tools: lookup_order_history, lookup_active_entitlements, lookup_refund_status, escalate_to_human)
- First exercise of the migration template from Pass 3c §A.10

**Why this one first:** narrow scope, Haiku model, low risk, no inter-agent dependencies. Establishes the pattern for everything that follows. If something is wrong with the migration template, this is where it surfaces — cheaply.

**Success criteria:**
1. billing_support extends AgenticBaseAgent with the 5 primitive flags from Pass 3c E1
2. Full prompt from Pass 3c E1 deployed at `backend/app/agents/prompts/billing_support.md`
3. Output schema `BillingSupportOutput` defined and validated
4. AgentCapability registered; Supervisor sees billing_support in its prompt
5. Universal tools (5 of them) implemented; billing-specific tools (4) implemented
6. Supervisor can route a billing question to billing_support via the canonical endpoint
7. Free-tier students can call billing_support (per Pass 3f §B.4)
8. Unit tests cover: happy path, all 5 failure classes, schema validation
9. E2E test: end-to-end billing question via Supervisor, asserts response shape
10. Legacy `backend/app/agents/billing_support.py` (BaseAgent version) deleted
11. AGENT_REGISTRY entry points to new class

**Risks:**
- **Tool bodies too thin.** Mitigation: explicitly include lookup-table seeding in the test fixtures so tools have real-ish data to query.
- **Migration template has gaps.** Mitigation: this is the first exercise; flagging gaps early is the *point*. Founder should pause and surface anything unclear rather than guess.

**Review checkpoint:** founder reviews Claude Code's report against Pass 3c E1's specifications. Specific questions to ask:
- Does the prompt match Pass 3c E1's text *verbatim* (subject to brand sweep adjustments)?
- Does the output schema honor every field in Pass 3c E1's spec?
- Are all 4 billing-specific tools present and registered?

---

### B.3 D11 — senior_engineer migration + sandbox infrastructure

**Architect role:** writes the full prompt when D10 signs off. The sandbox infrastructure choice (E2B vs. custom Docker) needs architectural input that goes beyond Pass 3d §E.3's "start with E2B."

**Implements:**
- Pass 3c E2 (senior_engineer migration, merged from code_review + coding_assistant + senior_engineer legacy)
- Pass 3d Section E.3 (run_static_analysis, run_in_sandbox, run_tests + sandbox infrastructure decision)
- Pass 3c §F.10 (caller updates: practice review endpoints repointed)

**Why this position:** high-traffic agent, but no upstream dependencies after D10. Establishes the merge pattern. The sandbox decision is the architectural complexity.

**Architect-only decisions in D11 prompt:**
- E2B vs. Modal vs. custom Docker (will commit before writing prompt)
- Whether sandbox runs are charged to student or platform (Pass 3f says student; revisit with sandbox-cost data)
- Network access policy edge cases beyond Pass 3d §E.3

**Success criteria, risks, checkpoints:** detailed in the D11 prompt when written.

---

### B.4 D12 — Career bundle (career_coach + study_planner + resume_reviewer + tailored_resume)

**Architect role:** none. Founder writes prompt using Pass 3c E3-E6 + Section D template.

**Implements:**
- Pass 3c E3 (career_coach), E4 (study_planner NEW), E5 (resume_reviewer), E6 (tailored_resume)
- Pass 3d Section E.2 (student state domain tools): read_student_full_progress, read_capstone_status, read_goal_contract, read_mastery_summary, read_recent_session_history
- Pass 3d Section F.3 (career-specific tools): commit_plan, track_adherence
- New table `study_plans` for plan persistence
- The handoff chain career_coach → study_planner → resume_reviewer that exercises Supervisor's chain dispatch

**Why migrate as a bundle:** these four hand off to each other. Migrating one without the others breaks chains.

**Success criteria:**
1. All four agents extend AgenticBaseAgent with appropriate primitive flags per Pass 3c
2. Output schemas defined for each
3. Handoff chains work: career_coach → study_planner via Supervisor; tailored_resume → resume_reviewer for self-validation
4. Student state domain tools implemented and tested
5. study_plans table created via migration
6. study_planner's `@proactive(cron="0 22 * * *")` scheduled for nightly adherence checks (NOT enabled in production until D16; just registered)
7. E2E test: full career conversation flow exercises chain dispatch
8. All four legacy agent files deleted; registry updated

**Risks:**
- **Chain dispatch complexity surfaces issues with D9's implementation.** Mitigation: D9's chain dispatch tests are synthetic; D12 is the first real exercise. If real chains reveal issues, escalate to architect.
- **study_planner is brand new with no legacy reference.** Mitigation: Pass 3c E4 specifies it in detail; founder follows that spec literally for v1.
- **read_market_signals deferred per Pass 3d §F.3.** career_coach's prompt acknowledges the gap; output schema's `market_signals` field will be empty in v1.

**Review checkpoint:** end-to-end run a "I'm planning my career switch" conversation. Assert: career_coach handles strategic direction; study_planner produces tactical plan; chain dispatched once between them; both write to memory; trace endpoint shows the chain.

---

### B.5 D13 — mock_interview migration

**Architect role:** none. Founder writes prompt using Pass 3c E7 + Section D template.

**Implements:**
- Pass 3c E7 (mock_interview migration)
- Pass 3d Section F.4 (mock_interview tools: generate_question_for_format, evaluate_response, lookup_interview_history)
- Stateful session state in agent_memory with longer TTL

**Why this position:** benefits from senior_engineer (D11) being available for code-coding-round handoffs. Career_coach (D12) is also available for "should I be doing interviews yet?" handoffs.

**Special concern:** mock_interview is the first agent with stateful multi-turn sessions. Most agents are stateless per call. The session_id pattern needs careful implementation; conversation_id (Pass 3b's persistent thread) is per-conversation, but mock_interview maintains *interview_session_id* across multiple Supervisor invocations within an interview.

**Success criteria:**
1. mock_interview extends AgenticBaseAgent
2. Four format sub-prompts (system_design, coding, behavioral, take_home) each handle their format correctly
3. Session state persists across Supervisor invocations
4. Coding-round handoff to senior_engineer works
5. Cross-session weakness tracking writes to memory at `mock_interview:weakness:*`
6. Critic samples mock_interview at higher rate (not 5%; closer to 20%) because interview quality is high-cost-of-failure
7. E2E test: multi-turn coding interview with handoff to senior_engineer

**Risks:**
- **Session state expiry.** A student might pause mid-interview for hours. Mitigation: 24-hour TTL on session state; if expired, agent gracefully resumes by reading prior turns from conversation thread.
- **Format-specific evaluation logic in code.** Mitigation: keep most evaluation in the prompt (LLM-driven) with structured output; only sandbox calls and rubric loads are code-side.

---

### B.6 D14 — practice_curator (NEW) + project_evaluator

**Architect role:** none. Founder writes prompt using Pass 3c E8-E9 + Section D template.

**Implements:**
- Pass 3c E8 (practice_curator NEW)
- Pass 3c E9 (project_evaluator migration)
- Pass 3d Section E.1 (curriculum domain tools — partial; full graph deferred to D15): find_concepts_at_mastery_edge, read_due_srs_cards
- Pass 3d Section F.5 (practice_curator tools): generate_exercise, validate_exercise_solvability
- Pass 3d Section F.6 (project_evaluator tools): read_full_capstone, read_published_rubric

**Why this position:** practice_curator is brand new; project_evaluator needs Supervisor + memory + curriculum domain tools. Both depend on D11's sandbox.

**Curriculum graph constraint:** practice_curator queries `find_concepts_at_mastery_edge` which works against existing tables (user_skill_states + srs_cards). It does NOT use the full curriculum graph yet (that's D15). practice_curator's exercise targeting is competent but graph-poor in v1; gets richer when D15 ships.

**Success criteria:**
1. practice_curator generates exercises targeted to student's mastery edge
2. project_evaluator evaluates capstones against published rubrics
3. Both hand off appropriately (practice_curator → senior_engineer for evaluation; project_evaluator → portfolio_builder for portfolio entry generation)
4. Sandbox-validates generated exercises (practice_curator's `validate_exercise_solvability`)
5. E2E test: student requests practice → practice_curator generates → student submits → senior_engineer evaluates

**Risks:**
- **Exercise generation produces unsolvable or trivially-solvable problems.** Mitigation: validate_exercise_solvability sandbox-runs the reference solution before returning to the student.
- **Anti-repetition logic gap.** Mitigation: practice_curator reads `submission:exercise:*` memory to avoid generating problems the student already saw.

---

### B.7 D15 — content_ingestion + curriculum knowledge graph

**Architect role:** writes the full prompt when D14 signs off. The curriculum graph build is the most complex remaining deliverable; benefits from architect attention.

**Implements:**
- Pass 3e (full curriculum graph build: bootstrap seeding, query patterns, narrative synthesis)
- Pass 3c E10 (content_ingestion migration with curriculum_mapper merged in)
- Pass 3d Section F.7 (content_ingestion tools): parse_github_repo, parse_youtube_content, extract_concepts, link_to_curriculum_graph, query_curriculum_graph
- Pass 3d Section G.1-G.2 (GitHub MCP server connection; YouTube MCP server build)
- Curriculum graph admin candidate review backend (no UI yet)
- Backfill: existing courses' concepts seeded into graph
- Update curriculum domain tools (Pass 3d §E.1.3) from "deferred" to functional

**Architect-only concerns in D15 prompt:**
- Concept slug naming convention (consistency across manual seeding + ingestion)
- Relationship inference confidence thresholds (when does an LLM-inferred relationship auto-apply vs. go to candidate queue)
- Embedding refresh policy edge cases
- Graph query caching strategy specifics
- Graceful degradation if Voyage-3 embedding service is down

**Success criteria, risks, checkpoints:** detailed in the D15 prompt when written.

---

### B.8 D16 — interrupt_agent + progress_report migration + Email MCP

**Architect role:** none. Founder writes prompt using Pass 3h + Pass 3c E11 + Section D template.

**Implements:**
- Pass 3h (interrupt_agent design)
- Pass 3c E11 (progress_report migration)
- Pass 3d Section F.8 (interrupt_agent tools): read_student_full_context, check_recent_outreach, compose_dm, compose_email, schedule_followup
- Pass 3d Section G.4 (Email MCP server build)
- Migration 0059: nudge_records, nudge_responses, scheduled_outreach tables
- Daily Celery beat for `daily_interrupt_check`
- 5% hold-out group implementation
- Engagement dashboard data feeds (Pass 3i §G.3 dashboards built in D17 consume this data)

**Why this position:** depends on D15's risk-signal enrichment from curriculum graph (e.g., "stuck at concept X with no canonical resource" is richer than "stuck at concept X").

**Success criteria:**
1. interrupt_agent runs daily for active paid students
2. Decision logic from Pass 3h §B.6 implemented (8-step decision order)
3. Frequency cap of 1 nudge/student/day enforced globally across channels
4. Quiet hours respected with timezone fallback to IST
5. Pause-link mandatory in every nudge
6. Email MCP server functional; sends through existing outreach_automation rate limits
7. Hold-out group: 5% of at_risk students excluded deterministically by hash
8. nudge_records and nudge_responses tables capture all outcome data
9. **Dry-run mode** runs for 3 days before live mode (per Pass 3h §H.3)
10. progress_report migration to AgenticBaseAgent complete

**Risks:**
- **First nudge sends to wrong students.** Mitigation: dry-run mode for 3 days; manual review of decisions before going live.
- **Email deliverability low for new sender domain.** Mitigation: gradual ramp; pre-warm domain reputation.
- **Pause-link click-through low.** Mitigation: A/B test the link prominence; track via PostHog.

---

### B.9 D17 — Final cleanup, runbooks, full operational set

**Architect role:** none. Founder writes prompt using Pass 3i + Pass 3j + Section D template.

**Implements:**
- Pass 3i (full operational dashboards + runbooks)
- Pass 3j (standalone cleanup batch: scaffolding folders, stale tests, residual retired agents, dead deps, two-main.py investigation)
- Performance baseline + regression test infrastructure
- The capacity checkpoint procedures documented as runbooks
- Production-readiness checklist verification

**Success criteria:**
1. All scaffolding folders deleted (per Pass 3j §B.1 verification protocol)
2. All stale `run_3*_tests.py` files deleted
3. All retired agents per Pass 3a Addendum gone (those not deleted earlier)
4. Backend dead dependencies removed (Stripe et al)
5. Two-main.py investigation complete; outcome documented
6. Engagement dashboard live (consuming D16 data)
7. Safety dashboard live (consuming Pass 3g data)
8. Curriculum graph dashboard live (consuming D15 data)
9. Cost dashboard live (consuming Pass 3f data)
10. Five core runbooks shipped: Supervisor LLM degradation, curriculum graph saturation, safety incident spike, cost-ceiling-hit surge, webhook subscriber gap
11. Final doc sweep: README, AGENTIC_OS.md, runbooks, all reflect AICareerOS
12. Smoke test: full platform end-to-end with synthetic student journey covering all 14 surviving agents

**Risks:**
- **Cleanup deletion breaks something.** Mitigation: Pass 3j §D verification protocols followed strictly; rollback plan in every commit.
- **Dashboards depend on data not flowing yet.** Mitigation: dashboards read from real D16 data after D16 has run for at least a week.

---

## Section C — D9 Implementation Prompt (Full)

This is the prompt to paste into Claude Code when D9 starts. Read end-to-end before invoking.

```
=========================================================================
D9: AICareerOS Foundation — Supervisor + Entitlement + Safety + Trace
=========================================================================

# Context

You are implementing the foundational deliverable for AICareerOS, a learning
operating system for engineers transitioning into senior GenAI engineering.
The architecture is designed in detail across passes 3b through 3j, all
committed to docs/architecture/ in this repo. Read these passes before
starting any implementation work:

  Required reading:
  - docs/architecture/pass-3b-supervisor-design.md (the Supervisor)
  - docs/architecture/pass-3f-entitlement-enforcement.md (entitlement layers)
  - docs/architecture/pass-3g-safety-beyond-critic.md (safety primitive)
  - docs/architecture/pass-3i-scale-observability-cost.md §F (trace endpoint)
  - docs/architecture/pass-3e-curriculum-knowledge-graph.md §B (graph schema only)
  - docs/AGENTIC_OS.md (the D1-D8 foundation you build on)

  Recommended:
  - docs/audits/pass-1-ground-truth.md (current state)
  - docs/audits/pass-2-hypothesis-verification.md (the gaps you close)
  - docs/audits/agentic-os-precondition-gaps.md (PG-1 specifically)

# What you're building

This deliverable lays the foundation that makes every subsequent agent
migration possible. Specifically:

1. The Supervisor agent — the orchestrator that turns specialist agents
   into a coordinated OS (Pass 3b)
2. The dispatch layer that executes Supervisor decisions
3. The canonical /api/v1/agentic/{flow}/chat endpoint
4. The three-layer entitlement enforcement model (Pass 3f)
5. Tier infrastructure with single 'standard' tier shipped + 'free' tier
   for narrow onboarding scope
6. The safety primitive wrapping every agent (Pass 3g): regex pattern bank,
   Microsoft Presidio for PII, severity-action policy
7. The curriculum graph schema (Pass 3e §B) — tables created, empty;
   D15 will populate
8. The trace endpoint /api/v1/admin/students/{id}/journey
9. PG-1 fix: agentic_loader called from FastAPI lifespan
10. EscalationLimiter Redis recovery on reconnect
11. Materialized view mv_student_daily_cost refreshed every 60s

# Migrations to create

Create these migrations IN ORDER:

  0055_supervisor_v1.py
    - Add 'summary' TEXT column to agent_actions for memory_curator pattern
    - Add index on agent_call_chain (request_id, parent_action_id) if missing
    - Add index on agent_actions (created_at) WHERE agent_name = 'supervisor'
      AND output_data->>'decline_reason' IS NOT NULL

  0056_curriculum_graph.py
    - Per Pass 3e §B exactly: concepts, concept_relationships,
      concept_resource_links, misconceptions, concept_candidates,
      student_concept_engagement
    - HNSW indexes on embedding columns
    - Standard btree indexes per Pass 3e §B
    - DO NOT POPULATE; D15 handles seeding

  0057_entitlement_tier.py
    - ALTER TABLE course_entitlements ADD COLUMN tier TEXT NOT NULL DEFAULT
      'standard' CHECK (tier IN ('free', 'standard', 'premium'))
    - CREATE TABLE free_tier_grants per Pass 3f §C.1
    - CREATE MATERIALIZED VIEW mv_student_daily_cost per Pass 3f §D.1
    - CREATE INDEX idx_entitlements_user_tier on the alter

  0058_safety_incidents.py
    - CREATE TABLE safety_incidents per Pass 3g §E.1
    - Indexes per Pass 3g §E.1

# New files to create

Backend:
  - backend/app/agents/supervisor.py — Supervisor(AgenticBaseAgent)
  - backend/app/agents/prompts/supervisor.md — full prompt per Pass 3b §4.2
  - backend/app/agents/dispatch.py — dispatch layer (single + chain + handoff)
  - backend/app/agents/capability.py — AgentCapability registry helpers
  - backend/app/agents/primitives/safety/__init__.py
  - backend/app/agents/primitives/safety/gate.py — SafetyGate class
  - backend/app/agents/primitives/safety/pii_detector.py — Presidio wrapper
  - backend/app/agents/primitives/safety/prompt_injection.py — regex layer
  - backend/app/agents/primitives/safety/llm_classifier.py — Layer 2 Haiku
  - backend/app/agents/primitives/safety/abuse_patterns.py — Layer 3
  - backend/app/agents/primitives/safety/output_scanners.py — output side
  - backend/app/agents/primitives/safety/streaming.py — streaming-aware scan
  - backend/app/agents/primitives/safety_patterns/prompt_injection_v1.json
    (pattern bank from Pass 3g §B.2.1)
  - backend/app/services/agentic_orchestrator.py — replaces AgentOrchestratorService
  - backend/app/services/student_snapshot_service.py — computes StudentSnapshot
  - backend/app/api/v1/routes/agentic.py — canonical endpoint
  - backend/app/api/v1/routes/admin_journey.py — trace endpoint
  - backend/app/api/v1/dependencies/entitlement.py — Layer 1 dependency
  - backend/app/services/entitlement_service.py — extend with
    compute_active_entitlements returning EntitlementContext
  - backend/app/core/tiers.py — TIER_CONFIGS
  - backend/app/core/safety_policy.py — severity → action mapping
  - backend/app/schemas/supervisor.py — RouteDecision, ChainStep,
    SupervisorContext, StudentSnapshot, AgentCapability
  - backend/app/schemas/entitlement.py — EntitlementContext, ActiveEntitlement,
    FreeTierState
  - backend/app/schemas/safety.py — SafetyVerdict, SafetyFinding

Tests:
  - backend/tests/test_agents/test_supervisor.py — unit tests for all
    5 failure classes from Pass 3b §7.1
  - backend/tests/test_agents/test_dispatch.py — single + chain + handoff
  - backend/tests/test_agents/test_safety_gate.py — input + output scans
  - backend/tests/test_entitlement.py — three-layer enforcement
  - backend/tests/test_pii_detector.py — Presidio integration
  - frontend/e2e/agentic-foundation.spec.ts — end-to-end tests
    (Track 5 established the pattern; follow it)

# Existing files to modify

  - backend/app/main.py — lifespan handler calls _agentic_loader.load_agentic_agents()
    (PG-1 fix); verify subscribers populated AFTER lifespan completes
  - backend/app/agents/agentic_base.py — wrap run() with safety scans per
    Pass 3g §A.5
  - backend/app/agents/primitives/escalation_limiter.py — add Redis-recovery
    logic that replays from agent_escalations on Redis reconnect
  - backend/app/celery.py — add beat schedule for mv_student_daily_cost
    refresh every 60s
  - pyproject.toml — add presidio-analyzer, presidio-anonymizer, spacy
  - Dockerfile (or container build process) — download spaCy en_core_web_lg

# Critical implementation notes

1. THE SUPERVISOR PROMPT MUST BE DYNAMIC. Build the agents list from
   the AgentCapability registry at request time, NOT hardcoded. This is
   load-bearing for the Pass 3a/3c roster to be reflected in routing.

2. ENTITLEMENT CHECK ORDER MATTERS. Layer 1 (route dependency) → Layer 2
   (Supervisor's reasoning) → Layer 3 (dispatch re-check). Each catches
   different failure modes per Pass 3f §A.4.

3. PRESIDIO LOADS A 750MB MODEL AT STARTUP. The container will be larger.
   Loading takes ~3 seconds per process. Test that worker startup
   succeeds with the larger image.

4. THE MATERIALIZED VIEW REFRESH IS A CELERY BEAT JOB. Use REFRESH
   MATERIALIZED VIEW CONCURRENTLY. The 60-second cadence is intentional
   per Pass 3f §D.1.

5. SAFETY GATE WRAPS run() OPTIONALLY. Per Pass 3g §A.5, the wrapping
   is part of AgenticBaseAgent.run(). For agents that opt out (only
   billing_support and supervisor at minimum-tier 'free' currently),
   the gate still runs — opting out of *safety* is not allowed. The
   only thing agents opt out of via flags is uses_self_eval, etc.

6. STUDENT SNAPSHOT CACHING IS LOAD-BEARING. Per Pass 3b §3.1, the
   snapshot has a 5-minute Redis TTL. The Supervisor reads through
   the snapshot, NEVER directly from underlying tables. This is
   critical for performance at 1k students.

7. THE CANONICAL ENDPOINT IS /api/v1/agentic/{flow}/chat. The {flow}
   parameter is for forward compatibility (different flows might
   want different Supervisor configurations later); for D9, accept
   "default" and "demo" as valid flows.

8. TRACE ENDPOINT IS READ-ONLY. /api/v1/admin/students/{id}/journey
   reads from primary at Tier 1 (Pass 3i §F.2); replica routing is
   a Tier 2 concern. Don't add replica logic now.

9. LEARNING COACH (D8) IS THE ONLY MIGRATED SPECIALIST INITIALLY. After
   D9, the Supervisor's roster has: supervisor itself, billing_support
   (NOT MIGRATED YET — declared in capability registry but the agent
   class is still the legacy BaseAgent version), Learning Coach
   (already migrated in D8). Other specialists are unreachable via
   the new endpoint until their migration deliverables run.

10. Brand: AICareerOS. Use exactly that capitalization. Support email:
    support@aicareeros.com. Per Pass 3j.

# Verification protocol

After all files written, BEFORE marking the deliverable complete:

  1. Run alembic upgrade head — all 4 migrations apply cleanly
  2. Run alembic downgrade base, then alembic upgrade head — round-trip works
  3. Run pytest backend/tests/ — all tests pass
  4. Run pytest backend/tests/test_agents/test_supervisor.py specifically
     — all 5 failure classes covered
  5. Start the FastAPI app — confirm Presidio + spaCy load successfully
     in startup logs
  6. Start the Celery worker — confirm same loads + beat schedule active
  7. Check that subscribers exist BOTH in Celery process AND FastAPI process
     (PG-1 verification — script in test that exercises this)
  8. Run frontend/e2e/agentic-foundation.spec.ts — passes
  9. Manual test: hit POST /api/v1/agentic/default/chat as an authenticated
     user with active entitlement; confirm 200 with structured response
  10. Manual test: hit same endpoint as authenticated user without
      entitlement; confirm 402 with structured error per Pass 3f §A.1
  11. Manual test: signup a new user; confirm free_tier_grants row created;
      confirm they can call billing_support but not senior_engineer

# Stop-and-review checkpoints

PAUSE and produce a status report at these mid-deliverable points:

  Checkpoint 1: After migrations + schemas defined (no agent code yet)
    — confirm migration plan is right before writing logic on top
  Checkpoint 2: After SafetyGate is implemented but before integration
    into AgenticBaseAgent — confirm the contract is right
  Checkpoint 3: After Supervisor + dispatch layer but before endpoint
    wiring — confirm the orchestration logic is sound
  Checkpoint 4: After endpoint wiring, before tests — confirm the
    full path from request to response is correct

At each checkpoint, write a brief report and wait for sign-off.

# Final deliverable report

When all 11 verification protocol items pass, produce a final report:

  - Summary: what was built (1 paragraph)
  - Files created: complete list with sizes
  - Files modified: complete list
  - Migrations: list with brief description of each
  - Test results: pytest output summary, E2E output summary
  - Manual verification: confirmation of items 9, 10, 11 above
  - Deliberately did NOT do: explicit list of things in Pass 3b/3f/3g/3e
    that this deliverable did NOT implement (e.g., curriculum graph
    population, agent migrations beyond the foundation)
  - Known follow-ups: anything you encountered that should be tracked
  - Risks for next deliverable: anything that might affect D10

# Anti-patterns to avoid

  - DO NOT migrate billing_support's class in D9. Only declare its
    capability. The class migration is D10's job.
  - DO NOT populate the curriculum graph. D15's job.
  - DO NOT wire up the YouTube/Email/Calendar MCPs. Different deliverables.
  - DO NOT touch the frontend except for adding/updating
    frontend/e2e/agentic-foundation.spec.ts (per the Track 5 pattern;
    test files are the only allowed frontend touches).
  - DO NOT implement red-team test suite. Pass 3g calls for ~30 case
    seed; that's D17.
  - DO NOT skip the EscalationLimiter Redis recovery. It's small
    (~30 LOC) and important.
  - DO NOT skip the PG-1 fix. ~5 LOC. Verified by test.
  - DO NOT change anything in /docs/architecture/. Those are the contract.
  - DO NOT modify the Pass 1 / Pass 2 / Pass 3a-Addendum docs in
    docs/audits/. Those are decision history.

=========================================================================
End of D9 prompt
=========================================================================
```

---

## Section D — Template For D10/D12/D13/D14/D16/D17

When founder writes a prompt for these deliverables, use this template. Replace `{deliverable_id}` and fill in deliverable-specific details from the corresponding Pass 3c section + Section B above.

```
=========================================================================
{deliverable_id}: {deliverable_short_name}
=========================================================================

# Context

You are implementing {deliverable_id} for AICareerOS. The architecture is
designed in passes 3b through 3j in docs/architecture/. The prior
deliverable {prior_deliverable_id} signed off on {prior_signoff_date}.

  Required reading:
  - docs/architecture/pass-3c-agent-migration-playbook.md
    Section {section} (the spec for this migration)
  - docs/architecture/pass-3d-tool-implementations.md
    Section {section} (tools needed)
  - {any other directly-relevant pass}

  Architectural foundation already in place:
  - D9: Supervisor, dispatch layer, entitlement enforcement, safety primitive,
    curriculum graph schema, trace endpoint
  - {prior deliverables: list what's already shipped}

# What you're building

{1-paragraph summary in plain language}

# Migrations to create

{Specific migration files with descriptions, OR "No new migrations" if none}

# New files to create

Backend:
  - backend/app/agents/{agent_name}.py — {AgentName}(AgenticBaseAgent)
  - backend/app/agents/prompts/{agent_name}.md — full prompt per
    Pass 3c {section} §A.9 structure
  - backend/app/schemas/agents/{agent_name}.py — output schema
  - {tool files per Pass 3d section}
  - {other files}

Tests:
  - backend/tests/test_agents/test_{agent_name}.py
    Cover: happy path, all 5 failure classes from Pass 3b §7.1,
    schema validation, memory read/write, handoff scenarios
  - frontend/e2e/{agent_name}.spec.ts (if applicable)

# Existing files to modify

  - backend/app/agents/__init__.py — register the new agent
  - {anywhere caller updates per Pass 3c §F apply}
  - {anything else}

# Critical implementation notes

  {Deliverable-specific gotchas. Use Pass 3c specific section's
   "migration checklist" §A.10 as the basis. Add anything that
   surfaced in earlier deliverables.}

# Verification protocol

After all files written, BEFORE marking the deliverable complete:

  1. Run alembic upgrade head — migration applies cleanly
  2. Run pytest — all tests pass
  3. Start FastAPI app — agent registers in capability registry
     (visible at /api/v1/admin/agents/list endpoint if available)
  4. Manual test: hit canonical endpoint with intent that should
     route to this agent; confirm Supervisor dispatches correctly
  5. Manual test: trace endpoint shows the call chain ending at
     this agent
  6. Memory persistence check: re-run the same user's query;
     confirm prior interaction visible in agent's context
  7. Legacy file deletion: confirm backend/app/agents/{agent_name}.py
     was the legacy BaseAgent version and is now the new
     AgenticBaseAgent version (i.e., the migration completed cleanly,
     not a parallel _v2 file lingering)

# Stop-and-review checkpoints

  Checkpoint 1: After schema + capability declared, before agent class
    — confirm contract matches Pass 3c spec
  Checkpoint 2: After agent class + prompt, before tools wired
    — confirm prompt is faithful to Pass 3c spec
  Checkpoint 3: After tools wired, before tests
    — confirm end-to-end works on a manual test
  Checkpoint 4: After tests pass, before legacy deletion
    — confirm test coverage matches Pass 3c §A.10 checklist

# Final deliverable report

  - Summary: what was built (1 paragraph)
  - Files created: complete list
  - Files modified: complete list
  - Files deleted: legacy agent file(s) per Pass 3c §F
  - Tests: pytest + E2E results
  - Manual verification: confirmation of protocol items 4-7
  - Deliberately did NOT do: list anything from Pass 3c
    §{section} that's deferred
  - Known follow-ups
  - Risks for next deliverable

# Anti-patterns to avoid

  - DO NOT extend scope beyond what Pass 3c §{section} specifies
  - DO NOT touch frontend except for E2E test files
  - DO NOT modify architecture documents
  - DO NOT skip verification protocol items
  - DO NOT delete legacy file until cutover is verified
  - {deliverable-specific anti-patterns}

=========================================================================
End of {deliverable_id} prompt
=========================================================================
```

The template is enough to write any of D10, D12, D13, D14, D16, D17 by filling in details from the corresponding Pass 3c section + Section B of this document. The pattern is consistent.

---

## Section E — Engagement Model

The decided engagement model for the implementation phase:

### E.1 Architect-led deliverables

**D9 (foundation):** architect writes the full prompt (Section C above), reviews the report, signs off.

**D11 (senior_engineer + sandbox):** architect writes the full prompt when D10 signs off. The sandbox infrastructure decision goes beyond Pass 3d's "start with E2B" — needs an architectural call-and-defer based on operational signal at that point.

**D15 (curriculum graph + content_ingestion):** architect writes the full prompt when D14 signs off. Most complex remaining deliverable; architect attention is high-leverage.

For these three deliverables, the architect remains available to answer mid-implementation architectural questions.

### E.2 Founder-led deliverables

**D10, D12, D13, D14, D16, D17:** founder writes the prompt using:

- The corresponding Pass 3c specification (e.g., D10 → Pass 3c E1)
- The template in Section D above
- Section B of this document (deliverable-specific scope, success criteria, risks)

For these six, the architect is **available on demand** but not by default. Specifically: founder initiates an architecture session if:

- A genuine architectural question arises (something the docs don't answer clearly)
- A spec in Pass 3c-3d turns out to have a gap that requires a decision
- Claude Code's report reveals something concerning that needs interpretation
- The founder wants a sanity check before signing off

The architect does NOT need to be involved in:

- Routine sign-off review (founder reviews against the spec)
- Mechanical issues (test failures, dependency problems)
- Cosmetic decisions (how to format a log line, etc.)

### E.3 Continuity considerations

If the architect Claude is unavailable for a session (context limit, cost, your preference), starting a fresh session is fine. Provide the new session with:

1. The pre-compaction summary from this conversation (already exists)
2. A pointer to the architecture docs in the repo
3. The specific deliverable in question

The architecture docs are detailed enough that a fresh Claude can pick up reasoning from cold.

### E.4 The honest accounting

This engagement has produced:

- Pass 1 + Pass 2 (audits)
- Pass 3a + Addendum (agent inventory)
- Track 1-7 (parallel hardening workstream, real code changes)
- Pass 3b through 3j (architecture documents)
- Pass 3k/3l (this synthesis)

Total architectural artifacts: ~50,000 lines of design documentation across 12 architecture files. The implementation that derives from them is bounded and largely mechanical.

If you want to pause the architecture engagement here and execute D9-D17 with periodic check-ins per the modified Option 3, you have everything you need.

---

## Section F — Closing

The architecture is complete.

Earlier passes asked questions:
- Pass 1: what does the codebase actually contain?
- Pass 2: do agents coordinate?
- Pass 3a: which agents survive?
- Pass 3b: how does coordination work?
- Pass 3c: how does each agent migrate?
- Pass 3d: what tools do they use?
- Pass 3e: how do concepts relate?
- Pass 3f: how is access enforced?
- Pass 3g: how is safety preserved?
- Pass 3h: how does the platform reach out?
- Pass 3i: will it run reliably and affordably?
- Pass 3j: what's the cleanup story?

Each got an answer with implementation contracts. The implementation is now a sequenced, scoped, executable plan.

The platform you're building — AICareerOS, a learning OS for engineers transitioning into senior GenAI roles — has the architecture to support 1,000 students at production grade with explicit upgrade paths to 10,000. The foundation is correct. The remaining work is execution.

D9 starts with the prompt in Section C. The rest follows the templates. The architect is available on the calls explicitly delegated to them; otherwise the docs and the templates are the source of truth.

Good luck.
