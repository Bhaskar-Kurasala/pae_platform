---
title: Pass 3a Addendum — Agent Inventory v2 (Corrected)
status: Final — this supersedes pass-3a-agent-inventory.md as the canonical roster
date: After D1–D8 delivery log was shared with the architect
authored_by: Architect Claude (Opus 4.7)
purpose: Correct the Pass 3a agent inventory after discovering that 4 of 7 proposed "new infrastructure agents" were already implemented as primitives in D1–D8.
supersedes: docs/architecture/pass-3a-agent-inventory.md
superseded_by: nothing — this is the canonical roster
---

# Pass 3a Addendum — Agent Inventory v2 (Corrected)

> This document is the canonical agent roster for AICareerOS. It supersedes Pass 3a's count of 24 agents. The corrected count is 16. The reduction is because 4 of the 7 proposed "new infrastructure agents" turned out to already exist as primitives (D1–D8 work), and the D8 Learning Coach consolidation absorbed 5 legacy agents instead of the partial absorption Pass 3a had proposed.

> Verdicts about which legacy agents to retire, merge, or rewrite (Pass 3a Part 1) REMAIN VALID and are not restated here in full — read Pass 3a alongside this document.

---

# PASS 3a ADDENDUM — Agent Inventory v2 (Corrected)

**Why this addendum exists:** Pass 3a was drafted without knowledge of D1–D8. Several decisions are now obsolete. This document corrects the roster with full knowledge of the foundation that exists.

## What changes

### Five of my "current agents" are being consolidated into Learning Coach (D8)

The other Claude's D8 plan explicitly states: `example_learning_coach` replaces socratic_tutor, student_buddy, adaptive_path, spaced_repetition, knowledge_graph.

This is a **broader merge than I proposed in Pass 3a.** I had:
- socratic_tutor as standalone (with student_buddy folded in as mode)
- adaptive_path as standalone rewrite
- spaced_repetition as standalone keep
- knowledge_graph replaced by my proposed `memory_curator`

The D8 approach is more ambitious: **one super-agent for the full learning experience.** This is defensible — these five agents all serve the "help the student learn what they need to learn next" workflow, and a single agent with mode-aware behavior + memory + tools is cleaner than five coordinating agents.

**My reconciliation: accept the D8 consolidation.** Learning Coach is one super-agent. It internally handles Socratic questioning, direct explanation, brief answers, learning path adaptation, and spaced repetition prompts as modes/tools. This is the right call.

**One concern I want to raise:** super-agents can become god objects. Learning Coach must have very clear internal structure (modes as separate methods, tools for each function) or it becomes unmaintainable. I'll watch this when I review D8 after it ships.

### Three of my "new agents" are not agents — they're primitives

I proposed:
- `memory_curator` → already implemented as `MemoryStore` (D2) + `decay()` task. **Retired from agent roster.**
- `safety_guardian` → mostly covered by Critic (D5) + webhook signature verification (D6). **Reduced scope** — still need an input-side guardian for prompt injection + PII detection, but it's smaller than I framed.
- `escalation_handler` → already implemented as `EscalationLimiter` (D5) + `agent_escalations` writes. **Retired from agent roster.**
- `meta_evaluator` → already implemented as Critic (D5). **Retired from agent roster.**

**Corrected count: I was proposing 7 new "infrastructure agents." Only 2 are actually still needed as agents** — `supervisor` and `interrupt_agent`. The others are already done as primitives.

### Some of my agents need to be migrated to `AgenticBaseAgent`, not just "rewritten"

The other Claude's D7 created `AgenticBaseAgent`. Every agent that survives the cleanup needs to extend `AgenticBaseAgent`, not the old `BaseAgent`. This is more concrete than "rewrite" — it's a specific migration with specific opt-in flags (`uses_memory`, `uses_tools`, `uses_inter_agent`, `uses_self_eval`, `uses_proactive`).

---

## Corrected final roster (post-D8)

### Group A: Tutoring & Learning (1 super-agent, was 4)
1. **Learning Coach** — the D8 super-agent. Replaces socratic_tutor, student_buddy, adaptive_path, spaced_repetition, knowledge_graph. **Already in flight as D8.**

### Group B: Content Generation (1, was 2)
2. **mcq_factory** — keep, migrate to `AgenticBaseAgent`. `uses_tools=True` (curriculum graph queries), `uses_memory=False` (stateless content generator), `uses_self_eval=False` (output is structured MCQs, not graded).

### Group C: Code & Engineering (3, was 4)
3. **senior_engineer** — merged from code_review + senior_engineer + coding_assistant (per Pass 3a). Migrate to `AgenticBaseAgent`. All flags ON except `uses_proactive`.
4. **project_evaluator** — keep, migrate to `AgenticBaseAgent`. All flags ON for capstone evaluation.
5. **practice_curator** (NEW) — generates personalized practice exercises. `AgenticBaseAgent` with all flags ON.

### Group D: Career Services (4)
6. **career_coach** — migrate to `AgenticBaseAgent`. All flags ON.
7. **study_planner** (NEW) — tactical weekly/daily planning. `AgenticBaseAgent` with `uses_proactive=True` (nightly check-ins on plan adherence).
8. **resume_reviewer** — migrate. All flags ON.
9. **tailored_resume** — migrate. `uses_inter_agent=True` to call resume_reviewer.

### Group E: Interview (1)
10. **mock_interview** — migrate. All flags ON. Reads prior session memory.

### Group F: Content Pipeline (1, was 3)
11. **content_ingestion** — keep (curriculum_mapper merged in per Pass 3a). Migrate to `AgenticBaseAgent`. `uses_proactive=True` (webhook-triggered) + `uses_tools=True` (YouTube API, GitHub crawl).

### Group G: Engagement (1)
12. **progress_report** — migrate. `uses_proactive=True` (Celery-driven weekly), `uses_inter_agent=True` (pulls from other agents' memories).

### Group H: Portfolio (1)
13. **portfolio_builder** — migrate. All flags ON.

### Group I: Operations (1)
14. **billing_support** — migrate. `uses_memory=True` (knows order history), `uses_tools=True` (entitlements lookup).

### Group J: OS Infrastructure (2 NEW agents, was 7)
15. **supervisor** (NEW) — sits on top of `call_agent` (D4). Routes student requests, decides chains, manages handoffs. **Replaces the current MOA.**
16. **interrupt_agent** (NEW) — `@proactive(cron=...)` agent. Reads `student_risk_signals`, decides on outreach, dispatches via `student_inbox` + email.

### What got retired/replaced from Pass 3a (unchanged)
- `cover_letter` — RETIRED (no consumer, low-value in 2026 GenAI hiring).
- `job_match` — RETIRED (was a stub with TODO in public UI).
- `peer_matching` — RETIRED (no critical mass at 1k users).
- `deep_capturer` — RETIRED (function absorbed into progress_report).
- `community_celebrator` — RETIRED (proactive celebration → interrupt_agent; reactive celebration → supervisor tone).
- `disrupt_prevention` — REPLACED by interrupt_agent.

---

## Corrected final count: 16 agents

Down from 26 current. Down from Pass 3a's proposal of 24. The reduction is because:
- D8's Learning Coach consolidation is more aggressive than Pass 3a proposed
- 4 of the "new infrastructure agents" turned out to be primitives, not agents

This is a leaner roster. Every agent has a clear role, a clear consumer, and a clear set of primitives it uses.

---

## What's NOT covered by D1–D8 and still needs design

Forward-looking work, scoped into future passes:

| Pass | Title | Why it's needed |
|---|---|---|
| **3b** | The Supervisor + new orchestrator | Replaces MOA. Sits on top of `call_agent`. Decides routing and chains. Single most important new agent. |
| **3c** | Agent migration playbook | How to take each of the 14 remaining agents and migrate them to `AgenticBaseAgent`. Per-agent migration recipes. |
| **3d** | Tool implementations | The 11 D3 stubs need real bodies. Plus likely 10–15 more tools (curriculum graph queries, student state queries, code execution sandbox). MCP server design for external services. |
| **3e** | Curriculum knowledge graph + GraphRAG | The hybrid memory strategy. Build the curriculum graph from ingested content. |
| **3f** | Entitlement enforcement layer | The Pass 2 H1 finding. All agent endpoints need to check `course_entitlements` before invocation. |
| **3g** | Safety beyond the critic | Input-side prompt injection scanning, PII detection in outputs, content moderation, cost ceiling per student per day. |
| **3h** | Interrupt agent + proactive engagement loop | Wire `student_risk_signals` to interventions via `student_inbox`. |
| **3i** | Scale + observability + cost model | What 1k students means concretely. |
| **3j** | Naming sweep + cleanup | AICareerOS canonical naming. Remove dead code. |
| **3k** | AGENTIC_OS.md (delivered as Track 3 of parallel work) | Architecture doc. |
| **3l** | Implementation roadmap | Sequence the above into deliverables D9, D10, D11... |
