from pydantic import BaseModel, Field


class ConsistencyResponse(BaseModel):
    """Days-active-in-window summary for the Today screen (P3 3A-14)."""

    days_this_week: int = Field(ge=0, le=7)
    window_days: int = Field(ge=1, le=30)
