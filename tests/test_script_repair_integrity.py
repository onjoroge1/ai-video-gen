"""Offline regressions from Studio job 72d6e8da (PR148 production check)."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

import claim_entailment as ce
import explainer_pipeline as ep
import script_editor as editor
from script_repair import broken_repair, reconcile_factcheck_events


def client(reply):
    def create(**kwargs):
        return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(reply))],
                               usage=SimpleNamespace(input_tokens=100, output_tokens=100))
    return lambda: SimpleNamespace(messages=SimpleNamespace(create=create))


@pytest.mark.parametrize("sentence,detail", [
    ("It is carried through the forest now with a chick in its jaws instead.", "a chick in its jaws"),
    ("At Shy Lake, in southern Fiordland, researchers tracked a kiwi population for years.",
     "tracked a kiwi population for years"),
    ("So back at Shy Lake, crews fought back.", "crews fought back"),
])
def test_never_cut_a_predicate_or_preposition_complement(sentence, detail):
    assert ep._clip_unsupported_clause(sentence, [detail], []) == sentence


@pytest.mark.parametrize("text", [
    "It is carried through the forest now with instead.",
    "At Shy Lake, in southern Fiordland, researchers.",
    "So back at Shy Lake.",
    "The stoats were introduced because.",
])
def test_rejects_production_repair_fragments(text):
    assert broken_repair(text)


@pytest.mark.parametrize("text", [
    "In New Zealand stoats spread.", "At Shy Lake, researchers tracked kiwi chicks.",
    "Nobody counted the native birds.", "Which animal was the plan intended for?",
])
def test_complete_narration_is_not_rejected(text):
    assert not broken_repair(text)


def test_trimming_preserves_at_least_one_sentence_and_reports_real_deletions():
    script = {"scenes": [{"beat_id": "b1", "narration": "Birds vanished. Nests emptied."}]}
    report = {"errors": [{"code": "NARRATION_EXCEEDS_EVENT", "scene": "b1",
                           "unsupported_details": ["Birds vanished", "Nests emptied"]}]}
    assert ep._trim_unsupported_sentences(script, report) == 1
    assert script["scenes"][0]["narration"] == "Nests emptied."


def test_partial_overlap_with_citation_prevents_clause_clip():
    text = "To stretch that fuel, he joins the others in a huddle."
    assert ep._clip_unsupported_clause(text, ["To stretch that fuel"], ["that fuel"]) == text


def fixture():
    before = "The plan worked so well that stoats were protected."
    after = "The plan failed, but stoats were still protected."
    event = {"text": "Stoats were protected.", "claim_refs": ["c09"]}
    script = {"_story_engine": "removed_keystone", "scenes": [{
        "beat_id": "event_04", "causal_role": "escalation", "scope": "primary_story",
        "event": event, "narration": after, "evidence_id": "e04",
        "claim_refs": [{"claim_id": "c09", "evidence_id": "e04", "narration_phrase": before}],
    }]}
    dossier = {"claims": [
        {"claim_id": "c06", "claim": "Stoats were introduced in a vain attempt to control rabbits."},
        {"claim_id": "c09", "claim": "Stoats were protected."},
    ]}
    proposal = [{"scene": 1, "event": {"text": after, "claim_refs": ["c06", "c09"]}}]
    return script, dossier, [before], proposal


def test_factcheck_reconciles_correction_only_after_both_boundaries(monkeypatch):
    script, dossier, before, proposals = fixture()
    calls = []
    def judge(payload):
        calls.append(payload["kind"])
        payload["cost_sink"].append(.01)
        return {"verdict": "entailed", "supported_core": payload["event"]}
    monkeypatch.setattr(ce, "_default_judge", judge)
    costs = []
    reconcile_factcheck_events(script, before, proposals, dossier, costs)
    assert calls == ["evidence", "fidelity"]
    assert sum(costs) == .02
    assert script["scenes"][0]["event"] == proposals[0]["event"]
    assert {r["claim_id"] for r in script["scenes"][0]["claim_refs"]} == {"c06", "c09"}
    assert all(r["narration_phrase"] == script["scenes"][0]["narration"]
               for r in script["scenes"][0]["claim_refs"])
    assert script["_factcheck_reconciliation"][0]["passed"]


@pytest.mark.parametrize("failure", ["evidence", "fidelity", "unavailable", "invalid_response"])
def test_factcheck_cannot_self_certify_unsupported_event(monkeypatch, failure):
    script, dossier, before, proposals = fixture()
    original = deepcopy(script["scenes"][0]["event"])
    def judge(payload):
        verdict = (failure if failure in {"unavailable", "invalid_response"}
                   else "unsupported" if payload["kind"] == failure else "entailed")
        return {"verdict": verdict}
    monkeypatch.setattr(ce, "_default_judge", judge)
    reconcile_factcheck_events(script, before, proposals, dossier, [])
    assert script["scenes"][0]["event"] == original
    assert "plan failed" in script["scenes"][0]["narration"]  # do not restore a false statement
    assert not script["_factcheck_reconciliation"][0]["passed"]


@pytest.mark.parametrize("invalid", ["unknown_id", "parallel_case", "derived", "unchanged", "duplicate"])
def test_invalid_event_updates_do_not_buy_a_judgment(monkeypatch, invalid):
    script, dossier, before, proposals = fixture()
    original = deepcopy(script["scenes"][0]["event"])
    if invalid == "unknown_id":
        proposals[0]["event"]["claim_refs"].append("invented")
    elif invalid == "parallel_case":
        dossier["claims"][0]["parallel_case_id"] = "hanoi"
    elif invalid == "derived":
        script["scenes"][0]["derivation"] = {"kind": "proxy_gap"}
    elif invalid == "unchanged":
        before = [script["scenes"][0]["narration"]]
    else:
        proposals += deepcopy(proposals)
    calls = []
    monkeypatch.setattr(ce, "_default_judge", lambda payload: calls.append(payload) or {"verdict": "entailed"})
    reconcile_factcheck_events(script, before, proposals, dossier, [])
    assert not calls
    assert script["scenes"][0]["event"] == original


def test_factcheck_wires_event_updates_and_accounts_for_judges(monkeypatch):
    script, dossier, before, proposals = fixture()
    corrected = script["scenes"][0]["narration"]
    script["scenes"][0]["narration"] = before[0]
    monkeypatch.setattr(ep, "_claude", client({"narration": [corrected], "notes": ["Corrected failure"],
                                               "event_updates": proposals}))
    def judge(payload):
        payload["cost_sink"].append(.1)
        return {"verdict": "entailed"}
    monkeypatch.setattr(ce, "_default_judge", judge)
    out, notes, cost = ep.factcheck_script(script, "Why stoats?", dossier)
    assert out["scenes"][0]["event"] == proposals[0]["event"]
    assert cost >= .2 and notes == ["Corrected failure"]


def test_factcheck_rejects_broken_repair_without_mutation_and_counts_cost(monkeypatch):
    script, dossier, _, _ = fixture()
    original = deepcopy(script)
    monkeypatch.setattr(ep, "_claude", client({"narration": ["So back at Shy Lake."]}))
    out, notes, cost = ep.factcheck_script(script, "Why?", dossier)
    assert out == original and cost > 0 and "rejected" in notes[0]


@pytest.mark.parametrize("local_success", [True, False])
def test_hook_and_hinge_overruns_never_replan_supported_story(monkeypatch, local_success):
    draft = {"scenes": [], "_research_dossier": {"claims": [{"claim_id": "c1"}]}}
    state = {"edited": False, "generated": 0, "hinge": 0}
    def generate(*args, **kwargs):
        state["generated"] += 1
        assert state["generated"] == 1, "local wording failure must not generate another story"
        return draft
    def hook(script, *args):
        state["edited"] = local_success
        return script, .1
    def hinge(script, *args):
        state["hinge"] += 1
        return script, .2
    monkeypatch.setattr(ep, "generate_script", generate)
    monkeypatch.setattr(ep, "_LONGFORM_CONTRACT_RETRIES", 2)
    monkeypatch.setattr(ep, "_ensure_hook_fits_budget", hook)
    monkeypatch.setattr(ep, "_ensure_hinge_fits_budget", hinge)
    monkeypatch.setattr(ep, "validate_longform_story", lambda *args: {
        "passed": state["edited"], "score": 100 if state["edited"] else 0,
        "errors": [] if state["edited"] else [{"code": "LONG_HOOK"}, {"code": "SOFT_HINGE"}]})
    monkeypatch.setattr(ep, "_causal_contract_report", lambda *args: (
        state["edited"], [] if state["edited"] else ["LONG_HOOK: 19 words", "SOFT_HINGE: 12 words"]))
    monkeypatch.setattr(ep, "grade_script", lambda *args, **kwargs: None)
    out = ep.generate_graded_script("Why stoats?", 180, "scientific", "", "landscape", "",
                                    causal_lane=True)
    assert state["generated"] == state["hinge"] == 1
    assert out["_retention_validation"]["passed"] == local_success
    assert out["_script_cost_usd"] == .3


def test_non_length_story_failure_still_needs_structural_repair():
    assert not ep._only_word_budget_blocks({"errors": [{"code": "MISSING_MECHANISM"}]}, ["SOFT_HINGE: long"])
    assert not ep._only_word_budget_blocks({"errors": []}, [])


def test_targeted_editor_uses_hard_hinge_cap(monkeypatch):
    script = {"scenes": [{"causal_role": "hinge", "narration": "word " * 20}]}
    defects = [{"scene": 1, "code": editor.HINGE_TOO_LONG, "note": "over budget"}]
    assert editor.build_payload(script, {}, defects)["scenes"][0]["words_allowed"] == "1-10"
    monkeypatch.setattr(ep, "_claude", client({"scenes": [{"scene": 1, "narration": "The problem was still there."}]}))
    out, cost, remaining = editor.edit(script, {}, defects)
    assert not remaining and out is not script and cost > 0


def test_targeted_editor_rejects_broken_sentences(monkeypatch):
    script = {"scenes": [{"causal_role": "hinge", "narration": "word " * 12}]}
    defects = [{"scene": 1, "code": editor.HINGE_TOO_LONG, "note": "over budget"}]
    monkeypatch.setattr(ep, "_claude", client({"scenes": [{"scene": 1, "narration": "So back at Shy Lake."}]}))
    out, cost, remaining = editor.edit(script, {}, defects)
    assert out is script and remaining == defects and cost > 0


def test_final_ledger_rejects_fragments_before_buying_evidence_checks(monkeypatch):
    import longform_research as lr
    calls = []
    monkeypatch.setattr(lr, "validate_story_fact_model", lambda *a, **k: calls.append(a))
    script, dossier, _, _ = fixture()
    script["scenes"][0]["narration"] = "It is carried through the forest now with instead."
    report = ep._validate_claims(script, dossier)
    assert not calls and not report["passed"]
    assert report["errors"][0]["code"] == "BROKEN_NARRATION_REPAIR"


def test_rejected_claim_rewrite_preserves_script_and_billable_cost(monkeypatch):
    script, dossier, _, _ = fixture()
    original = deepcopy(script)
    monkeypatch.setattr(ep, "_claude", client({"scenes": [{
        "scene": 1, "narration": "So back at Shy Lake.", "evidence_id": "e04",
        "claim_refs": [{"claim_id": "c09", "narration_phrase": "So back at Shy Lake."}],
    }]}))
    report = {"errors": [{"code": "NARRATION_EXCEEDS_EVENT", "scene": "event_04"}]}
    out, cost = ep.repair_claim_join_failures(script, dossier, report)
    assert out == original and cost > 0
