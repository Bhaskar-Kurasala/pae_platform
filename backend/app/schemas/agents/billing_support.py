"""D10 / Pass 3c E1 — billing_support output schema.

The structured response every billing_support invocation returns.
The dispatch layer surfaces this as `AgentResult.structured_output`;
the Critic (D5) validates against this schema; the orchestrator
serializes it for the canonical agentic endpoint response.

Per Pass 3c E1 verbatim:

  class BillingSupportOutput(BaseModel):
      answer: str
      grounded_in: list[str] = []
      suggested_action: Literal["none", "wait", "contact_support",
                                "self_serve"] | None = None
      self_serve_url: str | None = None
      escalation_ticket_id: str | None = None
      confidence: Literal["high", "medium", "low"]

Field semantics (all from Pass 3c E1's "Output schema" section):

  • answer: the response to send to the student, plain text
  • grounded_in: list of record references (e.g.
    ["order CF-20260415-A8K2"]) — empty if the answer didn't
    require record lookups
  • suggested_action: one of `none`, `wait`, `contact_support`, or
    `self_serve`; None when no specific action is suggested
  • self_serve_url: only when suggested_action="self_serve"
  • escalation_ticket_id: only when an escalation was triggered
  • confidence: agent's self-assessed confidence in the answer

Length caps on `answer` (≤ 4000 chars) and `grounded_in` items
(≤ 200 each) are not in the verbatim spec but are added as a
defensive measure against LLM token-bloat regressions per the
schemas/agents/__init__.py module-level convention. The cap on
`answer` is generous enough that a thorough multi-paragraph
response fits comfortably; it only catches genuine pathology.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BillingSupportOutput(BaseModel):
    """Structured response from the billing_support agent.

    Returned from `BillingSupportAgent.run()`. The dispatch layer
    inspects `suggested_action` for downstream UX hints (the
    frontend can render a "Contact support" button when
    `suggested_action="contact_support"`, etc.).
    """

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(
        min_length=1,
        max_length=4000,
        description=(
            "The response to send to the student, plain text. "
            "Match the student's communication preference."
        ),
    )
    grounded_in: list[str] = Field(
        default_factory=list,
        description=(
            "Record references the answer used (e.g. "
            "'order CF-20260415-A8K2'). Empty when no records "
            "were looked up."
        ),
    )
    suggested_action: (
        Literal["none", "wait", "contact_support", "self_serve"] | None
    ) = Field(
        default=None,
        description=(
            "Downstream UX hint: 'wait' for in-progress operations, "
            "'contact_support' when escalation is the right move, "
            "'self_serve' when there's a self-service flow."
        ),
    )
    self_serve_url: str | None = Field(
        default=None,
        max_length=500,
        description="Only set when suggested_action='self_serve'.",
    )
    escalation_ticket_id: str | None = Field(
        default=None,
        max_length=120,
        description="Only set when the agent escalated to human admin.",
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description=(
            "Agent's self-assessed confidence in the answer. "
            "Use 'low' when relying on assumptions over lookups."
        ),
    )

    @model_validator(mode="after")
    def _check_action_url_consistency(self) -> "BillingSupportOutput":
        """Coupled-field invariants from Pass 3c E1.

        • self_serve_url only makes sense when action == 'self_serve'
        • Each grounded_in item is bounded so the output stays
          predictable for downstream consumers.

        These are enforced here (Pydantic-level) rather than relying
        on prompt discipline — the LLM occasionally produces
        inconsistent tuples and we'd rather surface that as a
        validation error the Critic can flag than ship to the user.
        """
        if (
            self.self_serve_url is not None
            and self.suggested_action != "self_serve"
        ):
            raise ValueError(
                "self_serve_url is only valid when "
                "suggested_action='self_serve'; got "
                f"suggested_action={self.suggested_action!r}"
            )
        for ref in self.grounded_in:
            if len(ref) > 200:
                raise ValueError(
                    f"grounded_in entries must be ≤ 200 chars; got "
                    f"{len(ref)} chars in {ref[:60]!r}…"
                )
        return self


__all__ = ["BillingSupportOutput"]
