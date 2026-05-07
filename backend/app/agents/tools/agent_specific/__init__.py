"""Agent-specific tools per Pass 3d §A.3.

Each agent gets a sub-package; tool bodies are visible only to that
agent's invocation context (enforced by the @tool decorator's
permissions + the agent's own tool_call dispatch).

D10 CP3: billing_support (4 tools).
D11 CP1: senior_engineer (2 memory-read tools; sandbox deferred to D11.5).
D12 CP1: career_coach (4 read tools), study_planner (6 tools including
          2 write paths), resume_reviewer (2 read tools), tailored_resume
          (2 read tools for chat path).
D11.5 (deferred from D11): sandbox (run_in_sandbox + run_tests).
"""

from app.agents.tools.agent_specific import billing_support  # noqa: F401
from app.agents.tools.agent_specific import career_coach  # noqa: F401
from app.agents.tools.agent_specific import resume_reviewer  # noqa: F401
from app.agents.tools.agent_specific import sandbox  # noqa: F401
from app.agents.tools.agent_specific import senior_engineer  # noqa: F401
from app.agents.tools.agent_specific import study_planner  # noqa: F401
from app.agents.tools.agent_specific import tailored_resume  # noqa: F401

__all__ = [
    "billing_support",
    "career_coach",
    "resume_reviewer",
    "sandbox",
    "senior_engineer",
    "study_planner",
    "tailored_resume",
]
