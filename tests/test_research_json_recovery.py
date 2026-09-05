"""Recover complete provider ledgers without synthesizing or weakening evidence."""
import json

import pytest

import explainer_pipeline as pipeline
from longform_research import parse_research_dossier_text
from test_durable_anthropic_response import Provider
from test_durable_execution_phase6 import MemoryBlob, MemoryStore, runtime
from test_longform_research_phase2 import _dossier
from test_research_continuation import _completed, _mock_sources, _paused


@pytest.mark.parametrize("before,after", [
    ("", ""),
    ("```json\n", "\n```"),
    ("I searched for evidence.\n```json\n", "\n```\nSources are listed above."),
    ('Search input: {"query":"cobra bounty"}\n', "\nEnd of research."),
    ("Search template {query}, sources [1, 2].\n", ""),
    ("\ufeff", "\nA caution about the anecdote follows."),
])
def test_extracts_complete_dossier_and_preserves_evidence(before, after):
    dossier = _dossier(support_quote='A quote with {braces}, [arrays], "quotes" and \\ escapes.')
    assert parse_research_dossier_text([before, json.dumps(dossier), after]) == dossier


def test_text_block_split_inside_quote_does_not_insert_characters():
    dossier = _dossier()
    encoded = json.dumps(dossier)
    split = encoded.index("regional gauge") + 8
    assert parse_research_dossier_text([encoded[:split], encoded[split:]]) == dossier


def test_trailing_commas_are_removed_only_outside_evidence_strings():
    raw = '{"claims": [{"support_quote": "literal ,} and ,] stay unchanged",},],}'
    assert parse_research_dossier_text([raw]) == {
        "claims": [{"support_quote": "literal ,} and ,] stay unchanged"}]}


@pytest.mark.parametrize("raw", [
    '{"claims":[',
    '{"outer": {"claims": []}',
    '{"claims": [,]}',
    '{"claims": [],,}',
    '{"claims": [], "claims": [{"claim": "invented"}]}',
    '{"claims": [], "confidence": NaN}',
    '{"claims": []} {"claims": []}',
    '{"claims": []}\n{"claims": [',
    '[{"claims": []}]',
    '{"claims": [}',
    'No evidence was found.',
])
def test_rejects_incomplete_ambiguous_or_invalid_json(raw):
    with pytest.raises(ValueError):
        parse_research_dossier_text([raw])


def test_legacy_parser_failure_replays_saved_provider_response_without_charge(tmp_path, monkeypatch):
    _mock_sources(monkeypatch)
    store, blob = MemoryStore(cap=5), MemoryBlob(tmp_path / "blob")
    text = 'Search input: {"query":"gauge"}\n```json\n' + _completed()["content"][0]["text"] + '\n```\nDone.'
    provider = Provider(_paused(), _completed(text))
    worker = runtime(tmp_path, store, blob, "old-worker")
    monkeypatch.setattr(pipeline, "_anthropic_native", lambda: worker.wrap_anthropic(provider))
    current_parser = pipeline.parse_research_dossier_text

    def legacy_parser(blocks):
        raw = "\n".join(blocks)
        return json.loads(raw[raw.find("{"):])

    monkeypatch.setattr(pipeline, "parse_research_dossier_text", legacy_parser)
    with pytest.raises(json.JSONDecodeError):
        pipeline.generate_research_dossier("Why did the gauge move?")
    paid = store.job["spent_cost_usd"]
    assert len(provider.calls) == 2

    monkeypatch.setattr(pipeline, "parse_research_dossier_text", current_parser)
    worker = runtime(tmp_path, store, blob, "repaired-worker")
    recovered = pipeline.generate_research_dossier("Why did the gauge move?")
    assert recovered["validation"]["passed"] is True
    assert recovered["claims"][0]["support_quote"] == _dossier()["claims"][0]["support_quote"]
    assert len(provider.calls) == 2
    assert store.job["spent_cost_usd"] == paid
    assert store.job["reserved_cost_usd"] == 0
