"""The witness opening (OPENING_HOOK=witness) and the recap switch (SYNTHESIS_DEVICE=off).

Witness is the myth opening with the scale carried by the bust and one documented person's moment
in place of the one-sentence danger. Everything else the myth mode does still applies.
"""
import causal_story as cs
import hook_patterns as hp
import story_compiler as sc
import story_engines


def test_witness_is_a_myth_variant_and_myth_is_not_witness(monkeypatch):
    monkeypatch.setenv("OPENING_HOOK", "witness")
    assert hp.myth_mode() and hp.witness_mode()
    # the myth line still counts as the frame
    assert hp.frame_names_role("You'd think four hippos would simply die out.")
    assert hp.frame_rules() == hp.MYTH_FRAME_RULES
    monkeypatch.setenv("OPENING_HOOK", "myth")
    assert hp.myth_mode() and not hp.witness_mode()
    monkeypatch.delenv("OPENING_HOOK", raising=False)
    assert not hp.myth_mode() and not hp.witness_mode()


def test_witness_rules_replace_the_danger_and_lengthen_the_lead(monkeypatch):
    monkeypatch.setenv("OPENING_HOOK", "witness")
    planner = hp.opening_rules()
    assert "WITNESS OPENING" in planner and "MYTH-BUSTER OPENING" not in planner
    assert "Never invent a name" in planner and "told ONCE" in planner
    assert "never 'people believe'" in planner
    writer = hp.opening_writer_rules()
    assert "forty-five words" in writer and "twenty-five words" not in writer
    assert "no sentence begins 'Picture'" in writer
    body = hp.opening_body_rule()
    assert "ANSWERS the opening's question" in body, "the myth body rule still applies"
    assert "no body scene re-tells it" in body and "returns to the witness" in body
    turn = hp.opening_writer_rules(turn_rule=True, shape="A")
    assert hp.TURN_WITNESS_RULE in turn and hp.TURN_MYTH_RULE not in turn


def test_myth_and_ladder_rules_are_unchanged(monkeypatch):
    monkeypatch.setenv("OPENING_HOOK", "myth")
    assert "MYTH-BUSTER OPENING" in hp.opening_rules() and "WITNESS" not in hp.opening_rules()
    assert "twenty-five words" in hp.opening_writer_rules()
    assert "WITNESS" not in hp.opening_body_rule()
    assert hp.TURN_MYTH_RULE in hp.opening_writer_rules(turn_rule=True, shape="A")
    monkeypatch.delenv("OPENING_HOOK", raising=False)
    assert hp.opening_rules() == hp.OPENING_RULES
    assert hp.opening_writer_rules() == hp.OPENING_WRITER_RULES
    assert hp.opening_body_rule() == hp.OPENING_BODY_RULE


def test_the_planner_prompt_carries_the_witness_rules(monkeypatch):
    monkeypatch.delenv("OPENING_MODE", raising=False)
    monkeypatch.setenv("OPENING_HOOK", "witness")
    prompt = sc.factual_plan_prompt("q", 300, 60, "backfiring_solution", opening_mode="ladder")
    assert "WITNESS OPENING" in prompt and "forty seconds" in prompt


def test_witness_defects_catch_what_the_hippo_writer_did():
    import script_editor as se
    script = {"scenes": [
        {"causal_role": "setup", "narration": "You'd think four hippos would die out. They didn't."},
        {"causal_role": "intervention", "beat_id": "event_02",
         "narration": "So picture the fallout. Imagine you fish the Magdalena near the old estate."},
        {"causal_role": "escalation", "beat_id": "event_10",
         "narration": "Hippos turned up far down the Magdalena River basin, sixty miles from the old ranch, "
                      "and more than sixty miles north of it."},
        {"causal_role": "escalation", "beat_id": "event_10:2", "continues": "event_10",
         "narration": "Hippos turned up more than sixty miles north of the old ranch, and up to sixty miles "
                      "from it in the Magdalena River basin."},
        {"causal_role": "escalation", "narration": "Picture a slow manatee drifting where the water ran clean."},
        {"causal_role": "tool", "narration": "So trace the whole chain back. Four hippos were left behind. "
                                             "What stops them? Nothing stopped these."}]}
    found = {(d["scene"], d["code"]) for d in se.detect_witness_defects(script)}
    assert (5, se.FILLER) in found, "a 'Picture' line in the body"
    assert (6, se.CLOSE_RECAP) in found, "a recapping close"
    assert (4, se.REPEAT) in found, "a continuation that re-tells its own beat"
    assert not any(scene == 2 for scene, _ in found), "the role frame in the opening rows is allowed"
    assert all(d.get("witness") for d in se.detect_witness_defects(script))


def test_the_storyboard_contract_honours_the_synthesis_switch(monkeypatch):
    engine = dict(next(e for e in story_engines.ENGINES.values()
                       if cs.SYNTHESIS in (e.get("sequence") or ())), compiled_synthesis=True)
    monkeypatch.delenv("SYNTHESIS_DEVICE", raising=False)
    issues = []
    cs._check_synthesis([{"role": "escalation", "situation": "x"}], issues, engine, 300)
    assert any(i["code"] == "SYNTHESIS_MISSING" for i in issues)
    monkeypatch.setenv("SYNTHESIS_DEVICE", "off")
    issues = []
    cs._check_synthesis([{"role": "escalation", "situation": "x"}], issues, engine, 300)
    assert not any(i["code"] == "SYNTHESIS_MISSING" for i in issues)


def test_synthesis_can_be_switched_off(monkeypatch):
    engine = next(e for e in story_engines.ENGINES.values() if cs.SYNTHESIS in (e.get("sequence") or ()))
    monkeypatch.delenv("SYNTHESIS_DEVICE", raising=False)
    assert cs.synthesis_planned(engine, 300)
    monkeypatch.setenv("SYNTHESIS_DEVICE", "off")
    assert not cs.synthesis_planned(engine, 300)
    monkeypatch.setenv("SYNTHESIS_DEVICE", "on")
    assert cs.synthesis_planned(engine, 300)
