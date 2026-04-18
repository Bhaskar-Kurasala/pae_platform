# ADD TO registry.py: import app.agents.career_coach  # noqa: F401

import re
from pathlib import Path
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from tenacity import retry, stop_after_attempt, wait_exponential

from app.agents.base_agent import AgentState, BaseAgent
from app.agents.registry import register
from app.core.config import settings

log = structlog.get_logger()

_PROMPT = (Path(__file__).parent / "prompts" / "career_coach.md").read_text()


@register
class CareerCoachAgent(BaseAgent):
    """Generates personalised 90-day AI engineering career action plans.

    Takes optional context: current_role, target_role, skills, timeline_months,
    portfolio_items. Produces: (1) 90-day plan with weekly milestones, (2) skill
    gap analysis, (3) 3 portfolio project recommendations, (4) networking strategy.
    """

    name = "career_coach"
    description = (
        "Provides personalised AI engineering career coaching: 90-day action plans, "
        "skill gap analysis, portfolio project recommendations, and networking strategy."
    )
    trigger_conditions = [
        "career plan",
        "career roadmap",
        "become ai engineer",
        "what skills do i need",
        "career transition",
        "career coaching",
    ]
    model = "claude-sonnet-4-6"

    def _build_llm(self, max_tokens: int = 1024):
        from app.agents.llm_factory import build_llm
        return build_llm(max_tokens=max_tokens)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _call_llm(self, llm: Any, context_block: str, task: str) -> str:
        messages: list[Any] = [
            SystemMessage(content=_PROMPT),
            HumanMessage(
                content=(
                    f"{context_block}\n\n"
                    f"Student request: {task}\n\n"
                    "Please provide your career coaching response with:\n"
                    "1. Honest assessment of their current position\n"
                    "2. 90-day action plan with weekly milestones\n"
                    "3. Top 3 skill gaps to close (numbered)\n"
                    "4. 3 portfolio projects that will impress hiring managers (numbered)\n"
                    "5. Specific networking strategy for the AI engineering community"
                )
            ),
        ]
        response = await llm.ainvoke(messages)
        return str(response.content)

    async def execute(self, state: AgentState) -> AgentState:
        current_role: str = state.context.get("current_role", "not specified")
        target_role: str = state.context.get("target_role", "AI Engineer / ML Engineer")
        skills: list[str] = state.context.get("skills", [])
        timeline_months: int = int(state.context.get("timeline_months", 6))
        portfolio_items: list[str] = state.context.get("portfolio_items", [])

        context_block = (
            f"Student profile:\n"
            f"- Current role: {current_role}\n"
            f"- Target role: {target_role}\n"
            f"- Current skills: {', '.join(skills) if skills else 'not specified'}\n"
            f"- Target timeline: {timeline_months} months\n"
            f"- Existing portfolio: {', '.join(portfolio_items) if portfolio_items else 'none listed'}"
        )

        if settings.minimax_api_key or settings.anthropic_api_key:
            try:
                llm = self._build_llm()
                response_text = await self._call_llm(llm, context_block, state.task)
            except Exception as exc:
                self._log.warning("career_coach.llm_failed", error=str(exc))
                response_text = self._fallback_response(current_role, target_role, timeline_months)
        else:
            response_text = self._fallback_response(current_role, target_role, timeline_months)

        return state.model_copy(update={"response": response_text})

    def _fallback_response(self, current_role: str, target_role: str, timeline_months: int) -> str:
        return (
            f"## Career Coaching: {current_role} → {target_role}\n\n"
            f"**Note**: LLM unavailable — showing template plan.\n\n"
            f"### 90-Day Action Plan\n\n"
            f"1. **Weeks 1-2**: Audit current skills against job descriptions for {target_role} roles\n"
            f"2. **Weeks 3-6**: Complete PAE Platform core curriculum (RAG, LangGraph, FastAPI)\n"
            f"3. **Weeks 7-10**: Build first portfolio project (production RAG pipeline)\n"
            f"4. **Weeks 11-12**: Apply to 5 target companies; schedule mock interviews\n\n"
            f"### Top 3 Skill Gaps\n\n"
            f"1. LangGraph stateful orchestration\n"
            f"2. Production deployment (Docker, monitoring, CI/CD)\n"
            f"3. LLM evaluation and testing strategies\n\n"
            f"### 3 Portfolio Projects\n\n"
            f"1. Production RAG pipeline with Pinecone + FastAPI\n"
            f"2. Multi-agent LangGraph system with evaluation harness\n"
            f"3. Open-source LLM fine-tuning experiment with documented results\n\n"
            f"### Networking Strategy\n\n"
            f"- Contribute to LangChain/LangGraph GitHub issues\n"
            f"- Write 2 blog posts about production AI challenges\n"
            f"- Attend one AI engineering meetup per month"
        )

    async def evaluate(self, state: AgentState) -> AgentState:
        """Score based on whether response contains a numbered action plan."""
        response = state.response or ""
        # Check for numbered list items (e.g. "1.", "1 .", or "## 1")
        has_numbered_plan = bool(re.search(r"\b[1-5]\.\s", response))
        has_skills_section = "skill" in response.lower()
        score = 0.9 if (has_numbered_plan and has_skills_section) else (0.6 if has_numbered_plan else 0.4)
        return state.model_copy(update={"evaluation_score": score})
