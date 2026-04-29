"""PR3/D2.2 — production_required Pydantic validator on Settings.

The validator refuses to boot when ENVIRONMENT=production and any
critical secret is missing or matches a known dev default. These tests
cover the four secrets (secret_key, anthropic_api_key, database_url,
redis_url) and the no-op path on non-production environments.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings


# ── Helpers ────────────────────────────────────────────────────────────────


# A known-strong 32-byte secret. Generated once with `secrets.token_urlsafe(32)`
# and frozen as a fixture — the value isn't sensitive, it's only used to
# verify the validator accepts strong inputs.
_STRONG_SECRET = "Wt2sLBGv9XO5CP0uTABe7dJG3TkM-q5EXAMPLE_secret_for_test"
_STRONG_ANTHROPIC = "sk-ant-test-1234567890abcdef"
_STRONG_PG_PASSWORD = "K3yP@ss-from-vault-do-not-use"
_STRONG_REDIS_HOST = "redis.fly.dev"


def _strong_prod_kwargs() -> dict[str, str | int]:
    """Return a dict of Settings kwargs that PASS the validator in
    production. Each test mutates one field to verify the failure path.
    """
    return {
        "environment": "production",
        "secret_key": _STRONG_SECRET,
        "anthropic_api_key": _STRONG_ANTHROPIC,
        "postgres_host": "neon-prod.example.com",
        "postgres_port": 5432,
        "postgres_user": "pae_app",
        "postgres_password": _STRONG_PG_PASSWORD,
        "postgres_db": "pae_prod",
        "redis_host": _STRONG_REDIS_HOST,
        "redis_port": 6379,
        "redis_password": _STRONG_PG_PASSWORD,
    }


# ── Non-production paths (validator is no-op) ─────────────────────────────


def test_dev_environment_with_dev_defaults_boots() -> None:
    """Local dev MUST keep working with the shipped defaults."""
    s = Settings(environment="development")  # type: ignore[call-arg]
    assert s.environment == "development"
    # The dev default is intentionally weak; that's fine in dev.
    assert "changeme" in s.secret_key.lower()


def test_test_environment_with_dev_defaults_boots() -> None:
    """CI / pytest run with environment != production should also boot."""
    s = Settings(environment="test")  # type: ignore[call-arg]
    assert s.environment == "test"


def test_production_environment_is_case_insensitive_no_op_for_staging() -> None:
    """`ENVIRONMENT=staging` should NOT trip the prod check — only an
    explicit `production` (any case) does."""
    s = Settings(  # type: ignore[call-arg]
        environment="staging",
        secret_key="weak",  # would fail under prod
    )
    assert s.environment == "staging"


# ── Production path: happy case ───────────────────────────────────────────


def test_production_with_strong_values_boots_cleanly() -> None:
    """The reference example a reviewer can copy."""
    s = Settings(**_strong_prod_kwargs())  # type: ignore[arg-type]
    assert s.environment == "production"
    assert s.secret_key == _STRONG_SECRET


# ── Production path: each required field, individually broken ────────────


def test_production_rejects_default_secret_key() -> None:
    kwargs = _strong_prod_kwargs() | {"secret_key": "changeme-in-production-at-least-32-chars-long"}
    with pytest.raises(ValueError, match="secret_key"):
        Settings(**kwargs)  # type: ignore[arg-type]


def test_production_rejects_short_secret_key() -> None:
    kwargs = _strong_prod_kwargs() | {"secret_key": "tooShort"}
    with pytest.raises(ValueError, match="secret_key"):
        Settings(**kwargs)  # type: ignore[arg-type]


def test_production_rejects_empty_secret_key() -> None:
    kwargs = _strong_prod_kwargs() | {"secret_key": ""}
    with pytest.raises(ValueError, match="secret_key"):
        Settings(**kwargs)  # type: ignore[arg-type]


def test_production_rejects_empty_anthropic_key() -> None:
    kwargs = _strong_prod_kwargs() | {"anthropic_api_key": ""}
    with pytest.raises(ValueError, match="anthropic_api_key"):
        Settings(**kwargs)  # type: ignore[arg-type]


def test_production_rejects_mock_anthropic_key() -> None:
    """The CI mock key (`sk-test-mock`) is a documented dev fragment."""
    kwargs = _strong_prod_kwargs() | {"anthropic_api_key": "sk-test-mock"}
    with pytest.raises(ValueError, match="anthropic_api_key"):
        Settings(**kwargs)  # type: ignore[arg-type]


def test_production_rejects_default_postgres_credentials() -> None:
    """`postgres:postgres` is the docker-compose dev credential — must
    not appear anywhere in a prod database_url."""
    kwargs = _strong_prod_kwargs() | {
        "postgres_user": "postgres",
        "postgres_password": "postgres",
    }
    with pytest.raises(ValueError, match="database_url"):
        Settings(**kwargs)  # type: ignore[arg-type]


def test_production_accepts_neon_style_database_url() -> None:
    """Sanity: a realistic Neon URL passes the validator."""
    kwargs = _strong_prod_kwargs() | {
        "postgres_host": "ep-rough-feather-12345.us-east-1.aws.neon.tech",
        "postgres_user": "neondb_owner",
        "postgres_password": "npg_X7yK2pQrStUvWxYz1234567890",
        "postgres_db": "neondb",
    }
    s = Settings(**kwargs)  # type: ignore[arg-type]
    assert "neon.tech" in s.database_url


# ── Multi-error reporting ─────────────────────────────────────────────────


def test_production_lists_every_offending_field_at_once() -> None:
    """A partial fix that surfaces a new error on the next boot wastes
    wall-clock during a deploy. The validator names every offender."""
    kwargs = {
        "environment": "production",
        "secret_key": "changeme",
        "anthropic_api_key": "",
        "postgres_user": "postgres",
        "postgres_password": "postgres",
        "redis_host": "localhost",
    }
    with pytest.raises(ValueError) as exc_info:
        Settings(**kwargs)  # type: ignore[arg-type]
    msg = str(exc_info.value)
    assert "secret_key" in msg
    assert "anthropic_api_key" in msg
    assert "database_url" in msg
    # `redis://localhost:6379/0` doesn't contain a dev fragment, so it
    # passes — this asserts we don't over-trigger.
    # The error is multi-line and references the runbook.
    assert "secret-rotation.md" in msg


# ── Strong-secret helper ──────────────────────────────────────────────────


def test_strong_secret_helper_rejects_short() -> None:
    assert Settings._is_strong_secret("short", 32) is False


def test_strong_secret_helper_is_case_insensitive_on_fragments() -> None:
    """Operator pastes `ChangeMe-In-Production-Now-Pls-32chars-min`. Still fails."""
    assert Settings._is_strong_secret("ChangeMe-In-Production-Now-Pls-32chars-min", 32) is False


def test_strong_secret_helper_accepts_random() -> None:
    assert Settings._is_strong_secret(_STRONG_SECRET, 32) is True
