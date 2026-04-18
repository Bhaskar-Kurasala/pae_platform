"""Pure tests for Redis key namespacing (P3 3B #163)."""

from __future__ import annotations

import pytest

from app.core.redis import namespaced_key


def test_single_segment_key() -> None:
    key = namespaced_key("courses", "published")
    parts = key.split(":")
    assert parts[0] == "pae"
    assert parts[2] == "courses"
    assert parts[-1] == "published"


def test_multi_segment_key() -> None:
    key = namespaced_key("interview", "session", "abc-123")
    parts = key.split(":")
    assert parts[-3:] == ["interview", "session", "abc-123"]


def test_category_only() -> None:
    key = namespaced_key("conv")
    # pae:{env}:conv  — three segments, no trailing colon
    assert key.endswith(":conv")
    assert not key.endswith(":")


def test_unknown_category_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown redis key category"):
        namespaced_key("sessions", "x")


def test_environment_in_key() -> None:
    from app.core.config import settings

    key = namespaced_key("conv", "abc")
    assert f":{settings.environment}:" in key
