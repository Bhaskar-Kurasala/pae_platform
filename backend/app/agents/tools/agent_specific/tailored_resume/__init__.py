"""D12 / Pass 3d §E.2 — tailored_resume-specific tools.

Two read tools for the chat-path (Shape b thin-shim agent):
  • lookup_jd_decoded  — read decoded JD from existing JD decoder service
  • lookup_base_resume — read student's base resume

These tools are used by the chat-path TailoredResumeAgent.run() to
gather inputs before delegating to tailored_resume_service. The
service-path (route → service) does NOT call these tools — it receives
inputs directly from the request body.
"""

from app.agents.tools.agent_specific.tailored_resume.lookup_base_resume import (
    lookup_base_resume,
)
from app.agents.tools.agent_specific.tailored_resume.lookup_jd_decoded import (
    lookup_jd_decoded,
)

__all__ = [
    "lookup_base_resume",
    "lookup_jd_decoded",
]
