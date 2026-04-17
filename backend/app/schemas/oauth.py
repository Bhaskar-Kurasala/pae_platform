from pydantic import BaseModel


class OAuthCallbackResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str


class OAuthUserInfo(BaseModel):
    """Normalised user info from any OAuth provider."""

    email: str
    name: str
    provider: str  # "github" or "google"
    provider_user_id: str
    avatar_url: str | None = None
    github_username: str | None = None
