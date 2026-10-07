"""The human-first opening (operator brief, 2026-10-07): planned as beats, scored as a frame,
stamped on the script, and the shorts-fitted opening gates demoted to warnings for it."""
import causal_story as cs
import explainer_pipeline as ep
import hook_patterns as hp
import story_compiler as sc
import story_engines as se


def test_the_planner_asks_for_an_opening_under_the_ladder_and_a_cold_open_under_the_hook():
    ladder = sc.factual_plan_prompt("q", 300, 20, "removed_keystone", opening_mode="ladder")
    assert "THE OPENING." in ladder and '"opening": {' in ladder and "THE BODY BEGINS AFTER THE CONSEQUENCE" in ladder
    assert "COLD OPEN: besides the hook" not in ladder and '"cold_open"' not in ladder
    hook = sc.factual_plan_prompt("q", 300, 20, "removed_keystone", opening_mode="hook")
    assert "COLD OPEN: besides the hook" in hook and '"cold_open"' in hook and "THE OPENING." not in hook
    assert "Do not supply a hinge, mechanism, synthesis, tool" in ladder, "the compiler-owned devices are unchanged"


def test_plan_opening_normalises_and_needs_a_consequence():
    plan = {"opening": {"frame": "Imagine you're a beekeeper in Brazil.", "problem": "p", "solution": "s",
                        "transition": "t", "consequence": "c", "callback": {"kind": "need", "text": "a harvest"},
                        "claim_refs": {"problem": ["c39"], "consequence": ["cX5", ""]},
                        "missing_claims": ["why the visitor lifted the screens"]}}
    o = ep._plan_opening(plan)
    assert o["frame"].startswith("Imagine") and o["callback"] == {"kind": "need", "text": "a harvest"}
    assert o["claim_refs"]["consequence"] == ["cX5"] and o["missing_claims"] == ["why the visitor lifted the screens"]
    assert ep._plan_opening({"opening": {"frame": "x"}}) == {}
    assert ep._plan_opening({"hook": "x"}) == {}


def test_a_frame_is_scored_on_the_three_devices_it_can_carry():
    frame = hp.score_hook("Imagine you're a beekeeper in Brazil.", ladder=True)
    assert frame["score"] == 100 and not any("quantity" in n for n in frame["notes"])
    full = hp.score_hook("Imagine you're a beekeeper in Brazil.")
    assert full["score"] < frame["score"], "the full scorer docks the missing number; the frame scorer does not"
    hp.register_people({"claims": [{"claim_id": "c1", "claim": "Warwick Kerr imported the bees."}]})
    kerr = hp.score_hook("You watch Warwick Kerr bring African bees to Brazil.", ladder=True)
    assert kerr["score"] < 70 and not kerr["patterns"]["no_institution"]
    hp.register_people({"claims": []})


def _steps():
    rows = [("setup", "European bees struggled in Brazil."), ("intervention", "Kerr brought African queens."),
            ("hinge", "Except the queens did not stay."), ("mechanism", "Queens escaped and hybridized."),
            ("escalation", "Colonies grew and swarmed."), ("escalation", "Bees reached Arizona."),
            ("reversal", "Beekeeping shifted to Africanized bees."), ("tool", "Ask what else escaped the plan.")]
    return [{"step_id": f"s{i}", "role": r, "situation": t, "chapter": 1 + i // 2,
             "caused_by": f"s{i - 1}" if i else "", "start_sec": i * 40.0}   # mechanism at 120 s of 300
            for i, (r, t) in enumerate(rows)]


def test_the_shorts_fitted_gates_are_warnings_under_the_ladder():
    payload = {"runtime_sec": 300.0, "steps": _steps(), "opening_object": "the honey jars",
               "start_state": "low honey", "hook": {"line": " ".join(["word"] * 24), "cold_open": "",
                                                    "require_cold_open": True}}
    before = cs.validate_causal_story(payload, se.get("removed_keystone"))
    codes = {i["code"] for i in before["errors"]}
    assert {"LATE_MECHANISM", "LONG_HOOK", "COLD_OPEN_MISSING", "NO_CALLBACK"} <= codes
    after = cs.validate_causal_story(dict(payload, opening_contract=cs.OPENING_CONTRACT), se.get("removed_keystone"))
    errors = {i["code"] for i in after["errors"]}
    warnings = {i["code"] for i in after["warnings"]}
    assert not (cs.LADDER_ADVISORY_CODES & errors)
    assert {"LATE_MECHANISM", "LONG_HOOK", "COLD_OPEN_MISSING", "NO_CALLBACK"} <= warnings
    assert after["passed"], "nothing else was wrong with this chain"


def test_the_storyboard_carries_the_stamp_to_the_validator(monkeypatch):
    import copy
    import illustrated_story as lane
    from test_illustrated_story import _script
    seen = {}
    real = cs.validate_causal_story
    def spy(payload, engine=None):
        seen["opening_contract"] = payload.get("opening_contract")
        return real(payload, engine)
    monkeypatch.setattr(cs, "validate_causal_story", spy)
    script = _script(); script["_opening_contract"] = cs.OPENING_CONTRACT
    lane.build_storyboard(copy.deepcopy(script), "q")
    assert seen["opening_contract"] == cs.OPENING_CONTRACT
    lane.build_storyboard(copy.deepcopy(_script()), "q")
    assert seen["opening_contract"] == ""


def test_the_planner_prompt_has_one_definition_of_the_hook_field(monkeypatch):
    """V11 and V12 (2026-10-07): the causal rules defined the hook as a named actor causing the
    disaster, beside THE OPENING defining it as a frame; the planner returned the actor sentence."""
    from test_causal_lane_integration import _capture_beat_prompt
    monkeypatch.setenv("OPENING_MODE", "ladder")
    prompt = _capture_beat_prompt(monkeypatch, causal_lane=True)
    assert "whose SUBJECT is a named actor" not in prompt
    assert "the FRAME that opens the film" in prompt and "NOT a summary of the story" in prompt
    assert "THE OPENING." in prompt
    monkeypatch.setenv("OPENING_MODE", "hook")
    prompt = _capture_beat_prompt(monkeypatch, causal_lane=True)
    assert "THE OPENING." not in prompt and "the FRAME that opens the film" not in prompt
