"""Provider-agnostic payment abstraction.

Public surface — import from here, NOT from the concrete provider modules:

    from app.services.payment_providers import (
        get_provider,
        PaymentProviderBase,
        ProviderOrder,
        VerifiedPayment,
        WebhookEventEnvelope,
        RefundResult,
        PaymentProviderError,
        SignatureMismatchError,
        ProviderUnavailableError,
        MockProvider,        # dev / test only
        sign_payment,        # dev / test only — produce signature for mock
        sign_webhook,        # dev / test only — produce signature for mock
    )
"""

from .base import (
    PaymentProviderBase,
    PaymentProviderError,
    ProviderOrder,
    ProviderUnavailableError,
    RefundResult,
    SignatureMismatchError,
    VerifiedPayment,
    WebhookEventEnvelope,
)
from .factory import get_provider
from .mock_provider import MockProvider, sign_payment, sign_webhook

__all__ = [
    "PaymentProviderBase",
    "PaymentProviderError",
    "ProviderOrder",
    "ProviderUnavailableError",
    "RefundResult",
    "SignatureMismatchError",
    "VerifiedPayment",
    "WebhookEventEnvelope",
    "get_provider",
    "MockProvider",
    "sign_payment",
    "sign_webhook",
]
