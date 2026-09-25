"""A targeted revision edits the cached draft beat by beat; it never drops or reorders a beat.

Eleven fresh drafts of the emperor penguin episode (2026-09-25) each fixed some of the editor's
points and reintroduced others. The revision keeps the spine the ledger judged: scenes may merge
or split within a beat, every beat survives, and claim bindings are cleared for re-derivation.
"""
from types import SimpleNamespace

import explainer_pipeline as ep


def _script():
    return {"title": "T", "hook": "Old hook.", "scenes": [
        {"beat_id": "event_01", "causal_role": "setup", "beat_part": 1, "beat_part_count": 3,
         "narration": "Old hook. One egg.", "claim_refs": [{"claim_id": "c01"}], "shot_size": "wide"},
        {"beat_id": "event_01b", "causal_role": "setup", "beat_part": 2, "beat_part_count": 3,
         "narration": "She lays it in May.", "claim_refs": []},
        {"beat_id": "event_01c", "causal_role": "setup", "beat_part": 3, "beat_part_count": 3,
         "narration": "She walks to the sea.", "claim_refs": []},
        {"beat_id": "event_02", "causal_role": "hinge", "beat_part": 1, "beat_part_count": 1,
         "narration": "There is no nest.", "claim_refs": []},
        {"beat_id": "event_10:verdict", "causal_role": "verdict", "beat_part": 1,
         "beat_part_count": 2, "narration": "Look again.", "claim_refs": []},
        {"beat_id": "event_10:verdictb", "causal_role": "verdict", "beat_part": 2,
         "beat_part_count": 2, "narration": "She came back with dinner.", "claim_refs": []},
    ]}


def test_base_beat_ids():
    assert ep._base_beat_id("event_01b") == "event_01"
    assert ep._base_beat_id("event_01") == "event_01"
    assert ep._base_beat_id("event_10:verdictb") == "event_10:verdict"
    assert ep._base_beat_id("event_10:verdict") == "event_10:verdict"


def test_merging_parts_keeps_every_beat_and_the_template_fields():
    script = _script()
    ok = ep._rebuild_revised_scenes(script, [
        {"beat_id": "event_01", "narration": "New hook. She leaves her egg and heads to sea."},
        {"beat_id": "event_02", "narration": "There is no nest."},
        {"beat_id": "event_10:verdict", "narration": "She came back with dinner."},
    ])
    assert ok is True
    ids = [s["beat_id"] for s in script["scenes"]]
    assert ids == ["event_01", "event_02", "event_10:verdict"]
    assert script["scenes"][0]["shot_size"] == "wide"
    assert script["scenes"][0]["claim_refs"] == []
    assert script["scenes"][0]["beat_part_count"] == 1


def test_splitting_a_beat_numbers_its_parts():
    script = _script()
    assert ep._rebuild_revised_scenes(script, [
        {"beat_id": "event_01", "narration": "A."}, {"beat_id": "event_01", "narration": "B."},
        {"beat_id": "event_02", "narration": "C."},
        {"beat_id": "event_10:verdict", "narration": "D."},
    ])
    first, second = script["scenes"][0], script["scenes"][1]
    assert (first["beat_id"], first["beat_part"], first["beat_part_count"]) == ("event_01", 1, 2)
    assert (second["beat_id"], second["beat_part"], second["beat_part_count"]) == ("event_01b", 2, 2)


def test_a_dropped_or_unknown_beat_rejects_the_revision_and_leaves_the_script_alone():
    script = _script()
    assert ep._rebuild_revised_scenes(script, [
        {"beat_id": "event_01", "narration": "A."}, {"beat_id": "event_02", "narration": "C."}]) is False
    assert len(script["scenes"]) == 6
    assert ep._rebuild_revised_scenes(script, [
        {"beat_id": "event_99", "narration": "A."}]) is False
    assert len(script["scenes"]) == 6


def test_revise_cached_script_sets_the_hook_from_the_first_sentence(monkeypatch):
    reply = ('{"hook":"Why does this penguin look like the worst mother?","scenes":['
             '{"beat_id":"event_01","narration":"Why does this penguin look like the worst mother? She leaves."},'
             '{"beat_id":"event_02","narration":"There is no nest."},'
             '{"beat_id":"event_10:verdict","narration":"She came back with dinner."}]}')

    def create(**kwargs):
        return SimpleNamespace(content=[SimpleNamespace(text=reply)],
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    monkeypatch.setattr(ep, "_claude", lambda: SimpleNamespace(messages=SimpleNamespace(create=create)))
    script, cost = ep.revise_cached_script(_script(), "Merge the opening.", "q")
    assert script["hook"] == "Why does this penguin look like the worst mother?"
    assert script["_revision_note"] == "Merge the opening."
    assert len(script["scenes"]) == 3


def test_an_empty_note_is_a_no_op():
    script = _script()
    assert ep.revise_cached_script(script, "", "q") == (script, 0.0)


def test_extra_claim_ids_join_the_beat_event_and_the_contract_counts_follow():
    """Job 87b08528: the planner cited 'regurgitation' (c22) and left the oesophageal secretion
    (c23) unused, so the mechanism could never be spoken; a merged revision also failed the
    retention contract on scene arithmetic."""
    script = _script()
    script["_story_contract"] = {"scene_count": 6, "beat_count": 6,
                                 "beats": [{"role": r} for r in
                                           ("setup", "setup", "setup", "hinge", "verdict", "verdict")]}
    script["scenes"][3]["event"] = {"text": "He can feed it.", "claim_refs": ["c22"]}
    ok = ep._rebuild_revised_scenes(script, [
        {"beat_id": "event_01", "narration": "A."},
        {"beat_id": "event_02", "narration": "He feeds it a milky substance.", "claim_ids": ["c23", "c99"]},
        {"beat_id": "event_10:verdict", "narration": "D."},
        {"beat_id": "event_10:verdict", "narration": "E."},
    ], valid_claim_ids={"c22", "c23"})
    assert ok
    assert script["scenes"][1]["event"]["claim_refs"] == ["c22", "c23"]
    assert script["scenes"][3]["continues"] == "event_10:verdict"
    assert script["scenes"][2]["continues"] == ""
    contract = script["_story_contract"]
    assert contract["scene_count"] == contract["beat_count"] == 4
    assert [b["role"] for b in contract["beats"]] == ["setup", "hinge", "verdict", "verdict"]
