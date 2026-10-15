"""scripts/video_metadata.py: a read-only, bulk replacement for pasting links into mattw.io.

Everything here runs against a fake YouTube client that records each method it is asked for; no
network, no credentials. The fake answers only `list`, and the module is also checked statically
for any write-like attribute (insert/update/delete/set/rate/upload).
"""
import ast
import datetime as dt
import json
import os
import sys

import pytest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPTS)
import video_metadata as vm  # noqa: E402
from youtube_channels import CHANNELS  # noqa: E402

NOW = dt.datetime(2026, 10, 14, 12, 0, tzinfo=dt.timezone.utc)
INK = "UCpgrEMx8diLrw7YNQ6r3uUw"
OTHER = "UCaaaaaaaaaaaaaaaaaaaaaa"
WORLD, HISTORY = CHANNELS["world"]["id"], CHANNELS["history"]["id"]

# The structure of an Ink Explainer description (paraphrased text, same layout).
INK_DESC = """What Did Ancient Humans Do All Day?

Every study and source is linked below.

📚 RESEARCH & SOURCES:

▸ Work-hours fieldwork in the Kalahari — a 1968 chapter on how foragers spent their week.

▸ Persistence hunting — "Endurance running and the evolution of Homo" (2004, Nature) https://doi.org/10.1038/nature03052 — heat let humans outlast prey.

▸ Shell beads — (2004, Science) https://doi.org/10.1126/science.1095905 — ornaments over 70,000 years old.

▸ Firelight talk — (2014, PNAS) https://doi.org/10.1073/pnas.1404212111 — evening conversation turned to stories.

————————————————————

PEOPLE & SITES MENTIONED IN THIS VIDEO:

▸ Blombos Cave — a site on the southern coast of South Africa.

▸ Hohle Fels Cave — a cave in southern Germany where an old flute was found.

————————————————————

🎨 Animation by Ink Explainer

————————————————————

#ancienthumans #huntergatherer #prehistory #history #explainer"""

INK_TITLE = "What Did Ancient Humans Actually Do All Day?"

OUR_DESC = """Asian carp were imported to clean American fish ponds. Then they escaped into connected waterways.

This illustrated documentary follows silver carp and bighead carp.

⏱️ CHAPTERS
0:00 The Pond-Cleaning Problem
0:27 Why America Imported Asian Carp
0:54 Floods Open an Escape Route
1:43 Carp Appear in Monitoring Nets

Subscribe to Bolt Explains the World for illustrated documentaries about human decisions.

📚 SOURCES
National Park Service — Invasive Carp Overview:
https://www.nps.gov/miss/learn/nature/ascarpover.htm

🤖 Created with AI assistance, including synthetic narration and AI-generated illustrations. Disclosed as altered/synthetic content.

#AsianCarp #InvasiveSpecies #SilverCarp"""

OUR_TITLE = "They Imported Carp to Clean Ponds. Then They Escaped."


# ---------------------------------------------------------------------------------------------
# A fake youtube v3 client that records every method name it is asked for
# ---------------------------------------------------------------------------------------------

class _Request:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class _Resource:
    def __init__(self, client, name):
        self._client, self._name = client, name

    def list(self, **kwargs):
        self._client.calls.append((self._name, "list", kwargs))
        return _Request(lambda: self._client.respond(self._name, kwargs))

    def __getattr__(self, method):          # any write the module might try is recorded, then fails
        def refuse(*args, **kwargs):
            self._client.calls.append((self._name, method, kwargs))
            raise AssertionError(f"{self._name}.{method} called")
        return refuse


class FakeYouTube:
    def __init__(self, videos=(), channels=(), uploads=None, privacy=None, captions=None, handles=None):
        self.video_items = {v["id"]: v for v in videos}
        self.channel_items = {c["id"]: c for c in channels}
        self.uploads = uploads or {}          # playlist id -> [video ids]
        self.privacy = privacy or {}          # video id -> privacy for the owner's playlist view
        self.caption_items = captions or {}
        self.handles = handles or {}          # @handle -> channel id
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda: _Resource(self, name)

    def respond(self, name, kw):
        if name == "videos":
            return {"items": [self.video_items[i] for i in kw["id"].split(",") if i in self.video_items]}
        if name == "channels":
            if "forHandle" in kw:
                cid = self.handles.get(kw["forHandle"].lower())
                return {"items": [self.channel_items[cid]] if cid else []}
            if "forUsername" in kw:
                return {"items": []}
            return {"items": [self.channel_items[i] for i in kw["id"].split(",") if i in self.channel_items]}
        if name == "playlistItems":
            ids = self.uploads.get(kw["playlistId"], [])
            start = int(kw.get("pageToken") or 0)
            page = ids[start:start + kw.get("maxResults", 5)]
            nxt = start + len(page)
            return {"items": [{"contentDetails": {"videoId": v},
                               "snippet": {"resourceId": {"videoId": v},
                                           "title": self.video_items.get(v, {}).get("snippet", {}).get("title", "")},
                               "status": {"privacyStatus": self.privacy.get(v, "public")}} for v in page],
                    **({"nextPageToken": str(nxt)} if nxt < len(ids) else {})}
        if name == "videoCategories":
            return {"items": [{"id": i, "snippet": {"title": f"Category {i}"}} for i in kw["id"].split(",")]}
        if name == "captions":
            return {"items": self.caption_items.get(kw["videoId"], [])}
        raise AssertionError(f"unexpected resource {name}")

    def methods(self):
        return {(name, method) for name, method, _ in self.calls}


def video(vid, title, views, *, channel=INK, channel_title="Ink Explainer", days=30, seconds=600,
          tags=(), desc="", loc=None, category="27", likes=None, comments=None, lang="en"):
    published = (NOW - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    item = {
        "id": vid,
        "snippet": {"publishedAt": published, "channelId": channel, "title": title, "description": desc,
                    "channelTitle": channel_title, "tags": list(tags), "categoryId": category,
                    "liveBroadcastContent": "none", "defaultLanguage": lang, "defaultAudioLanguage": lang,
                    "thumbnails": {"high": {"url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"},
                                   "maxres": {"url": f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg"}}},
        "contentDetails": {"duration": f"PT{seconds // 60}M{seconds % 60}S", "caption": "false",
                           "definition": "hd", "licensedContent": True},
        "statistics": {"viewCount": str(views), "likeCount": str(likes if likes is not None else views // 100),
                       "commentCount": str(comments if comments is not None else views // 1000)},
        "status": {"privacyStatus": "public", "license": "youtube", "madeForKids": False},
        "topicDetails": {"topicCategories": ["https://en.wikipedia.org/wiki/Knowledge"]},
    }
    if loc:
        item["localizations"] = loc
    return item


def channel(cid, title, handle, subs=1000):
    return {"id": cid, "snippet": {"title": title, "customUrl": handle, "publishedAt": "2026-04-09T13:19:51Z"},
            "statistics": {"viewCount": "21830151", "subscriberCount": str(subs), "videoCount": "17",
                           "hiddenSubscriberCount": False},
            "contentDetails": {"relatedPlaylists": {"uploads": "UU" + cid[2:]}}}


def ink_world():
    """Ink: 10 long-form uploads (top two questions with many tags) plus 3 Shorts."""
    vids = []
    for i in range(10):
        top = i < 2
        vids.append(video(f"inklong{i:04d}", INK_TITLE if i == 0 else (f"Why Did Rome Fall So Fast? Part {i}" if top
                                                                       else f"The History of Bread Part {i}"),
                          views=[5_000_000, 3_000_000, 900_000, 800_000, 700_000, 600_000, 500_000,
                                 400_000, 100_000, 50_000][i],
                          days=20 + i * 10, seconds=660, desc=INK_DESC if top else "Short description.",
                          tags=[f"tag{j}" for j in (range(12) if top else range(3))],
                          loc={"en": {"title": INK_TITLE, "description": INK_DESC},
                               "de-DE": {"title": "Was taten die Menschen?", "description": "Alle Quellen"}}
                          if top else None))
    for i in range(3):
        vids.append(video(f"inkshrt{i:04d}", f"A Short {i} #shorts", views=[10_000, 20_000, 30_000][i],
                          days=5 + i, seconds=40))
    return vids


def fake_for_ink(extra_videos=(), extra_channels=(), uploads=None, **kw):
    vids = ink_world() + list(extra_videos)
    ups = {"UU" + INK[2:]: [v["id"] for v in vids if v["snippet"]["channelId"] == INK]}
    ups = {**ups, **(uploads or {})}
    return FakeYouTube(videos=vids, channels=[channel(INK, "Ink Explainer", "@inkexplainer96", 132000)]
                       + list(extra_channels), uploads=ups, handles={"@inkexplainer96": INK}, **kw)


# ---------------------------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "https://www.youtube.com/watch?v=49_Ph2q6uIM",
    "https://www.youtube.com/watch?v=49_Ph2q6uIM&t=42s",
    "https://youtube.com/watch?v=49_Ph2q6uIM&si=AbCdEf",
    "https://www.youtube.com/watch?app=desktop&v=49_Ph2q6uIM&list=PLxyz&index=3",
    "https://youtu.be/49_Ph2q6uIM?is=29h9cA5b36avVGRF",
    "https://youtu.be/49_Ph2q6uIM?si=xyz&t=10",
    "youtu.be/49_Ph2q6uIM",
    "www.youtube.com/watch?v=49_Ph2q6uIM",
    "https://www.youtube.com/shorts/49_Ph2q6uIM?feature=share",
    "https://m.youtube.com/watch?v=49_Ph2q6uIM&pp=xyz",
    "https://music.youtube.com/watch?v=49_Ph2q6uIM&feature=share",
    "https://www.youtube.com/embed/49_Ph2q6uIM?start=5",
    "https://www.youtube.com/live/49_Ph2q6uIM?si=x",
    "https://www.youtube-nocookie.com/embed/49_Ph2q6uIM",
    "49_Ph2q6uIM",
    "<https://youtu.be/49_Ph2q6uIM>",
    "  https://youtu.be/49_Ph2q6uIM  ",
])
def test_every_video_url_form_parses_to_the_id(text):
    assert vm.parse_input(text) == ("video", "49_Ph2q6uIM")


@pytest.mark.parametrize("text,expected", [
    ("https://www.youtube.com/channel/UCpgrEMx8diLrw7YNQ6r3uUw", ("channel", INK)),
    ("https://www.youtube.com/channel/UCpgrEMx8diLrw7YNQ6r3uUw/videos", ("channel", INK)),
    ("UCpgrEMx8diLrw7YNQ6r3uUw", ("channel", INK)),
    ("https://www.youtube.com/@inkexplainer96", ("handle", "@inkexplainer96")),
    ("https://www.youtube.com/@inkexplainer96/videos", ("handle", "@inkexplainer96")),
    ("https://youtube.com/@inkexplainer96?si=abc", ("handle", "@inkexplainer96")),
    ("https://m.youtube.com/@inkexplainer96/shorts", ("handle", "@inkexplainer96")),
    ("youtube.com/@inkexplainer96/featured", ("handle", "@inkexplainer96")),
    ("@inkexplainer96", ("handle", "@inkexplainer96")),
    ("@inkexplainer96/videos", ("handle", "@inkexplainer96")),
    ("https://www.youtube.com/user/SomeOldName", ("username", "SomeOldName")),
    ("https://www.youtube.com/c/SomeCustom/videos", ("handle", "@SomeCustom")),
])
def test_channel_url_forms_parse(text, expected):
    assert vm.parse_input(text) == expected


@pytest.mark.parametrize("text", [
    "", "https://vimeo.com/12345", "https://www.youtube.com/playlist?list=PLabc",
    "https://youtu.be/short", "@ab", "hello world", "https://www.youtube.com/",
    "https://www.youtube.com/channel/not-a-channel",
])
def test_unusable_inputs_are_refused(text):
    with pytest.raises(ValueError):
        vm.parse_input(text)


def test_parse_inputs_mixes_dedupes_and_reports_errors():
    parsed = vm.parse_inputs(["https://youtu.be/49_Ph2q6uIM?is=x", "49_Ph2q6uIM", "@inkexplainer96",
                              "https://www.youtube.com/@InkExplainer96/videos", "https://vimeo.com/1",
                              "https://www.youtube.com/channel/" + INK])
    assert parsed["videos"] == ["49_Ph2q6uIM"]
    assert parsed["channels"] == [("handle", "@inkexplainer96"), ("channel", INK)]
    assert len(parsed["errors"]) == 1 and "vimeo" in parsed["errors"][0]


def test_iso_durations():
    assert vm.iso_duration_seconds("PT11M13S") == 673
    assert vm.iso_duration_seconds("PT1H2M3S") == 3723
    assert vm.iso_duration_seconds("P1DT1S") == 86401
    assert vm.iso_duration_seconds("P0D") == 0
    assert vm.iso_duration_seconds(None) == 0


# ---------------------------------------------------------------------------------------------
# Title and description analysers
# ---------------------------------------------------------------------------------------------

def test_question_title_with_a_hook_word():
    t = vm.analyze_title(INK_TITLE)
    assert t["is_question"] and t["form"] == "question" and t["starts_with"] == "what"
    assert t["hook_words"] == ["actually"] and t["case_style"] == "title"
    assert t["words"] == 8 and t["chars"] == len(INK_TITLE) and not t["has_number"]
    assert not t["second_person"] and t["sentences"] == 1 and t["ends_with"] == "?"


def test_our_two_sentence_title():
    t = vm.analyze_title(OUR_TITLE)
    assert t["sentences"] == 2 and t["form"] == "multi-sentence statement" and not t["is_question"]
    assert t["starts_with"] == "other" and t["first_word"] == "they"
    assert vm.analyze_title("Escobar Brought Four Hippos to His Ranch. Colombia Cannot Stop Them.")["has_number_word"]


def test_number_led_two_part_title_with_caps_year_you_emoji_and_hashtag():
    t = vm.analyze_title("7 Lies You Were Taught About 1066 | The NEVER Told Story 🔥 #history")
    assert t["starts_with"] == "number" and t["form"] == "number-led" and t["has_digits"]
    assert t["has_pipe"] and t["two_part"] and t["second_person"] and t["years"] == ["1066"]
    assert t["caps_words"] == ["NEVER"] and t["emoji_count"] == 1 and t["hashtags"] == ["history"]
    assert t["hook_words"] == ["never"]
    assert vm.analyze_title("The Real Reason Rome Fell: Explained")["form"] == "two-part (: | -)"
    assert "real reason" in vm.analyze_title("The Real Reason Rome Fell")["hook_words"]
    assert vm.analyze_title("Is the secret out?")["starts_with"] == "yes/no question"
    assert vm.analyze_title("WHY ROME FELL")["case_style"] == "upper"


def test_ink_explainer_description_structure():
    d = vm.analyze_description(INK_DESC, INK_TITLE)
    assert d["section_headers"] == ["📚 RESEARCH & SOURCES:", "PEOPLE & SITES MENTIONED IN THIS VIDEO:",
                                    "🎨 Animation by Ink Explainer"]
    assert d["has_sources"] and d["has_people_places"]
    assert d["doi_count"] == 3 and d["dois"][0] == "10.1038/nature03052"
    assert d["url_count"] == 3 and d["domains"] == {"doi.org": 3} and d["youtube_links"] == 0
    assert d["hashtags"] == ["ancienthumans", "huntergatherer", "prehistory", "history", "explainer"]
    assert d["hashtag_count"] == 5 and d["hashtags_at_end"]
    assert d["credit_lines"] == ["🎨 Animation by Ink Explainer"]
    assert d["chapter_count"] == 0 and not d["chapters_valid"]
    assert d["separator_lines"] == 3 and d["bullet_lines"] == 6
    assert d["emoji_count"] == 2
    assert not d["ai_disclosure"] and not d["subscribe_cta"] and not d["sponsor_markers"]
    assert d["first_line_echoes_title"]
    assert d["above_fold"] == "What Did Ancient Humans Do All Day? / Every study and source is linked below."
    assert not d["above_fold_has_url"]


def test_our_description_structure():
    d = vm.analyze_description(OUR_DESC, OUR_TITLE)
    assert d["section_headers"] == ["⏱️ CHAPTERS", "📚 SOURCES"]
    assert d["chapter_count"] == 4 and d["chapters_start_at_zero"] and d["chapters_valid"]
    assert d["subscribe_cta"] and d["ai_disclosure"] and d["ai_disclosure_phrase"].lower() == "created with ai"
    assert d["has_sources"] and not d["has_people_places"]
    assert d["hashtags"] == ["AsianCarp", "InvasiveSpecies", "SilverCarp"] and d["hashtags_at_end"]
    assert d["domains"] == {"nps.gov": 1} and d["doi_count"] == 0
    assert not d["credit_lines"]


def test_a_link_label_is_not_a_section_header():
    desc = ("📚 SOURCES\nOklahoma State University:\nhttps://extension.okstate.edu/bees\n\n"
            "Research paper:\nhttps://doi.org/10.1000/xyz1\n\nFurther reading:\n▸ A book (1999)")
    d = vm.analyze_description(desc, "x")
    assert d["section_headers"] == ["📚 SOURCES", "Further reading:"]


def test_chapters_must_start_at_zero_and_ascend():
    d = vm.analyze_description("Intro\n0:15 Start\n1:00 Middle\n2:00 End", "x")
    assert d["chapter_count"] == 3 and not d["chapters_start_at_zero"] and not d["chapters_valid"]
    d = vm.analyze_description("Time stamps\n00:00 Intro\n01:10 Two\n1:02:03 Three", "x")
    assert d["chapters_valid"] and d["section_headers"] == ["Time stamps"]
    d = vm.analyze_description("Intro - 0:00\nMiddle - 1:00\nEnd - 2:00", "x")
    assert d["chapter_count"] == 3 and d["chapters_valid"]
    d = vm.analyze_description("INTRO 0:00\nTHE PROBLEM 1:23\nTHE FIX 4:56\nSources:\n▸ A book (1999)", "x")
    assert d["chapter_count"] == 3 and d["section_headers"] == ["Sources:"]   # chapters are not headers


def test_sponsor_social_support_and_credit_markers():
    desc = ("This video is sponsored by Brilliant. Use code BOLT for 20% off: https://brilliant.org/bolt\n"
            "The Royal Commission reported in 1904.\n"
            "Follow: https://instagram.com/bolt https://www.tiktok.com/@bolt\n"
            "Support: https://www.patreon.com/bolt\n"
            "Music: Epidemic Sound\nScript written by A. Writer\n"
            "Watch next: https://youtu.be/hFk6YVSa0xk\n"
            "Business: hello@example.com\n"
            "👉 Subscribe for more: https://www.youtube.com/@bolt?sub_confirmation=1")
    d = vm.analyze_description(desc, "x")
    assert set(d["sponsor_markers"]) == {"sponsored by", "use code"}
    assert d["social_links"] == ["instagram.com", "tiktok.com"] and d["support_links"] == ["patreon.com"]
    assert d["credit_lines"] == ["Music: Epidemic Sound", "Script written by A. Writer"]
    assert d["youtube_links"] == 2 and d["has_contact_email"] and d["subscribe_cta"]
    assert d["above_fold_has_url"]
    assert "commission" not in " ".join(d["sponsor_markers"])


def test_bulleted_citations_are_not_credits():
    desc = ("RESEARCH & SOURCES\n"
            "▸ Animation in Palaeolithic art: a pre-echo of cinema. Marc Azéma and Florent Rivère, 2012, Antiquity.\n"
            "▸ Research from the University of Cape Town found a link\n"
            "• Footage from the 1936 newsreel: the parade\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Music: A Very Short Introduction (Cook, 2000)\n"
            "Animation by Ink Explainer\n"
            "▸ Music: Epidemic Sound")
    d = vm.analyze_description(desc, "x")
    assert d["credit_lines"] == ["Animation by Ink Explainer", "▸ Music: Epidemic Sound"]
    d = vm.analyze_description("SOURCES & CREDITS\n• Music: Epidemic Sound\n• Narration by A. Voice", "x")
    assert d["credit_lines"] == ["• Music: Epidemic Sound", "• Narration by A. Voice"]


def test_ai_disclosure_needs_a_self_reference():
    for text in ("Try the best AI tools for research at https://x.ai",
                 "This video is about AI-generated misinformation in elections",
                 "AI images of the pope went viral last spring"):
        assert not vm.analyze_description(text, "x")["ai_disclosure"], text
    for text, phrase in (("This video uses AI-generated images.", "uses AI-generated"),
                         ("Narration: AI voice", ": AI voice"),
                         ("AI illustrations were used for the maps", "AI illustrations were used"),
                         ("Made with AI", "Made with AI")):
        d = vm.analyze_description(text, "x")
        assert d["ai_disclosure"] and d["ai_disclosure_phrase"] == phrase, text


def test_empty_description():
    d = vm.analyze_description("", "x")
    assert d["chars"] == 0 and d["lines"] == 0 and d["above_fold"] == "" and not d["section_headers"]


# ---------------------------------------------------------------------------------------------
# Records, medians, outliers, quartiles
# ---------------------------------------------------------------------------------------------

def test_video_record_has_mattw_parity_fields():
    item = video("49_Ph2q6uIM", INK_TITLE, 13_989_604, days=54, seconds=673, desc=INK_DESC,
                 tags=["what did ancient humans do all day", "prehistoric daily life", "human behavior"],
                 likes=76_607, comments=4_283, category="22",
                 loc={"en": {"title": INK_TITLE, "description": INK_DESC},
                      "de-DE": {"title": "Was haben Menschen gemacht?", "description": "Alle Quellen"},
                      "hi": {"title": "प्राचीन मानव", "description": INK_DESC}})
    r = vm.video_record(item, NOW)
    assert r["kind"] == "long" and not r["likely_short"] and r["duration_sec"] == 673
    assert r["age_days"] == 54.0 and r["views_per_day"] == round(13_989_604 / 54, 1)
    assert r["like_rate"] == round(76_607 / 13_989_604, 5) and r["comments"] == 4_283
    assert r["category_name"] == "People & Blogs" and r["topic_categories"] == ["Knowledge"]
    assert r["localizations"] == ["de-DE", "en", "hi"] and r["translated_title_count"] == 2
    assert r["localized_titles_differ"] and r["translated_description_count"] == 1
    assert r["tag_count"] == 3 and r["tag_chars"] == sum(len(t) for t in r["tags"])
    assert r["tag_limit_chars"] == r["tag_chars"] + 2 * 3 + 2
    assert r["thumbnail_size"] == "maxres" and r["thumbnail"].endswith("maxresdefault.jpg")
    assert r["default_audio_language"] == "en" and r["caption_flag"] is False
    assert r["caption_tracks"] is None and r["license"] == "youtube" and r["made_for_kids"] is False


def test_short_detection_and_hidden_stats():
    item = video("short000001", "A thing #Shorts", 500, seconds=59)
    item["statistics"].pop("likeCount")
    r = vm.video_record(item, NOW)
    assert r["kind"] == "short" and r["likely_short"] and r["shorts_hashtag"]
    assert r["likes"] is None and r["like_rate"] is None
    assert vm.video_record(video("long0000001", "Three minutes", 1, seconds=180), NOW)["kind"] == "short"
    assert vm.video_record(video("long0000002", "Over three", 1, seconds=181), NOW)["kind"] == "long"


def test_medians_and_outliers_are_split_by_kind():
    longs = [vm.video_record(video(f"long{i:07d}", f"L{i}", v, days=10), NOW)
             for i, v in enumerate([100, 200, 300, 400, 1000])]
    shorts = [vm.video_record(video(f"shrt{i:07d}", f"S{i}", v, seconds=30, days=10), NOW)
              for i, v in enumerate([10, 20, 30])]
    channels = {}
    vm.add_channel_context(longs + shorts, channels, {INK: longs + shorts})
    assert channels[INK]["median_long"] == 300 and channels[INK]["median_short"] == 20
    assert channels[INK]["n_long"] == 5 and channels[INK]["n_short"] == 3
    assert longs[4]["outlier_multiple"] == round(1000 / 300, 2) and longs[0]["outlier_multiple"] == 0.33
    assert shorts[2]["outlier_multiple"] == 1.5 and shorts[2]["channel_median_views"] == 20
    assert longs[4]["vpd_rank"] == 1 and longs[4]["vpd_rank_of"] == 8 and shorts[0]["vpd_rank"] == 8


def test_too_few_of_a_kind_gives_no_median():
    longs = [vm.video_record(video(f"long{i:07d}", f"L{i}", v), NOW) for i, v in enumerate([100, 200, 300])]
    shorts = [vm.video_record(video(f"shrt{i:07d}", f"S{i}", v, seconds=30), NOW) for i, v in enumerate([10, 20])]
    channels = {}
    vm.add_channel_context(longs + shorts, channels, {INK: longs + shorts})
    assert channels[INK]["median_short"] is None and shorts[0]["outlier_multiple"] is None
    assert channels[INK]["median_long"] == 200 and longs[2]["outlier_multiple"] == 1.5


def test_input_video_outside_fetched_uploads_is_ranked_but_not_in_the_median():
    ups = [vm.video_record(video(f"long{i:07d}", f"L{i}", v), NOW) for i, v in enumerate([100, 200, 300])]
    old = vm.video_record(video("oldvideo001", "Old", 9000, days=400), NOW)
    channels = {}
    vm.add_channel_context([old], channels, {INK: ups})
    assert channels[INK]["median_long"] == 200 and old["outlier_multiple"] == 45.0
    assert old["vpd_rank_of"] == 4 and channels[INK]["median_basis"] == "latest 3 uploads"


def test_quartile_comparison_states_observations_with_n():
    records = [vm.video_record(v, NOW) for v in ink_world()]
    channels = {INK: {"id": INK, "title": "Ink Explainer"}}
    vm.add_channel_context(records, channels, {INK: records})
    q = vm.quartile_comparison(channels[INK], records)
    assert q["n_long"] == 10 and q["q"] == 2
    assert [v["id"] for v in q["top"]] == ["inklong0000", "inklong0001"]
    assert [v["id"] for v in q["bottom"]] == ["inklong0008", "inklong0009"]
    texts = [o["text"] for o in q["observations"]]
    assert "tags: median 12 in top (n=2) vs 3 in bottom (n=2)" in texts
    assert "title is a question: 2/2 in top vs 0/2 in bottom" in texts
    assert "sources/references section: 2/2 in top vs 0/2 in bottom" in texts
    assert "translated titles (localizations): 2/2 in top vs 0/2 in bottom" in texts
    assert not any(t.startswith("duration") for t in texts)          # same duration: nothing to say
    assert any(t.startswith("title form: most often 'question'") for t in texts)
    # one video in a group of two is not a pattern: the hook word sits in 1/2 of the top quartile
    assert not any(t.startswith("title has a hook word") for t in texts)
    assert not any(t.startswith("title opener") for t in texts)       # 'what' 1/2 vs 'the' 2/2
    assert texts[-1].startswith("context, not a difference to copy: age in days")
    first_median = next(i for i, o in enumerate(q["observations"]) if "median" in o["text"])
    assert all("median" not in o["text"] for o in q["observations"][:first_median])
    assert q["observations"][0]["score"] == 1.0


def test_quartile_needs_eight_long_form_uploads():
    records = [vm.video_record(v, NOW) for v in ink_world()[:7]]
    channels = {INK: {"id": INK, "title": "Ink"}}
    vm.add_channel_context(records, channels, {INK: records})
    q = vm.quartile_comparison(channels[INK], records)
    assert "skipped" in q and "7 long-form" in q["skipped"]


# ---------------------------------------------------------------------------------------------
# Fetch layer, quota, read-only guarantees, report
# ---------------------------------------------------------------------------------------------

def test_collect_quota_and_only_list_calls():
    other = video("othervid001", "How Salt Built Empires", 2_000_000, channel=OTHER, channel_title="Other",
                  days=100, tags=["salt"])
    other_ups = [video(f"otherup{i:04d}", f"Other {i}", 100_000 * (i + 1), channel=OTHER,
                       channel_title="Other") for i in range(4)]
    fake = fake_for_ink(extra_videos=[other] + other_ups,
                        extra_channels=[channel(OTHER, "Other", "@other")],
                        uploads={"UU" + OTHER[2:]: [v["id"] for v in other_ups]})
    yt = vm.ReadOnlyYouTube(fake)
    parsed = vm.parse_inputs(["https://youtu.be/othervid001?si=x", "@inkexplainer96"])
    collected = vm.collect(yt, parsed, uploads=50, now=NOW)
    assert fake.methods() <= {("channels", "list"), ("playlistItems", "list"), ("videos", "list")}
    # forHandle (1) + Ink uploads (1 page) + videos (1) + Other channel by id (1) + Other uploads (1) + videos (1)
    assert yt.quota.calls == {"channels": 2, "playlistItems": 2, "videos": 2}
    assert yt.quota.units == 6 and "6 units" in yt.quota.summary()
    assert collected["analyzed"][0] == "othervid001" and len(collected["analyzed"]) == 14
    assert collected["baseline_channels"] == [OTHER] and collected["channels"][OTHER]["source"] == "seen"
    result = vm.analyze(collected, name="t", inputs=["x"], token_channel="world", quota=yt.quota)
    assert result["baseline_video_count"] == 4
    other_record = next(r for r in result["videos"] if r["id"] == "othervid001")
    assert result["channels"][OTHER]["median_long"] == 250_000.0
    assert other_record["outlier_multiple"] == 8.0


def test_upload_paging_respects_the_limit():
    fake = fake_for_ink()
    yt = vm.ReadOnlyYouTube(fake)
    ids = vm.upload_ids(yt, "UU" + INK[2:], 12)
    assert len(ids) == 12 and yt.quota.calls["playlistItems"] == 1
    fake.uploads["UU" + INK[2:]] = [f"v{i:010d}" for i in range(120)]
    yt2 = vm.ReadOnlyYouTube(fake)
    assert len(vm.upload_ids(yt2, "UU" + INK[2:], 120)) == 120 and yt2.quota.calls["playlistItems"] == 3


def test_captions_cost_fifty_units_each_and_are_capped():
    fake = fake_for_ink(captions={"inklong0000": [{"snippet": {"language": "en", "trackKind": "asr", "name": ""}},
                                                  {"snippet": {"language": "de", "trackKind": "standard",
                                                               "name": "Deutsch"}}]})
    yt = vm.ReadOnlyYouTube(fake)
    collected = vm.collect(yt, vm.parse_inputs(["@inkexplainer96"]), captions=True, captions_max=2, now=NOW)
    assert yt.quota.calls["captions"] == 2 and yt.quota.units == 2 * 50 + 3
    assert any("50 units" in w and "listing 2 of 13" in w for w in collected["warnings"])
    tracks = collected["records"]["inklong0000"]["caption_tracks"]
    assert tracks == [{"language": "en", "kind": "asr", "name": "", "audio_track_type": None},
                      {"language": "de", "kind": "standard", "name": "Deutsch", "audio_track_type": None}]
    assert collected["records"]["inklong0005"]["caption_tracks"] is None


def test_unknown_category_uses_one_lookup_call():
    fake = FakeYouTube()
    yt = vm.ReadOnlyYouTube(fake)
    names = vm.fetch_categories(yt, {"27", "99"})
    assert names["27"] == "Education" and names["99"] == "Category 99" and yt.quota.calls == {"videoCategories": 1}
    yt2 = vm.ReadOnlyYouTube(fake)
    vm.fetch_categories(yt2, {"27", "22"})
    assert yt2.quota.units == 0


def test_read_only_client_refuses_everything_but_list():
    yt = vm.ReadOnlyYouTube(FakeYouTube())
    for resource in ("videos", "channels", "playlistItems", "captions", "videoCategories"):
        for method in ("insert", "update", "delete", "rate", "set", "upload", "download"):
            with pytest.raises(PermissionError):
                getattr(getattr(yt, resource)(), method)
    for resource in ("thumbnails", "commentThreads", "playlists", "subscriptions", "watermarks"):
        with pytest.raises(AttributeError):
            getattr(yt, resource)
    assert yt.quota.units == 0


def test_module_never_references_a_write_method():
    path = os.path.join(SCRIPTS, "video_metadata.py")
    tree = ast.parse(open(path, encoding="utf-8").read())
    writes = {"insert", "update", "delete", "set", "rate", "upload", "markAsSpam",
              "setModerationStatus", "reportAbuse", "download"}
    attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not attrs & writes
    strings = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert not strings & writes                 # no getattr(resource, "insert") either
    assert set(vm.UNIT_COST) == {"videos", "channels", "playlistItems", "videoCategories", "captions"}


def _ours_fakes():
    world_vids = [video(f"world{i:06d}", OUR_TITLE if i == 0 else f"The {i}-Bird Mistake That Starved a Nation",
                        1000 * (i + 1), channel=WORLD, channel_title="Bolt explains the world", seconds=300,
                        desc=OUR_DESC, tags=["carp", "invasive species"]) for i in range(3)]
    world_vids.append(video("worldshort1", "The Wolf Mistake #Shorts", 900, channel=WORLD, seconds=20))
    world_vids.append(video("worldpriv01", "Private draft", 0, channel=WORLD, seconds=300))
    history_vids = [video(f"hist{i:07d}", "The Aral Sea Was Drained On Purpose. Here Is Why.", 500, channel=HISTORY,
                          channel_title="Bolt Explains History", seconds=400, desc=OUR_DESC) for i in range(2)]
    world = FakeYouTube(videos=world_vids, channels=[channel(WORLD, "Bolt explains the world", "@boltworld", 50)],
                        uploads={"UU" + WORLD[2:]: [v["id"] for v in world_vids]},
                        privacy={"worldpriv01": "private"})
    history = FakeYouTube(videos=history_vids, channels=[channel(HISTORY, "Bolt Explains History", "@bolthistory", 5)],
                          uploads={"UU" + HISTORY[2:]: [v["id"] for v in history_vids]})
    return world, history


def test_collect_ours_takes_public_long_form_only_through_channel_uploads():
    world, history = _ours_fakes()
    quota = vm.Quota()
    ours = vm.collect_ours({"world": vm.ReadOnlyYouTube(world, quota),
                            "history": vm.ReadOnlyYouTube(history, quota)}, NOW)
    assert [r["id"] for r in ours["world"]["videos"]] == ["world000000", "world000001", "world000002"]
    assert ours["world"]["channel"]["n_uploads"] == 5 and ours["world"]["channel"]["n_public"] == 4
    assert ours["world"]["channel"]["median_long"] == 2000
    assert len(ours["history"]["videos"]) == 2
    assert world.methods() | history.methods() <= {("channels", "list"), ("playlistItems", "list"),
                                                    ("videos", "list")}
    # per channel: channel_uploads' channels.list + 1 playlist page + our channels.list + 1 videos.list
    assert quota.calls == {"channels": 4, "playlistItems": 2, "videos": 2}


def test_report_and_summary_render_every_section():
    fake = fake_for_ink()
    yt = vm.ReadOnlyYouTube(fake)
    collected = vm.collect(yt, vm.parse_inputs(["https://youtu.be/inklong0000?is=x", "@inkexplainer96"]), now=NOW)
    world, history = _ours_fakes()
    ours = vm.collect_ours({"world": vm.ReadOnlyYouTube(world, yt.quota),
                            "history": vm.ReadOnlyYouTube(history, yt.quota)}, NOW)
    result = vm.analyze(collected, name="ink", inputs=["https://youtu.be/inklong0000?is=x", "@inkexplainer96"],
                        token_channel="world", quota=yt.quota, ours=ours)
    report = vm.render_report(result)
    for heading in ("# Video metadata: ink", "## Channels", "## 1. Videos", "## 2. Patterns across the set",
                    "## 3. Top vs bottom quartile by outlier multiple", "## 4. Compared with ours", "## Method"):
        assert heading in report
    assert report.index("### 1. " + INK_TITLE) < report.index("### 2. ")       # the input video comes first
    assert report.index("### 10. ") < report.index("A Short 0 #shorts")        # long-form cards before Shorts
    assert "| title split by ':' '\\|' or a dash |" in report                   # a pipe in a label stays in its cell
    assert report.count("\n### ") == 13 + 1                                    # 13 cards + 1 quartile channel
    assert "tag0, tag1, tag2, tag3" in report                                  # tags verbatim
    assert "localizations (2): de-DE, en" in report                            # languages verbatim
    assert "`📚 RESEARCH & SOURCES:`" in report and "🎨 Animation by Ink Explainer" in report
    assert "tags: median 12 in top (n=2) vs 3 in bottom (n=2)" in report
    assert "| feature | theirs (n=10) | world (n=3) | history (n=2) | ours combined (n=5) |" in report
    assert "AI disclosure line: 0/10 in theirs vs 5/5 in ours" in report
    assert "valid chapters (0:00 start, 3+): 0/10 in theirs vs 5/5 in ours" in report
    summary = vm.render_summary(result, "/tmp/x/report.md")
    assert summary.splitlines()[0].startswith("video_metadata ink: 13 videos (long 10, short 3)")
    assert "API units used: " in summary and "report: /tmp/x/report.md" in summary
    assert "Theirs (n=10) vs ours (n=5):" in summary
    assert len(summary.splitlines()) <= 40
    json.dumps(result, ensure_ascii=False)                                     # serialisable as-is


def test_patterns_count_forms_languages_and_description_features():
    records = [vm.video_record(v, NOW) for v in ink_world()]
    p = vm.patterns(records)
    assert p["n"] == 13 and p["kinds"] == {"long": 10, "short": 3}
    assert p["tags"]["buckets"] == {"1-5": 8, "0": 3, "11-20": 2}
    assert p["title"]["forms"]["question"] == 2 and p["title"]["flags"]["hook word"] == 1
    assert p["languages"]["localization_codes"] == {"en": 2, "de-DE": 2}
    assert p["languages"]["with_translated_titles"] == 2
    assert p["categories"] == {"Education": 13}
    assert p["duration"]["buckets"] == {"8-12 min": 10, "<=1 min": 3}
    assert p["description"]["features"]["sources/references section"] == 2
    assert p["description"]["headers"]["RESEARCH & SOURCES"] == 2


def test_main_writes_report_and_json_and_prints_units(tmp_path, monkeypatch, capsys):
    world, history = _ours_fakes()
    ink = fake_for_ink()
    clients = {"world": ink, "history": history}
    monkeypatch.setattr(vm, "_client", lambda name: clients[name])
    # --compare-ours reuses the lookup client for its own token; give it our World uploads too
    ink.video_items = {**ink.video_items, **world.video_items}
    ink.channel_items = {**ink.channel_items, **world.channel_items}
    ink.uploads = {**ink.uploads, **world.uploads}
    ink.privacy = world.privacy
    code = vm.main(["https://youtu.be/inklong0000?is=x", "@inkexplainer96", "--compare-ours",
                    "--name", "ink explainer", "--out", str(tmp_path)])
    assert code == 0
    out = capsys.readouterr().out
    folder = tmp_path / f"{dt.date.today().isoformat()}_ink-explainer"
    assert (folder / "report.md").exists() and (folder / "videos.json").exists()
    data = json.loads((folder / "videos.json").read_text(encoding="utf-8"))
    assert data["units"] > 0 and len(data["videos"]) == 13 and data["compare_ours"]["n"]["ours"] == 5
    assert f"report: {folder / 'report.md'}" in out and "API units used:" in out
    assert {m for _, m, _ in ink.calls + history.calls} == {"list"}


def test_no_baseline_json_output_and_an_unresolved_username(tmp_path, monkeypatch, capsys):
    other = video("othervid001", "How Salt Built Empires", 2_000_000, channel=OTHER, channel_title="Other")
    fake = FakeYouTube(videos=[other], channels=[channel(OTHER, "Other", "@other")])
    monkeypatch.setattr(vm, "_client", lambda name: fake)
    code = vm.main(["othervid001", "https://www.youtube.com/user/GoneName", "--no-baseline", "--json",
                    "--out", str(tmp_path)])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["name"] == "othervid001" and len(data["videos"]) == 1
    assert data["videos"][0]["outlier_multiple"] is None
    assert data["channels"][OTHER]["median_basis"] == "1 analyzed video(s) only"
    assert "username GoneName did not resolve to a channel" in data["input_errors"]
    assert any("--no-baseline" in w for w in data["warnings"])
    assert data["calls"] == {"channels.list": {"calls": 2, "units": 2}, "videos.list": {"calls": 1, "units": 1}}
    assert fake.methods() == {("channels", "list"), ("videos", "list")}


def test_main_accepts_a_bare_video_id_that_starts_with_a_dash(tmp_path, monkeypatch, capsys):
    other = video("-cBcDeFgHiJ", "How Salt Built Empires", 2_000_000, channel=OTHER, channel_title="Other")
    fake = FakeYouTube(videos=[other], channels=[channel(OTHER, "Other", "@other")])
    monkeypatch.setattr(vm, "_client", lambda name: fake)
    assert vm.main(["-cBcDeFgHiJ", "--no-baseline", "--json", "--out", str(tmp_path)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [v["id"] for v in data["videos"]] == ["-cBcDeFgHiJ"]
    assert data["inputs"] == ["-cBcDeFgHiJ"]


def test_main_refuses_when_no_input_is_usable(capsys):
    assert vm.main(["https://vimeo.com/1"]) == 2
    assert "no usable inputs" in capsys.readouterr().err
