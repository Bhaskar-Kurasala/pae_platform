import uuid
from datetime import datetime

from pydantic import BaseModel


class PaymentCreate(BaseModel):
    user_id: uuid.UUID
    course_id: uuid.UUID | None = None
    amount_cents: int
    currency: str = "usd"
    payment_method: str = "card"


class PaymentResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    user_id: uuid.UUID
    course_id: uuid.UUID | None = None
    amount_cents: int
    currency: str
    status: str
    payment_method: str
    created_at: datetime
    updated_at: datetime
