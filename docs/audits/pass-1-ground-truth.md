---
title: Pass 1 — Ground Truth Audit
status: Final
date: 2026-04 (approximate, prior to Track 7)
authored_by: Claude Code (audit session)
purpose: Establish what is actually in the AICareerOS codebase, structurally and verifiably. Observation only, no recommendations.
supersedes: nothing
superseded_by: nothing — this is the snapshot of record
---

# Pass 1 — Ground Truth Audit

> This document is the structural ground truth of the AICareerOS codebase as of the audit date. It contains observations only — no recommendations, no fixes, no opinions on quality. Subsequent passes (Pass 2, Pass 3a) build on this snapshot. If you need to know "what was in the codebase when the architecture was decided," this is the source.

PASS 1 AUDIT REPORT — Ground Truth
Project root for this audit: e:\Apps\pae_platform\pae_platform\ (the parent e:\Apps\pae_platform\ contains screenshots and a pae_platform.zip snapshot but is not a git repo).

SECTION 1: REPO MAP
Top-level directory tree (2 levels deep)
Path	Apparent purpose
6 important pages/	Static HTML mockups (Thankyou, checkout, cohort, main brand, programs, rag)
.claude/	Claude Code config: agents/, commands/, hooks/, rules/, skills/, worktrees/
.github/	GitHub Actions workflows
backend/	FastAPI app (app/, alembic/, tests/, course_content/, scripts/)
business-doc/	(parent dir, not in this project root)
cal/ claude/ cursor/ framer/ mintlify/ notion/ posthog/ raycast/ resend/ sentry/ stripe/ supabase/ superhuman/ vercel/	One-file scaffolding folders, see below
design-mockups/	Static HTML design mockups (e.g., CareerForge v10 - Capstone bundle.html)
design-system/	pae-platform/MASTER.md design tokens
docs/	audits/, design/, design-references/, features/, ops/, runbooks/, screenshots/, superpowers/
frontend/	Next.js 16 app: src/, e2e/, public/, tools/, playwright-report/, test-results/
infra/	backup/ only
nginx/	nginx config
scripts/	Repo-level shell scripts
File counts by language (excludes node_modules, .next, .git, __pycache__, .venv*)
Ext	Count
.py	4,986 (includes .venv/site-packages contamination — see note below)
.ts	216
.tsx	547
.js	1
.sql	10
.md	290
Note: the 4,986 .py count is inflated by Python virtualenvs at backend/.venv/ and backend/.venv-test/ not being excluded (filter only excluded .venv* not .venv-test). Project source .py count is in the low thousands; precise breakdown not run.

LOC (excluding tests, migrations, generated, node_modules, .venv*)
wc -l total: 91,346 lines across .py/.ts/.tsx source (this excluded test_*, *_test.py, *.test.ts, *.spec.ts, alembic/versions, node_modules, .next, .venv, __pycache__). cloc/tokei not available.

Scaffolding folders with no real code
Each contains exactly 1 file (DESIGN.md) and nothing else:


cal/         claude/      cursor/      framer/      mintlify/
notion/      posthog/     raycast/     resend/      sentry/
stripe/      supabase/    superhuman/  vercel/
14 scaffolding folders × 1 markdown file each.

SECTION 2: PRODUCT IDENTITY DRIFT
Source	Name used
README.md:1	"Production AI Engineering Platform" (a.k.a. "PAE Platform" in make/pae: Redis prefix)
CLAUDE.md:1	"Production AI Engineering Platform"
frontend/package.json:2	"name": "frontend" (no product name)
frontend/src/app/layout.tsx:29	title: "CareerForge — become, do not just learn"
frontend/src/app/layout.tsx:31	description mentions "18+ AI agents" (README says 20)
Agent prompts	backend/app/agents/prompts/tailored_resume.md:3 "You are CareerForge's tailoring agent."; readiness_interviewer.md:3 "the conversational front door of CareerForge's Job Readiness page"; billing_support.md also references CareerForge
docs/ARCHITECTURE.md:3	"Production AI Engineering Platform"
docs/AGENTS.md:1	"Production AI Engineering Platform"
Repo path / Redis prefix	pae_platform / pae: (backend/app/core/redis.py:11 _NAMESPACE_PREFIX = "pae")
Receipt format	CF-YYYYMMDD-XXXXXX (backend/app/services/order_service.py:68) — "CF" = CareerForge
design-system/pae-platform/MASTER.md	"PAE platform"
design-mockups/CareerForge v10 - Capstone bundle.html	"CareerForge"
Distinct product names found in the codebase
"Production AI Engineering Platform" — README, CLAUDE.md, ARCHITECTURE.md, AGENTS.md
"PAE Platform" / "pae" — directory name, Redis namespace prefix (backend/app/core/redis.py:11), design-system/pae-platform/
"CareerForge" — frontend <title> (frontend/src/app/layout.tsx:29), 3 agent prompts (tailored_resume.md, readiness_interviewer.md, billing_support.md), receipt prefix CF- (order_service.py:68), 6 admin commit messages (feat(retention-panels): readable in CareerForge admin dark mode), design-mockups/CareerForge v10 - Capstone bundle.html
"AICareerOS" — not found anywhere in the codebase. Grep for AICareerOS|aicareeros across .py/.ts/.tsx/.md/.json returned 0 source matches. The owner's stated brand name is absent from the code.
The frontend description tag (layout.tsx:31) advertises "18+ AI agents"; README (README.md:3) and ARCHITECTURE.md both say "20 AI agents"; backend/CLAUDE.md:4 says "18+ AI agents".

SECTION 3: AGENT SYSTEM SHAPE
Agent registry
backend/app/agents/registry.py

Registration mechanism: class decorator @register (line 12–15) that writes to module-level dict AGENT_REGISTRY: dict[str, type[BaseAgent]] (line 9) keyed by cls.name.
All agent modules are eagerly imported by _ensure_registered() (lines 34–61). 26 imports are listed; mcq_factory is also added (it's listed in moa.py keyword routing) bringing visible registrations to 26+1 ad-hoc.
All registered agents (from registry._ensure_registered, lines 36–61)
The registry imports 26 agent modules (note: README and AGENTS.md both claim "20 agents"; actual registry is 26):

#	Name	File	Model	One-line description
1	adaptive_path	adaptive_path.py:18	claude-sonnet-4-6 (line 28)	Adjusts learning path from quiz performance + skill gaps
2	adaptive_quiz	adaptive_quiz.py:65	claude-sonnet-4-6 (76)	Adaptive MCQ quizzing
3	billing_support	billing_support.py:24	claude-haiku-4-5 (49)	Billing/subscription Q&A; redirects refunds to support@pae.dev
4	career_coach	career_coach.py:21	claude-sonnet-4-6 (42)	90-day GenAI career action plans
5	code_review	code_review.py:79	claude-sonnet-4-6 (90)	Code review with structured JSON, score 0–100
6	coding_assistant	coding_assistant.py:17	claude-sonnet-4-6 (27)	PR-style review for student code
7	community_celebrator	community_celebrator.py:17	claude-sonnet-4-6 (27)	Celebration messages for milestones
8	content_ingestion	content_ingestion.py:32	claude-sonnet-4-6 (56)	Ingest GitHub/YouTube/free-text → metadata + concepts
9	cover_letter	cover_letter.py:28	claude-sonnet-4-6 (37)	250-word cover letter
10	curriculum_mapper	curriculum_mapper.py:18	claude-sonnet-4-6 (27)	Map ingested content to curriculum
11	deep_capturer	deep_capturer.py:18	claude-sonnet-4-6 (37)	Weekly synthesis with sticky metaphors
12	disrupt_prevention	disrupt_prevention.py:20	claude-sonnet-4-6 (29)	Detect disengaged students + re-engage
13	job_match	job_match.py:46	claude-sonnet-4-6 (56)	Skill→job matching (stub)
14	knowledge_graph	knowledge_graph.py:35	claude-haiku-4-5 (57)	Update concept mastery map
15	mcq_factory	mcq_factory.py	(per AGENTS.md) sonnet-4-6	Generate 5 MCQs per call
16	mock_interview	mock_interview.py:17	claude-sonnet-4-6 (26)	System-design mock interviews
17	peer_matching	peer_matching.py:47	claude-sonnet-4-6 (66)	Match students with study partners
18	portfolio_builder	portfolio_builder.py:18	claude-sonnet-4-6 (27)	Markdown portfolio entries
19	progress_report	progress_report.py:18	claude-sonnet-4-6 (27)	Weekly human-readable progress reports
20	project_evaluator	project_evaluator.py:26	claude-sonnet-4-6 (35)	Capstone evaluator with rubric
21	resume_reviewer	resume_reviewer.py:27	claude-sonnet-4-6 (47)	Scored, structured resume review
22	senior_engineer	senior_engineer.py:124	claude-sonnet-4-6 (137)	"Senior teammate" PR-style review
23	socratic_tutor	socratic_tutor.py:53	claude-sonnet-4-6 (65)	Socratic questioning
24	spaced_repetition	spaced_repetition.py:46	claude-haiku-4-5 (66)	SM-2 algorithm + LLM explanations
25	student_buddy	student_buddy.py:17	claude-sonnet-4-6 (28)	Short focused explanations
26	tailored_resume	tailored_resume.py:30	claude-sonnet-4-6 (43)	JD-tailored, ATS-safe resumes
Models in use: 22× claude-sonnet-4-6, 3× claude-haiku-4-5 (billing_support, knowledge_graph, spaced_repetition), mcq_factory model not directly verified.

Base agent class
backend/app/agents/base_agent.py, class BaseAgent (line 27).

Provides:

__init__() (line 42) — structlog logger bound to agent_name.
execute(state) -> AgentState (lines 46–48) — abstract; subclasses override.
evaluate(state) -> AgentState (lines 50–55) — default passes through with evaluation_score=0.8.
_merge_token_usage(state, llm_response) (lines 57–86) — extracts LangChain token counts into state.metadata for cost tracking.
log_action(state, status, duration_ms) (lines 88–209) — persists AgentAction row with token use, INR/USD cost, actor identity (DISC-57).
run(state) -> AgentState (lines 211–229) — pipeline: execute → evaluate → log_action; exception + timing handling.
AgentState(BaseModel) itself is defined in the same file (line 12) — see Section 4.

LangGraph StateGraph
backend/app/agents/moa.py — only file with a StateGraph.

StateGraph created at line 220 with state schema MOAGraphState (lines 116–126).
add_nodes (lines 222–223): "classify_intent" → classify_intent, "run_agent" → _run_any_agent.
add_edges (lines 226–227): classify_intent → run_agent, run_agent → END.
Entry point: classify_intent (line 225).
Only one StateGraph exists in the codebase. Despite product vision of "20 agents that coordinate," there is no multi-agent graph; the only graph is a 2-node classify-then-run pattern.

MOA / intent classifier / router
backend/app/agents/moa.py. Three-stage routing:

Keyword routing — _KEYWORD_MAP (lines 89–112) of (keywords, agent_name) pairs; keyword_route_with_reason() (lines 146–159) does substring match. O(1)-ish, no LLM cost.
LLM classifier fallback — _build_classifier() (line 174) uses build_classifier_llm() from llm_factory. Prompt _CLASSIFIER_PROMPT (lines 53–86) lists 24 routable agents. Per file comment line 7: "fast keyword matching first, then falls back to claude-haiku-4-5".
Default fallback (lines 186–188) — socratic_tutor.
Routable agent list in classifier prompt (lines 24–50): 24 agents. Note: that count differs from registry's 26, and includes one name studio_tutor not present in the registry.

SECTION 4: STATE & MEMORY SHAPE
AgentState Pydantic schema
backend/app/agents/base_agent.py:12. Fields:

Line	Field	Type	Default
15	student_id	str	required
16	conversation_history	list[dict[str, Any]]	default_factory=list
17	task	str	required
18	context	dict[str, Any]	default_factory=dict
19	response	str | None	None
20	tools_used	list[str]	default_factory=list
21	evaluation_score	float | None	None
22	agent_name	str | None	None
23	error	str | None	None
24	metadata	dict[str, Any]	default_factory=dict
Conversation history storage
Store: Redis, key namespace pae:{environment}:conv:{conversation_id} (backend/app/core/redis.py:11–37, category conv).
TTL: 3600 s (backend/app/services/agent_orchestrator.py:19 _HISTORY_TTL = 3600).
Value: JSON-serialized list[dict[str, Any]] of turns (load: agent_orchestrator.py:38–56; save: agent_orchestrator.py:59–73 via redis.setex).
Failure mode: Redis miss → empty history, log warning, continue (line 47–55).
agent_actions table
Migration: backend/alembic/versions/0001_initial_schema.py:326. Actor-identity columns (actor_id, actor_role, on_behalf_of) added in 0027_agent_actions_actor_identity.py.
Model: backend/app/models/agent_action.py:11. Columns: id (UUID PK from UUIDMixin), agent_name str(100) (indexed, line 14), student_id UUID FK users.id (line 15), action_type str(100) (18), input_data JSON (19), output_data JSON (20), status str(50) default "completed" (21), error_message Text (22), duration_ms int (23), tokens_used int (24), actor_id UUID FK users.id indexed (29), actor_role str(50) (32), on_behalf_of UUID FK users.id (33), created_at/updated_at (TimestampMixin).
Indexes: ix_agent_actions_agent_name, ix_agent_actions_actor_id.
Is agent_actions read or only written?
Read extensively. Read sites:

File	Lines	Purpose
backend/app/api/v1/routes/admin.py	113, 155, 161, 167–169, 176–177, 290, 610–611, 764–770, 944, 1065–1066, 1073, 1081–1083, 1562–1564, 1770–1779, 1784	Admin dashboard counts, per-agent stats, per-student history, cohort analysis
backend/app/services/at_risk_student_service.py	355–358, 365–369	Help-agent usage windows
backend/app/services/consistency_service.py	77–81	Daily action buckets
backend/app/services/confusion_heatmap_service.py	241–246	Help-agent input mining
backend/app/services/inactivity_service.py	91–94	Last-action-per-student
backend/app/services/receipts_service.py	192–197	Weekly action summary
Write sites:

backend/app/agents/base_agent.py:192 — main log_action path.
backend/app/services/diagnostic_cta_service.py:43 — diagnostic CTA flow.
Other long-term student state tables
From alembic migrations:

Table	Migration
student_progress	0001_initial_schema.py:214
user_skill_states	0004_skill_graph.py:94
conversation_memory	0010_conversation_memory.py:23
goal_contracts	0002_goal_contracts.py:23
growth_snapshots	0006_growth_snapshots.py:23
srs_cards	0008_srs_cards.py:23
student_misconceptions	0012_student_misconceptions.py:23
student_risk_signals	0049_student_risk_signals.py:34
learning_sessions	0044_today_screen_completion.py:75
agent_memory	0054_agentic_os_primitives.py:109
confidence_reports	0013_confidence_reports.py
daily_intentions	0016_daily_intentions.py
weekly_intentions	0019_weekly_intentions.py
student_notes	0014_student_notes.py
SECTION 5: COURSE & ENROLLMENT FLOW
Tables
Table	Migration
courses	0001_initial_schema.py:60
lessons	0001_initial_schema.py:146
lesson_resources	0042_lesson_resources.py:29
exercises	0001_initial_schema.py:181
exercise_submissions	0001_initial_schema.py:240
enrollments	0001_initial_schema.py:118 (legacy)
payments	0001_initial_schema.py:89 (legacy)
course_bundles	0047_payments_v2.py:59
orders	0047_payments_v2.py:82
payment_attempts	0047_payments_v2.py:120
payment_webhook_events	0047_payments_v2.py:149
course_entitlements	0047_payments_v2.py:175
refunds	0047_payments_v2.py:204
mcq_bank	0001_initial_schema.py:297
quiz_results	0001_initial_schema.py:269
Path "student pays → course unlocked → agent access granted"
POST /api/v1/payments/create-order (backend/app/api/v1/routes/payments_v2.py) — writes orders row with target_type + target_id; returns Razorpay key.
POST /api/v1/payments/confirm-order — verifies signature, writes payment_attempts, on success calls entitlement_service.grant_entitlement(order) which writes course_entitlements.
Webhook POST /api/v1/webhooks/razorpay (backend/app/api/v1/routes/payments_webhook.py) — idempotent on UNIQUE(provider, provider_event_id); writes payment_webhook_events; processes state transitions (authorized → fulfilled, refund.created, etc.).
Free path: POST /api/v1/payments/free-enroll → entitlement_service.grant_free_entitlement() → course_entitlements.
Catalog endpoint reads course_entitlements (active = revoked_at IS NULL) and old enrollments (back-compat) to populate is_unlocked.
Enrollment query: GET /api/v1/courses/{course_id}/my-enrollment (courses.py:84–85).
Coherence
Two parallel models exist concurrently: legacy payments + enrollments (2026-04 era, migration 0001) and v2 orders + payment_attempts + course_entitlements + refunds (migration 0047). Per dispatched explore agent: "Both active for backward compat." Refund schema present (refunds table, refund_offers table at 0052). No explicit "agent-access-grant" step beyond entitlement existence — agent endpoints are gated only by JWT auth, not by entitlement check, in the routes inspected. (This is observation; deeper gate analysis is for later passes.)

SECTION 6: BACKGROUND JOBS
Celery tasks (under backend/app/tasks/)
File	Task function
growth_snapshots.py	build_weekly_snapshots()
weekly_letters.py	send_weekly_letters()
weekly_review.py	assemble_weekly_reviews()
inactivity_sweep.py	sweep_inactive_students()
risk_scoring.py	score_all_users_task()
outreach_automation.py	run_nightly_outreach_task()
quiz_pregenerate.py:118	pregenerate_quiz_for_message(message_id, content) (on-demand, not scheduled)
Celery-beat schedule (backend/app/core/celery_app.py:30–69)
Job	Cron	Task	What it does	Engagement vs infra
growth-snapshots-weekly	Sun 00:00 UTC	build_weekly_snapshots	Write one growth_snapshots row per active user for the past week	Engagement (data prep)
weekly-letters	Sun 01:00 UTC	send_weekly_letters	Invoke progress_report agent per user; persist in-app notification + email	Proactive engagement
weekly-review-quiz	Sun 02:00 UTC	assemble_weekly_reviews	Build review quiz from due SRS cards	Proactive engagement
inactivity-sweep	Mon 09:00 UTC	sweep_inactive_students	Log re_engagement.flagged per inactive student	Proactive engagement (churn detection)
risk-scoring-nightly	Daily 03:00 UTC	score_all_users_task	F1: recompute every active user's risk_score + slip_type; upsert student_risk_signals	Proactive engagement (churn detection)
outreach-automation-nightly	Daily 09:00 UTC	run_nightly_outreach_task	F9: automated email sends per risk signal (dry-run unless ENV=production + OUTREACH_AUTO_SEND=1)	Proactive engagement (nudging)
No scheduled "personalization update" agent or learning-graph re-build job is present. All proactive jobs target retention/risk; none target curriculum personalization across the 20-agent claim.

SECTION 7: API SURFACE
Total FastAPI routes
227 route decorators across 48 router files mounted under /api/v1 (plus health router with no prefix). FastAPI app: backend/app/main.py, create_app() line 36; routers loop-mounted at main.py:245 with prefix /api/v1; health router at main.py:130.

Routes grouped by router file (top 15 by count)
Router	Count
admin.py	21
chat.py	18
exercises.py	15
interview.py	12
students.py	10
lessons.py	9
today.py	9
career.py	8
readiness.py	8
courses.py	7
mock_interview.py	7
notebook.py	7
payments_v2.py	6
auth.py	5
application_kit.py	5
33 other routers	1–4 each
(See dispatch-agent output for the full 48-row table; total = 227.)

Orphan routers
Per dispatched agent: none. Every APIRouter() instance in backend/app/api/ is mounted via the main.py:245 loop. Two APIRouter( references inside docstrings under dependencies/entitlement.py are example code.

SECTION 8: FRONTEND SURFACE
Total pages
53 page.tsx files under frontend/src/app/ (counted directly via find).

Top-level page routes
Public ((public)/, 14 pages): / (landing), /about, /agents, /blog, /changelog, /docs, /login, /mock-report/[token], /placement-quiz, /pricing, /privacy, /register, /security, /status, /terms.

Portal ((portal)/, 25 pages): /career, /career/interview-bank, /career/jd-fit, /career/resume, /catalog, /chat, /courses, /courses/[id], /dashboard, /exercises, /exercises/[id], /interview, /lessons/[id], /map, /notebook, /onboarding, /path, /practice, /practice/[problemId], /progress, /promotion, /readiness, /receipts, /studio, /today.

Admin (admin/, 13 pages, regular dir, not a route group): /admin, /admin/agents, /admin/at-risk, /admin/audit-log, /admin/confusion, /admin/content, /admin/content-performance, /admin/courses, /admin/courses/[id]/edit, /admin/feedback, /admin/pulse, /admin/students, /admin/students/[id].

Other: /design (design system browser).

Admin console
13 pages, listed above. Owner-recent commits indicate active retention/admin work (feat(admin): unified topbar nav, feat(retention-engine): F0–F14).

API client usage
openapi-fetch is in package.json:31 as a dependency, but 0 import sites in frontend/src/.
14 raw fetch( call sites, e.g.:
frontend/src/app/(portal)/interview/page.tsx:136
frontend/src/components/features/feedback-widget.tsx:17
frontend/src/components/features/readiness-diagnostic/diagnostic-anchor.tsx:168
frontend/src/components/features/studio/code-editor.tsx:84, :116
frontend/src/hooks/use-stream.ts:492, :858
frontend/src/lib/api-client.ts:109, :157
0 axios imports / usage.
Ratio openapi-fetch : raw fetch = 0 : 14. (Note: frontend/CLAUDE.md rule states "API calls through src/lib/api-client.ts — auto-generated from FastAPI OpenAPI schema"; current state diverges from that rule.)

SECTION 9: DOCS & INTENT
README.md:1–3
"# Production AI Engineering Platform

A git-based learning platform with 20 AI agents for teaching production GenAI systems. One human injects knowledge; the system automates content creation, student learning, career support, and revenue operations."

CLAUDE.md:1–6
"# Production AI Engineering Platform

Project Overview
A git-based learning platform with 18+ AI agents for teaching production GenAI.
Next.js 15 frontend + FastAPI backend + LangGraph agent orchestration + PostgreSQL + Redis."

docs/ARCHITECTURE.md:1–10
"# Architecture — Production AI Engineering Platform

System Overview
A git-based learning platform with 20 AI agents that automates content creation, student learning, career support, and community engagement. One human (you) injects knowledge; the system turns it into a self-serving learning machine."

docs/AGENTS.md:1–6
"# All 20 AI Agents — Production AI Engineering Platform

All agents extend BaseAgent, are registered via @register, and flow through the Master Orchestrator Agent (MOA) LangGraph StateGraph."

frontend/CLAUDE.md:1–4
"# Frontend — Next.js 15

Stack
Next.js 15 (App Router) + TypeScript (strict) + Tailwind CSS 4 + shadcn/ui + React Query + Zustand"

backend/CLAUDE.md:1–4
"# Backend — FastAPI

Stack
FastAPI + SQLAlchemy 2.0 (async) + Alembic + Celery + Redis + PostgreSQL 16 + LangGraph"

Explicit doc/code contradictions
Claim	Doc	Code reality
"20 AI agents"	README.md:3, ARCHITECTURE.md:3, AGENTS.md:1	backend/app/agents/registry.py:36–61 imports 26 agent modules; moa.py classifier prompt lists 24 routable; frontend description says "18+" (layout.tsx:31); backend/CLAUDE.md:4 says "18+"
"12 database tables"	ARCHITECTURE.md ("PostgreSQL 16 (12 tables)"), README.md:71	Alembic has 53 numbered migrations (gap at 0050) creating ~45+ distinct tables (full enumeration in Section 4)
"15 frontend routes"	README.md:62, ARCHITECTURE.md	53 page.tsx files
"8 route groups"	README.md:64, ARCHITECTURE.md	48 router files under api/v1/, 227 routes
"19 API endpoints"	ARCHITECTURE.md	227 route decorators
"84 backend tests · 28 frontend tests · 81% backend coverage"	README.md:84, ARCHITECTURE.md	Not verified in this pass. 18 standalone run_3*_tests.py runners exist outside the pytest tree, plus a tests/ directory.
Next.js version	README.md:60,125 "Next.js 16"; CLAUDE.md:5 "Next.js 15"; frontend/CLAUDE.md:1 "Next.js 15"; backend/CLAUDE.md n/a	frontend/package.json:29 "next": "16.2.2"
Payments provider	README.md:132 "Stripe (webhooks wired)"; ARCHITECTURE.md "Stripe webhooks"	Code uses Razorpay (payments_v2.py confirm-order takes razorpay_payment_id/razorpay_signature; payments_webhook.py /api/v1/webhooks/razorpay); receipt prefix CF- (order_service.py:68); @stripe/stripe-js in package.json:20 is a leftover dep with no stripe webhook route
Architecture says "MOA … 5 categories" / coordinated agents	README.md:66, ARCHITECTURE.md	One LangGraph StateGraph with 2 nodes (classify_intent → run_agent → END). No multi-agent orchestration graph; no shared agent memory passed between agents in a single user request
Product name	Docs: "Production AI Engineering Platform"; Repo path: pae_platform	Frontend brand: CareerForge (layout.tsx:29); 3 agent prompts call themselves CareerForge; receipts use CF- prefix
"Storybook"	frontend/CLAUDE.md:11 "pnpm storybook"; "ALL components must have Storybook stories"	No storybook package in frontend/package.json; no .storybook/ config; package.json has no storybook script (only dev, build, start, lint, test, e2e*). Dev gallery uses route-based /design (per user memory)
frontend/CLAUDE.md:9 says pnpm generate:api		No generate:api script in package.json:5–14
SECTION 10: RAW SIGNALS
Last 50 commit messages (git log --oneline | head -50)

eadbaef feat(admin): unified topbar nav + IA cleanup across the admin section
01ff1ed fix(admin): student detail modal renders in v8/cockpit chrome
a8e7b7d fix(path): constellation shows role progression, not course names
d685218 fix(admin): match Resume Lab tone in student detail modal
8600d29 fix(admin): retention 'See all' + panel rows stay on /admin (no nav)
5c3e1aa chore(admin): retire legacy /admin/at-risk in favor of F1 retention engine
838bd4c fix(admin): premium tone for student detail modal — match cockpit aesthetic
bc6659b feat(admin): retention 'See all N' lands on filtered roster (drops legacy redirect)
0d5df98 fix(admin): replace native <select> with shadcn Select to kill dark-mode flicker
6717785 fix(admin): kill <select> dropdown white-flash on open in dark modal
5d51f20 fix(admin): dark-mode contrast in student detail modal + remove redundant link
b7c98d6 feat(admin): student detail as centered modal (replaces full-page nav)
990e186 fix(admin): emit real cohort_events on lifecycle moments
8045802 fix(admin): wire pulse-strip 24h/7d/30d tabs to live data
342cc74 fix(retention): reconcile student counts on /admin (94/92/94)
15645c1 fix(admin): align action band → call list semantics with live data
57ea747 Merge branch 'feat/ld-1-action-band-roster-live' — Admin Live Data (LD-1..LD-7)
4f27145 docs: mark LD-1..LD-7 closed in admin-live-data tracker
ac90c44 feat(admin): LD-7 — drop unused admin_console_* imports
56f9d5a feat(admin): LD-6 — remove legacy student modal
c24dae0 feat(admin): LD-5 — right rail (calls + events + revenue) live
84b5b93 feat(admin): LD-4 — feature pulse 8 tiles live
2569afd feat(admin): LD-3 — learner funnel live counts
ed0a699 feat(admin): LD-2 — pulse strip live data with sparklines
e8135a0 feat(admin): LD-1 — action band + roster + click-thru live
38fa027 fix(retention-panels): readable in CareerForge admin dark mode
4f11f1d fix(auth): role-aware landing on login
7bcec0d chore(retention-engine): fix lint violations introduced by F8/F13/F14
40e220d docs: mark F12-F14 closed in retention-engine tracker
7b80094 feat(retention-engine): F12-F14 — Tier 3 admin polish
2b03554 docs: mark F8-F11 closed in retention-engine tracker
c673e5e Merge branch 'prod/f9-nightly-automation' — F8 in-app DM + F9 nightly outreach automation
61ebcd8 feat(retention-engine): F9 — nightly outreach automation
c48f96d feat(retention-engine): F8 — admin↔student in-app DM thread
475591a Merge branch 'feat/retention-f10-f11' — F10 calendar mailto + F11 refund offer flow
1bc1c7e feat(retention-engine): F11 — refund offer flow for paid_silent day-14
a7762fb feat(retention-engine): F10 — calendar mailto-shim
31496db docs: mark F0-F6 closed-by 3197dec/82e6246; close OPEN-ISSUES P1-A
82e6246 Merge branch 'prod/retention-engine-tier1' — Retention engine F0-F6
3197dec feat(retention-engine): F0-F6 — turn /admin from dashboard into retention engine
3de5dda docs: retention engine — 14-ticket plan for catching students before they slip
a582978 docs: add OPEN-ISSUES.md tracker for the post-PR3 tail
83b1f74 Merge branch 'prod/admin-audit-fixes' — MCP-driven coverage audit + regression lock
6b4d076 fix(admin+goals): MCP-driven coverage audit found 4 bugs across student/admin screens
e086906 docs(runbooks): admin account management runbook
a8ada4b Merge branch 'prod/pr3-e2e-and-cd' — Playwright smoke in CI + Fly deploy workflow
4349f1e ci: PR3/D8 — Playwright smoke in CI + tag-driven Fly deploy workflow
aa70c80 Merge branch 'prod/pr3-finish' — PR 3 finish-up: D4.1 + D5.1 + D7 + C3.2 screens + C4.1 source-maps
64434ed feat(observability): PR3/C3.2-finish — wire screen-level analytics events
59720e3 feat(deploy): PR3/C4.1-finish + D7 — Sentry source-maps + Fly configs + on-call runbook
TODO / FIXME / HACK / XXX in backend/app/ and frontend/src/
Count: 11 source-code occurrences (after stripping false positives like _TODO_RE, doc strings about TODOs, and lowercase "todo" enum values).

10 most interesting examples:

File:line	Comment
backend/app/agents/content_ingestion.py:41	"TODO (Phase 6): Wire YouTube Data API v3 for real transcript ingestion."
backend/app/agents/job_match.py:59	"# TODO: connect real job board APIs (LinkedIn, Greenhouse, Lever)"
backend/app/agents/knowledge_graph.py:42	"TODO (Phase 6): Persist updated_mastery to users.metadata JSONB column"
backend/app/services/rag_service.py:6	"TODO (Phase 6): Wire real embeddings via Anthropic and full Pinecone integration."
backend/app/services/attachment_storage.py:60	"TODO(P1-6 → prod): replace with an S3AttachmentStorage impl that uses…"
backend/app/services/student_snapshot_service.py:13	"exists; otherwise 0 with TODO"
backend/app/services/student_snapshot_service.py:263	"TODO: when capstones become a first-class model (their own table or…"
backend/app/api/v1/routes/webhooks.py:196	"# TODO: connect YouTube Data API push notifications"
frontend/src/app/(public)/agents/_agents-grid.tsx:186	description: "Ranks job listings by skill overlap with your profile. TODO: Adzuna / LinkedIn integration." (visible in public UI)
backend/app/services/quality_service.py:182,188,197	Defines _TODO_RE to flag TODOs in student code as a quality signal
Files with "deprecated", "legacy", "old", or "phase" in the filename (excluding .venv* and .claude/worktrees)

backend/app/api/_deprecated.py                                    — @deprecated route decorator + middleware
backend/app/schemas/fading_scaffolds.py                           — schemas
backend/app/services/fading_scaffolds_service.py                  — service
backend/app/services/scaffolding_service.py                       — service
backend/app/templates/email/cold_signup_day_1.html                — email template (matched on "old")
backend/tests/test_core/test_deprecated_decorator.py              — tests for the decorator
backend/tests/test_services/test_fading_scaffolds_service.py
backend/tests/test_services/test_scaffolding_service.py
docs/superpowers/plans/2026-04-08-phase5-polish.md
frontend/src/app/(public)/placement-quiz/_components/placeholder-badge.tsx (matched on "old"? — actually "placeholder")
refactor_phase.md (105 KB, root)
(Worktree-shadow copies of the same files exist under .claude/worktrees/agent-ae7cdee53c38db97d/ — listed in earlier grep output but excluded here as duplicates.)

Additionally, the backend/app/api/ tree contains an _deprecated.py module providing a @deprecated decorator that emits Deprecation: true / Sunset: headers — implying an active deprecation policy (PR2/A2.2/A2.3 cleanup mentioned in the docstring).

backend/app/services/interview_service.py and backend/app/services/interview_service_v2.py co-exist (the third version mock_interview_v3 is referenced in migration 0038_mock_interview_v3.py and per user memory the v3 is canonical; v1+v2 are deprecated for new work but still on disk).

The 18 backend/run_3*_tests.py files — confirmed
All 18 exist on disk:


backend/run_3a14_tests.py
backend/run_3a17_tests.py
backend/run_3a4_tests.py
backend/run_3b101_tests.py
backend/run_3b102_tests.py
backend/run_3b151_tests.py
backend/run_3b152_tests.py
backend/run_3b159_tests.py
backend/run_3b160_tests.py
backend/run_3b163_tests.py
backend/run_3b4_tests.py
backend/run_3b5_tests.py
backend/run_3b7_tests.py
backend/run_3b85_tests.py
backend/run_3b90_tests.py
backend/run_3b91_tests.py
backend/run_3b92_tests.py
backend/run_3b93_tests.py
backend/run_3a4_tests.py — first 20 lines

1  """Standalone runner for 3A-4 clarification helpers."""
2
3  from __future__ import annotations
4
5  import ast
6  import sys
7  import traceback
8  from pathlib import Path
9
10 BACKEND = Path(__file__).parent
11 MODULE = BACKEND / "app" / "services" / "clarification_service.py"
12 TESTS = BACKEND / "tests" / "test_services" / "test_clarification_service.py"
13
14 PURE_FUNCS = {
15     "should_clarify",
16     "generate_followups",
17     "_looks_like_code_response",
18     "_looks_like_concept_response",
19     "_looks_like_code_response",
20     "_looks_like_concept_response",
backend/run_3b5_tests.py — first 20 lines

1  """Standalone runner for 3B #5 weekly-hours helper."""
2
3  from __future__ import annotations
4
5  import ast
6  import sys
7  import traceback
8  from pathlib import Path
9
10 BACKEND = Path(__file__).parent
11 MODULE = BACKEND / "app" / "services" / "goal_contract_service.py"
12 TESTS = BACKEND / "tests" / "test_services" / "test_clarification_service.py"  (actual: test_goal_contract_weekly_hours.py)
13
14 PURE_FUNCS = {"daily_minutes_target"}
15 PURE_CONSTS = {"_WEEKLY_HOURS_TO_DAILY_MINUTES"}
16
17
18 def extract(src: str) -> str:
19     tree = ast.parse(src)
20     kept: list[ast.stmt] = []
Both are AST-extraction scripts that run a subset of test functions in isolation by AST-pruning the source module — they appear to be ad-hoc test harnesses for individual sub-tickets ("3A-4", "3B #5"), parallel to (not part of) the main pytest suite under backend/tests/.

End of report.
