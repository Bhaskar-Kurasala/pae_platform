from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# PR3/D2.2 — values that look like dev defaults and must NOT appear in
# production. Any of these substrings (case-insensitive) in a critical
# secret will refuse the boot when ENVIRONMENT=production.
#
# Kept tight — we want false negatives ("this looks like prod, OK") not
# false positives ("strong random key flagged as dev"). Each substring
# is one we ourselves shipped in code as a placeholder, so a prod secret
# containing any of them is unambiguously a misconfiguration.
_DEV_DEFAULT_FRAGMENTS: tuple[str, ...] = (
    "changeme",
    "test-secret",
    "dev-secret",
    "local-dev",
    "sk-test-mock",
    "postgres:postgres",  # the docker-compose dev DB credential
    "masterkey123",
)

# Minimum length for the JWT secret_key. 32 bytes (256 bits) is the
# documented HS256 minimum; anything shorter is a weakness.
_MIN_SECRET_KEY_LEN = 32


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
    # Razorpay (Catalog refactor 2026-04-26). Defaults are non-functional
    # placeholders so the app still starts in dev without secrets.
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    # Frontend uses ONLY the public key id (NEXT_PUBLIC_RAZORPAY_KEY_ID).
    payments_default_provider: str = "razorpay"
    payments_default_currency: str = "INR"
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

    # CORS — PR3/D3.1 allowlist driven by `CORS_ORIGINS` env var.
    #
    # Env-var form: comma-separated list of origins, e.g.
    #   CORS_ORIGINS=https://app.example.com,https://admin.example.com
    #
    # JSON-array form is ALSO accepted for compatibility with Pydantic's
    # native list parser:
    #   CORS_ORIGINS=["https://app.example.com","https://admin.example.com"]
    #
    # Wildcard (`*`) is allowed for dev only — in production, the
    # `production_required` validator (D2.2) will fail the boot if you
    # ship `*` because `allow_credentials=True` makes that a CORS spec
    # violation that browsers will silently reject anyway.
    cors_origins: list[str] = ["http://localhost:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: object) -> object:
        """Accept either a JSON array OR a comma-separated string.

        Fly secrets / .env files default to the latter —
        `CORS_ORIGINS=https://a.com,https://b.com` is the natural way to
        set this and Pydantic's native parser would reject it as
        invalid JSON. We normalize both forms to a `list[str]` here so
        downstream code never has to second-guess."""
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                # JSON-array form: parse it ourselves so this validator
                # always returns a list (Pydantic's `mode='before'`
                # then sees a list and skips its own list-parsing path).
                import json

                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"CORS_ORIGINS looks like JSON but didn't parse: {exc}") from exc
                if not isinstance(parsed, list):
                    raise ValueError("CORS_ORIGINS JSON must decode to a list")
                return [str(item) for item in parsed]
            # Comma-separated form.
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value

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

    # Agentic OS — embeddings for the memory primitive.
    # Voyage-3 is the default provider (1024 native dims, padded to
    # 1536 in app.agents.primitives.embeddings to fit the migration's
    # vector(1536) column). When voyage_api_key is unset the layer
    # falls back to a deterministic hash function so dev / CI work
    # without an external API. The full ENABLE_* feature flags for the
    # primitives layer land in a later deliverable (10) — this
    # commit only adds the two settings the embeddings helper reads.
    voyage_api_key: str = ""
    embeddings_model: str = "voyage-3"

    # Agentic OS — escalation limiter backend (D5+Track 2).
    #
    # `redis` (default): per-agent sliding-window sorted-set in Redis.
    #   Multi-worker safe: every Celery worker / FastAPI worker
    #   shares the same bucket so the configured limit is the
    #   actual cap on admin notifications.
    #
    # `in_memory`: process-local deque. Pre-Track-2 default;
    #   over-grants by Nx where N = worker count. Kept as the
    #   fallback path for tests and dev environments without
    #   Redis (and as the fail-open destination when Redis is
    #   unreachable at runtime).
    #
    # Fail-open contract (load-bearing): when Redis is configured
    # but unavailable, the limiter MUST degrade to permissive
    # (escalate everything) with a loud warning, NOT block. A
    # Redis incident is exactly when admins need the notification
    # firehose; suppressing during failure is the unsafe default.
    escalation_limiter_backend: str = "redis"

    # Inter-agent call depth ceiling. Hard cap that prevents an
    # agent that calls itself (or an unbounded chain) from hanging
    # the request. Default 5: enough headroom for legitimate
    # composition (root → 4 nested calls), tight enough to surface
    # accidental fan-out before it eats wall-clock or token budget.
    # Per-call timeouts ride on top of this via asyncio.wait_for.
    agent_call_max_depth: int = 5
    agent_call_timeout_seconds: float = 30.0

    # Webhook secrets for the proactive primitive (D6).
    #
    # `github_webhook_secret` is distinct from `github_token` (a PAT
    # used for API reads). Webhook secret is set inside GitHub's
    # repo / org webhook UI; payloads are signed with HMAC-SHA256
    # and we verify before routing. Empty = signature verification
    # rejects all requests, which is the safe default for an
    # unconfigured environment.
    github_webhook_secret: str = ""

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

    # PR3/D2.2 — production_required validator.
    #
    # Refuses to boot when ENVIRONMENT=production and any of the four
    # critical secrets (JWT secret_key, Anthropic key, Postgres URL,
    # Redis URL) is missing or matches a known dev default. The error
    # message names every offending field at once — a partial fix that
    # surfaces a new "still wrong" error on the next boot is wasted
    # wall-clock during a deploy.
    #
    # Why `model_validator(mode="after")` (not a `@field_validator`):
    #   - We need to read `environment` AND the four secrets on the
    #     same instance, so a per-field validator would fire before
    #     `environment` is bound and short-circuit incorrectly.
    #   - We need access to derived properties (`database_url`,
    #     `redis_url`) which only exist after model construction.
    @model_validator(mode="after")
    def _production_required(self) -> "Settings":
        if self.environment.lower() != "production":
            return self

        problems: list[str] = []

        if not self._is_strong_secret(self.secret_key, _MIN_SECRET_KEY_LEN):
            problems.append(
                "secret_key is missing, too short, or matches a dev default "
                f"(min length {_MIN_SECRET_KEY_LEN}, must not contain a dev fragment)"
            )

        if not self._is_strong_secret(self.anthropic_api_key, min_len=8):
            problems.append(
                "anthropic_api_key is missing or matches a dev default "
                "(must be a real Anthropic key starting with `sk-ant-…`)"
            )

        # database_url is a property derived from postgres_* fields. We
        # check the constructed URL so a sneaky `postgres:postgres` host
        # password gets caught even if the user split it across fields.
        if not self._is_strong_secret(self.database_url, min_len=8):
            problems.append(
                "database_url is missing or matches a dev default "
                "(set POSTGRES_HOST / POSTGRES_USER / POSTGRES_PASSWORD / "
                "POSTGRES_DB to non-default values, OR provide a managed-DB "
                "connection string in production)"
            )

        if not self._is_strong_secret(self.redis_url, min_len=8):
            problems.append(
                "redis_url is missing or matches a dev default "
                "(set REDIS_HOST / REDIS_PORT to a managed Redis endpoint)"
            )

        # PR3/D3.1 — CORS wildcard in production is a CORS-spec
        # violation when paired with `allow_credentials=True` (which
        # we use). Browsers silently reject it, but better to fail
        # loud at boot than ship a quietly-broken app.
        if "*" in self.cors_origins:
            problems.append(
                "cors_origins contains '*' which is invalid in production "
                "(allow_credentials=True forbids the wildcard). Set "
                "CORS_ORIGINS to an explicit comma-separated list of HTTPS "
                "origins."
            )

        if problems:
            joined = "\n  - ".join(problems)
            raise ValueError(
                "Refusing to boot: ENVIRONMENT=production but critical "
                "secrets are missing or look like dev defaults:\n  - "
                + joined
                + "\n\nFix by setting strong values in your production "
                "environment (see docs/runbooks/secret-rotation.md). "
                "This check is intentional — booting with dev defaults "
                "in production is a security incident."
            )

        return self

    @staticmethod
    def _is_strong_secret(value: str, min_len: int) -> bool:
        """Return True iff `value` is non-empty, ≥ min_len, and does not
        contain any known dev-default fragment.

        Comparison is case-insensitive — a prod operator who pastes
        `ChangeMe-In-Production` should fail just as loudly as the
        lower-cased default."""
        if not value or len(value) < min_len:
            return False
        lowered = value.lower()
        for fragment in _DEV_DEFAULT_FRAGMENTS:
            if fragment in lowered:
                return False
        return True


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
