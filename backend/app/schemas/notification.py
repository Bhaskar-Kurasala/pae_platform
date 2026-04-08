import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class NotificationCreate(BaseModel):
    user_id: uuid.UUID
    title: str
    body: str
    notification_type: str
    action_url: str | None = None
    metadata: dict[str, Any] | None = None


class NotificationResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    body: str
    notification_type: str
    is_read: bool
    action_url: str | None = None
    created_at: datetime
