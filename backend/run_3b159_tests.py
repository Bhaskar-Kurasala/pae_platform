"""Standalone runner for 3B #159 request-id helpers.

The module imports starlette/structlog which aren't in the sandbox
Python; we AST-extract just the pure helpers (`_sanitize_client_id`,
`new_request_id`, `HEADER_NAME`, `_MAX_CLIENT_ID_LEN`) and run the
pure tests against them.
"""

from __future__ import annotations

import ast
import sys
import traceback
from pathlib import Path

BACKEND = Path(__file__).parent
MODULE = BACKEND / "app" / "core" / "request_id.py"
TESTS = BACKEND / "tests" / "test_core" / "test_request_id.py"

PURE_NAMES = {
    "HEADER_NAME",
    "_MAX_CLIENT_ID_LEN",
    "_sanitize_client_id",
    "new_request_id",
}


def extract(src: str) -> str:
    tree = ast.parse(src)
    kept: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if (
                mod.startswith("starlette")
                or mod == "structlog"
                or mod.startswith("app.")
                or mod == "collections.abc"
            ):
                continue
            kept.append(node)
        elif isinstance(node, ast.Import):
            # keep `import uuid` etc. drop `import structlog`
            names = [alias.name for alias in node.names]
            if any(n.startswith("structlog") for n in names):
                continue
            kept.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in PURE_NAMES:
            kept.append(node)
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any(t in PURE_NAMES for t in targets):
                kept.append(node)
    return ast.unparse(ast.Module(body=kept, type_ignores=[]))


def main() -> int:
    src = MODULE.read_text(encoding="utf-8")
    pure = extract(src)
    ns: dict[str, object] = {}
    exec(compile(pure, str(MODULE), "exec"), ns)

    # Re-use the tests verbatim, stripping the `app.` import.
    test_src = TESTS.read_text(encoding="utf-8")
    test_tree = ast.parse(test_src)
    test_body: list[ast.stmt] = []
    for node in test_tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "app."
        ):
            continue
        test_body.append(node)
    test_tree.body = test_body
    test_src_clean = ast.unparse(test_tree)

    test_ns: dict[str, object] = {
        "_sanitize_client_id": ns["_sanitize_client_id"],
        "new_request_id": ns["new_request_id"],
    }
    exec(compile(test_src_clean, str(TESTS), "exec"), test_ns)

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
