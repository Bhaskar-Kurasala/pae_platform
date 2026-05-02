---
title: Pass 3a — Agent Inventory v2
status: Superseded by Pass 3a Addendum (after D8 reconciliation)
date: After Pass 2, before D8 delivery log was shared
authored_by: Architect Claude (Opus 4.7)
purpose: Establish the canonical agent roster for AICareerOS. Every current agent reviewed individually with a verdict. Gaps in the OS identified and filled with proposed new agents.
supersedes: nothing
superseded_by: docs/architecture/pass-3a-addendum-after-d8.md (this file's roster of 24 was revised to 16 after the D1–D8 work was discovered)
---

# Pass 3a — Agent Inventory v2

> ⚠️ This document is SUPERSEDED. After it was written, a parallel build effort (D1–D8 deliverables) was discovered that had already implemented several primitives this document proposed as agents. The canonical roster is now defined by the Pass 3a Addendum. This document is preserved for decision history.

> Read this together with the Addendum. Decisions in this document about which legacy agents to retire, merge, or rewrite REMAIN VALID. The Addendum corrects the count of new infrastructure agents and accepts a broader Learning Coach consolidation than this document originally proposed.

---

# PASS 3a — AGENT INVENTORY v2

**Purpose:** Establish the canonical agent roster for AICareerOS. Every current agent reviewed individually with a verdict. Gaps in the OS identified and filled with proposed new agents. This document is the agent contract for everything that follows.

**Methodology:** For each current agent I use the Pass 1 + Pass 2 evidence — what file it lives in, what model it uses, what UI consumes it, what it actually does in code, what it doesn't do that it claims to. Verdict is one of: KEEP, REWRITE, MERGE, SPLIT, RETIRE, REPLACE. Each verdict has confidence: HIGH (evidence is conclusive) / MEDIUM (judgment call I'd defend but you might override) / LOW (I'm guessing about product intent and need your input).

**Scope reminder:** All-agents-gated by course entitlement. Frontend frozen. Quality > timeline. Target: 1,000 students, production grade.

---

## Part 1: The 26 Current Agents — Reviews

### Group A: Tutoring & Learning (5 agents)

#### 1. `socratic_tutor`
**Today:** Sonnet-4-6. Asks Socratic questions, never gives direct answers. Prompt claims access to lesson and progress; gets neither. Has a stub `search_course_content` tool that returns hardcoded RAG-shaped string about RAG. Consumer: chat UI default agent, hit via `/agents/stream` (raw fetch from frontend chat).
**Wrong with it:** Prompt lies (claims access it doesn't have). RAG tool is a stub. No memory of past sessions. Score 0.9 if response contains "?" — naive evaluation.
**Verdict:** **REWRITE.** HIGH confidence.
**Why:** Socratic tutoring is the heart of the OS. The role is right. The implementation is wrong on every axis. Post-rewrite: real curriculum-graph-aware retrieval, real student-state injection (knows last 3 quiz failures, current lesson, mastery state), structured handoff to specialist agents when student wants direct answer ("escalate to student_buddy for a TLDR"). Becomes the canonical chat-mode agent.

#### 2. `student_buddy`
**Today:** Sonnet-4-6. "Short focused explanations." TLDR / ELI5 mode. Consumer: keyword-routed via MOA when student types "tldr / eli5 / brief / quick."
**Wrong with it:** Sonnet-4-6 is overkill for this. No memory. Indistinguishable from "ask socratic_tutor for a brief answer."
**Verdict:** **MERGE into socratic_tutor as a mode.** MEDIUM confidence.
**Why:** "Give me a Socratic question" and "give me a quick answer" are two modes of the same conversation, not two agents. Student doesn't think of them as different products. The supervisor (Pass 3c) decides mode based on user intent + memory ("this student is frustrated, switch to direct-answer mode"). One less agent, sharper UX. If you disagree because you want explicitly different chat modes in the UI, push back — this is reversible.

#### 3. `adaptive_quiz`
**Today:** Sonnet-4-6. Adaptive MCQ quizzing. Consumer: keyword-routed in MOA, also probably called from quiz UI.
**Wrong with it:** "Adaptive" is doing heavy lifting in the name — verify whether it actually adapts based on prior performance, or just generates new MCQs each call (Pass 2 evidence suggests the latter — no DB reads).
**Verdict:** **REWRITE.** HIGH confidence.
**Why:** Adaptive quizzing requires `user_skill_states` reads (which agent doesn't do today) and `mcq_bank` writes for spaced repetition. Real version uses the curriculum graph to pick concepts at the edge of student mastery. Post-rewrite this becomes a genuinely capable agent. If we don't rewrite, it's just `mcq_factory` with a different prompt.

#### 4. `mcq_factory`
**Today:** Per AGENTS.md generates 5 MCQs per call. Pre-generation pipeline via Celery (`quiz_pregenerate.py`). Consumer: `/chat/quiz` endpoint when student requests quiz on a chat message.
**Wrong with it:** Stateless. Doesn't know what MCQs already exist for this concept, doesn't know which the student already saw.
**Verdict:** **KEEP, light rewrite.** HIGH confidence.
**Why:** This is genuinely a content-generation worker, not a student-facing agent. It has a clear job (generate N MCQs from given content) and a clear consumer (the pre-generation pipeline + on-demand quiz). Light rewrite: dedupe against existing `mcq_bank` for the same concept; tag generated MCQs with concept IDs from the curriculum graph. Keep model selection — Haiku-4-5 if not already.

#### 5. `spaced_repetition`
**Today:** Haiku-4-5. SM-2 algorithm + LLM explanations. Consumer: keyword-routed, also `weekly-review-quiz` Celery job.
**Wrong with it:** Reads `srs_cards` (good — it's one of the few agents that touches a long-term table per Pass 2). Otherwise functional.
**Verdict:** **KEEP.** HIGH confidence.
**Why:** Clear scope, real algorithm, real DB integration, sensible model choice. One of the healthiest agents in the inventory. Light improvements during memory wiring (write back card-difficulty signals to the student model).

---

### Group B: Code & Engineering Review (4 agents — major consolidation needed)

#### 6. `code_review`
**Today:** Sonnet-4-6. 5-dimension rubric, 0–100 score, JSON output. Substring checks (`print(`, `import *`) + shells out to `ruff`. Consumer: not clearly invoked from UI — Pass 1/2 didn't trace it to a specific frontend page.
**Wrong with it:** Substring static analysis is 2022. JSON via regex extraction. No memory of student's prior submissions.

#### 7. `senior_engineer`
**Today:** Sonnet-4-6. PR-style review with verdict (approve/request_changes/comment), severity-scored comments. Consumer: `/practice/review` and `/senior-review` endpoints, called from practice page.
**Wrong with it:** Custom JSON extractor with brace-finding. No memory. Doesn't know the student's prior code, prior reviews, recurring mistakes.

#### 8. `coding_assistant`
**Today:** Sonnet-4-6. "PR-style review for student code." Consumer: keyword-routed (debug, fix my code, pr review, coding help).
**Wrong with it:** Almost word-for-word duplicate of senior_engineer's job. Different file, different prompt, same role.

**Verdict for #6, #7, #8: MERGE all three into one agent: `senior_engineer`.** HIGH confidence.

**Why:** Three agents doing the same job is the clearest finding in the entire audit. They differ in output format (rubric score vs. PR verdict vs. chat reply) but that's a *mode* of one agent, not three agents. The merged `senior_engineer` accepts a `mode` parameter (`pr_review` / `chat_help` / `rubric_score`) and adjusts output structure accordingly. Tools: real static analysis (ruff, mypy, optional language servers via subprocess), real test execution in sandbox, prior-submission lookup. Reads from a new `student_code_history` table (Pass 3i) so it knows "this student keeps writing bare except clauses, I've mentioned this twice already." This is a flagship OS-grade agent.

#### 9. `project_evaluator`
**Today:** Sonnet-4-6. Capstone evaluator with rubric. Consumer: studio page redirects to practice with `mode=capstone`, hits `/practice/review`.
**Wrong with it:** Project-level evaluation is meaningfully different from line-level code review (architecture, completeness, evidence of learning, demo quality). Worth keeping separate.
**Verdict:** **KEEP, rewrite.** HIGH confidence.
**Why:** Capstone evaluation is a high-stakes, low-frequency event with different criteria than "review my code." Different prompt, different rubric, different output (often a written narrative + score, not a PR verdict). Post-rewrite: pulls full project context from a new `capstone_submissions` table, references the course's published rubric, writes a structured evaluation that becomes a portfolio artifact. Distinct enough from senior_engineer to justify its own agent.

---

### Group C: Career Services (5 agents)

#### 10. `career_coach`
**Today:** Sonnet-4-6. 90-day GenAI career action plans. Consumer: career page, also keyword-routed (career plan, become ai engineer, etc.).
**Wrong with it:** No knowledge of the student's actual progress, mastery state, completed projects. Plans are generic.
**Verdict:** **REWRITE.** HIGH confidence.
**Why:** Career coaching without student context is fortune-cookie advice. Post-rewrite: reads from `user_skill_states`, `student_misconceptions`, `growth_snapshots`, `srs_cards` due cards, current course progress. Outputs personalized 90-day plans grounded in *this student's* actual gaps. Coordinates with `resume_reviewer` and `mock_interview` to schedule supporting activities.

#### 11. `resume_reviewer`
**Today:** Sonnet-4-6. Scored, structured resume review. Consumer: `/career/resume` GET endpoint.
**Wrong with it:** No knowledge of the student's actual portfolio (capstone projects, GitHub commits) — reviews resume in isolation.
**Verdict:** **REWRITE.** HIGH confidence.
**Why:** Resume review is more useful when the agent knows what's true vs. embellished. Post-rewrite: cross-references resume claims against student's `capstone_submissions`, `exercise_submissions`, `growth_snapshots`. Flags claims unsupported by evidence. Suggests additions based on real accomplishments the student undersold.

#### 12. `tailored_resume`
**Today:** Sonnet-4-6. JD-tailored, ATS-safe resumes. Consumer: `/career/resume/regenerate`.
**Wrong with it:** Reasonable scope. Prompt self-identifies as "CareerForge's tailoring agent" — naming sweep target.
**Verdict:** **KEEP, light rewrite.** MEDIUM confidence.
**Why:** Genuinely different job from resume_reviewer (generates new resume vs. critiques existing). Light rewrite for memory + naming. Consider whether this should be a *tool* of resume_reviewer rather than a separate agent — but I think the JD-tailoring task is meaty enough to warrant its own prompt and structured output. Tentatively standalone.

#### 13. `cover_letter`
**Today:** Sonnet-4-6. 250-word cover letter. Consumer: **none found in Pass 1/2.** Not in MOA classifier, not in keyword map, no UI route traced.
**Wrong with it:** No consumer. Built and forgotten, or built for a future feature.
**Verdict:** **RETIRE.** MEDIUM confidence.
**Why:** No UI invokes it. No service invokes it. If cover letters are part of the product vision, they should be a *mode* of `tailored_resume` or a *tool* the career_coach can invoke — not a standalone agent. **Push back if cover letters are a planned feature you want surfaced.** If yes, I'll merge it as a mode of tailored_resume rather than a standalone agent.

#### 14. `job_match`
**Today:** Sonnet-4-6. "Skill→job matching (stub)." TODO in code: "connect real job board APIs (LinkedIn, Greenhouse, Lever)." Public agents grid description in UI literally says "TODO: Adzuna / LinkedIn integration."
**Wrong with it:** It's a stub. Pass 2 found the TODO is *visible in the public UI*. Shipping unfinished features into the marketing surface.
**Verdict:** **RETIRE for Launch v1, REPLACE with a real implementation when you commit to a job-board integration.** HIGH confidence.
**Why:** A stub agent with a UI label that says "TODO" is worse than no agent at all — it advertises that the platform is incomplete. Either commit to the integration (Adzuna is the cheapest legitimate option for a job board API; LinkedIn requires partnership; Greenhouse/Lever are employer-side) and I'll design the real agent in Pass 3d, or remove it from the surface and the registry. **Push back with a job-board commitment if you want this kept.**

---

### Group D: Interview Preparation (1 agent)

#### 15. `mock_interview`
**Today:** Sonnet-4-6. System-design mock interviews. Consumer: `/interview/start`, `/interview/sessions/*`. Uses Redis with 2h TTL for session state. Has v1, v2, v3 service files (technical debt).
**Wrong with it:** No memory across sessions. Doesn't know which questions student already practiced. Doesn't escalate weaknesses to `career_coach` for follow-up.
**Verdict:** **KEEP, rewrite.** HIGH confidence.
**Why:** Mock interview is a flagship product feature. Real version: reads prior session history from a new `interview_sessions` table (long-term, not 2h Redis). Tracks weaknesses across sessions. Hands off to `senior_engineer` if student fails on coding rounds, to `career_coach` if interview reveals career-direction confusion. Sandbox for code execution during coding interview rounds. Multiple interview types (system design, coding, behavioral, take-home) as modes of one agent. Cleanup: delete interview_service.py v1+v2, keep v3 as canonical.

---

### Group E: Content & Curriculum (3 agents)

#### 16. `content_ingestion`
**Today:** Sonnet-4-6. Ingest GitHub/YouTube/free-text → metadata + concepts. TODO: "Phase 6: Wire YouTube Data API v3 for real transcript ingestion." Consumer: `/webhooks/github`.
**Wrong with it:** YouTube transcript ingestion is stubbed. Otherwise it's the entry point for new content into the platform.
**Verdict:** **KEEP, complete the stubs.** HIGH confidence.
**Why:** Critical infrastructure. The whole "creator ingests content, agents process it" loop depends on this. Post-rewrite: real YouTube Data API + transcript fetching, GitHub repo crawling with file selection, free-text chunking. Output feeds the curriculum knowledge graph (Pass 3b — GraphRAG layer). This becomes one of the most important non-student-facing agents.

#### 17. `curriculum_mapper`
**Today:** Sonnet-4-6. Map ingested content to curriculum.
**Wrong with it:** Consumer not clearly traced. Likely background. Job overlaps with what `content_ingestion` does (concept extraction).
**Verdict:** **MERGE into content_ingestion.** MEDIUM confidence.
**Why:** "Ingest content" and "map content to curriculum concepts" are two phases of one pipeline. Splitting them adds an agent boundary without value. Merged version: ingestion produces (raw content, extracted concepts, mapped curriculum links, prerequisite suggestions) in one structured output. Reduces coordination complexity in the content-processing pipeline.

#### 18. `knowledge_graph`
**Today:** Haiku-4-5. "Update concept mastery map." TODO: "Persist updated_mastery to users.metadata JSONB column."
**Wrong with it:** Persistence is stubbed. Updates exist in agent output but never written to a real table.
**Verdict:** **REPLACE with a memory-curator agent (see Pass 3a Part 2).** HIGH confidence.
**Why:** The current agent's job (update mastery) is real and important, but it's the wrong abstraction. We need a broader agent that maintains the *student's memory bank* — mastery is one of many things stored. The replacement (proposed in Part 2) handles mastery updates, misconception tracking, knowledge graph student-overlay updates, and memory consolidation. Current `knowledge_graph` agent gets retired, its job absorbed by `memory_curator`.

---

### Group F: Engagement & Retention (4 agents)

#### 19. `community_celebrator`
**Today:** Sonnet-4-6. Celebration messages for milestones. Consumer: keyword-routed (celebrate, i finished, milestone achieved).
**Wrong with it:** Reactive only — student has to type "I finished X." Sonnet-4-6 is overkill for "write a celebration message."
**Verdict:** **RETIRE as standalone, ABSORB into supervisor + new `interrupt_agent`.** MEDIUM confidence.
**Why:** Celebration is a *behavior of the OS*, not an agent. When risk-scoring detects a positive trajectory or completion event, the proactive layer (Pass 3e) sends a celebration via the new `interrupt_agent` with appropriate tone — no separate agent needed. If a student types "I just passed!", supervisor recognizes the moment and routes the response with celebration tone. **Push back if you want a discrete "celebrator" surface in the UI.**

#### 20. `disrupt_prevention`
**Today:** Sonnet-4-6. Detect disengaged students + re-engage. Consumer: keyword-routed (re-engage, churn risk, win back). Mostly background-job paired (inactivity-sweep logs flags but doesn't write to a table the agent reads).
**Wrong with it:** Pass 2 confirmed: agent doesn't read `student_risk_signals` even though risk-scoring writes to it nightly. Closed loop is broken.
**Verdict:** **REPLACE with `interrupt_agent` (Part 2).** HIGH confidence.
**Why:** "Disrupt prevention" framed the agent as reactive (student types "I'm thinking of quitting"). Real OS behavior is proactive: the system *initiates* outreach based on risk signals. The replacement reads `student_risk_signals` + recent activity + memory bank, decides whether to interrupt, what to say, and through which channel (in-app DM, email via outreach_automation, push notification). This becomes the central proactive engagement agent.

#### 21. `progress_report`
**Today:** Sonnet-4-6. Weekly human-readable progress reports. Consumer: `weekly-letters` Celery job.
**Wrong with it:** Pass 2 found this is the *one* agent that already gets long-term data injected (growth_snapshots → context). It works, in a narrow way.
**Verdict:** **KEEP, light rewrite.** HIGH confidence.
**Why:** Genuinely functional. Light rewrite: also pull from `student_risk_signals`, `srs_cards` due, recent code review feedback, mock interview scores. Becomes a richer weekly summary. Continues as Celery-driven, output goes to `notification` table + email.

#### 22. `peer_matching`
**Today:** Sonnet-4-6. Match students with study partners. Consumer: keyword-routed.
**Wrong with it:** Probably hard to actually deliver on at 1,000 students with no critical mass yet. No clear evidence of an underlying matching algorithm in code.
**Verdict:** **RETIRE for now.** LOW confidence.
**Why:** Peer matching needs (a) enough users to match, (b) a real matching engine (skills overlap + timezone + commitment level + complementary gaps), (c) a UI for accepting/rejecting matches, and (d) communication infrastructure between peers. None of this exists end-to-end. At launch with low user count, peer matching produces "no matches found" most of the time, which is a worse UX than not offering it. **Strongly push back if peer matching is a strategic differentiator** — if so, I'll design it properly in Pass 3, but it's a 2–3 month feature on its own.

---

### Group G: Documentation & Portfolio (3 agents)

#### 23. `portfolio_builder`
**Today:** Sonnet-4-6. Markdown portfolio entries. Consumer: keyword-routed (portfolio, showcase).
**Wrong with it:** No connection to actual portfolio data — capstones, exercises, GitHub. Generates generic markdown.
**Verdict:** **REWRITE.** MEDIUM confidence.
**Why:** Portfolio building is meaningful when the agent has real artifacts to draw from. Post-rewrite: reads `capstone_submissions`, top-rated `exercise_submissions`, GitHub repo metadata, course completion certificates. Generates portfolio entries grounded in real evidence. Could become a tool of `career_coach` rather than standalone — but the discrete "build my portfolio" student moment justifies its own agent. Marginal call.

#### 24. `deep_capturer`
**Today:** Sonnet-4-6. "Weekly synthesis with sticky metaphors." Consumer: not clearly traced.
**Wrong with it:** Vague purpose. "Sticky metaphors" suggests this generates memorable summaries of weekly learning, but the consumer isn't clear and it overlaps with progress_report's territory.
**Verdict:** **RETIRE.** LOW confidence — I need your input.
**Why:** Without a clear consumer, I can't justify keeping it. If "deep_capturer" was a planned feature for memorable weekly insights (separate from progress_report's "here's what you did"), tell me what the product moment is and I'll either keep it with rewrite, or absorb the function into `progress_report`. Default is retire.

#### 25. `adaptive_path`
**Today:** Sonnet-4-6. Adjusts learning path from quiz performance + skill gaps. Consumer: keyword-routed (learning path, what should i study, study plan).
**Wrong with it:** Pass 2 confirmed it doesn't read `user_skill_states` — so the "from quiz performance + skill gaps" part is a lie in the prompt.
**Verdict:** **REWRITE.** HIGH confidence.
**Why:** Adaptive path generation is core to personalization. Real version reads mastery state, misconceptions, completion history, course catalog, curriculum graph. Outputs concrete next steps tied to actual lessons/exercises. Coordinates with `career_coach` (long-term plans) and `socratic_tutor` (in-the-moment redirects). One of the most important agents post-rewrite.

---

### Group H: Operations (1 agent)

#### 26. `billing_support`
**Today:** Haiku-4-5. Billing/subscription Q&A; redirects refunds to support@pae.dev. Consumer: keyword-routed.
**Wrong with it:** Hardcoded "pae.dev" support email — naming sweep target. Otherwise reasonable.
**Verdict:** **KEEP, light rewrite.** HIGH confidence.
**Why:** Clear job, right model (Haiku for cost), real consumer. Light rewrite: read student's actual `course_entitlements` + `orders` + `refunds` to give grounded answers ("you bought X on date Y, here's your status") rather than generic FAQ. Naming sweep. Stays standalone.

---

## Part 2: Proposed New Agents

The OS vision requires capabilities that don't exist anywhere in the current 26 agents. Each proposal below has a specific role no existing agent fills, and a clear product moment it serves.

### 27. `supervisor` (NEW)

**Role:** The orchestrator that routes student requests to specialist agents, manages handoffs between agents, decides when one agent's output should trigger another, and maintains the conversation thread across multi-agent flows.

**Why it's needed:** The current MOA is a 2-node graph (`classify_intent → run_agent → END`). It picks one agent per request and that's it. The OS vision requires *coordination* — a student asking "review my code and help me prep for an interview about it" should hit `senior_engineer` first, get the review, then hand off to `mock_interview` with the review's findings as context. No current agent does this.

**Model:** Haiku-4-5 (routing should be cheap and fast).

**Inputs:** Student request, current student state from memory bank, conversation thread, available agents.

**Outputs:** Either (a) route to single agent with constructed context, (b) chain plan: agent A → agent B → agent C with state-passing rules, (c) decline with reason if request is out of scope.

**Tools:** `read_student_state`, `read_conversation_thread`, `list_available_agents`, `dispatch_agent` (calls another agent and waits), `dispatch_chain` (executes a multi-agent plan).

**Replaces:** The MOA classifier in `moa.py`. Keyword routing stays as a fast-path optimization but becomes a hint to the supervisor, not a final decision.

**Confidence:** HIGH. This is the single most important new agent. Without it, "agents that coordinate" doesn't happen.

### 28. `memory_curator` (NEW)

**Role:** Maintains the student's memory bank. After every significant student event (agent interaction, quiz completion, code submission, lesson completion, capstone milestone), this agent decides what to write to long-term memory, what to update, what to consolidate, and what to forget.

**Why it's needed:** Pass 2 confirmed `agent_memory` table exists with HNSW vector index, but nothing writes to it. The naive approach is "every agent writes its own memories" — that creates a noisy, redundant memory bank. The OS approach is a dedicated curator that watches all agent outputs + system events and decides what's memory-worthy.

**Model:** Haiku-4-5 for routine consolidation; Sonnet-4-6 for weekly deep consolidation.

**Inputs:** Stream of `agent_actions` rows (post-write triggers), system events (lesson completed, quiz scored, code submitted), student state.

**Outputs:** Writes to `agent_memory` (new memories), updates to `user_skill_states` (mastery deltas), updates to `student_misconceptions` (new misconceptions detected), occasional `memory_consolidation` records (weekly summaries).

**Tools:** `write_memory`, `update_mastery`, `record_misconception`, `consolidate_memories` (merge similar memories), `decay_memories` (lower confidence/access_count for stale entries), `embed_text` (for vector index).

**Modes:**
- **Real-time mode:** triggered on each agent_action insert (debounced, batched).
- **Daily consolidation:** Celery job, deduplicates and consolidates the day's memories.
- **Weekly deep consolidation:** Sonnet-4-6 reviews the week's memories per student, extracts themes, writes higher-order memories ("this student consistently struggles with async programming concepts").

**Replaces:** The current `knowledge_graph` agent (which had only mastery-update scope and was stubbed).

**Confidence:** HIGH. Without memory curation, the memory bank becomes either empty (no one writes) or noisy (everyone writes). Curation is the OS pattern.

### 29. `interrupt_agent` (NEW)

**Role:** Decides *when* the OS should proactively reach out to a student, *what* to say, and *through which channel*. This is the proactive nudging layer, currently absent.

**Why it's needed:** Pass 2 confirmed the closed loop is broken — `risk-scoring-nightly` writes `student_risk_signals`, `outreach-automation-nightly` sends emails, but nothing intelligent decides "this specific student needs *this specific* nudge right now via *this specific* channel." Current outreach is rule-based templates. OS-grade is agent-driven.

**Model:** Sonnet-4-6 (this is high-stakes — bad nudges drive students away).

**Inputs:** Student risk signals, recent activity, memory bank (what motivates them, past response to interventions), curriculum graph (where they're stuck), inbox state (don't double-message).

**Outputs:** Either (a) "no action right now," (b) a structured intervention plan: channel (in-app DM / email / push), message, timing, follow-up schedule.

**Tools:** `read_student_full_context`, `check_recent_outreach` (rate-limit interventions), `compose_dm`, `compose_email`, `schedule_followup`, `escalate_to_human` (writes to admin inbox for human review on edge cases).

**Modes:**
- **Risk-triggered:** invoked from risk-scoring job when a signal crosses threshold.
- **Opportunity-triggered:** invoked when student hits a milestone (offer celebration, suggest next step).
- **Stuck-detection:** invoked when a student repeats a failure pattern (offer different agent, different approach).

**Replaces:** The current `disrupt_prevention` agent (which never read the signals it was supposed to act on) and `community_celebrator` (proactive celebration moves here, reactive celebration handled by supervisor tone).

**Confidence:** HIGH. Proactive nudging is in your stated vision. Without this agent, the existing background-job infrastructure (which is genuinely good) doesn't connect to intelligent action.

### 30. `safety_guardian` (NEW)

**Role:** Sits in front of every agent invocation. Inspects user input for prompt injection attempts, jailbreaks, abuse, PII leakage attempts. Inspects every agent output for hallucinated PII, unsafe content, off-topic drift, prompt-injection success markers. Logs incidents.

**Why it's needed:** You explicitly asked for "advanced guardrails, advanced red teaming, prompt injection." Currently zero guardrails exist. At 1,000 students this becomes an incident waiting to happen.

**Model:** Haiku-4-5 + cheap classifier models for fast-path checks.

**Inputs:** Pre-invocation: user input, agent identity, student context. Post-invocation: agent output, tools called.

**Outputs:** Either (a) `allow`, (b) `block_with_reason`, (c) `redact_and_continue`, (d) `escalate_to_human`.

**Tools:** `check_prompt_injection` (regex + LLM classifier), `check_pii` (regex + entity extraction), `check_off_topic`, `check_output_safety`, `log_incident`.

**Architecture:** Wraps `BaseAgent.run()`. Pre-check before execute(), post-check after. Failure modes: fail-closed for high-severity, fail-open with logging for low-severity (don't break the platform on guardian outages).

**Confidence:** HIGH. Production AI systems without guardrails are negligent.

### 31. `meta_evaluator` (NEW)

**Role:** Periodically samples agent outputs and scores them on quality dimensions (was the answer correct, was the tone right, did the agent do its job, did it use memory, did it coordinate properly). Feeds findings into agent improvement.

**Why it's needed:** Currently `BaseAgent.evaluate()` returns a hardcoded 0.8 for most agents. There's no actual quality signal. Without this, the OS has no feedback loop on whether agents are getting better or worse over time.

**Model:** Sonnet-4-6 (evaluation needs strong reasoning).

**Inputs:** Sampled `agent_actions` rows (1–5% sample), full conversation context, expected behaviors per agent.

**Outputs:** Writes to `agent_evaluations` table (which exists from migration 0054, currently dormant — Pass 2). Score + dimension breakdown + rationale.

**Tools:** `fetch_agent_action`, `fetch_conversation_context`, `score_response` (rubric-driven), `flag_for_review`.

**Modes:**
- **Sampling mode:** Celery job, samples N actions per agent per day, scores them.
- **Triggered mode:** student feedback (thumbs down) triggers an immediate evaluation.
- **Regression mode:** runs against a curated test set after agent prompt changes.

**Confidence:** MEDIUM-HIGH. Could be deferred until after launch if needed, but this is what differentiates "agents that work" from "agents that improve." Wires up the dormant `agent_evaluations` table.

### 32. `escalation_handler` (NEW)

**Role:** When an agent fails, refuses, or hits its limits, this agent decides how to handle the escalation — retry with different agent, escalate to human admin, log incident, message the student gracefully.

**Why it's needed:** Currently agent failures throw exceptions and return generic strings ("I couldn't generate a response. Please try again."). At scale, this is a poor UX. The OS should degrade gracefully.

**Model:** Haiku-4-5.

**Inputs:** Failed agent action, error context, student context, available alternatives.

**Outputs:** Plan for recovery — retry with same agent, route to alternative agent, return graceful student-facing message, escalate to admin inbox (`student_inbox` table — dormant, will be wired).

**Tools:** `retry_agent`, `route_to_alternative`, `compose_apology`, `escalate_to_human`.

**Wires up:** The dormant `agent_escalations` table from migration 0054.

**Confidence:** MEDIUM. Could be a service rather than an agent — argument for agent: complex decisions about how to recover require reasoning, not rules. I'll commit to agent.

### 33. `practice_curator` (NEW)

**What it does:** Generates and curates personalized practice exercises matched to the student's current edge of mastery. Not quizzes (that's `adaptive_quiz`). Not capstones (that's `project_evaluator`). The space between — coding exercises, debugging challenges, system-design mini-problems, prompt engineering drills, evaluation rubric exercises.

**Why I missed it the first time:** I assumed `exercises` were static content the platform ships with. Then I remembered — for senior GenAI engineering, the practice surface needs to include things like "here's a broken RAG pipeline, find why retrieval is failing" or "rewrite this prompt to reduce hallucination" — problem types that don't exist in any course curriculum yet because the field is too new. Exercises need to be *generated* against the student's current concept, just like quizzes. Without this, "practice section" stays static and gets stale.

**Inputs:** Student's current concept focus, mastery state, prior exercises completed, common misconception patterns.

**Outputs:** Generated exercise with starter code/scaffold, expected solution shape, evaluation criteria, hints unlock sequence.

**Tools:** `read_curriculum_concept`, `read_student_mastery`, `fetch_canonical_examples`, `generate_exercise`, `validate_solution_shape`.

**Why it earns its place:** Practice volume + variety is one of the strongest predictors of skill acquisition. Static exercise libraries get stale or get gamed. Generated, personalized exercises is a real differentiator. **Confidence: HIGH.**

### 34. `study_planner` (NEW — split from career_coach)

**What it does:** Tactical day-to-day and week-to-week scheduling. "Given the student has 6 hours this week, here's the optimal allocation across new lessons, spaced repetition, capstone work, and interview prep." Negotiates with the student's stated goals and available time.

**Why I missed it the first time:** I had `adaptive_path` (long-term route through the curriculum) and `career_coach` (90-day career plan) but no agent for the *weekly* and *daily* tactical layer. That gap matters because it's exactly where students fall off — they know where they're going, they don't know what to do tonight.

**Distinction from existing agents:**
- `career_coach`: 90-day strategic plan tied to career outcome
- `adaptive_path`: which lessons/concepts in what order, weeks/months scope
- `study_planner`: this week, this evening, in this 30-minute slot

**Inputs:** Student's available time (from `goal_contracts` table — already exists), current course progress, due SRS cards, capstone status, upcoming interview goals, energy/mood signals from recent activity.

**Outputs:** Time-blocked plan for the week + tonight's specific session plan.

**Tools:** `read_student_calendar` (if integrated), `read_goal_contract`, `read_due_cards`, `read_progress`, `propose_time_block`, `commit_plan`, `track_adherence`.

**Why it earns its place:** Without a tactical planner, "personalization" stays abstract. With it, the OS makes a concrete claim every day: "do this, for this long, in this order." That's a felt experience of help, not just a stored plan.

**Confidence: HIGH.**

---

## Part 3: Final Roster Summary (24 agents)

Down from 26 current. 8 retired/merged, 6 new infrastructure + 2 new specialist. Net -2 plus better composition.

### Final agent list, by group

**Tutoring & Learning (4):** socratic_tutor (modes: socratic / direct / brief), adaptive_quiz, mcq_factory, spaced_repetition.

**Code & Engineering (3):** senior_engineer (merged from 3 legacy), project_evaluator, practice_curator (NEW).

**Career Services (4):** career_coach, study_planner (NEW), resume_reviewer, tailored_resume.

**Interview (1):** mock_interview.

**Content (1):** content_ingestion (curriculum_mapper merged in).

**Engagement (1):** progress_report.

**Portfolio & Path (2):** portfolio_builder, adaptive_path.

**Operations (1):** billing_support.

**OS Infrastructure (7 NEW):** supervisor, memory_curator, interrupt_agent, safety_guardian, meta_evaluator, escalation_handler, *(reserved slot)*.

### Retired / merged / replaced

| Original | Disposition |
|---|---|
| student_buddy | MERGED into socratic_tutor as mode |
| code_review | MERGED into senior_engineer |
| coding_assistant | MERGED into senior_engineer |
| cover_letter | RETIRED (no consumer, low-value in 2026 GenAI hiring) |
| job_match | RETIRED (was a stub with TODO in public UI) |
| peer_matching | RETIRED (no critical mass at 1k users) |
| deep_capturer | RETIRED (function absorbed into progress_report) |
| community_celebrator | RETIRED (proactive → interrupt_agent; reactive → supervisor tone) |
| disrupt_prevention | REPLACED by interrupt_agent |
| knowledge_graph | REPLACED by memory_curator |
| curriculum_mapper | MERGED into content_ingestion |
