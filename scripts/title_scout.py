#!/usr/bin/env python3
"""Title scout: which TITLES already win on a topic, outside established media.

    python3 scripts/title_scout.py burmese-pythons \
        --phrase "florida pythons" --phrase "python hunters everglades" --phrase "why can't florida stop pythons" \
        --must python --out topics/titles/burmese-pythons_2026-10-19.json --thumbs

The outlier scout finds topics. This finds the title shapes that do the work for one topic:
- search the phrasings a viewer would type, by relevance and by view count;
- drop established media (a subscriber cap and a list of media brands);
- rank the rest by how far each video beat its own channel's typical upload;
- tag every title with its pattern (question, "here's why", new development, conflict, superlative,
  number, caps) and measure each pattern's lift.

The report shows the patterns that over-perform, with the winners' thumbnails beside their titles.
Winners are evidence of what a viewer clicks. Our title uses a proven pattern with our own facts and
angle, never a copied title (the rule for scripts holds here too).

Quota: 100 units per search (phrases x orders), about 2 per channel baseline, 1 per 50 videos.
Three phrases by two orders with 60 channels is about 750 units.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import statistics
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import outlier_scout as osc  # noqa: E402

MAX_SUBS = 1_000_000
MEDIA = re.compile(
    r"\b(cbs|nbc|abc news|cnn|fox news|fox 5|pbs|bbc|sky news|national geographic|nat ?geo|discovery|"
    r"animal planet|smithsonian|vox|vice news|business insider|bloomberg|reuters|associated press|"
    r"the guardian|new york times|washington post|al jazeera|dw news|france 24|wion|60 minutes|"
    r"good morning america|nowthis|cnbc|wall street journal|wsj|the economist|time magazine|newsweek|"
    r"the telegraph|msnbc|itv news|channel 4 news|cbc news|global news|sbs news|9 news|7news|wired|"
    r"scientific american)\b", re.I)
# Brands whose names are ordinary words: matched only as the whole channel name, so "History Matters"
# or "Today I Found Out" are judged by their size, not their name.
MEDIA_EXACT = {"history", "today", "insider", "the independent", "abc", "vice", "fox", "nbc", "cbs", "pbs"}

PATTERNS = {
    "question": re.compile(r"\?|^\s*(why|how|what|who|when|where|is|are|did|does|do|can|could|would)\b", re.I),
    "heres_why": re.compile(r"\bhere'?s (why|how|what)\b|\bexplained\b|\bthe reason\b", re.I),
    "new_development": re.compile(r"\b(just|finally|now|new|first time|did the impossible|breakthrough|"
                                  r"after \d+ years|is back|returns?)\b", re.I),
    "conflict": re.compile(r"\b(can'?t|cannot|impossible|stop|losing|winning|war|fight|battle|overrun|"
                           r"invasion|invade|taking over|out of control|nothing can)\b", re.I),
    "superlative": re.compile(r"\b(worst|biggest|largest|deadliest|most|giant|monster|massive|insane|"
                              r"craziest|scariest)\b", re.I),
    "number": re.compile(r"\d|\b(one|two|three|four|five|six|seven|eight|nine|ten|hundred|"
                         r"thousand|million|billion)\b", re.I),
    "caps": re.compile(r"\b[A-Z]{4,}\b"),
    "statement_then_why": re.compile(r"[.!]\s+(here'?s why|why|but why)", re.I),
}


def is_media(channel_title: str, subs: int, max_subs: int = MAX_SUBS) -> bool:
    """Established media: a big audience or a media brand, so the views are not the title's doing."""
    name = (channel_title or "").strip()
    return subs > max_subs or name.lower() in MEDIA_EXACT or bool(MEDIA.search(name))


def title_patterns(title: str) -> list[str]:
    return [name for name, rx in PATTERNS.items() if rx.search(title or "")]


def keyword_position(title: str, keywords: list[str]) -> int | None:
    """Word index of the first topic keyword in the title (0 = it leads)."""
    words = re.findall(r"[a-z0-9']+", (title or "").lower())
    for i, w in enumerate(words):
        if any(w.startswith(k.lower().split()[0]) for k in keywords):
            return i
    return None


def ratio(row: dict) -> float:
    return row["ratio_baseline"] if row.get("ratio_baseline") is not None else row.get("ratio_subs") or 0.0


def pattern_lift(rows: list[dict]) -> list[dict]:
    """Per pattern: median over-performance of titles with it vs. without it, and how many carry it."""
    out = []
    for name in PATTERNS:
        with_p = [ratio(r) for r in rows if name in r["patterns"]]
        without = [ratio(r) for r in rows if name not in r["patterns"]]
        if not with_p or not without:
            out.append({"pattern": name, "n_with": len(with_p), "median_with": None, "median_without": None,
                        "lift": None})
            continue
        mw, mo = statistics.median(with_p), statistics.median(without)
        out.append({"pattern": name, "n_with": len(with_p), "median_with": round(mw, 2),
                    "median_without": round(mo, 2), "lift": round(mw / mo, 2) if mo else None})
    return sorted(out, key=lambda r: -(r["lift"] or 0))


def run(get, phrases: list[str], must: list[str], months: int = 36, min_views: int = 50_000,
        max_subs: int = MAX_SUBS, orders: tuple = ("relevance", "viewCount"), max_channels: int = 60) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    after = (now - dt.timedelta(days=30 * months)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids = []
    for phrase in phrases:
        for order in orders:
            ids += osc.search_seed(get, phrase, after, order=order)
    videos = osc.fetch_videos(get, ids)
    kept = [v for v in videos.values()
            if osc.seconds(v.get("contentDetails", {}).get("duration")) >= osc.LONG_FORM_SEC
            and osc.title_matches(v["snippet"].get("title", ""), must)
            and int(v.get("statistics", {}).get("viewCount") or 0) >= min_views]
    channels = osc.fetch_channels(get, [v["snippet"]["channelId"] for v in kept])
    media, independent = [], []
    for v in kept:
        ch = channels.get(v["snippet"]["channelId"]) or {}
        (media if is_media(v["snippet"].get("channelTitle", ""), ch.get("subs", 0), max_subs) else independent).append(v)
    baselines = {}
    for v in sorted(independent, key=lambda x: -int(x["statistics"].get("viewCount") or 0))[:max_channels]:
        cid = v["snippet"]["channelId"]
        if cid not in baselines:
            try:
                baselines[cid] = osc.channel_baseline(get, (channels.get(cid) or {}).get("uploads", ""), {v["id"]})
            except Exception:  # noqa: BLE001 - one channel's error must not lose the run
                baselines[cid] = None
    rows = []
    for v in independent:
        cid = v["snippet"]["channelId"]
        row = osc.score(v, channels.get(cid), baselines.get(cid), now)
        row["patterns"] = title_patterns(row["title"])
        row["keyword_position"] = keyword_position(row["title"], must)
        row["title_words"] = len(row["title"].split())
        row["thumbnail"] = ((v["snippet"].get("thumbnails") or {}).get("high") or {}).get("url", "")
        rows.append(row)
    rows.sort(key=lambda r: -ratio(r))
    return {"generated": now.isoformat(timespec="seconds"), "phrases": phrases, "must": must,
            "params": {"months": months, "min_views": min_views, "max_subs": max_subs, "orders": list(orders)},
            "quota_used": getattr(get, "units", None), "videos_found": len(videos), "kept": len(kept),
            "media_excluded": [{"title": v["snippet"]["title"], "channel": v["snippet"]["channelTitle"],
                                "views": int(v["statistics"].get("viewCount") or 0)} for v in media],
            "winners": rows, "pattern_lift": pattern_lift(rows)}


def thumbs_sheet(rows: list[dict], out: str, n: int = 12) -> str:
    """The top winners' thumbnails in a grid, each labelled with views, subscribers and its title."""
    from io import BytesIO
    from PIL import Image, ImageDraw
    tiles = []
    for r in rows[:n]:
        if not r.get("thumbnail"):
            continue
        with urllib.request.urlopen(r["thumbnail"], timeout=20) as resp:   # public YouTube image CDN
            im = Image.open(BytesIO(resp.read())).convert("RGB").resize((320, 180))
        canvas = Image.new("RGB", (320, 240), (15, 15, 15))
        canvas.paste(im, (0, 0))
        d = ImageDraw.Draw(canvas)
        d.text((4, 184), f"{r['views']:,} views · {r['subs']:,} subs · {ratio(r)}x", fill=(255, 230, 0))
        d.text((4, 200), r["title"][:52], fill=(230, 230, 230))
        d.text((4, 216), r["title"][52:104], fill=(230, 230, 230))
        tiles.append(canvas)
    cols = 4
    sheet = Image.new("RGB", (cols * 320, ((len(tiles) + cols - 1) // cols) * 240), (0, 0, 0))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * 320, (i // cols) * 240))
    sheet.save(out, quality=90)
    return out


def report(result: dict, topic: str, sheet: str = "") -> str:
    lines = [f"# Title scout: {topic} ({result['generated'][:10]})", "",
             f"Phrases: {', '.join(result['phrases'])} · must: {', '.join(result['must'])} · "
             f"{result['videos_found']} videos found, {result['kept']} long-form on topic, "
             f"{len(result['media_excluded'])} established media excluded · ~{result['quota_used']} units", ""]
    if sheet:
        lines += [f"Thumbnails: `{sheet}`", ""]
    lines += ["## Winning titles outside established media", "",
              "| × channel | views | subs | age (d) | title | patterns |", "|---:|---:|---:|---:|---|---|"]
    for r in result["winners"][:15]:
        lines.append(f"| {ratio(r)} | {r['views']:,} | {r['subs']:,} | {r['days']} | {r['title']} | "
                     f"{', '.join(r['patterns']) or '—'} |")
    lines += ["", "## Pattern lift (median over-performance with vs. without)", "",
              "| pattern | titles with it | median with | median without | lift |", "|---|---:|---:|---:|---:|"]
    for p in result["pattern_lift"]:
        lines.append(f"| {p['pattern']} | {p['n_with']} | {p['median_with']} | {p['median_without']} | {p['lift']} |")
    lines += ["", "## Excluded as established media", ""]
    lines += [f"- {m['views']:,} · {m['channel']} · {m['title']}" for m in result["media_excluded"][:12]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("topic")
    ap.add_argument("--phrase", action="append", required=True, help="a search a viewer would type (repeatable)")
    ap.add_argument("--must", action="append", default=[], help="title keyword alternatives that keep a video on topic")
    ap.add_argument("--out", required=True)
    ap.add_argument("--months", type=int, default=36)
    ap.add_argument("--min-views", type=int, default=50_000)
    ap.add_argument("--max-subs", type=int, default=MAX_SUBS)
    ap.add_argument("--orders", default="relevance,viewCount")
    ap.add_argument("--max-channels", type=int, default=60)
    ap.add_argument("--thumbs", action="store_true", help="also save a sheet of the winners' thumbnails")
    ap.add_argument("--report", default="", help="markdown report path (default topics/reports/titles_<topic>_<date>.md)")
    args = ap.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.expanduser("~/ai-video-gen-local"), ".env"))
    load_dotenv(os.path.join(ROOT, ".env"))
    get = osc.Api(os.environ["YOUTUBE_API_KEY"])
    result = run(get, args.phrase, args.must, args.months, args.min_views, args.max_subs,
                 tuple(o.strip() for o in args.orders.split(",") if o.strip()), args.max_channels)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=1, ensure_ascii=False)
    sheet = thumbs_sheet(result["winners"], os.path.splitext(args.out)[0] + "_thumbs.jpg") if args.thumbs else ""
    md = args.report or os.path.join(ROOT, "topics", "reports", f"titles_{args.topic}_{result['generated'][:10]}.md")
    with open(md, "w", encoding="utf-8") as handle:
        handle.write(report(result, args.topic, sheet))
    print(f"~{result['quota_used']} units; {len(result['winners'])} independent winners; report {md}")
    for r in result["winners"][:10]:
        print(f"{ratio(r):>7}x {r['views']:>11,} {r['subs']:>10,} subs  {r['title'][:80]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
