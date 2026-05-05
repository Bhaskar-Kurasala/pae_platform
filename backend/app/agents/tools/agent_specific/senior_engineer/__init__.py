"""D11 / Pass 3d §F.2 — senior_engineer-specific tools.

Two read tools land in D11. Both wrap `MemoryStore.recall` against
agent_memory rows the senior_engineer agent itself wrote on prior
turns.

  • lookup_prior_submissions — semantic search over `submission:code:*`
    keys; returns the N most similar prior code submissions
  • lookup_prior_reviews     — structured recall over `feedback:code_review:*`
    keys; returns recent reviews this student received

Sandbox tools (run_in_sandbox, run_static_analysis, run_tests) per
Pass 3d §E.3 are DEFERRED to D14 per the D11 prompt's sandbox
deferral. The agent's prompt explicitly does NOT claim execution
capability; v1 is LLM-only review.

Importing this package registers both tools with the global tool
registry via the @tool decorator — see app.agents.tools.__init__'s
ensure_tools_loaded for the load gate (D10 wired this in main.py
lifespan).
"""

from app.agents.tools.agent_specific.senior_engineer.lookup_prior_reviews import (
    LookupPriorReviewsInput,
    LookupPriorReviewsOutput,
    PriorReview,
    lookup_prior_reviews,
)
from app.agents.tools.agent_specific.senior_engineer.lookup_prior_submissions import (
    LookupPriorSubmissionsInput,
    LookupPriorSubmissionsOutput,
    PriorSubmission,
    lookup_prior_submissions,
)

__all__ = [
    "LookupPriorReviewsInput",
    "LookupPriorReviewsOutput",
    "LookupPriorSubmissionsInput",
    "LookupPriorSubmissionsOutput",
    "PriorReview",
    "PriorSubmission",
    "lookup_prior_reviews",
    "lookup_prior_submissions",
]
