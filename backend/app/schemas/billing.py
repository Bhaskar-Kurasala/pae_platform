from datetime import datetime

from pydantic import BaseModel


class CheckoutRequest(BaseModel):
    course_id: str
    tier: str = "pro"  # "pro" or "team"
    success_url: str
    cancel_url: str


class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


class SubscriptionInfo(BaseModel):
    tier: str  # "free", "pro", "team"
    status: str  # "active", "canceled", "trialing"
    current_period_end: datetime | None = None


class CustomerPortalResponse(BaseModel):
    portal_url: str


class WebhookResponse(BaseModel):
    received: bool
    event_type: str | None = None
    message: str = ""
