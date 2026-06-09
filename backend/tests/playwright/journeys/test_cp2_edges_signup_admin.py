"""D18 Phase B CP2 — edge cases for signup (a) and admin (h+j).

Backend-driven edges; cost class low (no LLM agents invoked).
Pattern 22: each edge verified against live route shape before
authoring.

Edges covered:
  (a) signup edges:
    1. Duplicate email → 409 Conflict
    2. Password lacks min_length client-side enforcement (server
       accepts any password length — regression guard for the
       intentional "frontend validates" contract).

  (j) admin login + dashboard edges:
    1. Cockpit reachable with empty roster (no at-risk students
       seeded) — empty-state surface.
    2. Anonymous request to admin endpoint → 401 (auth required).

  (h) admin retention edges:
    1. Create note targeting a non-existent student → 404 (not
       a silent success that orphans rows).
    2. Create note then re-fetch via GET — note round-trips with
       admin attribution preserved (idempotent observation).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid as _uuid

import pytest
from playwright.sync_api import Page

from tests.fixtures.admin_fixtures import seed_admin_user_with_login
from tests.fixtures.role_state_fixtures import seed_python_developer_fresh
from tests.playwright.helpers.sync_async_bridge import (
    cleanup_student_via_db,
    fetch_token_via_http,
    register_via_http,
    seed_student_via_db,
)

from ._journey_helpers import API_BASE, get_json, post_json

pytestmark = [pytest.mark.edge_case, pytest.mark.cost("low")]


# ── Journey (a) signup edges ────────────────────────────────────────


def test_signup_duplicate_email_returns_409(page: Page) -> None:
    """Second register with the same email returns 409 Conflict.

    Pattern 22-verified: auth_service.py:register raises
    HTTPException(409, "Email already registered") when
    repo.get_by_email returns a user.
    """
    suffix = _uuid.uuid4().hex[:12]
    email = f"d18-cp2a-dup-{suffix}@example.com"
    user_id = register_via_http(
        email=email, password="DupePass123!", full_name="CP2A Dup #1",
    )
    try:
        # Second register attempt with the same email.
        req = urllib.request.Request(
            url=f"{API_BASE}/auth/register",
            data=json.dumps({
                "email": email,
                "password": "DifferentPass456!",
                "full_name": "CP2A Dup #2",
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                pytest.fail(
                    f"duplicate-email register accepted; status={resp.status}"
                )
        except urllib.error.HTTPError as exc:
            assert exc.code == 409, (
                f"expected 409 Conflict on duplicate email; got {exc.code}"
            )
    finally:
        cleanup_student_via_db(user_id)


def test_signup_accepts_short_password_server_side(page: Page) -> None:
    """Backend accepts short passwords; frontend enforces min length.

    Pattern 22 contract verification: the server-side schema
    `UserCreate.password: str` has no min_length validator. The
    frontend register form refuses < 8 chars before submission;
    the contract is "frontend gates, backend trusts." This test
    pins the server-side contract — if a backend min_length is
    added later, this test catches the regression and the
    frontend's min-length enforcement can be relaxed (or this
    test's expectation flipped).
    """
    suffix = _uuid.uuid4().hex[:12]
    email = f"d18-cp2a-short-{suffix}@example.com"
    short_password = "short"  # 5 chars; would fail frontend's 8-char check
    req = urllib.request.Request(
        url=f"{API_BASE}/auth/register",
        data=json.dumps({
            "email": email,
            "password": short_password,
            "full_name": "CP2A Short Pass",
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    user_id: _uuid.UUID | None = None
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 201, (
                f"backend rejected short password (status={resp.status}); "
                f"frontend-only enforcement contract broken"
            )
            body = json.loads(resp.read().decode("utf-8"))
            user_id = _uuid.UUID(body["id"])
    finally:
        if user_id is not None:
            cleanup_student_via_db(user_id)


# ── Journey (j) admin login + dashboard edges ──────────────────────


def test_admin_endpoints_require_auth(page: Page) -> None:
    """GET /admin/students without a token → 401 Unauthorized."""
    req = urllib.request.Request(
        url=f"{API_BASE}/admin/students",
        headers={},  # no Authorization
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            pytest.fail(
                f"unauth admin endpoint accepted; status={resp.status}"
            )
    except urllib.error.HTTPError as exc:
        # 401 Unauthorized OR 403 Forbidden are both acceptable —
        # depends on whether the route uses Depends(get_current_user)
        # which raises 401, or a stricter admin-required dep.
        assert exc.code in (401, 403), (
            f"expected 401/403 on unauth admin call; got {exc.code}"
        )


def test_admin_at_risk_endpoint_returns_list_even_when_empty(
    page: Page,
) -> None:
    """GET /admin/at-risk-students returns 200 + list when no students
    are at risk (empty-state surface)."""
    admin = seed_student_via_db(seed_admin_user_with_login)
    token = fetch_token_via_http(email=admin.email, password=admin.password)
    try:
        status, body = get_json("/admin/at-risk-students", token=token)
        assert status == 200
        assert isinstance(body, list), (
            f"empty-state should still return a list; got {type(body).__name__}"
        )
        # Don't assert len==0; other tests may have seeded at-risk
        # students. Just verify the endpoint shape.
    finally:
        cleanup_student_via_db(admin.user_id)


# ── Journey (h) admin retention edges ──────────────────────────────


def test_admin_note_on_nonexistent_student_returns_404(page: Page) -> None:
    """POST /admin/students/{nonexistent}/notes → 404 Not Found."""
    admin = seed_student_via_db(seed_admin_user_with_login)
    token = fetch_token_via_http(email=admin.email, password=admin.password)
    try:
        nonexistent_id = _uuid.uuid4()
        status, body = post_json(
            f"/admin/students/{nonexistent_id}/notes",
            token=token,
            body={"body_md": "should not land — student doesn't exist"},
        )
        assert status == 404, (
            f"expected 404 for nonexistent student; got {status}: {body}"
        )
    finally:
        cleanup_student_via_db(admin.user_id)


def test_admin_note_round_trips_via_get_with_attribution(page: Page) -> None:
    """Create note via POST, retrieve via GET; verify attribution preserved."""
    admin = seed_student_via_db(seed_admin_user_with_login)
    token = fetch_token_via_http(email=admin.email, password=admin.password)
    student = seed_student_via_db(seed_python_developer_fresh)
    try:
        body_text = "CP2H round-trip — verify attribution survives GET"
        post_status, _ = post_json(
            f"/admin/students/{student.user_id}/notes",
            token=token,
            body={"body_md": body_text},
        )
        assert post_status == 201

        get_status, get_body = get_json(
            f"/admin/students/{student.user_id}/notes", token=token,
        )
        assert get_status == 200
        assert isinstance(get_body, list)
        assert len(get_body) >= 1

        # Find the note we just created.
        match = next(
            (n for n in get_body if n["body_md"] == body_text), None,
        )
        assert match is not None, (
            f"note not found in GET response; got {len(get_body)} notes"
        )
        assert match["admin_id"] == str(admin.user_id), (
            f"admin attribution drifted between POST and GET: "
            f"{match['admin_id']} != {admin.user_id}"
        )
        assert match["student_id"] == str(student.user_id)
    finally:
        cleanup_student_via_db(student.user_id)
        cleanup_student_via_db(admin.user_id)
