"""Read-only channel report: every upload with its public stats and owner analytics.

Pulls, for the channel the OAuth token is bound to (YOUTUBE_CHANNEL_ID):
  * the upload list with duration, publish date, title (Data API)
  * per-video analytics for the lifetime window: views, watch time, average view duration and
    percentage, likes, comments, shares, subscribers gained (Analytics API)
  * traffic sources and the retention curve for every video (Analytics API)
  * channel-level day series for the last 90 days

Writes jobs/yt/<channel_id>/report.json and prints a table. Nothing is written to YouTube.

    python3 scripts/youtube_channel_report.py [--channel UC...] [--days 365]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _creds():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    from google.oauth2.credentials import Credentials
    missing = [k for k in ("YOUTUBE_OAUTH_CLIENT_ID", "YOUTUBE_OAUTH_CLIENT_SECRET",
                           "YOUTUBE_OAUTH_REFRESH_TOKEN") if not os.environ.get(k)]
    if missing:
        sys.exit(f"missing in .env: {', '.join(missing)} (run scripts/youtube_oauth_setup.py --write)")
    return Credentials(
        None, refresh_token=os.environ["YOUTUBE_OAUTH_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YOUTUBE_OAUTH_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_OAUTH_CLIENT_SECRET"])


def _iso_seconds(value: str) -> int:
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def _query(ya, **kw):
    rows = ya.reports().query(**kw).execute()
    cols = [c["name"] for c in rows.get("columnHeaders", [])]
    return [dict(zip(cols, r)) for r in rows.get("rows", [])]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default=os.environ.get("YOUTUBE_CHANNEL_ID", ""))
    ap.add_argument("--days", type=int, default=730)
    args = ap.parse_args()
    from googleapiclient.discovery import build
    creds = _creds()
    channel_id = args.channel or os.environ.get("YOUTUBE_CHANNEL_ID", "")
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    ya = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)

    ch = yt.channels().list(part="id,snippet,statistics,contentDetails",
                            **({"id": channel_id} if channel_id else {"mine": True})).execute()
    if not ch.get("items"):
        sys.exit(f"channel {channel_id!r} not found")
    ch = ch["items"][0]
    channel_id = ch["id"]
    uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]

    videos: list[dict] = []
    page = None
    while True:
        pl = yt.playlistItems().list(part="contentDetails", playlistId=uploads, maxResults=50,
                                     pageToken=page).execute()
        ids = [it["contentDetails"]["videoId"] for it in pl.get("items", [])]
        if ids:
            vs = yt.videos().list(part="snippet,contentDetails,statistics", id=",".join(ids)).execute()
            for v in vs.get("items", []):
                st = v.get("statistics", {})
                videos.append({
                    "id": v["id"], "title": v["snippet"]["title"],
                    "published": v["snippet"]["publishedAt"][:10],
                    "seconds": _iso_seconds(v["contentDetails"].get("duration", "")),
                    "views": int(st.get("viewCount", 0)), "likes": int(st.get("likeCount", 0)),
                    "comments": int(st.get("commentCount", 0)),
                    "tags": v["snippet"].get("tags", []),
                    "description_head": (v["snippet"].get("description") or "")[:160],
                })
        page = pl.get("nextPageToken")
        if not page:
            break
    for v in videos:
        v["format"] = "short" if v["seconds"] <= 180 else "long"

    end = dt.date.today()
    start = end - dt.timedelta(days=args.days)
    base = dict(ids=f"channel=={channel_id}", startDate=start.isoformat(), endDate=end.isoformat())

    per_video = {r["video"]: r for r in _query(
        ya, **base, dimensions="video", sort="-views", maxResults=200,
        metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,"
                "likes,comments,shares,subscribersGained,subscribersLost")}
    for v in videos:
        v["analytics"] = per_video.get(v["id"], {})

    traffic = {}
    retention = {}
    for v in videos:
        vid = v["id"]
        try:
            traffic[vid] = _query(ya, **base, dimensions="insightTrafficSourceType",
                                  filters=f"video=={vid}", metrics="views,estimatedMinutesWatched",
                                  sort="-views")
        except Exception as exc:  # a brand-new video can have no rows yet
            traffic[vid] = [{"error": str(exc)[:120]}]
        try:
            retention[vid] = _query(ya, ids=f"channel=={channel_id}",
                                    startDate=start.isoformat(), endDate=end.isoformat(),
                                    dimensions="elapsedVideoTimeRatio",
                                    filters=f"video=={vid}", metrics="audienceWatchRatio")
        except Exception as exc:
            retention[vid] = [{"error": str(exc)[:120]}]

    day_start = end - dt.timedelta(days=90)
    days = _query(ya, ids=f"channel=={channel_id}", startDate=day_start.isoformat(),
                  endDate=end.isoformat(), dimensions="day", sort="day",
                  metrics="views,estimatedMinutesWatched,subscribersGained,subscribersLost")
    try:
        by_type = _query(ya, **base, dimensions="creatorContentType",
                         metrics="views,estimatedMinutesWatched,averageViewDuration,likes,subscribersGained")
    except Exception as exc:
        by_type = [{"error": str(exc)[:160]}]
    try:
        sources_all = _query(ya, **base, dimensions="insightTrafficSourceType", sort="-views",
                             metrics="views,estimatedMinutesWatched")
    except Exception as exc:
        sources_all = [{"error": str(exc)[:160]}]

    out_dir = os.path.join(ROOT, "jobs", "yt", channel_id)
    os.makedirs(out_dir, exist_ok=True)
    report = {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "channel": {"id": channel_id, "title": ch["snippet"]["title"],
                    "statistics": ch["statistics"], "created": ch["snippet"]["publishedAt"][:10]},
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "videos": videos, "traffic": traffic, "retention": retention,
        "days_90": days, "by_content_type": by_type, "sources_all": sources_all,
    }
    path = os.path.join(out_dir, "report.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=1, ensure_ascii=False)

    stats = ch["statistics"]
    print(f"{ch['snippet']['title']} ({channel_id}) subs={stats.get('subscriberCount')} "
          f"videos={stats.get('videoCount')} views={stats.get('viewCount')} created={ch['snippet']['publishedAt'][:10]}")
    print(f"{'published':10} {'fmt':5} {'len':>5} {'views':>7} {'avg%':>5} {'avgSec':>6} {'likes':>5} {'subs+':>5}  title")
    for v in sorted(videos, key=lambda x: x["published"], reverse=True):
        a = v["analytics"]
        print(f"{v['published']:10} {v['format']:5} {v['seconds']:5d} {v['views']:7d} "
              f"{float(a.get('averageViewPercentage', 0)):5.1f} {float(a.get('averageViewDuration', 0)):6.0f} "
              f"{v['likes']:5d} {int(a.get('subscribersGained', 0)):5d}  {v['title'][:60]}")
    print(f"\nreport: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
