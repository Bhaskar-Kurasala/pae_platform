"""Pure tests for deep health checks (P3 3B #160).

Stubs `_check_db` and `_check_redis` so we don't need a live DB or Redis
to verify the readiness endpoint's shape and status code.
"""

from __future__ import annotations

import asyncio

from fastapi import Response

from app.api.v1.routes import health as health_module
from app.api.v1.routes.health import (
    ReadinessCheck,
    liveness,
    readiness,
)


def _run(coro):
    return asyncio.run(coro)


def test_liveness_is_ok() -> None:
    out = _run(liveness())
    assert out.status == "ok"


def test_readiness_all_ok_returns_200(monkeypatch) -> None:
    async def fake_db() -> ReadinessCheck:
        return ReadinessCheck(ok=True)

    async def fake_redis() -> ReadinessCheck:
        return ReadinessCheck(ok=True)

    monkeypatch.setattr(health_module, "_check_db", fake_db)
    monkeypatch.setattr(health_module, "_check_redis", fake_redis)

    response = Response()
    out = _run(readiness(response))

    assert out.status == "ok"
    assert out.checks["db"].ok is True
    assert out.checks["redis"].ok is True
    assert response.status_code != 503


def test_readiness_db_down_returns_503(monkeypatch) -> None:
    async def fake_db() -> ReadinessCheck:
        return ReadinessCheck(ok=False, error="connection refused")

    async def fake_redis() -> ReadinessCheck:
        return ReadinessCheck(ok=True)

    monkeypatch.setattr(health_module, "_check_db", fake_db)
    monkeypatch.setattr(health_module, "_check_redis", fake_redis)

    response = Response()
    out = _run(readiness(response))

    assert out.status == "degraded"
    assert out.checks["db"].ok is False
    assert out.checks["db"].error == "connection refused"
    assert response.status_code == 503


def test_readiness_redis_down_returns_503(monkeypatch) -> None:
    async def fake_db() -> ReadinessCheck:
        return ReadinessCheck(ok=True)

    async def fake_redis() -> ReadinessCheck:
        return ReadinessCheck(ok=False, error="timeout")

    monkeypatch.setattr(health_module, "_check_db", fake_db)
    monkeypatch.setattr(health_module, "_check_redis", fake_redis)

    response = Response()
    out = _run(readiness(response))

    assert out.status == "degraded"
    assert out.checks["redis"].ok is False
    assert response.status_code == 503
