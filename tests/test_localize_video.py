"""Localized metadata keeps every number, link and chapter; subtitles keep their timings."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import localize_video as lv  # noqa: E402

SOURCE = {"title": "America Brought in 1 Fish. It Took Over 45 States.",
          "description": "Carp escaped.\n\n0:00 The Green Pond\n2:26 Growth\n\nSource: https://www.doi.gov/x"}


def test_a_faithful_translation_passes():
    ok = {"title": "Estados Unidos trajo 1 pez. Terminó invadiendo 45 estados.",
          "description": "Las carpas escaparon.\n\n0:00 El estanque verde\n2:26 Crecimiento\n\n"
                         "Fuente: https://www.doi.gov/x"}
    assert lv.check_translation(SOURCE, ok) == []


def test_lost_numbers_links_and_chapters_are_refused():
    bad = {"title": "Estados Unidos trajo un pez. Invadió el país.",
           "description": "Las carpas escaparon.\n\n0:00 El estanque\n\nFuente: https://doi.gov"}
    problems = " ".join(lv.check_translation(SOURCE, bad))
    assert "lost numbers" in problems and "lost URL" in problems and "2:26" in problems
    assert lv.check_translation(SOURCE, {"title": "x" * 101, "description": SOURCE["description"]})


def test_subtitles_round_trip_with_their_timings():
    srt = "1\n00:00:00,000 --> 00:00:14,880\nFirst line\nsecond line\n\n2\n00:00:14,880 --> 00:00:26,880\nNext.\n"
    cues = lv.parse_srt(srt)
    assert [c["time"] for c in cues] == ["00:00:00,000 --> 00:00:14,880", "00:00:14,880 --> 00:00:26,880"]
    assert cues[0]["text"] == "First line second line"
    assert lv.parse_srt(lv.render_srt(cues)) == cues
