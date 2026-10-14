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
    # A single word is a fragment of the topic's name, not a search (audit, 2026-10-13).
    assert picked["rejected"]["carp"] == "single-word fragment" and "carp" not in picked["tags"]


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


def test_fragments_entity_labels_format_words_news_and_hobby_intent_are_refused():
    """Audit 2026-10-13: the bees film carried 'bees', 'killer', 'bee (animal)', and the carp film
    'carp fishing' and 'eating carp'; 'news' and 'documentary' name no topic or audience."""
    videos = [_video(2_000_000, ["silver carp", "carp", "carp fishing", "eating carp",
                                 "asian carp (fish)", "documentary", "news", "explainer video"])]
    picked = ts.select_tags(videos, TRANSCRIPT + " fishing eating", TITLE,
                            PIPELINE + ["documentary", "carp", "educational video"])
    assert "silver carp" in picked["tags"]
    for tag, reason in (("carp", "single-word fragment"), ("carp fishing", "hobby or cooking intent"),
                        ("eating carp", "hobby or cooking intent"), ("asian carp (fish)", "entity label"),
                        ("documentary", "generic"), ("news", "generic"),
                        ("explainer video", "format word"), ("educational video", "format word")):
        assert tag not in picked["tags"], tag
        assert picked["rejected"][tag] == reason, (tag, picked["rejected"][tag])


def test_the_audience_layer_and_brand_keep_their_room_after_a_long_harvest():
    audience = ["unintended consequences", "nature documentary", "invasive species documentary"]
    many = [_video(1_000_000, [f"carp river {i}" for i in range(60)])]
    picked = ts.select_tags(many, TRANSCRIPT + " ".join(str(i) for i in range(60)), TITLE,
                            PIPELINE, short=True, audience=audience)
    tags = picked["tags"]
    assert tags[-5:] == audience + ["shorts", ts.CHANNEL_TAG]      # the template's order, last
    assert len(tags) <= ts.MAX_TAGS and ts.tags_chars(tags) <= ts.MAX_TOTAL_CHARS
    assert {picked["sources"][t]["source"] for t in audience} == {"audience"}


def test_upload_description_applies_the_channel_template():
    text = ("Hook.\n\nTags: a, b, c\n\nSubscribe for clear, no-spin explainers on how the world really "
            "works — new videos regularly.\n\n#one #two #three #four #five\n\n🤖 AI line.")
    out = upload_job.upload_description(text, "world")
    assert "Tags:" not in out and "no-spin" not in out
    assert upload_job.CTAS["world"] in out
    assert "#one #two #three\n" in out and "#four" not in out
    # History has its own line now (2026-10-14); a channel without one keeps the film's.
    history = upload_job.upload_description(text, "history")
    assert upload_job.CTAS["history"] in history and "no-spin" not in history
    assert "no-spin" in upload_job.upload_description(text, "nature")


def test_short_link_goes_above_the_subscribe_line_once():
    desc = f"Hook.\n\n{upload_job.CTAS['world']}\n\n🤖 AI line.\n"
    once = upload_job.add_short_line(desc, "abc123")
    lines = once.splitlines()
    assert lines[lines.index(upload_job.CTAS["world"]) - 1] == "Short version: https://youtube.com/shorts/abc123"
    assert upload_job.add_short_line(once, "abc123") == once


def test_audience_tags_follow_the_direction_and_the_narration(tmp_path):
    job = tmp_path / "carp"
    job.mkdir()
    (job / "direction.txt").write_text("Bolt Explains the World: one sourced animal-intervention backfire.\n")
    assert upload_job.audience_tags(str(job), "the carp became an invasive species") == [
        "unintended consequences", "nature documentary", "invasive species documentary"]
    (job / "direction.txt").write_text("Bolt Explains the World: one sourced intervention backfire "
                                       "(an invention adopted).\n")
    assert upload_job.audience_tags(str(job), "radium paint") == [
        "unintended consequences", "history documentary"]
    assert upload_job.audience_tags(str(job), "x", channel="history") == [
        "history documentary", "dark history"]
    assert upload_job.audience_tags(str(job), "x", channel="nature") == []


def test_a_history_film_carries_its_own_channel_name_not_the_worlds():
    """The first History upload would have been tagged 'bolt explains the world'."""
    picked = ts.select_tags([], TRANSCRIPT, TITLE, PIPELINE, audience=["history documentary"],
                            brand=ts.CHANNEL_TAGS["history"])
    assert picked["tags"][-1] == "bolt explains history"
    assert ts.CHANNEL_TAG not in picked["tags"]
    assert picked["sources"]["bolt explains history"]["source"] == "brand"
    # World is unchanged.
    assert ts.select_tags([], TRANSCRIPT, TITLE, PIPELINE)["tags"][-1] == ts.CHANNEL_TAG
