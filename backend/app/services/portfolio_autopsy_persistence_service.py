"""Persist Portfolio Autopsy results so the Proof Portfolio view can list past
autopsies and the Application Kit can attach the strongest one.

The autopsy endpoint used to score and discard. Now every successful run lands
in `portfolio_autopsy_results` (one row per run, never updated). This module
owns the write-and-read shape: route handlers stay thin and just call into the
helpers below.

Persistence is best-effort from the route's perspective — the score is the
product, the row is the receipt. If the DB write fails the user still gets
their feedback and we log the failure rather than 500'ing.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, is_dataclass
from typing import Any

import structlog
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portfolio_autopsy_result import PortfolioAutopsyResult
from app.models.user import User

log = structlog.get_logger()


_AXIS_KEYS = ("architecture", "failure_handling", "observability", "scope_discipline")


def _axis_to_dict(axis: Any) -> dict[str, Any]:
    """Coerce one axis (dataclass / object / dict) to `{score, assessment}`.

    Defensive defaults: missing fields fall back to score=0 / empty assessment
    so a half-formed `PortfolioAutopsy` never breaks persistence.
    """
    if axis is None:
        return {"score": 0, "assessment": ""}
    if isinstance(axis, dict):
        return {
            "score": axis.get("score", 0),
            "assessment": axis.get("assessment", ""),
        }
    score = getattr(axis, "score", 0)
    assessment = getattr(axis, "assessment", "")
    return {"score": score, "assessment": assessment}


def axes_to_dict(result: Any) -> dict[str, dict[str, Any]]:
    """Pure helper: project the four axes off a `PortfolioAutopsy` into JSON.

    Shape:
        {
          "architecture":     {"score": int, "assessment": str},
          "failure_handling": {"score": int, "assessment": str},
          "observability":    {"score": int, "assessment": str},
          "scope_discipline": {"score": int, "assessment": str},
        }
    """
    return {key: _axis_to_dict(getattr(result, key, None)) for key in _AXIS_KEYS}


def _findings_to_list(result: Any) -> list[dict[str, Any]]:
    findings = getattr(result, "what_to_do_differently", []) or []
    out: list[dict[str, Any]] = []
    for f in findings:
        if isinstance(f, dict):
            out.append(
                {
                    "issue": f.get("issue", ""),
                    "why_it_matters": f.get("why_it_matters", ""),
                    "what_to_do_differently": f.get("what_to_do_differently", ""),
                }
            )
        elif is_dataclass(f):
            out.append(asdict(f))
        else:
            out.append(
                {
                    "issue": getattr(f, "issue", ""),
                    "why_it_matters": getattr(f, "why_it_matters", ""),
                    "what_to_do_differently": getattr(f, "what_to_do_differently", ""),
                }
            )
    return out


def _payload_to_dict(payload: Any) -> dict[str, Any] | None:
    """Best-effort serialise the request payload (Pydantic v2, dict, or None)."""
    if payload is None:
        return None
    if isinstance(payload, dict):
        return payload
    dump = getattr(payload, "model_dump", None)
    if callable(dump):
        return dump()  # type: ignore[no-any-return]
    legacy = getattr(payload, "dict", None)
    if callable(legacy):
        return legacy()  # type: ignore[no-any-return]
    return None


async def persist_autopsy_result(
    db: AsyncSession,
    *,
    user: User,
    request_payload: Any,
    result: Any,
) -> PortfolioAutopsyResult:
    """Insert one row capturing this autopsy run.

    `request_payload` is the original `AutopsyRequest` (Pydantic) — we stash
    the dict form on `raw_request` for audit. `result` is the
    `PortfolioAutopsy` dataclass returned by `run_autopsy`.
    """
    raw_request = _payload_to_dict(request_payload)
    project_title = (
        getattr(request_payload, "project_title", None)
        or (raw_request or {}).get("project_title")
        or ""
    )
    project_description = (
        getattr(request_payload, "project_description", None)
        or (raw_request or {}).get("project_description")
        or ""
    )
    code = getattr(request_payload, "code", None)
    if code is None and raw_request is not None:
        code = raw_request.get("code")

    row = PortfolioAutopsyResult(
        user_id=user.id,
        project_title=project_title,
        project_description=project_description,
        code=code,
        headline=getattr(result, "headline", "") or "",
        overall_score=int(getattr(result, "overall_score", 0) or 0),
        axes=axes_to_dict(result),
        what_worked=list(getattr(result, "what_worked", []) or []),
        what_to_do_differently=_findings_to_list(result),
        production_gaps=list(getattr(result, "production_gaps", []) or []),
        next_project_seed=getattr(result, "next_project_seed", None),
        raw_request=raw_request,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def list_autopsies_for_user(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    limit: int = 20,
) -> list[PortfolioAutopsyResult]:
    """Newest-first list of autopsies owned by `user_id`."""
    q = (
        select(PortfolioAutopsyResult)
        .where(PortfolioAutopsyResult.user_id == user_id)
        .order_by(desc(PortfolioAutopsyResult.created_at))
        .limit(limit)
    )
    rows = (await db.execute(q)).scalars().all()
    return list(rows)


async def get_autopsy_for_user(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    autopsy_id: uuid.UUID,
) -> PortfolioAutopsyResult | None:
    """Return the row only if `user_id` owns it. None otherwise (incl. 404)."""
    q = select(PortfolioAutopsyResult).where(
        PortfolioAutopsyResult.id == autopsy_id,
        PortfolioAutopsyResult.user_id == user_id,
    )
    return (await db.execute(q)).scalar_one_or_none()
