"""Shared HTTP helpers for D18 Phase B CP1 journey tests.

Wraps urllib + JSON conventions used across journey tests. Keeps
each test file focused on the journey under test rather than the
HTTP plumbing. Low-LoC; no external deps beyond stdlib.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

API_BASE = os.environ.get("PLAYWRIGHT_API_BASE", "http://nginx/api/v1")


def post_json(
    path: str,
    *,
    token: str | None = None,
    body: dict | None = None,
    timeout: int = 30,
) -> tuple[int, Any]:
    """Authed (or anonymous) POST; returns (status, parsed body).

    Default timeout is 30s for typical CRUD operations. LLM-bearing
    endpoints (e.g., /agentic/default/chat) can take 30-60s; pass
    timeout=120 for those tests.
    """
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(
        url=f"{API_BASE}{path}", data=data, headers=headers, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except Exception:
            return exc.code, None


def get_json(path: str, *, token: str | None = None) -> tuple[int, Any]:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        url=f"{API_BASE}{path}", headers=headers, method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except Exception:
            return exc.code, None


def delete_json(path: str, *, token: str) -> int:
    req = urllib.request.Request(
        url=f"{API_BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        method="DELETE",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status
