"""The world channel's backfire packaging: title formula, thumbnail grammar, and its scope.

Reference set (2026-09-28): "The 2-Billion Bird Mistake That Starved a Nation", "The $24M Mistake:
Why Killing Every Cat Backfired", "The Rat Bounty Mistake That Created Millions More", each under a
split-frame thumbnail with a red prohibition ring, a yellow arrow and the headline FATAL ERROR.
No provider is called here: the composition is pure Pillow and the title check is pure text.
"""
import os

from PIL import Image

import backfire_packaging as bp

TRANSCRIPT = ("In 1935 Queensland released about one hundred and two toads from Hawaii. "
              "Within decades the toads had spread across 1 million square kilometres.")


def test_applies_only_to_the_backfire_engine_in_landscape(monkeypatch):
    monkeypatch.delenv("BACKFIRE_PACKAGING", raising=False)
    assert bp.applies({"_story_engine": "backfiring_solution"}, "landscape")
    assert bp.applies({"_story_engine": "removed_keystone"}, "landscape")
    assert not bp.applies({"_story_engine": "backfiring_solution"}, "social")
    assert not bp.applies({"_story_engine": "mistaken_verdict"}, "landscape")
    assert not bp.applies({"_story_engine": "accumulating_indictment"}, "landscape")
    assert not bp.applies(None, "landscape")
    monkeypatch.setenv("BACKFIRE_PACKAGING", "0")
    assert not bp.applies({"_story_engine": "backfiring_solution"}, "landscape")


def test_spoken_numbers_reads_compounds_the_way_a_narrator_says_them():
    assert {"102", "1935", "1"} <= bp.spoken_numbers(TRANSCRIPT)
    assert "2400" in bp.spoken_numbers("two thousand four hundred toads were released")
    assert "2000000000" in bp.spoken_numbers("two billion birds")
    assert "24" in bp.spoken_numbers("it cost twenty-four million dollars")
    assert "3000" not in bp.spoken_numbers("three toads and a thousand beetles")


def test_title_formula_and_spoken_numbers():
    assert bp.title_valid("The 102-Toad Mistake That Poisoned Australia's Predators", TRANSCRIPT)
    assert bp.title_valid("The Beetle Mistake That Made Australia Toxic", TRANSCRIPT)
    # A number the narration never speaks is the same defect as an unsupported claim.
    assert not bp.title_valid("The 3,000-Toad Mistake That Poisoned a Continent", TRANSCRIPT)
    # Formula, punctuation and length are all hard rules.
    assert not bp.title_valid("Why Cane Toads Backfired", TRANSCRIPT)
    assert not bp.title_valid("The Toad Mistake: Why It Backfired", TRANSCRIPT)
    assert not bp.title_valid("The Toad Mistake That Backfired?", TRANSCRIPT)
    assert not bp.title_valid("The " + "Very " * 14 + "Long Mistake That Backfired", TRANSCRIPT)
    assert not bp.title_valid("", TRANSCRIPT)


def test_image_prompt_leaves_overlays_to_the_compositor():
    pair = {"crossed_out_subject": "a cane beetle", "crossed_out_scene": "A beetle on cane.",
            "consequence_subject": "cane toads", "consequence_scene": "Hundreds of toads at night."}
    prompt = bp.image_prompt(pair)
    assert "a cane beetle" in prompt and "Hundreds of toads at night." in prompt
    assert "NO text" in prompt and "arrows" in prompt and "No gore" in prompt


def _sample(image, x, y):
    return image.getpixel((int(x), int(y)))


def test_compose_draws_ring_arrow_and_headline(tmp_path):
    bg = tmp_path / "bg.jpg"
    Image.new("RGB", (1536, 1024), (30, 60, 30)).save(bg)
    out = bp.compose(str(bg), str(tmp_path / "thumb.jpg"))
    image = Image.open(out).convert("RGB")
    assert image.size == (1280, 720)
    geo = bp.geometry(1280, 720)
    cx, cy = geo["ring_center"]
    # The ring's right edge is red; its interior is untouched background.
    r, g, b = _sample(image, cx + geo["ring_radius"], cy)
    assert r > 180 and g < 90 and b < 90
    r, g, b = _sample(image, cx + geo["ring_radius"] * 0.5, cy - geo["ring_radius"] * 0.5)
    assert r < 100
    # The arrow tip lands in the consequence panel, painted yellow with a dark outline nearby.
    tip = geo["arrow"][2]
    yellow = 0
    for dx in range(-30, 31, 6):
        for dy in range(-30, 31, 6):
            px = _sample(image, min(1279, tip[0] + dx), min(719, tip[1] + dy))
            if px[0] > 200 and px[1] > 180 and px[2] < 90:
                yellow += 1
    assert yellow > 3
    # The headline band holds both yellow (FATAL) and white (ERROR) pixels.
    bx0, by0, bx1, by1 = geo["headline_box"]
    saw_yellow = saw_white = False
    for x in range(bx0, bx1, 8):
        for y in range(by0, by1, 8):
            px = _sample(image, x, y)
            saw_yellow |= px[0] > 200 and px[1] > 180 and px[2] < 90
            saw_white |= px[0] > 235 and px[1] > 235 and px[2] > 235
    assert saw_yellow and saw_white


def test_compose_headline_fits_inside_the_frame(tmp_path):
    bg = tmp_path / "bg.jpg"
    Image.new("RGB", (400, 225), (0, 0, 0)).save(bg)
    out = bp.compose(str(bg), str(tmp_path / "small.jpg"), tw=400, th=225)
    image = Image.open(out).convert("RGB")
    # Nothing bright touches the far right column: the headline shrank to fit its box.
    assert all(sum(_sample(image, 399, y)) < 200 for y in range(0, 60, 4))
    assert os.path.getsize(out) > 0
