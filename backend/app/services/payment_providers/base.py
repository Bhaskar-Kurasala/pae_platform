"""Abstract base class + value-object dataclasses for payment providers.

The goal of this module is to keep the rest of the codebase (services, routes,
webhook handlers) provider-agnostic. Each concrete provider — Razorpay, Stripe,
…  — adapts its native SDK shape to the dataclasses defined here.

Public exports re-exported from ``app.services.payment_providers`` (see
``__init__.py``).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Value objects — frozen dataclasses, JSON-friendly
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderOrder:
    """A normalised order created on the provider side (Razorpay/Stripe).

    ``amount_cents`` is the smallest currency unit (paise for INR, cents for
    USD/EUR). Always an integer — never a float — to avoid rounding drift.
    """

    provider_order_id: str
    amount_cents: int
    currency: str
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VerifiedPayment:
    """A payment whose signature has been verified against the provider secret.

    Returned by callers after ``verify_payment_signature`` succeeds; the rest of
    the system trusts the contents (the provider order id + payment id are
    cryptographically bound).
    """

    provider_payment_id: str
    provider_order_id: str
    signature: str
    amount_cents: int
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WebhookEventEnvelope:
    """Provider-agnostic envelope around a parsed webhook body.

    ``provider_event_id`` is the unique id from the provider (used for idempotent
    insert into ``payment_webhook_events``). ``event_type`` is the provider's
    raw event name (e.g. ``payment.captured`` for Razorpay,
    ``checkout.session.completed`` for Stripe). The related order/payment ids
    are extracted out so downstream code doesn't need to walk the raw JSON.
    """

    provider_event_id: str
    event_type: str
    related_provider_order_id: str | None
    related_provider_payment_id: str | None
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RefundResult:
    """Result of a refund initiation call against the provider."""

    provider_refund_id: str
    status: str  # "pending" | "processed" | "failed"
    raw_response: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PaymentProviderError(Exception):
    """Base class for all provider-related errors."""


class SignatureMismatchError(PaymentProviderError):
    """Raised when a webhook or payment signature does not match the secret."""


class ProviderUnavailableError(PaymentProviderError):
    """Raised when the upstream provider returns a network/5xx-class error."""


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class PaymentProviderBase(ABC):
    """Abstract base for every payment provider implementation.

    Concrete providers MUST set ``name`` to the lowercase canonical key
    (``"razorpay"``, ``"stripe"``) — this is the same key persisted on the
    ``orders.provider`` column and used by the factory.
    """

    name: str = ""

    @abstractmethod
    async def create_order(
        self,
        *,
        amount_cents: int,
        currency: str,
        receipt: str,
        notes: dict[str, str],
    ) -> ProviderOrder:
        """Create an order on the provider; returns a normalised ``ProviderOrder``."""

    @abstractmethod
    def verify_payment_signature(
        self,
        *,
        provider_order_id: str,
        provider_payment_id: str,
        signature: str,
    ) -> bool:
        """Verify the signature returned by the hosted checkout on success.

        Razorpay signs ``order_id|payment_id`` with HMAC-SHA256 using the
        ``key_secret``. Stripe doesn't ship this exact pattern — its impl is a
        documented no-op that returns ``True`` because Stripe's redirect already
        carries a signed ``session_id`` we don't re-verify here (the webhook is
        the auth boundary for Stripe).
        """

    @abstractmethod
    def verify_webhook_signature(self, *, raw_body: bytes, signature: str) -> bool:
        """Verify the webhook signature header against ``raw_body``.

        Implementations MUST return ``False`` (rather than raising) on a
        mismatch so callers can return a 4xx without leaking exception detail.
        """

    @abstractmethod
    def parse_webhook_event(self, *, raw_body: bytes) -> WebhookEventEnvelope:
        """Parse a raw webhook body into a normalised envelope.

        Callers should call ``verify_webhook_signature`` *before* this — parsing
        an unverified body is an XSRF vector.
        """

    @abstractmethod
    async def fetch_payment(self, provider_payment_id: str) -> dict[str, Any]:
        """Fetch the latest payment record from the provider.

        Returns the raw provider dict — callers can pluck the fields they need
        without us guessing every field they might want.
        """

    @abstractmethod
    async def create_refund(
        self,
        *,
        provider_payment_id: str,
        amount_cents: int,
        notes: dict[str, str],
    ) -> RefundResult:
        """Initiate a refund against ``provider_payment_id`` for ``amount_cents``."""
