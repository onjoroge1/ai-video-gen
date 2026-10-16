"""Outlier scout: start from demand, not from a topic.

Searches YouTube for recent long-form videos in our lanes and keeps the ones that beat their OWN
channel's baseline. A 2.1M-view film on a 6.5K-subscriber channel (Blue Trees' carp, measured
2026-10-15) is the topic and the angle doing the work, not the audience. Those outliers are the
evidence a question will be watched. Our film then answers it in our own way: our research, our
witness opening, our present-consequence angle. Never a copy of their script or sequence.

    python3 scripts/outlier_scout.py topics/scout_seeds.json topics/scout_<date>.json
            [--months 24] [--min-views 200000] [--min-ratio 5] [--max-channels 200] [--comments 20]

Scores per video:
  ratio_baseline  views / the channel's median views over its recent long-form uploads (the outlier
                  itself excluded). The primary signal.
  ratio_subs      views / subscribers (floor 1,000). The fallback when no baseline is available.
  vpd             views per day since publishing: what is rising now.

Read-only YouTube Data API, about 100 units per seed search plus ~2 per channel baseline and 1 per
comment fetch. With 24 seeds and 200 channels that is roughly 3,000 units of the 10,000 daily quota.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://www.googleapis.com/youtube/v3/"
COST = {"search": 100}          # every other list call used here costs 1 unit
LONG_FORM_SEC = 180
SUBS_FLOOR = 1_000
QUESTION = re.compile(r"\?|^(why|how|what|who|when|where|is|are|did|does|do|can|could|would)\b", re.I)


class Api:
    """Thin YouTube Data API client that counts the quota it spends."""

    def __init__(self, key: str):
        self.key, self.units = key, 0

    def __call__(self, path: str, **params):
        params["key"] = self.key
        self.units += COST.get(path, 1)
        url = API + path + "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r)


def seconds(iso: str) -> int:
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    d, h, mi, s = (int(x or 0) for x in m.groups()) if m else (0, 0, 0, 0)
    return d * 86400 + h * 3600 + mi * 60 + s


def _batches(items, n=50):
    items = list(items)
    for i in range(0, len(items), n):
        yield items[i:i + n]


def search_seed(get, q: str, published_after: str, per_query: int = 50,
                order: str = "relevance") -> list[str]:
    """Relevance, not view count: sorting by views pulled in big off-topic hits ("still burning
    today" returned a reggae tribute, 2026-10-16). The ratio does the ranking afterwards."""
    found = get("search", part="id", q=q, type="video", order=order, maxResults=per_query,
                publishedAfter=published_after, relevanceLanguage="en")
    return [i["id"]["videoId"] for i in found.get("items", []) if i.get("id", {}).get("videoId")]


def fetch_videos(get, ids) -> dict:
    out = {}
    for batch in _batches(dict.fromkeys(ids)):
        for v in get("videos", part="snippet,statistics,contentDetails", id=",".join(batch)).get("items", []):
            out[v["id"]] = v
    return out


def fetch_channels(get, channel_ids) -> dict:
    out = {}
    for batch in _batches(dict.fromkeys(channel_ids)):
        for c in get("channels", part="statistics,contentDetails", id=",".join(batch)).get("items", []):
            stats = c.get("statistics", {})
            out[c["id"]] = {
                "subs": int(stats.get("subscriberCount") or 0),
                "hidden_subs": bool(stats.get("hiddenSubscriberCount")),
                "videos": int(stats.get("videoCount") or 0),
                "uploads": c.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads", ""),
            }
    return out


def channel_baseline(get, uploads: str, exclude: set, n: int = 30) -> float | None:
    """Median views of the channel's recent long-form uploads, excluding the outliers themselves.
    None when fewer than five long-form uploads are available to judge against."""
    if not uploads:
        return None
    items = get("playlistItems", part="contentDetails", playlistId=uploads, maxResults=min(50, n + 10))
    ids = [i["contentDetails"]["videoId"] for i in items.get("items", [])
           if i.get("contentDetails", {}).get("videoId") not in exclude]
    if not ids:
        return None
    vids = get("videos", part="statistics,contentDetails", id=",".join(ids[:50])).get("items", [])
    views = [int(v["statistics"].get("viewCount") or 0) for v in vids
             if seconds(v.get("contentDetails", {}).get("duration")) >= LONG_FORM_SEC][:n]
    return float(statistics.median(views)) if len(views) >= 5 else None


def score(video: dict, channel: dict | None, baseline: float | None, now: dt.datetime) -> dict:
    sn, st = video["snippet"], video.get("statistics", {})
    views = int(st.get("viewCount") or 0)
    published = dt.datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00"))
    days = max(1, (now - published).days)
    subs = (channel or {}).get("subs") or 0
    return {
        "video_id": video["id"], "url": f"https://youtu.be/{video['id']}", "title": sn.get("title", ""),
        "channel": sn.get("channelTitle", ""), "channel_id": sn.get("channelId", ""),
        "published": sn["publishedAt"][:10], "days": days,
        "duration_sec": seconds(video.get("contentDetails", {}).get("duration")),
        "views": views, "vpd": round(views / days, 1), "subs": subs,
        "baseline": baseline, "ratio_baseline": round(views / max(baseline, SUBS_FLOOR), 1) if baseline else None,
        "ratio_subs": round(views / max(subs, SUBS_FLOOR), 1),
        "comments": int(st.get("commentCount") or 0),
    }


def title_matches(title: str, must: list[str] | None) -> bool:
    """A seed's "must" alternatives, as in topic_market: any alternative, words joined by "+"
    must all appear in the title. No "must" list means no title filter."""
    if not must:
        return True
    t = title.lower()
    return any(all(w.strip().lower() in t for w in alt.split("+")) for alt in must)


def is_outlier(row: dict, min_views: int, min_ratio: float) -> bool:
    if row["views"] < min_views or row["duration_sec"] < LONG_FORM_SEC:
        return False
    ratio = row["ratio_baseline"] if row["ratio_baseline"] is not None else row["ratio_subs"]
    return ratio >= min_ratio


def question_comments(get, video_id: str, n: int = 20) -> list[str]:
    """Viewer questions among the top comments: what the video left unanswered."""
    try:
        res = get("commentThreads", part="snippet", videoId=video_id, order="relevance",
                  maxResults=n, textFormat="plainText")
    except urllib.error.HTTPError:          # comments disabled
        return []
    out = []
    for item in res.get("items", []):
        text = item["snippet"]["topLevelComment"]["snippet"].get("textDisplay", "").strip()
        if text and QUESTION.search(text) and len(text) <= 400:
            out.append(text)
    return out[:8]


def run(get, seeds: list[dict], months: int = 24, min_views: int = 200_000, min_ratio: float = 5.0,
        max_channels: int = 200, comments: int = 20, per_query: int = 50, now: dt.datetime | None = None,
        log=print) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    after = (now - dt.timedelta(days=int(months * 30.44))).strftime("%Y-%m-%dT%H:%M:%SZ")
    found_by: dict[str, list[dict]] = {}
    seed_stats = []
    for seed in seeds:
        try:
            ids = search_seed(get, seed["q"], after, per_query, seed.get("order", "relevance"))
        except urllib.error.HTTPError as exc:
            log(f"search failed for {seed['q']!r}: HTTP {exc.code}")
            seed_stats.append({**seed, "found": 0, "error": f"HTTP {exc.code}"})
            if exc.code == 403:             # quota exhausted: stop searching, score what we have
                break
            continue
        for vid in ids:
            found_by.setdefault(vid, []).append(seed)
        seed_stats.append({**seed, "found": len(ids)})
    videos = fetch_videos(get, found_by)
    # Off-topic hits out before any baseline is bought: keep a video if ANY seed that found it
    # accepts its title.
    for vid in list(found_by):
        title = (videos.get(vid) or {}).get("snippet", {}).get("title", "")
        keep = [s for s in found_by[vid] if title_matches(title, s.get("must"))]
        if keep:
            found_by[vid] = keep
        else:
            found_by.pop(vid); videos.pop(vid, None)
    channels = fetch_channels(get, {v["snippet"]["channelId"] for v in videos.values()})
    rows = {vid: score(v, channels.get(v["snippet"]["channelId"]), None, now) for vid, v in videos.items()}
    # Baselines cost ~2 units a channel: only for long-form candidates above the view floor whose
    # subscriber ratio is at least within reach of the bar, biggest first, up to max_channels.
    candidates = sorted((r for r in rows.values() if r["views"] >= min_views
                         and r["duration_sec"] >= LONG_FORM_SEC
                         and (r["ratio_subs"] >= min_ratio / 2 or not r["subs"])),
                        key=lambda r: -r["views"])
    by_channel: dict[str, list[str]] = {}
    for r in candidates:
        by_channel.setdefault(r["channel_id"], []).append(r["video_id"])
    baselines = {}
    for cid in list(by_channel)[:max_channels]:
        try:
            baselines[cid] = channel_baseline(get, channels.get(cid, {}).get("uploads", ""),
                                              exclude=set(by_channel[cid]))
        except urllib.error.HTTPError as exc:
            log(f"baseline failed for channel {cid}: HTTP {exc.code}")
            if exc.code == 403:
                break
    for r in rows.values():
        if r["channel_id"] in baselines:
            b = baselines[r["channel_id"]]
            r["baseline"] = b
            r["ratio_baseline"] = round(r["views"] / max(b, SUBS_FLOOR), 1) if b else None
    outliers = [dict(r, seeds=[s["q"] for s in found_by[r["video_id"]]],
                     groups=sorted({s.get("group", "") for s in found_by[r["video_id"]]}))
                for r in rows.values() if is_outlier(r, min_views, min_ratio)]
    outliers.sort(key=lambda r: (-(r["ratio_baseline"] or r["ratio_subs"]), -r["vpd"]))
    for r in outliers[:comments]:
        r["viewer_questions"] = question_comments(get, r["video_id"])
    for s in seed_stats:
        s["outliers"] = sum(s["q"] in r["seeds"] for r in outliers)
    return {"generated": now.strftime("%Y-%m-%d"),
            "params": {"months": months, "min_views": min_views, "min_ratio": min_ratio,
                       "max_channels": max_channels, "per_query": per_query},
            "quota_used": getattr(get, "units", None), "seeds": seed_stats,
            "candidates_scored": len(rows), "outliers": outliers,
            # Shorts are scored apart (subscriber ratio only, no baseline bought): evidence for the
            # companion-Short strategy, never mixed into the long-form ranking.
            "shorts_outliers": sorted(
                (dict(r, seeds=[s["q"] for s in found_by[r["video_id"]]]) for r in rows.values()
                 if r["duration_sec"] < LONG_FORM_SEC and r["views"] >= min_views
                 and r["ratio_subs"] >= min_ratio),
                key=lambda r: -r["ratio_subs"])[:25],
            # The biggest on-topic videos whether or not they cleared the bar: shows what the seeds
            # actually reach, and where demand sits on big channels.
            "top_candidates": [{k: r[k] for k in ("title", "channel", "url", "views", "subs", "baseline",
                                                  "ratio_baseline", "ratio_subs", "vpd", "duration_sec")}
                               for r in sorted(rows.values(), key=lambda r: -r["views"])[:15]]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("seeds")
    ap.add_argument("out")
    ap.add_argument("--months", type=int, default=24)
    ap.add_argument("--min-views", type=int, default=200_000)
    ap.add_argument("--min-ratio", type=float, default=5.0)
    ap.add_argument("--max-channels", type=int, default=200)
    ap.add_argument("--comments", type=int, default=20)
    args = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.expanduser("~/ai-video-gen-local"), ".env"))
    load_dotenv(os.path.join(ROOT, ".env"))
    get = Api(os.environ["YOUTUBE_API_KEY"])
    result = run(get, json.load(open(args.seeds)), args.months, args.min_views, args.min_ratio,
                 args.max_channels, args.comments)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=1, ensure_ascii=False)
    print(f"quota used ~{result['quota_used']} units; {result['candidates_scored']} videos scored; "
          f"{len(result['outliers'])} outliers")
    for r in result["outliers"][:40]:
        ratio = r["ratio_baseline"] if r["ratio_baseline"] is not None else f"{r['ratio_subs']}s"
        print(f"{str(ratio):>7}x {r['views']:>11,} {r['vpd']:>9,.0f}/d  {r['channel'][:22]:<22} {r['title'][:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
