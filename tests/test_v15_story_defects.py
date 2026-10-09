"""Three defects a read-through of V14 found that no gate had caught (2026-10-08):
the opening's consequence was never spoken, the recap played twice across its two scenes, and
"Chapter one." was narrated although spoken markers are off."""
import copy

import causal_story as cs
import illustrated_story as lane
import storyboard_repair as repair
from test_illustrated_story import _script, _CHAIN


def _words(prefix, n):
    return " ".join(f"{prefix}{i:02d}word" for i in range(n))


def test_a_leaked_chapter_signpost_is_stripped_when_markers_are_off(monkeypatch):
    monkeypatch.delenv("SPOKEN_CHAPTER_MARKERS", raising=False)
    scenes = [{"scene_id": "a", "narration": "Chapter one. Out in the grove the queens breed."},
              {"scene_id": "b", "narration": "Part Two: the spread."},
              {"scene_id": "c", "narration": "Step 3 continued. Nothing else."},
              {"scene_id": "d", "narration": "The chapter of her life ended."}]
    assert cs.strip_leaked_signposts(scenes) == ["a", "b", "c"]
    assert scenes[0]["narration"] == "Out in the grove the queens breed."
    assert scenes[3]["narration"].startswith("The chapter")
    monkeypatch.setenv("SPOKEN_CHAPTER_MARKERS", "1")
    assert cs.strip_leaked_signposts([{"scene_id": "e", "narration": "Step one. Go."}]) == []


def _ladder(consequence_claims=("c06", "c07")):
    script = _script()
    script["_opening_contract"] = "ladder_v1"
    script["_opening"] = {"consequence": "a visitor lifts the screens and twenty-six queens leave",
                          "claim_refs": {"consequence": list(consequence_claims)}}
    for index, scene in enumerate(script["scenes"]):
        role, _, words = _CHAIN[index]
        if role != "hinge" and index != len(script["scenes"]) - 1:
            scene["narration"] = _words(f"s{index}", words)
    return script


def test_the_opening_consequence_must_be_spoken_before_the_mechanism():
    script = _ladder()
    errors = lane.build_storyboard(copy.deepcopy(script), "q")["validation"]["errors"]
    assert any(e.startswith("OPENING_CONSEQUENCE_UNSPOKEN") for e in errors)
    script["scenes"][2]["claim_refs"] = [{"claim_id": "c07", "narration_phrase": "x"}]
    errors = lane.build_storyboard(copy.deepcopy(script), "q")["validation"]["errors"]
    assert not any(e.startswith("OPENING_CONSEQUENCE_UNSPOKEN") for e in errors)
    late = _ladder()
    late["scenes"][5]["claim_refs"] = [{"claim_id": "c07", "narration_phrase": "x"}]   # after the mechanism
    errors = lane.build_storyboard(copy.deepcopy(late), "q")["validation"]["errors"]
    assert any(e.startswith("OPENING_CONSEQUENCE_UNSPOKEN") for e in errors)


def test_the_consequence_repair_grows_the_row_before_the_hinge():
    script = _ladder()
    board = lane.build_storyboard(copy.deepcopy(script), "q")
    assert repair.repairable_errors(board["validation"]["errors"])
    edit = repair.plan(script, board)
    assert edit["consequence_scene_id"] == "scene_003", "the false_resolution row, before the hinge"
    assert "scene_003" in edit["scene_ids"] and edit["consequence_claims"] == ["c06", "c07"]
    text = repair.prompt(script, edit)
    assert "CONSEQUENCE was never spoken" in text and "twenty-six queens" in text
    original = script["scenes"][2]["narration"]
    grown = original + " A visitor lifts the screens and twenty-six queens leave into the forest."
    candidate = repair.apply_response(script, edit, {"scenes": [{"scene_id": "scene_003", "narration": grown}]})
    assert candidate["scenes"][2]["narration"] == grown
    for bad, reason in ((original + " " + _words("x", 50), "past its allowance"),
                        (" ".join(original.split()[:4]), "shortened")):
        try:
            repair.apply_response(script, edit, {"scenes": [{"scene_id": "scene_003", "narration": bad}]})
        except ValueError as exc:
            assert reason in str(exc)
        else:
            raise AssertionError(reason)


def test_a_recap_split_across_two_scenes_is_judged_as_one_and_may_not_repeat():
    steps = [{"step_id": f"s{i}", "role": r, "situation": t, "continues": c, "index": i}
             for i, (r, t, c) in enumerate([
                 ("setup", "orchard pumps drained", ""), ("intervention", "canal water arrived", ""),
                 ("hinge", "Except the canal silted.", ""),
                 ("mechanism", "silt settled because the gradient was flat", ""),
                 ("escalation", "the meadow flooded every spring", ""),
                 ("reversal", "the wells came back", ""),
                 ("synthesis", "So trace it. Silt settled on the flat gradient, and the meadow flooded.", ""),
                 ("synthesis", "The silt settled on the gradient and the meadow flooded again.", "s6"),
                 ("tool", "look at the pumps", "")])]
    issues = []
    cs._check_synthesis(steps, issues, {"compiled_synthesis": True, "name": "e"}, 300)
    codes = {i["code"] for i in issues}
    assert "SYNTHESIS_REPEATED" in codes
    assert "SYNTHESIS_SKIPS_A_BEAT" not in codes, "the parts are judged as one text"
    steps[7]["situation"] = "One choice, the whole length of it."
    issues = []
    cs._check_synthesis(steps, issues, {"compiled_synthesis": True, "name": "e"}, 300)
    assert "SYNTHESIS_REPEATED" not in {i["code"] for i in issues}


def test_a_consequence_spoken_in_the_hinge_counts_even_when_bound_to_other_claims():
    script = _ladder()
    script["_opening"]["consequence"] = ("In October 1957 a passing beekeeper removes the queen "
                                         "excluders and 26 queens leave with small swarms into the forest.")
    script["scenes"][3]["narration"] = ("But one October day in 1957 the grids came off, and "
                                        "twenty-six queens left for the forest.")
    errors = lane.build_storyboard(copy.deepcopy(script), "q")["validation"]["errors"]
    assert not any(e.startswith("OPENING_CONSEQUENCE_UNSPOKEN") for e in errors)
    assert cs._consequence_is_spoken("the grids came off and twenty-six queens left for the forest",
                                     script["_opening"]["consequence"])
    assert not cs._consequence_is_spoken("the forest doesn't read the plan", script["_opening"]["consequence"])


def test_a_long_hinge_is_repaired_by_moving_its_facts_into_the_row_before():
    script = _ladder()
    script["scenes"][2]["claim_refs"] = [{"claim_id": "c07", "narration_phrase": "x"}]  # consequence bound
    script["scenes"][3]["narration"] = ("But one October day in 1957 the grids came off, and "
                                        "twenty-six queens left for the forest.")
    board = lane.build_storyboard(copy.deepcopy(script), "q")
    codes = {e.split(":", 1)[0] for e in board["validation"]["errors"]}
    assert "SOFT_HINGE" in codes and repair.repairable_errors(board["validation"]["errors"])
    edit = repair.plan(script, board)
    assert edit["hinge_scene_id"] == "scene_004" and edit["consequence_scene_id"] == "scene_003"
    assert {"scene_003", "scene_004"} <= set(edit["scene_ids"])
    assert "MOVES to the END" in repair.prompt(script, edit)
    prev = script["scenes"][2]["narration"]
    good = {"scenes": [
        {"scene_id": "scene_004", "narration": "Except the grids came off."},
        {"scene_id": "scene_003", "narration": prev + " One October day in 1957 a visitor lifts the "
                                               "excluders and twenty-six queens leave for the forest."}]}
    candidate = repair.apply_response(script, edit, good)
    assert candidate["scenes"][3]["narration"] == "Except the grids came off."
    bad = {"scenes": [{"scene_id": "scene_004", "narration": "Except one October day in 1957 the grids "
                                                               "came off and twenty-six queens left for the forest."},
                      {"scene_id": "scene_003", "narration": prev}]}
    try:
        repair.apply_response(script, edit, bad)
    except ValueError as exc:
        assert "hinge over its word cap" in str(exc)
    else:
        raise AssertionError("a long hinge was accepted")


# ── V15 read-through defects, caught before spend (2026-10-08) ───────────────

def _steps(*rows):
    return [{"step_id": f"s{i}", "role": r, "situation": t, "continues": c, "index": i}
            for i, (r, t, c) in enumerate(rows)]


def test_a_continuation_that_retells_its_parent_is_caught():
    steps = _steps(("escalation", "By 2005 these bees turned up in Florida, far from any marching "
                                  "front, riding in on trucks and ships.", ""),
                   ("escalation", "By 2005 the hybrid turned up in Florida, far from the marching "
                                  "front. Trucks and ships carried it in.", "s0"))
    issues = []
    cs._check_continuation_repeats(steps, issues)
    assert [i["code"] for i in issues] == ["CONTINUATION_REPEATS"]
    steps[1]["situation"] = "Within a decade the colonies there were indistinguishable from the rest."
    issues = []
    cs._check_continuation_repeats(steps, issues)
    assert issues == []


def test_a_reference_to_something_never_named_is_caught_and_an_earlier_one_is_not():
    steps = _steps(("escalation", "One slow march that no fence or border could hold.", ""),
                   ("escalation", "That wall held for years.", ""))
    issues = []
    cs._check_dangling_reference(steps, issues)
    assert [i["code"] for i in issues] == ["DANGLING_REFERENCE"]
    steps = _steps(("setup", "The calm temper of the European bees.", ""),
                   ("escalation", "The hybrids kept a fierce streak.", ""),
                   ("escalation", "That temper travels with them.", ""))
    issues = []
    cs._check_dangling_reference(steps, issues)
    assert issues == [], "a noun the film named earlier may be pointed back at"


def test_a_close_cannot_assume_an_outcome_the_reversal_never_told():
    steps = _steps(("reversal", "The gentle European hives were gone.", ""),
                   ("tool", "If the fix finally filled the harvest, was it worth it?", ""))
    issues = []
    cs._check_close_presupposes_outcome(steps, issues)
    assert [i["code"] for i in issues] == ["CLOSE_PRESUPPOSES_OUTCOME"]
    steps[0]["situation"] = "Brazil's harvest filled again once keepers adapted."
    issues = []
    cs._check_close_presupposes_outcome(steps, issues)
    assert issues == []


def test_all_three_are_repairable_and_name_their_scenes():
    for code in ("CONTINUATION_REPEATS", "DANGLING_REFERENCE", "CLOSE_PRESUPPOSES_OUTCOME"):
        assert code in repair.REPAIRABLE
    assert "CLOSE_PRESUPPOSES_OUTCOME" in repair.CLOSE_CODES
