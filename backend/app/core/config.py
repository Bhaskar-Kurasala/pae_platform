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

    # Feature flags
    feature_tailored_resume_agent: bool = False
    # Defaults flipped to True 2026-04-26 with the readiness workspace
    # production refactor — these are no longer experimental. Set the env
    # vars to "false" to use the legacy fallback paths.
    feature_readiness_diagnostic: bool = True
    feature_jd_decoder: bool = True

    # Chat attachments (P1-6). Local dev stores attachment bytes on disk under
    # `attachments_dir`; created lazily on first upload. In production this
    # swaps to S3 by replacing the `AttachmentStorage` backend without any
    # schema change.
    attachments_dir: str = "var/attachments"
    attachments_max_bytes: int = 10 * 1024 * 1024  # 10 MB per file
    attachments_max_per_message: int = 4

    # Course content — private GitHub repo holding notebooks/PDFs/slides.
    # Backend acts as a proxy: students never get repo access; resolution
    # to a Colab/raw URL happens at request time, gated by enrollment.
    github_content_token: str = ""
    github_content_repo: str = ""  # e.g. "your-username/pae-course-content"
    github_content_branch: str = "main"

    # Celery — default to the same Redis as the app (host-aware) so docker
    # and local runs don't silently point the worker at localhost. Any env
    # override of celery_broker_url / celery_result_backend still wins.
    celery_broker_url: str = ""
    celery_result_backend: str = ""

    def model_post_init(self, __context: object) -> None:
        if not self.celery_broker_url:
            self.celery_broker_url = f"redis://{self.redis_host}:{self.redis_port}/1"
        if not self.celery_result_backend:
            self.celery_result_backend = f"redis://{self.redis_host}:{self.redis_port}/2"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
