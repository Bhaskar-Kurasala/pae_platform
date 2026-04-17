from pathlib import Path
from typing import Any

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import SecretStr
from tenacity import retry, stop_after_attempt, wait_exponential

from app.agents.base_agent import AgentState, BaseAgent
from app.agents.registry import register
from app.core.config import settings

log = structlog.get_logger()

_PROMPT = (Path(__file__).parent / "prompts" / "deep_capturer.md").read_text()


@register
class DeepCapturerAgent(BaseAgent):
    """Generates weekly synthesis connecting concepts across the curriculum.

    Takes lessons_completed and concepts_seen from context and uses Claude Sonnet
    to produce: (1) a narrative connecting this week's concepts, (2) a surprise
    connection the student might not have noticed, and (3) a sticky metaphor.
    """

    name = "deep_capturer"
    description = (
        "Generates rich weekly synthesis narratives connecting concepts studied, "
        "revealing hidden connections and memorable metaphors. Runs on a schedule."
    )
    trigger_conditions = [
        "weekly summary",
        "concept connections",
        "synthesis",
        "big picture",
    ]
    model = "claude-sonnet-4-6"

    def _build_llm(self) -> ChatAnthropic:
        return ChatAnthropic(  # type: ignore[call-arg]
            model=self.model,
            anthropic_api_key=SecretStr(settings.anthropic_api_key) if settings.anthropic_api_key else None,
            max_tokens=1024,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _synthesise(
        self,
        llm: ChatAnthropic,
        lessons: list[str],
        concepts: list[str],
        week_theme: str,
    ) -> str:
        """Call Claude Sonnet to produce the weekly synthesis markdown."""
        lessons_text = "\n".join(f"- {lesson}" for lesson in lessons) if lessons else "- No lessons recorded yet"
        concepts_text = "\n".join(f"- {c}" for c in concepts) if concepts else "- No concepts recorded yet"

        messages: list[Any] = [
            SystemMessage(content=_PROMPT),
            HumanMessage(
                content=(
                    f"Week theme: {week_theme}\n\n"
                    f"Lessons completed this week:\n{lessons_text}\n\n"
                    f"Concepts encountered:\n{concepts_text}\n\n"
                    "Please produce a rich weekly synthesis in Markdown with these three sections:\n\n"
                    "## Concept Connections\n"
                    "A narrative (3-4 sentences) showing how this week's concepts connect and "
                    "reinforce each other. Be specific — mention the actual concepts by name.\n\n"
                    "## Surprise Connection\n"
                    "One non-obvious connection between two concepts that the student might not "
                    "have noticed. Explain WHY it matters for production AI engineering.\n\n"
                    "## Sticky Metaphor\n"
                    "A single memorable metaphor that makes the week's central concept stick. "
                    "Use everyday language — no jargon.\n\n"
                    "Keep the total response under 400 words. Make it feel like insight, not summary."
                )
            ),
        ]
        response = await llm.ainvoke(messages)
        return str(response.content)

    async def execute(self, state: AgentState) -> AgentState:
        lessons_completed: list[str] = state.context.get("lessons_completed", [])
        concepts_seen: list[str] = state.context.get("concepts_seen", [])
        week_theme: str = state.context.get("week_theme", "Production AI Engineering Fundamentals")

        if settings.anthropic_api_key:
            try:
                llm = self._build_llm()
                synthesis = await self._synthesise(llm, lessons_completed, concepts_seen, week_theme)
            except Exception as exc:
                self._log.warning("deep_capturer.llm_failed", error=str(exc))
                synthesis = self._fallback_synthesis(lessons_completed, concepts_seen, week_theme)
        else:
            synthesis = self._fallback_synthesis(lessons_completed, concepts_seen, week_theme)

        return state.model_copy(
            update={
                "response": synthesis,
                "context": {**state.context, "weekly_synthesis": synthesis},
            }
        )

    def _fallback_synthesis(
        self,
        lessons: list[str],
        concepts: list[str],
        week_theme: str,
    ) -> str:
        """Return a structured fallback when the LLM is unavailable."""
        concept_list = ", ".join(concepts[:4]) if concepts else "RAG, LangGraph, Pydantic v2"
        return (
            f"## Concept Connections\n\n"
            f"This week's theme — **{week_theme}** — runs through everything you studied. "
            f"The concepts {concept_list} all orbit the same core idea: "
            f"reliable state management at every layer of a production AI system.\n\n"
            f"## Surprise Connection\n\n"
            f"Pydantic validation and LangGraph state schemas solve the same problem at different "
            f"scales: both enforce a contract on data shape, preventing silent failures that are "
            f"nearly impossible to debug in production.\n\n"
            f"## Sticky Metaphor\n\n"
            f"Think of a production AI system like a relay race: each agent is a runner, "
            f"the `AgentState` is the baton, and Pydantic is the rule that says the baton "
            f"must be passed with both hands — no fumbles allowed."
        )

    async def evaluate(self, state: AgentState) -> AgentState:
        response = state.response or ""
        has_connections = "## Concept Connections" in response or "connections" in response.lower()
        has_metaphor = "## Sticky Metaphor" in response or "metaphor" in response.lower()
        score = 0.9 if (has_connections and has_metaphor) else (0.6 if has_connections else 0.4)
        return state.model_copy(update={"evaluation_score": score})
