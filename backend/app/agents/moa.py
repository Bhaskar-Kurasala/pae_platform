"""Master Orchestrator Agent (MOA) — LangGraph StateGraph.

Flow:
  classify_intent → route → [SocraticTutor | CodeReview | AdaptiveQuiz] → evaluate_response → END
"""

from typing import Annotated, Any, Literal

import structlog
from pydantic import SecretStr
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from app.agents.base_agent import AgentState
from app.core.config import settings

log = structlog.get_logger()

_CLASSIFIER_PROMPT = """You are the Master Orchestrator for a production AI engineering learning platform.

Your job: classify the student's message and choose the right agent to handle it.

Available agents:
- socratic_tutor: For conceptual questions, "what is X", "explain Y", "help me understand Z"
- code_review: For code submissions, "review my code", "is this correct", code blocks in message
- adaptive_quiz: For practice/testing, "quiz me", "test my knowledge", "MCQ", "practice"

Respond with ONLY one of: socratic_tutor, code_review, adaptive_quiz

Student message: {message}

Agent:"""


class MOAGraphState(TypedDict):
    messages: Annotated[list[Any], add_messages]
    agent_state: AgentState
    routed_to: str
    final_response: str
    evaluation_score: float


def _build_classifier() -> ChatAnthropic:
    return ChatAnthropic(  # type: ignore[call-arg]
        model="claude-haiku-4-5",  # Use Haiku for fast, cheap classification
        anthropic_api_key=SecretStr(settings.anthropic_api_key) if settings.anthropic_api_key else None,
        max_tokens=20,
    )


async def classify_intent(state: MOAGraphState) -> dict[str, Any]:
    """Classify the student's intent and pick an agent."""
    agent_st = state["agent_state"]
    task = agent_st.task

    # Fast keyword check first (avoids LLM call for obvious cases)
    lowered = task.lower()
    if any(w in lowered for w in ("review", "check my code", "```", "def ", "class ", "import ")):
        routed = "code_review"
    elif any(w in lowered for w in ("quiz", "test me", "mcq", "multiple choice", "practice")):
        routed = "adaptive_quiz"
    elif settings.anthropic_api_key:
        # Use Haiku for nuanced classification
        try:
            llm = _build_classifier()
            resp = await llm.ainvoke(
                [HumanMessage(content=_CLASSIFIER_PROMPT.format(message=task))]
            )
            routed = str(resp.content).strip().lower()
            if routed not in {"socratic_tutor", "code_review", "adaptive_quiz"}:
                routed = "socratic_tutor"
        except Exception:
            routed = "socratic_tutor"
    else:
        routed = "socratic_tutor"

    log.info("moa.classify", routed_to=routed, task_preview=task[:50])
    return {"routed_to": routed}


def route_to_agent(state: MOAGraphState) -> Literal["socratic_tutor", "code_review", "adaptive_quiz"]:
    """LangGraph conditional edge: reads routed_to and returns the next node name."""
    return state["routed_to"]  # type: ignore[return-value]


async def run_socratic_tutor(state: MOAGraphState) -> dict[str, Any]:
    from app.agents.socratic_tutor import SocraticTutorAgent

    agent = SocraticTutorAgent()
    result = await agent.run(state["agent_state"])
    return {
        "agent_state": result,
        "final_response": result.response or "",
        "evaluation_score": result.evaluation_score or 0.0,
    }


async def run_code_review(state: MOAGraphState) -> dict[str, Any]:
    from app.agents.code_review import CodeReviewAgent

    agent = CodeReviewAgent()
    result = await agent.run(state["agent_state"])
    return {
        "agent_state": result,
        "final_response": result.response or "",
        "evaluation_score": result.evaluation_score or 0.0,
    }


async def run_adaptive_quiz(state: MOAGraphState) -> dict[str, Any]:
    from app.agents.adaptive_quiz import AdaptiveQuizAgent

    agent = AdaptiveQuizAgent()
    result = await agent.run(state["agent_state"])
    return {
        "agent_state": result,
        "final_response": result.response or "",
        "evaluation_score": result.evaluation_score or 0.0,
    }


def build_moa_graph() -> Any:
    """Build and compile the LangGraph MOA StateGraph."""
    graph = StateGraph(MOAGraphState)

    graph.add_node("classify_intent", classify_intent)
    graph.add_node("socratic_tutor", run_socratic_tutor)
    graph.add_node("code_review", run_code_review)
    graph.add_node("adaptive_quiz", run_adaptive_quiz)

    graph.set_entry_point("classify_intent")
    graph.add_conditional_edges(
        "classify_intent",
        route_to_agent,
        {
            "socratic_tutor": "socratic_tutor",
            "code_review": "code_review",
            "adaptive_quiz": "adaptive_quiz",
        },
    )
    graph.add_edge("socratic_tutor", END)
    graph.add_edge("code_review", END)
    graph.add_edge("adaptive_quiz", END)

    return graph.compile()


# Singleton graph instance — compiled once at startup
_moa_graph: Any = None


def get_moa_graph() -> Any:
    global _moa_graph
    if _moa_graph is None:
        _moa_graph = build_moa_graph()
    return _moa_graph
