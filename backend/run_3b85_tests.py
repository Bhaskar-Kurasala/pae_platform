"""Standalone runner for 3B #85 interleaving helpers.

The service file imports sqlalchemy and app models which aren't in the
sandbox Python; AST-extract only the pure helpers
(`should_interleave`, `pick_adjacent_skill`) and run the pure tests.
"""

from __future__ import annotations

import ast
import sys
import traceback
from pathlib import Path

BACKEND = Path(__file__).parent
MODULE = BACKEND / "app" / "services" / "interleaving_service.py"
TESTS = BACKEND / "tests" / "test_services" / "test_interleaving_service.py"

PURE_FUNCS = {"should_interleave", "pick_adjacent_skill"}
PURE_CONSTS = {"_CONSECUTIVE_THRESHOLD", "_SUBMISSION_LOOKBACK"}


def extract(src: str) -> str:
    tree = ast.parse(src)
    kept: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.startswith(("sqlalchemy", "app.")):
                continue
            kept.append(node)
        elif isinstance(node, ast.Import):
            kept.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in PURE_FUNCS:
            kept.append(node)
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any(t in PURE_CONSTS for t in targets):
                kept.append(node)
    return ast.unparse(ast.Module(body=kept, type_ignores=[]))


def strip_app_imports(src: str) -> str:
    tree = ast.parse(src)
    body: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "app."
        ):
            continue
        body.append(node)
    tree.body = body
    return ast.unparse(tree)


def main() -> int:
    src = MODULE.read_text(encoding="utf-8")
    pure = extract(src)
    ns: dict[str, object] = {}
    exec(compile(pure, str(MODULE), "exec"), ns)

    test_src = strip_app_imports(TESTS.read_text(encoding="utf-8"))
    test_ns: dict[str, object] = {
        "should_interleave": ns["should_interleave"],
        "pick_adjacent_skill": ns["pick_adjacent_skill"],
    }
    exec(compile(test_src, str(TESTS), "exec"), test_ns)

    passed = 0
    failed: list[tuple[str, str]] = []
    for name, fn in test_ns.items():
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                passed += 1
                print(f"  ok   {name}")
            except Exception:  # noqa: BLE001
                failed.append((name, traceback.format_exc()))
                print(f"  FAIL {name}")

    print(f"\n{passed} passed, {len(failed)} failed")
    for name, tb in failed:
        print(f"\n--- {name} ---\n{tb}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
