"""Offline contracts; live judgment quality is a separate opt-in evaluation."""
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import Mock
import json
import pytest

import claim_entailment as ce
import explainer_pipeline as ep
import script_integrity as si


def draft(text="Half of all chicks die from stoats."):
    return {"scenes": [{"scene_id": "s1", "beat_id": "e1", "narration": text,
        "event": {"text": "Stoats cause half of kiwi chick deaths.", "claim_refs": ["c1"]}}]}


DOSSIER = {"claims": [{"claim_id": "c1", "claim": "Stoats cause half of kiwi chick deaths.",
                       "support_quote": "Stoats cause half of kiwi chick deaths."}]}


def issue(code="METRIC_MEANING_CHANGED", scene=1, quote="Half of all chicks"):
    return {"issues": [{"code": code, "scene": scene, "quote": quote,
        "reason": "Share of deaths is not a share of all chicks.",
        "repair": "Preserve deaths as the denominator."}]}


def test_exact_content_cached_and_edits_to_prose_or_evidence_rejudge():
    cache, calls = {}, []
    def judge(payload):
        calls.append(deepcopy(payload))
        return {"issues": []}
    script, dossier = draft(), deepcopy(DOSSIER)
    for _ in range(2):
        si.review(script, dossier, judge=judge, cache=cache)
    assert len(calls) == 1
    script["scenes"][0]["narration"] = "Half of chick deaths are caused by stoats."
    si.review(script, dossier, judge=judge, cache=cache)
    dossier["claims"][0]["support_quote"] = "A changed quotation."
    si.review(script, dossier, judge=judge, cache=cache)
    assert len(calls) == 3
    assert calls[-1]["scenes"][0]["evidence"][0]["support_quote"] == "A changed quotation."


def test_known_local_defect_cannot_disappear_when_an_unrelated_scene_changes():
    script, cache = draft(), {}
    script["scenes"].append({"scene_id": "s2", "narration": "A separate closing question."})
    assert not si.review(script, DOSSIER, judge=lambda _: issue(), cache=cache)["passed"]
    script["scenes"][1]["narration"] = "What does that mean for the birds?"
    result = si.review(script, DOSSIER, judge=lambda _: {"issues": []}, cache=cache)
    assert not result["passed"] and result["errors"][0]["code"] == "METRIC_MEANING_CHANGED"
    script["scenes"][0]["narration"] = "Stoats cause half of kiwi chick deaths."
    assert si.review(script, DOSSIER, judge=lambda _: {"issues": []}, cache=cache)["passed"]


def test_global_defect_is_rejudged_when_other_scenes_supply_missing_context():
    script, cache = draft(), {}
    assert not si.review(script, DOSSIER, judge=lambda _: issue("HOOK_PROMISE_UNPAID"), cache=cache)["passed"]
    script["scenes"].append({"scene_id": "s2", "narration": "The missing answer."})
    assert si.review(script, DOSSIER, judge=lambda _: {"issues": []}, cache=cache)["passed"]


def test_old_whole_story_clean_cache_cannot_erase_a_later_local_finding():
    script, cache = draft(), {}
    script["scenes"].append({"scene_id": "s2", "narration": "First ending."})
    assert si.review(script, DOSSIER, judge=lambda _: {"issues": []}, cache=cache)["passed"]
    script["scenes"][1]["narration"] = "Second ending."
    assert not si.review(script, DOSSIER, judge=lambda _: issue(), cache=cache)["passed"]
    script["scenes"][1]["narration"] = "First ending."
    judge = Mock(side_effect=AssertionError("whole-story response is cached"))
    assert not si.review(script, DOSSIER, judge=judge, cache=cache)["passed"]


@pytest.mark.parametrize("bad", [{}, {"issues": "none"}, issue(scene=99),
    issue(quote="not in the narration"), issue(code="STYLE_PREFERENCE"), issue(scene=True)])
def test_invalid_review_retries_once_fails_closed_and_is_not_cached(bad):
    judge, cache = Mock(return_value=bad), {}
    result = si.review(draft(), DOSSIER, judge=judge, cache=cache)
    assert not result["passed"] and result["retryable"]
    assert judge.call_count == 2 and cache == {}


def test_discordant_entailment_does_not_drive_a_repair():
    responses = iter([
        {"verdict": "partially_entailed", "unsupported_details": [
            "the reserve is unnamed, which is not itself an added fact — not flagged"]},
        {"verdict": "entailed", "unsupported_details": []}])
    result = ce.narration_fidelity("At Riponui six chicks survived.", "At one reserve six chicks survived.",
        judge=lambda _: next(responses))
    assert result["passed"]
    invalid = ce.narration_fidelity("E", "N", judge=lambda _: {
        "verdict": "entailed", "unsupported_details": ["an unsupported date"]})
    assert not invalid["passed"] and ce.is_retryable(invalid)


def test_real_content_failure_is_cached_and_addresses_the_repair_scene():
    judge, cache = Mock(return_value=issue()), {}
    result = si.review(draft(), DOSSIER, judge=judge, cache=cache)
    assert not result["passed"] and not result["retryable"]
    assert result["errors"][0]["scene"] == 1
    assert result["errors"][0]["code"] == "METRIC_MEANING_CHANGED"
    si.review(draft(), DOSSIER, judge=judge, cache=cache)
    assert judge.call_count == 1


def test_whole_script_review_includes_discourse_and_blocks_claim_pass(monkeypatch):
    import longform_research as lr
    script = draft()
    script["scenes"].append({"narration": "Remove a predator the birds never met.",
                             "event": {"text": "", "claim_refs": []}})
    seen = []
    def judge(payload, costs):
        seen.extend(payload["scenes"])
        costs.append(.03)
        return issue("CAUSAL_DIRECTION_REVERSED", 2, "Remove a predator")
    monkeypatch.setattr(lr, "validate_story_fact_model", lambda *a, **k: {"passed": True, "errors": []})
    monkeypatch.setattr(si, "_judge", judge)
    costs = []
    report = ep._validate_claims(script, DOSSIER, costs)
    assert not report["passed"] and report["errors"][0]["scene"] == 2
    assert seen[1]["event"]["text"] == "" and costs == [.03]
    assert not script["_script_integrity"]["passed"]


def test_production_prompt_uses_the_same_meaning_rules_and_accounts_each_attempt(monkeypatch):
    create = Mock(side_effect=[NS(usage=NS(input_tokens=1, output_tokens=1), content=[NS(text="bad")]),
        NS(usage=NS(input_tokens=1, output_tokens=1), content=[NS(text='{"issues": []}')])])
    monkeypatch.setattr(ep, "_claude", lambda: NS(messages=NS(create=create)))
    monkeypatch.setattr(ep, "_msg_cost", lambda _: .01)
    costs = []
    assert si.review(draft(), DOSSIER, cost_sink=costs)["passed"]
    assert costs == [.01, .01] and create.call_count == 2
    assert ce.MEANING_RULES in create.call_args.kwargs["system"]
    assert "support_quote" in create.call_args.kwargs["messages"][0]["content"]


def test_fewer_errors_cannot_trade_factual_repairs_for_a_new_broken_transition():
    before = {"errors": [{"code": "NARRATION_EXCEEDS_EVENT", "scene": i} for i in range(3)]}
    after = {"errors": [{"code": "MISSING_CASE_TRANSITION", "scene": 2}]}
    assert not si.improves(before, after)
    assert not si.improves(before, {"passed": True, "retryable": True})
    assert si.improves(before, {"errors": before["errors"][:1]})


def test_trim_that_orphans_a_subject_is_rolled_back(monkeypatch):
    script = {"scenes": [{"beat_id": "e1", "narration":
        "The little spotted kiwi survives. Birds remain offshore.",
        "claim_refs": [{"narration_phrase": "Birds remain offshore."}]},
        {"narration": "It survives only on islands."}]}
    original = deepcopy(script)
    before = {"passed": False, "errors": [{"code": "NARRATION_EXCEEDS_EVENT", "scene": "e1",
        "unsupported_details": ["The little spotted kiwi survives"]},
        {"code": "NARRATION_EXCEEDS_EVENT", "scene": "e2"}]}
    monkeypatch.setattr(ep, "rederive_narration_bindings", lambda *a: None)
    monkeypatch.setattr(ep, "_validate_claims", lambda *a: {"passed": False, "errors": [
        {"code": "UNRESOLVED_REFERENCE", "scene": 2}]})
    candidate, report, count = ep._validated_claim_trim(script, DOSSIER, before, [], lambda _: None)
    assert count == 0 and candidate is script and report is before
    assert script["scenes"] == original["scenes"]
    assert script["_edit_audit"][-1]["accepted"] is False
    assert script["_edit_audit"][-1]["candidate_report"]["errors"][0]["code"] == "UNRESOLVED_REFERENCE"
    monkeypatch.setattr(ep, "_validate_claims", lambda *a: {"passed": True, "errors": []})
    candidate, report, count = ep._validated_claim_trim(script, DOSSIER, before, [], lambda _: None)
    assert count == 1 and report["passed"] and script["scenes"] == original["scenes"]
    assert candidate["scenes"][0]["narration"] == "Birds remain offshore."


def test_integrity_failure_can_use_evidence_locked_editor(monkeypatch):
    create = Mock(return_value=NS(usage=NS(input_tokens=100, output_tokens=100), content=[NS(text=json.dumps({
        "scenes": [{"scene": 1, "narration": "Stoats cause half of kiwi chick deaths.",
                    "claim_refs": [{"claim_id": "c1", "narration_phrase": "Stoats cause half of kiwi chick deaths."}]}]}))]))
    monkeypatch.setattr(ep, "_claude", lambda: NS(messages=NS(create=create)))
    report = si.review(draft(), DOSSIER, judge=lambda _: issue())
    candidate, cost = ep.repair_claim_join_failures(draft(), DOSSIER, report)
    assert cost > 0 and candidate["scenes"][0]["narration"] == "Stoats cause half of kiwi chick deaths."
    payload = json.loads(create.call_args.kwargs["messages"][0]["content"])
    assert payload["scenes"][0]["allowed_claim_ids"] == ["c1"]
    create.reset_mock()
    ep.repair_claim_join_failures(draft(), DOSSIER, {**report, "retryable": True})
    create.assert_not_called()


def test_promptfoo_fixtures_use_production_prompt_and_reject_wrong_findings():
    from evals.promptfoo import prompts, asserts
    cases = prompts._fixture("script_integrity.json")
    assert len(cases) == 9
    for name, case in cases.items():
        context = {"vars": {"case": name}}
        messages = prompts.integrity(context)
        assert messages[0]["content"] == si.SYSTEM + "\n" + ce.MEANING_RULES
        payload = json.loads(messages[1]["content"])
        assert len(payload["scenes"]) == len(case["scenes"])
        empty = asserts.integrity_findings('{"issues": []}', context)
        assert empty["pass"] == (not case["expected"])
        assert not asserts.integrity_findings('{"issues": "not checked"}', context)["pass"]
