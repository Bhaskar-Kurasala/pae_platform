from pydantic import BaseModel, Field


class PillItem(BaseModel):
    key: str
    label: str


class ClarifyCheckRequest(BaseModel):
    message: str = Field(min_length=0, max_length=4000)


class ClarifyCheckResponse(BaseModel):
    show_pills: bool
    reason: str
    pills: list[PillItem]


class FollowupRequest(BaseModel):
    reply: str = Field(min_length=0, max_length=20000)


class FollowupResponse(BaseModel):
    pills: list[PillItem]
