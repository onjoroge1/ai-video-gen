"""Compiled story functions, saved decisions, and optional roles share one engine contract."""
from copy import deepcopy
import io
import json
import tarfile
from unittest.mock import Mock

import pytest

import app as studio
import event_functions as ef
import research_handoff as handoff
import story_fact_model as facts
import story_planning
from test_durable_execution_phase6 import MemoryBlob
from test_evidence_coverage import fixture, INTRO


CORE = "Cane toads were brought to Queensland to control cane beetles, which are pests of the sugar cane industry."
AFTER = "growers looking for a living remedy to protect the harvest"


def snapshot():
    beats, dossier = fixture()
    claims = {c["claim_id"]: c for c in dossier["claims"]}
    for claim in claims.values():
        claim.update(quote_verified=True, source_reachable=True)
    beats[0]["changes_state"]["to"] = AFTER
    beats[0]["event"]["text"] = "Tropical growers sought a cure for crop damage."
    verdict = {"verdict": "partially_entailed", "passed": False, "supported_core": CORE,
               "unsupported_details": ["the specific growers"], "beat_id": "event_1"}
    compiled = {"passed": False, "still_failing": ["event_1"],
                "unrepairable": [{"beat_id": "event_1", "code": "ROLE_CONTRACT_FAILED",
                    "message": "the narrowed event shares nothing with the state it must produce"}],
                "cascade": {"evidence": [verdict]}}
    key = handoff.identity(beats, "removed_keystone", claims, {}, "Saved topic", False)
    key.pop("role_contract")  # The exact pre-fix contract, not a new rejection.
    prepared = {"beats": beats, "compiled": compiled, "cache": {}, "cost_usd": 0.1}
    return handoff.record(key, beats, claims, prepared), verdict


@pytest.mark.parametrize("engine,function,core", [
    ("removed_keystone", ef.ESTABLISHES_BALANCE, CORE),
    ("backfiring_solution", ef.ESTABLISHES_PROBLEM, "Rats infested the city."),
    ("almost_happened_plan", ef.ESTABLISHES_PROBLEM, "Meat shortages threatened consumers."),
])
def test_mapped_setup_reaches_semantic_review_without_shared_words(engine, function, core):
    beat = {"beat_id": "setup", "role": "setup", "event_function": function,
            "scope": "primary_story", "changes_state": {"from": "earlier", "to": AFTER},
            "event": {"text": "An embellished setup", "claim_refs": ["c1"]}}
    verdict = {"verdict": "partially_entailed", "passed": False, "supported_core": core}
    assert not facts.role_contract_holds(dict(beat, event={"text": core}))[0]
    judge = Mock(return_value={"verdict": "entailed"})
    kept, narrowed, blocked = facts.narrow_required_roles([beat], {"setup": verdict}, engine, judge=judge)
    assert narrowed and not blocked and kept[0]["event"]["text"] == core
    assert kept[0]["event"]["claim_refs"] == ["c1"]
    assert judge.call_count == 1 and judge.call_args.args[0]["kind"] == "function"


@pytest.mark.parametrize("verdict", ["unsupported", "contradicted", "unavailable"])
def test_semantic_rejection_or_outage_cannot_pass_narrowing(verdict):
    saved, partial = snapshot()
    judge = Mock(return_value={"verdict": verdict})
    kept, narrowed, blocked = facts.narrow_required_roles(
        [saved["draft_beats"][0]], {"event_1": partial}, "removed_keystone", judge=judge)
    assert not narrowed and blocked and judge.call_count == 1
    assert kept[0]["event"]["text"] != CORE


@pytest.mark.parametrize("core,scope", [
    ("The paper describes the cane beetle problem.", "primary_story"),
    (CORE, "parallel_case"),
])
def test_hard_scope_and_bibliography_checks_still_precede_semantics(core, scope):
    saved, partial = snapshot()
    beat = saved["draft_beats"][0]
    beat["scope"] = scope
    partial["supported_core"] = core
    judge = Mock(return_value={"verdict": "entailed"})
    _, narrowed, blocked = facts.narrow_required_roles([beat], {"event_1": partial},
                                                      "removed_keystone", judge=judge)
    assert not narrowed and blocked and judge.call_count == 0


@pytest.mark.parametrize("engine,function,prunes", [
    ("removed_keystone", ef.INTENDED_EFFECT, True),
    ("backfiring_solution", ef.APPARENT_SUCCESS, False),
    ("almost_happened_plan", ef.GAINS_BACKING, False),
    ("", ef.INTENDED_EFFECT, False),
])
def test_optional_status_comes_from_selected_engine(engine, function, prunes):
    beat = {"beat_id": "result", "role": "false_resolution", "event_function": function,
            "event": {"text": "A result the evidence does not support.", "claim_refs": ["c1"]}}
    kept, dropped = facts.prune_unsupported_optional([beat], {"result"}, engine)
    assert bool(dropped) is prunes and bool(kept) is not prunes


def test_full_compile_narrows_setup_and_drops_nonessential_beat_then_replays(tmp_path, monkeypatch):
    saved, partial = snapshot()
    beats, claims = saved["draft_beats"], saved["research_claims"]
    claims["c2"]["claim"] = INTRO
    beats.insert(2, {"beat_id": "optional", "role": "false_resolution",
                    "event_function": ef.INTENDED_EFFECT,
                    "event": {"text": "The beetles vanished.", "claim_refs": ["c2"]}})
    calls = []
    def judge(payload):
        calls.append(payload)
        if payload["kind"] == "function":
            return {"verdict": "entailed" if payload["claims"][0]["claim"] == CORE else "unsupported"}
        if payload["event"] == "The beetles vanished.":
            return {"verdict": "unsupported", "reason": "No such outcome in the source."}
        if payload["event"] == beats[0]["event"]["text"]:
            return partial
        return {"verdict": "entailed"}
    monkeypatch.setattr(handoff, "_location", lambda: (tmp_path / handoff.FILENAME, Mock()))
    result = story_planning.prepare(beats, "removed_keystone", claims, judge=judge)
    assert result["compiled"]["passed"]
    assert result["beats"][0]["event"]["text"] == CORE
    assert "optional" not in {b["beat_id"] for b in result["beats"]}
    before = len(calls)
    replay = story_planning.prepare(beats, "removed_keystone", claims, judge=judge)
    assert replay["compiled"] == result["compiled"] and len(calls) == before


@pytest.mark.parametrize("change", ["none", "new_contract", "changed_quote", "changed_draft",
                                    "contradiction", "other_failure", "outage", "unverified"])
def test_saved_checkpoint_eligibility_never_promotes_a_rejection(tmp_path, change):
    saved, _ = snapshot()
    if change == "new_contract":
        saved["identity"]["role_contract"] = facts.ROLE_CONTRACT_VERSION
    elif change == "changed_quote":
        saved["research_claims"]["c1"]["support_quote"] += " A changed quotation."
    elif change == "changed_draft":
        saved["draft_beats"][0]["event"]["text"] = "A different event."
    elif change == "contradiction":
        saved["prepared"]["compiled"]["cascade"]["evidence"][0]["verdict"] = "contradicted"
    elif change == "other_failure":
        saved["prepared"]["compiled"]["unrepairable"][0]["message"] = "The intervention purpose is absent."
    elif change == "outage":
        saved["prepared"]["compiled"]["cascade"]["unavailable"] = [{"verdict": "unavailable"}]
    elif change == "unverified":
        saved["research_claims"]["c1"]["quote_verified"] = False
        saved["identity"]["evidence_sha256"] = handoff._hash(saved["research_claims"])
    original = deepcopy(saved)
    archive = tmp_path / "checkpoint.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        raw = json.dumps(saved).encode()
        member = tarfile.TarInfo(handoff.FILENAME)
        member.size = len(raw)
        tar.addfile(member, io.BytesIO(raw))
    blob = MemoryBlob(tmp_path / "blob")
    checkpoint = blob.upload(str(archive), "checkpoint.tar.gz")
    job = {"id": "job", "error": "STORY_SPINE_UNSUPPORTED", "checkpoint": checkpoint}
    assert studio._compiled_function_checkpoint_repairable(job, object(), blob) is (change == "none")
    assert saved == original and saved["status"] == "blocked"
    if change == "none":
        new_key = {**saved["identity"], "role_contract": facts.ROLE_CONTRACT_VERSION}
        assert new_key != saved["identity"], "old completed decision cannot satisfy the new key"
