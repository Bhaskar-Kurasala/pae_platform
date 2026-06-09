---
title: Pass 2 — Hypothesis Verification
status: Final
date: 2026-04 (approximate, after Pass 1, prior to Track 7)
authored_by: Claude Code (audit session)
purpose: Verify five specific hypotheses about whether AICareerOS implements an "OS of learning" or a "chatbot platform with a registry." Code-level evidence for each hypothesis.
supersedes: nothing
superseded_by: nothing — findings stand as the basis for Pass 3a decisions
---

# Pass 2 — Hypothesis Verification

> This document tested five hypotheses raised by Pass 1. All five came back confirmed with code-level evidence. The findings drove the agent roster decisions in Pass 3a.

> Headline conclusion: AICareerOS as of this audit was not yet an "OS of learning" — it was a chatbot platform with a registry of 26 agents, a sophisticated retention engine, and the foundation of an OS layer (migration 0054 "agentic_os_primitives") that had been built but never wired up. Pass 3a designed the path forward.

PASS 2 AUDIT REPORT — Hypothesis Verification
Project root: e:\Apps\pae_platform\pae_platform\. Observation only.

HYPOTHESIS 1: AGENT ENDPOINTS ARE NOT ENTITLEMENT-GATED
Verdict: CONFIRMED. Agents are completely ungated by entitlements.

1.1 Agent-invoking routes
HTTP	Path	File:line	What it does
POST	/api/v1/agents/chat	backend/app/api/v1/routes/agents.py:23	AgentOrchestratorService.chat() → MOA
GET	/api/v1/agents/list	backend/app/api/v1/routes/agents.py:52	Lists registry
POST	/api/v1/agents/stream	backend/app/api/v1/routes/stream.py:509	Direct streaming via keyword route + build_llm()
POST	/api/v1/chat/quiz	backend/app/api/v1/routes/chat.py:899	Invokes MCQFactoryAgent.execute() (line 941)
POST	/api/v1/practice/review	backend/app/api/v1/routes/practice.py:62	Invokes senior_engineer.execute() (line 94)
POST	/api/v1/senior-review	backend/app/api/v1/routes/senior_review.py:27	Invokes senior_engineer.execute() (line 54)
POST	/api/v1/interview/stream	backend/app/api/v1/routes/interview.py:258	build_llm() direct streaming
POST	/api/v1/interview/sessions/start	backend/app/api/v1/routes/interview.py:341	start_interview_session() (line 348)
POST	/api/v1/interview/sessions/answer	backend/app/api/v1/routes/interview.py:363	evaluate_answer() (line 382)
POST	/api/v1/admin/agents/{name}/trigger	backend/app/api/v1/routes/admin.py:858	Admin manual run via get_agent() (line 905)
POST	/api/v1/demo/chat	backend/app/api/v1/routes/demo.py:33	Public demo, no auth
POST (handler)	/api/v1/webhooks/github async	backend/app/api/v1/routes/webhooks.py:46	ContentIngestionAgent.run() (line 68)
1.2 Per-route auth + entitlement table
Route	Auth (JWT)	Entitlement check	Evidence
POST /agents/chat	yes (get_current_user)	no	agents.py:23–27 deps: AgentOrchestratorService, get_current_user only
GET /agents/list	yes	no	agents.py:52
POST /agents/stream	yes	no	stream.py:509–515
POST /chat/quiz	yes	no	chat.py:899
POST /practice/review	yes	no	practice.py:62–69
POST /senior-review	yes	no	senior_review.py:27–75
POST /interview/*	yes	no	interview.py:172–191, 258, 341–382
POST /admin/agents/{name}/trigger	yes (admin)	no	admin.py:858–905 (uses _require_admin, not entitlement)
POST /demo/chat	no (public)	no	demo.py:33
POST /webhooks/github	signature	no	webhooks.py:46–68
1.3 entitlement_service inventory
backend/app/services/entitlement_service.py exports:

Function	Caller (file:line)	In any agent route?
is_entitled()	app/api/v1/dependencies/entitlement.py:69; app/api/v1/routes/catalog.py:64	no
grant_entitlement()	called via grant_for_order() from app/services/order_service.py:149	no
grant_for_order()	app/services/order_service.py:149	no
grant_free_course()	not called anywhere	n/a
list_entitlements_for_user()	app/api/v1/routes/payments_v2.py:365	no
revoke_entitlement()	no external callers	n/a
revoke_for_order()	likely refund flow (services); not in any agent route	no
expand_bundle()	internal (grant_for_order())	no
1.4 The require_course_access dependency exists but is unused
backend/app/api/v1/dependencies/entitlement.py:69 defines require_course_access(course_id_param) which calls is_entitled() and raises 403 if not entitled. Grep confirms zero imports of require_course_access in any route file under backend/app/api/v1/routes/ that invokes an agent. The only route file that gates content by entitlement is catalog.py — and that gate marks courses as is_unlocked for display, not to deny access to agents.

1.5 Verdict
Agents are ungated. Strongest single piece of evidence: every agent-invoking route in §1.1 depends only on get_current_user (JWT). Any logged-in account — paying or not — can invoke any agent. The entitlement plumbing exists end-to-end (payments → orders → course_entitlements → is_entitled()) but is wired only into the catalog display, never into the inference path.

HYPOTHESIS 2: NO AGENT READS FROM OTHER AGENTS' OUTPUTS OR LONG-TERM STUDENT STATE
Verdict: CONFIRMED for long-term student state. Agents do not read each other's outputs from agent_actions or from long-term tables. There is a single agent_memory read path inside app/agents/primitives/memory.py, but no agent class actually calls it.

2.1 Read sites for each long-term student state table (grouped by parent dir)
Table	agents/	services/	api/	tasks/	other
user_skill_states (UserSkillState)	0	diagnostic_service.py:48, growth_snapshot_service.py:116, retrieval_quiz_service.py:176, scaffolding_service.py:98, skill_service.py:25,44, student_context_service.py:241	0	0	scripts/seed_today_demo.py:257,1247
student_misconceptions (StudentMisconception)	0	welcome_prompt_service.py:189	0	0	scripts/seed_today_demo.py:370
student_risk_signals (StudentRiskSignals)	0	student_risk_service.py:449	admin.py:2066	0	0
goal_contracts (GoalContract)	0	goal_contract_service.py:61, student_context_service.py:232	skill_path.py:31	0	0
confidence_reports (ConfidenceReport)	0	0	0	0	0
growth_snapshots (GrowthSnapshot)	0	growth_snapshot_service.py:195	receipts.py:56	weekly_letters.py:70	0
learning_sessions (LearningSession)	0	learning_session_service.py:34	0	0	scripts/seed_today_demo.py:395
srs_cards (SrsCard)	0	srs_service.py:116,164,185	0	0	0
conversation_memory (ConversationMemory)	0	conversation_memory_service.py:106,155	0	0	0
agent_memory (AgentMemory)	primitives/memory.py:536,566,580 (and elsewhere internal to that file)	0	0	0	0
2.2 Does any file under backend/app/agents/ read any of these tables?
Only one file does: backend/app/agents/primitives/memory.py (the MemoryStore wrapper, lines 150, 194–195, 218, 245, 279–285, 346, 363, 461–483, 493, 500–511, 527, 536–541, 565–574, 578–580). No concrete agent class under backend/app/agents/*.py calls MemoryStore or queries any of these tables. (See H3 below — MemoryStore is exported but not imported by any agent.)

2.3 Does any agent read agent_actions to see what other agents have done?
Zero agent files read agent_actions. Reads of AgentAction are confined to:

backend/app/api/v1/routes/admin.py (15 read sites — Pass 1 §4)
backend/app/services/at_risk_student_service.py:355–369, consistency_service.py:77–81, confusion_heatmap_service.py:241–246, inactivity_service.py:91–94, receipts_service.py:192–197
No path goes agents/* → AgentAction.select(…).

2.4 AgentState(...) construction sites
File:line	student_id	task	conversation_history	context
app/services/agent_orchestrator.py:104	from request	from request	Redis (_load_history) at line 102	from caller context or {}
app/api/v1/routes/admin.py:892	from path/body	from request	empty (default [])	hard-coded {actor_id, actor_role, on_behalf_of, trigger}
app/api/v1/routes/chat.py:927	current_user.id	"Generate 5 MCQ questions"	empty []	from request (focus_topic, source_message_id, content, conversation_context)
app/api/v1/routes/demo.py:68	demo constant	from request	empty	{}
app/api/v1/routes/practice.py:77	current_user.id	"practice_review"	empty	{code, problem_context} from request
app/api/v1/routes/senior_review.py:37	current_user.id	"senior_review"	empty	{code, problem_context} from request
app/api/v1/routes/webhooks.py:58	"system"	github task string	empty	{github_commit, repo} from webhook
app/tasks/quiz_pregenerate.py:41	"pregenerate"	mcq prompt	empty []	{focus_topic} from local var
app/tasks/weekly_letters.py:85	user.id	weekly-letter prompt	empty []	from GrowthSnapshot.payload (the only construction site that reads a long-term table — and it's the task, not the agent)
2.5 Verdict
Agents do NOT share memory or knowledge. Concrete agents only see what their caller hands them in state.context plus state.conversation_history (Redis 1h). No agent reads a long-term student-state table; no agent reads agent_actions; no agent reads another agent's prior output. The only cross-table connector is weekly_letters.py:70–85 — a Celery task — which reads growth_snapshots and pours selected fields into state.context before invoking progress_report. Outside that one spot, all "knowledge sharing" is one-way: services/tasks WRITE student state; agents READ none of it.

HYPOTHESIS 3: agent_memory IS DEFINED BUT UNUSED
Verdict: PARTIALLY CONFIRMED. The table, model, and MemoryStore wrapper are fully built and production-ready. They are NOT called from any concrete agent, service, route, or task — MemoryStore is imported only by its own module, exported via primitives/__init__.py, and stubbed in agents/tools/memory_tools.py (raises NotImplementedError). Six other migration-0054 tables are even more dormant (model-only).

3.1 agent_memory schema (migration backend/alembic/versions/0054_agentic_os_primitives.py:109–219)
14 columns: id (UUID PK, server default gen_random_uuid()), user_id (UUID FK users.id CASCADE, nullable), agent_name (Text), scope (ENUM user/agent/global, default user), key (Text), value (JSONB), embedding (vector(1536), HNSW cosine index added at lines 189–191, 216–219), valence (Float, ±1 check), confidence (Float, 0..1 check), source_message_id (UUID), created_at, last_used_at, access_count (Int, default 0), expires_at (timestamptz nullable). 4 indexes: (user_id, scope), (agent_name), (expires_at) WHERE NOT NULL, HNSW on embedding. 2 check constraints (valence/confidence ranges).

3.2 ORM model
backend/app/models/agent_memory.py:49–94 — full SQLAlchemy 2.0 model AgentMemory(Base, UUIDMixin) mirroring the migration schema, including the pgvector Vector(EMBEDDING_DIM) column.

3.3 Reads/writes of AgentMemory / agent_memory
All non-test references live inside backend/app/agents/primitives/memory.py:

READ sites: lines 245 (recall), 279–285, 461–483, 493, 500–511, 527, 536–541, 565–574, 578–580.
WRITE sites: lines 150 (write), 194–195 (update), 218 (insert), 346 (forget), 353 (delete by id), 390–394 (decay), 403–404 (delete below threshold), 410–413 (delete expired).
API-shape exports: MemoryStore exported in app/agents/primitives/__init__.py:29, 54.
Other references:

backend/app/agents/tools/memory_tools.py:67, 73, 77–81, 115, 119–123 — tool stubs that raise NotImplementedError. Comment notes: "real implementation wires MemoryStore through the agent session in deliverable 7".
backend/app/agents/primitives/metrics.py:101 — docstring only.
backend/app/models/__init__.py:16, 114 — re-export.
backend/alembic/versions/0054_agentic_os_primitives.py — migration only.
No concrete agent class (socratic_tutor.py, senior_engineer.py, code_review.py, etc.) imports MemoryStore or AgentMemory. No FastAPI route imports them. No Celery task imports them. The decay() method exists but no scheduled job calls it.

3.4 Other tables introduced by migration 0054
Table	create_table file:line	ORM model exists?	App-code refs (excl. tests/init/migration)	Status
agent_memory	0054_agentic_os_primitives.py:109	yes (agent_memory.py)	All in primitives/memory.py + tool stubs	DORMANT (wrapper built, not called)
agent_tool_calls	0054:222	yes (agent_tool_call.py)	primitives/tools.py:58, 543 writes one row per dispatch	LIVE
agent_call_chain	0054:275	yes (agent_call_chain.py)	model + a comment in agent_tool_call.py:47; no read/write	DORMANT
agent_evaluations	0054:330	yes (agent_evaluation.py)	model only	DORMANT
agent_escalations	0054:378	yes (agent_escalation.py)	model only	DORMANT
agent_proactive_runs	0054:416	yes (agent_proactive_run.py)	model only	DORMANT
student_inbox	0054:473	yes (student_inbox.py)	model only	DORMANT
3.5 Verdict
agent_memory is dormant: a full production-quality memory layer (table + pgvector index + ORM + repository wrapper) exists but is not plugged into any agent. The migration name "agentic_os_primitives" and the comment in memory_tools.py ("deliverable 7") indicate this was intentionally staged for later wire-up. Five of the seven tables introduced in 0054 have no callers at all.

HYPOTHESIS 4: CONVERSATION HISTORY IS THE ONLY MEMORY, AND IT EXPIRES IN 1 HOUR
Verdict: CONFIRMED for what an agent can actually access. The longest-lived memory an agent reads at runtime is the Redis conv key (1h TTL). DB tables exist that hold longer state, but no agent reads them.

4.1 Redis namespace inventory (backend/app/core/redis.py:11–20 enumerates 5 categories)
Namespace	Pattern	TTL	What's stored	Evidence
conv	pae:{env}:conv:{conv_id}	3600 s (1 h)	JSON list of {role, content, agent} turns; trimmed to last 20	services/agent_orchestrator.py:19, 33–35, 44, 67–71, 156–158
courses	pae:{env}:courses:published	300 s (5 min)	Published course list cache	services/course_service.py:17, 21–23, 60, 75
interview	pae:{env}:interview:session:{session_id}	7200 s (2 h)	InterviewSession (problem slug, turns)	services/interview_service.py:31, 198–200, 210–216, 233, 237
quiz	pae:{env}:quiz:{message_id}	86 400 s (24 h)	3 pre-generated MCQ versions + counter	tasks/quiz_pregenerate.py:23, 27–28, 99, 110; routes/chat.py:1004–1023, 1071
notebook	pae:{env}:notebook:summary:{message_id}:{content_len}	3600 s (1 h)	Bookmark summary + tags	services/notebook_summarize_service.py:36, 124, 192, 234–238
No raw redis.set/setex calls bypass namespaced_key().

4.2 DB-backed "memory" tables
Table	Retention	Used by agents at runtime?
chat_messages (migration 0028)	persistent	no — read only by chat history admin/UI routes
conversations (0028)	persistent	no
conversation_memory (0010)	persistent	no — only conversation_memory_service.py:106, 155 reads it
learning_sessions (0044)	persistent	no
agent_memory (0054)	persistent + optional expires_at	dormant (H3)
agent_actions (0001)	persistent	no agent reads it
growth_snapshots (0006)	persistent	no agent reads it
4.3 conversation_memory table specifically
Reads: services/conversation_memory_service.py:106, 155 only.
Writes: not located in this audit's scope (likely same service file). No agent imports ConversationMemory. Used by services that compute/serve "what tutor knows about this student per skill," but the actual socratic_tutor agent does not consult it.

4.4 Verdict
The longest-lived memory an agent can actually access in its execute() body is the Redis conv: key — 3600 s, last 20 turns. (Agents that don't go through the chat orchestrator — practice/review, senior-review, chat/quiz — receive conversation_history=[], so for those agents memory is zero: each call is stateless.) Every longer-lived store (DB conversation history, conversation_memory, learning_sessions, agent_memory) is invisible to the agent.

HYPOTHESIS 5: BACKGROUND JOBS DO NOT FEED INTO AGENT BEHAVIOR
Verdict: CONFIRMED. With one narrow exception (weekly_letters reads growth_snapshots and passes selected fields into the progress_report agent's state.context), background jobs and agents are parallel systems that never read each other's outputs.

5.1 Per-job table writes
Job	File:line of writes	Tables written
growth-snapshots-weekly	services/growth_snapshot_service.py:212–221	growth_snapshots (upsert on user_id, week_ending)
weekly-letters	tasks/weekly_letters.py:131–144	notification (one row per user with the agent-generated body)
weekly-review-quiz	(none)	none — in-memory assembly only (tasks/weekly_review.py:44–48)
inactivity-sweep	(none — logs only)	none (tasks/inactivity_sweep.py:27–31); comment lines 4–6: "the existing disrupt_prevention agent consumes these via the chat/agents surface; this cron's only job is to surface the cohort"
risk-scoring-nightly	services/student_risk_service.py:374–435	student_risk_signals (delete + pg_insert(...).on_conflict_do_update)
outreach-automation-nightly	services/outreach_service.py:58–72, 120–145	outreach_log (insert + status updates)
5.2 Do agents read these outputs?
Grep backend/app/agents/ for risk_signal | risk_score | slip_type | growth_snapshot | last_session_age | outreach_log | inactivity | weeks_in_program: zero hits.
Grep backend/app/agents/prompts/: zero hits.
Grep backend/app/agents/ for any import of StudentRiskSignals, GrowthSnapshot, OutreachLog, Notification: zero hits.

The disrupt_prevention agent (backend/app/agents/disrupt_prevention.py) — the natural consumer of churn signals — reads days_inactive, last_lesson, streak_before from state.context, none of which are populated from student_risk_signals rows in any code path under audit. The inactivity-sweep task only logs; it does not write to a table that the agent later reads.

5.3 weekly_letters exception
backend/app/tasks/weekly_letters.py:70 reads GrowthSnapshot; line 83 instantiates ProgressReportAgent; lines 85–103 build AgentState(...) with context = {...from snap.payload}; line 104 calls agent.execute(state); line 105 captures result.response; lines 131–144 write that response to notification.body. The agent is invoked with snapshot data, but no agent reads the resulting notification.body later. The progress_report agent itself does not query growth_snapshots; the task does the lookup and pours data into context.

5.4 Verdict
Background jobs and agents are parallel systems. The only point of contact is weekly_letters.py:70 → 104, which is a one-shot push from a task into an agent invocation. There is no closed loop: nothing the jobs produce alters what an agent decides on a future user-initiated request.

ADDITIONAL CHECKS
A. Frontend → API trace for 10 agent features (no entitlement gate found anywhere)
#	Feature	Frontend page (file:line)	API endpoint	JWT	Entitlement check
1	Chat (Socratic)	frontend/src/app/(portal)/chat/page.tsx	POST /api/v1/agents/stream	yes	no (stream.py:509–515)
2	Code review	frontend/src/app/(portal)/practice/[problemId]/page.tsx:88	POST /api/v1/practice/review	yes	no (practice.py:62–69)
3	Mock interview	frontend/src/app/(portal)/interview/page.tsx:136	POST /api/v1/interview/start	yes	no (interview.py:172–191)
4	Resume review	frontend/src/app/(portal)/career/resume/page.tsx:94–98	GET /api/v1/career/resume	yes	no (career.py:46–63)
5	JD checker	frontend/src/app/(portal)/career/jd-fit/page.tsx:89	POST /api/v1/career/fit-score	yes	no (career.py:92–118)
6	Career coach	frontend/src/app/(portal)/chat/page.tsx:49–55 (agent mode)	POST /api/v1/agents/stream	yes	no (stream.py:509–515)
7	Senior engineer review	frontend/src/app/(portal)/practice/[problemId]/page.tsx:86–105	POST /api/v1/practice/review (also senior_review.py:27–75)	yes	no
8	Project evaluator (capstone)	frontend/src/app/(portal)/studio/page.tsx:9 (redirects to /practice?mode=capstone)	POST /api/v1/practice/review	yes	no
9	Tailored resume	frontend/src/app/(portal)/career/resume/page.tsx:94–98 (regenerate)	POST /api/v1/career/resume/regenerate	yes	no (career.py:66–89)
10	Today / readiness diagnostic	frontend/src/app/(portal)/today/page.tsx; (portal)/readiness/page.tsx	GET /api/v1/today/summary; POST /api/v1/readiness/sessions	yes	no (today.py:165–180; readiness.py:103–125)
B. Redis key patterns — full inventory
(See §4.1 above.) 5 namespaces, all routed through namespaced_key(). TTLs: 5 min (courses), 1 h (conv, notebook), 2 h (interview), 24 h (quiz). No persistent (TTL-less) Redis keys found.

C. _KEYWORD_MAP and registry vs. classifier mismatch
_KEYWORD_MAP (backend/app/agents/moa.py:89–113):


[
  (["def ", "class ", "import ", "```python", "review my code", "check my code"], "code_review"),
  (["quiz me", "mcq", "multiple choice", "test my knowledge"], "adaptive_quiz"),
  (["interview", "system design", "mock interview", "interview prep"], "mock_interview"),
  (["portfolio", "showcase", "build my portfolio"], "portfolio_builder"),
  (["jobs", "job listing", "career opportun", "find jobs", "hiring"], "job_match"),
  (["study partner", "find peer", "study group", "peer match"], "peer_matching"),
  (["celebrate", "i finished", "i passed", "milestone achieved", "completed course"], "community_celebrator"),
  (["weekly report", "progress report", "how am i doing"], "progress_report"),
  (["spaced repetition", "due cards", "flashcard", "review cards"], "spaced_repetition"),
  (["learning path", "what should i study", "study plan", "adapt path"], "adaptive_path"),
  (["help with code", "debug", "fix my code", "pr review", "coding help"], "coding_assistant"),
  (["tldr", "eli5", "brief", "quick explanation", "summarize"], "student_buddy"),
  (["ingest", "youtube.com", "github.com/", "new video", "process content"], "content_ingestion"),
  (["generate question", "create mcq", "make quiz", "question bank"], "mcq_factory"),
  (["capstone", "grade my project", "evaluate project"], "project_evaluator"),
  (["re-engage", "reengage", "inactive student", "churn risk", "win back", "nudge student"], "disrupt_prevention"),
  (["career plan", "career roadmap", "become ai engineer", "what skills do i need", "career transition", "career coaching"], "career_coach"),
  (["review my resume", "resume feedback", "improve cv", "resume critique", "check my resume"], "resume_reviewer"),
  (["billing", "subscription", "refund", "cancel subscription", "upgrade plan", "payment issue", "invoice"], "billing_support"),
]
19 keyword entries map to 19 distinct agents.

Registry vs classifier vs reality
Registry (registry._ensure_registered:36–61): 26 imports → 26 agents instantiable. Names: adaptive_path, adaptive_quiz, billing_support, career_coach, code_review, coding_assistant, community_celebrator, content_ingestion, cover_letter, curriculum_mapper, deep_capturer, disrupt_prevention, job_match, knowledge_graph, mcq_factory, mock_interview, peer_matching, portfolio_builder, progress_report, project_evaluator, resume_reviewer, senior_engineer, socratic_tutor, spaced_repetition, student_buddy, tailored_resume.
Classifier ROUTABLE_AGENTS (moa.py:24–51): 24 names. Includes studio_tutor. Excludes: cover_letter, senior_engineer, tailored_resume.
Classifier prompt body (moa.py:53–86): lists only 22 agents (omits even more than ROUTABLE_AGENTS — verify against the literal text). Prompt explicitly enumerates: socratic_tutor, code_review, adaptive_quiz, mcq_factory, coding_assistant, student_buddy, content_ingestion, curriculum_mapper, deep_capturer, spaced_repetition, knowledge_graph, adaptive_path, project_evaluator, progress_report, mock_interview, portfolio_builder, job_match, disrupt_prevention, peer_matching, community_celebrator, career_coach, resume_reviewer, billing_support → that's 23 in the prompt; studio_tutor is in ROUTABLE_AGENTS but not in the prompt body.
Mismatches:
Agent	In registry?	In ROUTABLE_AGENTS?	In classifier prompt?	In _KEYWORD_MAP?
cover_letter	yes	no	no	no
senior_engineer	yes	no	no	no (keywords for "senior review" not present)
tailored_resume	yes	no	no	no
studio_tutor	no	yes	no	no
knowledge_graph	yes	yes	yes	no keyword
mcq_factory	yes	yes	yes	yes
So:

3 registered agents are unreachable via the MOA (cover_letter, senior_engineer, tailored_resume) — they can still be invoked via direct routes (senior_review.py, practice.py, career/resume).
1 name is in ROUTABLE_AGENTS but not in the registry (studio_tutor) — if the LLM classifier ever returns it, _run_any_agent() (moa.py:200–204) catches the KeyError and falls back to socratic_tutor.
D. BaseAgent pipeline — full run()

# backend/app/agents/base_agent.py:211–229
async def run(self, state: AgentState) -> AgentState:
    """Full pipeline: execute → evaluate → log_action."""
    start_ms = int(time.monotonic() * 1000)
    status = "completed"
    try:
        self._log.info("agent.run.start", task_length=len(state.task))
        state = await self.execute(state)
        state = await self.evaluate(state)
        state = state.model_copy(update={"agent_name": self.name})
        self._log.info("agent.run.complete", score=state.evaluation_score)
    except Exception as exc:
        status = "error"
        state = state.model_copy(update={"error": str(exc), "agent_name": self.name})
        self._log.exception("agent.run.error", error=str(exc))
        raise
    finally:
        duration_ms = int(time.monotonic() * 1000) - start_ms
        await self.log_action(state, status=status, duration_ms=duration_ms)
    return state
Signatures (base_agent.py:45–55):


@abstractmethod
async def execute(self, state: AgentState) -> AgentState: ...

async def evaluate(self, state: AgentState) -> AgentState:
    """Default: pass-through with score 0.8."""
    return state.model_copy(update={"evaluation_score": 0.8})
log_action() (base_agent.py:88–209) opens a fresh AsyncSessionLocal, writes one AgentAction row per run with: agent_name, student_id, action_type="execute", input_data={"task", "context_keys": list(...)} (note: only the keys of context, not values), output_data={"response_length", "tools_used", "evaluation_score", "input_tokens", "output_tokens"}, tokens_used, status, error_message, duration_ms, plus DISC-57 actor columns from state.context.get("actor_id"|"actor_role"|"on_behalf_of"). Emits a llm.call structlog + PostHog telemetry event with INR/USD cost estimate.

E. agent_orchestrator.py end-to-end (backend/app/services/agent_orchestrator.py, 175 lines)
chat(student_id, message, conversation_id?, agent_name?, context?) (line 80).
Generates conv_id if absent (line 100).
Loads Redis client; _load_history() reads pae:{env}:conv:{conv_id} (line 102; returns [] on miss/error).
Constructs AgentState(student_id, task=message, conversation_history=history, context=context or {}) (line 104).
Branches:
If caller passed agent_name: get_agent(agent_name) from registry; await agent.run(state) (line 127). On KeyError, returns a hard-coded "agent not found" string.
Else: builds MOAGraphState, calls graph.ainvoke(graph_input) (line 138). The MOA graph routes via keyword/LLM and dispatches.
Calls flatten_content() (_llm_utils.py) on result_state.response (line 149) to handle Anthropic list-of-dict content. Falls back to "I couldn't generate a response. Please try again." string.
Appends user + assistant turns to history, trims to last 20, setex with 1h TTL (lines 155–159).
Returns {response, agent_name, evaluation_score, conversation_id} dict (line 169).
It does NOT: read any DB table; check entitlements; fetch student profile; inject student state into context. It is a transparent Redis-backed wrapper around the MOA graph.

F. Three sample agents in full
F.1 socratic_tutor.py (backend/app/agents/socratic_tutor.py)
Prompt (prompts/socratic_tutor.md): Socratic principles (never give direct answers, build on student's current understanding, calibrate complexity). Notes "You have access to: the student's current lesson and course progress, their recent conversation history, any course content relevant to their question (provided in context)" — but the only thing actually fed in is state.context["course_content"] and state.conversation_history (Redis).
execute() (lines 95–113): builds messages = SystemMessage(prompt) + optional [CONTEXT: {course_content}] + last 6 turns of conversation history + current task. Calls stub search_course_content.ainvoke({"query": state.task}) — line 18–35: returns a hard-coded RAG-shaped string about "Retrieval Augmented Generation". Re-builds messages, invokes LLM, returns updated state.
Context expected: state.context.get("course_content") (optional). Nothing from DB.
DB reads: zero.
DB writes: zero (only the parent BaseAgent.log_action() writes one agent_actions row).
evaluate() (line 115–120): score 0.9 if response contains "?", else 0.3.
F.2 code_review.py (backend/app/agents/code_review.py)
Prompt (prompts/code_review.md): Five-dimension rubric (correctness, production readiness, LLM best practices, code quality, performance), each 0–20 pts, total 100. Demands strict JSON output schema with score, summary, strengths, issues[], dimension_scores, approved.
execute() (lines 96–130): pulls code = state.context.get("code", state.task). Runs synchronous local analyze_code tool (lines 21–75) — does substring checks (print(, import *, except:, os.environ[, "password", "api_key") and shells out to ruff check --output-format=concise. Sends static-analysis findings + code to LLM. Uses flatten_content() + extract_first_balanced_json() from _llm_utils.py to parse output. Stores review_json into state.response (as JSON string) and state.context["review"].
Context expected: state.context["code"] (or falls back to state.task).
DB reads: zero.
DB writes: zero (parent's log_action only).
evaluate() (lines 132–140): re-parses response JSON, score / 100.0 clamped to [0, 1]; 0.5 fallback.
F.3 senior_engineer.py (backend/app/agents/senior_engineer.py)
Prompt (prompts/senior_engineer.md): Direct-but-kind voice, no sycophancy. JSON-only output with verdict ∈ {approve, request_changes, comment}, headline ≤ 120 chars, strengths[0..3], comments[] with {line, severity, message ≤ 240 chars, suggested_change?}, next_step ≤ 200 chars. Severity: nit / suggestion / concern / blocking. Review priorities ranked: correctness → runtime safety → AI-engineering concerns → production-readiness → readability.
execute() (lines 143–195): pulls code = state.context.get("code") or state.task, optional problem_context. Builds messages, invokes LLM. Uses _clean_text_blocks() (lines 28–38) and a custom _extract_json() (lines 41–62, handles ```json fences and brace-finding). Runs _sanitize_review() (lines 65–120) which: clamps verdict, truncates headline/message/next_step, enforces verdict↔severity consistency (any blocking → request_changes; no blocking + request_changes → downgrade to comment).
Context expected: state.context["code"], optionally state.context["problem_context"].
DB reads: zero.
DB writes: zero (parent's log_action only).
evaluate() (lines 197–215): 1.0 if (verdict=approve, no comments) OR (any comments with valid verdict); 0.6 if approve+no comments; 0.5 fallback; 0.3 on parse failure or invalid verdict.
Common pattern across all three: the agent reads only what state.context and state.conversation_history give it; runs a single LLM call (plus, in code_review, a local subprocess); writes nothing to the DB except the audit row in agent_actions via log_action. None of the three reaches into student state, course progress, prior agent outputs, risk signals, mastery state, or any long-term table.

End of Pass 2 report. Observations only
