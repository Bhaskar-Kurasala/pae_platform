"""Pure tests for deep health checks.

PR3/C6.1 — readiness reports DB, Redis, and Anthropic key presence.
PR3/C6.2 — `/health/version` returns commit / build / env triple.

Stubs `_check_db` / `_check_redis` so we don't need a live DB or Redis
to verify the readiness endpoint's shape and status code.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import patch

from fastapi import Response

from app.api.v1.routes import health as health_module
from app.api.v1.routes.health import (
    ReadinessCheck,
    liveness,
    readiness,
    version,
)


def _run(coro):
    return asyncio.run(coro)


# ── Liveness ───────────────────────────────────────────────────────────


def test_liveness_is_ok() -> None:
    out = _run(liveness())
    assert out.status == "ok"


# ── Readiness ──────────────────────────────────────────────────────────


def test_readiness_all_ok_returns_200(monkeypatch) -> None:
    async def fake_db() -> ReadinessCheck:
        return ReadinessCheck(ok=True, status="ok")

    async def fake_redis() -> ReadinessCheck:
        return ReadinessCheck(ok=True, status="ok")

    async def fake_anthropic() -> ReadinessCheck:
        return ReadinessCheck(ok=True, status="ok")

    monkeypatch.setattr(health_module, "_check_db", fake_db)
    monkeypatch.setattr(health_module, "_check_redis", fake_redis)
    monkeypatch.setattr(health_module, "_check_anthropic", fake_anthropic)

    response = Response()
    out = _run(readiness(response))

    assert out.status == "ok"
    assert out.checks["db"].ok is True
    assert out.checks["redis"].ok is True
    assert out.checks["anthropic"].ok is True
    assert response.status_code != 503


def test_readiness_db_down_returns_503(monkeypatch) -> None:
    async def fake_db() -> ReadinessCheck:
        return ReadinessCheck(
            ok=False, status="unreachable", error="connection refused"
        )

    async def fake_redis() -> ReadinessCheck:
        return ReadinessCheck(ok=True, status="ok")

    async def fake_anthropic() -> ReadinessCheck:
        return ReadinessCheck(ok=True, status="skipped")

    monkeypatch.setattr(health_module, "_check_db", fake_db)
    monkeypatch.setattr(health_module, "_check_redis", fake_redis)
    monkeypatch.setattr(health_module, "_check_anthropic", fake_anthropic)

    response = Response()
    out = _run(readiness(response))

    assert out.status == "degraded"
    assert out.checks["db"].ok is False
    assert out.checks["db"].status == "unreachable"
    assert out.checks["db"].error == "connection refused"
    assert response.status_code == 503


def test_readiness_redis_down_returns_503(monkeypatch) -> None:
    async def fake_db() -> ReadinessCheck:
        return ReadinessCheck(ok=True, status="ok")

    async def fake_redis() -> ReadinessCheck:
        return ReadinessCheck(
            ok=False, status="unreachable", error="timeout"
        )

    async def fake_anthropic() -> ReadinessCheck:
        return ReadinessCheck(ok=True, status="skipped")

    monkeypatch.setattr(health_module, "_check_db", fake_db)
    monkeypatch.setattr(health_module, "_check_redis", fake_redis)
    monkeypatch.setattr(health_module, "_check_anthropic", fake_anthropic)

    response = Response()
    out = _run(readiness(response))

    assert out.status == "degraded"
    assert out.checks["redis"].ok is False
    assert out.checks["redis"].status == "unreachable"
    assert response.status_code == 503


def test_readiness_anthropic_skipped_does_not_503(monkeypatch) -> None:
    """Anthropic is informational — its absence must NOT trip 503.

    A dev environment without an Anthropic key is still ready to serve
    most traffic. The endpoint should report `anthropic.status="skipped"`
    but stay 200.
    """

    async def fake_db() -> ReadinessCheck:
        return ReadinessCheck(ok=True, status="ok")

    async def fake_redis() -> ReadinessCheck:
        return ReadinessCheck(ok=True, status="ok")

    async def fake_anthropic() -> ReadinessCheck:
        return ReadinessCheck(ok=True, status="skipped")

    monkeypatch.setattr(health_module, "_check_db", fake_db)
    monkeypatch.setattr(health_module, "_check_redis", fake_redis)
    monkeypatch.setattr(health_module, "_check_anthropic", fake_anthropic)

    response = Response()
    out = _run(readiness(response))

    assert out.status == "ok"
    assert out.checks["anthropic"].status == "skipped"
    assert response.status_code != 503


def test_anthropic_check_skipped_when_no_key(monkeypatch) -> None:
    """`_check_anthropic` reports `skipped` when no key is configured."""
    from app.core import config as config_module

    monkeypatch.setattr(
        config_module.settings, "anthropic_api_key", "", raising=False
    )

    out = _run(health_module._check_anthropic())
    assert out.ok is True
    assert out.status == "skipped"


def test_anthropic_check_ok_when_key_set(monkeypatch) -> None:
    """`_check_anthropic` reports `ok` when a key is configured."""
    from app.core import config as config_module

    monkeypatch.setattr(
        config_module.settings,
        "anthropic_api_key",
        "sk-test-mock",
        raising=False,
    )

    out = _run(health_module._check_anthropic())
    assert out.ok is True
    assert out.status == "ok"


# ── Version ────────────────────────────────────────────────────────────


def test_version_uses_build_env_vars() -> None:
    """When build args are present, /health/version returns them verbatim."""
    with patch.dict(
        os.environ,
        {
            "BUILD_COMMIT_SHA": "abc123def",
            "BUILD_TIME": "2026-04-29T10:00:00Z",
        },
        clear=False,
    ):
        out = _run(version())

    assert out.commit_sha == "abc123def"
    assert out.build_time == "2026-04-29T10:00:00Z"
    assert out.env  # whatever Settings reports — non-empty


def test_version_falls_back_to_dev_sentinel() -> None:
    """Without build args, commit_sha falls back to `dev`."""
    env_no_build = {
        k: v
        for k, v in os.environ.items()
        if k not in {"BUILD_COMMIT_SHA", "BUILD_TIME"}
    }
    with patch.dict(os.environ, env_no_build, clear=True):
        out = _run(version())

    assert out.commit_sha == "dev"
    # build_time falls back to a generated ISO timestamp — just sanity.
    assert "T" in out.build_time
