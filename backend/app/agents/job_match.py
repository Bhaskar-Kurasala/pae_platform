import json
from pathlib import Path
from typing import Any

import structlog

from app.agents.base_agent import AgentState, BaseAgent
from app.agents.registry import register

log = structlog.get_logger()

_PROMPT_PATH = Path(__file__).parent / "prompts" / "job_match.md"

_MOCK_JOB_LISTINGS: list[dict[str, Any]] = [
    {
        "title": "Senior ML Engineer",
        "company": "Anthropic",
        "match_score": 0.9,
        "skills_match": ["LangGraph", "RAG", "Python", "FastAPI"],
        "url": "https://example.com/job/1",
        "description": "Build production LLM systems at scale. Work on Claude's tooling and evaluation pipelines.",
        "salary_range": "$180k–$280k",
    },
    {
        "title": "AI Platform Engineer",
        "company": "OpenAI",
        "match_score": 0.85,
        "skills_match": ["RAG", "Python", "Vector Databases", "Async APIs"],
        "url": "https://example.com/job/2",
        "description": "Design and maintain the inference infrastructure powering GPT models.",
        "salary_range": "$200k–$320k",
    },
    {
        "title": "LLM Applications Engineer",
        "company": "Scale AI",
        "match_score": 0.78,
        "skills_match": ["LangChain", "FastAPI", "PostgreSQL", "Pydantic"],
        "url": "https://example.com/job/3",
        "description": "Build evaluation pipelines and RLHF tooling for fine-tuning LLMs.",
        "salary_range": "$160k–$240k",
    },
]


@register
class JobMatchAgent(BaseAgent):
    name = "job_match"
    description = "Matches student skills to relevant job listings. Stub for job board API integration."
    trigger_conditions = [
        "job match",
        "find jobs",
        "job listings",
        "career opportunities",
        "hiring",
    ]
    model = "claude-sonnet-4-6"

    async def execute(self, state: AgentState) -> AgentState:
        # TODO: connect real job board APIs (LinkedIn, Greenhouse, Lever)
        student_skills: list[str] = state.context.get("skills", [])

        # Filter and rank listings by skills overlap when skills are provided
        listings = list(_MOCK_JOB_LISTINGS)
        if student_skills:
            for listing in listings:
                overlap = len(set(student_skills) & set(listing["skills_match"]))
                listing["match_score"] = round(min(1.0, overlap / max(len(student_skills), 1)), 2)
            listings.sort(key=lambda x: x["match_score"], reverse=True)

        return state.model_copy(
            update={
                "response": json.dumps(listings, indent=2),
                "context": {**state.context, "job_listings": listings},
            }
        )
