"""Anchor repair never puts two beats of a scene on one moment (2026-10-14).

Its fallbacks reach for fallbacks[0] or the first-sentence opening, which beat zero already holds:
aral-v2 carried "Imagine you're a fishing family on the" beside beat zero's "Imagine you're a
fishing family", and "And it worked." twice. Two states on one instant cannot both be cut on their
words, so one is moved, reported unaligned, and the opening's semantic_sync cap follows.
"""
import explainer_pipeline as ep


def _positions(narration, scene):
    haystack = narration.casefold()
    return [haystack.find(beat["anchor_phrase"].casefold()) for beat in scene["visual_beats"]]


def _keys(scene):
    return [" ".join(beat["anchor_phrase"].casefold().replace(".", "").split())
            for beat in scene["visual_beats"]]


def test_fallbacks_never_land_on_a_moment_another_beat_holds():
    narration = ("Imagine you're a fishing family on the Aral Sea. Two rivers fed it for "
                 "centuries. And it worked.")
    scene = {"narration": narration, "visual_beats": [
        {"anchor_phrase": "a family fishing the sea"}, {"anchor_phrase": "the two rivers"},
        {"anchor_phrase": "it was fine"}, {"anchor_phrase": "nothing like this"},
        {"anchor_phrase": "nor this"}]}
    ep._repair_anchor_phrases({"scenes": [scene]})
    anchors = [beat["anchor_phrase"] for beat in scene["visual_beats"]]
    positions = _positions(narration, scene)
    assert all(anchor.casefold() in narration.casefold() for anchor in anchors)
    assert len(set(positions)) == len(positions), anchors
    assert len(set(_keys(scene))) == len(anchors)
    assert anchors[0] == "Imagine you're a fishing family"
    assert all("anchor_phrase_model" in beat for beat in scene["visual_beats"])


def test_replacements_keep_the_narrations_order_while_it_has_room():
    narration = ("Imagine you're a fishing family on the Aral Sea. Two rivers fed it for "
                 "centuries. And it worked for a while, until the planners came with their "
                 "canals and their cotton.")
    scene = {"narration": narration, "visual_beats": [
        {"anchor_phrase": "a family fishing the sea"}, {"anchor_phrase": "the two rivers"},
        {"anchor_phrase": "it was fine"}, {"anchor_phrase": "nothing like this"},
        {"anchor_phrase": "nor this"}]}
    ep._repair_anchor_phrases({"scenes": [scene]})
    positions = _positions(narration, scene)
    assert positions == sorted(positions) and len(set(positions)) == 5


def test_a_model_written_duplicate_is_replaced_and_audited():
    narration = ("And at first it looked like simple arithmetic. Fewer wolves meant more elk, "
                 "and the herds grew.")
    scene = {"narration": narration, "visual_beats": [
        {"anchor_phrase": "And at first it looked"},
        {"anchor_phrase": "Fewer wolves meant more elk"},
        {"anchor_phrase": "Fewer wolves meant more elk"}]}
    ep._repair_anchor_phrases({"scenes": [scene]})
    beats = scene["visual_beats"]
    assert beats[1]["anchor_phrase"] == "Fewer wolves meant more elk"
    assert "anchor_phrase_model" not in beats[1]
    assert beats[2]["anchor_phrase"] != beats[1]["anchor_phrase"]
    assert beats[2]["anchor_phrase"] in narration
    assert beats[2]["anchor_phrase_model"] == "Fewer wolves meant more elk"
    assert len(set(_positions(narration, scene))) == 3


def test_a_phrase_that_also_occurs_earlier_is_not_offered():
    # "the herd" occurs twice; a window starting at the second occurrence would resolve to the
    # first in both str.find and the timing search, so it cannot be a unique replacement.
    narration = "the herd ran. the herd stopped. the herd turned back."
    phrase = ep._unique_anchor_phrase(narration, {"the herd ran"}, {0}, 0)
    assert phrase and narration.find(phrase) > 0
    assert narration.casefold().find(phrase.casefold()) == narration.find(phrase)
