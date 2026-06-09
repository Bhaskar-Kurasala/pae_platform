# All ~28 AI Agents — Production AI Engineering Platform

Agents live in a **dual-registry** architecture:

- **Legacy agents (17)** extend `BaseAgent`, are registered via `@register`
  (`AGENT_REGISTRY`), and flow through the Master Orchestrator Agent (MOA)
  LangGraph `StateGraph` in `app/agents/moa.py`. Wired to `routes/agents.py`
  and `routes/stream.py`. These are documented in the categories below.
- **Agentic agents (11)** subclass `AgenticBaseAgent`, auto-register via
  `__init_subclass__`, are loaded by `app/agents/_agentic_loader.py`, and are
  dispatched via the canonical `/api/v1/agentic/{flow}/chat` endpoint. See the
  "Agentic Agents" section below.

## MOA — Master Orchestrator Agent

| Property | Value |
|---|---|
| File | `app/agents/moa.py` |
| Model | `claude-haiku-4-5` (classifier) |
| Role | Classifies intent → routes to correct agent |
| Routing | 15-pattern keyword map → LLM fallback |

---

## Category 1: Creation Agents

| # | Agent | File | Model | Trigger Keywords | Tools | Notes |
|---|---|---|---|---|---|---|
| 1 | `content_ingestion` | `content_ingestion.py` | — | ingest, youtube, github push | — | Stub; TODO: YouTube + GitHub APIs |
| 2 | `curriculum_mapper` | `curriculum_mapper.py` | claude-sonnet-4-6 | map curriculum, lesson order | — | Maps content metadata to curriculum |
| 3 | `mcq_factory` | `mcq_factory.py` | claude-sonnet-4-6 | generate questions, create mcq | — | **Real** — generates 5 MCQs per call |
| 4 | `student_buddy` | `student_buddy.py` | claude-sonnet-4-6 | tldr, eli5, quick explanation | — | < 200 word responses |
| 5 | `deep_capturer` | `deep_capturer.py` | — | weekly summary, concept connections | — | Stub; TODO: real weekly synthesis |

> Note: `coding_assistant` was absorbed into the agentic `senior_engineer` agent
> (see Agentic Agents below) and no longer exists as a legacy `@register` agent.

## Category 2: Learning Agents

| # | Agent | File | Model | Trigger Keywords | Tools | Notes |
|---|---|---|---|---|---|---|
| 7 | `socratic_tutor` | `socratic_tutor.py` | claude-sonnet-4-6 | what is, explain, help me understand | `search_course_content` (stub) | Eval: must contain `?` |
| 8 | `spaced_repetition` | `spaced_repetition.py` | — | review, flashcard, due cards | — | Full SM-2 algorithm (no LLM) |
| 9 | `knowledge_graph` | `knowledge_graph.py` | — | concept mastery, skill map | — | Stub; EMA mastery scoring |
| 10 | `adaptive_path` | `adaptive_path.py` | claude-sonnet-4-6 | learning path, study plan, next lesson | — | Uses quiz_scores from context |

## Category 3: Analytics Agents

| # | Agent | File | Model | Trigger Keywords | Tools | Notes |
|---|---|---|---|---|---|---|
| 11 | `adaptive_quiz` | `adaptive_quiz.py` | claude-sonnet-4-6 | quiz me, MCQ, multiple choice | — | 3-question bank + LLM fallback; adaptive difficulty |
| 12 | `progress_report` | `progress_report.py` | claude-sonnet-4-6 | my progress, weekly report, how am I doing | — | Narrative weekly summary |

> Note: `project_evaluator` is now an agentic `AgenticBaseAgent`
> (`project_evaluator.py`), not a legacy `@register` agent — see Agentic Agents below.

## Category 4: Career Agents

| # | Agent | File | Model | Trigger Keywords | Tools | Notes |
|---|---|---|---|---|---|---|
| 13 | `portfolio_builder` | `portfolio_builder.py` | claude-sonnet-4-6 | build portfolio, showcase project | — | Markdown portfolio entries; eval checks for `#` heading |
| 14 | `cover_letter` | `cover_letter.py` | claude-sonnet-4-6 | cover letter, write a cover letter | — | 250-word cover letter; bundled with tailored resume |
| 15 | `job_match` | `job_match.py` | — | find jobs, job listings, career | — | Stub; mock listings with skill overlap ranking |

> Note: `mock_interview` is now an agentic `AgenticBaseAgent` (`mock_interview.py`),
> not a legacy `@register` agent — see Agentic Agents below.

## Category 5: Engagement Agents

| # | Agent | File | Model | Trigger Keywords | Tools | Notes |
|---|---|---|---|---|---|---|
| 16 | `disrupt_prevention` | `disrupt_prevention.py` | claude-sonnet-4-6 | re-engage, inactive, churn | — | No-op if days_inactive < 3 |
| 17 | `peer_matching` | `peer_matching.py` | — | study partner, find peers | — | Stub; topic-overlap mock matching |
| 18 | `community_celebrator` | `community_celebrator.py` | claude-sonnet-4-6 | celebrate, milestone, completed | — | Multi-format celebration messages |

> Note: `code_review` was absorbed into the agentic `senior_engineer` agent
> (see Agentic Agents below) and no longer exists as a legacy `@register` agent.

---

## Agentic Agents (11)

These subclass `AgenticBaseAgent[InputModel]`, auto-register via
`__init_subclass__`, are loaded by `app/agents/_agentic_loader.py`, and are
dispatched via `/api/v1/agentic/{flow}/chat` (not through the MOA).

| Agent class | File |
|---|---|
| `CareerCoachAgent` | `career_coach_v2.py` |
| `SeniorEngineerAgent` (absorbs `code_review` + `coding_assistant`) | `senior_engineer.py` |
| `MockInterviewAgent` | `mock_interview.py` |
| `ProjectEvaluatorAgent` | `project_evaluator.py` |
| `ResumeReviewerAgent` | `resume_reviewer_v2.py` |
| `TailoredResumeShimAgent` | `tailored_resume_v2.py` |
| `StudyPlannerAgent` | `study_planner_v2.py` |
| `PracticeCuratorAgent` | `practice_curator.py` |
| `BillingSupportAgent` | `billing_support.py` |
| `Supervisor` | `supervisor.py` |
| `LearningCoach` | `example_learning_coach.py` |

---

## AgentState Schema

```python
class AgentState(BaseModel):
    student_id: str
    conversation_history: list[dict]   # Last 6 turns injected into LLM
    task: str                          # Current student message
    context: dict                      # Agent-specific data (code, quiz_state, etc.)
    response: str | None               # Agent's response text
    tools_used: list[str]              # Tools called during execution
    evaluation_score: float | None     # 0.0–1.0 quality score
    agent_name: str | None             # Set by run() after execute()
    error: str | None                  # Set if execute() raises
    metadata: dict                     # Free-form agent metadata
```

## Adding a New Agent (legacy `@register` path)

> The steps below describe the **legacy** MOA / `@register` path. New agents are
> generally built as agentic `AgenticBaseAgent` subclasses instead (auto-registered
> via `__init_subclass__`, loaded by `_agentic_loader.py`, dispatched via
> `/api/v1/agentic/{flow}/chat`).

1. Create `app/agents/{name}.py` extending `BaseAgent`
2. Add `@register` decorator to the class
3. Set `name`, `description`, `trigger_conditions`, `model`
4. Implement `async execute(self, state: AgentState) -> AgentState`
5. Create `app/agents/prompts/{name}.md` system prompt
6. Add import to `_ensure_registered()` in `registry.py`
7. Add keyword patterns to `_KEYWORD_MAP` in `moa.py`
8. Write test in `tests/test_agents/test_{name}.py`

## Stubs — TODO List

`job_match` is now the only **pure stub** agent. Other agents previously listed
here have since been implemented or partially wired; remaining gaps are tracked
below as TODOs rather than full stubs.

| Agent | Status / Missing |
|---|---|
| `job_match` | **Pure stub** — mock listings; needs Adzuna / LinkedIn job board API |
| `content_ingestion` | TODO: YouTube Data API v3, PyGitHub commit reader |
| `deep_capturer` | TODO: weekly synthesis from real student progress data |
| `knowledge_graph` | TODO: JSONB persistence to `users.metadata` column |
| `peer_matching` | TODO: vector similarity matching via Pinecone |
| `socratic_tutor` | TODO: real Pinecone RAG for `search_course_content` |
