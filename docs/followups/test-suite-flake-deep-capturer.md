# Test flake — `test_deep_capturer_fallback_synthesis`

**Status:** Open. Pre-existing flake characterized during D12 CP4.2.
**Created:** 2026-05-07 (D12 closure).

## What it is

`tests/test_agents/test_ws4_agents.py::test_deep_capturer_fallback_synthesis` fails under parallel test ordering (~50% of full-suite runs) but passes in isolation. Symptom: 40s+ duration on the failing run, suggesting the `app.agents.deep_capturer.settings` patch is leaking and a real LLM call fires instead of the fallback synthesis path.

## Why it's pre-existing (not D12)

The flake predates D12 CP3 work. It's in the WS4 test surface (deep_capturer is a legacy WS4 agent, not a D12 agent) and reproducibly passes when run alone. D12 verification reproduced the flake exactly once during the post-Phase-4 regression run (175/176 passing, deep_capturer flake), then re-ran in isolation and confirmed it passes.

## Likely cause

`app.agents.deep_capturer.settings` is a module-level reference to `app.core.config.settings`. The test does:

```python
with patch("app.agents.deep_capturer.settings") as mock_settings:
    mock_settings.anthropic_api_key = ""
```

If a parallel test imports `app.core.config.settings` directly and reads `anthropic_api_key` after this test starts (e.g., during a real LLM call in another test), the global `settings` object is shared state — even though the patch is module-scoped, the underlying `Settings` instance still has the real key. This is a known shared-mutable-state issue in Pydantic Settings; the fix would be to patch `anthropic_api_key` directly on the underlying object, not the module reference.

## Triage

D17 cleanup or earlier if it disrupts CI. The fix is small (~5 lines) but requires careful review because patching `settings.anthropic_api_key` directly affects all parallel tests reading from it. Safer approach: use a `monkeypatch.setattr("app.core.config.settings.anthropic_api_key", "")` with a per-test scope, ensuring teardown restores.

## How to reproduce

```bash
docker compose exec backend uv run pytest tests/test_agents/ -q
# Runs ~3 minutes; deep_capturer fails ~50% of the time.

docker compose exec backend uv run pytest tests/test_agents/test_ws4_agents.py::test_deep_capturer_fallback_synthesis -v
# Always passes in isolation.
```
