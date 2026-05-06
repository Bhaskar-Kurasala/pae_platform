"""D12 CP3 Stage 4.1(a)'.2 — pure-LLM diagnostic on career_coach.

Bypasses orchestrator wrapper, safety layer, dispatch, supervisor, DB
writes. Direct call to MiniMax via the build_llm path career_coach uses,
with the same system prompt + a representative user_block (empty-tool
results — the case that was hitting the timeout in production).

Captures three measurements:
  1. TTFT (time-to-first-token via streaming if available)
  2. Total elapsed wall-clock
  3. Output token counts split: thinking vs text

Discriminates Hypothesis 1 (thinking eats budget) vs 2 (orchestrator
overhead) vs 3 (provider throughput floor).

180s wall-clock cap. max_tokens=4096 (smart-tier default — let MiniMax
produce what it wants).
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

if "/app" not in sys.path:
    sys.path.insert(0, "/app")


async def main() -> int:
    print("=" * 70)
    print("D12 CP3 Stage 4.1(a)'.2 — career_coach pure-LLM diagnostic")
    print("=" * 70)

    from app.agents.career_coach_v2 import _build_user_block, _extract_text
    from app.agents.llm_factory import build_llm

    # Same system prompt + user_block shape as career_coach.run() with
    # empty tool results (matches what failed in Stage 4.1(a)).
    from pathlib import Path
    system_prompt = (
        Path("/app/app/agents/prompts/career_coach.md").read_text()
    )
    print(f"\nSystem prompt: {len(system_prompt)} chars")

    user_block = _build_user_block(
        question=(
            "I'm a backend engineer with 5 years experience. I want to "
            "move into senior GenAI engineering roles in the next 6 "
            "months. What should I focus on, and how should I structure "
            "my learning given I have about 8 hours per week?"
        ),
        progress={},
        contract={},
        capstone={},
        mastery={},
        target_role=None,
        timeline_weeks=None,
    )
    print(f"User block: {len(user_block)} chars")
    print(f"System+user total input chars: {len(system_prompt) + len(user_block)}")

    # smart tier = 4096 max_tokens by default. Let MiniMax produce freely.
    # IMPORTANT: build_llm sets _LLM_TIMEOUT_S=30s on the Anthropic SDK
    # client, which kills any single attempt that exceeds 30s and triggers
    # 3 retries (90-127s total). For this diagnostic we need the SDK to
    # NOT give up — patch the timeout up to 175s and disable retries so
    # we measure a single MiniMax round-trip cleanly.
    from langchain_anthropic import ChatAnthropic
    from pydantic import SecretStr
    from app.core.config import settings

    if settings.minimax_api_key:
        llm = ChatAnthropic(  # type: ignore[call-arg]
            model=settings.minimax_model,
            anthropic_api_key=SecretStr(settings.minimax_api_key),
            base_url=settings.minimax_api_base_url,
            max_tokens=4096,
            timeout=175.0,
            max_retries=0,
        )
    else:
        # Fall back to default factory if MiniMax not configured.
        llm = build_llm(max_tokens=4096, tier="smart")
    print(f"\nLLM model: {getattr(llm, 'model', '?')}")
    print(f"LLM base_url: {getattr(llm, 'anthropic_api_url', getattr(llm, 'base_url', '?'))}")
    print("LLM timeout: 175s, max_retries: 0 (diagnostic override)")

    print("\n→ Sending to MiniMax (180s cap, no orchestrator)...")
    request_start = time.monotonic()
    try:
        response = await asyncio.wait_for(
            llm.ainvoke(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_block},
                ]
            ),
            timeout=180.0,
        )
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - request_start
        print(f"\n!! HARD TIMEOUT at 180s wall-clock cap (elapsed={elapsed:.1f}s)")
        print("This is a Hypothesis 3 signal: MiniMax can't produce")
        print("career_coach output even with 180s budget. Surfacing.")
        return 2
    except Exception as exc:  # noqa: BLE001
        elapsed = time.monotonic() - request_start
        print(f"\n!! ainvoke RAISED at {elapsed:.1f}s: {type(exc).__name__}: {exc}")
        return 1

    elapsed_total = time.monotonic() - request_start

    print(f"\n=== Response received in {elapsed_total:.2f}s ===\n")

    # Capture content blocks
    content = getattr(response, "content", None)
    print(f"type(response.content) = {type(content).__name__}")

    thinking_text = ""
    text_text = ""
    block_count = 0
    if isinstance(content, list):
        block_count = len(content)
        for i, block in enumerate(content):
            if isinstance(block, dict):
                btype = block.get("type")
                if btype == "thinking":
                    thinking_text += block.get("thinking", "") or ""
                elif btype == "text":
                    text_text += block.get("text", "") or ""
                print(f"  Block {i}: type={btype!r} keys={list(block.keys())}")
    elif isinstance(content, str):
        text_text = content
        block_count = 1

    # Token counts from response_metadata
    rmeta = getattr(response, "response_metadata", {}) or {}
    umeta = getattr(response, "usage_metadata", {}) or {}
    print(f"\nresponse_metadata keys: {list(rmeta.keys()) if isinstance(rmeta, dict) else 'N/A'}")
    print(f"usage_metadata: {umeta}")

    # The Anthropic SDK 'usage' on response_metadata may break out thinking
    rm_usage = rmeta.get("usage", {}) if isinstance(rmeta, dict) else {}
    print(f"response_metadata.usage: {rm_usage}")

    input_tokens = (
        umeta.get("input_tokens", 0) if isinstance(umeta, dict) else 0
    )
    output_tokens = (
        umeta.get("output_tokens", 0) if isinstance(umeta, dict) else 0
    )
    total_tokens = (
        umeta.get("total_tokens", input_tokens + output_tokens)
        if isinstance(umeta, dict)
        else input_tokens + output_tokens
    )

    # Estimate thinking vs text token split from char counts (rough)
    # MiniMax doesn't break it out in usage, so we estimate by char ratio.
    thinking_chars = len(thinking_text)
    text_chars = len(text_text)
    total_chars = thinking_chars + text_chars
    if total_chars > 0:
        thinking_token_estimate = int(output_tokens * thinking_chars / total_chars)
        text_token_estimate = output_tokens - thinking_token_estimate
    else:
        thinking_token_estimate = 0
        text_token_estimate = output_tokens

    print()
    print("=" * 70)
    print("MEASUREMENTS")
    print("=" * 70)
    print(f"\nWall-clock elapsed:           {elapsed_total:.2f}s")
    print(f"Block count:                   {block_count}")
    print(f"Thinking content:              {thinking_chars:,} chars")
    print(f"Text content:                  {text_chars:,} chars")
    print(f"Input tokens:                  {input_tokens:,}")
    print(f"Output tokens:                 {output_tokens:,}")
    print(f"Total tokens:                  {total_tokens:,}")
    print(f"Thinking tokens (estimated):   {thinking_token_estimate:,}")
    print(f"Text tokens (estimated):       {text_token_estimate:,}")
    if output_tokens > 0:
        thinking_pct = 100 * thinking_token_estimate / output_tokens
        print(f"Thinking %% of output:          {thinking_pct:.1f}%")
    if elapsed_total > 0:
        throughput = output_tokens / elapsed_total
        print(f"Effective throughput:          {throughput:.1f} tok/sec (output)")
        text_throughput = text_token_estimate / elapsed_total
        print(f"Text-only throughput:          {text_throughput:.1f} tok/sec")

    # Cost
    from app.agents.llm_factory import estimate_cost_inr

    live_model = (
        rmeta.get("model") or rmeta.get("model_name")
        if isinstance(rmeta, dict)
        else None
    ) or "MiniMax-M2.7"
    cost_inr = estimate_cost_inr(
        model=live_model, input_tokens=input_tokens, output_tokens=output_tokens
    )
    print(f"\nEstimated cost: ₹{cost_inr:.4f}")

    print()
    print("=" * 70)
    print("HYPOTHESIS DISCRIMINATION")
    print("=" * 70)

    h1_signal = thinking_pct >= 50.0 if output_tokens > 0 else False
    h2_signal = (
        elapsed_total < 40.0
        and (text_token_estimate / max(elapsed_total, 0.1)) > 25.0
    )
    h3_signal = (
        elapsed_total > 60.0
        and (not h1_signal)
        and (output_tokens / max(elapsed_total, 0.1)) <= 30.0
    )

    print(f"\nHypothesis 1 (thinking >=50% AND elapsed >60s):  {h1_signal and elapsed_total > 60.0}")
    print(f"  thinking_pct={thinking_pct:.1f}%, elapsed={elapsed_total:.1f}s")
    print(f"\nHypothesis 2 (text throughput >>25 AND total <40s): {h2_signal}")
    print(f"  text_tok/sec={text_token_estimate / max(elapsed_total, 0.1):.1f}, elapsed={elapsed_total:.1f}s")
    print(f"\nHypothesis 3 (thinking <50% AND throughput ~25 tok/s AND total >60s): {h3_signal}")
    print(f"  thinking_pct={thinking_pct:.1f}%, throughput={output_tokens / max(elapsed_total, 0.1):.1f} tok/s, elapsed={elapsed_total:.1f}s")

    print()
    print("=" * 70)
    print("PARSER ATTEMPT")
    print("=" * 70)

    raw_text = _extract_text(response)
    print(f"\n_extract_text returned {len(raw_text)} chars")
    if raw_text:
        try:
            from app.agents.career_coach_v2 import _parse_output

            parsed = _parse_output(raw_text)
            print(f"_parse_output succeeded: {type(parsed).__name__}")
            print(f"  headline: {parsed.headline[:200]!r}")
        except Exception as exc:  # noqa: BLE001
            print(f"_parse_output RAISED: {type(exc).__name__}: {str(exc)[:300]}")

    print()
    print("=" * 70)
    print("END OF PURE-LLM DIAGNOSTIC")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
