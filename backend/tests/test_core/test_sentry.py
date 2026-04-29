"""PR3/C5.1 — backend Sentry shim tests.

We test the four guarantees every call site relies on:

  1. With SENTRY_DSN unset, init_sentry() is a no-op and downstream
     helpers (set_user_context, set_agent_context, capture_exception)
     never raise — env-less dev / CI must boot and serve traffic
     identically to a production deploy.
  2. The before_send hook redacts known-PII headers, drops request
     bodies, and strips email/full_name off the user dict — events
     leaving the process cannot leak secrets.
  3. Long query-string values get redacted (cheap heuristic for tokens).
  4. is_enabled() reflects init outcome.

We do NOT test the actual sentry-sdk wire behavior — that's a moving
SDK target and a real Sentry project would catch any regression.
"""

from __future__ import annotations

import builtins
from typing import Any

import pytest

import app.core.sentry as sentry


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sentry, "_initialized", False)
    monkeypatch.setattr(sentry, "_enabled", False)


def test_init_is_noop_without_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    sentry.init_sentry()
    assert sentry.is_enabled() is False


def test_init_is_noop_when_sdk_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SENTRY_DSN", "https://fake@sentry.io/1")
    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("sentry_sdk"):
            raise ImportError("simulated missing dep")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    sentry.init_sentry()
    assert sentry.is_enabled() is False


def test_set_user_context_is_safe_when_disabled() -> None:
    """All public helpers no-op safely when Sentry isn't enabled,
    so call sites don't need `if settings.sentry_dsn:` guards."""
    sentry.set_user_context("user-123")  # no Sentry init
    sentry.set_user_context(None)
    sentry.set_agent_context("socratic_tutor")
    sentry.set_agent_context(None)
    sentry.capture_exception(ValueError("nope"))
    # No assertions needed — the test is "doesn't raise".


def test_init_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Second init call short-circuits via the _initialized guard."""
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    sentry.init_sentry()
    sentry.init_sentry()
    sentry.init_sentry()
    assert sentry._initialized is True
    assert sentry.is_enabled() is False


# ----------------------------------------------------------------------
# before_send / PII filtering
# ----------------------------------------------------------------------


def test_before_send_redacts_authorization_header() -> None:
    event = {
        "request": {
            "headers": {
                "Authorization": "Bearer abc123",
                "User-Agent": "Mozilla",
            }
        }
    }
    cleaned = sentry._before_send(event, {})
    assert cleaned is not None
    assert cleaned["request"]["headers"]["Authorization"] == "[redacted]"
    assert cleaned["request"]["headers"]["User-Agent"] == "Mozilla"


def test_before_send_redacts_cookie_and_refresh_headers() -> None:
    event = {
        "request": {
            "headers": {
                "Cookie": "session=xyz",
                "X-Refresh-Token": "rt_abc",
                "X-Csrf-Token": "csrf_xyz",
            }
        }
    }
    cleaned = sentry._before_send(event, {})
    assert cleaned is not None
    assert cleaned["request"]["headers"]["Cookie"] == "[redacted]"
    assert cleaned["request"]["headers"]["X-Refresh-Token"] == "[redacted]"
    assert cleaned["request"]["headers"]["X-Csrf-Token"] == "[redacted]"


def test_before_send_handles_list_format_headers() -> None:
    """Older sentry-sdk versions pass headers as list of [name, value]."""
    event = {
        "request": {
            "headers": [
                ["authorization", "Bearer abc"],
                ["user-agent", "curl"],
            ]
        }
    }
    cleaned = sentry._before_send(event, {})
    assert cleaned is not None
    headers = cleaned["request"]["headers"]
    assert ["authorization", "[redacted]"] in [list(h) for h in headers]
    assert ["user-agent", "curl"] in [list(h) for h in headers]


def test_before_send_drops_request_body() -> None:
    event = {
        "request": {
            "data": {"prompt": "my anthropic key is sk-ant-abc123..."}
        }
    }
    cleaned = sentry._before_send(event, {})
    assert cleaned is not None
    assert cleaned["request"]["data"] == "[redacted]"


def test_before_send_strips_pii_from_user() -> None:
    event = {
        "user": {
            "id": "user-123",
            "email": "demo@pae.dev",
            "full_name": "Demo Person",
            "ip_address": "1.2.3.4",
        }
    }
    cleaned = sentry._before_send(event, {})
    assert cleaned is not None
    user = cleaned["user"]
    # `id` is preserved — that's the whole point of set_user_context.
    assert user["id"] == "user-123"
    assert user["email"] == "[redacted]"
    assert user["full_name"] == "[redacted]"
    assert user["ip_address"] == "[redacted]"


def test_before_send_redacts_long_querystring_values() -> None:
    long_token = "a" * 64
    event = {
        "request": {
            "query_string": f"course=python-foundations&token={long_token}",
        }
    }
    cleaned = sentry._before_send(event, {})
    assert cleaned is not None
    qs = cleaned["request"]["query_string"]
    # Short value preserved.
    assert "course=python-foundations" in qs
    # Long value redacted.
    assert "token=[redacted]" in qs
    assert long_token not in qs


def test_before_send_returns_event_even_when_request_missing() -> None:
    """Some events (e.g. messages from a Celery task) have no request."""
    event = {"message": "background task failed"}
    cleaned = sentry._before_send(event, {})
    assert cleaned == event
