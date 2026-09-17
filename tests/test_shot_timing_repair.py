"""One bad anchor must not cost a whole scene its alignment.

`compile_scene_shots` resolved each evidence state's anchor phrase against measured word timings,
then applied a single whole-scene verdict: if any start was out of order or too close to its
neighbour, EVERY start in the scene was discarded and replaced with even spacing, and every shot
reported `semantic_aligned: False`.

Measured on a real 75.1-second render, two scenes collapsed and took nine cuts with them:

  scene 3   the tail was 1.49s against MIN_SHOT_SECONDS = 1.5   -- out by 0.01 seconds
  scene 5   the callback was anchored to word 9 of 59 but is the LAST shot, so its start
            resolved 16.5s before its predecessor's

The reported `semantic_sync_ratio` was 27%, below the 0.70 hard-failure line, for a cut whose
timings were almost all correct.
"""
import json
from pathlib import Path

import longform_evidence as le
import longform_shots as ls


MIN = ls.MIN_SHOT_SECONDS


def _state(sid, anchor, **kw):
    base = {"state_id": sid, "asset_id": f"asset:{sid}", "anchor_phrase": anchor,
            "asset_status": "accepted", "asset_strategy": "distinct", "purpose": "evidence",
            "verified_visible_information": True}
    base.update(kw)
    return base


def _words(narration, duration):
    parts = narration.split()
    step = duration / len(parts)
    return [(w, i * step, (i + 1) * step) for i, w in enumerate(parts)]


NARRATION = ("The beetles came first and the cane suffered badly. "
             "Then the toads arrived by ship. "
             "They ate almost everything except the beetles. "
             "The quolls died where they fed.")


def test_a_scene_keeps_the_cuts_that_were_always_right():
    """The regression: a single unresolvable anchor used to zero its neighbours."""
    duration = 24.0
    states = [
        _state("s1:e01", "The beetles came first"),
        _state("s1:e02", "Then the toads arrived by ship"),
        _state("s1:e03", "They ate almost everything"),
        _state("s1:e04", "a phrase that is not in this narration at all"),
    ]
    shots = ls.compile_scene_shots(
        {"narration": NARRATION, "story_role": "setup"}, duration, 0,
        word_times=_words(NARRATION, duration), evidence_states=states,
        require_measured_timing=True)

    sources = [s["timing_source"] for s in shots]
    assert "even_fallback" not in sources, "the scene must not collapse for one bad anchor"
    assert sources[3] == "repaired", "the unresolvable anchor is the one that gets moved"
    # The cuts whose anchors resolved keep their credit.
    assert [s["semantic_aligned"] for s in shots[1:3]] == [True, True]
    # And the moved one does not.
    assert shots[3]["semantic_aligned"] is False


def test_a_repaired_start_never_counts_as_aligned():
    """The anti-laundering property. A moved shot no longer lands on its words, and says so."""
    duration = 24.0
    states = [_state("s1:e01", "The beetles came first"),
              _state("s1:e02", "nowhere in the text"),
              _state("s1:e03", "also absent")]
    shots = ls.compile_scene_shots(
        {"narration": NARRATION, "story_role": "setup"}, duration, 0,
        word_times=_words(NARRATION, duration), evidence_states=states,
        require_measured_timing=True)

    for shot in shots:
        if shot["timing_source"] == "repaired":
            assert shot["semantic_aligned"] is False


def test_repaired_starts_stay_monotone_and_fit_the_scene():
    duration = 20.0
    states = [_state(f"s1:e{i:02d}", "not present either") for i in range(1, 6)]
    shots = ls.compile_scene_shots(
        {"narration": NARRATION, "story_role": "setup"}, duration, 0,
        word_times=_words(NARRATION, duration), evidence_states=states,
        require_measured_timing=True)

    starts = [s["start_sec"] for s in shots]
    assert starts == sorted(starts)
    assert all(b - a >= MIN - 1e-6 for a, b in zip(starts, starts[1:])), starts
    assert duration - starts[-1] >= MIN - 1e-6
    assert all(s["duration"] >= MIN - 1e-6 for s in shots)


def test_a_fully_resolved_scene_is_untouched():
    """No repair, no relabelling, every cut aligned."""
    duration = 24.0
    states = [
        _state("s1:e01", "The beetles came first"),
        _state("s1:e02", "Then the toads arrived by ship"),
        _state("s1:e03", "The quolls died where they fed"),
    ]
    shots = ls.compile_scene_shots(
        {"narration": NARRATION, "story_role": "setup"}, duration, 0,
        word_times=_words(NARRATION, duration), evidence_states=states,
        require_measured_timing=True)
    assert all(s["timing_source"] == "measured" for s in shots)
    assert all(s["semantic_aligned"] for s in shots[1:])


# ---- the callback anchor ---------------------------------------------------------------------

def test_the_callback_anchors_to_the_end_of_its_scene():
    """It is the last shot by construction, so its anchor must resolve last."""
    scene = {"narration": NARRATION, "motion_anchor_phrase": "The beetles came first"}
    existing = [{"anchor_phrase": "Then the toads arrived by ship"}]
    phrase = le._closing_anchor_phrase(scene, existing)

    assert phrase in NARRATION, "the anchor must be verbatim on the page"
    assert NARRATION.find(phrase) > NARRATION.find("Then the toads arrived by ship")


def test_the_callback_does_not_reuse_an_anchor_already_taken():
    """Reusing one resolves to that state's position and reintroduces the ordering failure.

    Measured: the final evidence state held the whole closing clause, so the obvious tail phrase
    was already claimed. Punctuation must not hide the collision either.
    """
    scene = {"narration": NARRATION}
    taken = "The quolls died where they fed."          # note the period
    existing = [{"anchor_phrase": "The quolls died where they fed"}]
    phrase = le._closing_anchor_phrase(scene, existing)

    assert le._anchor_key(phrase) != le._anchor_key(taken)
    assert phrase in NARRATION
    # Still at the very end: a strict suffix starts later than the phrase it came from.
    assert NARRATION.find(phrase) >= NARRATION.find("The quolls died")


def test_a_scene_without_narration_keeps_its_historical_anchor():
    """Nothing to derive a position from, and no measured timings to order against."""
    assert le._closing_anchor_phrase(
        {"motion_anchor_phrase": "Alex reads the answer"}, []) == "Alex reads the answer"
    assert le._closing_anchor_phrase(
        {}, [{"anchor_phrase": "the last beat"}]) == "the last beat"


def test_the_real_run_callback_no_longer_points_backwards():
    """Replayed against the recorded render that exposed this."""
    saved = Path(__file__).parent / "fixtures" / "cane_toad_scene5.json"
    if not saved.is_file():
        import pytest
        pytest.skip("recorded scene not present")
    data = json.loads(saved.read_text(encoding="utf-8"))
    scene, existing = data["scene"], data["existing_states"]
    narration = scene["narration"]

    assert scene["motion_anchor_phrase"] == "the toads marched"
    assert narration.find("the toads marched") < len(narration) * 0.25, "the old anchor was early"

    phrase = le._closing_anchor_phrase(scene, existing)
    last_existing = max(narration.find(s["anchor_phrase"]) for s in existing
                        if s.get("anchor_phrase") and s["anchor_phrase"] in narration)
    assert narration.find(phrase) > last_existing, "the callback must resolve after every state"
