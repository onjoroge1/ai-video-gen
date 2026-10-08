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
