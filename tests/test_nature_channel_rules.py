"""Nature-channel rules apply only on the Nature channel; the history/world lane is unchanged.

Measured on the first emperor penguin long-form (job 59d6106d, 2026-09-24): the lead tag
"explained like you are five" was spoken, 24 of 43 image states required anonymous people (so
researchers stood beside the penguins and people assembled the huddle), the thumbnail said
"65 DAYS" over a narration that says "seven, eight weeks", and a 67/100 script rendered anyway.
"""
import explainer_pipeline as ep
import longform_evidence as le
import nature_channel as nc


def _script(channel, sheet=""):
    return {"_topic_channel": channel, "_subject_sheet": sheet,
            "_story_contract": {"opening_object": "one egg", "final_callback_object": "one egg"},
            "scenes": [{"narration": "a", "continuity_anchor": "sea ice"},
                       {"narration": "b"}]}


def _state(channel, purpose="action", sheet=""):
    pack = le.build_continuity_pack(_script(channel, sheet))
    beat = {"purpose": purpose, "state_after": "the males press into a huddle",
            "anchor_phrase": "press together"}
    return pack, le._state_from_beat({}, beat, 1, 0, pack, opening=False)


def test_format_tag_is_silent_only_on_nature():
    assert nc.format_tag("nature", ep._CAUSAL_FORMAT_TAG) == ""
    assert nc.format_tag("history", ep._CAUSAL_FORMAT_TAG) == ep._CAUSAL_FORMAT_TAG
    assert nc.format_tag("", ep._CAUSAL_FORMAT_TAG) == ep._CAUSAL_FORMAT_TAG


def test_nature_states_carry_no_people_and_forbid_them():
    pack, state = _state("nature", sheet="Adult: black back, white front.")
    assert pack["channel"] == "nature"
    assert pack["subject_sheet"] == "Adult: black back, white front."
    assert state["anonymous_people_required"] is False
    assert state["include_human"] is False
    assert state["include_bolt"] is False
    assert nc.FORBIDDEN_PEOPLE in state["forbidden_objects"]


def test_history_states_are_unchanged():
    pack, state = _state("history")
    assert pack["channel"] == "history"
    assert state["anonymous_people_required"] is True
    assert nc.FORBIDDEN_PEOPLE not in state["forbidden_objects"]
    _, state = _state("")
    assert state["anonymous_people_required"] is True


def test_evidence_prompt_cast_clause_swaps_only_on_nature():
    pack, state = _state("nature", sheet="Adult: black back, white front.")
    prompt = ep._evidence_state_prompt({}, state, pack, "style")
    assert "NO PEOPLE ANYWHERE IN FRAME" in prompt
    assert "SUBJECT SHEET" in prompt and "black back" in prompt
    assert "period-correct" not in prompt
    pack, state = _state("history")
    prompt = ep._evidence_state_prompt({}, state, pack, "style")
    assert "PERIOD-CORRECT PERSON" in prompt
    assert "NO PEOPLE ANYWHERE" not in prompt


def test_thumbnail_numbers_must_be_spoken():
    narration = "Roughly seven, eight weeks she stays out there. She vanishes for two months."
    assert nc.headline_numbers_supported("DAD CAN'T MOVE 65 DAYS", narration) is False
    assert nc.headline_numbers_supported("GONE 2 MONTHS", narration) is True
    assert nc.headline_numbers_supported("GONE TWO MONTHS", narration) is True
    assert nc.headline_numbers_supported("SHE JUST LEAVES", narration) is True
    assert nc.headline_numbers_supported("8 WEEKS ALONE", narration) is True


def test_script_floor_is_hard_only_on_nature():
    assert nc.script_floor_is_hard("nature") is True
    assert nc.script_floor_is_hard("history") is False
    assert nc.script_floor_is_hard("") is False


def test_subject_sheet_text_flattens_the_designer_json():
    text = nc.subject_sheet_text({"adult": "Black back, white front, orange ear patches.",
                                  "egg_or_newborn": "", "young": "Grey down, black cap",
                                  "never": "No arms; flippers only"})
    assert text == ("Adult: Black back, white front, orange ear patches. Young: Grey down, black "
                    "cap. Never draw: No arms; flippers only.")
    assert nc.subject_sheet_text(None) == ""


def test_stop_after_script_is_a_request_field_and_a_distinct_stop():
    import app
    req = app.ExplainerRequest(question="q")
    assert req.stop_after_script is False
    assert app.ExplainerRequest(question="q", stop_after_script=True).stop_after_script is True
    assert issubclass(ep.ScriptApprovalRequired, RuntimeError)


def test_nature_callback_sits_at_the_head_of_the_closing_scene():
    """The exact-reuse callback stays, but the last shot is the scene's own final state."""
    import copy
    script = _script("nature")
    script["scenes"] = [
        {"narration": "One egg sits on his feet. She walks away.", "continuity_anchor": "sea ice",
         "story_role": "opening",
         "visual_beats": [{"purpose": "setup", "state_after": "egg on feet",
                             "anchor_phrase": "One egg sits on his feet"},
                            {"purpose": "consequence", "state_after": "she walks away",
                             "anchor_phrase": "She walks away"}]},
        {"narration": "Look again at that egg. Now the chick is fed.", "story_role": "final_payoff",
         "visual_beats": [{"purpose": "setup", "state_after": "the egg again",
                             "anchor_phrase": "Look again at that egg"},
                            {"purpose": "consequence", "state_after": "the chick is fed",
                             "anchor_phrase": "Now the chick is fed"}]},
    ]
    history = copy.deepcopy(script)
    history["_topic_channel"] = "history"
    nature_plan = le.compile_evidence_plan(script, {0: 12.0, 1: 12.0})
    history_plan = le.compile_evidence_plan(history, {0: 12.0, 1: 12.0})
    nature_last = nature_plan["scenes"][-1]["states"]
    history_last = history_plan["scenes"][-1]["states"]
    assert nature_last[0]["purpose"] == "callback"
    assert nature_last[0]["asset_strategy"] == "exact_reuse"
    assert nature_last[0]["anchor_phrase"] == "Look again at that egg"
    assert nature_last[-1]["purpose"] != "callback"
    assert nature_last[-1]["state_after"] == "the chick is fed"
    assert history_last[-1]["purpose"] == "callback"


def test_writing_contract_rides_with_the_operator_block_only_on_nature():
    token = ep._TOPIC_CHANNEL.set("nature")
    try:
        assert "NATURE CHANNEL WRITING CONTRACT" in ep._operator_block("")
        both = ep._operator_block("keep it short")
        assert "NATURE CHANNEL WRITING CONTRACT" in both and "keep it short" in both
        assert both.index("WRITING CONTRACT") < both.index("OPERATOR DIRECTION")
    finally:
        ep._TOPIC_CHANNEL.reset(token)
    token = ep._TOPIC_CHANNEL.set("history")
    try:
        assert ep._operator_block("") == ""
        assert "WRITING CONTRACT" not in ep._operator_block("keep it short")
    finally:
        ep._TOPIC_CHANNEL.reset(token)


def test_an_establishing_state_with_identical_before_and_after_is_repaired():
    """Job 60b97bcf (2026-09-25): 'whole intact ice sheet' on both sides of a master shot."""
    script = _script("history")
    script["scenes"] = [
        {"narration": "The egg sits on his feet. She walks away.", "continuity_anchor": "sea ice",
         "visual_beats": [{"purpose": "setup", "state_before": "egg on feet",
                           "state_after": "egg on feet", "anchor_phrase": "The egg sits on his feet"},
                          {"purpose": "consequence", "state_before": "egg on feet",
                           "state_after": "she walks away", "anchor_phrase": "She walks away"}]},
        {"narration": "Solid ice holds them. It breaks.", "story_role": "final_payoff",
         "visual_beats": [{"purpose": "setup", "state_before": "solid ice",
                           "state_after": "solid ice", "anchor_phrase": "Solid ice holds them"},
                          {"purpose": "consequence", "state_before": "solid ice",
                           "state_after": "broken ice", "anchor_phrase": "It breaks"}]},
    ]
    plan = le.compile_evidence_plan(script, {0: 12.0, 1: 12.0})
    first = plan["scenes"][0]["states"][0]
    later = plan["scenes"][1]["states"][0]
    assert first["state_before"] == "not yet shown: egg on feet"
    assert later["state_before"] == "she walks away"
    assert [r["code"] for r in plan["repairs"]].count("unchanged_evidence_state_repaired") == 2
    assert le.validate_evidence_plan(plan)["passed"] is True


def test_a_scene_too_short_for_one_image_holds_the_previous_image():
    """Job c96cb9dc (2026-09-25): the four-word hinge measured 1.10s and the render refused."""
    import longform_shots as ls
    script = _script("nature")
    script["scenes"] = [
        {"narration": "She leaves her only egg with Dad and heads to sea.", "continuity_anchor": "ice",
         "visual_beats": [{"purpose": "setup", "state_before": "egg handed over",
                           "state_after": "egg on his feet", "anchor_phrase": "She leaves her only egg"},
                          {"purpose": "consequence", "state_before": "egg on his feet",
                           "state_after": "she walks to the sea", "anchor_phrase": "heads to sea"}]},
        {"narration": "There is no nest.",
         "visual_beats": [{"purpose": "setup", "state_before": "bare ice",
                           "state_after": "bare ice, no nest", "anchor_phrase": "There is no nest"}]},
        {"narration": "So he keeps the egg warm beneath a fold of skin.", "story_role": "final_payoff",
         "visual_beats": [{"purpose": "consequence", "state_before": "egg on feet",
                           "state_after": "egg under the fold", "anchor_phrase": "keeps the egg warm"},
                          {"purpose": "consequence", "state_before": "egg under the fold",
                           "state_after": "the chick is fed", "anchor_phrase": "fold of skin"}]},
    ]
    plan = le.compile_evidence_plan(script, {0: 6.0, 1: 1.1, 2: 8.0})
    short = plan["scenes"][1]["states"]
    assert len(short) == 1
    assert short[0]["asset_strategy"] == "exact_reuse"
    assert short[0]["source_asset_id"] == plan["scenes"][0]["states"][-1]["asset_id"]
    assert short[0]["anchor_phrase"] == "There is no nest."
    assert any(r["code"] == "short_scene_holds_previous_image" for r in plan["repairs"])
    assert le.validate_evidence_plan(plan)["passed"] is True
    shots = ls.compile_scene_shots(
        script["scenes"][1], 1.1, 1, evidence_states=[dict(short[0], asset_status="reused_exact")],
        require_measured_timing=False)
    assert len(shots) == 1


def test_a_required_object_that_is_also_forbidden_exposed_is_dropped():
    """Job 45711ddf (2026-09-25): 'warm-coral egg' required, 'exposed egg' forbidden, rejected."""
    script = _script("nature")
    script["scenes"] = [
        {"narration": "He holds the egg on his feet, under that brood pouch.", "continuity_anchor": "ice",
         "visual_beats": [{"purpose": "setup", "state_before": "egg on feet",
                           "state_after": "egg on feet", "anchor_phrase": "He holds the egg",
                           "required_objects": ["male emperor penguin", "egg on feet"]},
                          {"purpose": "evidence", "state_before": "egg on feet",
                           "state_after": "pouch clearly covering egg",
                           "anchor_phrase": "under that brood pouch",
                           "required_objects": ["brood pouch over egg", "warm-coral egg"],
                           "forbidden_objects": ["exposed egg"]}]},
        {"narration": "She came back with dinner.", "story_role": "final_payoff",
         "visual_beats": [{"purpose": "consequence", "state_before": "chick waits",
                           "state_after": "chick fed", "anchor_phrase": "came back with dinner"},
                          {"purpose": "consequence", "state_before": "chick fed",
                           "state_after": "both parents", "anchor_phrase": "dinner"}]},
    ]
    plan = le.compile_evidence_plan(script, {0: 8.0, 1: 8.0})
    state = plan["scenes"][0]["states"][1]
    assert state["required_objects"] == ["brood pouch over egg"]
    assert any(r["code"] == "required_object_conflicts_with_forbidden" for r in plan["repairs"])
