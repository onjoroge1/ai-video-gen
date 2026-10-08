#!/usr/bin/env python3
"""Rank candidate World-channel topics by YouTube demand, competition and our own channel's record.

    python3 scripts/research_topics.py [--candidates topics/candidates.json] [--out topics/research.json]

For each candidate it runs one YouTube Data API search (100 quota units) and one videos.list
(1 unit), measures the market the way topic_roi.opportunity_score expects it (median views and
views per day of relevant results, the top result's outlier ratio, recency of the newest strong
video, how many 100k+ competitors exist), takes our own fit from the channel report
(jobs/yt/<channel>/report.json, scripts/youtube_channel_report.py), and scores it with
topic_roi.opportunity_score. Read-only: nothing is posted, nothing is generated.

The editorial fields (curiosity_gap, visual_promise, production_fit, fact_confidence, novelty,
0-10) are the editor's judgment and live in the candidates file so they can be argued with.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import statistics
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import topic_roi  # noqa: E402

WORLD = "UCnDdL_at-7BV9kBQnJ3GMtA"


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def market_for(query: str, key: str, topic_words: str) -> dict:
    params = {"part": "snippet", "q": query, "type": "video", "maxResults": 25,
              "relevanceLanguage": "en", "videoDuration": "medium", "key": key}
    found = _get("https://www.googleapis.com/youtube/v3/search?" + urllib.parse.urlencode(params))
    ids = [item["id"]["videoId"] for item in found.get("items") or [] if item.get("id", {}).get("videoId")]
    stats = {}
    if ids:
        listed = _get("https://www.googleapis.com/youtube/v3/videos?" + urllib.parse.urlencode(
            {"part": "statistics,snippet", "id": ",".join(ids), "key": key}))
        stats = {item["id"]: item for item in listed.get("items") or []}
    now = dt.datetime.now(dt.timezone.utc)
    rows = []
    for vid in ids:
        item = stats.get(vid) or {}
        snippet = item.get("snippet") or {}
        views = int((item.get("statistics") or {}).get("viewCount") or 0)
        published = snippet.get("publishedAt")
        days = max(1.0, (now - dt.datetime.fromisoformat(published.replace("Z", "+00:00"))).days) if published else 3650.0
        relevant = topic_roi.topic_similarity(topic_words, snippet.get("title") or "") >= 0.12
        rows.append({"id": vid, "title": snippet.get("title"), "channel": snippet.get("channelTitle"),
                     "views": views, "days": days, "views_per_day": views / days, "relevant": relevant})
    relevant_rows = [r for r in rows if r["relevant"]] or rows[:5]
    views = [r["views"] for r in relevant_rows] or [0]
    per_day = [r["views_per_day"] for r in relevant_rows] or [0]
    strong_recent = [r["days"] for r in relevant_rows if r["views"] >= 10_000]
    median_views = statistics.median(views)
    return {
        "relevant_count": sum(1 for r in rows if r["relevant"]),
        "median_views": median_views,
        "median_views_per_day": statistics.median(per_day),
        "outlier": (max(views) / median_views) if median_views else 0.0,
        "recency_days": min(strong_recent) if strong_recent else None,
        "competition": sum(1 for r in relevant_rows if r["views"] >= 100_000 and r["days"] <= 730),
        "top": sorted(relevant_rows, key=lambda r: -r["views"])[:3],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--candidates", default=os.path.join(ROOT, "topics", "candidates.json"))
    parser.add_argument("--out", default=os.path.join(ROOT, "topics", "research.json"))
    args = parser.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    key = os.environ["YOUTUBE_API_KEY"]
    with open(args.candidates, encoding="utf-8") as handle:
        candidates = json.load(handle)
    report_path = os.path.join(ROOT, "jobs", "yt", WORLD, "report.json")
    metrics = []
    if os.path.exists(report_path):
        with open(report_path, encoding="utf-8") as handle:
            report = json.load(handle)
        for v in report.get("videos") or report.get("uploads") or []:
            metrics.append({"title": v.get("title"), "views": v.get("views"),
                            "video_len_sec": v.get("duration_sec") or v.get("len"),
                            "avg_view_dur_sec": v.get("avg_view_duration_sec") or v.get("avgSec"),
                            "pct_viewed": v.get("avg_view_pct") or v.get("avg_pct"),
                            "subs_gained": v.get("subscribers_gained") or v.get("subs"),
                            "format": "short" if (v.get("duration_sec") or v.get("len") or 0) <= 60 else "long"})
    ranked = []
    for topic in candidates:
        market = market_for(topic["search"], key, topic["question"])
        fit, evidence = topic_roi.own_channel_fit(topic["question"], "long", metrics)
        score, breakdown = topic_roi.opportunity_score(topic, market, fit)
        ranked.append({**topic, "score": score, "breakdown": breakdown, "own_fit_evidence": evidence,
                       "market": {k: v for k, v in market.items() if k != "top"},
                       "top_competitors": market["top"]})
        print(f"{score:>3}  {topic['slug']:<28} median {market['median_views']:>9,.0f} views, "
              f"{market['median_views_per_day']:>7,.0f}/day, 100k+ rivals {market['competition']}")
    ranked.sort(key=lambda t: -t["score"])
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump({"generated": dt.date.today().isoformat(), "ranked": ranked}, handle, indent=1)
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
