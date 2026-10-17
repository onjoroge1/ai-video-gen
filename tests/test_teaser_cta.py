"""Shorts call to action (2026-10-17): the Chernobyl Short drew 725 views in a day while its film
had 25, and its only pointer was a 2.6 s "FULL STORY ON THE CHANNEL" card. The card now names the
action and stays 4 s; a spoken line in the narrator's voice follows the narration. No network.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import make_teaser_short as mts  # noqa: E402


def test_the_spoken_line_follows_the_narration_and_the_card_covers_it():
    t = mts.cta_timeline(51.71, cta_sec=2.4)
    assert t["cta_start"] == round(51.71 + mts.CTA_GAP_SEC, 3)
    assert t["total"] == round(51.71 + mts.CTA_GAP_SEC + 2.4 + mts.CTA_TAIL_SEC, 3)
    assert t["total"] - t["end_card_at"] == mts.END_CARD_SEC
    assert t["end_card_at"] <= t["cta_start"], "the card is up before the line is spoken"


def test_without_a_spoken_line_the_short_ends_at_the_cut_with_a_longer_card():
    t = mts.cta_timeline(51.71, cta_sec=0.0)
    assert t["total"] == 51.71 and t["cta_start"] == 51.71
    assert round(t["total"] - t["end_card_at"], 3) == mts.END_CARD_SEC >= 4.0


def test_the_card_names_the_action():
    words = [w for line in mts.END_CARD_LINES for w, _ in line]
    assert "FILM:" in words and "LINK" in words and "CHANNEL" not in words
    assert "linked below" in mts.SPOKEN_CTA


def test_audio_appends_the_spoken_line_after_a_gap(monkeypatch):
    calls = []
    monkeypatch.setattr(mts, "_run", lambda cmd: calls.append(cmd))
    mts._audio("film.mp4", 51.71, "out.m4a", cta_mp3="cta.mp3")
    cmd = calls[0]
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "concat=n=4:v=0:a=1" in graph and "atrim=0:51.710" in graph
    assert cmd.count("-i") == 2 and "cta.mp3" in cmd
    calls.clear()
    mts._audio("film.mp4", 51.71, "out.m4a")
    assert "-filter_complex" not in calls[0] and "-t" in calls[0]
