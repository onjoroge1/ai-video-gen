"""Peer scout (2026-10-18): every long-form upload in the window against the ten before it; short
histories unscored, never padded; young uploads out of the rates. No network: the API is faked.
"""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import peer_scout as ps  # noqa: E402

NOW = dt.datetime.now(dt.timezone.utc)


def _iso(days_ago: int) -> str:
    return (NOW - dt.timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _video(vid, title, cid, views, days_ago, seconds=600):
    return {"id": vid, "snippet": {"title": title, "channelTitle": f"Channel {cid}", "channelId": cid,
                                   "publishedAt": _iso(days_ago), "liveBroadcastContent": "none"},
            "statistics": {"viewCount": str(views)}, "contentDetails": {"duration": f"PT{seconds}S"}}


# Channel A: twelve uploads before the window at 1,000 views, then ten inside it whose every
# preceding-ten median is 1,000, then a young upload and a Short.
WINDOW = [("Why Florida Lost Its Swamps", 3_000, 300), ("Are Pythons Unstoppable?", 500, 300),
          ("The Everglades Problem", 1_000, 300), ("Snake Country", 1_000, 300),
          ("How One Bounty Changed Everything", 15_000, 300), ("Gator Patrol", 1_000, 1200),
          ("Is Florida Sinking?", 1_000, 1200), ("The Last Glade", 400, 1200), ("Swamp Notes", 1_000, 1200),
          ("A Year of Snakes", 1_000, 1200)]
A = ([_video(f"a_old{i}", f"Old {i}", "cA", 1_000, 1200 - 5 * i) for i in range(12)]
     + [_video(f"a{i}", t, "cA", v, 900 - 30 * i, s) for i, (t, v, s) in enumerate(WINDOW)]
     + [_video("a_young", "Brand new film", "cA", 1_000, 10), _video("a_short", "Clip #shorts", "cA", 90_000, 20, 40)])
# Channel B: five uploads, so nothing can be scored.
B = [_video(f"b{i}", f"New channel film {i}", "cB", 50_000, 300 - 20 * i) for i in range(5)]


class FakeApi:
    def __init__(self):
        self.units = 0
        self.known = {v["id"]: v for v in A + B}
        self.playlists = {"UcA": list(reversed(A)), "UcB": list(reversed(B))}

    def __call__(self, path, **params):
        self.units += 1
        if path == "channels":
            subs = {"cA": 35_600, "cB": 900}
            return {"items": [{"id": c, "statistics": {"subscriberCount": str(subs[c]), "videoCount": "30"},
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
        if path == "videos":
            return {"items": [self.known[i] for i in params["id"].split(",") if i in self.known]}
        return {}


def _window():
    return (NOW - dt.timedelta(days=1000)).strftime("%Y-%m-%d"), NOW.strftime("%Y-%m-%d")


def test_every_window_upload_is_scored_against_the_ten_before_it():
    start, end = _window()
    out = ps.run(FakeApi(), [{"channel_id": "cA", "name": "EyeTech-like"}, {"channel_id": "cB", "name": ""}], start, end)
    a, b = out["channels"]
    assert a["name"] == "EyeTech-like" and a["subs"] == 35_600 and a["window_covered"]
    assert a["scored"] == 10 and a["young"] == 1, "the 10-day-old upload is listed but kept out of the rates"
    assert (a["share_2x"], a["share_10x"], a["share_low"]) == (0.2, 0.1, 0.1)
    assert a["top_multiples"][0]["title"] == "How One Bounty Changed Everything" and a["top_multiples"][0]["multiple"] == 15.0
    assert all("shorts" not in r["title"].lower() for r in out["rows"]), "a Short is not a long-form upload"
    assert b["scored"] == 0 and b["unscored"] == 5 and b["name"] == "Channel cB"
    assert all("ten needed" in r["reason"] for r in out["unscored"] if r["channel_id"] == "cB")
    assert b["top_views"][0]["multiple"] is None, "a raw view leader without ten earlier uploads has no multiple"

    rt = out["runtime_outcomes"]
    assert (rt["under 8 min"]["n"], rt["under 8 min"]["high"]) == (5, 2)
    assert (rt["15-25 min"]["n"], rt["15-25 min"]["high"], rt["15-25 min"]["low"]) == (5, 0, 1)
    assert out["pooled"] == {"scored": 10, "high": 2, "low": 1}
    assert out["form_outcomes"]["question"]["n"] == 2 and out["favours"] == "too_thin"

    md = ps.report(out)
    for text in ("Peer scout", "EyeTech-like", "Runtime band vs. outcome", "no multiple", "Favours: too_thin"):
        assert text in md


def test_handoff_supplies_channels_and_window(tmp_path):
    path = tmp_path / "audit.json"
    path.write_text(json.dumps({"scout_handoff": {"B": {"window_start": "2023-10-18", "window_end": "2026-10-18",
                                                        "channels": [{"channel_id": "UC1", "name": "Micro"}]}}}))
    channels, start, end = ps.load_handoff(str(path))
    assert channels == [{"channel_id": "UC1", "name": "Micro"}] and (start, end) == ("2023-10-18", "2026-10-18")


def test_runtime_bands():
    assert [ps.band(s) for s in (299, 480, 899, 900, 1499, 1500)] == [
        "under 8 min", "8-15 min", "8-15 min", "15-25 min", "15-25 min", "25+ min"]
