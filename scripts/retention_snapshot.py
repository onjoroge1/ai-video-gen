"""Read-only retention snapshot for the films in a retention experiment.

For each video: public views (live), and from the Analytics API (2-3 days behind) views by
traffic source, subscribed vs not, daily views, and the audience-retention curve, reduced to the
numbers the experiments are judged on: share still watching at 10/15/20/30/45/60 seconds and at
25/50/75/100% of the film. Nothing is written to YouTube.

    python3 scripts/retention_snapshot.py [VIDEO_ID ...] [--save] [--env ~/ai-video-gen-local/.env]

With no IDs it reads the baseline set below. --save writes
~/ai-video-gen-local/jobs/yt/experiments/snapshots/<date>.json (git-ignored: the repo is public).

API notes learned 2026-10-15:
  * insightTrafficSourceType "SUBSCRIBER" is BROWSE FEATURES (home page, subscription feed,
    Watch later), not "subscribers": the cane toad film's 2,162 "SUBSCRIBER" views came from
    2,185 UNSUBSCRIBED viewers. Read it as the home-feed test.
  * The google client has no socket timeout by default; one dead connection hung
    youtube_channel_report.py for 15 minutes. Every call here has a 40 s timeout and retries.
  * The retention report is empty below a few dozen views.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time

BASELINE = {
    # video id: (channel key, label)
    "NIGiEV6xGSg": ("world", "cane toad V1"),
    "AQtWf-bNLTs": ("world", "elk V1"),
    "gCJh5oM8kwg": ("world", "bees V1"),
    "5L4SnRyJAII": ("world", "sparrows V1 (search-led)"),
    "eWJr_iwUNx4": ("world", "carp V1 (private 10-15)"),
    "hFk6YVSa0xk": ("world", "hippo V1 (private 10-15)"),
    "W_34aCW7iJM": ("world", "carp V2 witness remake"),
    "DxkTFbQbCWg": ("world", "hippo V2 witness remake"),
    "IN1DERNZ2zA": ("history", "Aral V1"),
}
CHANNELS = {"world": ("YOUTUBE_OAUTH_REFRESH_TOKEN", "UCnDdL_at-7BV9kBQnJ3GMtA"),
            "history": ("YOUTUBE_OAUTH_REFRESH_TOKEN_HISTORY", "UCUXQrPJppPI97unCQsr9wRA")}
SECONDS = (10, 15, 20, 30, 45, 60)
RATIOS = (0.25, 0.5, 0.75, 1.0)
OUT_DIR = os.path.expanduser("~/ai-video-gen-local/jobs/yt/experiments/snapshots")


def _clients(env: dict, channel: str):
    import google_auth_httplib2
    import httplib2
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    token_key, _ = CHANNELS[channel]
    creds = Credentials(None, refresh_token=env[token_key], token_uri="https://oauth2.googleapis.com/token",
                        client_id=env["YOUTUBE_OAUTH_CLIENT_ID"],
                        client_secret=env["YOUTUBE_OAUTH_CLIENT_SECRET"])

    def http():
        return google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=40))
    return (build("youtubeAnalytics", "v2", http=http(), cache_discovery=False),
            build("youtube", "v3", http=http(), cache_discovery=False))


def _query(ya, **kw) -> list[dict]:
    last = ""
    for attempt in range(3):
        try:
            r = ya.reports().query(**kw).execute()
            cols = [c["name"] for c in r.get("columnHeaders", [])]
            return [dict(zip(cols, row)) for row in r.get("rows", [])]
        except Exception as exc:  # timeouts and 5xx retry; anything else is reported
            last = str(exc)[:200]
            if "timed out" in last.lower() or " 50" in last:
                time.sleep(2 * (attempt + 1))
                continue
            break
    return [{"error": last}]


def _seconds(iso: str) -> int:
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    h, mi, s = (int(x) if x else 0 for x in m.groups()) if m else (0, 0, 0)
    return h * 3600 + mi * 60 + s


def _at(curve: list[dict], length: int) -> dict:
    pts = [(p["elapsedVideoTimeRatio"], p["audienceWatchRatio"]) for p in curve
           if "elapsedVideoTimeRatio" in p]
    if not pts or not length:
        return {}

    def ratio_at(r: float) -> float:
        best = min(pts, key=lambda p: abs(p[0] - r))
        return round(best[1], 3)
    out = {f"{s}s": ratio_at(s / length) for s in SECONDS if s < length}
    out.update({f"{int(r * 100)}%": ratio_at(r) for r in RATIOS})
    return out


def snapshot(video_id: str, channel: str, env: dict) -> dict:
    ya, yt = _clients(env, channel)
    _, channel_id = CHANNELS[channel]
    items = yt.videos().list(part="snippet,statistics,contentDetails,status", id=video_id).execute().get("items")
    if not items:
        return {"id": video_id, "error": "not found"}
    v = items[0]
    length = _seconds(v["contentDetails"]["duration"])
    base = dict(ids=f"channel=={channel_id}", startDate="2026-06-01",
                endDate=dt.date.today().isoformat(), filters=f"video=={video_id}")
    rec = {
        "id": video_id, "title": v["snippet"]["title"], "published": v["snippet"]["publishedAt"][:10],
        "privacy": v["status"]["privacyStatus"], "seconds": length,
        "public_views": int(v["statistics"].get("viewCount", 0)),
        "totals": _query(ya, **base, metrics="views,averageViewDuration,averageViewPercentage,"
                                               "likes,shares,subscribersGained"),
        "by_subscribed": _query(ya, **base, dimensions="subscribedStatus",
                                metrics="views,averageViewPercentage"),
        "traffic": _query(ya, **base, dimensions="insightTrafficSourceType",
                          metrics="views,averageViewDuration", sort="-views"),
        "days": _query(ya, **base, dimensions="day", metrics="views", sort="day"),
        "curve": _query(ya, **base, dimensions="elapsedVideoTimeRatio",
                        metrics="audienceWatchRatio,relativeRetentionPerformance"),
    }
    rec["retention"] = _at(rec["curve"], length)
    traffic = {t.get("insightTrafficSourceType"): t.get("views", 0) for t in rec["traffic"]
               if "error" not in t}
    rec["browse_views"] = traffic.get("SUBSCRIBER", 0)
    rec["search_views"] = traffic.get("YT_SEARCH", 0)
    rec["suggested_views"] = traffic.get("RELATED_VIDEO", 0)
    rec["ad_views"] = traffic.get("ADVERTISING", 0)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*", help="video IDs; ID@history for the History channel")
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--env", default=os.path.expanduser("~/ai-video-gen-local/.env"))
    args = ap.parse_args()
    from dotenv import dotenv_values
    env = dotenv_values(args.env)
    targets = {}
    for raw in args.ids:
        vid, _, ch = raw.partition("@")
        targets[vid] = (ch or "world", BASELINE.get(vid, ("", vid))[1])
    targets = targets or BASELINE
    rows = []
    for vid, (channel, label) in targets.items():
        rec = snapshot(vid, channel, env)
        rec["label"] = label
        rows.append(rec)
    cols = ["10s", "15s", "20s", "30s", "45s", "60s", "50%", "100%"]
    print(f"{'film':26s} {'pub':>5s} {'views':>5s} {'brows':>5s} {'srch':>4s} {'ads':>4s}  "
          + " ".join(f"{c:>5s}" for c in cols))
    for r in rows:
        t = r.get("totals") or [{}]
        views = t[0].get("views", 0) if "error" not in t[0] else "err"
        ret = r.get("retention") or {}
        print(f"{r['label'][:26]:26s} {r.get('public_views', 0):5d} {views!s:>5s} "
              f"{r.get('browse_views', 0):5d} {r.get('search_views', 0):4d} {r.get('ad_views', 0):4d}  "
              + " ".join(f"{ret[c]:5.2f}" if c in ret else "    -" for c in cols))
    if args.save:
        os.makedirs(OUT_DIR, exist_ok=True)
        path = os.path.join(OUT_DIR, f"{dt.date.today().isoformat()}.json")
        with open(path, "w") as handle:
            json.dump({"generated": dt.datetime.now().isoformat(timespec="seconds"), "films": rows},
                      handle, indent=1)
        print(f"saved {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
