"""Shorts tags (2026-10-20): the topic's harvested tags the Short can claim, the 480-char budget, the
spec's tags kept. No network: the harvest is faked."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import shorts_tags as st  # noqa: E402
import tag_strategy  # noqa: E402


def test_build_fills_the_budget_with_claimable_tags(tmp_path):
    d = tmp_path / "jobs" / "chernobyl-today" / "shorts" / "opening_x"
    d.mkdir(parents=True)
    (d / "spec.json").write_text(json.dumps({"title": "Why Did She Go Back to Chernobyl's Closed Zone?",
        "tags": ["chernobyl", "exclusion zone", "shorts"],
        "beats": [{"text": "The summer after the 1986 evacuation, her family went back to their farm inside the Chernobyl exclusion zone."},
                  {"text": "About 350,000 people were evacuated after the nuclear disaster."}]}))
    (d / "package.json").write_text(json.dumps({"title": "Why Did She Go Back to Chernobyl's Closed Zone?", "tags": ["chernobyl", "shorts"]}))
    videos = [{"channel": "Some Doc", "views": 900000, "tags": ["chernobyl", "chernobyl exclusion zone", "chernobyl disaster", "nuclear disaster",
                                               "evacuation", "pripyat", "chernobyl today", "minecraft", "funny cats"]}] * 5
    pkg = st.build(str(d), search="chernobyl today", harvest=lambda q: [dict(v, id=str(i)) for i, v in enumerate(videos)])
    tags = pkg["tags"]
    assert "shorts" in tags and tag_strategy.CHANNEL_TAG in tags
    assert "chernobyl exclusion zone" in tags and "nuclear disaster" in tags
    assert "minecraft" not in tags and "funny cats" not in tags, "a tag the Short cannot claim stays out"
    assert tag_strategy.tags_chars(tags) <= tag_strategy.MAX_TOTAL_CHARS
    assert pkg["tags_spec"] == ["chernobyl", "shorts"] and pkg["tags_research"]["search"] == "chernobyl today"


def test_a_failed_harvest_keeps_the_spec_tags(tmp_path):
    d = tmp_path / "jobs" / "x" / "shorts" / "y"
    d.mkdir(parents=True)
    (d / "spec.json").write_text(json.dumps({"title": "What Is Hippo Dung Doing to Rivers?", "tags": ["colombia hippos", "hippo dung"],
                                             "beats": [{"text": "Colombia hippos and their hippo dung change the rivers."}]}))
    (d / "package.json").write_text(json.dumps({"tags": ["hippos"]}))

    def boom(q):
        raise RuntimeError("quota")
    pkg = st.build(str(d), search="hippos", harvest=boom)
    assert "colombia hippos" in pkg["tags"] and "shorts" in pkg["tags"] and "quota" in pkg["tags_research"]["harvest_error"]


def test_fill_uses_the_budget_with_tags_sharing_a_word():
    videos = [{"channel": "Doc", "views": 800000, "tags": ["chernobyl disaster", "chernobyl documentary", "nuclear accident",
               "pripyat ukraine", "radiation zone", "exclusion zone ukraine", "soviet union history", "chernobyl 1986",
               "best minecraft builds", "cooking recipes", "Doc channel"]}]
    out = st.fill(["exclusion zone", "shorts", tag_strategy.CHANNEL_TAG], videos,
                  "the chernobyl exclusion zone was evacuated after the 1986 nuclear accident in ukraine", [])
    assert "chernobyl disaster" in out and "nuclear accident" in out and "pripyat ukraine" not in out
    assert "best minecraft builds" not in out and "cooking recipes" not in out
    assert out[-2:] == ["shorts", tag_strategy.CHANNEL_TAG] and tag_strategy.tags_chars(out) <= 480


def test_other_media_tags_stay_out():
    for t in ("chernobyl hbo", "chernobyl ep 5", "official trailer", "shadow of chernobyl", "vox borders colombia",
              "sneaking into chernobyl", "chernobyl 2019", "chernobil 2", "may 6", "chernobyl tour"):
        assert st.off_media(t), t
    for t in ("chernobyl disaster", "pripyat evacuation", "nuclear accident", "chernobyl 1986s"):
        assert not st.off_media(t), t


def test_one_shared_word_does_not_carry_an_unrelated_tag():
    videos = [{"channel": "Doc", "views": 900000, "tags": ["chernobyl firefighter", "chernobyl soundtrack", "chernobyl bomb",
               "radiation poisoning", "chernobyl evacuation", "chernobyl documentary", "pripyat evacuation", "abandoned chernobyl"]}]
    out = st.fill(["shorts", tag_strategy.CHANNEL_TAG], videos, "about 350,000 people were evacuated from the chernobyl zone around pripyat", [])
    assert {"chernobyl evacuation", "chernobyl documentary", "pripyat evacuation", "abandoned chernobyl"} <= set(out)
    assert not {"chernobyl firefighter", "chernobyl soundtrack", "chernobyl bomb", "radiation poisoning"} & set(out)
