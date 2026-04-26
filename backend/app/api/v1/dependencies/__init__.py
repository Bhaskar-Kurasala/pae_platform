"""Reusable FastAPI dependencies for the v1 API.

Stuff in here is intentionally route-agnostic — anything a route can drop
into ``Depends(...)`` lives here so the route file stays a thin
controller.
"""
