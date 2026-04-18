from uuid import UUID

from pydantic import BaseModel


class InterleavingSuggestionResponse(BaseModel):
    suggest: bool
    current_skill_id: UUID | None
    next_skill_id: UUID | None
    reason: str
