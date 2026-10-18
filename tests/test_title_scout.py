"""Title scout (2026-10-18): established media excluded, title forms coded, every video scored against
its channel at the time, and a comparison set with the flops in it. No network: the API is faked.
"""
import datetime as dt
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


def test_title_form_matches_the_reports_coding():
    # Direct questions: a question mark, or an inverted auxiliary even without one.
    assert ts.title_form("Why Can't Anyone Live at Chernobyl, 40 Years Later?") == "question"
    assert ts.title_form("How is Money “Deleted”") == "question"
    assert ts.title_form("Is Solar Power About to Hit a Massive Brick Wall") == "question"
    assert ts.title_form("What if we created 23 Million Mini Ponds?") == "question"
    assert ts.title_form("The Demon Core Killed a Scientist. Why Did They Keep Testing It by Hand?") == "question"
    assert ts.title_form("The Demon Core Killed a Scientist. Why Did They Keep Testing It by Hand") == "question"
    # How/Why explanations: the outcome stated, the explanation promised.
    assert ts.title_form("Why Crumbl Cookies Can't Survive") == "how_why"
    assert ts.title_form("How Private Equity Turns Your Favorite Channels Into Slop") == "how_why"
    assert ts.title_form("$1 Billion To Forgotten: How Dollar Shave Club Lost Everything") == "how_why"
    assert ts.title_form("Australia's Dinosaur Trees are Thriving in Britain - here's why") == "how_why"
    assert ts.title_form("The Demon Core Killed a Scientist. Why They Kept Testing It by Hand") == "how_why"
    # Statements and labels, including embedded clauses that are not questions.
    assert ts.title_form("Florida Just Did the Impossible to Stop Pythons") == "statement"
    assert ts.title_form("What Archeologists Just Found Beneath Easter Island Will Leave You SHOCKED") == "statement"
    assert ts.title_form("The Biggest Mistake in the History of Hollywood") == "statement"
    assert ts.title_form("I Investigated the Swamp Nobody Can Drain") == "statement"


def test_title_patterns_from_the_pythons_field():
    assert set(ts.title_patterns("Florida Just Did the Impossible to Stop Pythons")) >= {"new_development", "conflict"}
    p = ts.title_patterns("Giant Pythons Have Overrun Florida. Here's Why.")
    assert {"how_why", "heres_why", "conflict", "superlative", "statement_then_why"} <= set(p) and "question" not in p
    p = ts.title_patterns("Why Florida Can't Stop 20ft Invasive Pythons")
    assert {"how_why", "conflict", "number"} <= set(p) and "question" not in p, "a How/Why headline is not a question"
    assert "question" in ts.title_patterns("Why Can't Florida Stop Its Pythons?")


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


def test_baseline_is_the_ten_uploads_before_and_outcomes_have_fixed_cuts():
    history = [{"video_id": f"h{i}", "views": v} for i, v in enumerate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 999])]
    assert ts.prior_baseline(history, 11) == 6.5, "median of h1..h10, not the latest uploads or the video itself"
    assert ts.prior_baseline(history, 3) is None, "fewer than five uploads before it"
    assert ts.recent_baseline(history, {"h11"}) == 6.5
    assert [ts.outcome(r) for r in (2.0, 1.99, 0.5, 0.493)] == ["high", "ordinary", "ordinary", "low"]


def test_favours_needs_two_forms_with_five_titles_and_a_clear_lead():
    def cell(n, hi):
        return {"n": n, "high_rate": hi / n if n else None}
    assert ts.favours({"question": cell(18, 1), "how_why": cell(18, 7), "statement": cell(35, 7)}) == "how_why"
    assert ts.favours({"question": cell(18, 4), "how_why": cell(18, 5), "statement": cell(35, 9)}) == "mixed"
    assert ts.favours({"question": cell(3, 0), "how_why": cell(4, 3), "statement": cell(35, 7)}) == "too_thin"


NOW = dt.datetime.now(dt.timezone.utc)


def _iso(days_ago: int) -> str:
    return (NOW - dt.timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _video(vid, title, channel, cid, views, days_ago, dur="PT12M"):
    return {"id": vid, "snippet": {"title": title, "channelTitle": channel, "channelId": cid,
                                   "publishedAt": _iso(days_ago), "liveBroadcastContent": "none",
                                   "thumbnails": {"high": {"url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"}}},
            "statistics": {"viewCount": str(views)}, "contentDetails": {"duration": dur}}


# The Explorer (c1): ten ordinary uploads, then ten whose titles and views make a known comparison set,
# then the python hit. Every comparison video's own preceding-ten median works out to 10,000.
C1_WINDOW = [("How Florida Lost Its Swamps", 30_000), ("Are Pythons Unstoppable?", 3_000),
             ("The Everglades Problem", 10_000), ("Why Nobody Can Stop the Snakes", 30_000),
             ("Can Robots Catch Pythons?", 3_000), ("Ancient Snakes of the South", 10_000),
             ("The Swamp Patrol", 10_000), ("Is Florida Sinking?", 10_000), ("Gator Country", 10_000),
             ("A Year in the Glades", 10_000)]
C1 = ([_video(f"o{i}", f"Old upload {i}", "The Explorer", "c1", 10_000, 600 - 7 * i) for i in range(10)]
      + [_video(f"w{i}", t, "The Explorer", "c1", v, 520 - 7 * i) for i, (t, v) in enumerate(C1_WINDOW)]
      + [_video("v1", "Florida Just Did the Impossible to Stop Pythons", "The Explorer", "c1", 2_564_307, 400)]
      + [_video("s1", "Python facts #shorts", "The Explorer", "c1", 500_000, 450, dur="PT40S")])
SEARCH = [C1[20],
          _video("v2", "Python hunters take on Florida's snake problem", "CBS Mornings", "c2", 1_904_670, 300),
          _video("v3", "Why Florida Can't Stop 20ft Pythons", "mintz", "c3", 60_000, 200),
          _video("v4", "Pythons in 60 seconds", "Shorty", "c4", 900_000, 100, dur="PT55S"),
          _video("v5", "Python Snake Sighting", "Tiny Channel", "c5", 4_000, 100)]


class FakeApi:
    def __init__(self):
        self.units = 0
        self.known = {v["id"]: v for v in C1 + SEARCH}
        self.playlists = {"Uc1": list(reversed(C1)), "Uc3": []}       # uploads playlists list newest first

    def __call__(self, path, **params):
        self.units += 100 if path == "search" else 1
        if path == "search":
            return {"items": [{"id": {"videoId": v["id"]}} for v in SEARCH]}
        if path == "videos":
            return {"items": [self.known[i] for i in params["id"].split(",") if i in self.known]}
        if path == "channels":
            subs = {"c1": 98_000, "c2": 3_320_000, "c3": 10_300, "c4": 5_000, "c5": 900}
            return {"items": [{"id": c, "statistics": {"subscriberCount": str(subs[c])},
                               "contentDetails": {"relatedPlaylists": {"uploads": f"U{c}"}}} for c in params["id"].split(",")]}
        if path == "playlistItems":
            items = self.playlists.get(params["playlistId"], [])
            start = int(params.get("pageToken") or 0)
            page = items[start:start + params.get("maxResults", 50)]
            out = {"items": [{"contentDetails": {"videoId": v["id"], "videoPublishedAt": v["snippet"]["publishedAt"]}}
                             for v in page]}
            if start + len(page) < len(items):
                out["nextPageToken"] = str(start + len(page))
            return out
        return {}


def test_run_scores_winners_then_and_builds_the_comparison_set():
    out = ts.run(FakeApi(), ["florida pythons"], ["python"], orders=("relevance",))
    titles = [w["title"] for w in out["winners"]]
    assert titles[0] == "Florida Just Did the Impossible to Stop Pythons"
    assert all("CBS" not in w["channel"] for w in out["winners"])
    assert any(m["channel"] == "CBS Mornings" for m in out["media_excluded"])
    assert "Pythons in 60 seconds" not in titles, "Shorts are not long-form"
    assert "Python Snake Sighting" not in titles, "the view floor still applies to finding winners"
    top = out["winners"][0]
    assert top["baseline_kind"] == "prior_ten" and top["baseline"] == 10_000.0, "the ten uploads before the hit"
    assert top["form"] == "statement" and top["thumbnail"].endswith("hqdefault.jpg")
    no_history = next(w for w in out["winners"] if w["channel"] == "mintz")
    assert no_history["baseline_kind"] is None and no_history["form"] == "how_why"

    comp = out["comparison"]
    assert len(comp) == 10 and {r["title"] for r in comp} == {t for t, _ in C1_WINDOW}
    assert "Python facts #shorts" not in {r["title"] for r in comp}, "Shorts stay out of the history"
    by_title = {r["title"]: r for r in comp}
    assert by_title["How Florida Lost Its Swamps"]["outcome"] == "high"
    assert by_title["Are Pythons Unstoppable?"]["outcome"] == "low"
    fo = out["form_outcomes"]
    assert fo["how_why"] == {"n": 2, "high": 2, "ordinary": 0, "low": 0, "high_rate": 1.0, "low_rate": 0.0, "thin": True}
    assert fo["question"]["n"] == 3 and fo["question"]["low"] == 2
    assert fo["statement"]["n"] == 5 and fo["statement"]["high"] == 0
    assert out["favours"] == "too_thin"
    assert out["within_channel"][0]["channel"] == "The Explorer"
    assert out["winner_forms"]["n"] == 1 and out["winner_forms"]["statement"] == 1
    assert out["coverage"] == {"channels": 2, "with_history": 1, "anchored": 1}

    md = ts.report(out, "burmese-pythons")
    for heading in ("Winning titles outside established media", "Title form vs. outcome", "Favours: too_thin",
                    "Within channel", "CBS Mornings"):
        assert heading in md


def test_history_pages_back_only_as_far_as_needed():
    api = FakeApi()
    api.playlists["Ubig"] = [_video(f"p{i}", f"Upload {i}", "Big", "cb", 1_000, i) for i in range(1, 181)]
    api.known.update({v["id"]: v for v in api.playlists["Ubig"]})
    calls = []

    def counting(path, **params):
        calls.append(path)
        return api(path, **params)

    history = ts.channel_history(counting, "Ubig", back_to=_iso(40), max_pages=4)
    assert calls.count("playlistItems") == 2, "page one holds only 10 uploads older than the hit; page two reaches 30"
    assert history[0]["published"] < history[-1]["published"], "oldest first"
