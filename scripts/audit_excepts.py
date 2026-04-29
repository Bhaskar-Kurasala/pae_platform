"""PR3/C2.1 — audit every except block in backend/app/.

Walks every .py file under backend/app/, finds every ExceptHandler node,
inspects the handler body, and classifies:

  - logged       — body contains a structlog .info/.warning/.error/.exception/.debug call
  - reraised     — body just raises (often appropriate)
  - raises_new   — body raises a *different* exception (often HTTPException)
  - returned     — body returns a deliberate response
  - silent_pass  — body is just `pass` or `...` (red flag unless documented)
  - other        — everything else (manual review)

Plus catches:
  - bare `except:` (no exception type) → automatic flag
  - print() calls in the handler body → flag (CLAUDE.md forbids print)

Run from the repo root:

    python scripts/audit_excepts.py

Re-run any time. Treat the silent_pass + bare_except + has_print
counts as a regression budget: anything > the baseline is a new red
flag. The intentional silent_pass cases (well-commented best-effort
swallows) are expected to stay.
"""
from __future__ import annotations

import ast
from pathlib import Path

# Resolve relative to the script's location so the tool survives CI / a
# different cwd. scripts/ → repo-root → backend/app
ROOT = Path(__file__).resolve().parent.parent / "backend" / "app"

LOG_METHODS = {"info", "warning", "error", "exception", "debug", "critical"}


def classify_handler(handler: ast.ExceptHandler) -> tuple[str, list[str]]:
    """Return (verdict, notes)."""
    notes: list[str] = []
    body = handler.body

    # bare `except:`
    if handler.type is None:
        notes.append("BARE_EXCEPT")

    # body == [Pass()] or [Expr(Constant(...))] (the `...` literal)
    if len(body) == 1:
        stmt = body[0]
        if isinstance(stmt, ast.Pass):
            return ("silent_pass", notes)
        if (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and stmt.value.value is Ellipsis
        ):
            return ("silent_pass", notes)

    # Walk the first ~5 statements; flag log calls and prints.
    has_log = False
    has_print = False
    has_reraise = False
    has_return = False
    has_raise_new = False

    for stmt in body[:8]:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call):
                # log.warning(...) / log.error(...) / etc.
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr in LOG_METHODS
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in {"log", "logger", "logging"}
                ):
                    has_log = True
                # print(...)
                elif isinstance(node.func, ast.Name) and node.func.id == "print":
                    has_print = True
            if isinstance(node, ast.Raise):
                if node.exc is None:
                    has_reraise = True
                else:
                    has_raise_new = True
            if isinstance(node, ast.Return):
                has_return = True

    if has_print:
        notes.append("HAS_PRINT")
    if has_log:
        return ("logged", notes)
    if has_reraise:
        return ("reraised", notes)
    if has_raise_new:
        return ("raises_new", notes)
    if has_return:
        return ("returned", notes)
    return ("other", notes)


def audit_file(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        return [{"file": str(path.relative_to(ROOT.parent)), "line": 0, "verdict": "PARSE_ERROR", "notes": [str(e)], "exc_type": ""}]

    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            verdict, notes = classify_handler(node)
            exc_type = ""
            if node.type is not None:
                exc_type = ast.unparse(node.type)
            rows.append({
                "file": str(path.relative_to(ROOT.parent)),
                "line": node.lineno,
                "verdict": verdict,
                "notes": notes,
                "exc_type": exc_type,
            })
    return rows


def main() -> None:
    all_rows: list[dict[str, object]] = []
    for path in sorted(ROOT.rglob("*.py")):
        all_rows.extend(audit_file(path))

    # Tally
    by_verdict: dict[str, int] = {}
    for r in all_rows:
        by_verdict[r["verdict"]] = by_verdict.get(r["verdict"], 0) + 1
    print("=" * 60)
    print("Verdict tally")
    print("=" * 60)
    for v, n in sorted(by_verdict.items()):
        print(f"  {v:15s}  {n}")
    print(f"  {'TOTAL':15s}  {sum(by_verdict.values())}")

    # Flagged rows: anything not 'logged' or 'reraised' (those are usually fine)
    print()
    print("=" * 60)
    print("FLAGGED (verdict != logged/reraised, or has notes)")
    print("=" * 60)
    flagged = [r for r in all_rows if r["verdict"] not in {"logged", "reraised"} or r["notes"]]
    for r in flagged:
        notes_str = f"  [{','.join(r['notes'])}]" if r["notes"] else ""
        print(f"  {r['file']}:{r['line']:5d}  {r['verdict']:15s}  except {r['exc_type']!s:30s}{notes_str}")
    print(f"\n{len(flagged)} flagged out of {len(all_rows)} total")


if __name__ == "__main__":
    main()
