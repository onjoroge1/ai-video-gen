"""State count is arithmetic on the scene's length, not a fixed number.

Each state is held for duration/count, bounded at both ends: below
MIN_EVIDENCE_STATE_SECONDS it reads as a flash frame, above MAX_VISUAL_STATE_SECONDS the
rendered gate rejects it. compile_evidence_plan used a flat beats[:4] regardless of duration,
and run 9c1fa296 carried both failures at once -- "3 states in 4.42s would force 1.47s flash
frames" and "3 state(s) across 12.60s holds each for 4.20s".
"""

import math

from longform_evidence import (
    MAX_VISUAL_STATE_SECONDS,
    MIN_EVIDENCE_STATE_SECONDS,
    WORDS_PER_SECOND,
    _states_that_fit,
)


def _scene(words):
    """Built from WORDS, which is what the code measures.

    An earlier version took seconds and converted, so a 4.42s scene became 13 words and read
    back as 4.545s -- across the boundary, where keeping 3 states is correct. The fixture was
    wrong, not the code, and it would have sent me to change working behaviour.
    """
    return {"narration": " ".join(["word"] * max(1, words))}


def _seconds(words):
    return words / WORDS_PER_SECOND


def _beats(count):
    return [{"anchor_phrase": f"phrase {i}"} for i in range(count)]


def test_a_short_scene_is_trimmed_below_the_flash_frame_floor():
    # The exact failure: 12 words is 4.20s, and 3 states would hold each for 1.40s.
    kept = _states_that_fit(_beats(3), _scene(12))

    assert len(kept) < 3
    assert _seconds(12) / len(kept) >= MIN_EVIDENCE_STATE_SECONDS


def test_no_realistic_scene_is_left_below_the_floor():
    for words in range(9, 60):
        for offered in (2, 3, 4, 5, 6):
            kept = len(_states_that_fit(_beats(offered), _scene(words)))
            assert _seconds(words) / kept >= MIN_EVIDENCE_STATE_SECONDS - 0.02, (
                f"{words}w ({_seconds(words):.2f}s) with {offered} beats kept {kept}, "
                f"holding {_seconds(words) / kept:.2f}s")


def test_it_only_trims_and_never_invents():
    # A long scene offered too few beats keeps them; the validator reports the sparse hold.
    # Adding a state means inventing a visual no beat asked for.
    kept = _states_that_fit(_beats(2), _scene(40))

    assert len(kept) == 2, "padding would fabricate visual content"
    assert _seconds(40) / len(kept) > MAX_VISUAL_STATE_SECONDS, (
        "so the sparse case must still be caught")


def test_a_well_sized_scene_is_untouched():
    scene = _scene(26)
    offered = _beats(math.ceil(_seconds(26) / MAX_VISUAL_STATE_SECONDS))

    assert len(_states_that_fit(offered, scene)) == len(offered)


def test_empty_input_survives():
    assert _states_that_fit([], _scene(23)) == []
    assert _states_that_fit(_beats(2), {"narration": ""}) == _beats(2)


def test_measured_seconds_override_the_word_estimate():
    """The plan is re-fitted against real audio, not the prediction it was written from.

    A scene planned at 36 words reads as 12.6s and holds four states. If the TTS actually
    came in at 5.0s, four states hold 1.25s each -- below the flash-frame floor. Fitting
    against the estimate and aligning against the measurement is the same planned-versus-
    measured split that made the runtime contract 34% wrong.
    """
    scene = _scene(36)
    beats = _beats(4)

    assert len(_states_that_fit(beats, scene)) == 4, "planned duration holds four"
    assert len(_states_that_fit(beats, scene, 5.0)) < 4, "measured 5.0s cannot"
    assert 5.0 / len(_states_that_fit(beats, scene, 5.0)) >= MIN_EVIDENCE_STATE_SECONDS - 0.02


def test_a_longer_measurement_is_not_trimmed():
    # Measurement cuts both ways: audio longer than predicted keeps every state.
    assert len(_states_that_fit(_beats(4), _scene(36), 20.0)) == 4


def test_the_compiler_accepts_measured_durations():
    from longform_evidence import compile_evidence_plan

    script = {"scenes": [{
        "narration": " ".join(["word"] * 36), "story_role": "mechanism",
        "visual_beats": [{"anchor_phrase": f"phrase {i}"} for i in range(4)],
    }]}

    planned = compile_evidence_plan(script)
    measured = compile_evidence_plan(script, scene_seconds={0: 5.0})

    assert len(measured["scenes"][0]["states"]) < len(planned["scenes"][0]["states"])
