from pathlib import Path
from typing import Any

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from pydantic import SecretStr

from app.agents.base_agent import AgentState, BaseAgent
from app.agents.registry import register
from app.core.config import settings

log = structlog.get_logger()

_PROMPT = (Path(__file__).parent / "prompts" / "socratic_tutor.md").read_text()


@tool
async def search_course_content(query: str, lesson_id: str | None = None) -> str:
    """Search course content via RAG pipeline (Pinecone stub).

    Args:
        query: The search query.
        lesson_id: Optional lesson to restrict search scope.

    Returns:
        Relevant course content as a string.
    """
    # STUB: Returns mock content until Pinecone is wired up in Phase 4
    return (
        f"[Course content for '{query}']\n"
        "Relevant excerpt: Retrieval Augmented Generation (RAG) combines a retrieval step "
        "that fetches relevant documents from a vector store with an LLM generation step. "
        "This solves the knowledge cutoff and hallucination problems by grounding responses "
        "in real retrieved context."
    )


@tool
async def get_student_progress(student_id: str) -> str:
    """Retrieve the student's current progress and completed lessons.

    Args:
        student_id: The student's UUID.

    Returns:
        Summary of student progress as a string.
    """
    # Stub — in Phase 4 this hits the progress repo
    return f"[Progress for student {student_id}]\nCompleted: 3 lessons. Current lesson: Introduction to LangGraph."


@register
class SocraticTutorAgent(BaseAgent):
    name = "socratic_tutor"
    description = "Guides students to understanding through Socratic questioning. Never gives direct answers."
    trigger_conditions = [
        "explain",
        "what is",
        "how does",
        "help me understand",
        "I don't get",
        "confused about",
        "question about",
    ]
    model = "claude-sonnet-4-6"

    def _build_llm(self) -> ChatAnthropic:
        return ChatAnthropic(  # type: ignore[call-arg]
            model=self.model,
            anthropic_api_key=SecretStr(settings.anthropic_api_key) if settings.anthropic_api_key else None,
            max_tokens=1024,
        )

    def _build_messages(self, state: AgentState) -> list[Any]:
        messages: list[Any] = [SystemMessage(content=_PROMPT)]

        # Include course context if available
        if state.context.get("course_content"):
            messages.append(
                HumanMessage(
                    content=f"[CONTEXT: {state.context['course_content']}]"
                )
            )

        # Prior conversation
        for turn in state.conversation_history[-6:]:  # Last 6 turns
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            else:
                from langchain_core.messages import AIMessage
                messages.append(AIMessage(content=content))

        messages.append(HumanMessage(content=state.task))
        return messages

    async def execute(self, state: AgentState) -> AgentState:
        llm = self._build_llm()
        messages = self._build_messages(state)

        # Optionally search course content
        course_content = await search_course_content.ainvoke({"query": state.task})
        if course_content:
            state = state.model_copy(
                update={"context": {**state.context, "course_content": course_content}}
            )
            messages = self._build_messages(state)
            state = state.model_copy(
                update={"tools_used": state.tools_used + ["search_course_content"]}
            )

        response = await llm.ainvoke(messages)
        content = str(response.content)

        return state.model_copy(update={"response": content})

    async def evaluate(self, state: AgentState) -> AgentState:
        """A good Socratic response must contain at least one question."""
        response = state.response or ""
        has_question = "?" in response
        score = 0.9 if has_question else 0.3
        return state.model_copy(update={"evaluation_score": score})
