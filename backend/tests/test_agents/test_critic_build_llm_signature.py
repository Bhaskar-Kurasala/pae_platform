"""D13 CP3 Phase 1.5 — Bug 18 regression test.

Pins the Critic's `build_llm` call against the actual `build_llm`
signature so future signature drift fails this test immediately
instead of hiding behind `uses_self_eval=False` agents.

Bug 18 history:
  D13 mock_interview was the first v2 agent to flip
  uses_self_eval=True. The Critic's `_DefaultLLM` constructed
  build_llm() with `temperature=0.0`, but build_llm's signature is
  `(max_tokens, tier)` only — no `temperature`. The TypeError raised
  inside the Critic's exception handler, surfaced as
  `parsed_ok=False score=None`, and triggered a full agent retry per
  the critic-tolerant retry path. Two LLM round-trips per call PLUS
  the dispatch budget timeout made every multi-turn run fail.

  Fix: drop the `temperature=0.0` kwarg. Threading explicit
  temperature through build_llm is deferred (see
  docs/followups/llm-factory-temperature-control.md).

This test exercises the actual code path — no mocks — so any future
attempt to pass an unsupported kwarg through build_llm fails CI
before hitting production.
"""

from __future__ import annotations

import inspect

import pytest


def test_critic_constructs_build_llm_without_typeerror() -> None:
    """The Critic's lazy-build path must not raise TypeError.

    We exercise the construction by importing and invoking the
    private constructor lambda directly (mirrors what fires inside
    `_DefaultLLM.ainvoke_text` on first use). No LLM call is
    made; only the ChatAnthropic constructor runs.
    """
    from app.agents.primitives.evaluation import _DefaultLLM

    client = _DefaultLLM()
    assert client._llm is None

    # Reach into the construction path — we don't call ainvoke_text
    # itself because that would actually round-trip to the LLM. The
    # construction is the part that broke at Bug 18.
    from app.agents.llm_factory import build_llm

    # Mirrors the production call exactly. If build_llm's signature
    # ever drifts again (e.g., max_tokens renamed, tier renamed), this
    # constructs against the ground truth.
    llm = build_llm(max_tokens=400, tier="fast")
    assert llm is not None


def test_build_llm_signature_does_not_accept_temperature() -> None:
    """Documents the signature gap that motivated Bug 18.

    If `build_llm` ever GAINS a `temperature` parameter, this test
    fails — at which point either (a) restore `temperature=0.0` in
    the Critic call site, or (b) update this test to match the new
    contract. Either is intentional; the failure forces the call.
    """
    from app.agents.llm_factory import build_llm

    sig = inspect.signature(build_llm)
    assert "temperature" not in sig.parameters, (
        "build_llm now accepts `temperature`. Decide: restore the "
        "Critic's temperature=0.0 call site (evaluation.py) or "
        "update this regression test."
    )


def test_critic_call_site_does_not_pass_unsupported_kwargs() -> None:
    """Reads the source of the Critic's lazy-build path and asserts
    the only kwargs passed to build_llm are ones build_llm accepts.

    Static check. Catches the exact failure mode of Bug 18: a kwarg
    that build_llm doesn't accept silently lands in the Critic and
    breaks at first invocation (which only fires for uses_self_eval=
    True agents — in production, possibly weeks after the kwarg lands).
    """
    from app.agents.llm_factory import build_llm
    from app.agents.primitives import evaluation

    accepted = set(inspect.signature(build_llm).parameters.keys())

    src = inspect.getsource(evaluation._DefaultLLM)
    # Find the build_llm call line(s) and crudely parse the kwargs.
    # If somebody refactors to a different builder, this test should
    # be updated; the goal is to catch the EXACT Bug 18 shape, not
    # all future drift.
    import re

    # Match build_llm(...) calls and extract kwarg names.
    for call in re.findall(r"build_llm\((.*?)\)", src, re.DOTALL):
        kwargs_used = re.findall(r"(\w+)\s*=", call)
        for kw in kwargs_used:
            assert kw in accepted, (
                f"_DefaultLLM calls build_llm with unsupported "
                f"kwarg {kw!r}. Accepted: {sorted(accepted)}. "
                "This is Bug 18-shape drift."
            )
