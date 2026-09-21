"""Three defects the 94-shot render exposed: uneven holds, empty frames, an unscored engine.

All three were invisible while films were short and sparse. At 94 shots the distribution, the
cast density and the engine coverage all became measurable, and all three were wrong.
"""
import statistics as st

import illustrated_score as sc
import longform_shots as ls
import story_engines as se
from longform_evidence import _state_from_beat, build_continuity_pack


# ── timing distribution ──────────────────────────────────────────────────────────────────────

def _holds(starts, duration):
    return [round(b - a, 3) for a, b in zip(starts, starts[1:] + [duration])]


def _repair(spans, starts, duration):
    """The spreading pass, exercised exactly as compile_scene_shots runs it."""
    count = len(spans)
    starts = list(starts)
    index = 1
    while index < count:
        if spans[index] and starts[index] >= starts[index - 1] + ls.MIN_SHOT_SECONDS:
            index += 1
            continue
        run_end = index
        while run_end < count and not spans[run_end]:
            run_end += 1
        anchor = starts[run_end] if run_end < count and spans[run_end] else duration
        gap = anchor - starts[index - 1]
        slots = run_end - index + 1
        step = gap / slots if slots else 0.0
        if step >= ls.MIN_SHOT_SECONDS:
            for offset in range(index, run_end):
                starts[offset] = starts[index - 1] + step * (offset - index + 1)
            index = run_end
            continue
        index += 1
    # The forward pin still runs after the spreading pass, exactly as production does. Spreading
    # is a better placement where there is room for one; it does not replace the floor.
    for index in range(1, count):
        floor = starts[index - 1] + ls.MIN_SHOT_SECONDS
        if starts[index] < floor:
            starts[index] = floor
    return starts


def test_a_run_of_dead_anchors_is_shared_out_not_stacked_at_the_floor():
    """The measured shape: mean 3.25s passes while 17 shots sit at 1.5s and 38 run over 3.5s.

    Stacking three unplaceable anchors at MIN_SHOT_SECONDS hands every second they did not take
    to the next shot that resolved. long_visual_hold is per shot, so a passing mean cannot buy it.
    """
    starts = _repair([True, False, False, False, True, True],
                     [0.0, -1.0, -1.0, -1.0, 20.0, 24.0], 30.0)
    holds = _holds(starts, 30.0)
    assert max(holds) <= 6.0, holds
    assert min(holds) >= ls.MIN_SHOT_SECONDS, holds
    # The old behaviour put 15.5s on one shot. Anything near that is the bug returning.
    assert max(holds) < 10.0


def test_measured_anchors_are_never_moved():
    """Only indexes with no usable span may move. A resolved anchor is where the audio put it."""
    starts = _repair([True, False, True, False, True],
                     [0.0, -1.0, 12.0, -1.0, 24.0], 30.0)
    assert starts[0] == 0.0 and starts[2] == 12.0 and starts[4] == 24.0


def test_the_result_is_still_strictly_increasing():
    starts = _repair([True, False, False, True], [0.0, -1.0, -1.0, 9.0], 20.0)
    assert all(b - a >= ls.MIN_SHOT_SECONDS - 1e-9 for a, b in zip(starts, starts[1:]))


def test_a_run_with_no_room_falls_back_to_the_floor_rather_than_going_backwards():
    """When the gap cannot pay MIN_SHOT_SECONDS per slot, spreading is refused and the forward
    pass still pins. Better a known floor than a negative step."""
    starts = _repair([True, False, False, True], [0.0, -1.0, -1.0, 2.0], 10.0)
    assert starts == sorted(starts)


def test_a_trailing_run_uses_the_scene_end_as_its_anchor():
    starts = _repair([True, False, False], [0.0, -1.0, -1.0], 12.0)
    holds = _holds(starts, 12.0)
    assert max(holds) <= 4.5, holds


# ── people in the frame ──────────────────────────────────────────────────────────────────────

_PACK = build_continuity_pack({
    "scenes": [{"narration": "x", "continuity_anchor": "a Georgia hillside"}],
    "_story_contract": {"opening_object": "a kudzu seedling",
                        "final_callback_object": "a kudzu seedling",
                        "recurring_location": "a Georgia hillside"}})


def _needs_people(purpose, **beat):
    state = _state_from_beat(
        {"narration": "Something happened here.", "human_present": False},
        {"anchor_phrase": "Something happened", "purpose": purpose, "visual": "a field", **beat},
        1, 0, _PACK, opening=False)
    return bool(state.get("anonymous_people_required"))


def test_a_consequence_frame_asks_for_the_people_it_happened_to():
    """The largest group, and the one the default missed. A vine over a forest is a texture; a
    vine over a forest with a farmer beneath it is a consequence."""
    assert _needs_people("consequence")


def test_an_action_frame_still_asks_for_the_people_performing_it():
    assert _needs_people("action")


def test_pure_evidence_frames_never_grow_a_bystander():
    """A document, a diagram or a record is the evidence. Adding a figure invents a witness."""
    for purpose in ("evidence", "diagram", "record", "scale"):
        assert not _needs_people(purpose), purpose


def test_the_writer_can_still_override_the_default():
    assert not _needs_people("consequence", anonymous_people_required=False)


# ── the score ────────────────────────────────────────────────────────────────────────────────

def test_every_selectable_engine_has_a_designed_score():
    """removed_keystone had none and fell through to ("curious", 88, "major").

    Measured: a five-minute film about kudzu smothering the American South was scored cheerful and
    in a major key, because its engine had no row. A new engine must not ship able to do that.
    """
    assert sc._engines_without_a_score() == [], sc._engines_without_a_score()
    assert set(se.ENGINES) <= set(sc._MOODS)


def test_removed_keystone_is_scored_as_a_collapse_not_a_curiosity():
    spec = sc.score_spec("Why America Paid Farmers to Plant Kudzu", "removed_keystone", 300.0)
    assert spec["mode"] == "minor"
    assert spec["mood"] != "curious"
    assert spec["tempo_bpm"] < 92, "a collapse is gradual; it should sit under the other engines"


def test_the_designed_engines_are_unchanged():
    """This adds a row; it must not retune the four that were already deliberate."""
    for engine, (mood, tempo, mode) in (
            ("backfiring_solution", ("wry", 106, "minor")),
            ("accidental_invention", ("discovery", 110, "major"))):
        spec = sc.score_spec("t", engine, 120.0)
        assert spec["mood"] == mood and spec["mode"] == mode
        assert abs(spec["tempo_bpm"] - tempo) <= 3, "only the theme jitter may move the tempo"


# ── the long-tail redistribution must not eat measured anchors ───────────────────────────────

def _long_tail_fires(holds, spans, duration, count):
    """The #118 collapse-shape test, with the discriminator this adds."""
    from longform_evidence import MAX_VISUAL_STATE_SECONDS
    long_index = holds.index(max(holds)) if holds else -1
    unexplained = long_index >= 0 and (long_index == count - 1 or not spans[long_index])
    return bool(holds) and unexplained and max(holds) > max(
        MAX_VISUAL_STATE_SECONDS, 2.0 * duration / count) + 1e-9


def test_a_long_first_clause_is_not_a_collapse():
    """The measured mis-fire. vb1 sits at 0.0 and vb2 starts at the second clause, so the first
    gap is long by construction -- scene 1 of a delivered film had 13.52s against a 8.24s
    threshold, with every anchor resolved. Re-spacing it discarded correct timing and cost
    narration alignment four points short of scoring."""
    holds = [13.52, 1.20, 4.30, 1.58]
    spans = [True, True, True, True]
    assert not _long_tail_fires(holds, spans, 20.6, 5)


def test_the_collapse_shape_still_redistributes():
    """[1.5, 1.5, 43.08] -- the shape #118 exists for. The long shot has no anchor of its own; it
    absorbed what the dropped states could not take."""
    holds = [1.5, 1.5, 43.08]
    spans = [True, False, False]
    assert _long_tail_fires(holds, spans, 46.08, 3)


def test_a_long_hold_between_two_measured_anchors_is_left_alone():
    """Where the narration put the pictures is not a defect this pass may overrule."""
    holds = [2.0, 9.0, 2.0]
    spans = [True, True, True]
    assert not _long_tail_fires(holds, spans, 13.0, 3)


def test_a_long_FINAL_hold_is_a_collapse_even_with_a_resolved_anchor():
    """Nothing measures where the last shot should stop. When the words run out 40 seconds before
    the audio does, the tail is unexplained however well its own anchor resolved."""
    holds = [2.0, 1.5, 42.58]
    spans = [True, True, True]
    assert _long_tail_fires(holds, spans, 46.08, 3)
