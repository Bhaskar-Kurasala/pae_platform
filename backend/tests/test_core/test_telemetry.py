"""PR3/C3.1 — backend telemetry shim tests.

Verifies:
  1. With POSTHOG_KEY unset, init returns None and capture is a no-op
     that doesn't raise.
  2. With POSTHOG_KEY set but the `posthog` package not installed, the
     same no-op behavior — we don't blow up at import time.
  3. With a fake Posthog stub injected, capture forwards the event +
     properties to the SDK, using "anon" when distinct_id is None.
  4. SDK exceptions during capture/flush are swallowed (telemetry
     never propagates errors into request handlers).
"""

from __future__ import annotations

import builtins
import sys
from typing import Any

import pytest

import app.core.telemetry as telemetry


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts with a fresh shim state."""
    monkeypatch.setattr(telemetry, "_client", None)
    monkeypatch.setattr(telemetry, "_initialized", False)


def test_capture_is_noop_when_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("POSTHOG_KEY", raising=False)
    # Should not raise even though the SDK has not been imported.
    telemetry.capture("user-1", "test.event", {"foo": "bar"})
    assert telemetry._client is None


def test_capture_is_noop_when_sdk_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POSTHOG_KEY", "phc_fake")
    # Force `import posthog` inside _maybe_init to fail.
    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "posthog":
            raise ImportError("simulated missing dep")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    telemetry.capture("user-1", "test.event")
    assert telemetry._client is None


def test_capture_forwards_to_sdk_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POSTHOG_KEY", "phc_fake")

    captured: list[dict[str, Any]] = []

    class FakePosthog:
        def __init__(self, key: str, host: str = "") -> None:
            self.key = key
            self.host = host

        def capture(
            self,
            distinct_id: str,
            event: str,
            properties: dict[str, Any],
        ) -> None:
            captured.append(
                {"distinct_id": distinct_id, "event": event, "properties": properties}
            )

        def flush(self) -> None:
            captured.append({"flushed": True})

    fake_module = type(sys)("posthog")
    fake_module.Posthog = FakePosthog  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "posthog", fake_module)

    telemetry.capture("user-42", "today.summary_loaded", {"warmup_done": True})
    telemetry.capture(None, "auth.signed_up")  # anonymous bucket
    telemetry.flush()

    assert len(captured) == 3
    assert captured[0] == {
        "distinct_id": "user-42",
        "event": "today.summary_loaded",
        "properties": {"warmup_done": True},
    }
    assert captured[1]["distinct_id"] == "anon"
    assert captured[2] == {"flushed": True}


def test_sdk_exceptions_are_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTHOG_KEY", "phc_fake")

    class ExplodingPosthog:
        def __init__(self, key: str, host: str = "") -> None:
            pass

        def capture(self, **_: Any) -> None:
            raise RuntimeError("network fell over")

        def flush(self) -> None:
            raise RuntimeError("queue is on fire")

    fake_module = type(sys)("posthog")
    fake_module.Posthog = ExplodingPosthog  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "posthog", fake_module)

    # Neither call should raise.
    telemetry.capture("user-1", "any.event")
    telemetry.flush()


def test_init_failure_disables_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the Posthog constructor itself blows up, we degrade to
    no-op rather than re-trying on every event (which would amplify
    a transient init blip into a flood of warnings)."""
    monkeypatch.setenv("POSTHOG_KEY", "phc_fake")

    class BadPosthog:
        def __init__(self, key: str, host: str = "") -> None:
            raise RuntimeError("constructor failed")

    fake_module = type(sys)("posthog")
    fake_module.Posthog = BadPosthog  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "posthog", fake_module)

    telemetry.capture("user-1", "test.event")
    telemetry.capture("user-1", "test.event2")
    # _client stays None; _initialized flag prevents repeated init.
    assert telemetry._client is None
    assert telemetry._initialized is True
