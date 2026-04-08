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
    import app.agents.adaptive_quiz  # noqa: F401
    import app.agents.code_review  # noqa: F401
    import app.agents.socratic_tutor  # noqa: F401
