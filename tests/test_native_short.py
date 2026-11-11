"""Native Shorts (2026-10-17): lines back to back with a breath, and the vertical picture rules. No network."""
import pytest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import make_native_short as mns  # noqa: E402


def test_lines_run_back_to_back_with_a_breath():
    t = mns.beat_timeline([2.0, 3.5, 1.25], gap=0.12)
    assert t == [{"start": 0.0, "end": 2.0}, {"start": 2.12, "end": 5.62}, {"start": 5.74, "end": 6.99}]


def test_every_picture_is_drawn_for_the_vertical_frame():
    prompt = mns.picture_prompt("Ink-and-cut-paper storybook.", "a screwdriver in a gap.")
    assert prompt.startswith("Ink-and-cut-paper storybook. a screwdriver in a gap.")
    for rule in ("Vertical 2:3", "ONE large subject", "no text", "never recognizable real people"):
        assert rule in prompt, rule
    assert mns.IMAGE_SIZE == "1024x1536"


# The opening package (2026-10-25): hook rules, fast hook cuts, one-or-two-word captions.
import shorts_hook as sh  # noqa: E402


def test_hook_rules_follow_our_own_stayed_to_watch_data():
    # The two best openings (72%, 58%) pass: a year is a warning, not a failure.
    ef = "In 1996, a man stood beside the most dangerous thing at Chernobyl."
    assert sh.hook_problems(ef) == []
    assert sh.hook_warnings(ef) == ["hook names a year in its first six words"]
    assert sh.hook_problems("For decades, Yellowstone's park service killed its own elk.") == []
    # The worst (17%) fails: a seasonal preamble and no stakes.
    hanna = "The summer after the 1986 evacuation, Hanna Zavorotnya's family went back to their farm."
    assert any("preamble" in p for p in sh.hook_problems(hanna))
    # A scene with an anonymous person and nothing at stake fails.
    assert any("stakes" in p for p in sh.hook_problems("In Colombia, a fisherman felt something move."))
    assert sh.hook_problems("Something under his canoe spilled this fisherman into the water.") == []
    # Ending on a question fails; all three worst did.
    assert any("question" in p for p in sh.hook_problems("Twenty thousand people had to leave home for these bombs.",
                                                           last_line="So why can't Colombia stop them?"))


def test_opening_framings_change_every_1_3_seconds_then_relax():
    shots = [{"start": 0.0, "end": 3.9, "image": "a"}, {"start": 4.0, "end": 9.0, "image": "b"},
             {"start": 9.1, "end": 12.0, "image": "c"}]
    out = sh.hook_shots(shots)
    opening = [s for s in out if s["start"] < sh.HOOK_WINDOW]
    assert all(s["end"] - s["start"] <= sh.HOOK_HOLD + 1e-6 for s in opening)
    assert [s["start"] for s in out if s["start"] < 1.5][1] <= sh.FIRST_CUT_MAX
    late = [s for s in out if s["start"] >= 9.0]
    assert len(late) == 2 and all(sh.HOOK_HOLD < s["end"] - s["start"] <= sh.SHOT_HOLD for s in late)


def test_captions_are_one_or_two_words_and_stop_at_punctuation():
    words = [("Twenty", 0.0, 0.3), ("thousand", 0.3, 0.6), ("people,", 0.6, 0.9), ("evacuated.", 1.0, 1.6),
             ("Why?", 2.0, 2.4)]
    chunks = sh.word_chunks(words, until=3.0)
    assert [c[2] for c in chunks] == [["Twenty", "thousand"], ["people,"], ["evacuated."], ["Why?"]]
    assert chunks[0][1] == 0.6 and chunks[-1][1] == 3.0


def test_numbers_and_danger_words_are_coloured():
    assert sh.caption_colour("20,000", set()) == sh.mts.YELLOW
    assert sh.caption_colour("killed.", set()) == sh.mts.YELLOW
    assert sh.caption_colour("bombs", {"bombs"}) == sh.mts.YELLOW
    assert sh.caption_colour("people", set()) == sh.mts.WHITE


def test_gate_fails_a_quiet_static_opening():
    shots = [{"start": 0.0, "end": 4.0}, {"start": 4.0, "end": 6.0}]
    caps = [(0.0, 1.0, ["one", "two"])]
    checks = sh.gate("In Colombia, a fisherman felt something move.", shots, caps,
                     {"lufs": -23.0, "true_peak": -3.0}, 38.0, last_line="So why?")
    assert not checks["first_cut_le_1_5s"][1]
    assert not checks["loudness_minus14_pm1"][1]
    assert not checks["hook_rules"][1]
    assert not sh.gate_passed(checks)


def test_windows_are_centred_on_the_subject_not_the_busy_edges(tmp_path):
    # A plain background with a dark subject right of centre and busy noise along the left edge.
    from PIL import Image, ImageDraw
    import random
    im = Image.new("RGB", (1024, 1536), (235, 225, 200))
    d = ImageDraw.Draw(im)
    random.seed(1)
    for _ in range(4000):
        x, y = random.randint(0, 150), random.randint(0, 1535)
        d.point((x, y), fill=(random.randint(0, 255), 120, 60))
    d.ellipse((520, 500, 900, 1100), fill=(40, 40, 50))
    path = tmp_path / "pic.png"
    im.save(path)
    x0, y0, x1, y1 = sh._subject_box_pixels(str(path))
    assert 470 <= x0 <= 560 and 860 <= x1 <= 940, (x0, x1)
    import unittest.mock as um
    with um.patch.object(sh, "subject_box", sh._subject_box_pixels):
        w = sh.subject_windows(str(path))
        other = tmp_path / "other.png"
        im.save(other)
        framed = sh.frame_drawn([{"start": 0, "end": 2, "image": str(path)}, {"start": 2, "end": 4, "image": str(path)},
                                 {"start": 4, "end": 6, "image": str(other)}])
    wx, _, ww, _ = w["wide"]
    assert wx <= 520 and wx + ww >= 900          # the wide window holds the whole subject
    cx, cy, cw, ch = w["close"]
    assert cx <= 520 and cx + cw >= 900 and cy <= 500 and cy + ch >= 1100
    assert framed[0]["window"] == w["wide"] and framed[1]["window"] == w["close"]
    # One drift per picture: it never reverses across that picture's cuts, only on a new picture.
    assert [f["path"]["direction"] for f in framed] == [1, 1, -1]
    assert framed[0]["path"] == framed[1]["path"]
    p = framed[0]["path"]
    centres = [sh.drift_x(p, t, ww, 1024) + ww / 2 for t in (0, 1, 2, 3, 4)]
    assert all(b >= a for a, b in zip(centres, centres[1:])) and centres[-1] > centres[0]
    assert 0 < p["travel"] <= 0.03 * ww * 4 + 1e-6      # slow: about 3% of the frame a second


def test_picture_cuts_land_on_their_words():
    words = [("Something", 0.0, 0.4), ("under", 0.46, 0.6), ("his", 0.7, 0.9), ("canoe", 0.98, 1.2),
             ("spilled", 1.26, 1.9), ("this", 1.96, 2.3), ("fisherman", 2.42, 2.7), ("into", 2.74, 3.0),
             ("the", 3.08, 3.2), ("water.", 3.28, 3.9)]
    cuts = sh.picture_cuts([(w, s + 10, e + 10) for w, s, e in words], 10.0, [None, "spilled", "into"])
    assert cuts == [10.0, pytest.approx(11.18), pytest.approx(12.66)]
    with pytest.raises(ValueError):
        sh.picture_cuts(words, 0.0, [None, "into", "spilled"])     # cue words must be in line order


def test_moving_first_shot_relaxes_the_opening_but_not_still_holds():
    import shorts_hook as sh
    level = {"lufs": -14.0, "true_peak": -2.0}
    caps = [(0.0, 1.0, ["a"])]
    moving = [{"start": 0.0, "end": 3.2, "motion": "slow push in"}, {"start": 3.2, "end": 5.0}, {"start": 5.0, "end": 7.4}]
    g = sh.gate("Rich men lowered a dam and 2,209 people died.", moving, caps, level, 52.0, "It ended.",
                hold_max=2.8, max_duration=60.0)
    assert g["first_cut_le_1_5s"][1] and g["cuts_in_first_5s_ge_3"][1] and g["duration_20_to_45s"][1]
    still = [dict(s, motion=None) for s in moving]
    g = sh.gate("Rich men lowered a dam and 2,209 people died.", still, caps, level, 52.0, "It ended.", hold_max=2.8)
    assert not g["first_cut_le_1_5s"][1] and not g["longest_hold_le_2s"][1] and not g["duration_20_to_45s"][1]


def test_hold_opening_keeps_moving_first_shot_and_drops_flashes():
    shots = [{"start": 0.0, "end": 1.46, "image": "a", "motion": "m"},
             {"start": 1.46, "end": 2.72, "image": "b"},
             {"start": 2.72, "end": 3.2, "image": "c"},
             {"start": 3.2, "end": 5.0, "image": "d"}]
    out = mns.hold_opening(shots, 3.0)
    assert [s["image"] for s in out] == ["a", "d"]
    assert out[0]["end"] == 3.0 and out[1]["start"] == 3.0 and out[1]["end"] == 5.0


def test_hold_opening_leaves_still_opening_alone():
    shots = [{"start": 0.0, "end": 1.0, "image": "a"}, {"start": 1.0, "end": 2.0, "image": "b"}]
    assert mns.hold_opening(shots, 3.0) == shots
