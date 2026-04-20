"""Master Orchestrator Agent (MOA) — LangGraph StateGraph.

Flow:
  classify_intent → route → [specific agent] → END

All 20 agents are registered and routable. The classifier uses fast keyword
matching first, then falls back to claude-haiku-4-5 for nuanced cases.
"""

from typing import Annotated, Any

import structlog
from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from app.agents.base_agent import AgentState
from app.core.config import settings

log = structlog.get_logger()

# All routable agent names
ROUTABLE_AGENTS = [
    "socratic_tutor",
    "code_review",
    "adaptive_quiz",
    "mcq_factory",
    "coding_assistant",
    "student_buddy",
    "content_ingestion",
    "curriculum_mapper",
    "deep_capturer",
    "spaced_repetition",
    "knowledge_graph",
    "adaptive_path",
    "project_evaluator",
    "progress_report",
    "mock_interview",
    "portfolio_builder",
    "job_match",
    "disrupt_prevention",
    "peer_matching",
    "community_celebrator",
    # WS4 new agents
    "career_coach",
    "resume_reviewer",
    "billing_support",
    # Studio context-aware tutor (P1-B-3)
    "studio_tutor",
]

_CLASSIFIER_PROMPT = """You are the Master Orchestrator for a production AI engineering learning platform.

Your job: classify the student's message and choose the right agent.

Available agents and their purposes:
- socratic_tutor: conceptual questions, "what is X", "explain Y", "how does Z work"
- code_review: reviewing code for correctness and production readiness
- adaptive_quiz: MCQ practice, "quiz me", "test my knowledge", "multiple choice"
- mcq_factory: generating new questions from content
- coding_assistant: coding help, debugging, "fix my code", "PR review"
- student_buddy: quick explanations, "tldr", "eli5", "summarize briefly"
- content_ingestion: ingesting YouTube/GitHub content
- curriculum_mapper: curriculum updates, lesson ordering
- deep_capturer: weekly synthesis, concept connections
- spaced_repetition: flashcard review, "due cards", "spaced repetition"
- knowledge_graph: concept mastery updates, "skill map"
- adaptive_path: learning path, "what should I study next", "study plan"
- project_evaluator: capstone evaluation, "grade my project"
- progress_report: "how am I doing", "my progress", "weekly report"
- mock_interview: interview practice, "system design", "mock interview"
- portfolio_builder: "build my portfolio", "showcase project"
- job_match: "find jobs", "job listings", "career opportunities"
- disrupt_prevention: re-engagement messages, inactive students
- peer_matching: "study partner", "find peers", "study group"
- community_celebrator: celebrations, milestones, "I finished", "I passed"
- career_coach: career planning, "become AI engineer", skill roadmap, career transition
- resume_reviewer: resume review, CV feedback, resume critique, before/after improvements
- billing_support: billing questions, subscription, refund, cancel, upgrade plan

Respond with ONLY the agent name. No explanation.

Student message: {message}

Agent:"""

# Fast keyword routing — avoids LLM call for the most common patterns
_KEYWORD_MAP: list[tuple[list[str], str]] = [
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
    # DISC-57 — previously this sat below socratic_tutor's broad patterns and
    # "re-engage inactive student" routed to socratic_tutor. The disrupt_prevention
    # agent is the correct target for churn-risk nudges.
    (["re-engage", "reengage", "inactive student", "churn risk", "win back", "nudge student"], "disrupt_prevention"),
    # WS4 new agent keyword patterns
    (["career plan", "career roadmap", "become ai engineer", "what skills do i need", "career transition", "career coaching"], "career_coach"),
    (["review my resume", "resume feedback", "improve cv", "resume critique", "check my resume"], "resume_reviewer"),
    (["billing", "subscription", "refund", "cancel subscription", "upgrade plan", "payment issue", "invoice"], "billing_support"),
]


class MOAGraphState(TypedDict, total=False):
    messages: Annotated[list[Any], add_messages]
    agent_state: AgentState
    routed_to: str
    # P2-4 — why the router picked that agent. One of:
    #   "keyword:<pattern>"  for a hit in _KEYWORD_MAP
    #   "llm_classifier"     for the claude-haiku fallback
    #   "default_fallback"   when nothing matched and LLM was unavailable
    routing_reason: str | None
    final_response: str
    evaluation_score: float


def _build_classifier():
    from app.agents.llm_factory import build_classifier_llm
    return build_classifier_llm()


def _keyword_route(task: str) -> str | None:
    """Back-compat wrapper that returns just the routed agent name.

    Callers that want the matched pattern for telemetry / UI should use
    :func:`keyword_route_with_reason` instead — it returns the first
    matched keyword alongside the agent so the UI can render something
    like "Routed to Tutor · keyword:explain · change" (P2-4).
    """
    match = keyword_route_with_reason(task)
    return match[0] if match else None


def keyword_route_with_reason(task: str) -> tuple[str, str] | None:
    """Return (agent, matched_keyword) or None if no keyword pattern hit.

    The matched keyword doubles as a human-readable reason — we just
    prefix it with ``keyword:`` at the call site so consumers can tell a
    keyword hit apart from an LLM classification (``llm_classifier``) or
    the default fallback (``default_fallback``).
    """
    lowered = task.lower()
    for keywords, agent in _KEYWORD_MAP:
        for kw in keywords:
            if kw in lowered:
                return agent, kw.strip()
    return None


async def classify_intent(state: MOAGraphState) -> dict[str, Any]:
    """Classify the student's intent and pick an agent."""
    task = state["agent_state"].task

    # 1. Fast keyword check
    match = keyword_route_with_reason(task)
    routed: str | None = match[0] if match else None
    reason: str | None = f"keyword:{match[1]}" if match else None

    # 2. LLM classification for nuanced cases
    if not routed and (settings.minimax_api_key or settings.anthropic_api_key):
        try:
            llm = _build_classifier()
            resp = await llm.ainvoke(
                [HumanMessage(content=_CLASSIFIER_PROMPT.format(message=task))]
            )
            candidate = str(resp.content).strip().lower().split()[0]
            if candidate in ROUTABLE_AGENTS:
                routed = candidate
                reason = "llm_classifier"
        except Exception as exc:
            log.warning("moa.classify.llm_failed", error=str(exc))

    # 3. Default fallback
    if routed is None:
        routed = "socratic_tutor"
        reason = reason or "default_fallback"

    log.info("moa.classify", routed_to=routed, reason=reason, task_preview=task[:60])
    return {"routed_to": routed, "routing_reason": reason}


async def _run_any_agent(state: MOAGraphState) -> dict[str, Any]:
    """Generic node that runs whichever agent was routed to."""
    from app.agents.registry import _ensure_registered, get_agent

    _ensure_registered()
    agent_name = state["routed_to"]
    try:
        agent = get_agent(agent_name)
    except KeyError:
        agent_name = "socratic_tutor"
        agent = get_agent(agent_name)

    result = await agent.run(state["agent_state"])
    return {
        "agent_state": result,
        "final_response": result.response or "",
        "evaluation_score": result.evaluation_score or 0.0,
    }


def build_moa_graph() -> Any:
    """Build and compile the LangGraph MOA StateGraph.

    Uses a single generic 'run_agent' node that dispatches to any registered
    agent — avoids adding a new node for every new agent.
    """
    graph = StateGraph(MOAGraphState)

    graph.add_node("classify_intent", classify_intent)
    graph.add_node("run_agent", _run_any_agent)

    graph.set_entry_point("classify_intent")
    graph.add_edge("classify_intent", "run_agent")
    graph.add_edge("run_agent", END)

    return graph.compile()


_moa_graph: Any = None


def get_moa_graph() -> Any:
    global _moa_graph
    if _moa_graph is None:
        _moa_graph = build_moa_graph()
    return _moa_graph
