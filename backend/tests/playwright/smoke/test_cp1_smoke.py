"""D18 Phase A CP1 smoke — Playwright + pytest-playwright are wired correctly.

What this proves:
- pytest-playwright is installed and discovers tests under backend/tests/playwright/.
- The browser binary (chromium) is installed and launches.
- The conftest base_url / viewport overrides apply.
- The frontend container is reachable on PLAYWRIGHT_BASE_URL.
- The /login route renders login-shaped content.

What this does NOT prove (deferred to later CPs):
- Database isolation (CP2)
- Page object models (CP3)
- Fixture seeding (CP4)
- Assertion helpers / budget (CP5)
- CI parallelization + production build pipeline (CP6)

Forgiving assertion strategy (per CP1 Q1 confirmation): the smoke verifies
"a login page rendered" without pinning DOM structure. Any of the following
signals counts: an email input (by type, name, id, or testid), the URL
ending at /login, the document title containing 'login', or 'login' /
'sign in' appearing in body text. Brittle exact-DOM matching belongs in
journey tests with stable selectors, not infrastructure smoke.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect


_STACK_DOWN_HINT = (
    "\n\nIf the smoke failed because the stack is unreachable, start it with:\n"
    "    docker compose up -d --build\n"
    "    docker compose exec backend uv run alembic upgrade head\n"
    "Then re-run:\n"
    "    cd backend && uv run pytest tests/playwright/smoke/test_cp1_smoke.py -v\n"
    "See docs/testing/playwright-setup.md for the full setup checklist."
)


def test_can_open_login_page(page: Page, base_url: str) -> None:
    """Navigate to /login and verify login-shaped content rendered.

    Uses a chain of forgiving signals (email input ∨ URL ∨ title ∨ body
    text) so the smoke stays green across cosmetic UI changes. Smoke
    tests verify infrastructure works; structural assertions live in
    journey tests.
    """
    try:
        response = page.goto(f"{base_url}/login", wait_until="domcontentloaded")
    except Exception as exc:  # noqa: BLE001 — re-raise with operator hint
        raise AssertionError(
            f"Could not reach {base_url}/login — Playwright raised {type(exc).__name__}: {exc}."
            + _STACK_DOWN_HINT
        ) from exc

    assert response is not None, (
        f"page.goto({base_url}/login) returned no response object." + _STACK_DOWN_HINT
    )
    assert response.ok, (
        f"GET {base_url}/login returned HTTP {response.status}; "
        f"expected 2xx for a rendered login page." + _STACK_DOWN_HINT
    )

    # Forgiving signal chain. Any one is enough.
    email_input = page.locator(
        "input[type='email'], input[name='email'], input[id='email'], "
        "[data-testid='email-input'], [data-testid='login-email']"
    )
    if email_input.count() > 0:
        expect(email_input.first).to_be_visible()
        return

    title = (page.title() or "").lower()
    if "login" in title or "sign in" in title:
        return

    if "/login" in page.url.lower():
        # URL settled at /login — page rendered without redirecting away.
        # Double-check there's at least *some* body text so we didn't
        # match a 200 OK with an empty/loading-spinner shell.
        body_text = (page.locator("body").inner_text(timeout=5_000) or "").lower()
        if "login" in body_text or "sign in" in body_text or "email" in body_text:
            return

    body_text = (page.locator("body").inner_text(timeout=5_000) or "").lower()
    raise AssertionError(
        "Reached /login but no login-shaped signal found "
        "(no email input, title doesn't contain 'login'/'sign in', "
        "URL didn't settle at /login, body text didn't mention "
        "'login'/'sign in'/'email'). "
        f"Final URL: {page.url}. Title: {page.title()!r}. "
        f"First 200 chars of body: {body_text[:200]!r}."
        + _STACK_DOWN_HINT
    )
