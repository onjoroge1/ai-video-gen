"""The world channel's backfire packaging: title formula, thumbnail grammar, and its scope.

Reference set (2026-09-28): "The 2-Billion Bird Mistake That Starved a Nation", "The $24M Mistake:
Why Killing Every Cat Backfired", "The Rat Bounty Mistake That Created Millions More", each under a
split-frame thumbnail with a red prohibition ring, a yellow arrow and the headline FATAL ERROR.
No provider is called here: the composition is pure Pillow and the title check is pure text.
"""
import json
import os

import pytest
from PIL import Image

import backfire_packaging as bp
import explainer_pipeline as ep


@pytest.fixture(autouse=True)
def _no_headline_provider(monkeypatch):
    """No provider is called here: regenerated headlines are stubbed unless a test supplies them."""
    monkeypatch.setattr(bp, "propose_headlines", lambda *a, **k: [])

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


def test_title_is_a_story_sentence_and_numbers_are_spoken():
    """v3 (2026-10-11): a plain sentence and a turn, not the "The <X> Mistake That <Y>" label."""
    assert bp.title_valid("Australia Released 102 Toads to Save Its Sugar. Big Mistake.", TRANSCRIPT)
    assert bp.title_valid("Queensland Brought In Toads to Eat Beetles (Then They Spread)", TRANSCRIPT)
    # The old label formula is refused now, with or without a valid number.
    assert not bp.title_valid("The 102-Toad Mistake That Poisoned Australia's Predators", TRANSCRIPT)
    # A number the narration never speaks is the same defect as an unsupported claim.
    assert not bp.title_valid("Australia Released 3,000 Toads. Big Mistake.", TRANSCRIPT)
    # Shape, punctuation and length are hard rules.
    assert not bp.title_valid("Why Cane Toads Backfired", TRANSCRIPT)
    assert not bp.title_valid("Toads: Why It Backfired. Badly.", TRANSCRIPT)
    assert not bp.title_valid("Did the Toads Backfire? Yes.", TRANSCRIPT)
    assert not bp.title_valid("Australia " + "Really " * 12 + "Released Toads. Oops.", TRANSCRIPT)
    assert not bp.title_valid("", TRANSCRIPT)


def test_headline_is_per_film_with_a_fixed_fallback():
    title = "Australia Released 102 Toads to Save Its Sugar. Big Mistake."
    assert bp.headline_words("the beetles won", title, TRANSCRIPT) == ("THE", "BEETLES", "WON")
    assert bp.headline_words("IT BACKFIRED", title, TRANSCRIPT) == ("IT", "BACKFIRED")
    for bad in ("", "WON", "THIS IS FAR TOO LONG", "BIG MISTAKE", "3000 TOADS", "WHY? NOW"):
        assert bp.headline_words(bad, title, TRANSCRIPT) == bp.HEADLINE, bad


def test_compose_three_word_headline_first_word_yellow(tmp_path):
    bg = tmp_path / "bg.jpg"
    Image.new("RGB", (1536, 1024), (30, 60, 30)).save(bg)
    out = bp.compose(str(bg), str(tmp_path / "t.jpg"), headline=("THE", "LOCUSTS", "WON"))
    image = Image.open(out).convert("RGB")
    bx0, by0, bx1, by1 = bp.geometry(1280, 720)["headline_box"]
    yellow = white = 0
    for x in range(bx0, bx1, 6):
        for y in range(by0, by1, 6):
            px = _sample(image, x, y)
            yellow += px[0] > 200 and px[1] > 180 and px[2] < 90
            white += px[0] > 235 and px[1] > 235 and px[2] > 235
    assert yellow > 5 and white > yellow, (yellow, white)


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


def test_illustrated_prompt_asks_for_one_medium_and_photoreal_still_asks_for_photography():
    """Two media in one prompt produced a photo-textured drawing with neither medium's contrast.

    The illustrated prompt opened with "never a photograph" and closed with "documentary photography
    look ... no cartoon or vector styling"; the model split the difference. The photoreal branch
    is the delivered grammar and keeps every word.
    """
    pair = {"crossed_out_subject": "a cane beetle", "crossed_out_scene": "A beetle on cane.",
            "consequence_subject": "cane toads", "consequence_scene": "Hundreds of toads at night."}
    drawn = bp.image_prompt(pair, illustrated=True)
    photo = bp.image_prompt(pair)
    assert "photography" not in drawn.lower()
    assert "No cartoon or vector styling" not in drawn
    assert "gouache" in drawn and "cut-paper shapes" in drawn
    assert "Documentary photography look" in photo
    assert photo.endswith("No cartoon or vector styling.")
    # Everything that is not the medium is shared: overlays stay with the compositor in both.
    for prompt in (drawn, photo):
        assert "NO text" in prompt and "do NOT draw any prohibition sign" in prompt


_PAIRS = [
    {"crossed_out_subject": "a cane beetle", "crossed_out_scene": "A beetle on cane.",
     "consequence_subject": "cane toads", "consequence_scene": "Hundreds of toads at night."},
    {"crossed_out_subject": "a cane toad", "crossed_out_scene": "A toad on a road.",
     "consequence_subject": "a dead quoll", "consequence_scene": "A quoll beside a toad."},
]


def _fake_image(prompt, output_path, *args, **kwargs):
    Image.new("RGB", (96, 64), (90, 120, 60)).save(output_path)
    return output_path


def _verdict(fails, note):
    keys = ("one_second", "mistake_identifiable", "fear_foreground",
            "one_subject_per_panel", "headline_legible", "single_ring", "medium_matches",
            "consequence_not_title_echo")
    return {"items": {k: i >= fails for i, k in enumerate(keys)}, "fails": fails,
            "redesign_note": note}


def test_generate_thumbnail_writes_packaging_json_with_the_whole_verdict(monkeypatch, tmp_path):
    """Every shipped thumbnail logged "weak (4/8)" and nothing recorded WHICH four or the fix.

    write_report had no caller in the pipeline, so jobs/<job>/packaging.json never existed; the
    per-item verdict was dropped at the rendered.append line. Both variants' items and the
    grader's redesign_note must reach disk, alongside the keys explainer_pipeline reads.
    """
    monkeypatch.setenv("THUMB_VARIANTS", "2")
    monkeypatch.setattr(ep, "generate_image", _fake_image)
    monkeypatch.setattr(bp, "detect_drawn_ring", lambda *a, **k: False)
    calls = []

    def fake_grade(image_path, title, cost_sink=None):      # today's signature: no `system`
        calls.append(image_path)
        return _verdict(4, "subject too small") if len(calls) == 1 else _verdict(1, "fine")

    monkeypatch.setattr(ep, "grade_thumbnail", fake_grade)
    report = {}
    out = bp.generate_thumbnail("The 102-Toad Mistake That Poisoned Australia's Predators",
                                "cane toads", TRANSCRIPT, str(tmp_path), report=report,
                                pairs=_PAIRS)
    assert os.path.exists(out) and len(calls) == 2
    path = os.path.join(str(tmp_path), "packaging.json")
    assert os.path.exists(path), "packaging.json was not written by the pipeline path"
    with open(path) as handle:
        disk = json.load(handle)
    assert disk == report
    # The keys explainer_pipeline reads keep their shapes; the better variant was chosen.
    assert disk["fails"] == 1 and disk["weak"] is False and disk["qa"] == "ok"
    assert disk["chosen"] == 1 and disk["variants"] == 2 and disk["headline"] == "FATAL ERROR"
    # The whole verdict per variant, not just the count.
    assert [p["fails"] for p in disk["pairs"]] == [4, 1]
    assert [p["redesign_note"] for p in disk["pairs"]] == ["subject too small", "fine"]
    for entry in disk["pairs"]:
        assert isinstance(entry["items"], dict) and len(entry["items"]) == 8
        assert sum(not v for v in entry["items"].values()) == entry["fails"]
    # A grader without a `system` keyword is called as before and the report says which list ran.
    assert disk["checklist_version"] == "science_v1"


def test_backfire_checklist_reaches_a_grader_that_accepts_one(monkeypatch, tmp_path):
    """The science checklist fails the split-frame grammar by construction (item 7: "NOT photo").

    The Backfire list is passed only when grade_thumbnail's signature names `system`; the report
    records which checklist produced the score so 4/8 is a comparable number again.
    """
    monkeypatch.setenv("THUMB_VARIANTS", "1")
    monkeypatch.setattr(ep, "generate_image", _fake_image)
    monkeypatch.setattr(bp, "detect_drawn_ring", lambda *a, **k: False)
    systems = []

    def fake_grade(image_path, title, cost_sink=None, system=None):
        systems.append(system)
        return _verdict(2, "ring clips the subject")

    monkeypatch.setattr(ep, "grade_thumbnail", fake_grade)
    report = {}
    bp.generate_thumbnail("The 102-Toad Mistake That Poisoned Australia's Predators", "cane toads",
                          TRANSCRIPT, str(tmp_path), report=report, pairs=_PAIRS[:1],
                          illustrated=True)
    assert systems == [bp.thumb_grade_system(True)]
    assert systems[0].startswith(bp.BACKFIRE_THUMB_GRADE_SYSTEM)
    assert "cut-paper illustration" in systems[0] and "photoreal" in bp.thumb_grade_system(False)
    assert report["checklist_version"] == "backfire_v2"
    assert report["fails"] == 2 and report["pairs"][0]["redesign_note"] == "ring clips the subject"
    # Same return contract as explainer_pipeline._THUMB_GRADE_SYSTEM: 8 named booleans, a count,
    # one note -- so rep["fails"] / rep["weak"] / rep["qa"] mean the same thing under both lists.
    for item in ("one_second", "mistake_identifiable", "fear_foreground",
                 "one_subject_per_panel", "headline_legible", "single_ring", "medium_matches",
                 "consequence_not_title_echo"):
        assert item in bp.BACKFIRE_THUMB_GRADE_SYSTEM
    numbered = [line.split(". ", 1)[0] for line in bp.BACKFIRE_THUMB_GRADE_SYSTEM.split("\n")
                if line[:1].isdigit()]
    assert numbered == [str(i) for i in range(1, 9)], numbered
    for word in ('"items"', '"fails"', '"redesign_note"'):
        assert word in bp.BACKFIRE_THUMB_GRADE_SYSTEM and word in ep._THUMB_GRADE_SYSTEM


def test_v2_left_is_the_act_and_right_is_one_frightened_invented_person():
    """YouTube's review of the bee film read a ringed lone bee as pest control (2026-10-09).

    The ring circles the act of the mistake and has no slash; the right panel carries the fear.
    """
    pair = {"crossed_out_subject": "bees escaping a hive",
            "crossed_out_scene": "A gloved hand lifts a hive screen as bees climb out.",
            "consequence_subject": "a dark swarm",
            "consequence_scene": "A farmer recoils as a swarm closes in."}
    for prompt in (bp.image_prompt(pair), bp.image_prompt(pair, illustrated=True)):
        assert "ONE frightened" in prompt and "No faces in the left panel" in prompt
        assert "never a real, named or famous" in prompt
        assert "people's faces" not in prompt
    assert "MISTAKE IN ACTION" in bp._STRATEGY_SYSTEM and "FEAR" in bp._STRATEGY_SYSTEM
    assert "pest control" in bp.BACKFIRE_THUMB_GRADE_SYSTEM


def test_v2_ring_has_no_slash_unless_asked(tmp_path):
    bg = tmp_path / "bg.jpg"
    Image.new("RGB", (1536, 1024), (30, 60, 30)).save(bg)
    plain = Image.open(bp.compose(str(bg), str(tmp_path / "plain.jpg"))).convert("RGB")
    slashed = Image.open(bp.compose(str(bg), str(tmp_path / "slash.jpg"), slash=True)).convert("RGB")
    cx, cy = bp.geometry(1280, 720)["ring_center"]
    assert plain.getpixel((cx, cy))[0] < 100, "the ring's centre should be untouched background"
    assert slashed.getpixel((cx, cy))[0] > 180, "slash=True should still draw the diagonal"


def test_headline_may_not_repeat_a_title_word():
    """Audit 2026-10-13: "FROM FOUR" and "CANNOT STOP THEM" only restated the hippo title."""
    title = "Escobar Brought Four Hippos to His Ranch. Colombia Cannot Stop Them."
    transcript = "Four hippos. That is a species claiming a whole river for itself."
    assert bp.headline_words("FROM FOUR", title, transcript) == bp.HEADLINE
    assert bp.headline_words("CANNOT STOP THEM", title, transcript) == bp.HEADLINE
    assert bp.headline_words("HIPPO NATION", title, transcript) == bp.HEADLINE
    assert bp.headline_words("RIVER TAKEN", title, transcript) == ("RIVER", "TAKEN")


def test_failed_headlines_are_regenerated_before_falling_back(monkeypatch, tmp_path):
    monkeypatch.setattr(ep, "generate_image", _fake_image)
    monkeypatch.setattr(bp, "detect_drawn_ring", lambda *a, **k: False)
    monkeypatch.setattr(ep, "grade_thumbnail", lambda *a, **k: _verdict(0, "fine"))
    asked = []

    def fake_propose(title, transcript, rejected=None, cost_sink=None):
        asked.append(list(rejected or []))
        return ["BIG MISTAKE", "BEETLES WON"]          # the first echoes the title

    monkeypatch.setattr(bp, "propose_headlines", fake_propose)
    pairs = [dict(_PAIRS[0], headline="BIG MISTAKE"), dict(_PAIRS[1], headline="SAVE ITS SUGAR")]
    report = {}
    bp.generate_thumbnail("Australia Released 102 Toads to Save Its Sugar. Big Mistake.",
                          "cane toads", TRANSCRIPT, str(tmp_path), report=report, pairs=pairs)
    assert len(asked) == 1 and asked[0] == ["BIG MISTAKE", "SAVE ITS SUGAR"]   # asked once per film
    assert report["headline"] == "BEETLES WON" and report["headline_fallback"] is False
    assert report["headlines_regenerated"] == ["BIG MISTAKE", "BEETLES WON"]


def test_another_pairs_headline_is_used_before_asking_again(monkeypatch, tmp_path):
    monkeypatch.setattr(ep, "generate_image", _fake_image)
    monkeypatch.setattr(bp, "detect_drawn_ring", lambda *a, **k: False)
    monkeypatch.setattr(ep, "grade_thumbnail", lambda *a, **k: _verdict(0, "fine"))
    monkeypatch.setattr(bp, "propose_headlines", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    pairs = [dict(_PAIRS[0], headline="BIG MISTAKE"), dict(_PAIRS[1], headline="THE BEETLES WON")]
    report = {}
    bp.generate_thumbnail("Australia Released 102 Toads to Save Its Sugar. Big Mistake.",
                          "cane toads", TRANSCRIPT, str(tmp_path), report=report, pairs=pairs)
    assert {p["headline_used"] for p in report["pairs"]} == {"THE BEETLES WON"}


def test_headline_sits_on_a_dark_band_in_the_consequence_panel(tmp_path):
    bg = tmp_path / "bg.jpg"
    Image.new("RGB", (1536, 1024), (200, 210, 230)).save(bg)       # a pale sky
    banded = Image.open(bp.compose(str(bg), str(tmp_path / "b.jpg"), headline=("RIVER", "TAKEN")))
    plain = Image.open(bp.compose(str(bg), str(tmp_path / "p.jpg"), headline=("RIVER", "TAKEN"),
                                  band=False))
    point = (1270, 8)                                             # top-right corner, no text
    assert sum(banded.convert("RGB").getpixel(point)) < sum(plain.convert("RGB").getpixel(point)) - 150
    # The left panel and the lower right panel are untouched.
    for spot in ((40, 8), (1200, 650)):
        assert abs(sum(banded.convert("RGB").getpixel(spot)) - sum(plain.convert("RGB").getpixel(spot))) < 12
