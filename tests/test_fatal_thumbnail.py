"""FATAL thumbnails (2026-10-17): the headline guardrail, the prompt's click rules, the feed sheet and the
install step. No network: the image call is never made here.
"""
import json
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


# ── Hypothesis tests (2026-10-18): control + two one-variable variants, logged and measured ──

def _spec():
    return {"hypothesis_id": "H3", "hypothesis": "The word matters.", "variable": "headline",
            "control": {"name": "A", "first": "FATAL", "word": "COIL", "left": "a snake", "right": "a hunter"},
            "variants": [{"name": "B", "first": "STILL", "word": "WINNING", "note": "a word from the film"},
                         {"name": "C", "first": "", "word": "", "note": "no text"}]}


def test_a_headline_test_reuses_one_picture():
    plan = mft.variant_plan(_spec())
    assert [p["name"] for p in plan] == ["A", "B", "C"]
    assert [p["reuse"] for p in plan] == [False, True, True]
    spec = _spec()
    spec["variants"][0]["right"] = "a face in danger"
    assert [p["reuse"] for p in mft.variant_plan(spec)] == [False, False, True]


def test_a_test_is_exactly_three_thumbnails():
    spec = _spec()
    spec["variants"] = spec["variants"][:1]
    try:
        mft.variant_plan(spec)
    except ValueError:
        pass
    else:
        raise AssertionError("two thumbnails is not a test")


def test_no_text_is_a_valid_headline():
    assert mft.headline_ok("", "")
    assert not mft.headline_ok("FATAL", "")


def test_fatal_variants_obey_the_guardrail(tmp_path, monkeypatch):
    (tmp_path / "transcript.txt").write_text("The pythons spread across the Everglades.")
    monkeypatch.setattr(mft, "background", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    try:
        mft.build_variants(str(tmp_path), _spec(), "H3", log_path=str(tmp_path / "log.md"))
    except SystemExit as stop:
        assert "FATAL refused" in str(stop)
    else:
        raise AssertionError("FATAL was not refused")


def test_variants_are_built_logged_and_measured(tmp_path, monkeypatch):
    (tmp_path / "transcript.txt").write_text("The hunters killed thousands of snakes.")
    bg = tmp_path / "bg.png"
    Image.new("RGB", (1536, 1024), (40, 60, 40)).save(bg)
    calls = []
    monkeypatch.setattr(mft, "background", lambda job, name, *a: (calls.append(name), (str(bg), "p"))[1])
    log = tmp_path / "log.md"
    out = mft.build_variants(str(tmp_path), _spec(), "H3", log_path=str(log))
    assert calls == ["H3_A"], "one image for a headline-only test"
    assert all(os.path.isfile(f) for f in out["files"].values()) and os.path.isfile(out["feed"])
    text = log.read_text()
    assert "— H3: The word matters." in text and "(no text)" in text and "| C |" in text
    mft.record_result(str(tmp_path), "H3", "winner", "B", {"A": 31.0, "B": 44.0, "C": 25.0}, log_path=str(log))
    assert "RESULT `H3`: winner; winner B; shares A 31.0%, B 44.0%, C 25.0%" in log.read_text()
    record = json.loads((tmp_path / "thumbs" / "H3.json").read_text())
    assert record["result"]["winner"] == "B"


def test_the_next_hypothesis_is_the_first_one_not_started(tmp_path):
    log = tmp_path / "log.md"
    assert mft.next_hypothesis(str(log))[0] == "H1"
    log.write_text("## 2026-10-18 chernobyl-today — H1: title vs backstory\n")
    assert mft.next_hypothesis(str(log))[0] == "H2"
