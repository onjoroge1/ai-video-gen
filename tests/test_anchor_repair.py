"""Anchor phrases must be exact narration substrings — four gates depend on it."""
import explainer_pipeline as ep

NARRATION = ("For sixty years doctors blamed stress. Then Marshall drank the culture, "
             "and ten days later a biopsy showed the bacteria.")


def _scene(*anchors):
    return {"narration": NARRATION,
            "visual_beats": [{"anchor_phrase": a, "purpose": "evidence"} for a in anchors]}


def _anchors(scene):
    return [b["anchor_phrase"] for b in scene["visual_beats"]]


def test_every_repaired_anchor_is_a_real_substring():
    """The invariant the gates actually check. Never satisfied by inventing text."""
    scene = _scene("doctors thought it was stress", "he swallowed the bacteria", "a test came back")
    script = {"scenes": [scene]}
    ep._repair_anchor_phrases(script)
    for anchor in _anchors(scene):
        assert anchor, "an empty anchor cannot be located either"
        assert anchor.casefold() in NARRATION.casefold(), anchor


def test_a_paraphrased_anchor_is_rewritten_and_the_original_kept():
    scene = _scene("doctors blamed anxiety and diet")
    ep._repair_anchor_phrases({"scenes": [scene]})
    beat = scene["visual_beats"][0]
    assert beat["anchor_phrase"].casefold() in NARRATION.casefold()
    assert beat["anchor_phrase_model"] == "doctors blamed anxiety and diet"


def test_beat_zero_is_pinned_to_the_narration_opening():
    """The shot compiler needs shot 0's span within 1.0s of scene start.

    An anchor taken from mid-sentence can never satisfy that, however exact it is — which is why
    a verbatim mid-narration phrase is still replaced on beat zero.
    """
    scene = _scene("a biopsy showed the bacteria")
    assert "a biopsy showed the bacteria" in NARRATION, "precondition: already exact"
    ep._repair_anchor_phrases({"scenes": [scene]})
    assert NARRATION.casefold().startswith(_anchors(scene)[0].casefold())


def test_an_already_correct_later_anchor_is_left_alone():
    scene = _scene("For sixty years", "Marshall drank the culture")
    ep._repair_anchor_phrases({"scenes": [scene]})
    assert _anchors(scene)[1] == "Marshall drank the culture"
    assert "anchor_phrase_model" not in scene["visual_beats"][1]


def test_repair_survives_malformed_scenes():
    for junk in ({"scenes": None}, {"scenes": [{}]}, {"scenes": [{"narration": "", "visual_beats": []}]},
                 {"scenes": [{"narration": NARRATION, "visual_beats": [None, "x"]}]}):
        ep._repair_anchor_phrases(junk)


def test_it_reports_how_many_it_changed():
    scene = _scene("nothing like the narration at all")
    assert ep._repair_anchor_phrases({"scenes": [scene]}) >= 1
    assert ep._repair_anchor_phrases({"scenes": [dict(scene)]}) >= 0
