"""Depth-format renderer: time references, the spoken-words card rule, camera maths, and a frame smoke
test on synthetic pictures. No network, no paid calls, no ffmpeg."""
import json

import pytest
from PIL import Image

import depth_film as df


def words():
    seq = "picture this it's spring this is the zone poison a farm horse has 32 pairs this one has 33 a farm horse".split()
    w = [(tok, i * 0.5, i * 0.5 + 0.4) for i, tok in enumerate(df.tokens(" ".join(seq)))]
    return df.Words(w, [(0, 20, " ".join(seq))])


def test_word_references_and_occurrences():
    w = words()
    assert w.find("This") == w.find("this#1")
    assert w.find("This is") > w.find("This")             # "Picture this." comes first
    assert w.find("farm#2") > w.find("farm")
    assert w.find("Poison+0.25") == pytest.approx(w.find("Poison") + 0.25)
    assert w.find("this one-0.1") == pytest.approx(w.find("this one") - 0.1)
    with pytest.raises(df.SpecError):
        w.find("reactor")
    with pytest.raises(df.SpecError):
        w.find("farm#3")


def test_tokens_normalise_apostrophes_and_spelling():
    assert df.tokens("Przewalski’s horse") == ["przewalski", "horse"]
    assert df.tokens("SAND-COLOURED") == df.tokens("sand colored")


def test_relative_time_needs_a_shot():
    assert df.resolve_time("+1.5", None, 10.0) == 11.5
    with pytest.raises(df.SpecError):
        df.resolve_time("+1", None)


def make_spec(tmp_path, overlays):
    job = tmp_path / "job"
    (job / "images").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1536, 1024), (90, 120, 60)).save(job / "images" / "a.jpg")
    spec = {"job": "..", "audio": {"source": "film.mp4", "start": 0, "end": 10.0},
            "points": {"p": [0.5, 0.5]},
            "shots": [{"name": "one", "start": 0, "bg": {"still": "images/a.jpg", "z": [1.0, 1.2]}, "overlays": overlays},
                      {"name": "two", "start": "farm", "vignette": 0.4,
                       "bg": [{"still": "images/a.jpg"}, {"still": "images/a.jpg", "from": "+0.5", "xfade": 0.3, "blur": 4}]}]}
    d = job / "depth"
    d.mkdir(exist_ok=True)
    p = d / "depth.json"
    p.write_text(json.dumps(spec))
    return str(p)


def test_card_rule_flags_unspoken_words(tmp_path):
    ok = df.load(make_spec(tmp_path, [{"text": "POISON", "at": "Poison"}]), words())
    assert ok.check_cards() == []
    bad = df.load(make_spec(tmp_path, [{"text": "DEADLY RADIATION", "at": "Poison"}]), words())
    problems = bad.check_cards()
    assert any("deadly" in p for p in problems) and any("radiation" in p for p in problems)


def test_card_rule_is_local_in_time(tmp_path):
    # "33" is spoken, but not anywhere near t=0.
    r = df.load(make_spec(tmp_path, [{"text": "33", "at": 0}]), words())
    assert r.check_cards(window=2)
    assert not r.check_cards(window=10)   # "33" is spoken at 9.0 s


def test_shots_tile_the_audio_and_frames_render(tmp_path):
    r = df.load(make_spec(tmp_path, [
        {"text": "POISON", "mark": "check", "at": "Poison"},
        {"type": "pin", "pt": "p"},
        {"type": "callout", "pt": [0.4, 0.4], "label": [200, 50], "text": "FARM HORSE", "at": "farm"},
        {"type": "ring", "pt": "p", "at": 0.5},
    ]), words())
    assert r.shots[0]["t0"] == 0 and r.shots[0]["t1"] == r.shots[1]["t0"] and r.shots[-1]["t1"] == 10.0
    for t in (0.0, 2.0, r.shots[1]["t0"] + 0.6, 9.99):
        f = r.frame(t)
        assert f.size == (df.W, df.H)


def test_first_shot_must_start_at_audio_start(tmp_path):
    p = make_spec(tmp_path, [])
    spec = json.load(open(p)); spec["shots"][0]["start"] = 1.0
    open(p, "w").write(json.dumps(spec))
    with pytest.raises(df.SpecError):
        df.load(p, words())


def test_camera_keeps_the_window_inside_the_picture(tmp_path):
    r = df.load(make_spec(tmp_path, []), words())
    src = Image.new("RGB", (1536, 1024))
    g = {"_from": 0, "_to": 1, "z": [1.0, 4.0], "c": [[0.0, 0.0], [1.0, 1.0]]}
    for t in (0, 0.5, 1):
        _, (x0, y0, x1, y1) = r.camera(src, g, t)
        assert x0 >= 0 and y0 >= 0 and x1 <= 1536 + 1e-6 and y1 <= 1024 + 1e-6
        assert (x1 - x0) / (y1 - y0) == pytest.approx(16 / 9)
