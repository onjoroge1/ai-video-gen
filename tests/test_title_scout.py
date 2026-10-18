"""Title scout (2026-10-18): established media excluded, title patterns tagged, pattern lift measured.
No network: the API is faked.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import title_scout as ts  # noqa: E402


def test_established_media_is_excluded_by_size_or_brand():
    assert ts.is_media("CBS Mornings", 50_000)
    assert ts.is_media("HISTORY", 900_000)
    assert ts.is_media("Some Channel", 3_000_000)
    assert not ts.is_media("History Matters", 400_000)
    assert not ts.is_media("The Explorer", 98_000)


def test_title_patterns_from_the_pythons_field():
    assert set(ts.title_patterns("Florida Just Did the Impossible to Stop Pythons")) >= {"new_development", "conflict"}
    p = ts.title_patterns("Giant Pythons Have Overrun Florida. Here's Why.")
    assert {"heres_why", "conflict", "superlative", "statement_then_why"} <= set(p) and "question" not in p
    assert {"question", "conflict", "number"} <= set(ts.title_patterns("Why Florida Can't Stop 20ft Invasive Pythons"))


def test_keyword_position():
    assert ts.keyword_position("Pythons Are Taking Over", ["python"]) == 0
    assert ts.keyword_position("Why Florida Can't Stop Pythons", ["python"]) == 4
    assert ts.keyword_position("Florida Swamps", ["python"]) is None


def test_pattern_lift_compares_with_and_without():
    rows = [{"patterns": ["question"], "ratio_baseline": 2.0}, {"patterns": ["question"], "ratio_baseline": 4.0},
            {"patterns": ["heres_why"], "ratio_baseline": 30.0}, {"patterns": [], "ratio_baseline": 6.0}]
    lift = {p["pattern"]: p for p in ts.pattern_lift(rows)}
    assert lift["question"]["median_with"] == 3.0 and lift["question"]["median_without"] == 18.0
    assert lift["question"]["lift"] == round(3.0 / 18.0, 2)
    assert lift["heres_why"]["lift"] == round(30.0 / 4.0, 2)


class FakeApi:
    units = 0

    def __call__(self, path, **params):
        self.units += 100 if path == "search" else 1
        if path == "search":
            return {"items": [{"id": {"videoId": v}} for v in ("v1", "v2", "v3", "v4")]}
        if path == "videos" and params.get("part", "").startswith("snippet"):
            def video(vid, title, channel, cid, views, dur="PT12M"):
                return {"id": vid, "snippet": {"title": title, "channelTitle": channel, "channelId": cid,
                                               "publishedAt": "2025-06-01T00:00:00Z",
                                               "thumbnails": {"high": {"url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"}}},
                        "statistics": {"viewCount": str(views)}, "contentDetails": {"duration": dur}}
            return {"items": [video("v1", "Florida Just Did the Impossible to Stop Pythons", "The Explorer", "c1", 2_564_307),
                              video("v2", "Python hunters take on Florida's snake problem", "CBS Mornings", "c2", 1_904_670),
                              video("v3", "Why Florida Can't Stop 20ft Pythons", "mintz", "c3", 60_000),
                              video("v4", "Pythons in 60 seconds", "Shorty", "c4", 900_000, dur="PT55S")]}
        if path == "channels":
            subs = {"c1": 98_000, "c2": 3_320_000, "c3": 10_300, "c4": 5_000}
            return {"items": [{"id": c, "statistics": {"subscriberCount": str(subs[c])},
                               "contentDetails": {"relatedPlaylists": {"uploads": f"U{c}"}}} for c in params["id"].split(",")]}
        if path == "playlistItems":
            return {"items": [{"contentDetails": {"videoId": f"b{i}"}} for i in range(8)]}
        if path == "videos":
            base = 100_000 if params["id"].startswith("b") else 1_000
            return {"items": [{"statistics": {"viewCount": str(base)}, "contentDetails": {"duration": "PT10M"}}
                              for _ in params["id"].split(",")]}
        return {}


def test_run_ranks_independent_winners_and_drops_media_and_shorts():
    out = ts.run(FakeApi(), ["florida pythons"], ["python"], orders=("relevance",))
    titles = [w["title"] for w in out["winners"]]
    assert titles[0] == "Florida Just Did the Impossible to Stop Pythons"
    assert all("CBS" not in w["channel"] for w in out["winners"])
    assert any(m["channel"] == "CBS Mornings" for m in out["media_excluded"])
    assert "Pythons in 60 seconds" not in titles, "Shorts are not long-form"
    assert out["winners"][0]["patterns"] and out["winners"][0]["thumbnail"].endswith("hqdefault.jpg")
    assert out["pattern_lift"]
    md = ts.report(out, "burmese-pythons")
    assert "Winning titles outside established media" in md and "CBS Mornings" in md
