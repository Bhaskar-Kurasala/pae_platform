"""Unit tests for StripeService."""
from unittest.mock import MagicMock, patch

import pytest

from app.services.stripe_service import StripeService


@pytest.fixture
def svc() -> StripeService:
    with patch("app.services.stripe_service.stripe") as mock_stripe:
        mock_stripe.api_key = None
        service = StripeService()
    return service


# ---------------------------------------------------------------------------
# get_price_id
# ---------------------------------------------------------------------------


def test_get_price_id_pro() -> None:
    svc = StripeService.__new__(StripeService)
    with patch("app.services.stripe_service.settings") as mock_settings:
        mock_settings.stripe_pro_price_id = "price_pro_real"
        mock_settings.stripe_team_price_id = "price_team_real"
        assert svc.get_price_id("pro") == "price_pro_real"


def test_get_price_id_team() -> None:
    svc = StripeService.__new__(StripeService)
    with patch("app.services.stripe_service.settings") as mock_settings:
        mock_settings.stripe_pro_price_id = ""
        mock_settings.stripe_team_price_id = "price_team_real"
        assert svc.get_price_id("team") == "price_team_real"


def test_get_price_id_fallback_to_test_ids() -> None:
    svc = StripeService.__new__(StripeService)
    with patch("app.services.stripe_service.settings") as mock_settings:
        mock_settings.stripe_pro_price_id = ""
        mock_settings.stripe_team_price_id = ""
        assert svc.get_price_id("pro") == "price_pro_test"
        assert svc.get_price_id("team") == "price_team_test"


def test_get_price_id_unknown_raises() -> None:
    svc = StripeService.__new__(StripeService)
    with pytest.raises(ValueError, match="Unknown tier"):
        svc.get_price_id("enterprise")


# ---------------------------------------------------------------------------
# create_checkout_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_checkout_session_returns_url() -> None:
    mock_session = MagicMock()
    mock_session.url = "https://checkout.stripe.com/pay/cs_test"

    with patch("app.services.stripe_service.stripe") as mock_stripe:
        mock_stripe.checkout.Session.create.return_value = mock_session
        svc = StripeService()
        url = await svc.create_checkout_session(
            user_id="user-1",
            course_id="course-1",
            price_id="price_pro_test",
            success_url="http://localhost:3000/success",
            cancel_url="http://localhost:3000/cancel",
        )

    assert url == "https://checkout.stripe.com/pay/cs_test"


# ---------------------------------------------------------------------------
# handle_webhook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_webhook_invalid_signature_raises() -> None:
    with patch("app.services.stripe_service.stripe") as mock_stripe:
        mock_stripe.error.SignatureVerificationError = Exception
        mock_stripe.Webhook.construct_event.side_effect = Exception("bad sig")
        svc = StripeService()

        with patch("app.services.stripe_service.settings") as mock_settings:
            mock_settings.stripe_webhook_secret = "whsec_test"
            with pytest.raises(ValueError, match="Invalid Stripe webhook signature"):
                await svc.handle_webhook(b"payload", "bad-sig")


@pytest.mark.asyncio
async def test_handle_webhook_returns_event_dict() -> None:
    fake_event: dict = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "metadata": {"user_id": "u1", "course_id": "c1"},
                "customer": "cus_123",
            }
        },
    }

    with patch("app.services.stripe_service.stripe") as mock_stripe:
        mock_stripe.error.SignatureVerificationError = type("SigErr", (Exception,), {})
        mock_stripe.Webhook.construct_event.return_value = fake_event
        svc = StripeService()

        with patch("app.services.stripe_service.settings") as mock_settings:
            mock_settings.stripe_webhook_secret = "whsec_test"
            result = await svc.handle_webhook(b"payload", "t=1,v1=sig")

    assert result["event_type"] == "checkout.session.completed"
    assert "metadata" in result["data"]


@pytest.mark.asyncio
async def test_handle_webhook_no_secret_raises() -> None:
    with patch("app.services.stripe_service.stripe"):
        svc = StripeService()
        with patch("app.services.stripe_service.settings") as mock_settings:
            mock_settings.stripe_webhook_secret = ""
            with pytest.raises(ValueError, match="not configured"):
                await svc.handle_webhook(b"payload", "sig")


# ---------------------------------------------------------------------------
# create_customer_portal_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_customer_portal_session_returns_url() -> None:
    mock_portal = MagicMock()
    mock_portal.url = "https://billing.stripe.com/session/test"

    with patch("app.services.stripe_service.stripe") as mock_stripe:
        mock_stripe.billing_portal.Session.create.return_value = mock_portal
        svc = StripeService()
        url = await svc.create_customer_portal_session(
            customer_id="cus_test", return_url="http://localhost:3000/dashboard"
        )

    assert url == "https://billing.stripe.com/session/test"
