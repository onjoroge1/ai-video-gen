"""Native Shorts (2026-10-17): lines back to back with a breath, and the vertical picture rules. No network."""
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
