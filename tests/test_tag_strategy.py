"""Researched tags: harvested from the topic's winners, kept only when the film can claim them.

Operator, 2026-10-11: tags moved Shorts from a few views to thousands; they get the same care as
the title. No provider is called here.
"""
import os
import sys

import tag_strategy as ts

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import upload_job  # noqa: E402

TRANSCRIPT = ("Imagine you run a catfish farm and your ponds turn green. In 1973 fish farmers "
              "brought silver and bighead carp from China. Floods carried the carp into the "
              "Mississippi River. Two species spread. Startled by boat motors, silver carp leap. "
              "The Army Corps built an electrical barrier toward the Great Lakes.")
TITLE = "Fish Farmers Brought In Carp to Clean Their Ponds. They Escaped."
PIPELINE = ["asian carp escape", "carp mississippi river"]


def _video(views, tags, channel="Some Channel"):
    return {"id": str(views), "title": "", "channel": channel, "views": views, "tags": tags}


def test_ranked_by_views_and_kept_only_when_the_film_says_every_word():
    videos = [_video(2_000_000, ["silver carp", "bighead carp", "blue catfish", "living fossil"]),
              _video(300_000, ["silver carp", "great lakes", "alligator gar"])]
    picked = ts.select_tags(videos, TRANSCRIPT, TITLE, PIPELINE)
    assert picked["tags"][0] == "silver carp"            # two winners, most views
    assert "bighead carp" in picked["tags"]
    # Said in the film, but on neither its title nor its own tags, and only one winner uses it.
    assert picked["rejected"]["great lakes"] == "off the film's core topic"
    for tag in ("blue catfish", "living fossil", "alligator gar"):
        assert tag not in picked["tags"], tag
        assert tag in picked["rejected"]


def test_generic_words_and_other_channels_names_are_refused():
    videos = [_video(900_000, ["viral", "watch", "river", "vice news", "carp"], channel="VICE News"),
              _video(800_000, ["documentary", "carp"])]
    picked = ts.select_tags(videos, TRANSCRIPT + " Watch the river.", TITLE, PIPELINE)
    assert picked["rejected"]["viral"] == "generic"
    assert picked["rejected"]["vice news"] == "another channel's name"
    assert "watch" not in picked["tags"]                  # said in the film, but off the topic
    assert "carp" in picked["tags"]


def test_a_category_tag_four_winners_share_is_kept():
    videos = [_video(100_000 * (i + 1), ["invasive species", "carp"]) for i in range(4)]
    picked = ts.select_tags(videos, TRANSCRIPT, TITLE, PIPELINE)
    assert "invasive species" in picked["tags"]
    assert picked["sources"]["invasive species"]["rule"] == "consensus"


def test_low_view_videos_do_not_vote_and_limits_hold():
    videos = [_video(1_000, ["silver carp"])]
    assert "silver carp" not in ts.select_tags(videos, TRANSCRIPT, TITLE, [])["tags"]
    many = [_video(1_000_000, [f"carp {i}" for i in range(60)])]
    picked = ts.select_tags(many, TRANSCRIPT + " ".join(str(i) for i in range(60)), TITLE,
                            PIPELINE, short=True)
    assert len(picked["tags"]) <= ts.MAX_TAGS
    assert sum(len(t) for t in picked["tags"]) + 2 * (len(picked["tags"]) - 1) <= ts.MAX_TOTAL_CHARS
    assert set(PIPELINE) <= set(picked["tags"]) and "shorts" in picked["tags"]
    assert all(len(t) <= ts.MAX_TAG_CHARS for t in picked["tags"])


def test_no_harvest_falls_back_to_the_films_own_tags_and_the_brand():
    picked = ts.select_tags([], TRANSCRIPT, TITLE, PIPELINE)
    assert picked["tags"] == PIPELINE + [ts.CHANNEL_TAG]


def test_upload_removes_the_visible_tag_line_from_the_description(tmp_path):
    desc = tmp_path / "description.txt"
    desc.write_text("Hook line.\n\nTags: a, b, c\n\nDisclosure.\n")
    cleaned = upload_job._description_without_tag_line(str(desc))
    assert "Tags:" not in cleaned and "Hook line." in cleaned and "Disclosure." in cleaned
