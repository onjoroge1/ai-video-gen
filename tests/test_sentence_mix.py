"""Joints and sentence mix are measured, not requested (change #8, 2026-10-06).

A 552 s reference explainer opens 8 of 14 sections on a gap or a consequence and keeps one
sentence in three interpretive or addressed to the viewer; the delivered killer bees V8 opened
1 of 15 scenes that way and ran 21 fact sentences in a row. The bands sit between the two, the
storyboard mints them as codes, and the pipeline's bounded edit owns them.
"""
import causal_story as cs
import explainer_pipeline as ep
import hook_patterns
import story_engine

REFERENCE_JOINTS = [
    "But airflow alone doesn't explain the most comfortable spaces in these homes.",
    "Not quite, because a sealed, shaded, thick walled box creates a new problem.",
    "Even the thickest wall has a weakness.",
    "So, the ancient Egyptians did something that seems, at first, completely backward.",
    "Here's the part almost no one expects.",
    "And there was one more layer, subtle, almost invisible, but genuinely powerful, water.",
    "How?",
]
V8_OPENINGS = [
    "In 1956, Brazilian geneticist Warwick Kerr brought African honey bees to the Americas.",
    "Queens and drones escaped the managed setting, so their genes met bees already living there.",
    "When disturbed, Africanized honey bees respond more rapidly and more intensely.",
    "Africanized bees were detected in Arizona in 1993.",
]


def test_the_joint_regex_recognises_the_reference_joints_and_not_v8s_openings():
    for line in REFERENCE_JOINTS:
        assert cs.is_joint(line)[0], line
    for line in V8_OPENINGS:
        assert not cs.is_joint(line)[0], line


def test_a_hinge_joint_is_never_a_question():
    assert not cs.is_joint("Was the fix really working?", role=cs.HINGE)[0]
    assert cs.is_joint("Except the bees did not stay in their boxes.", role=cs.HINGE)[0]
    assert cs.is_joint("Was the fix really working?", role=cs.ESCALATION) == (True, "question")


def test_step_continued_is_one_marker_and_the_opening_survives():
    body = cs._MARKER.sub("", "Step three continued. At its northern peak, the spread advanced.")
    assert body.startswith("At its northern peak")
    assert cs.scene_opening("continued. At its northern peak, the spread advanced.") == \
        "At its northern peak, the spread advanced."


def _v8_like(n_scenes=14):
    scenes = ["Your hive could face twenty-six escaped queens. European bees struggled in Brazil."]
    scenes += [f"In 19{50 + i}, the bees were detected in a new state. Colonies grew and swarmed."
               for i in range(n_scenes - 1)]
    return scenes


def _reference_like():
    scenes = ["You wake up and the air is already trying to kill you. It will hit fifty degrees."]
    for i in range(13):
        opener = ["But that alone does not explain what came next.", "So the walls grew thicker.",
                  "Not quite.", "Even the thickest wall has a weakness."][i % 4]
        scenes.append(f"{opener} The builders packed mud and straw into bricks. "
                      "Imagine your hand on that wall at noon: it is cool to the touch.")
    return scenes


def test_v8_shape_fails_exactly_the_four_bands_and_a_reference_shape_passes():
    codes = [i["code"] for i in cs.sentence_mix_issues(_v8_like())]
    assert codes == ["JOINT_BAND", "ADDRESS_BAND", "MIX_BAND", "FACT_RUN"]
    assert cs.sentence_mix_issues(_reference_like()) == []
    # Fewer than four scenes: nothing is measured, nothing fails.
    assert cs.sentence_mix_issues(_v8_like(3)) == []


def test_a_continuation_scene_is_not_an_opening():
    scenes = _v8_like(6)
    conts = ["", "", "beat_01", "", "", ""]
    mix = cs.measure_sentence_mix(scenes, continues=conts)
    assert mix["openings"] == 4 and 3 not in mix["bare_openings"]


def test_grade_fails_on_the_blocking_bands_only_when_scenes_are_supplied():
    payload = {"runtime_sec": 300.0, "steps": [], "hook": {"line": "Your hive could face trouble."}}
    without = cs.grade(payload, " ".join(_v8_like()))
    assert without["sentence_mix_measured"] is False and without["failed_bands"] == []
    with_scenes = cs.grade(payload, "", scenes=_v8_like())
    assert with_scenes["sentence_mix_measured"] is True
    assert {m["metric"] for m in with_scenes["failed_bands"]} == cs.BLOCKING_BANDS
    assert with_scenes["passed"] is False


def test_the_second_person_regex_is_one_object():
    assert story_engine._SECOND_PERSON is cs.SECOND_PERSON
    assert hook_patterns._SECOND_PERSON is cs.SECOND_PERSON
    assert cs.classify_sentence("Picture your hive with the grid lifted off.") == "address"
    assert cs.classify_sentence("It seemed like the obvious fix.") == "interpretive"
    assert cs.classify_sentence("In 1957 it seemed to work.") == "fact"
    assert cs.classify_sentence("Twenty-six queens left the apiary.") == "fact"


def test_the_mix_codes_are_bounded_edits_not_replans():
    passed = {"passed": True, "score": 80, "errors": []}
    mix = ["JOINT_BAND: 1 of 15 scene openings join", "FACT_RUN: 21 fact sentences in a row"]
    assert ep._only_repairable_timing_blocks(passed, mix)
    assert ep._only_repairable_timing_blocks(passed, mix + ["LATE_MECHANISM: at 62s"])
    assert not ep._only_repairable_timing_blocks(passed, mix + ["NO_HINGE: none"])


def _scenes_for_edit():
    return [
        {"beat_id": "event_01", "causal_role": "setup", "narration": "Your hive could face queens. Bees struggled.",
         "event": {"text": "European bees struggled in Brazil.", "claim_refs": ["c01"]}, "claim_refs": []},
        {"beat_id": "event_02", "causal_role": "intervention",
         "narration": "In 1956 Kerr brought African queens to Brazil for honey.",
         "event": {"text": "In 1956 Kerr brought African queens to Brazil.", "claim_refs": ["c02"]},
         "claim_refs": [{"claim_id": "c02", "narration_phrase": "brought African queens to Brazil"}]},
        {"beat_id": "event_03", "causal_role": "escalation", "narration": "Colonies grew and swarmed.",
         "event": {"text": "Colonies grew and swarmed more often.", "claim_refs": ["c03"]}, "claim_refs": []},
        {"beat_id": "event_04", "causal_role": "escalation", "narration": "Bees were detected in Arizona in 1993.",
         "event": {"text": "Bees were detected in Arizona in 1993.", "claim_refs": ["c04"]}, "claim_refs": []},
    ]


DOSSIER = {"claims": [{"claim_id": f"c0{i}", "claim": t} for i, t in enumerate([
    "European bees struggled in Brazil.", "In 1956 Kerr brought African queens to Brazil.",
    "Colonies grew and swarmed more often.", "Bees were detected in Arizona in 1993."], 1)]}


class _FakeClaude:
    def __init__(self, reply):
        self.reply, self.calls = reply, 0
        outer = self

        class _Messages:
            def create(self, **kwargs):
                outer.calls += 1
                outer.last = kwargs
                return type("R", (), {"content": [type("C", (), {"text": outer.reply})()],
                                      "usage": type("U", (), {"input_tokens": 1000, "output_tokens": 200})()})()
        self.messages = _Messages()


def test_the_bounded_edit_keeps_sourced_rewrites_and_holds_the_rest(monkeypatch):
    import json
    reply = json.dumps({"scenes": [
        # 2: joint added, sourced phrase kept -> kept
        {"id": 2, "narration": "So in 1956 Kerr brought African queens to Brazil for honey."},
        # 3: joint added but a new fact (a place) -> held by the judge
        {"id": 3, "narration": "But the colonies in Texas grew and swarmed."},
        # 4: sourced phrase fine, but 30 words over the cap -> held
        {"id": 4, "narration": "Not quite. " + "Bees were detected in Arizona in 1993. " * 6},
    ]})
    fake = _FakeClaude(reply)
    monkeypatch.setattr(ep, "_claude", lambda: fake)
    monkeypatch.setattr(ep, "_msg_cost", lambda usage: 0.01)

    def judge(ceiling, narration, **_kw):
        return {"passed": "Texas" not in narration, "unsupported_details": ["Texas"] if "Texas" in narration else []}
    monkeypatch.setattr(ep, "expansion_survives_the_ledger",
                        lambda new, ceiling, **kw: (judge(ceiling, new)["passed"], judge(ceiling, new)["unsupported_details"]))
    scenes = _scenes_for_edit()
    lines = []
    out, cost, changed = ep._ensure_sentence_mix_in_band(scenes, DOSSIER, [], {}, log=lines.append)
    assert fake.calls == 1 and changed
    assert out[1]["narration"].startswith("So in 1956")
    assert out[2]["narration"] == "Colonies grew and swarmed."          # held: Texas
    assert out[3]["narration"] == "Bees were detected in Arizona in 1993."  # held: growth cap
    joined = "\n".join(lines)
    assert "1 scene(s) rewritten (2)" in joined and "2 held back" in joined
    assert "Texas" in joined and "over the +15 cap" in joined
    # Scene 1 is never sent: its lead is the hook and cold open.
    assert all(r["id"] != 1 for r in json.loads(fake.last["messages"][0]["content"].split("\n\n", 1)[1].rsplit("\n\nReturn ONLY", 1)[0]))


def test_an_in_band_script_costs_nothing(monkeypatch):
    fake = _FakeClaude("{}")
    monkeypatch.setattr(ep, "_claude", lambda: fake)
    scenes = [{"beat_id": f"e{i}", "causal_role": "escalation", "narration": n, "event": {"text": n, "claim_refs": []}, "claim_refs": []}
              for i, n in enumerate(_reference_like())]
    out, cost, changed = ep._ensure_sentence_mix_in_band(scenes, DOSSIER, [], {}, log=lambda m: None)
    assert fake.calls == 0 and cost == 0.0 and not changed


def test_the_storyboard_mints_the_codes_only_for_stamped_scripts():
    """Same scoping as require_cold_open: fixtures and old checkpoints are judged as before."""
    import copy
    import illustrated_story as lane
    from test_illustrated_story import _script
    plain = _script()
    board = lane.build_storyboard(copy.deepcopy(plain), "q")
    assert not any(e.split(":")[0] in {"JOINT_BAND", "ADDRESS_BAND", "MIX_BAND", "FACT_RUN"}
                   for e in board["validation"]["errors"])
    stamped = copy.deepcopy(plain)
    stamped["_sentence_mix_contract"] = cs.SENTENCE_MIX_CONTRACT
    board = lane.build_storyboard(stamped, "q")
    assert any(e.startswith("JOINT_BAND:") for e in board["validation"]["errors"]), board["validation"]["errors"]
