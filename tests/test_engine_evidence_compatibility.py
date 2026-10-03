"""Evidence owns the story engine when an incentive story and an ecology story diverge."""
from types import SimpleNamespace
import json

import explainer_pipeline as ep
import story_engines as se
import story_planner as planner


STOATS = {
    "claims": [
        {"claim_id": "c1", "claim": "Large numbers of stoats were introduced to New Zealand to control rabbits."},
        {"claim_id": "c2", "claim": "Stoat predation caused severe declines in native bird populations and kills kiwi chicks."},
        # A payment existed, but the ecological cascade was not caused by people gaming it.
        {"claim_id": "c3", "claim": "A reward was paid for stoats liberated onto Crown lands."},
    ]
}

HANOI = {
    "claims": [
        {"claim_id": "c1", "claim": "Authorities paid a bounty for each rat tail."},
        {"claim_id": "c2", "claim": "Residents bred and farmed rats to profit from the bounty."},
    ]
}


def _reply(value):
    return SimpleNamespace(
        content=[SimpleNamespace(text=json.dumps(value))],
        usage=SimpleNamespace(input_tokens=10, output_tokens=10),
    )


def test_ecological_introduction_overrides_bounty_engine_even_when_a_payment_is_mentioned():
    result = se.evidence_compatibility(se.BACKFIRING_SOLUTION, STOATS)
    assert result["compatible"] is False
    assert result["replacement"] == se.REMOVED_KEYSTONE
    assert "no evidence that people exploited" in result["reason"]


def test_actual_bounty_exploitation_keeps_the_backfiring_engine():
    assert se.evidence_compatibility(se.BACKFIRING_SOLUTION, HANOI)["compatible"] is True


def test_parallel_bounty_case_cannot_reclassify_an_ecology_story():
    dossier = json.loads(json.dumps(STOATS))
    dossier["claims"].append({
        "claim_id": "case1", "scope": "parallel_case",
        "claim": "A comparable bounty was exploited when residents bred rats for profit.",
    })
    assert se.evidence_compatibility(
        se.BACKFIRING_SOLUTION, dossier)["replacement"] == se.REMOVED_KEYSTONE


def test_selector_refuses_model_choice_that_contradicts_sourced_premise(monkeypatch):
    monkeypatch.setattr(ep, "_claude", lambda: SimpleNamespace(messages=SimpleNamespace(
        create=lambda **_: _reply({"engine": se.BACKFIRING_SOLUTION, "why": "the fix backfired"}))))
    assert ep._select_story_engine(
        "Why were stoats released in New Zealand?", 180,
        research_dossier=STOATS) == se.REMOVED_KEYSTONE


def test_engine_switch_selector_excludes_failed_contract_and_quotes_report(monkeypatch):
    prompts = []

    def create(**call):
        prompts.append(call["messages"][0]["content"])
        return _reply({"engine": se.REMOVED_KEYSTONE, "why": "an ecological cascade"})

    monkeypatch.setattr(ep, "_claude", lambda: SimpleNamespace(
        messages=SimpleNamespace(create=create)))
    selected = ep._select_story_engine(
        "Why were stoats released in New Zealand?", 180,
        research_dossier=STOATS,
        excluded_engines=(se.BACKFIRING_SOLUTION,),
        failure_report="[ROLE_CONTRACT_FAILED] direct introduction is not an incentive",
    )
    assert selected == se.REMOVED_KEYSTONE
    assert "ROLE_CONTRACT_FAILED" in prompts[0]
    assert "backfiring_solution:" not in prompts[0]


def test_dramatron_score_surfaces_engine_mismatch_instead_of_reporting_100():
    plan = {
        "hook": "New Zealand imported a predator and its native birds paid the price.",
        "cold_open": {"text": "A stoat pulls a kiwi chick from its burrow.", "claim_refs": ["c2"]},
        "beats": [{
            "n": 1, "beat_id": "event_01", "beat": "Stoats were introduced.",
            "event_function": "establishes_problem", "caused_by": "",
            "event": {"text": "Stoats were introduced to control rabbits.", "claim_refs": ["c1"]},
            "changes_state": {"from": "", "to": ""},
        }],
    }
    report = planner.score_plan(plan, se.BACKFIRING_SOLUTION, STOATS, 180)
    assert report["score"] < 100
    assert any("engine mismatch" in issue for issue in report["issues"])
