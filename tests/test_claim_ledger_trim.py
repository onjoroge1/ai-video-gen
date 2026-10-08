"""The deterministic sentence trim behind the claim ledger: delete, never rewrite.

Measured on the first emperor penguin long-form script (2026-09-24): "So he stands." failed
NARRATION_EXCEEDS_EVENT against an event that says the male incubates the egg in his brood pouch,
and two model repair passes kept the word because it is true. The trim removes the sentence when
nothing the ledger relies on is in it, and the caller re-validates, so it can only turn a failure
into a judged pass.
"""
import explainer_pipeline as ep


def _script():
    return {"scenes": [
        {"beat_id": "event_01", "narration": "One egg. She hands it over.",
         "claim_refs": [{"claim_id": "c01", "narration_phrase": "She hands it over."}]},
        {"beat_id": "event_03b",
         "narration": "So he stands. Tucked inside that brood pouch, the egg is his to hold. "
                      "He will hold it there for roughly sixty-five days.",
         "claim_refs": [{"claim_id": "c05",
                         "narration_phrase": "He will hold it there for roughly sixty-five days."}]},
    ]}


def _report(scene="event_03b", details=("He stands",)):
    return {"passed": False, "errors": [{"code": "NARRATION_EXCEEDS_EVENT", "scene": scene,
                                          "unsupported_details": list(details)}]}


def test_the_offending_sentence_is_dropped_and_the_bound_sentence_kept():
    script = _script()
    dropped = ep._trim_unsupported_sentences(script, _report())
    assert dropped == 1
    assert script["scenes"][1]["narration"] == (
        "Tucked inside that brood pouch, the egg is his to hold. "
        "He will hold it there for roughly sixty-five days.")


def test_a_sentence_carrying_a_bound_claim_phrase_is_never_dropped():
    script = _script()
    dropped = ep._trim_unsupported_sentences(script, _report(details=("sixty-five days",)))
    assert dropped == 0
    assert "sixty-five days" in script["scenes"][1]["narration"]


def test_a_single_sentence_scene_is_left_for_the_model_repair_or_the_refusal():
    script = {"scenes": [{"beat_id": "event_02", "narration": "So he stands.", "claim_refs": []}]}
    assert ep._trim_unsupported_sentences(script, _report(scene="event_02")) == 0
    assert script["scenes"][0]["narration"] == "So he stands."


def test_scenes_are_addressed_by_beat_id_or_by_index_and_other_codes_are_ignored():
    script = _script()
    assert ep._trim_unsupported_sentences(script, _report(scene=2)) == 1
    script = _script()
    other = {"passed": False, "errors": [{"code": "claim_assertion_mismatch", "scene": "event_03b",
                                          "unsupported_details": ["He stands"]}]}
    assert ep._trim_unsupported_sentences(script, other) == 0


def test_a_leading_purpose_clause_is_clipped_and_the_mechanism_kept():
    """Job 87884355 (2026-09-25): 'To stretch that fuel, he joins the others in a huddle' failed
    on the purpose clause alone; dropping the sentence would have dropped the huddle."""
    script = {"scenes": [{"beat_id": "event_06", "narration": (
        "To stretch that fuel, he joins the others in a huddle, packing tight so they lose heat "
        "far more slowly. Tiny, coordinated steps travel as a wave through the whole group."),
        "claim_refs": [{"claim_id": "c26", "narration_phrase":
                        "Tiny, coordinated steps travel as a wave through the whole group."}]}]}
    dropped = ep._trim_unsupported_sentences(
        script, _report(scene="event_06", details=("to stretch that fuel",)))
    assert dropped == 1
    assert script["scenes"][0]["narration"] == (
        "He joins the others in a huddle, packing tight so they lose heat far more slowly. "
        "Tiny, coordinated steps travel as a wave through the whole group.")


def test_a_trailing_clause_is_clipped_with_its_comma():
    assert ep._clip_unsupported_clause(
        "He holds it there, to keep it warm.", ["to keep it warm"], []) == "He holds it there."
    assert ep._clip_unsupported_clause(
        "He holds it there.", ["holds it there"], []) == "He holds it there."
    assert ep._clip_unsupported_clause(
        "He holds it, warm, for weeks.", ["warm"], ["He holds it, warm, for weeks."]) == \
        "He holds it, warm, for weeks."


def test_a_paraphrased_verdict_overshoot_drops_the_unbound_sentence():
    """The judge wrote 'the father was left guarding the egg during her absence'; no sentence
    contains those words, so the unbound sentence is the one to go."""
    script = {"scenes": [{"beat_id": "event_10:verdict", "narration": (
        "She didn't leave the egg unprotected. She left it with its father — and came back with "
        "dinner."),
        "claim_refs": [{"claim_id": "c20", "narration_phrase":
                        "She left it with its father — and came back with dinner."}]}]}
    dropped = ep._trim_unsupported_sentences(script, _report(
        scene="event_10:verdict",
        details=("the father was left guarding the egg during her absence",)))
    assert dropped == 1
    assert script["scenes"][0]["narration"] == \
        "She left it with its father — and came back with dinner."


def test_the_hook_sentence_is_never_dropped_and_annotated_spans_are_clipped():
    """Job 218e75c5 (2026-09-25): the judge wrote 'with Dad (that the male takes over the egg)'
    and the fallback deleted the spoken question instead of clipping 'with Dad'."""
    script = {"hook": "Why does this emperor penguin look like the worst mother?",
              "scenes": [{"beat_id": "event_01", "narration": (
                  "Why does this emperor penguin look like the worst mother? She leaves her only "
                  "egg with Dad and heads to sea. But if the chick hatches before she returns, how "
                  "does the father feed it?"),
                  "claim_refs": [{"claim_id": "c01", "narration_phrase":
                                  "But if the chick hatches before she returns, how does the father feed it?"}]}]}
    dropped = ep._trim_unsupported_sentences(script, _report(
        scene="event_01", details=("with Dad (that the male takes over the egg)",)))
    assert dropped == 1
    assert script["scenes"][0]["narration"] == (
        "Why does this emperor penguin look like the worst mother? She leaves her only egg and "
        "heads to sea. But if the chick hatches before she returns, how does the father feed it?")


def test_the_unbound_fallback_drops_one_sentence_per_round():
    """Job 2e2c7498: dropping every unbound sentence at once gutted the early-hatch beat."""
    script = {"scenes": [{"beat_id": "event_08", "narration": (
        "Now suppose the chick hatches before the mother is back. It needs food, not only "
        "warmth. He can feed it before the female returns."),
        "claim_refs": [{"claim_id": "c23", "narration_phrase":
                        "He can feed it before the female returns."}]}]}
    dropped = ep._trim_unsupported_sentences(script, _report(
        scene="event_08", details=("the female returns from the sea",)))
    assert dropped == 1
    assert script["scenes"][0]["narration"].count(".") == 2


def test_opening_questions_are_judged_with_the_hook_not_against_beat_one(monkeypatch):
    import longform_research as lr
    import story_fact_model as sfm
    seen = {}

    def fake_cascade(beats, *a, **k):
        seen["beat_one"] = beats[0]["narration"]
        import collections
        report = collections.defaultdict(list)
        report["structure_status"] = "pass"
        report["passed"] = True
        return report
    monkeypatch.setattr(sfm, "validate_cascade", fake_cascade)
    monkeypatch.setattr(sfm, "_validate_relationships", lambda *a, **k: [])
    monkeypatch.setattr(lr, "script_has_events", lambda s: True, raising=False)
    import claim_entailment as ce
    judged = {}
    monkeypatch.setattr(ce, "narration_fidelity", lambda story, hook, **k: judged.setdefault(
        "hook", hook) and {"verdict": "entailed", "passed": True})
    script = {"hook": "Why does this penguin look like the worst mother?",
              "scenes": [{"beat_id": "event_01", "causal_role": "setup",
                          "event": {"text": "She lays one egg and returns to sea.", "claim_refs": []},
                          "narration": ("Why does this penguin look like the worst mother? She "
                                        "leaves her egg with Dad. But how does he feed the chick?")}]}
    lr.validate_story_fact_model(script, {"claims": []})
    assert seen["beat_one"] == "She leaves her egg with Dad."
    assert judged["hook"].endswith("But how does he feed the chick?")
