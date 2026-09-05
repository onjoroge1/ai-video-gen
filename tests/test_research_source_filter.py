"""Exclude disallowed evidence without weakening retained-claim or spending gates."""
import copy
import json
from pathlib import Path

import pytest

import claim_verify
import explainer_pipeline as pipeline
from durable_execution import activate
from longform_research import (
    claim_context_for_prompt,
    filter_disallowed_source_claims,
    validate_claim_joins,
    validate_research_dossier,
)
from test_durable_anthropic_response import Provider, payload
from test_durable_execution_phase6 import MemoryBlob, MemoryStore, runtime
from test_longform_research_phase2 import SOURCE, QUOTE, _dossier, _script


WEAK_URL = "https://en.wikipedia.org/wiki/Cobra_effect"
WEAK_QUOTE = "A weak-source statement that must never license narration."


def _mixed_dossier(weak_url=WEAK_URL):
    dossier = _dossier()
    weak = copy.deepcopy(dossier["claims"][0])
    weak.update(claim_id="c02", claim=WEAK_QUOTE, source_url=weak_url,
                support_quote=WEAK_QUOTE, source_type="authoritative_secondary")
    dossier["claims"].append(weak)
    dossier["citation_urls"].append(weak_url)
    dossier["citation_records"].append({"url": weak_url, "cited_text": WEAK_QUOTE})
    return dossier


def _codes(report):
    return {issue["code"] for issue in report["errors"]}


def test_mixed_dossier_keeps_original_valid_claim_and_audits_excluded_evidence():
    original = _mixed_dossier()
    before = copy.deepcopy(original)

    filtered = filter_disallowed_source_claims(original)

    assert original == before, "Filtering must preserve the input evidence for diagnosis"
    assert filtered is not original
    assert filtered["claims"] == [before["claims"][0]]
    assert filtered["excluded_claims"] == [{
        "claim": before["claims"][1], "reason": "weak_source_domain"}]
    assert validate_research_dossier(filtered)["passed"] is True
    context = claim_context_for_prompt(filtered)
    assert [claim["claim_id"] for claim in context] == ["c01"]
    assert WEAK_QUOTE not in json.dumps(context)
    assert WEAK_URL not in json.dumps(context)


@pytest.mark.parametrize("url", [
    "https://wikipedia.org/article",
    "https://en.m.wikipedia.org/article",
    "https://www.medium.com/article",
    "https://author.blogspot.com/article",
    "https://www.reddit.com.:443/r/science/example",
    "https://EN.WIKIPEDIA.ORG:443/article",
])
def test_domain_variants_remain_disallowed_in_filter_and_strict_validator(url):
    dossier = _mixed_dossier(url)
    assert "weak_source_domain" in _codes(validate_research_dossier(dossier))
    filtered = filter_disallowed_source_claims(dossier)
    assert [claim["claim_id"] for claim in filtered["claims"]] == ["c01"]
    assert filtered["excluded_claims"][0]["claim"]["source_url"] == url


def test_weak_name_inside_different_hostname_is_not_a_denylist_match():
    url = "https://wikipedia.org.evidence.example.edu/article"
    dossier = _mixed_dossier(url)
    filtered = filter_disallowed_source_claims(dossier)
    assert len(filtered["claims"]) == 2
    assert validate_research_dossier(filtered)["passed"] is True


def test_all_weak_evidence_still_fails_existing_missing_claims_gate():
    dossier = _mixed_dossier()
    dossier["claims"] = dossier["claims"][1:]
    filtered = filter_disallowed_source_claims(dossier)
    report = validate_research_dossier(filtered)
    assert filtered["claims"] == []
    assert report["passed"] is False
    assert "missing_claims" in _codes(report)


def test_script_cannot_reference_a_quarantined_claim():
    filtered = filter_disallowed_source_claims(_mixed_dossier())
    script = _script(WEAK_QUOTE)
    script["scenes"][0]["claim_refs"][0]["claim_id"] = "c02"
    report = validate_claim_joins(script, filtered)
    assert report["passed"] is False
    assert "unknown_claim" in _codes(report)


@pytest.mark.parametrize("defect", ["duplicate", "missing_id", "invalid_claim"])
def test_structure_failure_cannot_be_hidden_by_excluding_a_weak_claim(defect):
    dossier = _mixed_dossier()
    if defect == "duplicate":
        dossier["claims"][1]["claim_id"] = "c01"
    elif defect == "missing_id":
        dossier["claims"][1].pop("claim_id")
    else:
        dossier["claims"].append("not a claim object")
    with pytest.raises(ValueError):
        filter_disallowed_source_claims(dossier)


@pytest.mark.parametrize("change,error", [
    ({"claim": "This happens globally everywhere.", "geographic_scope": "local"},
     "scope_inflation"),
    ({"support_quote": "This quotation was never in the source."},
     "unverified_support_quote"),
    ({"source_url": "https://invented.example.edu/no-provider-result"},
     "unverified_source"),
])
def test_retained_claims_still_fail_all_existing_factual_gates(change, error):
    dossier = _mixed_dossier()
    dossier["claims"][0].update(change)
    filtered = filter_disallowed_source_claims(dossier)
    report = validate_research_dossier(filtered)
    assert len(filtered["claims"]) == 1
    assert report["passed"] is False
    assert error in _codes(report)


def test_page_verifier_cannot_make_a_model_only_url_provider_observed(monkeypatch):
    dossier = _dossier(source_url="https://invented.example.edu/no-provider-result")
    provider_urls = copy.deepcopy(dossier["citation_urls"])
    monkeypatch.setattr(claim_verify, "fetch_page_text", lambda url, **kw: QUOTE)

    pipeline._verify_claims_against_sources(dossier)

    assert dossier["citation_urls"] == provider_urls
    report = validate_research_dossier(dossier)
    assert report["passed"] is False
    assert "unverified_source" in _codes(report)


def test_weak_source_gate_replays_paid_response_and_filters_before_page_verification(
        tmp_path, monkeypatch):
    dossier = _mixed_dossier()
    raw = payload(text=json.dumps(dossier), output_tokens=300)
    raw["content"][0]["citations"] = [{
        "type": "web_search_result_location", "url": record["url"],
        "cited_text": record["cited_text"],
    } for record in dossier["citation_records"]]
    provider = Provider(raw)
    store, blob = MemoryStore(cap=5), MemoryBlob(tmp_path / "blob")
    worker = runtime(tmp_path, store, blob, "old-worker")
    monkeypatch.setattr(pipeline, "_anthropic_native", lambda: worker.wrap_anthropic(provider))
    monkeypatch.setattr(pipeline, "_claude", lambda: pytest.fail("research used text adapter"))
    monkeypatch.setattr(pipeline, "_parse_script_json",
                        lambda *a, **kw: pytest.fail("research purchased JSON repair"))
    fetched = []

    def fetch_page(url, **kwargs):
        fetched.append(url)
        return QUOTE if url == SOURCE else WEAK_QUOTE

    monkeypatch.setattr(claim_verify, "fetch_page_text", fetch_page)
    active_filter = pipeline.filter_disallowed_source_claims
    monkeypatch.setattr(pipeline, "filter_disallowed_source_claims", lambda dossier: dossier)
    with pytest.raises(ValueError, match="weak_source_domain"):
        pipeline.generate_research_dossier("Why did the gauge move?")
    paid = store.job["spent_cost_usd"]
    assert paid > 0
    assert len(provider.calls) == 1
    assert WEAK_URL in fetched

    fetched.clear()
    monkeypatch.setattr(pipeline, "filter_disallowed_source_claims", active_filter)
    worker = runtime(tmp_path, store, blob, "repaired-worker")
    recovered = pipeline.generate_research_dossier("Why did the gauge move?")

    assert recovered["validation"]["passed"] is True
    assert [claim["claim_id"] for claim in recovered["claims"]] == ["c01"]
    assert recovered["claims"][0]["support_quote"] == QUOTE
    assert recovered["excluded_claims"][0]["claim"] == dossier["claims"][1]
    assert fetched == [SOURCE], "Disallowed sources should not be retrieved on recovery"
    assert len(provider.calls) == 1
    assert store.job["spent_cost_usd"] == paid
    assert store.job["reserved_cost_usd"] == 0


def test_all_weak_provider_dossier_records_failed_audit_before_scripting(tmp_path, monkeypatch):
    dossier = _mixed_dossier()
    dossier["claims"] = dossier["claims"][1:]
    dossier["citation_urls"] = [WEAK_URL]
    dossier["citation_records"] = [{"url": WEAK_URL, "cited_text": WEAK_QUOTE}]
    original_claim = copy.deepcopy(dossier["claims"][0])
    raw = payload(text=json.dumps(dossier), output_tokens=200)
    raw["usage"]["server_tool_use"]["web_search_requests"] = 1
    raw["content"][0]["citations"] = [{
        "type": "web_search_result_location", "url": WEAK_URL,
        "cited_text": WEAK_QUOTE,
    }]
    provider = Provider(raw)
    store, blob = MemoryStore(cap=5), MemoryBlob(tmp_path / "blob")
    worker = runtime(tmp_path, store, blob, "audit-worker")
    monkeypatch.setattr(pipeline, "_anthropic_native", lambda: worker.wrap_anthropic(provider))
    monkeypatch.setattr(claim_verify, "fetch_page_text",
                        lambda *a, **kw: pytest.fail("Excluded evidence was fetched"))

    with activate(worker), pytest.raises(ValueError, match="no usable claims") as failure:
        pipeline.generate_research_dossier("Why did the gauge move?")

    assert "search-budget" not in str(failure.value)
    assert "scripting has not started" in str(failure.value)
    audit = json.loads((Path(worker.output_dir) / "research_dossier.json").read_text())
    assert audit["claims"] == []
    assert audit["excluded_claims"] == [{
        "claim": original_claim, "reason": "weak_source_domain"}]
    assert audit["validation"]["passed"] is False
    assert "missing_claims" in _codes(audit["validation"])
    assert len(provider.calls) == 1
