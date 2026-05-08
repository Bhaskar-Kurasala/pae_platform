"""D18 Phase A — Playwright suite root configuration.

Configures pytest-playwright defaults (base URL, viewport, headless,
default timeout). Subsequent CPs add session-scoped DB reset (CP2),
fixture extensions (CP4), assertion helpers (CP5), and budget tracking
(CP5/CP6).

Two-suite world:
- This suite (Python pytest-playwright at backend/tests/playwright/) drives
  backend-fixture-driven full-stack journeys.
- frontend/e2e/ (TypeScript @playwright/test) drives frontend-team-owned
  UI smoke. Phase B respects the boundary.

The stack must be running before this suite executes (docker compose up -d).
See docs/testing/playwright-setup.md.
"""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest

DEFAULT_BASE_URL = "http://localhost:3002"
DEFAULT_VIEWPORT = {"width": 1920, "height": 1080}
DEFAULT_TIMEOUT_MS = 30_000


def _base_url() -> str:
    return os.environ.get("PLAYWRIGHT_BASE_URL", DEFAULT_BASE_URL)


@pytest.fixture(scope="session")
def base_url() -> str:
    """Override pytest-playwright's default base URL.

    Default targets the docker-compose frontend (host port 3002 per
    README + frontend/CLAUDE.md). Override via PLAYWRIGHT_BASE_URL env
    var (e.g. http://localhost:3000 for `pnpm dev` host workflow, or
    http://frontend:3000 for in-container CI).
    """
    return _base_url()


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict) -> dict:
    """Desktop-first viewport per D-A scope. Mobile deferred post-launch."""
    return {
        **browser_context_args,
        "viewport": DEFAULT_VIEWPORT,
        "base_url": _base_url(),
    }


@pytest.fixture(autouse=True)
def _set_default_timeout(page) -> Generator[None, None, None]:  # type: ignore[no-untyped-def]
    """30s default per-action timeout. Per-test overrides via page.set_default_timeout()."""
    page.set_default_timeout(DEFAULT_TIMEOUT_MS)
    yield
