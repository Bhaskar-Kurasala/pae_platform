"""H6 — unit tests for set_request_context in app.core.sentry."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest


def test_set_request_context_calls_set_tag_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_sdk = MagicMock()
    monkeypatch.setitem(sys.modules, "sentry_sdk", mock_sdk)
    import app.core.sentry as sentry_mod

    monkeypatch.setattr(sentry_mod, "_enabled", True)
    from app.core.sentry import set_request_context

    set_request_context("req-123", "trace-abc")
    mock_sdk.set_tag.assert_any_call("request_id", "req-123")
    mock_sdk.set_tag.assert_any_call("trace_id", "trace-abc")


def test_set_request_context_noop_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_sdk = MagicMock()
    monkeypatch.setitem(sys.modules, "sentry_sdk", mock_sdk)
    import app.core.sentry as sentry_mod

    monkeypatch.setattr(sentry_mod, "_enabled", False)
    from app.core.sentry import set_request_context

    set_request_context("req-123", "trace-abc")
    mock_sdk.set_tag.assert_not_called()


def test_set_request_context_skips_none_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_sdk = MagicMock()
    monkeypatch.setitem(sys.modules, "sentry_sdk", mock_sdk)
    import app.core.sentry as sentry_mod

    monkeypatch.setattr(sentry_mod, "_enabled", True)
    from app.core.sentry import set_request_context

    set_request_context(None, "trace-abc")
    mock_sdk.set_tag.assert_called_once_with("trace_id", "trace-abc")


def test_set_request_context_skips_none_trace_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_sdk = MagicMock()
    monkeypatch.setitem(sys.modules, "sentry_sdk", mock_sdk)
    import app.core.sentry as sentry_mod

    monkeypatch.setattr(sentry_mod, "_enabled", True)
    from app.core.sentry import set_request_context

    set_request_context("req-123", None)
    mock_sdk.set_tag.assert_called_once_with("request_id", "req-123")
