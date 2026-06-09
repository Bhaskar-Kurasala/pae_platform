"""Per-agent output schemas.

Each migrated agent gets its own `{agent_name}.py` here. The schema
is the contract the agent's `run()` returns and what the dispatch
layer surfaces back to callers as `AgentResult.structured_output`.

Pass 3c §A.7: every migrated agent returns a structured Pydantic
output, not a free-form string. Three benefits:
  • Supervisor reads structured outputs to make handoff decisions
  • Critic (D5) validates quality against the schema
  • Downstream code (notification builders, dashboards) doesn't parse
    free text.

Conventions:
  • Class name = ToCamelCase(agent_name) + "Output" (e.g.
    BillingSupportOutput).
  • Always set `model_config = ConfigDict(extra='forbid')` so an
    agent that hallucinates an extra key fails validation loudly.
  • String fields the LLM produces are length-bounded — uncapped
    text fields invite token-bloat regressions.
"""

from app.schemas.agents.billing_support import BillingSupportOutput

__all__ = ["BillingSupportOutput"]
