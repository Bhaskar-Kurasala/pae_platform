from pydantic import BaseModel


class DifficultyRecommendationResponse(BaseModel):
    current: str
    recommended: str
    reason: str
