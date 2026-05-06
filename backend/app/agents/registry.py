from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.base_agent import BaseAgent

# Populated by each agent module at import time via register()
AGENT_REGISTRY: dict[str, type[BaseAgent]] = {}


def register(cls: type[BaseAgent]) -> type[BaseAgent]:
    """Class decorator that registers an agent in the global registry."""
    AGENT_REGISTRY[cls.name] = cls
    return cls


def get_agent(name: str) -> BaseAgent:
    """Instantiate an agent by name. Raises KeyError if not found."""
    if name not in AGENT_REGISTRY:
        available = list(AGENT_REGISTRY.keys())
        raise KeyError(f"Agent '{name}' not registered. Available: {available}")
    return AGENT_REGISTRY[name]()


def list_agents() -> list[dict[str, str]]:
    """Return all registered agents as dicts for API responses."""
    return [
        {"name": cls.name, "description": cls.description}
        for cls in AGENT_REGISTRY.values()
    ]


def _ensure_registered() -> None:
    """Force import of all agent modules so they register themselves."""
    import app.agents.adaptive_path  # noqa: F401
    import app.agents.adaptive_quiz  # noqa: F401
    # billing_support — D10 cutover migrated this from BaseAgent to
    # AgenticBaseAgent. Legacy file deleted; the new class lives at
    # app.agents.billing_support and registers via _agentic_registry
    # (loaded by _agentic_loader at FastAPI startup), NOT via the
    # @register decorator that AGENT_REGISTRY consumes. The legacy
    # MOA endpoint that this _ensure_registered serves no longer
    # routes to billing_support — students hit it through the
    # canonical /api/v1/agentic/{flow}/chat endpoint instead.
    # career_coach — D12 CP4 cutover (Checkpoint 4) migrated this
    # from BaseAgent to AgenticBaseAgent. Legacy file deleted; the
    # new class lives at app.agents.career_coach_v2 and registers
    # via _agentic_registry. Same pattern as D10 billing_support.
    # code_review + coding_assistant — D11 cutover (Checkpoint 4)
    # absorbed both into senior_engineer (Pass 3c E2). Their
    # AGENT_REGISTRY entries are no longer reachable via MOA;
    # canonical /api/v1/agentic/{flow}/chat dispatch handles
    # senior_engineer through _agentic_registry.
    import app.agents.community_celebrator  # noqa: F401
    import app.agents.content_ingestion  # noqa: F401
    import app.agents.curriculum_mapper  # noqa: F401
    import app.agents.deep_capturer  # noqa: F401
    import app.agents.disrupt_prevention  # noqa: F401
    import app.agents.job_match  # noqa: F401
    import app.agents.knowledge_graph  # noqa: F401
    import app.agents.mcq_factory  # noqa: F401
    import app.agents.mock_interview  # noqa: F401
    import app.agents.peer_matching  # noqa: F401
    import app.agents.portfolio_builder  # noqa: F401
    import app.agents.progress_report  # noqa: F401
    import app.agents.project_evaluator  # noqa: F401
    # resume_reviewer — D12 CP4 cutover. Legacy file deleted; new
    # class at app.agents.resume_reviewer_v2 registers via
    # _agentic_registry. Same pattern as D12 career_coach above.
    # senior_engineer — D11 cutover (Checkpoint 4) migrated this
    # to the canonical agentic endpoint. The class is now an
    # AgenticBaseAgent subclass loaded via _agentic_loader; legacy
    # MOA dispatch (which AGENT_REGISTRY serves) can no longer
    # reach senior_engineer. Same pattern as billing_support's
    # D10 cutover.
    import app.agents.socratic_tutor  # noqa: F401
    import app.agents.spaced_repetition  # noqa: F401
    import app.agents.student_buddy  # noqa: F401
    # tailored_resume_llm — D12 CP4 cutover removed the @register
    # decorator and BaseAgent inheritance from this module. The
    # class became a plain LLM-call helper (TailoredResumeLLM) that
    # the tailored_resume_service calls directly. The chat-path agent
    # is app.agents.tailored_resume_v2.TailoredResumeShimAgent
    # (AgenticBaseAgent), registered via _agentic_registry. The
    # tailored_resume_llm module no longer needs to be imported
    # here for AGENT_REGISTRY side-effects; the service imports it
    # directly when needed.
    import app.agents.cover_letter  # noqa: F401
