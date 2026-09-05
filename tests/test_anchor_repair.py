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


FACTCHECKED = ("The bacteria appeared in more than 90% of duodenal ulcers. "
               "Antibiotics healed them for good.")


def _claim_scene(*phrases):
    return {"narration": FACTCHECKED, "evidence_id": "e01",
            "claim_refs": [{"claim_id": f"c{i:02d}", "narration_phrase": p, "evidence_id": "e01"}
                           for i, p in enumerate(phrases, 1)]}


def test_a_phrase_the_factcheck_rewrote_is_rebound():
    """The real failure: fact-check changed 'Over ninety percent' to 'more than 90%'.

    Both wordings are correct; the binding made against the older one is not.
    """
    scene = _claim_scene("Over ninety percent of duodenal ulcers")
    assert ep._repair_claim_phrases({"scenes": [scene]}) == 1
    ref = scene["claim_refs"][0]
    assert ref["narration_phrase"].casefold() in FACTCHECKED.casefold()
    assert ref["narration_phrase_model"] == "Over ninety percent of duodenal ulcers"


def test_a_claim_the_factcheck_removed_is_dropped_not_repointed():
    """If the assertion is gone from the narration, its citation goes too.

    Repointing it at the nearest surviving sentence would attach a source to a claim the script no
    longer makes — which is the fabrication the ledger exists to prevent.
    """
    scene = _claim_scene("the moon landing was filmed in a studio")
    ep._repair_claim_phrases({"scenes": [scene]})
    assert scene["claim_refs"] == []
    assert scene["evidence_id"] == "", "an unclaimed scene must not keep a dangling evidence join"


def test_an_exact_phrase_is_expanded_to_its_complete_assertion():
    scene = _claim_scene("Antibiotics healed them")
    ep._repair_claim_phrases({"scenes": [scene]})
    ref = scene["claim_refs"][0]
    assert ref["narration_phrase"] == "Antibiotics healed them for good."
    assert ref["narration_phrase_model"] == "Antibiotics healed them"


def test_claim_repair_survives_malformed_input():
    for junk in ({"scenes": None}, {"scenes": [{}]},
                 {"scenes": [{"narration": FACTCHECKED, "claim_refs": [None, "x"]}]}):
        ep._repair_claim_phrases(junk)
