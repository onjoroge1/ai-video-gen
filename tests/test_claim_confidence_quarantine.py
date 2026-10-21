"""One claim with an off-schema confidence must cost that claim, not the dossier.

Measured on the Chernobyl research (2026-10-15): 43 otherwise usable claims and $1.02 of research
were refused for `invalid_confidencex1`. A plain variant of a level is normalized; a value that
names no level is quarantined like a self-contradictory row. The validator itself is unchanged.
"""
import copy
import json
from pathlib import Path

import pytest

import claim_verify
import explainer_pipeline as pipeline
from durable_execution import activate
from longform_research import (
    normalize_confidence,
    quarantine_invalid_confidence_claims,
    validate_claim_joins,
    validate_research_dossier,
)
from test_durable_anthropic_response import Provider, payload
from test_durable_execution_phase6 import MemoryBlob, MemoryStore, runtime
from test_longform_research_phase2 import QUOTE, SOURCE, _dossier, _script


QUESTION = "Why did the gauge move?"
QUOTE_2 = "The coastal gauge recorded a second rise of one meter in the following decade."
QUOTE_3 = "Some researchers suggest the gauge may keep rising for another decade."


def _three_claim_dossier(second="High ", third="very likely"):
    """c01 is valid; c02 and c03 carry the confidence values under test."""
    dossier = _dossier()
    base = dossier["claims"][0]
    for claim_id, quote, confidence in (("c02", QUOTE_2, second), ("c03", QUOTE_3, third)):
        claim = copy.deepcopy(base)
        claim.update(claim_id=claim_id, claim=quote, support_quote=quote, confidence=confidence)
        dossier["claims"].append(claim)
        dossier["citation_records"].append({"url": SOURCE, "cited_text": quote})
    return dossier


def _codes(report):
    return [issue["code"] for issue in report["errors"]]


@pytest.mark.parametrize("raw,level", [
    ("high", "high"), ("High ", "high"), ("HIGH", "high"), ("  medium\n", "medium"),
    ("Medium-High", "medium"), ("medium/high", "medium"), ("medium high", "medium"),
    ("moderate", "medium"), ("low", "speculative"), ("Speculative ", "speculative"),
    ("high-speculative", "speculative"), ("low_medium", "speculative"),
])
def test_plain_variants_of_a_level_normalize_and_compounds_round_down(raw, level):
    assert normalize_confidence(raw) == level


@pytest.mark.parametrize("raw", [
    "very likely", "likely", "probable", "very high", "medium to high", "not high", "high.",
    "", "   ", None, 0.9, True, ["high"],
])
def test_a_value_that_names_no_level_is_not_guessed(raw):
    assert normalize_confidence(raw) == ""


def test_one_variant_is_normalized_one_unknown_is_quarantined_and_the_dossier_passes():
    original = _three_claim_dossier()
    before = copy.deepcopy(original)
    assert _codes(validate_research_dossier(original)) == [
        "invalid_confidence", "invalid_confidence"], "precondition: both rows fail today"

    filtered = quarantine_invalid_confidence_claims(original)

    assert original == before, "Filtering must preserve the input evidence for diagnosis"
    assert [c["claim_id"] for c in filtered["claims"]] == ["c01", "c02"]
    assert filtered["claims"][0] == before["claims"][0]
    assert filtered["claims"][1]["confidence"] == "high"
    assert filtered["excluded_claims"] == [
        {"claim": before["claims"][2], "reason": "invalid_confidence"}]
    assert filtered["confidence_filter"] == {
        "version": 1, "candidate_count": 3, "retained_count": 2, "excluded_count": 1,
        "normalized": [{"claim_id": "c02", "from": "High ", "to": "high"}]}
    assert validate_research_dossier(filtered)["passed"] is True


def test_an_accepted_value_is_left_byte_identical():
    """A ledger that passed before keeps the same claims, evidence hash and handoff key."""
    dossier = _dossier(confidence="medium ")
    filtered = quarantine_invalid_confidence_claims(dossier)
    assert filtered["claims"] == dossier["claims"]
    assert filtered["confidence_filter"]["normalized"] == []


def test_the_validator_still_rejects_every_off_schema_value():
    """Normalizing is the filter's job; the gate keeps its exact vocabulary."""
    for raw in ("High ", "very likely", "Medium-High", None):
        report = validate_research_dossier(_dossier(confidence=raw))
        assert report["passed"] is False
        assert _codes(report) == ["invalid_confidence"]


def test_a_normalized_speculative_claim_still_requires_hedged_narration():
    """Why the value is rewritten rather than accepted loosely: the join check compares exactly."""
    narration = "A regional gauge rose two meters over ten years."
    filtered = quarantine_invalid_confidence_claims(_dossier(confidence="Speculative-Medium"))
    assert filtered["claims"][0]["confidence"] == "speculative"
    report = validate_claim_joins(_script(narration), filtered)
    assert "unhedged_speculation" in _codes(report)


def test_other_per_claim_gates_are_unchanged_on_retained_claims():
    dossier = _three_claim_dossier()
    dossier["claims"][1]["support_quote"] = "This quotation was never in the source."
    report = validate_research_dossier(quarantine_invalid_confidence_claims(dossier))
    assert report["passed"] is False
    assert _codes(report) == ["unverified_support_quote"]


def _replay(tmp_path, monkeypatch, dossier, worker_name):
    raw = payload(text=json.dumps(dossier), output_tokens=300)
    raw["content"][0]["citations"] = [{
        "type": "web_search_result_location", "url": record["url"],
        "cited_text": record["cited_text"],
    } for record in dossier["citation_records"]]
    provider = Provider(raw)
    store, blob = MemoryStore(cap=5), MemoryBlob(tmp_path / "blob")
    worker = runtime(tmp_path, store, blob, worker_name)
    monkeypatch.setenv("RESEARCH_CACHE", "0")
    monkeypatch.setenv("RESEARCH_CACHE_WRITE", "0")
    monkeypatch.setattr(pipeline, "_anthropic_native", lambda: worker.wrap_anthropic(provider))
    monkeypatch.setattr(pipeline, "_claude", lambda: pytest.fail("research used text adapter"))
    monkeypatch.setattr(claim_verify, "fetch_page_text",
                        lambda url, **kw: " ".join([QUOTE, QUOTE_2, QUOTE_3]))
    return provider, worker


def test_generate_research_dossier_drops_one_bad_row_and_passes(tmp_path, monkeypatch):
    dossier = _three_claim_dossier()
    provider, worker = _replay(tmp_path, monkeypatch, dossier, "confidence-worker")
    logs = []

    with activate(worker):
        result = pipeline.generate_research_dossier(QUESTION, log=logs.append)

    assert result["validation"]["passed"] is True
    assert [c["claim_id"] for c in result["claims"]] == ["c01", "c02"]
    assert result["claims"][1]["confidence"] == "high"
    excluded = [e for e in result["excluded_claims"] if e["reason"] == "invalid_confidence"]
    assert [e["claim"]["claim_id"] for e in excluded] == ["c03"]
    assert excluded[0]["claim"]["confidence"] == "very likely"
    assert any("dropped c03" in line and "'very likely'" in line for line in logs)
    assert any("normalized 1 claim" in line for line in logs)
    audit = json.loads((Path(worker.output_dir) / "research_dossier.json").read_text())
    assert audit["confidence_filter"]["excluded_count"] == 1
    assert len(provider.calls) == 1


def test_a_ledger_with_no_valid_confidence_still_fails_and_says_why(tmp_path, monkeypatch):
    dossier = _three_claim_dossier(second="probable", third="very likely")
    dossier["claims"][0]["confidence"] = "certain"
    _provider, worker = _replay(tmp_path, monkeypatch, dossier, "all-bad-worker")

    with activate(worker), pytest.raises(ValueError, match=r"invalid_confidencex3") as failure:
        pipeline.generate_research_dossier(QUESTION)

    assert "no remaining claim's confidence" in str(failure.value)
    audit = json.loads((Path(worker.output_dir) / "research_dossier.json").read_text())
    assert audit["claims"] == []
    assert audit["validation"]["passed"] is False
    assert [e["reason"] for e in audit["excluded_claims"]] == ["invalid_confidence"] * 3
