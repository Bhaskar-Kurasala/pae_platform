"""Standalone runner for 3B #90 desirable-difficulty helpers."""

from __future__ import annotations

import ast
import sys
import traceback
from pathlib import Path

BACKEND = Path(__file__).parent
MODULE = BACKEND / "app" / "services" / "difficulty_service.py"
TESTS = BACKEND / "tests" / "test_services" / "test_difficulty_service.py"

PURE_FUNCS = {"next_difficulty", "prev_difficulty", "recommend_difficulty"}
PURE_CLASSES = {"FirstTryOutcome", "DifficultyRecommendation"}
PURE_CONSTS = {"_DIFFICULTY_LADDER", "_BUMP_UP_WINDOW", "_EASE_DOWN_FAIL_LIMIT"}


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
        elif isinstance(node, ast.ClassDef) and node.name in PURE_CLASSES:
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
        "FirstTryOutcome": ns["FirstTryOutcome"],
        "next_difficulty": ns["next_difficulty"],
        "prev_difficulty": ns["prev_difficulty"],
        "recommend_difficulty": ns["recommend_difficulty"],
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
