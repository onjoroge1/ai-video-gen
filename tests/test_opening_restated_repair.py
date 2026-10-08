"""OPENING_RESTATED has a bounded repair (flow validation 2026-10-07, item 8).

The check blocks a body scene that re-tells the opening's problem, decision or escape. It used to
be the one blocking storyboard code with no repair, so a single overlapping sentence after
research, planning and script spend ended the run. The repair is a trim of the named scene.
"""
import copy

import illustrated_story as lane
import storyboard_repair as repair
from test_illustrated_story import _script, _CHAIN


def _words(prefix: str, count: int) -> str:
    return " ".join(f"{prefix}{i:02d}word" for i in range(count))


SETUP = "orchard pumps drained every august leaving trees parched while farmers waited for rain"


def _ladder_script():
    """The fixture with distinct narration per scene, stamped as a ladder opening, and the
    third escalation re-telling the setup inside its own 55 words."""
    script = _script()
    script["_opening_contract"] = "ladder_v1"
    for index, scene in enumerate(script["scenes"]):
        role, _, words = _CHAIN[index]
        if role == "hinge" or index == len(script["scenes"]) - 1:
            continue
        scene["narration"] = SETUP if index == 0 else _words(f"s{index}", words)
    retold = script["scenes"][7]
    retold["narration"] = SETUP + " " + _words("again", 55 - len(SETUP.split()))
    return script


def _board(script):
    return lane.build_storyboard(copy.deepcopy(script), "q")


def test_a_retold_opening_is_the_only_error_and_is_repairable():
    script = _ladder_script()
    errors = _board(script)["validation"]["errors"]
    assert len(errors) == 1 and errors[0].startswith("OPENING_RESTATED: scene_008 re-tells the setup")
    assert repair.repairable_errors(errors)
    assert "OPENING_RESTATED" in repair.REPAIRABLE


def test_the_plan_selects_the_retold_scene_and_the_prompt_asks_for_a_trim():
    script = _ladder_script()
    edit = repair.plan(script, _board(script))
    assert edit["scene_ids"] == ["scene_008"]
    assert edit["restated"] == [{"scene_id": "scene_008", "re_tells": "setup"}]
    text = repair.prompt(script, edit)
    assert "this is a trim, not a rewrite" in text
    assert "refer back with an article or a pronoun" in text


def test_a_trim_is_accepted_and_clears_the_gate():
    script = _ladder_script()
    board = _board(script)
    edit = repair.plan(script, board)
    trimmed = "those pumps " + _words("after", 40)
    candidate = repair.apply_response(script, edit, {"scenes": [
        {"scene_id": "scene_008", "narration": trimmed}]})
    assert candidate["scenes"][7]["narration"] == trimmed
    assert _board(candidate)["validation"]["passed"]


def test_a_repair_that_grows_the_retold_scene_is_refused():
    script = _ladder_script()
    edit = repair.plan(script, _board(script))
    longer = "those pumps " + _words("after", 60)
    try:
        repair.apply_response(script, edit, {"scenes": [{"scene_id": "scene_008", "narration": longer}]})
    except ValueError as exc:
        assert "grew a restated scene" in str(exc)
    else:
        raise AssertionError("a longer restated scene was accepted")


def test_a_message_the_planner_cannot_place_is_not_a_bounded_edit():
    script = _ladder_script()
    board = _board(script)
    board["validation"]["errors"] = ["OPENING_RESTATED: scene_999 re-tells the setup (80%)"]
    assert repair.plan(script, board) is None


def _rejected_long_synthesis():
    """A first repair whose candidate re-walked every beat and ran to 98 words."""
    script = _ladder_script()
    script["scenes"][7]["narration"] = "those pumps " + _words("after", 40)   # no restatement
    candidate = copy.deepcopy(script)
    syn = {"scene_id": "scene_syn", "causal_role": "synthesis", "chapter": 4,
           "caused_by": "scene_009", "narration": "So trace it back. " + _words("recap", 96) + ".",
           "visual_beats": [{"state_after": "recap"}]}
    candidate["scenes"].insert(9, syn)
    script["scenes"].insert(9, dict(syn, narration="So trace it back. " + _words("short", 20) + "."))
    return {"status": "rejected", "rejection_code": "STORYBOARD_VALIDATION",
            "input_script": script, "candidate_script": candidate,
            "candidate_validation": {"errors": [
                "SYNTHESIS_TOO_LONG: the synthesis is 5 sentences / 98 words against 4 sentences and 70 words"]}}


def test_a_candidate_that_only_ran_long_earns_one_shorten_retry():
    saved = _rejected_long_synthesis()
    edit = repair.synthesis_length_plan(saved)
    assert edit and edit["scene_ids"] == ["scene_syn"]
    assert edit["scene_word_limits"] == {"scene_syn": 70}
    assert edit["shorten"]["current_words"] == 100 and edit["shorten"]["max_sentences"] == 5
    assert "previous rewrite" in repair.prompt(saved["candidate_script"], edit)
    for other in ({"rejection_code": "JSON_PARSE"}, {"candidate_validation": {"errors": [
            "SYNTHESIS_TOO_LONG: x", "JOINT_BAND: y"]}}):
        assert repair.synthesis_length_plan({**saved, **other}) is None


def test_the_shorten_retry_refuses_a_result_over_the_cap():
    saved = _rejected_long_synthesis()
    edit = repair.synthesis_length_plan(saved)
    candidate = saved["candidate_script"]
    long = {"scenes": [{"scene_id": "scene_syn", "narration": "So. " + _words("x", 75) + "."}]}
    try:
        repair.apply_response(candidate, edit, long)
    except ValueError as exc:
        assert "synthesis word cap" in str(exc)
    else:
        raise AssertionError("a 76-word synthesis was accepted")
    short = {"scenes": [{"scene_id": "scene_syn", "narration": "So trace it back. " + _words("y", 50) + "."}]}
    result = repair.apply_response(candidate, edit, short)
    assert result["scenes"][9]["narration"].startswith("So trace it back.")
