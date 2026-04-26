"""Resolve a ``LessonResource`` row to an actual ``open_url`` for the UI.

Notebooks resolve to a Colab URL pointed at the private content repo —
Colab loads it through the user's GitHub auth; for users without access
the backend can mirror the file via the API in a future iteration. Repos,
videos, and links resolve to their declared URL. PDFs/slides resolve to
a (future) signed download URL — for v1 we 501 these so we don't ship
something half-working.

This module is the *only* place that knows how to convert a repo-relative
``path`` into a public URL. The DB stays repo-relative so we can swap the
resolution strategy (Colab → S3-signed → in-app viewer) without a migration.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import HTTPException

from app.core.config import settings
from app.models.lesson_resource import LessonResource


def _colab_url_for_path(path: str) -> str:
    """Build a Colab URL that opens a notebook from the private content repo."""
    if not settings.github_content_repo:
        raise HTTPException(
            status_code=503,
            detail="github_content_repo is not configured on the server",
        )
    repo = settings.github_content_repo.strip("/")
    branch = settings.github_content_branch or "main"
    safe_path = quote(path.lstrip("/"))
    return f"https://colab.research.google.com/github/{repo}/blob/{branch}/{safe_path}"


def _github_blob_url_for_path(path: str) -> str:
    repo = settings.github_content_repo.strip("/")
    branch = settings.github_content_branch or "main"
    safe_path = quote(path.lstrip("/"))
    return f"https://github.com/{repo}/blob/{branch}/{safe_path}"


def resolve_open_url(resource: LessonResource) -> str:
    """Return the URL the browser should open for a given resource."""
    kind = resource.kind

    if kind == "notebook":
        if resource.path:
            return _colab_url_for_path(resource.path)
        if resource.url:
            return resource.url
        raise HTTPException(
            status_code=500,
            detail=f"notebook resource {resource.id} has neither path nor url",
        )

    if kind in ("repo", "video", "link"):
        if resource.url:
            return resource.url
        raise HTTPException(
            status_code=500,
            detail=f"{kind} resource {resource.id} requires a url",
        )

    if kind in ("pdf", "slides"):
        # v1 falls back to GitHub's blob viewer if path-based; signed
        # download URLs come in v2.
        if resource.path:
            return _github_blob_url_for_path(resource.path)
        if resource.url:
            return resource.url
        raise HTTPException(
            status_code=501,
            detail=f"{kind} resources without a url are not yet downloadable",
        )

    raise HTTPException(status_code=500, detail=f"unknown resource kind: {kind}")
