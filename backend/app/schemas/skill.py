import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

MasteryLevel = Literal["unknown", "novice", "learning", "proficient", "mastered"]
EdgeType = Literal["prereq", "related"]


class SkillNode(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    slug: str
    name: str
    description: str
    difficulty: int


class SkillEdgeResponse(BaseModel):
    model_config = {"from_attributes": True}

    from_skill_id: uuid.UUID
    to_skill_id: uuid.UUID
    edge_type: EdgeType


class SkillGraphResponse(BaseModel):
    nodes: list[SkillNode]
    edges: list[SkillEdgeResponse]


class UserSkillStateResponse(BaseModel):
    model_config = {"from_attributes": True}

    skill_id: uuid.UUID
    mastery_level: MasteryLevel
    confidence: float
    last_touched_at: datetime | None


class UserSkillTouchResponse(BaseModel):
    skill_id: uuid.UUID
    last_touched_at: datetime
