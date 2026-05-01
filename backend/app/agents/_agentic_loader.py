"""Agentic-agent module loader.

Single responsibility: import every module under `app/agents/` that
defines an `AgenticBaseAgent` subclass, so the `__init_subclass__`
hook fires and the agentic registry is populated.

Why this lives in its own file:
  • The legacy `app/agents/registry.py::_ensure_registered` imports
    the legacy BaseAgent modules. We could overload that file, but
    keeping the agentic loader separate means a stale legacy
    agent's import error doesn't take down the agentic side, and
    vice-versa.
  • Boot-order matters: this MUST run before
    `register_proactive_schedules(celery_app)`, which reads the
    decorator-registered schedules. The intent is documented at
    the call site in `app/core/celery_app.py`.

Loud-fail contract (per D7b directive):
  If any agentic agent module fails to import (broken syntax,
  missing dep, bad decorator usage), boot fails LOUDLY here with
  a wrapped exception that names which module broke. A swallowed
  import error means a proactive flow silently stops working in
  prod and nobody notices for a week.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterable

import structlog

log = structlog.get_logger().bind(layer="agentic_loader")


# Modules under app/agents/ that define AgenticBaseAgent subclasses.
# Keep this list in sync as new agentic agents land. The legacy
# BaseAgent modules live in `app/agents/registry.py::_ensure_registered`
# and are NOT loaded here.
_AGENTIC_AGENT_MODULES: tuple[str, ...] = (
    # D8 — reference Learning Coach (replaces socratic_tutor /
    # student_buddy / adaptive_path / spaced_repetition /
    # knowledge_graph). Demonstrates all 5 primitives across chat,
    # cron, and webhook entry points.
    "app.agents.example_learning_coach",
    # "app.agents.engagement_watchdog",      # future
    # "app.agents.code_mentor",              # future
)


class AgenticAgentImportError(RuntimeError):
    """Boot-time failure importing an agentic agent module.

    Wraps the underlying exception with the module name so the
    operator sees the diagnosis without spelunking through a
    multi-frame traceback. Always raised with `from exc` so the
    original cause is preserved.
    """


def load_agentic_agents(
    *,
    modules: Iterable[str] | None = None,
) -> list[str]:
    """Import every agentic agent module so subclasses register.

    Returns the list of module names that imported successfully.
    Raises `AgenticAgentImportError` on the first failure — the
    call site (Celery beat / FastAPI startup) is responsible for
    catching and crashing the process loudly. We don't continue
    past a broken module: a partial registration is worse than no
    registration, because it makes "did my agent fire?" a guessing
    game.

    `modules` is overridable for tests that want to inject a
    different list. Production callers pass nothing and use the
    module-level constant.
    """
    target = list(modules) if modules is not None else list(_AGENTIC_AGENT_MODULES)
    if not target:
        log.info("agentic_loader.empty")
        return []

    loaded: list[str] = []
    for module_name in target:
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001 - we want every cause surfaced
            # Re-raise with context so the operator sees which
            # module is broken, not a generic ImportError 6 frames
            # deep. `from exc` keeps the original traceback chain.
            raise AgenticAgentImportError(
                f"failed to import agent module {module_name!r}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        loaded.append(module_name)
    log.info(
        "agentic_loader.loaded",
        count=len(loaded),
        modules=loaded,
    )
    return loaded


__all__ = [
    "AgenticAgentImportError",
    "load_agentic_agents",
]
