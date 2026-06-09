"""D12 CP3 Phase 2 — diagnose study_planner LLM output.

Replicates the LLM call study_planner_v2.run() makes (same prompt,
same user_block construction) but captures raw response BEFORE any
parsing. Lets us see exactly what MiniMax produced before deciding
how to fix Bug 10 ("No JSON object in LLM output: " — empty raw text).

DO NOT propose a fix from this script. Just capture data.

Run inside the backend container:
    uv run python scripts/d12_cp3_phase2_diagnose_llm.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

if "/app" not in sys.path:
    sys.path.insert(0, "/app")


async def main() -> int:
    print("=" * 70)
    print("D12 CP3 Phase 2 — study_planner LLM diagnostic")
    print("=" * 70)

    # Build the LLM exactly as the agent does.
    from app.agents.llm_factory import build_llm
    from app.agents.study_planner_v2 import _build_user_block, _load_prompt

    system_prompt = _load_prompt("study_planner")
    print(f"\nSystem prompt loaded — {len(system_prompt)} chars")
    print(f"System prompt first 200 chars: {system_prompt[:200]!r}")
    print(f"System prompt last 200 chars: {system_prompt[-200:]!r}")

    # User block — mirrors the agent's _build_user_block call shape.
    # Empty contract/srs/capstone/history dicts simulate "tools returned
    # nothing" (which is what the diagnostic call's fresh test user has).
    user_block = _build_user_block(
        message=(
            "Build me a 12-week study plan for transitioning to AI engineering, "
            "given that I know Python well but not ML."
        ),
        mode="weekly_plan",
        contract={},
        srs={},
        capstone={},
        history={},
        week_starting="2026-05-12",
        session_date=None,
        session_duration_minutes=None,
    )
    print(f"\nUser block — {len(user_block)} chars")
    print(f"User block first 400 chars:\n---\n{user_block[:400]}\n---")

    # ── Fire the LLM call ──────────────────────────────────────────
    llm = build_llm(max_tokens=1800, tier="smart")
    print(f"\nLLM built: {type(llm).__name__}, model={getattr(llm, 'model', '?')}")
    print(f"LLM base_url: {getattr(llm, 'anthropic_api_url', getattr(llm, 'base_url', '?'))}")

    print("\n→ Sending to MiniMax...")
    try:
        response = await llm.ainvoke(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_block},
            ]
        )
    except Exception as exc:  # noqa: BLE001
        print(f"\n!! ainvoke RAISED: {type(exc).__name__}: {exc}")
        return 1

    # ── Capture raw response BEFORE any parsing ───────────────────
    print("\n" + "=" * 70)
    print("RAW RESPONSE (verbatim, before any parsing)")
    print("=" * 70)

    print(f"\ntype(response) = {type(response).__name__}")
    print(f"\ndir(response) = {[a for a in dir(response) if not a.startswith('_')]}")

    # response.content
    content = getattr(response, "content", "<NO CONTENT ATTR>")
    print(f"\ntype(response.content) = {type(content).__name__}")
    print(f"\nrepr(response.content) =\n{content!r}")

    # If content is a list, dump each block's structure
    if isinstance(content, list):
        print(f"\n--- response.content has {len(content)} blocks ---")
        for i, block in enumerate(content):
            print(f"\nBlock {i}:")
            print(f"  type = {type(block).__name__}")
            print(f"  repr = {block!r}")
            if isinstance(block, dict):
                print(f"  keys = {list(block.keys())}")
                if "type" in block:
                    print(f"  block.type = {block['type']!r}")

    # response.response_metadata
    rmeta = getattr(response, "response_metadata", "<NO response_metadata ATTR>")
    print(f"\ntype(response.response_metadata) = {type(rmeta).__name__}")
    print(f"response.response_metadata =\n{json.dumps(rmeta, indent=2, default=str) if isinstance(rmeta, dict) else rmeta!r}")

    # response.usage_metadata
    umeta = getattr(response, "usage_metadata", "<NO usage_metadata ATTR>")
    print(f"\ntype(response.usage_metadata) = {type(umeta).__name__}")
    print(f"response.usage_metadata =\n{json.dumps(umeta, indent=2, default=str) if isinstance(umeta, dict) else umeta!r}")

    # ── Now run the parser and capture its behavior ───────────────
    print("\n" + "=" * 70)
    print("PARSER BEHAVIOR")
    print("=" * 70)

    from app.agents.study_planner_v2 import _extract_text, _parse_output

    raw_text = _extract_text(response)
    print(f"\n_extract_text(response) returned (type={type(raw_text).__name__}, len={len(raw_text) if isinstance(raw_text, str) else '?'}):")
    print(f"---\n{raw_text!r}\n---")

    if isinstance(raw_text, str) and len(raw_text) > 0:
        print(f"\nFirst 500 chars (visible):\n---\n{raw_text[:500]}\n---")

    print("\nAttempting _parse_output(raw_text)...")
    try:
        parsed = _parse_output(raw_text)
        print(f"\n_parse_output succeeded:")
        print(f"  type = {type(parsed).__name__}")
        print(f"  mode = {getattr(parsed, 'mode', '?')}")
        try:
            print(f"  model_dump = {json.dumps(parsed.model_dump(mode='json'), indent=2, default=str)[:600]}")
        except Exception:
            print(f"  model_dump failed; repr = {parsed!r}")
    except Exception as exc:  # noqa: BLE001
        print(f"\n_parse_output RAISED: {type(exc).__name__}: {exc}")

    # ── Cost estimate ─────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("COST ESTIMATE")
    print("=" * 70)

    if isinstance(umeta, dict):
        in_tok = int(umeta.get("input_tokens", 0) or 0)
        out_tok = int(umeta.get("output_tokens", 0) or 0)
        from app.agents.llm_factory import estimate_cost_inr

        live_model = None
        if isinstance(rmeta, dict):
            live_model = rmeta.get("model") or rmeta.get("model_name")
        live_model = live_model or "MiniMax-M2.7"

        cost = estimate_cost_inr(
            model=live_model, input_tokens=in_tok, output_tokens=out_tok
        )
        print(f"  model: {live_model}")
        print(f"  input_tokens: {in_tok}")
        print(f"  output_tokens: {out_tok}")
        print(f"  estimated cost: ₹{cost:.4f}")
    else:
        print("  (no usage_metadata available)")

    print("\n" + "=" * 70)
    print("END OF DIAGNOSTIC")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
