"""Dramatron-style planning: candidates are scored by the gates and the best is chosen."""
import json
import os

import story_planner as sp


def _beat(n, fn, text, refs, caused_by=""):
    return {"n": n, "beat_id": f"event_{n:02d}", "beat": text, "event_function": fn,
            "caused_by": caused_by, "event": {"text": text, "claim_refs": refs},
            "changes_state": {"from": "", "to": ""}}


def test_distinct_events_flags_a_restated_event():
    beats = [
        _beat(1, "prior_food_web", "Colonists carried European honey bees to the Americas.", ["c1"]),
        _beat(2, "species_introduced", "Brazil imported African queens in 1956 to breed a tropical strain.", ["c2"]),
        _beat(3, "population_shift", "Twenty-six African queens escaped the apiary with their swarms in 1957.", ["c3"]),
        _beat(4, "population_shift", "In 1957 twenty-six African queens and their swarms escaped the apiary.", ["c3"]),
    ]
    assert sp.distinct_events(beats) == [True, True, True, False]


def test_choose_plan_prefers_the_highest_score_and_the_first_on_ties():
    assert sp.choose_plan([{"score": 60}, {"score": 85}, {"score": 85}]) == 1
    assert sp.choose_plan([{"score": 0}]) == 0


def test_score_plan_penalises_a_missing_cold_open_and_restated_beats():
    good = {"hook": "Brazil imported African bees to make more honey", "title": "t",
            "cold_open": {"text": "A dark swarm boils out of a hive box while the keeper backs away",
                          "claim_refs": ["c3"]},
            "beats": [_beat(1, "prior_food_web", "Colonists carried European bees to the Americas centuries earlier.", ["c1"]),
                      _beat(2, "species_introduced", "Brazil imported African queens in 1956 for a breeding program.", ["c2"]),
                      _beat(3, "population_shift", "Twenty-six queens escaped the apiary with their swarms in 1957.", ["c3"]),
                      _beat(4, "population_shift", "The hybrids spread north two hundred miles a year and reached Texas.", ["c4"]),
                      _beat(5, "place_becomes", "Africanized bees became the feral honey bee of the Americas.", ["c5"])]}
    dossier = {"claims": [{"claim_id": f"c{i}", "claim": "x", "source_url": "https://x"} for i in range(1, 6)]}
    base = sp.score_plan(good, "removed_keystone", dossier, 120)
    worse = json.loads(json.dumps(good))
    worse.pop("cold_open")
    worse["beats"][3]["event"]["text"] = worse["beats"][2]["event"]["text"]
    worse["beats"][3]["event"]["claim_refs"] = ["c3"]
    lower = sp.score_plan(worse, "removed_keystone", dossier, 120)
    assert lower["score"] < base["score"]
    assert any("cold open" in i for i in lower["issues"])
    assert any("distinct facts" in i for i in lower["issues"])


def test_approval_files_round_trip(tmp_path):
    plan = {"title": "T", "hook": "h", "cold_open": {"text": "c", "claim_refs": []},
            "beats": [_beat(1, "prior_food_web", "a", ["c1"])]}
    path = sp.write_plan_for_approval(str(tmp_path), plan, {"score": 80, "issues": []}, [{"score": 80}])
    assert os.path.isfile(path) and os.path.isfile(os.path.join(tmp_path, sp.PLAN_FILE))
    assert sp.approved_plan(str(tmp_path)) is None
    os.replace(os.path.join(tmp_path, sp.PLAN_FILE), os.path.join(tmp_path, sp.APPROVED_PLAN_FILE))
    assert sp.approved_plan(str(tmp_path))["title"] == "T"
    text = open(path, encoding="utf-8").read()
    assert "Plan score: 80/100" in text and "1. [prior_food_web] a" in text


def test_the_planner_asks_for_one_sheet_by_default():
    """Selecting among candidates on STRUCTURE while the next gate tests EVIDENCE is an own-goal.

    The three films that shipped were planned with a single sheet. After candidate selection
    landed, twelve consecutive launches failed and the spine refused a different required role
    almost every time. The mechanism stays, the default does not.
    """
    import story_planner as sp
    assert sp.PLAN_CANDIDATES_DEFAULT == 1


def test_score_plan_still_cannot_see_evidence_support():
    """Documents WHY the default is one: the scorer rewards ambition and never checks support.

    If this ever starts failing because score_plan gained an evidence term, raising the default
    again is worth revisiting.
    """
    import inspect
    import story_planner as sp
    source = inspect.getsource(sp.score_plan)
    assert "distinct_ratio" in source          # it rewards more distinct facts
    assert "validate_cascade" not in source    # and never runs the evidence cascade
