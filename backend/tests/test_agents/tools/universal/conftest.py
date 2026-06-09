"""Reuse the pg_session + voyage_disabled fixtures from the
primitives conftest. These tests need the same Postgres + pgvector
setup the primitives tests have because they exercise the universal
tools' MemoryStore round-trips end-to-end.

Importing the names here lets pytest discover them as fixtures
in this subtree without copying the schema-creation code.
"""

from __future__ import annotations

import pytest

# Re-export the primitives fixtures into this subtree.
# pytest treats names imported into a conftest as available fixtures.
from tests.test_agents.primitives.conftest import (  # noqa: F401
    _pg_available,
    pg_session,
    voyage_disabled,
)


@pytest.fixture(autouse=True)
def _ensure_universal_tools_registered() -> None:
    """Defensive: re-register the five universal tools before each
    test in this subtree.

    Why this fixture exists:
      tests/test_agents/primitives/test_tools.py has a module-scoped
      autouse fixture that calls `tool_registry.clear()` and then
      reloads ONLY its own theme modules. When test_tools runs
      before this subtree (alphabetical pytest collection order),
      its teardown leaves the registry without the five universal
      tools. Tests here that assert registry membership then fail.

      We can't call test_tools' fixture from here (it's module-
      scoped), and we don't want to widen its responsibility
      (universal tools live in their own subtree). The cheapest fix
      is a one-line guard in this subtree's conftest: importlib-
      reload the universal modules so their @tool decorators re-fire.
      The package-level reload of `tools_pkg` in test_tools' fixture
      already re-executes `from . import universal` but that
      re-imports the cached module (no-op); only an explicit
      `importlib.reload` of each universal sub-module re-runs the
      decorators.

      The reload pattern is the same as test_tools' fixture, but
      scoped to just this subtree. Module-level imports of
      MemoryWriteOutput etc. in test_universal_tools.py would break
      under reload (see the D10 Checkpoint 1 status report on the
      isinstance trap), so this fixture intentionally does NOT
      reload — it relies on `import` to be a no-op when the module
      is already in sys.modules. If the registry is empty (because
      test_tools cleared it), we must re-register; if the registry
      already has these names, registering raises DuplicateToolError
      and we skip.
    """
    from app.agents.primitives.tools import (
        DuplicateToolError,
        registry,
        tool,
    )
    from app.agents.tools.universal.log_event import (
        LogEventInput,
        LogEventOutput,
        log_event,
    )
    from app.agents.tools.universal.memory_forget import (
        MemoryForgetInput,
        MemoryForgetOutput,
        memory_forget,
    )
    from app.agents.tools.universal.memory_recall import (
        MemoryRecallInput,
        MemoryRecallOutput,
        memory_recall,
    )
    from app.agents.tools.universal.memory_write import (
        MemoryWriteInput,
        MemoryWriteOutput,
        memory_write,
    )
    from app.agents.tools.universal.read_own_capability import (
        ReadOwnCapabilityInput,
        ReadOwnCapabilityOutput,
        read_own_capability,
    )

    # Each universal tool's spec is stashed on the function via
    # `func.spec` by the @tool decorator. If the registry already
    # has the name, do nothing (test_universal_tools-only run path).
    # If not, re-register from the cached spec (post-test_tools-clear
    # path).
    have = set(registry.names())
    for fn in (
        memory_recall,
        memory_write,
        memory_forget,
        log_event,
        read_own_capability,
    ):
        spec = getattr(fn, "spec", None)
        if spec is None or spec.name in have:
            continue
        try:
            registry.register(spec)
        except DuplicateToolError:
            # Race: another fixture re-registered between have-check
            # and now. Safe to ignore.
            pass
