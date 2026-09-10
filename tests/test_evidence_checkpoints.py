"""Restore intermediate evidence work into a new worker, with no live providers."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

import claim_entailment as ce
import claim_verify
import cost_ledger
from provider_blocks import ProviderBlocked, MESSAGES
import research_coverage as coverage
from test_durable_execution_phase6 import MemoryBlob, MemoryStore, runtime
from test_evidence_coverage import INTRO, Judge, dossier, fixture, prepare


def blocked():
    return ProviderBlocked({"provider": "anthropic", "code": "insufficient_credit",
                            "http_status": 400, "message": MESSAGES["insufficient_credit"]})


def attach_worker(tmp_path, store, blob, name, monkeypatch):
    worker = runtime(tmp_path, store, blob, name)
    worker.restore_checkpoint(store.job["checkpoint"])
    path = Path(worker.output_dir) / f"{coverage.REPAIR_VERSION}.json"
    monkeypatch.setattr(coverage, "_state_path", lambda: (path, worker))
    return path


def test_source_passages_and_decisions_survive_account_pause_in_new_worker(tmp_path, monkeypatch):
    beats, data = fixture()
    report = prepare(beats, data, Judge())
    data["claims"][0].update(quote_verified=True, source_reachable=True)
    # The question shares every content word but establishes no fact.
    question = "Cane toads were introduced to control cane beetles?"
    fetch = Mock(return_value=f"{question}\n{INTRO}")
    monkeypatch.setattr(claim_verify, "fetch_page_text", fetch)
    monkeypatch.setattr(claim_verify, "candidate_passages", lambda *a, **kw: [question, INTRO])
    store, blob = MemoryStore(), MemoryBlob(tmp_path / "blob")
    path = attach_worker(tmp_path, store, blob, "first", monkeypatch)
    calls = []

    def judge(payload):
        calls.append(payload["claims"][0]["claim"])
        if len(calls) == 2:
            raise blocked()
        payload["cost_sink"].append(.02)
        return {"verdict": "entailed" if calls[-1] == INTRO else "unsupported"}

    generate = Mock(side_effect=AssertionError("A verified page should cover this gap"))
    with pytest.raises(ProviderBlocked):
        coverage.repair_sheet("Question", beats, report, data,
                              generate=generate, judge=judge)
    saved = json.loads(path.read_text())
    assert len(saved["source_progress"]["decisions"]) == 1
    assert len(saved["source_progress"]["candidates"]["event_2"]) == 2
    restored = attach_worker(tmp_path, store, blob, "second", monkeypatch)
    assert restored != path and json.loads(restored.read_text()) == saved

    sink = cost_ledger.CostLedger()
    repaired = coverage.repair_sheet("Question", beats, report, data,
                                    generate=generate, judge=judge, cost_sink=sink)
    assert repaired and fetch.call_count == 1
    assert calls == [question, INTRO, INTRO]  # Only the rejected account call is retried.
    assert generate.call_count == 0
    assert repaired["cost_usd"] == pytest.approx(.04)
    assert sink.by_stage() == {cost_ledger.BOUNDARY_A: .04}
    assert prepare(repaired["beats"], repaired["dossier"], Judge())["passed"]


@pytest.mark.parametrize("ledger", [True, False])
def test_returned_supplement_and_each_verdict_survive_later_pause(tmp_path, monkeypatch, ledger):
    beats, data = fixture()
    report = prepare(beats, data, Judge())
    store, blob = MemoryStore(), MemoryBlob(tmp_path / "blob")
    attach_worker(tmp_path, store, blob, "first", monkeypatch)
    supplement = dossier([(INTRO, "event"), ("Toad toxins poison predators.", "mechanism")])

    def generate(*a, cost_sink, **kw):
        cost_sink.append(.45)
        return deepcopy(supplement)

    generate = Mock(side_effect=generate)
    calls = []

    def judge(payload):
        calls.append(payload["event"])
        if len(calls) == 2:
            raise blocked()
        payload["cost_sink"].append(.02)
        return {"verdict": "entailed"}

    with pytest.raises(ProviderBlocked):
        coverage.repair_sheet("Question", beats, report, data, generate=generate, judge=judge)
    attach_worker(tmp_path, store, blob, "second", monkeypatch)
    sink = cost_ledger.CostLedger() if ledger else []
    repaired = coverage.repair_sheet("Question", beats, report, data,
                                    generate=generate, judge=judge, cost_sink=sink)
    assert repaired and generate.call_count == 1
    assert calls == [INTRO, supplement["claims"][1]["claim"], supplement["claims"][1]["claim"]]
    assert repaired["research_cost_usd"] == pytest.approx(.45)
    assert repaired["cost_usd"] == pytest.approx(.04)
    if ledger:
        assert sink.by_stage() == {cost_ledger.RESEARCH: .45, cost_ledger.BOUNDARY_A: .04}
    else:
        assert sum(sink) + repaired["cost_usd"] == pytest.approx(.49)


def test_failed_research_keeps_source_rejections_without_repeating_fetch(tmp_path, monkeypatch):
    beats, data = fixture()
    report = prepare(beats, data, Judge())
    data["claims"][0].update(quote_verified=True, source_reachable=True)
    fetch = Mock(return_value="Cane toads and cane beetles appear in a museum catalogue.")
    monkeypatch.setattr(claim_verify, "fetch_page_text", fetch)
    path = tmp_path / "repair.json"
    monkeypatch.setattr(coverage, "_state_path", lambda: (path, Mock()))
    judge = Mock(return_value={"verdict": "unsupported", "reason": "No introduction purpose."})
    generate = Mock(side_effect=ValueError("Evidence supplement failed source validation"))
    for _ in range(2):
        with pytest.raises(ValueError, match="source validation"):
            coverage.repair_sheet("Question", beats, report, data, generate=generate, judge=judge)
    saved = json.loads(path.read_text())
    assert saved["status"] == "started"
    assert saved["source_reuse"] == {"sources": 1, "fetched": 1, "recovered_gaps": 0}
    assert saved["source_entailment"][0]["reason"] == "No introduction purpose."
    assert saved["reused_claims"] == []
    assert fetch.call_count == judge.call_count == 1


def test_saved_invalid_supplement_stays_invalid_without_rebuying_it(tmp_path, monkeypatch):
    beats, data = fixture()
    report = prepare(beats, data, Judge())
    monkeypatch.setattr(coverage, "_state_path", lambda: (tmp_path / "repair.json", Mock()))
    bad = dossier([(INTRO, "event")])
    bad["citation_urls"] = []
    generate, judge = Mock(return_value=bad), Mock()
    for _ in range(2):
        with pytest.raises(ValueError, match="source validation"):
            coverage.repair_sheet("Question", beats, report, data, generate=generate, judge=judge)
    assert generate.call_count == 1 and judge.call_count == 0


def test_decision_reuse_binds_content_and_contract_and_counts_usage_once(monkeypatch):
    progress, accounted, sink = {}, set(), []

    def judge(payload):
        payload["cost_sink"].append(.02)
        return {"verdict": "entailed"}

    judge = Mock(side_effect=judge)
    claims = [{"claim_id": "source_excerpt", "claim": INTRO, "source_url": "https://example.edu"}]

    def check(assertion=INTRO):
        return coverage._checkpointed_entailment(
            claims, assertion, progress=progress, save=lambda: None,
            accounted=accounted, judge=judge, cost_sink=sink)

    assert check()["passed"] and check()["passed"]
    assert judge.call_count == 1 and sum(sink) == pytest.approx(.02)
    accounted, sink = set(), []  # A new attempt includes saved usage once.
    check()
    check()
    assert judge.call_count == 1 and sum(sink) == pytest.approx(.02)
    check("An altered assertion")
    claims[0]["claim"] = "An altered source passage"
    check()
    monkeypatch.setattr(ce, "ENTAILMENT_CONTRACT_VERSION", "changed_contract")
    check()
    assert judge.call_count == 4
