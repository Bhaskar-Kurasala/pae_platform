# All 20 AI Agents — Production AI Engineering Platform

All agents extend `BaseAgent`, are registered via `@register`, and flow through
the Master Orchestrator Agent (MOA) LangGraph StateGraph.

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
| 4 | `coding_assistant` | `coding_assistant.py` | claude-sonnet-4-6 | help with code, debug, fix my code | — | PR-style inline comments |
| 5 | `student_buddy` | `student_buddy.py` | claude-sonnet-4-6 | tldr, eli5, quick explanation | — | < 200 word responses |
| 6 | `deep_capturer` | `deep_capturer.py` | — | weekly summary, concept connections | — | Stub; TODO: real weekly synthesis |

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
| 12 | `project_evaluator` | `project_evaluator.py` | claude-sonnet-4-6 | evaluate project, capstone | — | 5-dimension rubric, score 0-100 |
| 13 | `progress_report` | `progress_report.py` | claude-sonnet-4-6 | my progress, weekly report, how am I doing | — | Narrative weekly summary |

## Category 4: Career Agents

| # | Agent | File | Model | Trigger Keywords | Tools | Notes |
|---|---|---|---|---|---|---|
| 14 | `mock_interview` | `mock_interview.py` | claude-sonnet-4-6 | mock interview, system design, interview prep | — | FAANG-style AI engineering interviews |
| 15 | `portfolio_builder` | `portfolio_builder.py` | claude-sonnet-4-6 | build portfolio, showcase project | — | Markdown portfolio entries; eval checks for `#` heading |
| 16 | `job_match` | `job_match.py` | — | find jobs, job listings, career | — | Stub; mock listings with skill overlap ranking |

## Category 5: Engagement Agents

| # | Agent | File | Model | Trigger Keywords | Tools | Notes |
|---|---|---|---|---|---|---|
| 17 | `disrupt_prevention` | `disrupt_prevention.py` | claude-sonnet-4-6 | re-engage, inactive, churn | — | No-op if days_inactive < 3 |
| 18 | `peer_matching` | `peer_matching.py` | — | study partner, find peers | — | Stub; topic-overlap mock matching |
| 19 | `community_celebrator` | `community_celebrator.py` | claude-sonnet-4-6 | celebrate, milestone, completed | — | Multi-format celebration messages |
| 20 | `code_review` | `code_review.py` | claude-sonnet-4-6 | review my code, check my code | `analyze_code` (ruff) | Structured JSON with score 0-100 |

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

## Adding a New Agent

1. Create `app/agents/{name}.py` extending `BaseAgent`
2. Add `@register` decorator to the class
3. Set `name`, `description`, `trigger_conditions`, `model`
4. Implement `async execute(self, state: AgentState) -> AgentState`
5. Create `app/agents/prompts/{name}.md` system prompt
6. Add import to `_ensure_registered()` in `registry.py`
7. Add keyword patterns to `_KEYWORD_MAP` in `moa.py`
8. Write test in `tests/test_agents/test_{name}.py`

## Stubs — TODO List

| Agent | Missing |
|---|---|
| `content_ingestion` | YouTube Data API v3, PyGitHub commit reader |
| `deep_capturer` | Weekly synthesis from real student progress data |
| `knowledge_graph` | JSONB persistence to `users.metadata` column |
| `job_match` | Adzuna / LinkedIn job board API |
| `peer_matching` | Vector similarity matching via Pinecone |
| `socratic_tutor` | Real Pinecone RAG for `search_course_content` |
