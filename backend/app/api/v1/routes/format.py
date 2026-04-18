"""Studio code format + lint endpoint — ruff via subprocess (#43, #44)."""

import contextlib
import json
import os
import subprocess
import tempfile

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.security import get_current_user
from app.models.user import User

log = structlog.get_logger()

router = APIRouter(prefix="/format", tags=["format"])

# Monaco MarkerSeverity constants
_SEVERITY_ERROR = 8
_SEVERITY_WARNING = 4


class FormatRequest(BaseModel):
    code: str
    language: str = "python"
    lint_only: bool = False


class FormatResponse(BaseModel):
    code: str
    changed: bool
    # Monaco-compatible marker dicts (camelCase keys expected by the frontend)
    markers: list[dict[str, object]] = []


def _write_temp(code: str) -> str:
    """Write code to a temp file and return the path."""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(code)
        return f.name


def _ruff_format(code: str) -> tuple[str, bool]:
    """Run ruff format on code; return (formatted_code, changed)."""
    tmp = _write_temp(code)
    try:
        subprocess.run(
            ["ruff", "format", tmp],
            capture_output=True,
            timeout=5,
        )
        with open(tmp) as f:
            formatted = f.read()
        return formatted, formatted != code
    except Exception as exc:
        log.warning("studio.format_failed", error=str(exc))
        return code, False
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp)


def _ruff_lint(code: str) -> list[dict[str, object]]:
    """Run ruff check --output-format=json and convert to Monaco markers."""
    tmp = _write_temp(code)
    try:
        result = subprocess.run(
            ["ruff", "check", "--output-format=json", "--no-cache", tmp],
            capture_output=True,
            timeout=5,
        )
        raw = result.stdout.decode("utf-8", errors="replace")
        if not raw.strip():
            return []
        diagnostics: list[dict[str, str | dict[str, int]]] = json.loads(raw)
        markers: list[dict[str, object]] = []
        for d in diagnostics:
            raw_loc = d.get("location", {})
            raw_end = d.get("end_location", raw_loc)
            loc: dict[str, int] = raw_loc if isinstance(raw_loc, dict) else {}
            end_loc: dict[str, int] = raw_end if isinstance(raw_end, dict) else {}
            code_str = str(d.get("code", ""))
            msg = f"[{code_str}] {d.get('message', '')}"
            severity = _SEVERITY_ERROR if code_str.startswith("E") else _SEVERITY_WARNING
            # Monaco camelCase marker shape
            markers.append(
                {
                    "startLineNumber": int(loc.get("row", 1)),
                    "startColumn": int(loc.get("column", 1)),
                    "endLineNumber": int(end_loc.get("row", 1)),
                    "endColumn": int(end_loc.get("column", 1)) + 1,
                    "message": msg,
                    "severity": severity,
                }
            )
        return markers
    except Exception as exc:
        log.warning("studio.lint_failed", error=str(exc))
        return []
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp)


@router.post("", response_model=FormatResponse)
async def format_code(
    body: FormatRequest,
    _: User = Depends(get_current_user),
) -> FormatResponse:
    if body.language != "python":
        return FormatResponse(code=body.code, changed=False, markers=[])

    if body.lint_only:
        markers = _ruff_lint(body.code)
        log.info("studio.lint_applied", marker_count=len(markers))
        return FormatResponse(code=body.code, changed=False, markers=markers)

    formatted, changed = _ruff_format(body.code)
    log.info("studio.format_applied", changed=changed)
    return FormatResponse(code=formatted, changed=changed, markers=[])
