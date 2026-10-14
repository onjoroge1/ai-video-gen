"""Bolt Explains History packaging: its own title patterns and a cause -> consequence thumbnail.

A History film must never go out with World's FATAL ERROR split frame; the two channels share a
pipeline and must still be told apart at feed size. No provider is called here.
"""
import json
import os

from PIL import Image

import backfire_packaging as bp
import explainer_pipeline as ep
import history_packaging as hp

TRANSCRIPT = ("In 1692 the village of Salem accused more than two hundred people. "
              "Nineteen were hanged on the strength of spectral evidence.")


def test_history_style_is_selected_by_env_not_by_engine(monkeypatch):
    monkeypatch.delenv("PACKAGING_STYLE", raising=False)
    assert not hp.applies("landscape")
    monkeypatch.setenv("PACKAGING_STYLE", "history")
    assert hp.applies("landscape") and not hp.applies("social")


def test_title_patterns_and_the_world_brand_words_are_refused():
    assert hp.title_valid("How Salem Hanged Nineteen People on a Dream", TRANSCRIPT)
    assert hp.title_valid("Why a Village Believed Its Children in 1692", TRANSCRIPT)
    assert hp.title_valid("The Spectral Evidence That Hanged Nineteen People", TRANSCRIPT)
    assert not hp.title_valid("The Salem Mistake That Hanged Nineteen", TRANSCRIPT)
    assert not hp.title_valid("The Fatal Village", TRANSCRIPT)
    assert not hp.title_valid("The Salem Witch Trials", TRANSCRIPT)          # "The" needs "That"
    assert not hp.title_valid("Salem: What Really Happened", TRANSCRIPT)
    assert not hp.title_valid("Why Did Salem Hang Them?", TRANSCRIPT)
    assert not hp.title_valid("How Salem Hanged 40 People", TRANSCRIPT)       # 40 is never spoken


def test_headline_and_year_must_be_spoken():
    assert hp.headline_valid("NINETEEN HANGED", TRANSCRIPT)
    assert not hp.headline_valid("HANGED", TRANSCRIPT)                       # too short
    assert not hp.headline_valid("FIFTY PEOPLE WERE HANGED THAT YEAR", TRANSCRIPT)
    assert hp.year_valid("1692", TRANSCRIPT)
    assert not hp.year_valid("1693", TRANSCRIPT) and not hp.year_valid("92", TRANSCRIPT)


def test_compose_band_headline_arrow_and_seal(tmp_path):
    """v2 (operator design, 2026-10-14): band lower-left, stacked headline, red arrow, seal in the sky."""
    bg = tmp_path / "bg.jpg"
    Image.new("RGB", (1536, 1024), (170, 150, 120)).save(bg)
    out = hp.compose(str(bg), str(tmp_path / "t.jpg"), "COTTON DRAINED A SEA", "1692")
    image = Image.open(out).convert("RGB")
    assert image.size == (1280, 720)
    geo = hp.geometry(1280, 720)
    # The band darkens the lower left; the upper right of the scene stays light.
    assert sum(image.getpixel((10, 715))) < 150 and sum(image.getpixel((1270, 10))) > 400
    # Cream headline pixels inside the headline box.
    hx0, hy0, hx1, hy1 = geo["headline_box"]
    cream = sum(1 for x in range(hx0, hx1, 6) for y in range(hy0, hy1, 6)
                if all(c > 200 for c in image.getpixel((x, y))))
    assert cream > 20
    # The arrow is red at the middle of its curve.
    (x0, y0), (x1, y1), (x2, y2) = geo["arrow"]
    mx, my = int(0.25 * x0 + 0.5 * x1 + 0.25 * x2), int(0.25 * y0 + 0.5 * y1 + 0.25 * y2)
    r, g, b = image.getpixel((mx, my))
    assert r > 150 and g < 80 and b < 80
    # The seal is in the top right, clear of the reacting face in the lower right.
    cx, cy = geo["seal_center"]
    assert cx > 1100 and cy < 200
    r, g, b = image.getpixel((cx - int(geo["seal_radius"] * 0.9), cy))
    assert r > 120 and g < 60 and b < 60


def test_the_headline_stacks_with_short_words_riding_along():
    assert hp.stack_headline("COTTON DRAINED A SEA") == ["COTTON", "DRAINED", "A SEA"]
    assert hp.stack_headline("NINETEEN HANGED") == ["NINETEEN", "HANGED"]
    assert len(hp.stack_headline("ONE TWO THREE FOUR")) == 3


def test_compose_without_a_year_draws_no_seal(tmp_path):
    bg = tmp_path / "bg.jpg"
    Image.new("RGB", (1536, 1024), (170, 150, 120)).save(bg)
    image = Image.open(hp.compose(str(bg), str(tmp_path / "t.jpg"), "NINETEEN HANGED")).convert("RGB")
    cx, cy = hp.geometry(1280, 720)["seal_center"]
    r, g, b = image.getpixel((cx, cy))
    assert not (r > 120 and g < 60 and b < 60)


PAIR = {"cause": "A Soviet sluice gate pours water onto cotton under a red poster.",
        "consequence": "A fishing ship lies stranded on cracked seabed.",
        "person": "an elderly fisherman grieving", "link": "the diverted canal",
        "headline": "NINETEEN HANGED"}


def test_image_prompt_is_a_split_frame_and_leaves_text_to_the_compositor():
    prompt = hp.image_prompt(PAIR)
    for part in ("cause", "consequence", "person", "link"):
        assert PAIR[part].rstrip(".") in prompt, part
    assert "torn-paper diagonal" in prompt and "LOWER-LEFT" in prompt and "TOP-RIGHT" in prompt
    assert "NO text" in prompt and "seals" in prompt and "never a real or named" in prompt
    assert "FATAL" not in prompt


def test_the_strategy_asks_for_the_narrations_own_verb():
    assert "never stronger than the narration" in hp._STRATEGY_SYSTEM
    assert '"pairs"' in hp._STRATEGY_SYSTEM and "state symbol" in hp._STRATEGY_SYSTEM


def _fake_image(prompt, output_path, *args, **kwargs):
    Image.new("RGB", (96, 64), (90, 80, 60)).save(output_path)
    return output_path


def test_generate_thumbnail_keeps_the_better_pair_and_reports(monkeypatch, tmp_path):
    monkeypatch.setenv("THUMB_VARIANTS", "2")
    monkeypatch.setattr(ep, "generate_image", _fake_image)
    systems, calls = [], []

    def fake_grade(image_path, title, cost_sink=None, system=None):
        systems.append(system)
        calls.append(image_path)
        keys = ("one_second", "cause_identifiable", "consequence_identifiable", "link_reads",
                "reaction_readable", "headline_legible", "medium_matches", "clean_frame")
        fails = 3 if len(calls) == 1 else 1
        return {"items": {k: i >= fails for i, k in enumerate(keys)}, "fails": fails,
                "redesign_note": "n"}

    monkeypatch.setattr(ep, "grade_thumbnail", fake_grade)
    plan = {"year": "1692", "pairs": [dict(PAIR), dict(PAIR, headline="SPECTRAL EVIDENCE")]}
    report = {}
    out = hp.generate_thumbnail("How Salem Hanged Nineteen People", "Salem", TRANSCRIPT,
                                str(tmp_path), report=report, plan=plan, illustrated=True)
    assert os.path.exists(out)
    assert systems[0] == hp.thumb_grade_system(True) and "cut-paper" in systems[0]
    assert "cause_identifiable" in systems[0] and "top right" in systems[0]
    disk = json.load(open(tmp_path / "packaging.json"))
    assert disk == report and disk["chosen"] == 1 and disk["fails"] == 1
    assert disk["checklist_version"] == "history_v2" and disk["year"] == "1692"
    assert disk["grammar"] == "history_cause_consequence" and "FATAL" not in json.dumps(disk)


def test_an_unspoken_headline_is_dropped_before_any_spend(monkeypatch, tmp_path):
    monkeypatch.setattr(ep, "generate_image", _fake_image)
    monkeypatch.setattr(ep, "grade_thumbnail", lambda *a, **k: {"items": {}, "fails": 0,
                                                                 "redesign_note": ""})
    report = {}
    hp.generate_thumbnail("How Salem Hanged Nineteen People", "Salem", TRANSCRIPT, str(tmp_path),
                          report=report, plan={"year": "1699", "pairs": [
                              dict(PAIR, headline="FIFTY HANGED"), dict(PAIR)]})
    assert [p["headline"] for p in report["pairs"]] == ["NINETEEN HANGED"]
    assert report["year"] == ""          # 1699 is never spoken
