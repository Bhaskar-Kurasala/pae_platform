"""PR1/A1.1 — backend endpoint inventory.

Walks every Python file in `backend/app/api/v1/routes/`, parses it with the
stdlib `ast` module (no FastAPI import — keeps the script side-effect-free
and runnable from a clean clone), and emits a row per route:

    method, path, tag, handler, file, line

Output: `docs/audits/endpoints.csv` (sorted by path).

Why ast, not introspection: importing FastAPI here would require booting
the whole app (DB, redis, env vars). We only need the symbol shape.

Usage:
    python scripts/audit_endpoints.py

Sanity check on current main: ~80–100 rows.
"""
from __future__ import annotations

import ast
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROUTES_DIR = REPO / "backend" / "app" / "api" / "v1" / "routes"
OUT_DIR = REPO / "docs" / "audits"
OUT_PATH = OUT_DIR / "endpoints.csv"

# Every route module mounts at /api/v1 via main.py:
#   app.include_router(r, prefix="/api/v1")
# So the full path is /api/v1{router.prefix}{decorator.path}
GLOBAL_PREFIX = "/api/v1"
HTTP_VERBS = {"get", "post", "put", "patch", "delete", "options", "head"}


@dataclass(frozen=True)
class RouteRow:
    method: str
    path: str
    tag: str
    handler: str
    file: str
    line: int


def _extract_router_prefix_and_tags(tree: ast.Module) -> tuple[str, str]:
    """Find `router = APIRouter(prefix=..., tags=[...])` at module level."""
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "router"
        ):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        prefix = ""
        tag = ""
        for kw in node.value.keywords:
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                prefix = kw.value.value or ""
            elif kw.arg == "tags" and isinstance(kw.value, ast.List):
                tags = [
                    e.value
                    for e in kw.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                ]
                tag = tags[0] if tags else ""
        return prefix, tag
    return "", ""


def _route_decorator_info(
    deco: ast.expr,
) -> tuple[str, str] | None:
    """Return (HTTP_METHOD, sub_path) if this is a `@router.<verb>(...)`
    decorator, else None. Path comes from positional arg 0."""
    # Two shapes:
    #   @router.get("/foo")            → ast.Call on ast.Attribute
    #   @router.get("/foo", response_model=...)
    if not isinstance(deco, ast.Call):
        return None
    func = deco.func
    if not isinstance(func, ast.Attribute):
        return None
    if not (isinstance(func.value, ast.Name) and func.value.id == "router"):
        return None
    if func.attr.lower() not in HTTP_VERBS:
        return None
    if not deco.args:
        return None
    first = deco.args[0]
    if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
        return None
    return func.attr.upper(), first.value


def _iter_route_rows(py_file: Path) -> list[RouteRow]:
    src = py_file.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src, filename=str(py_file))
    except SyntaxError as exc:
        print(f"[audit_endpoints] skip {py_file.name}: {exc}", file=sys.stderr)
        return []

    prefix, tag = _extract_router_prefix_and_tags(tree)
    rel_file = str(py_file.relative_to(REPO)).replace("\\", "/")

    rows: list[RouteRow] = []
    for node in tree.body:
        # Both sync and async route handlers count.
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            info = _route_decorator_info(deco)
            if info is None:
                continue
            method, sub_path = info
            full_path = f"{GLOBAL_PREFIX}{prefix}{sub_path}"
            # Normalize trailing slash collisions: keep the path as the
            # author wrote it; FastAPI doesn't auto-rewrite either way.
            rows.append(
                RouteRow(
                    method=method,
                    path=full_path,
                    tag=tag,
                    handler=node.name,
                    file=rel_file,
                    line=node.lineno,
                )
            )
    return rows


def main() -> int:
    if not ROUTES_DIR.is_dir():
        print(f"[audit_endpoints] missing {ROUTES_DIR}", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    all_rows: list[RouteRow] = []
    for py in sorted(ROUTES_DIR.glob("*.py")):
        if py.name.startswith("_") or py.name == "__init__.py":
            continue
        all_rows.extend(_iter_route_rows(py))

    # Health route lives at /health — not under /api/v1.
    health_file = REPO / "backend" / "app" / "api" / "v1" / "routes" / "health.py"
    # We already iterated it; rewrite its rows so /api/v1/health/foo doesn't
    # appear when the actual mount is /health.
    fixed: list[RouteRow] = []
    for r in all_rows:
        if r.file.endswith("/health.py"):
            # main.py mounts health_router with no prefix at app root.
            # The router itself has prefix="/health" in health.py.
            # Strip the GLOBAL_PREFIX we prepended.
            stripped = r.path
            if stripped.startswith(GLOBAL_PREFIX):
                stripped = stripped[len(GLOBAL_PREFIX) :]
            fixed.append(
                RouteRow(
                    method=r.method,
                    path=stripped,
                    tag=r.tag,
                    handler=r.handler,
                    file=r.file,
                    line=r.line,
                )
            )
        else:
            fixed.append(r)

    fixed.sort(key=lambda r: (r.path, r.method))

    with OUT_PATH.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["method", "path", "tag", "handler", "file", "line"])
        for r in fixed:
            writer.writerow([r.method, r.path, r.tag, r.handler, r.file, r.line])

    print(f"[audit_endpoints] wrote {len(fixed)} rows -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
