"""Misconception detection (P2-09).

Correctness tests catch wrong *answers*. This module catches wrong *mental
models* — the hidden misunderstandings that produce lots of different-looking
bugs from one root cause. Fix the bug and the student still holds the bad
model; name the model and they never write that family of bug again.

Deterministic AST walk (no LLM) so it's instant and can ride every Run.

Design principles:
  - Every finding names the misconception, not the symptom
  - Every finding includes a one-line "what you probably think" and "what's
    actually true" pair, because that's the teaching moment
  - Rules are conservative — a false positive here erodes trust. If in doubt,
    don't flag.

Rules:
  - is-with-literal:  `x is "foo"` / `x is 5` — identity vs equality
  - eq-none:          `x == None` / `x != None` — use `is None`
  - range-len:        `for i in range(len(xs)): ... xs[i]` — iterate directly
  - concat-in-loop:   `s += ...` with str accumulator — strings are immutable
  - mutable-class-attr: `class C: items = []` — shared across instances
  - silent-except:    `except ...: pass` or empty — errors aren't noise
  - mutate-no-return: function mutates a list param and returns None — caller
                      confusion about "did my list change?"
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from typing import Literal

Severity = Literal["info", "warning"]


@dataclass(frozen=True)
class Misconception:
    code: str              # short slug, e.g. "is-with-literal"
    title: str             # human title, e.g. "Using `is` to compare values"
    line: int
    severity: Severity
    you_think: str         # the student's probable mental model
    actually: str          # what's really true
    fix_hint: str          # concrete nudge toward the fix


@dataclass(frozen=True)
class MisconceptionReport:
    items: list[Misconception]
    summary: str

    def to_dict(self) -> dict:
        return {
            "items": [asdict(m) for m in self.items],
            "summary": self.summary,
        }


def _is_literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and not isinstance(node.value, type(None))


def _check_is_with_literal(tree: ast.AST) -> list[Misconception]:
    out: list[Misconception] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        for op, right in zip(node.ops, node.comparators, strict=False):
            if isinstance(op, (ast.Is, ast.IsNot)) and _is_literal(right):
                out.append(
                    Misconception(
                        code="is-with-literal",
                        title="Using `is` to compare values",
                        line=node.lineno,
                        severity="warning",
                        you_think="`is` and `==` both check if two things are equal.",
                        actually=(
                            "`is` checks whether two names point to the same object in memory. "
                            "It only works for values by accident (small-int cache, interned strings). "
                            "Use `==` for value equality; reserve `is` for `None`, `True`, `False`."
                        ),
                        fix_hint="Replace `is` / `is not` with `==` / `!=` here.",
                    )
                )
    return out


def _check_eq_none(tree: ast.AST) -> list[Misconception]:
    out: list[Misconception] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        for op, right in zip(node.ops, node.comparators, strict=False):
            is_none = isinstance(right, ast.Constant) and right.value is None
            if is_none and isinstance(op, (ast.Eq, ast.NotEq)):
                out.append(
                    Misconception(
                        code="eq-none",
                        title="Comparing to `None` with `==`",
                        line=node.lineno,
                        severity="info",
                        you_think="`== None` and `is None` are interchangeable.",
                        actually=(
                            "`None` is a singleton — there's exactly one. Identity (`is`) is the "
                            "correct check, and it can't be overridden by a pathological __eq__."
                        ),
                        fix_hint="Use `is None` / `is not None`.",
                    )
                )
    return out


def _check_range_len(tree: ast.AST) -> list[Misconception]:
    """`for i in range(len(xs)): ... xs[i]` → iterate directly."""
    out: list[Misconception] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        it = node.iter
        # range(len(xs))
        if (
            isinstance(it, ast.Call)
            and isinstance(it.func, ast.Name)
            and it.func.id == "range"
            and len(it.args) == 1
            and isinstance(it.args[0], ast.Call)
            and isinstance(it.args[0].func, ast.Name)
            and it.args[0].func.id == "len"
            and len(it.args[0].args) == 1
            and isinstance(it.args[0].args[0], ast.Name)
        ):
            out.append(
                Misconception(
                    code="range-len",
                    title="Iterating by index instead of by value",
                    line=node.lineno,
                    severity="info",
                    you_think="To loop over a list I need an index variable like in C/Java.",
                    actually=(
                        "In Python you iterate the collection directly: `for x in xs`. "
                        "If you need the index too, use `enumerate(xs)`."
                    ),
                    fix_hint="Replace `for i in range(len(xs)):` with `for x in xs:` or `for i, x in enumerate(xs):`.",
                )
            )
    return out


def _check_concat_in_loop(tree: ast.AST) -> list[Misconception]:
    """Detect `s += "..."` or `s = s + "..."` inside a `for`/`while` where the
    accumulator is a string literal. Strings are immutable — this is O(n²)."""
    out: list[Misconception] = []
    for loop in ast.walk(tree):
        if not isinstance(loop, (ast.For, ast.While)):
            continue
        for inner in ast.walk(loop):
            if isinstance(inner, ast.AugAssign) and isinstance(inner.op, ast.Add):
                if _looks_like_string_value(inner.value):
                    out.append(_concat_misc(inner.lineno))
                    break
    return out


def _looks_like_string_value(node: ast.AST) -> bool:
    """Heuristic: is this expression obviously a string?"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    if isinstance(node, ast.JoinedStr):  # f-string
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        # "fmt" % ... — rare but treat as string
        return _looks_like_string_value(node.left)
    return False


def _concat_misc(line: int) -> Misconception:
    return Misconception(
        code="concat-in-loop",
        title="Building a string with `+=` inside a loop",
        line=line,
        severity="info",
        you_think="Appending to a string is like appending to a list — cheap.",
        actually=(
            "Strings are immutable. Each `s += x` allocates a new string and copies the old "
            "one — O(n²) for n iterations. Build a list of parts and `''.join(...)` at the end."
        ),
        fix_hint="Collect pieces in a list and `''.join(parts)` after the loop.",
    )


def _check_mutable_class_attr(tree: ast.AST) -> list[Misconception]:
    out: list[Misconception] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and isinstance(
                stmt.value, (ast.List, ast.Dict, ast.Set)
            ):
                out.append(
                    Misconception(
                        code="mutable-class-attr",
                        title="Mutable value as class attribute",
                        line=stmt.lineno,
                        severity="warning",
                        you_think="`class C: items = []` gives each instance its own list.",
                        actually=(
                            "Class-level assignments are shared across all instances. "
                            "`C().items.append(1)` mutates the list every instance sees."
                        ),
                        fix_hint="Move the assignment into `__init__`: `self.items = []`.",
                    )
                )
    return out


def _check_silent_except(tree: ast.AST) -> list[Misconception]:
    out: list[Misconception] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        body = node.body
        only_pass = len(body) == 1 and isinstance(body[0], ast.Pass)
        only_ellipsis = (
            len(body) == 1
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and body[0].value.value is Ellipsis
        )
        if only_pass or only_ellipsis:
            out.append(
                Misconception(
                    code="silent-except",
                    title="Swallowing an exception with `pass`",
                    line=node.lineno,
                    severity="warning",
                    you_think="If I catch the error the program keeps working — job done.",
                    actually=(
                        "A silent `except: pass` hides real bugs. You lose the error, the "
                        "traceback, and any chance of diagnosing why the next thing fails."
                    ),
                    fix_hint="At minimum log the exception; better, handle the specific type you expect.",
                )
            )
    return out


def _check_mutate_no_return(tree: ast.AST) -> list[Misconception]:
    """Function mutates a list-typed parameter (via .append/.extend/indexed
    assignment) and never returns a value → caller probably expects the
    *returned* list to be the new one."""
    out: list[Misconception] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        param_names = {a.arg for a in fn.args.args}
        if not param_names:
            continue

        mutates = False
        returns_value = False
        for node in ast.walk(fn):
            if node is fn:
                continue
            if isinstance(node, ast.Return) and node.value is not None:
                returns_value = True
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                target = node.func.value
                method = node.func.attr
                if (
                    isinstance(target, ast.Name)
                    and target.id in param_names
                    and method in {"append", "extend", "insert", "pop", "remove"}
                ):
                    mutates = True
            if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store):
                # Unused — Subscript with Store ctx appears on AugAssign targets
                pass
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if (
                        isinstance(tgt, ast.Subscript)
                        and isinstance(tgt.value, ast.Name)
                        and tgt.value.id in param_names
                    ):
                        mutates = True

        if mutates and not returns_value:
            out.append(
                Misconception(
                    code="mutate-no-return",
                    title="Mutating an argument without returning it",
                    line=fn.lineno,
                    severity="info",
                    you_think=(
                        "If I modify the list inside the function, the caller sees the change — "
                        "but I should also return it to be safe."
                    ),
                    actually=(
                        "Python passes references, so `lst.append(x)` *does* mutate the caller's "
                        "list. But mixing 'mutate-in-place' and 'return-a-new-one' APIs is the "
                        "source of endless bugs — pick one style and be consistent."
                    ),
                    fix_hint=(
                        "Either document that the function mutates in place (name it `add_...` "
                        "and return `None`), or return a new list and don't mutate the input."
                    ),
                )
            )
    return out


def _summarize(items: list[Misconception]) -> str:
    if not items:
        return "No misconceptions detected."
    warnings = sum(1 for m in items if m.severity == "warning")
    infos = len(items) - warnings
    parts = []
    if warnings:
        parts.append(f"{warnings} likely misconception{'s' if warnings != 1 else ''}")
    if infos:
        parts.append(f"{infos} possible misconception{'s' if infos != 1 else ''}")
    return " · ".join(parts)


def detect_misconceptions(source: str) -> MisconceptionReport:
    """Scan Python source and return detected misconceptions.

    Never raises on syntax errors — returns an empty report. Syntax errors are
    a different teaching surface handled by the quality analyzer.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return MisconceptionReport(items=[], summary="Code doesn't parse — fix the syntax first.")

    items: list[Misconception] = []
    items.extend(_check_is_with_literal(tree))
    items.extend(_check_eq_none(tree))
    items.extend(_check_range_len(tree))
    items.extend(_check_concat_in_loop(tree))
    items.extend(_check_mutable_class_attr(tree))
    items.extend(_check_silent_except(tree))
    items.extend(_check_mutate_no_return(tree))

    severity_order = {"warning": 0, "info": 1}
    items.sort(key=lambda m: (m.line, severity_order[m.severity]))

    return MisconceptionReport(items=items, summary=_summarize(items))


def format_overlay(items: list[Misconception]) -> str:
    """Render detected misconceptions as a tutor-prompt overlay.

    Intent: give the streaming tutor a hidden note about *why* the student is
    likely stuck, so it addresses the mental model rather than the symptom. The
    tutor should NOT quote this overlay verbatim.
    """
    if not items:
        return ""
    lines = [
        "\n\n---\nStudent may be holding these misconceptions (internal — do not quote back, "
        "use them to shape your questions and explanations):",
    ]
    for m in items:
        lines.append(
            f"- [{m.code}] line {m.line}: likely thinks — \"{m.you_think}\" · reality — \"{m.actually}\""
        )
    return "\n".join(lines)
