import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import short_from_engine as sfe  # noqa: E402

LINES = ["This ant is going to die biting a leaf.", "And it's walking there by itself."]


def _plan():
    return [{"pictures": [{"image": "a carpenter ant on a leaf", "motion": "it walks"}]},
            {"pictures": [{"image": "a carpenter ant walking"}, {"from": "itself.", "image": "a carpenter ant alone"}]}]


def test_check_plan_accepts_cue_words_in_order_with_punctuation():
    assert sfe.check_plan(LINES, _plan()) == []


def test_check_plan_rejects_missing_cue_and_absence_prompt_and_no_motion():
    plan = _plan()
    plan[0]["pictures"][0].pop("motion")
    plan[1]["pictures"][1]["from"] = "running"
    plan[1]["pictures"][0]["image"] = "an empty branch, no ants"
    errors = sfe.check_plan(LINES, plan)
    assert any("running" in e for e in errors)
    assert any("absence" in e for e in errors)
    assert any("motion" in e for e in errors)


def test_review_problems_lists_flags_and_unknown_version():
    assert sfe.review_problems({"handoff_version": 2})[0].startswith("unknown handoff_version")
    h = {"handoff_version": 1, "review_needed": True, "review_reasons": ["1 claims not fully supported"],
         "flagged_facts": [{"n": 3, "claim": "noon", "status": "partly supported"}]}
    assert len(sfe.review_problems(h)) == 2
    assert sfe.review_problems({"handoff_version": 1, "review_needed": False}) == []


def test_to_spec_sets_hold_tags_and_keeps_engine_provenance():
    h = {"title": "T", "lines": LINES, "run_id": "r1", "files": {"facts": "/x/facts.md"}}
    plan = {"setting": "a rainforest.", "headline": "ZOMBIE|ANT", "tags": ["ants", "shorts", "fungus"],
            "description": "d", "lines": _plan()}
    spec = sfe.to_spec(h, plan)
    assert spec["open_hold_sec"] == 3.0 and spec["tags"] == ["ants", "fungus", "shorts"]
    assert spec["style"].endswith("a rainforest.") and spec["script_engine"]["facts"] == "/x/facts.md"
    assert [b["text"] for b in spec["beats"]] == LINES


def test_check_plan_wants_one_picture_in_held_line_1_and_enough_pictures_later():
    plan = _plan()
    plan[0]["pictures"].append({"from": "biting", "image": "a carpenter ant biting a leaf"})
    long_line = "Its spores rain onto the forest floor, where the next ants walk, day after day after day."
    plan[1] = {"pictures": [{"image": "a carpenter ant stalk shedding spores"}]}
    errors = sfe.check_plan([LINES[0], long_line], plan)
    assert any(e.startswith("line 1:") for e in errors)
    assert any(e.startswith("line 2:") and "needs" in e for e in errors)
