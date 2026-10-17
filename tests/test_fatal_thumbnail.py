"""FATAL thumbnails (2026-10-17): the headline guardrail, the prompt's click rules, the feed sheet and the
install step. No network: the image call is never made here.
"""
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import make_fatal_thumbnail as mft  # noqa: E402


def test_fatal_needs_a_documented_death_or_lethal_danger():
    ok, evidence = mft.fatal_allowed("The screwdriver slipped. Nine days later, Slotin was dead. He was not the first.")
    assert ok and evidence == "Nine days later, Slotin was dead."
    ok, _ = mft.fatal_allowed("When it was first measured, it gave off a lethal dose in under five minutes.")
    assert ok
    ok, evidence = mft.fatal_allowed("The pythons spread across the Everglades. Rabbits vanished.")
    assert not ok and evidence == ""


def test_the_refusal_stops_before_any_image_call(tmp_path, monkeypatch):
    (tmp_path / "transcript.txt").write_text("The pythons spread across the Everglades.")
    monkeypatch.setattr(mft, "generate", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    try:
        mft.main([str(tmp_path), "--word", "SNAKE", "--left", "a", "--right", "b"])
    except SystemExit as stop:
        assert "FATAL refused" in str(stop)
    else:
        raise AssertionError("FATAL was not refused")


def test_headline_is_two_short_uppercase_words():
    assert mft.headline_ok("FATAL", "FUEL") and mft.headline_ok("FATAL", "SLIP")
    assert not mft.headline_ok("FATAL", "fuel")
    assert not mft.headline_ok("FATAL", "TWO WORDS")
    assert not mft.headline_ok("FATAL", "EXTRAORDINARYTEST")


def test_the_prompt_carries_the_click_rules():
    prompt = mft.build_prompt("bare fingers on a screwdriver in a glowing gap", "a face lit blue")
    for rule in ("ONE large, high-contrast subject per panel", "LARGE in the near foreground",
                 "never a cartoon expression", "NO text", "Do NOT draw any red circle", "TOP 22%"):
        assert rule in prompt, rule
    assert "bare fingers on a screwdriver in a glowing gap." in prompt
    assert "cut-paper" in mft.build_prompt("a", "b", "illustrated")


def test_feed_sheet_puts_every_candidate_at_feed_size(tmp_path):
    paths = []
    for name in ("a.jpg", "b.jpg"):
        Image.new("RGB", (1280, 720), (90, 20, 20)).save(tmp_path / name)
        paths.append(str(tmp_path / name))
    out = mft.feed_sheet(paths, str(tmp_path / "sheet.jpg"))
    width, height = Image.open(out).size
    assert width == 14 + (mft.FEED_WIDTH + 14) * 2 and height == round(mft.FEED_WIDTH * 9 / 16) + 22 + 28


def test_install_keeps_the_pipeline_thumbnail_once(tmp_path):
    (tmp_path / "thumbnail.jpg").write_bytes(b"pipeline")
    (tmp_path / "v1.jpg").write_bytes(b"one")
    (tmp_path / "v2.jpg").write_bytes(b"two")
    mft.install_thumbnail(str(tmp_path), str(tmp_path / "v1.jpg"))
    mft.install_thumbnail(str(tmp_path), str(tmp_path / "v2.jpg"))
    assert (tmp_path / "thumbnail.jpg").read_bytes() == b"two"
    assert (tmp_path / "thumbnail_pipeline.jpg").read_bytes() == b"pipeline"
