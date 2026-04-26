"""Provider factory — single dispatch point for ``order``/``entitlement`` services.

Callers do ``provider = get_provider(order.provider)`` and never see a concrete
SDK class — that's the whole point of the abstraction.

Dev-mode fallback: if the requested provider is razorpay/stripe but its
credentials are unconfigured AND the environment is not "production", we
return the deterministic ``MockProvider``. This lets the full Catalog → order
→ confirm → entitlement flow work end-to-end in dev + tests without real
gateway accounts. Production environments raise instead of falling back.
"""

from __future__ import annotations

import structlog

from app.core.config import settings

from .base import PaymentProviderBase, ProviderUnavailableError
from .mock_provider import MockProvider
from .razorpay_provider import RazorpayProvider
from .stripe_provider import StripeProvider

log = structlog.get_logger()


def _razorpay_configured() -> bool:
    return bool(settings.razorpay_key_id and settings.razorpay_key_secret)


def _stripe_configured() -> bool:
    return bool(settings.stripe_secret_key)


def _is_production() -> bool:
    return (settings.environment or "").lower() == "production"


def get_provider(name: str) -> PaymentProviderBase:
    """Return a concrete ``PaymentProviderBase`` for the given canonical name.

    Raises ``ValueError`` for any unknown provider — the exhaustive enum lives
    in this dict, NOT spread across the codebase.
    """
    key = (name or "").strip().lower()
    if key == "mock":
        if _is_production():
            raise ProviderUnavailableError(
                "MockProvider is disabled in production."
            )
        return MockProvider()
    if key == "razorpay":
        if _razorpay_configured():
            return RazorpayProvider()
        if _is_production():
            raise ProviderUnavailableError(
                "Razorpay is not configured in this production environment."
            )
        log.warning(
            "payment_providers.factory.fallback_to_mock",
            requested="razorpay",
            reason="razorpay credentials missing; using MockProvider in non-prod",
        )
        return MockProvider()
    if key == "stripe":
        if _stripe_configured():
            return StripeProvider()
        if _is_production():
            raise ProviderUnavailableError(
                "Stripe is not configured in this production environment."
            )
        log.warning(
            "payment_providers.factory.fallback_to_mock",
            requested="stripe",
            reason="stripe credentials missing; using MockProvider in non-prod",
        )
        return MockProvider()
    raise ValueError(
        f"Unknown payment provider: {name!r}. "
        "Expected one of: 'razorpay', 'stripe', 'mock'."
    )
