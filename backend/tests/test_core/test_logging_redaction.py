"""H5 — unit tests for PII redaction processors in app.core.logging."""

from __future__ import annotations

from app.core.logging import _PII_KEY_DENYLIST, _redact_pii_processor, _walk_redact


def test_top_level_pii_key_is_redacted() -> None:
    event_dict: dict[str, object] = {"password": "s3cr3t", "event": "login"}
    _walk_redact(event_dict)
    assert event_dict["password"] == "[redacted]"
    assert event_dict["event"] == "login"


def test_non_pii_key_is_unchanged() -> None:
    event_dict: dict[str, object] = {"event": "page_view", "user_id": "abc-123"}
    _walk_redact(event_dict)
    assert event_dict["event"] == "page_view"
    assert event_dict["user_id"] == "abc-123"


def test_nested_dict_pii_is_redacted() -> None:
    event_dict: dict[str, object] = {
        "auth": {"token": "secret123", "user": "alice"}
    }
    _walk_redact(event_dict)
    auth = event_dict["auth"]
    assert isinstance(auth, dict)
    assert auth["token"] == "[redacted]"
    assert auth["user"] == "alice"


def test_nested_list_of_dicts_pii_is_redacted() -> None:
    event_dict: dict[str, object] = {
        "items": [{"email": "x@y.com", "name": "Alice"}]
    }
    _walk_redact(event_dict)
    items = event_dict["items"]
    assert isinstance(items, list)
    first = items[0]
    assert isinstance(first, dict)
    assert first["email"] == "[redacted]"
    assert first["name"] == "Alice"


def test_processor_returns_event_dict() -> None:
    event_dict: dict[str, object] = {"event": "ok"}
    result = _redact_pii_processor(None, "info", event_dict)
    assert result is event_dict
