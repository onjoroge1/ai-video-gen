"""Outlier scout (2026-10-16): demand first. A video counts as an outlier when it beats its own
channel's baseline, not when it is merely big. No network: a fake API serves canned responses.
"""
import datetime as dt
import os
import sys
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import outlier_scout as osc  # noqa: E402

NOW = dt.datetime(2026, 10, 17, tzinfo=dt.timezone.utc)


def _video(vid, views, channel, days_ago=100, duration="PT12M", title=None):
    published = (NOW - dt.timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": vid, "snippet": {"title": title or f"video {vid}", "channelId": channel,
                                   "channelTitle": f"chan {channel}", "publishedAt": published},
            "statistics": {"viewCount": str(views), "commentCount": "10"},
            "contentDetails": {"duration": duration}}


class FakeApi:
    """search -> ids per query; videos/channels/playlistItems/commentThreads from tables."""

    def __init__(self, search, videos, channels, uploads, comments=None, fail=None):
        self.search, self.videos, self.channels, self.uploads = search, videos, channels, uploads
        self.comments, self.fail, self.units, self.calls = comments or {}, fail or {}, 0, []

    def __call__(self, path, **p):
        self.units += osc.COST.get(path, 1)
        self.calls.append(path)
        if path in self.fail:
            raise urllib.error.HTTPError("u", self.fail[path], "x", {}, None)
        if path == "search":
            return {"items": [{"id": {"videoId": v}} for v in self.search.get(p["q"], [])]}
        if path == "videos":
            return {"items": [self.videos[i] for i in p["id"].split(",") if i in self.videos]}
        if path == "channels":
            return {"items": [{"id": c, "statistics": {"subscriberCount": str(s)},
                               "contentDetails": {"relatedPlaylists": {"uploads": f"UU{c}"}}}
                              for c, s in self.channels.items() if c in p["id"].split(",")]}
        if path == "playlistItems":
            return {"items": [{"contentDetails": {"videoId": v}} for v in self.uploads.get(p["playlistId"], [])]}
        if path == "commentThreads":
            return {"items": [{"snippet": {"topLevelComment": {"snippet": {"textDisplay": t}}}}
                              for t in self.comments.get(p["videoId"], [])]}
        raise AssertionError(path)


def _world():
    videos = {
        # small channel, its usual uploads get ~20K: a 2M video is a 100x outlier
        "out1": _video("out1", 2_000_000, "small"),
        # big channel, usual 1.5M: a 2M video is NOT an outlier despite being big
        "big1": _video("big1", 2_000_000, "big"),
        # under the view floor
        "tiny": _video("tiny", 50_000, "small"),
        # a Short: never counts
        "short": _video("short", 5_000_000, "small", duration="PT45S"),
    }
    for k in range(8):
        videos[f"s{k}"] = _video(f"s{k}", 20_000 + k * 1000, "small")
        videos[f"b{k}"] = _video(f"b{k}", 1_500_000 + k * 1000, "big")
    uploads = {"UUsmall": ["out1"] + [f"s{k}" for k in range(8)],
               "UUbig": ["big1"] + [f"b{k}" for k in range(8)]}
    return FakeApi(search={"why can't anyone live there": ["out1", "big1", "tiny", "short"],
                           "still burning today": ["out1"]},
                   videos=videos, channels={"small": 6_500, "big": 3_000_000}, uploads=uploads,
                   comments={"out1": ["Why did they never clean it up?", "great video", "How long until people return?"]})


def test_an_outlier_beats_its_own_channel_not_just_a_view_count():
    api = _world()
    seeds = [{"group": "world", "q": "why can't anyone live there"}, {"group": "world", "q": "still burning today"}]
    res = osc.run(api, seeds, now=NOW, log=lambda *a: None)
    ids = [r["video_id"] for r in res["outliers"]]
    assert ids == ["out1"], ids
    top = res["outliers"][0]
    assert top["baseline"] == 23_500.0            # median of the 8 other long-form uploads
    assert top["ratio_baseline"] > 80
    assert sorted(top["seeds"]) == ["still burning today", "why can't anyone live there"]
    assert top["groups"] == ["world"]


def test_the_outlier_itself_is_excluded_from_its_channel_baseline():
    api = _world()
    b = osc.channel_baseline(api, "UUsmall", exclude={"out1"})
    assert b == 23_500.0
    assert osc.channel_baseline(api, "UUsmall", exclude=set()) == 24_000.0  # out1 would drag it up


def test_viewer_questions_are_collected_for_the_top_outliers():
    res = osc.run(_world(), [{"group": "world", "q": "why can't anyone live there"}], now=NOW,
                  log=lambda *a: None)
    assert res["outliers"][0]["viewer_questions"] == ["Why did they never clean it up?",
                                                      "How long until people return?"]


def test_shorts_and_small_videos_never_count():
    api = _world()
    rows = {v: osc.score(api.videos[v], {"subs": 6_500}, None, NOW) for v in ("short", "tiny")}
    assert not osc.is_outlier(rows["short"], 200_000, 5)
    assert not osc.is_outlier(rows["tiny"], 200_000, 5)


def test_without_a_baseline_the_subscriber_ratio_decides():
    row = osc.score(_video("x", 400_000, "c"), {"subs": 10_000}, None, NOW)
    assert row["ratio_baseline"] is None and row["ratio_subs"] == 40.0
    assert osc.is_outlier(row, 200_000, 5)


def test_quota_is_counted_and_a_quota_error_stops_searching():
    api = _world()
    osc.run(api, [{"group": "world", "q": "why can't anyone live there"}], now=NOW, log=lambda *a: None)
    assert api.units >= 100 and api.calls.count("search") == 1
    failing = _world(); failing.fail = {"search": 403}
    res = osc.run(failing, [{"q": "a"}, {"q": "b"}], now=NOW, log=lambda *a: None)
    assert failing.calls.count("search") == 1 and res["seeds"][0]["error"] == "HTTP 403"


def test_disabled_comments_do_not_break_the_run():
    api = _world(); api.fail = {"commentThreads": 403}
    res = osc.run(api, [{"group": "world", "q": "why can't anyone live there"}], now=NOW, log=lambda *a: None)
    assert res["outliers"][0]["viewer_questions"] == []


def test_off_topic_titles_are_dropped_before_any_baseline_is_bought():
    api = _world()
    api.videos["out1"]["snippet"]["title"] = "Burning Spear: reggae legend tribute"
    seeds = [{"group": "world", "q": "still burning today", "must": ["underground+fire", "radiation"]}]
    res = osc.run(api, seeds, now=NOW, log=lambda *a: None)
    assert res["outliers"] == [] and "playlistItems" not in api.calls


def test_must_alternatives_join_words_with_plus():
    assert osc.title_matches("The Fire That Has Burned Underground for 60 Years", ["underground+fire"])
    assert not osc.title_matches("Underground cities", ["underground+fire"])
    assert osc.title_matches("anything", None)


def test_shorts_are_reported_apart_from_long_form():
    res = osc.run(_world(), [{"group": "world", "q": "why can't anyone live there"}], now=NOW, log=lambda *a: None)
    assert [r["video_id"] for r in res["shorts_outliers"]] == ["short"]
    assert "short" not in [r["video_id"] for r in res["outliers"]]
