"""Second-pass market check: short search phrase, title-keyword relevance, long-form only,
small-channel breakout ratio. Read-only YouTube Data API (about 102 quota units per topic)."""
import datetime as dt
import json
import os
import statistics
import sys
import urllib.parse
import urllib.request

from dotenv import load_dotenv

ROOT = os.path.expanduser("~/ai-video-gen-local")
load_dotenv(os.path.join(ROOT, ".env"))
KEY = os.environ["YOUTUBE_API_KEY"]
API = "https://www.googleapis.com/youtube/v3/"


def get(path, **params):
    params["key"] = KEY
    with urllib.request.urlopen(API + path + "?" + urllib.parse.urlencode(params), timeout=30) as r:
        return json.load(r)


def seconds(iso):
    import re
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    d, h, mi, s = (int(x or 0) for x in m.groups()) if m else (0, 0, 0, 0)
    return d * 86400 + h * 3600 + mi * 60 + s


def measure(topic):
    found = get("search", part="snippet", q=topic["q"], type="video", maxResults=25,
                relevanceLanguage="en")
    ids = [i["id"]["videoId"] for i in found.get("items", []) if i["id"].get("videoId")]
    vids = get("videos", part="statistics,snippet,contentDetails", id=",".join(ids)).get("items", [])
    chans = {c["id"]: int(c["statistics"].get("subscriberCount") or 0) for c in get(
        "channels", part="statistics", id=",".join({v["snippet"]["channelId"] for v in vids})).get("items", [])}
    now = dt.datetime.now(dt.timezone.utc)
    rows = []
    for v in vids:
        title = v["snippet"]["title"].lower()
        if seconds(v["contentDetails"].get("duration")) <= 90:
            continue
        if not any(all(w in title for w in alt.split("+")) for alt in topic["must"]):
            continue
        views = int(v["statistics"].get("viewCount") or 0)
        days = max(1, (now - dt.datetime.fromisoformat(v["snippet"]["publishedAt"].replace("Z", "+00:00"))).days)
        subs = chans.get(v["snippet"]["channelId"], 0)
        rows.append({"title": v["snippet"]["title"], "views": views, "days": days, "vpd": views / days,
                     "subs": subs, "channel": v["snippet"]["channelTitle"]})
    if not rows:
        return {"n": 0}
    recent = [r for r in rows if r["days"] <= 1095]
    small = [r for r in rows if r["subs"] and r["subs"] < 200_000]
    return {
        "n": len(rows),
        "median_views": statistics.median(r["views"] for r in rows),
        "top_views": max(r["views"] for r in rows),
        "n_100k": sum(r["views"] >= 100_000 for r in rows),
        "recent_median_vpd": statistics.median(r["vpd"] for r in recent) if recent else 0,
        "n_recent": len(recent),
        # A channel under 200k subscribers getting views well above its subscriber count means
        # the topic travels on browse/suggested, not on an existing audience.
        "small_breakouts": sum(r["views"] >= 3 * r["subs"] and r["views"] >= 50_000 for r in small),
        "top": sorted(rows, key=lambda r: -r["views"])[:3],
    }


if __name__ == "__main__":
    topics = json.load(open(sys.argv[1]))
    out = []
    for t in topics:
        try:
            m = measure(t)
        except Exception as exc:  # noqa: BLE001
            m = {"error": str(exc)[:200]}
        out.append({**t, "m": m})
        print(f"{t['slug']:<22} n={m.get('n')} med={m.get('median_views', 0):>10,.0f} "
              f"top={m.get('top_views', 0):>11,} 100k+={m.get('n_100k')} "
              f"vpd={m.get('recent_median_vpd', 0):>7,.0f} small_breakouts={m.get('small_breakouts')}",
              flush=True)
    json.dump(out, open(sys.argv[2], "w"), indent=1)
