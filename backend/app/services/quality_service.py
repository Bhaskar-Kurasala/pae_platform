"""Code-quality analysis (P2-08).

Deterministic AST walk that surfaces style / production-readiness issues that
correctness tests alone can't catch. No LLM — this needs to be instant so it
can run every time the student hits Run in the Studio.

Design goal: feedback a senior reviewer would actually care about in a PR.
Avoid bike-shed nits. Every rule must either (a) block a production ship or
(b) teach a durable habit.

Rules implemented (Python):
  - bare-except:     `except:` with no class. Hides real failures.
  - print-debug:     `print(...)` left in code. Use structlog for real logging.
  - missing-type-hints: public `def f(...)` with no annotations on args/return.
  - long-function:   function body > 40 statements. Hard to review / test.
  - mutable-default: `def f(x=[]):` or `={}` default arg. Classic footgun.
  - todo-marker:     TODO / FIXME in code. Track them, don't ship them.
  - no-docstring:    public function > 15 statements with no docstring.

Every finding has `severity` (info / warning) and a `message` that points the
student at the fix, not just the problem.
"""

from __future__ import annotations

import ast
import re
from dataclasses import asdict, dataclass
from typing import Literal

Severity = Literal["info", "warning"]

_LONG_FUNCTION_THRESHOLD = 40
_DOCSTRING_THRESHOLD = 15


@dataclass(frozen=True)
class QualityIssue:
    rule: str
    severity: Severity
    line: int
    message: str


@dataclass(frozen=True)
class QualityReport:
    issues: list[QualityIssue]
    score: int  # 0-100, coarse overall quality signal
    summary: str

    def to_dict(self) -> dict:
        return {
            "issues": [asdict(i) for i in self.issues],
            "score": self.score,
            "summary": self.summary,
        }


def _is_public(name: str) -> bool:
    return not name.startswith("_")


def _has_any_annotation(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if node.returns is not None:
        return True
    for arg in node.args.args + node.args.kwonlyargs:
        if arg.annotation is not None:
            return True
    return False


def _walk_functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    funcs: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append(node)
    return funcs


def _check_functions(
    funcs: list[ast.FunctionDef | ast.AsyncFunctionDef],
) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    for fn in funcs:
        body_len = len(fn.body)

        if _is_public(fn.name) and not _has_any_annotation(fn):
            issues.append(
                QualityIssue(
                    rule="missing-type-hints",
                    severity="warning",
                    line=fn.lineno,
                    message=(
                        f"`{fn.name}` has no type hints. "
                        "Add them — they catch bugs before runtime and document intent."
                    ),
                )
            )

        if body_len > _LONG_FUNCTION_THRESHOLD:
            issues.append(
                QualityIssue(
                    rule="long-function",
                    severity="warning",
                    line=fn.lineno,
                    message=(
                        f"`{fn.name}` is {body_len} statements — hard to review and test. "
                        "Split it into smaller functions with single responsibilities."
                    ),
                )
            )

        if _is_public(fn.name) and body_len > _DOCSTRING_THRESHOLD:
            docstring = ast.get_docstring(fn)
            if not docstring:
                issues.append(
                    QualityIssue(
                        rule="no-docstring",
                        severity="info",
                        line=fn.lineno,
                        message=(
                            f"`{fn.name}` is a non-trivial public function with no docstring. "
                            "A one-liner explaining the contract is worth writing."
                        ),
                    )
                )

        # Mutable default args.
        for default in fn.args.defaults:
            if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                issues.append(
                    QualityIssue(
                        rule="mutable-default",
                        severity="warning",
                        line=default.lineno,
                        message=(
                            "Mutable default argument — it's shared across all calls and causes "
                            "state leaks. Use `None` and create the collection inside the body."
                        ),
                    )
                )
    return issues


def _check_handlers(tree: ast.AST) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            issues.append(
                QualityIssue(
                    rule="bare-except",
                    severity="warning",
                    line=node.lineno,
                    message=(
                        "Bare `except:` swallows every exception including KeyboardInterrupt. "
                        "Catch specific types — or at minimum `except Exception`."
                    ),
                )
            )
    return issues


def _check_calls(tree: ast.AST) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "print":
                issues.append(
                    QualityIssue(
                        rule="print-debug",
                        severity="info",
                        line=node.lineno,
                        message=(
                            "`print()` left in code. In production, use a logger "
                            "(structlog / logging) so output is structured and filterable."
                        ),
                    )
                )
    return issues


_TODO_RE = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b")


def _check_todos(source: str) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    for i, line in enumerate(source.splitlines(), start=1):
        m = _TODO_RE.search(line)
        if m:
            issues.append(
                QualityIssue(
                    rule="todo-marker",
                    severity="info",
                    line=i,
                    message=(
                        f"`{m.group(1)}` marker in code. "
                        "Track it in your issue tracker — shipped TODOs rot."
                    ),
                )
            )
    return issues


def _score_from_issues(issues: list[QualityIssue]) -> int:
    # 100 baseline. Each warning -8, each info -3. Floor at 0.
    penalty = 0
    for i in issues:
        penalty += 8 if i.severity == "warning" else 3
    return max(0, 100 - penalty)


def _summarize(issues: list[QualityIssue], score: int) -> str:
    if not issues:
        return "Clean — nothing to flag."
    warnings = sum(1 for i in issues if i.severity == "warning")
    infos = len(issues) - warnings
    parts = []
    if warnings:
        parts.append(f"{warnings} warning{'s' if warnings != 1 else ''}")
    if infos:
        parts.append(f"{infos} suggestion{'s' if infos != 1 else ''}")
    return f"{', '.join(parts)} (quality score: {score}/100)"


def analyze_quality(source: str) -> QualityReport:
    """Analyze a Python source string and return a quality report.

    Never raises on syntax errors — returns a single-issue report flagging the
    parse failure so the UI can still render something.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        issue = QualityIssue(
            rule="syntax-error",
            severity="warning",
            line=exc.lineno or 1,
            message=f"Syntax error: {exc.msg}. Code won't parse — fix this first.",
        )
        return QualityReport(issues=[issue], score=0, summary="Code doesn't parse.")

    funcs = _walk_functions(tree)
    issues: list[QualityIssue] = []
    issues.extend(_check_functions(funcs))
    issues.extend(_check_handlers(tree))
    issues.extend(_check_calls(tree))
    issues.extend(_check_todos(source))

    # Stable order for deterministic UI: by line, then severity (warnings first).
    severity_order = {"warning": 0, "info": 1}
    issues.sort(key=lambda i: (i.line, severity_order[i.severity]))

    score = _score_from_issues(issues)
    summary = _summarize(issues, score)
    return QualityReport(issues=issues, score=score, summary=summary)
