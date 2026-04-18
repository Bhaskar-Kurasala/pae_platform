# ADD TO registry.py: import app.agents.billing_support  # noqa: F401

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

_PROMPT = (Path(__file__).parent / "prompts" / "billing_support.md").read_text()

# Pattern to detect dollar amounts — guardrail check
_DOLLAR_PATTERN = re.compile(r"\$\d+|\d+\s*dollars?|\d+\s*USD", re.IGNORECASE)


@register
class BillingSupportAgent(BaseAgent):
    """Answers billing and subscription questions with guardrails.

    Handles: subscription tier info, upgrade/downgrade, refund policy,
    cancellation. Never promises specific refund amounts — always redirects
    financial decisions to support@pae.dev.

    Guardrail: evaluate() fails if response contains dollar amounts.
    """

    name = "billing_support"
    description = (
        "Answers billing and subscription questions for the PAE Platform. "
        "Handles tier info, upgrade/downgrade, refund policy, and cancellation. "
        "Escalates financial decisions to support@pae.dev."
    )
    trigger_conditions = [
        "billing",
        "subscription",
        "refund",
        "cancel subscription",
        "upgrade plan",
        "payment issue",
        "invoice",
    ]
    model = "claude-haiku-4-5"

    def _build_llm(self, max_tokens: int = 1024):
        from app.agents.llm_factory import build_llm
        return build_llm(max_tokens=max_tokens)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _call_llm(
        self,
        llm: Any,
        subscription_tier: str,
        issue_type: str,
        task: str,
    ) -> str:
        messages: list[Any] = [
            SystemMessage(content=_PROMPT),
            HumanMessage(
                content=(
                    f"Student subscription tier: {subscription_tier}\n"
                    f"Issue type: {issue_type or 'not specified'}\n\n"
                    f"Student question: {task}"
                )
            ),
        ]
        response = await llm.ainvoke(messages)
        return str(response.content)

    async def execute(self, state: AgentState) -> AgentState:
        subscription_tier: str = state.context.get("subscription_tier", "free")
        issue_type: str = state.context.get("issue_type", "")

        if settings.minimax_api_key or settings.anthropic_api_key:
            try:
                llm = self._build_llm()
                response_text = await self._call_llm(llm, subscription_tier, issue_type, state.task)
            except Exception as exc:
                self._log.warning("billing_support.llm_failed", error=str(exc))
                response_text = self._fallback_response(issue_type)
        else:
            response_text = self._fallback_response(issue_type)

        return state.model_copy(update={"response": response_text})

    def _fallback_response(self, issue_type: str) -> str:
        """Return a static fallback for common billing questions."""
        if "refund" in issue_type.lower():
            return (
                "We offer a 30-day money-back guarantee on all paid plans. "
                "For direct billing assistance, please email support@pae.dev with your order details."
            )
        if "cancel" in issue_type.lower():
            return (
                "You can cancel your subscription at any time from your account settings. "
                "You'll retain access until the end of your current billing period. "
                "For assistance, email support@pae.dev."
            )
        if "upgrade" in issue_type.lower():
            return (
                "You can upgrade from Free to Pro ($29/mo) or Team ($99/mo) from your "
                "account settings. Changes take effect immediately. "
                "For help, email support@pae.dev."
            )
        return (
            "Thank you for contacting PAE Platform billing support. "
            "For direct assistance with your billing question, "
            "please email support@pae.dev with your order details and we'll get back to you within 24 hours."
        )

    async def evaluate(self, state: AgentState) -> AgentState:
        """Guardrail: pass only if response does NOT contain dollar amounts.

        Dollar amounts in the response indicate the agent may have promised
        a specific refund or made an unauthorised financial commitment.
        """
        response = state.response or ""
        contains_dollar_amount = bool(_DOLLAR_PATTERN.search(response))

        if contains_dollar_amount:
            self._log.warning(
                "billing_support.guardrail_triggered",
                student_id=state.student_id,
                reason="response_contains_dollar_amount",
            )
            # Still return the response but with a low score to flag for review
            score = 0.2
        else:
            has_escalation = "support@pae.dev" in response
            score = 0.9 if has_escalation else 0.7

        return state.model_copy(update={"evaluation_score": score})
