from __future__ import annotations

import ast
import json
import re
from typing import Any

# Matches a Python-repr'd list of content blocks like
#   [{'signature': '…', 'thinking': '…', 'type': 'thinking'}, {'text': 'Hello', 'type': 'text'}]
# We use this as a last-resort fallback when an agent has already stringified
# its Anthropic response before handing it to the orchestrator.
_LIST_OF_DICT_RE = re.compile(r"^\s*\[\s*\{.*?\}\s*\]\s*$", re.DOTALL)


def flatten_content(raw: Any) -> str:
    """Turn an Anthropic-style content payload into plain text.

    Handles:
      - plain ``str`` (passthrough)
      - ``list[dict]`` with ``{"type": "text", "text": "..."}`` / ``"thinking"`` /
        ``"tool_use"`` blocks
      - list of raw strings
      - a ``str(content)`` that was stringified upstream (Python repr of the
        list) — we re-parse with ``ast.literal_eval`` and re-flatten
    """
    if raw is None:
        return ""

    if isinstance(raw, list):
        parts: list[str] = []
        for block in raw:
            if isinstance(block, dict):
                # Skip extended-thinking + tool_use blocks — we only want text.
                btype = block.get("type")
                if btype == "text":
                    parts.append(str(block.get("text", "")))
                elif btype in (None, "message"):
                    text = block.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p)

    if isinstance(raw, str):
        # Last-ditch recovery: an agent ran ``str(response.content)`` on a
        # list-of-dicts content payload. Detect and re-parse.
        if _LIST_OF_DICT_RE.match(raw):
            try:
                parsed = ast.literal_eval(raw)
            except (ValueError, SyntaxError):
                return raw
            return flatten_content(parsed)
        return raw

    return str(raw)


def extract_first_balanced_json(raw: str) -> dict[str, Any] | None:
    """Return the first balanced JSON object found inside ``raw`` (or None).

    Tolerates code-fenced JSON (```json ... ```), leading prose, and trailing
    commentary. Returns ``None`` if nothing parses cleanly.
    """
    if not raw:
        return None

    text = raw.strip()

    # Strip code fences first — they are the most common wrapper.
    if "```json" in text:
        fenced = text.split("```json", 1)[1].split("```", 1)[0].strip()
        parsed = _try_json(fenced)
        if parsed is not None:
            return parsed
    if text.startswith("```"):
        fenced = text.split("```", 1)[1].split("```", 1)[0].strip()
        parsed = _try_json(fenced)
        if parsed is not None:
            return parsed

    # Balanced-braces scan: find the first '{' and track depth to its match.
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    parsed = _try_json(candidate)
                    if parsed is not None:
                        return parsed
                    break  # advance to next '{'
        start = text.find("{", start + 1)

    return None


def _try_json(text: str) -> dict[str, Any] | None:
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        return None
    return result if isinstance(result, dict) else None
