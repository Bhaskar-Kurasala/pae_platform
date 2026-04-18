from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "Production AI Engineering Platform"
    app_version: str = "0.1.0"
    debug: bool = False
    environment: str = "development"

    # Database
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "platform"
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # DB connection pool
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800  # recycle connections after 30 min

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_key_prefix: str = "pae"  # namespace prefix — prevents key collisions across envs

    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/0"
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    # JWT
    secret_key: str = "changeme-in-production-at-least-32-chars-long"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480  # 8 hours
    refresh_token_expire_days: int = 7

    # External APIs
    anthropic_api_key: str = ""
    minimax_api_key: str = ""
    minimax_api_base_url: str = "https://api.minimax.io/anthropic"
    minimax_model: str = "MiniMax-M2.7"
    sendgrid_api_key: str = ""
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    github_token: str = ""
    pinecone_api_key: str = ""
    meilisearch_host: str = "http://localhost:7700"
    meilisearch_master_key: str = "masterKey123"

    # OAuth
    github_client_id: str = ""
    github_client_secret: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""

    # Stripe price IDs
    stripe_pro_price_id: str = "price_pro_test"
    stripe_team_price_id: str = "price_team_test"

    # SendGrid
    sendgrid_from_email: str = "noreply@pae.dev"

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
