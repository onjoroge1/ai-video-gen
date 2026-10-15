"""The turn by 45 seconds, MEASURED (opening_turn): the read's quote and the conservative fallback
against the eight hand labels, the deletion paper test, the TTS timing and the run record."""
import copy
import json
import os
import sys

import pytest

import causal_story as cs
import explainer_pipeline as ep
import opening_turn as ot
from turn_fixture import (LABELLED, ROOT, SAVED,
                          delete_sentences as _delete,
                          script_for as _script)



# ── 1. the hand-labelled fixture ────────────────────────────────────────────────────────────

def test_the_constants_are_the_decision():
    assert ot.TURN_LIMIT_WORDS == 116 and ot.TURN_TARGET_WORDS == 103
    assert ot.WORDS_PER_SECOND == 2.588 and ot.TURN_LIMIT_SEC == 45.0
    assert ot.TURN_ENGINES == {"removed_keystone", "backfiring_solution", "state_programme"}


@pytest.mark.parametrize("job", sorted(LABELLED))
def test_the_read_quote_locates_every_hand_label_exactly(job):
    entry = SAVED[job]
    turn = ot.measure_turn(entry["scenes"], entry["opening"], entry["engine"],
                           quote=entry["label"]["quote"])
    assert turn["source"] == "quote" and turn["consequence_spoken"] is True
    assert turn["turn_words"] == entry["label"]["words"]


@pytest.mark.parametrize("job", sorted(SAVED))
def test_the_structural_fallback_never_under_measures_and_all_eight_are_late(job):
    entry = SAVED[job]
    turn = ot.measure_turn(entry["scenes"], entry["opening"], entry["engine"])
    assert turn["source"] == "fallback" and turn["late"], job
    assert turn["turn_words"] > ot.TURN_LIMIT_WORDS
    if entry["label"]["words"]:
        assert turn["turn_words"] >= entry["label"]["words"], "a fallback that under-measures lets a late film pass"


def test_the_shapes_match_the_plans():
    shapes = {job: ot.scenes_shape(e["scenes"], e["opening"], e["engine"]) for job, e in SAVED.items()}
    # The bees' consequence claims (c06-c08) are not the mechanism's (c10, c11): the hinge says it.
    assert {shapes[j] for j in ("bees_v13", "bees_v14", "bees_v15", "bees_v16")} == {"A"}
    # Carp c15/c19 and escobar c05 sit inside the mechanism event; state_programme is always B
    # (aral-v2's saved _opening had no claim_refs at all and is still B).
    assert {shapes[j] for j in ("asian-carp", "escobar-hippos", "history-aral-sea",
                                "history-aral-sea-v2")} == {"B"}


def test_v14_never_states_it_and_the_read_saying_so_is_a_finding():
    entry = SAVED["bees_v14"]
    turn = ot.measure_turn(entry["scenes"], entry["opening"], entry["engine"], quote="NONE")
    assert turn["consequence_spoken"] is False and turn["source"] == "fallback" and turn["late"]
    script = _script("bees_v14", _opening_turn=turn)
    assert ot.read_says_unspoken(script)
    script["scenes"][2]["narration"] += " Then the grids came off and the queens left."
    assert not ot.read_says_unspoken(script), "a finding on old narration does not bind new words"


def test_a_quote_outside_the_window_or_across_two_sentences_is_refused():
    entry = SAVED["bees_v16"]
    frame_quote = "Your bees are European honey bees, built for a temperate climate."
    assert ot.measure_turn(entry["scenes"], entry["opening"], entry["engine"],
                           quote=frame_quote)["source"] == "fallback"
    two = "They were contained. Except in October 1957, grids off, twenty-six queens flew free."
    assert ot.measure_turn(entry["scenes"], entry["opening"], entry["engine"], quote=two)["source"] == "fallback"
    # Punctuation, case and curly quotes are folded; the words must be verbatim.
    loose = "except in october 1957 grids off twenty six queens flew free"
    assert ot.measure_turn(entry["scenes"], entry["opening"], entry["engine"], quote=loose)["turn_words"] == 163


def test_scope():
    assert ot.rule_applies("removed_keystone", 300, "ladder")
    assert ot.rule_applies("state_programme", 225, "ladder_v1")
    assert not ot.rule_applies("removed_keystone", 224, "ladder")
    assert not ot.rule_applies("removed_keystone", 300, "hook")
    assert not ot.rule_applies("almost_happened_plan", 300, "ladder")
    assert not ot.rule_applies("strange_behaviour", 300, "ladder")
    old_checkpoint = {"_story_engine": "removed_keystone", "_opening_contract": cs.OPENING_CONTRACT,
                      "_runtime_plan": {"target_seconds": 300.0}}
    assert ot.script_rule(old_checkpoint)
    assert not ot.script_rule(dict(old_checkpoint, _turn_rule={"applies": False}))



# ── 6. the deletion paper test ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("job", ["bees_v16", "asian-carp", "history-aral-sea-v2", "escobar-hippos"])
def test_the_target_is_reachable_by_deleting_existing_sentences(job):
    entry = SAVED[job]
    deletion = entry["deletion"]
    scenes = copy.deepcopy(entry["scenes"])
    for scene in scenes:
        scene["narration"] = _delete(scene["narration"], deletion["delete"])
    turn = ot.measure_turn(scenes, entry["opening"], entry["engine"], quote=entry["label"]["quote"])
    assert turn["source"] == "quote" and turn["turn_words"] == deletion["expected_words"]
    text = " ".join(s["narration"] for s in scenes)
    assert all(sentence in text for sentence in deletion["must_keep"]), "decision, rationale, consequence"
    if job == "escobar-hippos":
        assert turn["late"], "the myth block keeps escobar over the limit: it must count inside the budget"
    else:
        assert not turn["late"]



# ── after TTS, the run record and the reports ───────────────────────────────────────────────

def test_turn_end_sec_reads_the_word_times_without_adding_the_pause_twice():
    scenes = [{"causal_role": "setup", "narration": "Imagine you keep bees here."},
              {"causal_role": "intervention", "narration": "Kerr imported queens. They lived."},
              {"causal_role": "hinge", "narration": "Except the grids came off, and the queens flew free."},
              {"causal_role": "mechanism", "narration": "They bred."}]
    turn = ot.measure_turn(scenes, {}, "removed_keystone", quote="the queens flew free")
    assert turn["scene"] == 3 and turn["turn_words"] == 20
    times = [[], [], [["Except", 0.0, 1.0], ["the", 1.0, 1.1], ["grids", 1.1, 1.5], ["came", 1.5, 1.7],
                      ["off,", 1.7, 2.0], ["and", 2.0, 2.1], ["the", 2.1, 2.2], ["queens", 2.2, 2.6],
                      ["flew", 2.6, 2.9], ["free.", 2.9, 3.4]], []]
    timing = ot.turn_end_sec(scenes, turn, [0.0, 2.0, 41.0, 45.0], times)
    assert timing == {"turn_end_sec": 44.4, "method": "matched_word", "late": False, "limit_sec": 45.0}
    times[2] = [["x", 0.0, 1.0]] * 4
    assert ot.turn_end_sec(scenes, turn, [0.0, 2.0, 41.0, 45.0], times)["method"] == "proportional"


def test_late_turn_is_recorded_and_never_a_degraded_reason():
    script = _script("bees_v16")
    script["_opening_turn"] = dict(ot.measure_script(script), measured_sec=59.4)
    fields = ot.run_result_fields(script)
    assert fields["late_turn"] == {"words": 163, "est_sec": 63.0, "measured_sec": 59.4,
                                   "limit_words": 116, "limit_sec": 45.0, "source": "fallback",
                                   "shape": "A"}
    script["_opening_turn"]["late"] = False
    assert ot.run_result_fields(script)["late_turn"] is None
    import inspect
    appended = "".join(line for line in inspect.getsource(ep).splitlines() if "reasons.append" in line)
    assert "LATE_TURN" not in appended and "late_turn" not in appended


def test_measure_vs_reference_reports_the_turn(tmp_path):
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import measure_vs_reference as mvr
    script = _script("bees_v16")
    (tmp_path / "audio").mkdir()
    (tmp_path / "_state.json").write_text(json.dumps({"script": script}))
    starts = [0.0, 20.5, 37.1, 54.456, 59.8, 74.4, 88.4]
    (tmp_path / "audio_timing_report.json").write_text(json.dumps(
        {"scenes": [{"scene": i + 1, "start_sec": t} for i, t in enumerate(starts)]}))
    hinge_words = script["scenes"][3]["narration"].split()
    (tmp_path / "audio" / "scene_03.mp3.word_times.json").write_text(json.dumps(
        {"word_times": [[w, i * 0.45, i * 0.45 + 0.4] for i, w in enumerate(hinge_words[:-1])]
         + [["free.", 4.6, 4.96]]}))
    out = mvr.turn_timing(str(tmp_path))
    assert out["turn_words"] == 163 and out["turn_end_sec"] == 59.4 and out["turn_late"]
    assert ("turn_end_sec", "turn ends (s), limit 45") in mvr.ROWS



def test_the_read_s_unspoken_finding_blocks_the_storyboard_until_the_narration_changes():
    steps = [{"step_id": "s0", "role": "setup", "situation": "x"},
             {"step_id": "s1", "role": "hinge", "situation": "But a pond is not a sealed box."},
             {"step_id": "s2", "role": "mechanism", "situation": "y"}]
    issues = []
    cs._check_opening_consequence_spoken([dict(s, index=i, claim_ids=["c15"]) for i, s in enumerate(steps)],
                                         issues, ["c15"], "", unspoken_by_read=True)
    assert [i["code"] for i in issues] == ["OPENING_CONSEQUENCE_UNSPOKEN"]
    issues = []
    cs._check_opening_consequence_spoken([dict(s, index=i, claim_ids=["c15"]) for i, s in enumerate(steps)],
                                         issues, ["c15"], "")
    assert issues == [], "claim binding alone passes it: that is the defect the read closes"


