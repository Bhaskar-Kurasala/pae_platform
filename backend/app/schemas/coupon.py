from datetime import datetime
from pydantic import BaseModel, Field


class CouponCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64)
    course_id: str | None = None
    bundle_id: str | None = None
    percent_off: int = Field(ge=1, le=100)
    max_redemptions: int | None = None
    expires_at: datetime | None = None


class CouponUpdate(BaseModel):
    percent_off: int | None = Field(default=None, ge=1, le=100)
    max_redemptions: int | None = None
    expires_at: datetime | None = None
    is_active: bool | None = None


class CouponRead(BaseModel):
    id: str
    code: str
    course_id: str | None
    bundle_id: str | None
    percent_off: int
    max_redemptions: int | None
    redemption_count: int
    expires_at: datetime | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
