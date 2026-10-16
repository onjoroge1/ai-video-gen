"""Shorts pacing (2026-10-16): no framing is held longer than MAX_HOLD, repeats of one picture get
different windows, and inserted pictures replace exactly the range they cover.

The Chernobyl Short held its first picture for 10.6 s: the film's shot plan re-framed one still
four times (push to detail, pull to wide, pan), and the reframe flattened all four into the same
centred window. No ffmpeg is run here.
"""
import os
import re
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import make_teaser_short as mts  # noqa: E402


def _picture(tmp_path, name, size=(1536, 1024), busy_x=1200):
    path = tmp_path / name
    im = Image.new("RGB", size, (90, 90, 100))
    d = ImageDraw.Draw(im)
    for k in range(0, size[1], 12):            # a busy striped subject on one side
        d.line((busy_x - 150, k, busy_x + 150, k + 6), fill=(250, 250, 250), width=3)
    im.save(path)
    return str(path)


def test_long_holds_are_split_and_short_ones_kept(tmp_path):
    img = _picture(tmp_path, "a.png")
    shots = [{"start": 0.0, "end": 10.6, "image": img}, {"start": 10.6, "end": 12.0, "image": img}]
    out = mts.split_long(shots, max_hold=2.6)
    assert max(s["end"] - s["start"] for s in out) <= 2.6 + 1e-9
    assert len(out) == 5 + 1
    assert abs(out[0]["start"] - 0.0) < 1e-9 and abs(out[4]["end"] - 10.6) < 1e-9
    assert out[-1]["end"] - out[-1]["start"] == 12.0 - 10.6


def test_a_split_part_is_never_shorter_than_the_floor(tmp_path):
    img = _picture(tmp_path, "a.png")
    out = mts.split_long([{"start": 0.0, "end": 3.0, "image": img}], max_hold=1.0, min_part=1.1)
    assert all(s["end"] - s["start"] >= 1.1 - 1e-9 for s in out)


def test_repeats_of_one_picture_never_reuse_a_window_back_to_back(tmp_path):
    img = _picture(tmp_path, "a.png")
    shots = mts.split_long([{"start": 0.0, "end": 10.6, "image": img}], max_hold=2.6)
    framed = mts.assign_framing(shots)
    windows = [s["window"] for s in framed]
    assert all(a != b for a, b in zip(windows, windows[1:]))
    assert len(set(windows)) >= 3


def test_the_wide_window_lands_on_the_busy_subject(tmp_path):
    img = _picture(tmp_path, "a.png", busy_x=1250)
    best = mts.candidate_windows(img)["wide"][0][1]
    x, _, w, _ = best
    assert x <= 1250 <= x + w, best


def test_hints_steer_the_framing(tmp_path):
    img = _picture(tmp_path, "a.png")
    shots = [{"start": 0, "end": 2, "image": img, "transition": "continuous", "motion": "locked"},
             {"start": 2, "end": 4, "image": img, "transition": "push_to_detail", "motion": "locked"},
             {"start": 4, "end": 6, "image": img, "transition": "pull_to_wide", "motion": "pan_right"}]
    framed = mts.assign_framing(shots)
    ih = 1024
    assert framed[1]["window"][3] < ih, "push_to_detail takes a close-up"
    assert framed[2]["window"][3] == ih and framed[2]["move"] == "pan_right"


def test_inserts_replace_exactly_the_range_they_cover(tmp_path):
    a, v = _picture(tmp_path, "a.png"), _picture(tmp_path, "v.png", size=(1024, 1536), busy_x=500)
    shots = [{"start": 0.0, "end": 10.6, "image": a}, {"start": 10.6, "end": 16.0, "image": a}]
    out = mts.apply_inserts(shots, [{"start": 2.6, "end": 4.8, "image": v}])
    spans = [(round(s["start"], 2), round(s["end"], 2), os.path.basename(s["image"])) for s in out]
    assert spans == [(0.0, 2.6, "a.png"), (2.6, 4.8, "v.png"), (4.8, 10.6, "a.png"), (10.6, 16.0, "a.png")]


def test_a_vertical_picture_gets_full_height_windows(tmp_path):
    v = _picture(tmp_path, "v.png", size=(1024, 1536), busy_x=500)
    wide = mts.candidate_windows(v)["wide"]
    assert all(w[3] == 1536 and abs(w[2] / w[3] - 9 / 16) < 0.01 for _, w in wide)


def test_an_inserted_picture_with_blank_margins_is_framed_on_its_content(tmp_path):
    path = tmp_path / "margins.png"
    im = Image.new("RGB", (1024, 1536), (240, 228, 200))            # blank paper
    d = ImageDraw.Draw(im)
    for k in range(560, 980, 10):                                     # content only in the middle band
        d.line((150, k, 870, k + 5), fill=(30, 30, 30), width=3)
    im.save(path)
    framed = mts.assign_framing([{"start": 0, "end": 2, "image": str(path), "inserted": True}])
    x, y, w, h = framed[0]["window"]
    assert h < 1536 and y <= 600 and y + h >= 900, framed[0]["window"]


def test_captions_of_a_cut_cue_keep_their_real_pace():
    """A cue running past the cut is timed over its full span: words after the cut never show."""
    text = ("But proving it meant working the reactor hard. To set up the test the operators lowered "
            "the power. Then someone pressed the emergency shutdown button and the core surged.")
    cues = [{"start": 40.0, "end": 60.0, "text": text}]
    out = mts._phrases(cues, until=48.0)
    shown = " ".join(p["text"] for p in out)
    assert "shutdown" not in shown and "surged" not in shown
    assert all(p["end"] <= 48.0 for p in out)


def test_a_caption_never_straddles_two_sentences():
    cues = [{"start": 0.0, "end": 6.0, "text": "A home again. It isn't. The zone is closed."}]
    for p in mts._phrases(cues, until=6.0):
        assert not re.search(r"[.!?]\s+\S", p["text"]), p["text"]


def test_a_bar_forces_the_headline_break():
    lines = mts._headline_lines("CHERNOBYL|40 YEARS LATER", 84)
    assert [" ".join(w for w, _ in ln) for ln in lines] == ["CHERNOBYL", "40 YEARS LATER"]
    assert lines[0][0][1] == mts.YELLOW and lines[1][0][1] == mts.WHITE
