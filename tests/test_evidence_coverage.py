"""Regression coverage for the paid cane-toad failure; provider decisions are explicit fixtures."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import claim_entailment as ce
import cost_ledger
import durable_execution
import event_functions as ef
import explainer_pipeline as ep
import research_coverage as coverage
import story_compiler as compiler
import story_fact_model as facts
import story_planning
from test_longform_research_phase2 import _dossier
from test_durable_anthropic_response import Provider
from test_durable_execution_phase6 import MemoryBlob, MemoryStore, runtime
from test_research_continuation import _paused, _completed, _mock_sources

INTRO = "Cane toads were introduced to control cane beetles."
STUDIES = "No studies of the toad's environmental impact preceded its release."
SETUP = "Across the wetland, lizards and quolls fed on frogs within a long-established food web."


def dossier(texts):
    template = _dossier()["claims"][0]
    claims = [dict(template, claim_id=f"c{i}", claim=text, support_quote=text,
                   claim_kind=kind, source_url=f"https://fixture.example.edu/evidence/{i}",
                   claim_kind_confidence=1.0)
              for i, (text, kind) in enumerate(texts, 1)]
    return {"topic": "Cane toad introduction", "version": 1, "claims": claims,
            "citation_urls": [c["source_url"] for c in claims],
            "citation_records": [{"url": c["source_url"], "cited_text": c["support_quote"]}
                                 for c in claims]}


def fixture():
    texts = [SETUP, INTRO,
             "Cane toad toxins poison native frog-eating predators.",
             "Large native predator populations declined after the toads arrived.",
             "Smaller prey species increased as their predators declined."]
    data = dossier([(texts[0], "mechanism"), (STUDIES, "context"),
                    (texts[2], "mechanism"), (texts[3], "outcome"), (texts[4], "outcome")])
    beats = [{"beat_id": f"event_{i}", "beat": text, "event_function": function,
              "event": {"text": text, "claim_refs": [f"c{i}"]},
              "changes_state": {"from": "Earlier ecological state", "to": text}}
             for i, (text, function) in enumerate(zip(texts, ef.REMOVED_KEYSTONE.required), 1)]
    return compiler.compile_roles(beats, "removed_keystone")["beats"], data


class Judge:
    def __init__(self):
        self.calls = []

    def __call__(self, payload):
        self.calls.append(payload)
        claims = " ".join(c.get("claim", "") for c in payload["claims"])
        if payload["kind"] == "function":
            return {"verdict": "entailed" if INTRO in claims else "unsupported",
                    "reason": "An absence of studies does not establish implementation and intent."}
        if payload["event"] == INTRO and INTRO not in claims:
            return {"verdict": "partially_entailed", "supported_core": STUDIES,
                    "unsupported_details": [INTRO], "reason": "Introduction purpose is missing."}
        if "bred rats" in payload["event"]:
            return {"verdict": "unsupported", "reason": "No evidence of rat breeding."}
        return {"verdict": "entailed", "reason": "Fixture supports the statement."}


def prepare(beats, data, judge, cache=None):
    return story_planning.prepare(beats, "removed_keystone",
        {c["claim_id"]: c for c in data["claims"]}, judge=judge, cache=cache)["compiled"]


def test_ecological_setup_reaches_semantic_check_and_fabrication_still_fails():
    beats, data = fixture()
    judge = Judge()
    report = prepare(beats, data, judge)
    assert any(call["event"] == SETUP for call in judge.calls)
    assert not any(row["code"] == "CLAIM_KIND_MISMATCH" for row in report["cascade"]["structural"])
    bad = deepcopy(beats[0])
    bad["event"]["text"] = "People bred rats for a bounty."
    checked = facts.validate_cascade([bad], {c["claim_id"]: c for c in data["claims"]},
                                    engine_id="removed_keystone", judge=judge)
    assert not checked["passed"] and checked["evidence"][0]["verdict"] == "unsupported"
    assert "mechanism" not in facts.accepted_claim_kinds("intervention", "removed_keystone")


def test_narrowing_cannot_remove_the_intervention_and_its_purpose():
    beats, data = fixture()
    report = prepare(beats, data, Judge())
    assert not report["passed"]
    assert any(row["code"] == "ROLE_CONTRACT_FAILED" for row in report["unrepairable"])
    assert "intervention" in report["coverage"]["missing"]
    assert report["effective_beats"][1]["event"]["text"] == INTRO
    gaps = coverage.evidence_gaps(report, beats)
    assert len(gaps) == 1 and gaps[0]["assertion_to_verify"] == INTRO


def test_one_research_repair_preserves_events_old_claims_and_rechecks_the_same_sheet(tmp_path, monkeypatch):
    beats, data = fixture()
    original = deepcopy(data)
    judge, cache = Judge(), {}
    report = prepare(beats, data, judge, cache)
    supplement = dossier([(INTRO, "event")])  # c1 collides deliberately with existing evidence.
    generate = Mock(return_value=supplement)
    path = tmp_path / "coverage.json"
    monkeypatch.setattr(coverage, "_state_path", lambda: (path, Mock()))
    repaired = coverage.repair_sheet("Question", beats, report, data,
                                    generate=generate, judge=judge, cache=cache)
    assert repaired and data == original
    assert repaired["dossier"]["claims"][:5] == data["claims"]
    assert repaired["dossier"][coverage.REPAIR_VERSION]["added_claim_ids"] == ["repair_c1"]
    for old, new in zip(beats, repaired["beats"]):
        assert old["event"]["text"] == new["event"]["text"]
        assert old["event_function"] == new["event_function"]
        if old["beat_id"] != "event_2":
            assert old == new
    assert prepare(repaired["beats"], repaired["dossier"], judge, cache)["passed"]
    # A worker restart reads the completed repair, without purchasing research again.
    replay = coverage.repair_sheet("Question", beats, report, data,
                                  generate=generate, judge=judge, cache=cache)
    assert replay["dossier"] == repaired["dossier"] and generate.call_count == 1
    assert coverage.repair_sheet("Question", beats, report, repaired["dossier"],
                                 generate=generate, judge=judge) is None
    changed = deepcopy(report)
    changed["cascade"]["evidence"][0]["reason"] = "A different missing fact"
    with pytest.raises(ValueError, match="different gap set"):
        coverage.repair_sheet("Question", beats, changed, data, generate=generate, judge=judge)
    assert generate.call_count == 1


@pytest.mark.parametrize("failure", ["unavailable", "contradicted", "function_unavailable"])
def test_operational_failure_or_contradiction_never_starts_research(failure):
    beats, data = fixture()
    report = prepare(beats, data, Judge())
    if failure == "unavailable":
        report["cascade"]["unavailable"] = [{"verdict": "unavailable"}]
    elif failure == "contradicted":
        report["cascade"]["judgments"][0]["verdict"] = "contradicted"
    else:
        report["unrepairable"][0]["function_verdict"] = "unavailable"
    generate = Mock(side_effect=AssertionError("Research must not run"))
    assert coverage.repair_sheet("Question", beats, report, data, generate=generate) is None


def test_quote_presence_alone_does_not_license_a_new_fact(monkeypatch):
    beats, data = fixture()
    report = prepare(beats, data, Judge())
    supplement = dossier([(INTRO, "event")])
    supplement["claims"][0]["claim"] = "People bred rats for a bounty."
    result = coverage.repair_sheet("Question", beats, report, data,
        generate=lambda *a, **kw: supplement, judge=Judge())
    assert result is None


def test_supplement_cannot_import_comparison_facts_or_unobserved_urls():
    _, data = fixture()
    supplement = dossier([("COMPARABLE CASE (Hanoi): Residents bred rats.", "event")])
    merged, added = coverage.merge_supplement(data, supplement)
    assert not added and merged["claims"] == data["claims"]
    supplement = dossier([(INTRO, "event")])
    supplement["citation_urls"] = []
    with pytest.raises(ValueError, match="source validation"):
        coverage.merge_supplement(data, supplement)


def test_new_mechanism_claim_is_not_attached_to_an_intervention():
    beats, data = fixture()
    report = prepare(beats, data, Judge())
    supplement = dossier([(INTRO, "event"), ("Toxins affect native predators.", "mechanism")])
    repaired = coverage.repair_sheet("Question", beats, report, data,
        generate=lambda *a, **kw: supplement, judge=Judge())
    assert repaired["beats"][1]["event"]["claim_refs"] == ["c2", "repair_c1"]


def test_only_the_legacy_setup_failure_is_recoverable_with_a_valid_saved_dossier():
    _, data = fixture()
    message = ("STORY_SPINE_UNSUPPORTED\nwho was eating whom before anyone intervened\n"
               "[CLAIM_KIND_MISMATCH] beat event_1 is a setup beat citing c1, "
               "which is a mechanism claim; a setup beat may cite event, context, outcome")
    original = deepcopy(data)
    assert coverage.legacy_setup_dossier_repairable(data, message)
    assert data == original
    assert not coverage.legacy_setup_dossier_repairable(data, message.replace("setup beat", "intervention beat"))
    assert not coverage.legacy_setup_dossier_repairable(data, "Different failure\n" + message)
    data["citation_urls"] = []
    assert not coverage.legacy_setup_dossier_repairable(data, message)


def test_original_paid_request_is_unchanged_and_focused_search_replays_on_restart(tmp_path, monkeypatch):
    _mock_sources(monkeypatch)
    store, blob = MemoryStore(cap=20), MemoryBlob(tmp_path / "blob")
    provider = Provider(_paused(), _completed(), _paused(), _completed())
    gaps = [{"beat_id": "event_2", "assertion_to_verify": INTRO}]
    for name in ("worker-a", "worker-b"):
        worker = runtime(tmp_path, store, blob, name)
        monkeypatch.setattr(ep, "_anthropic_native", lambda: worker.wrap_anthropic(provider))
        ep.generate_research_dossier("Question")
        ep.generate_research_dossier("Question", evidence_gaps=gaps)
    assert len(provider.calls) == 4  # one initial search and one supplement, each with one pause.
    original, supplement = provider.calls[0], provider.calls[2]
    assert hashlib.sha256(original["messages"][0]["content"].encode()).hexdigest() == \
        "79517ce3aa63e672cc2f8b46145b3f09a60a6b205d59234542944d42c75b0264"
    prompt = supplement["messages"][0]["content"]
    assert "UNVERIFIED research questions" in prompt and INTRO in prompt
    assert "22-28" not in prompt and "3-5 claims about COMPARABLE CASES" not in prompt
    assert supplement["max_tokens"] <= 6000 and supplement["tools"][0]["max_uses"] <= 6
    assert store.job["reserved_cost_usd"] == 0


@pytest.mark.parametrize("ledger", [False, True])
def test_research_is_counted_once_outside_script_subtotal_even_on_checkpoint_reuse(tmp_path, monkeypatch, ledger):
    beats, data = fixture()
    report = prepare(beats, data, Judge())
    def generate(*a, cost_sink, **kw):
        cost_sink.append(.45)
        return dossier([(INTRO, "event")])
    generate = Mock(side_effect=generate)
    def judge(payload):
        payload["cost_sink"].append(.02)
        return Judge()(payload)
    monkeypatch.setattr(coverage, "_state_path", lambda: (tmp_path / "repair.json", Mock()))
    for _ in range(2):
        sink = cost_ledger.CostLedger() if ledger else []
        result = coverage.repair_sheet("Question", beats, report, data,
                                       generate=generate, judge=judge, cost_sink=sink)
        assert result["cost_usd"] == pytest.approx(.02)
        if ledger:
            assert sink.by_stage() == {"research": .45, "boundary_a_evidence": .02}
        else:
            assert sum(sink) + result["cost_usd"] == pytest.approx(.47)
    assert generate.call_count == 1


def test_supplement_obeys_the_existing_durable_budget_before_calling_provider(tmp_path, monkeypatch):
    _mock_sources(monkeypatch)
    store, blob = MemoryStore(cap=.0001), MemoryBlob(tmp_path / "blob")
    provider = Provider(_paused(), _completed())
    worker = runtime(tmp_path, store, blob, "worker")
    monkeypatch.setattr(ep, "_anthropic_native", lambda: worker.wrap_anthropic(provider))
    with pytest.raises(durable_execution.BudgetExceeded):
        ep.generate_research_dossier("Question", evidence_gaps=[{"assertion_to_verify": INTRO}])
    assert not provider.calls


def test_production_rechecks_repaired_sheet_before_buying_expansion(monkeypatch):
    beats, data = fixture()
    judge = Judge()
    plan_calls, expansions = [], []
    def create(**request):
        prompt = request["messages"][0]["content"]
        if "Plan the sourced factual events" in prompt:
            plan_calls.append(prompt)
            return SimpleNamespace(content=[SimpleNamespace(text=json.dumps({
                "beats": beats, "hook": "Why did the introduction change the ecosystem?"}))],
                usage=SimpleNamespace(input_tokens=10, output_tokens=10))
        if "NOW WRITE scenes" in prompt:
            expansions.append(prompt)
            assert "repair_c1" in prompt and INTRO in prompt
            raise StopAtExpansion()
        pytest.fail("Unexpected provider request")
    class StopAtExpansion(Exception):
        pass
    supplement = Mock(return_value=dossier([(INTRO, "event")]))
    monkeypatch.setattr(ep, "_claude", lambda: SimpleNamespace(messages=SimpleNamespace(create=create)))
    monkeypatch.setattr(ep, "generate_research_dossier", supplement)
    monkeypatch.setattr(ce, "_default_judge", judge)
    with pytest.raises(StopAtExpansion):
        ep._generate_script_chunked("Question", 90, "engaging", "", 7,
            causal_lane=True, pinned_engine="removed_keystone", research_dossier=data)
    assert len(plan_calls) == len(expansions) == supplement.call_count == 1
