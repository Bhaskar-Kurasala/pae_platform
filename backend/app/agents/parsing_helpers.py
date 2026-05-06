"""Shared parsing helpers for D12 v2 agents (and forward).

Currently exports `truncate_to_schema` — server-side enforcement of
Pydantic string max_length constraints before model_validate runs.

Background — D12 CP3 Phase 4 Bug 17:
  Prompt-level constraint emphasis (e.g. "HARD LIMIT: 200 characters")
  proved unreliable under MiniMax. Three iterations on resume_reviewer
  surfaced different max_length overshoots even with explicit framing.
  The principle adopted in Bug 17's architectural fix: schema is
  canonical; LLM produces best-effort; server enforces.

  This helper makes max_length overshoots a recoverable parse-time fix
  (truncate, log, validate) instead of a validation error that surfaces
  as a 5xx to the user.

Future scope (out of D12, registered in
docs/followups/schema-aware-server-side-validation.md):
  • Literal allowlist coercion (closest-match snap)
  • Required-field synthesis for absent string fields
  • Type coercion (int → str, str → bool) where safe
"""

from __future__ import annotations

import types
from typing import Any, Union, get_args, get_origin

import structlog
from pydantic import BaseModel
from pydantic.fields import FieldInfo

log = structlog.get_logger().bind(layer="parsing_helpers")


def _is_union(origin: Any) -> bool:
    """True for both typing.Union[T, None] and PEP 604 `T | None` shapes.

    In Python 3.10+ the `T | None` syntax produces a types.UnionType
    rather than typing.Union; both are valid Union-shaped annotations
    and we need to handle both. Pydantic field annotations in
    AgentCapability use the `T | None` form, hence this guard.
    """
    return origin is Union or origin is types.UnionType


def truncate_to_schema(
    data: dict[str, Any],
    model: type[BaseModel],
    *,
    _path: str = "",
) -> dict[str, Any]:
    """Truncate string fields in `data` to their Pydantic max_length.

    Returns a NEW dict; does not mutate `data`. Recurses into nested
    BaseModel fields and lists of BaseModels. For Union types, picks
    the first member that is a BaseModel subclass (heuristic; logs a
    warning and skips when ambiguous).

    Fields without max_length constraints are left unchanged. Fields
    that are not strings are unchanged. None values are preserved.

    Each truncation emits a single debug log line with the field path
    and the lengths involved.

    Args:
      data: parsed JSON dict produced by the LLM.
      model: the Pydantic BaseModel subclass we will validate against.
      _path: internal — used to produce field paths like
        "plan.weekly_focus_areas.0.theme" in debug logs. Callers
        should leave this empty.

    Returns:
      A new dict with all string overshoots truncated.
    """
    if not isinstance(data, dict):
        # Defensive — if a caller passes something non-dict, we don't
        # crash; return as-is and let Pydantic surface the type error.
        return data

    out: dict[str, Any] = {}
    fields = model.model_fields

    for key, value in data.items():
        if key not in fields:
            # Extra key (will be rejected by extra="forbid" anyway, or
            # passed through if "ignore"). Don't transform it.
            out[key] = value
            continue

        field_info = fields[key]
        out[key] = _process_field(value, field_info, f"{_path}{key}")

    return out


def _process_field(
    value: Any,
    field_info: FieldInfo,
    path: str,
) -> Any:
    """Apply max_length truncation + recursion to one field's value."""
    if value is None:
        return value

    annotation = field_info.annotation
    origin = get_origin(annotation)
    args = get_args(annotation)

    # ── Strings: enforce max_length if present ────────────────────
    if isinstance(value, str):
        max_length = _max_length_for_field(field_info)
        if max_length is not None and len(value) > max_length:
            log.debug(
                "truncate_to_schema.applied",
                field=path,
                from_length=len(value),
                to=max_length,
            )
            return value[:max_length]
        return value

    # ── Lists: recurse into elements if element type is a BaseModel ──
    if isinstance(value, list):
        element_type = _list_element_type(annotation, origin, args)
        if element_type is not None and isinstance(element_type, type) and issubclass(element_type, BaseModel):
            return [
                truncate_to_schema(item, element_type, _path=f"{path}.{i}.")
                if isinstance(item, dict)
                else item
                for i, item in enumerate(value)
            ]
        return value

    # ── Dicts: recurse if the field's type is a BaseModel subclass ──
    if isinstance(value, dict):
        nested_model = _nested_model_class(annotation, origin, args)
        if nested_model is not None:
            return truncate_to_schema(value, nested_model, _path=f"{path}.")
        # Untyped dict (e.g. dict[str, Any]) — don't recurse.
        return value

    # ── Other primitives — pass through unchanged ─────────────────
    return value


def _max_length_for_field(field_info: FieldInfo) -> int | None:
    """Pull the max_length constraint off a Pydantic FieldInfo, if any.

    In Pydantic v2 the constraint lives in field_info.metadata as a
    pydantic_core._pydantic_core.MaxLen instance. We probe defensively
    for the attribute since metadata shape can change across minor
    Pydantic versions.
    """
    metadata = getattr(field_info, "metadata", None)
    if not metadata:
        return None
    for entry in metadata:
        # MaxLen has a `max_length` attribute in Pydantic v2.x.
        max_len = getattr(entry, "max_length", None)
        if isinstance(max_len, int):
            return max_len
    return None


def _list_element_type(
    annotation: Any, origin: Any, args: tuple[Any, ...]
) -> Any:
    """Return the element type for a list[T] / list[Optional[T]] annotation.

    Returns None if not a list, or if element type isn't introspectable.
    """
    if origin is list and args:
        elem = args[0]
        # Unwrap Optional[T] (i.e. Union[T, None] or `T | None`).
        if _is_union(get_origin(elem)):
            non_none = [a for a in get_args(elem) if a is not type(None)]
            if len(non_none) == 1:
                return non_none[0]
        return elem
    return None


def _nested_model_class(
    annotation: Any, origin: Any, args: tuple[Any, ...]
) -> type[BaseModel] | None:
    """If `annotation` resolves (possibly through Optional/Union) to a
    single BaseModel subclass, return it. Otherwise None.

    Logs a warning when a Union has multiple BaseModel members and
    can't be disambiguated by shape alone — those fields are skipped.
    """
    # Direct BaseModel subclass.
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation

    # Optional[Model] / Union[Model, None] / `Model | None`.
    if _is_union(origin):
        non_none = [a for a in args if a is not type(None)]
        model_subs = [
            a for a in non_none
            if isinstance(a, type) and issubclass(a, BaseModel)
        ]
        if len(model_subs) == 1:
            return model_subs[0]
        if len(model_subs) > 1:
            log.warning(
                "truncate_to_schema.union_ambiguous",
                members=[m.__name__ for m in model_subs],
                note="multiple BaseModel members in Union; skipping recursion",
            )
            return None

    return None


__all__ = ["truncate_to_schema"]
