"""Unit tests for portfolio autopsy parser (P2-12).

The async `run_autopsy` calls the LLM and is covered by route-level integration
tests; here we pin the pure parser that turns LLM JSON into a validated autopsy.
"""

from __future__ import annotations

import json

import pytest

from app.services.portfolio_autopsy_service import (
    _response_to_text,
    parse_autopsy,
)


def _good_payload() -> dict:
    return {
        "headline": "Ships a working RAG demo with missing production rails.",
        "overall_score": 62,
        "architecture": {
            "score": 3,
            "assessment": "Single-file Flask app with embeddings computed at request time.",
        },
        "failure_handling": {
            "score": 2,
            "assessment": "No retries on OpenAI calls; a 429 crashes the request.",
        },
        "observability": {
            "score": 2,
            "assessment": "print() for logging; no request IDs; no latency tracking.",
        },
        "scope_discipline": {
            "score": 4,
            "assessment": "Stayed focused on retrieval quality rather than chasing UI polish.",
        },
        "what_worked": [
            "Picked a tight domain so retrieval recall was measurable.",
            "Wrote a smoke-test notebook before the API.",
        ],
        "what_to_do_differently": [
            {
                "issue": "Embeddings recomputed per request instead of cached.",
                "why_it_matters": "Each query is a paid API round-trip; this will not scale.",
                "what_to_do_differently": "Precompute at ingest, store vectors in pgvector or Pinecone.",
            },
            {
                "issue": "No rate-limit handling on OpenAI calls.",
                "why_it_matters": "A 429 will propagate as a 500 to the user.",
                "what_to_do_differently": "Wrap calls in tenacity.retry with exponential backoff + jitter.",
            },
            {
                "issue": "Prints instead of structured logs.",
                "why_it_matters": "On prod, you cannot slice by user or request ID.",
                "what_to_do_differently": "Switch to structlog and emit request_id + latency on every call.",
            },
        ],
        "production_gaps": [
            "No auth on /query endpoint.",
            "No cost cap on embedding calls.",
        ],
        "next_project_seed": "Add an eval harness that scores retrieval hit-rate against a fixed 20-question set.",
    }


def test_parse_valid_payload() -> None:
    autopsy = parse_autopsy(json.dumps(_good_payload()))
    assert autopsy.overall_score == 62
    assert autopsy.architecture.score == 3
    assert len(autopsy.what_to_do_differently) == 3
    assert autopsy.production_gaps[0].startswith("No auth")


def test_parse_accepts_code_fenced_json() -> None:
    raw = "```json\n" + json.dumps(_good_payload()) + "\n```"
    autopsy = parse_autopsy(raw)
    assert autopsy.failure_handling.score == 2


def test_parse_accepts_plain_triple_backticks() -> None:
    raw = "```\n" + json.dumps(_good_payload()) + "\n```"
    autopsy = parse_autopsy(raw)
    assert autopsy.observability.score == 2


def test_parse_rejects_non_json() -> None:
    with pytest.raises(ValueError, match="invalid JSON"):
        parse_autopsy("this is not json at all")


def test_parse_rejects_non_object_root() -> None:
    with pytest.raises(ValueError, match="must be an object"):
        parse_autopsy(json.dumps([1, 2, 3]))


def test_parse_rejects_empty_headline() -> None:
    p = _good_payload()
    p["headline"] = "   "
    with pytest.raises(ValueError, match="headline"):
        parse_autopsy(json.dumps(p))


def test_parse_rejects_overall_score_out_of_range() -> None:
    p = _good_payload()
    p["overall_score"] = 120
    with pytest.raises(ValueError, match="overall_score"):
        parse_autopsy(json.dumps(p))


def test_parse_rejects_axis_score_out_of_range() -> None:
    p = _good_payload()
    p["architecture"]["score"] = 9
    with pytest.raises(ValueError, match="architecture.score"):
        parse_autopsy(json.dumps(p))


def test_parse_rejects_missing_axis() -> None:
    p = _good_payload()
    del p["failure_handling"]
    with pytest.raises(ValueError, match="failure_handling"):
        parse_autopsy(json.dumps(p))


def test_parse_rejects_findings_below_minimum() -> None:
    p = _good_payload()
    p["what_to_do_differently"] = p["what_to_do_differently"][:1]
    with pytest.raises(ValueError, match="2-5 entries"):
        parse_autopsy(json.dumps(p))


def test_parse_rejects_findings_above_maximum() -> None:
    p = _good_payload()
    dupes = p["what_to_do_differently"]
    p["what_to_do_differently"] = dupes + dupes + dupes  # 9 entries
    with pytest.raises(ValueError, match="2-5 entries"):
        parse_autopsy(json.dumps(p))


def test_parse_rejects_finding_missing_field() -> None:
    p = _good_payload()
    p["what_to_do_differently"][0]["why_it_matters"] = ""
    with pytest.raises(ValueError, match="why_it_matters"):
        parse_autopsy(json.dumps(p))


def test_parse_rejects_what_worked_with_non_string() -> None:
    p = _good_payload()
    p["what_worked"] = ["ok", 42]
    with pytest.raises(ValueError, match="what_worked"):
        parse_autopsy(json.dumps(p))


def test_parse_rejects_what_worked_empty() -> None:
    p = _good_payload()
    p["what_worked"] = []
    with pytest.raises(ValueError, match="what_worked"):
        parse_autopsy(json.dumps(p))


def test_parse_allows_empty_production_gaps() -> None:
    p = _good_payload()
    p["production_gaps"] = []
    autopsy = parse_autopsy(json.dumps(p))
    assert autopsy.production_gaps == []


def test_parse_rejects_empty_next_project_seed() -> None:
    p = _good_payload()
    p["next_project_seed"] = ""
    with pytest.raises(ValueError, match="next_project_seed"):
        parse_autopsy(json.dumps(p))


def test_parse_extracts_json_from_preamble() -> None:
    # LLMs with extended thinking sometimes prepend prose before the JSON.
    raw = "Here is my honest autopsy of your project:\n\n" + json.dumps(_good_payload())
    autopsy = parse_autopsy(raw)
    assert autopsy.overall_score == 62


def test_response_to_text_handles_plain_string() -> None:
    assert _response_to_text("hello") == "hello"


def test_response_to_text_strips_thinking_blocks() -> None:
    blocks = [
        {"type": "thinking", "thinking": "let me analyse this..."},
        {"type": "text", "text": '{"headline": "x"}'},
    ]
    assert _response_to_text(blocks) == '{"headline": "x"}'


def test_response_to_text_joins_multiple_text_blocks() -> None:
    blocks = [
        {"type": "text", "text": "part one"},
        {"type": "text", "text": "part two"},
    ]
    assert _response_to_text(blocks) == "part one\npart two"


def test_to_dict_roundtrip() -> None:
    autopsy = parse_autopsy(json.dumps(_good_payload()))
    d = autopsy.to_dict()
    assert d["overall_score"] == 62
    assert d["architecture"]["score"] == 3
    assert len(d["what_to_do_differently"]) == 3
    assert d["next_project_seed"].startswith("Add an eval harness")
