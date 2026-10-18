#!/usr/bin/env python3
"""Title scout: which TITLES already win on a topic, outside established media.

    python3 scripts/title_scout.py burmese-pythons \
        --phrase "florida pythons" --phrase "python hunters everglades" --phrase "why can't florida stop pythons" \
        --must python --out topics/titles/burmese-pythons_2026-10-19.json --thumbs

The outlier scout finds topics. This finds the title shapes that do the work for one topic:
- search the phrasings a viewer would type, by relevance and by view count;
- drop established media (a subscriber cap and a list of media brands);
- score every video against its channel AT THE TIME: the median of the ten long-form uploads
  immediately before it, not the channel's latest uploads (a 2024 hit is not judged by 2026 views);
- code every title's editorial form: a direct question, a How/Why explanation ("Why Crumbl Cookies
  Can't Survive": the outcome stated, the explanation promised), or a statement;
- build a comparison set with the flops in it: each winning channel's ten uploads before its hit, each
  scored against its own preceding ten and classed high (>= 2x), ordinary or low (< 0.5x);
- report the share of each form that reached high, pooled, per channel and with channels weighted
  equally, and the form the evidence favours ("too_thin" when no two forms have five titles each).

Winners alone cannot show a title advantage: a 10-18 report found 6 of 8 winners were statements, and
so were 75% of the ordinary uploads beside them. The comparison set is the denominator. The view
floor applies to finding winners only; the comparison set keeps every upload, flops included.

Winners are evidence of what a viewer clicks. Our title uses a proven form with our own facts and
angle, never a copied title (the rule for scripts holds here too). The same title earned 2.3M views
on one channel and 42 on another, so a form is a hypothesis to test on our own film, not a recipe.

Quota: 100 units per search (phrases x orders) and about 6-10 per channel history (up to four pages of
uploads plus their statistics). Four phrases by two orders with 60 channels is about 1,300 units.
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

# Editorial form, coded in priority order: a direct question, else a How/Why explanation, else a
# statement. "Why Can't Anyone Live at Chernobyl?" asks; "Why Crumbl Cookies Can't Survive" states the
# outcome and promises the explanation. The 10-18 cohorts split them: questions reached high least
# often, explanations most. A missing question mark does not make a title a statement, and a How or
# Why does not make it a question: the word after it decides (an auxiliary verb inverts it).
FORMS = ("question", "how_why", "statement")
_AUX = (r"(is|are|was|were|isn'?t|aren'?t|wasn'?t|do|does|did|don'?t|doesn'?t|didn'?t|can|can'?t|cannot|"
        r"could|couldn'?t|will|won'?t|would|wouldn'?t|should|shouldn'?t|has|have|had|hasn'?t|haven'?t|"
        r"may|might|must)")
_CLAUSE = r"(?:^|[.!:|\-–—]\s+)\s*[\"'“]?"                   # the title's start, or a new sentence or part
DIRECT_QUESTION = re.compile(
    rf"{_CLAUSE}(why|how|what|who|when|where|which)\s+{_AUX}\b"   # Why Can't..., How Is Money Deleted
    rf"|^\s*{_AUX}\s"                                              # Is Solar Power About to..., Can Robots...
    r"|^\s*(what|who)\s+(happened|happens|went|killed|caused|made|changed)\b"
    r"|^\s*what if\b", re.I)
HOW_WHY = re.compile(rf"{_CLAUSE}(why|how)\b|\bhere'?s (why|how|what)\b", re.I)
MIN_CELL = 5            # fewer titles than this in a form is too thin to read


def title_form(title: str) -> str:
    t = title or ""
    if "?" in t or DIRECT_QUESTION.search(t):
        return "question"
    if HOW_WHY.search(t):
        return "how_why"
    return "statement"


PATTERNS = {
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
    """The title's form (unless a plain statement) followed by every wording cue it carries."""
    form = title_form(title)
    return ([form] if form != "statement" else []) + [n for n, rx in PATTERNS.items() if rx.search(title or "")]


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
    for name in ("question", "how_why", *PATTERNS):
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


def channel_history(get, uploads: str, back_to: str = "", max_pages: int = 4, cushion: int = 30) -> list[dict]:
    """The channel's public long-form uploads, oldest first, with exact views. Shorts and past live
    streams are left out: they are not the upload a viewer compares a film with. Pages back until
    `cushion` uploads predate `back_to` (a ten-upload comparison window plus each of those uploads'
    own preceding ten, with room for Shorts), or max_pages."""
    if not uploads:
        return []
    ids, dates, token = [], [], None
    for _ in range(max_pages):
        params = {"part": "contentDetails", "playlistId": uploads, "maxResults": 50}
        if token:
            params["pageToken"] = token
        page = get("playlistItems", **params)
        for item in page.get("items", []):
            cd = item.get("contentDetails", {})
            if cd.get("videoId"):
                ids.append(cd["videoId"])
                dates.append(cd.get("videoPublishedAt", ""))
        token = page.get("nextPageToken")
        if not token or (back_to and sum(1 for d in dates if d and d < back_to) >= cushion):
            break
    out = []
    for batch in osc._batches(ids):
        for v in get("videos", part="snippet,statistics,contentDetails,liveStreamingDetails",
                     id=",".join(batch)).get("items", []):
            sn = v.get("snippet", {})
            if "liveStreamingDetails" in v or sn.get("liveBroadcastContent", "none") != "none":
                continue
            if osc.seconds(v.get("contentDetails", {}).get("duration")) < osc.LONG_FORM_SEC:
                continue
            out.append({"video_id": v["id"], "title": sn.get("title", ""), "channel": sn.get("channelTitle", ""),
                        "published": sn.get("publishedAt", ""), "views": int(v.get("statistics", {}).get("viewCount") or 0)})
    return sorted(out, key=lambda h: h["published"])


def prior_baseline(history: list[dict], index: int, n: int = 10, min_n: int = 5) -> float | None:
    """Median views of the n long-form uploads immediately before history[index]: the channel as it
    was when the video came out. None with fewer than min_n of them (a new channel or a short history)."""
    prior = [h["views"] for h in history[max(0, index - n):index]]
    return float(statistics.median(prior)) if len(prior) >= min_n else None


def recent_baseline(history: list[dict], exclude: set, n: int = 10, min_n: int = 5) -> float | None:
    """Fallback when the video is older than the history fetched: the latest n uploads' median."""
    recent = [h["views"] for h in history if h["video_id"] not in exclude][-n:]
    return float(statistics.median(recent)) if len(recent) >= min_n else None


def outcome(r: float) -> str:
    return "high" if r >= 2.0 else "low" if r < 0.5 else "ordinary"


def _days(published: str, now: dt.datetime) -> int:
    return max(1, (now - dt.datetime.fromisoformat(published.replace("Z", "+00:00"))).days)


def comparison_rows(history: list[dict], anchor: int, exclude: set, now: dt.datetime, after: str,
                    n: int = 10, min_age_days: int = 30) -> list[dict]:
    """The channel's n uploads before its hit, each scored against its own preceding ten. Other search
    hits stay in the winners table, not here. Uploads under 30 days old or outside the window are out."""
    rows = []
    for j in range(max(0, anchor - n), anchor):
        h = history[j]
        if h["video_id"] in exclude or h["published"] < after or _days(h["published"], now) < min_age_days:
            continue
        base = prior_baseline(history, j)
        if base is None:
            continue
        r = h["views"] / max(base, osc.SUBS_FLOOR)
        rows.append({"video_id": h["video_id"], "title": h["title"], "channel": h["channel"],
                     "channel_id": h.get("channel_id", ""), "published": h["published"][:10],
                     "days": _days(h["published"], now), "views": h["views"], "baseline": base,
                     "ratio_baseline": round(r, 3), "outcome": outcome(r), "form": title_form(h["title"]),
                     "patterns": title_patterns(h["title"])})
    return rows


def _rate(k: int, n: int) -> float | None:
    return round(k / n, 3) if n else None


def form_outcomes(rows: list[dict]) -> dict:
    """Per form: how many titles, and how many reached high, stayed ordinary or fell low."""
    out = {}
    for f in FORMS:
        grp = [r for r in rows if r["form"] == f]
        hi = sum(r["outcome"] == "high" for r in grp)
        lo = sum(r["outcome"] == "low" for r in grp)
        out[f] = {"n": len(grp), "high": hi, "ordinary": len(grp) - hi - lo, "low": lo,
                  "high_rate": _rate(hi, len(grp)), "low_rate": _rate(lo, len(grp)), "thin": len(grp) < MIN_CELL}
    return out


def channel_weighted(rows: list[dict]) -> dict:
    """Each channel's high rate per form, averaged with every channel counting once: one prolific
    channel's habits (GEN titles 13 of 20 uploads How/Why) must not stand in for the field."""
    by_channel: dict[str, list[dict]] = {}
    for r in rows:
        by_channel.setdefault(r["channel_id"] or r["channel"], []).append(r)
    out = {}
    for f in FORMS:
        rates = [sum(r["outcome"] == "high" for r in grp if r["form"] == f) / n
                 for grp in by_channel.values() if (n := sum(r["form"] == f for r in grp))]
        out[f] = {"channels": len(rates), "mean_high_rate": round(statistics.mean(rates), 3) if rates else None}
    return out


def within_channel(rows: list[dict]) -> list[dict]:
    """Channels that used both question and non-question titles: the high-rate gap holds the channel's
    audience, voice and thumbnails fixed (positive favours non-question titles)."""
    by_channel: dict[str, list[dict]] = {}
    for r in rows:
        by_channel.setdefault(r["channel"], []).append(r)
    out = []
    for name, grp in by_channel.items():
        q = [r for r in grp if r["form"] == "question"]
        other = [r for r in grp if r["form"] != "question"]
        if q and other:
            hq = _rate(sum(r["outcome"] == "high" for r in q), len(q))
            ho = _rate(sum(r["outcome"] == "high" for r in other), len(other))
            out.append({"channel": name, "n_question": len(q), "n_other": len(other),
                        "high_rate_question": hq, "high_rate_other": ho, "gap": round(ho - hq, 3)})
    return out


def winner_forms(rows: list[dict]) -> dict:
    """Forms of the mature winners: at least 2x their channel at the time, at least 30 days old."""
    sel = [r for r in rows if r.get("baseline_kind") == "prior_ten" and (r.get("ratio_baseline") or 0) >= 2
           and r["days"] >= 30]
    return {"n": len(sel), **{f: sum(r["form"] == f for r in sel) for f in FORMS}}


def favours(outcomes: dict, margin: float = 0.10) -> str:
    """The form with the highest high rate among forms with at least MIN_CELL titles, when it leads the
    next by `margin`; "mixed" when it does not; "too_thin" when fewer than two forms qualify."""
    ok = sorted(((v["high_rate"], f) for f, v in outcomes.items() if v["n"] >= MIN_CELL), reverse=True)
    if len(ok) < 2:
        return "too_thin"
    return ok[0][1] if ok[0][0] - ok[1][0] >= margin else "mixed"


def run(get, phrases: list[str], must: list[str], months: int = 36, min_views: int = 50_000,
        max_subs: int = MAX_SUBS, orders: tuple = ("relevance", "viewCount"), max_channels: int = 60,
        max_pages: int = 4) -> dict:
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
    # Channels in order of their most-viewed hit; the first max_channels get a history.
    by_channel: dict[str, list[dict]] = {}
    for v in sorted(independent, key=lambda x: -int(x["statistics"].get("viewCount") or 0)):
        by_channel.setdefault(v["snippet"]["channelId"], []).append(v)
    hits = {v["id"] for v in independent}
    rows, comparison, coverage = [], [], {"channels": 0, "with_history": 0, "anchored": 0}
    for rank, (cid, vids) in enumerate(by_channel.items()):
        ch = channels.get(cid) or {}
        history = []
        if rank < max_channels:
            coverage["channels"] += 1
            try:
                history = channel_history(get, ch.get("uploads", ""),
                                          back_to=min(v["snippet"]["publishedAt"] for v in vids), max_pages=max_pages)
            except Exception:  # noqa: BLE001 - one channel's error must not lose the run
                history = []
            coverage["with_history"] += bool(history)
        for h in history:
            h["channel_id"] = cid
        index = {h["video_id"]: i for i, h in enumerate(history)}
        for v in vids:
            i = index.get(v["id"])
            base, kind = (prior_baseline(history, i), "prior_ten") if i is not None else (recent_baseline(history, hits), "recent")
            row = osc.score(v, ch, base, now)
            row["baseline_kind"] = kind if base is not None else None
            row["form"] = title_form(row["title"])
            row["patterns"] = title_patterns(row["title"])
            row["keyword_position"] = keyword_position(row["title"], must)
            row["title_words"] = len(row["title"].split())
            row["thumbnail"] = ((v["snippet"].get("thumbnails") or {}).get("high") or {}).get("url", "")
            rows.append(row)
        if vids[0]["id"] in index:          # the channel's most-viewed hit anchors its comparison window
            coverage["anchored"] += 1
            comparison += comparison_rows(history, index[vids[0]["id"]], hits, now, after)
    rows.sort(key=lambda r: -ratio(r))
    outcomes = form_outcomes(comparison)
    return {"generated": now.isoformat(timespec="seconds"), "phrases": phrases, "must": must,
            "params": {"months": months, "min_views": min_views, "max_subs": max_subs, "orders": list(orders),
                       "max_channels": max_channels, "max_pages": max_pages},
            "quota_used": getattr(get, "units", None), "videos_found": len(videos), "kept": len(kept),
            "media_excluded": [{"title": v["snippet"]["title"], "channel": v["snippet"]["channelTitle"],
                                "views": int(v["statistics"].get("viewCount") or 0)} for v in media],
            "winners": rows, "coverage": coverage, "comparison": comparison,
            "form_outcomes": outcomes, "channel_weighted": channel_weighted(comparison),
            "within_channel": within_channel(comparison), "winner_forms": winner_forms(rows),
            "favours": favours(outcomes), "pattern_lift": pattern_lift(comparison)}


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
    cov = result.get("coverage") or {}
    lines += ["## Winning titles outside established media", "",
              "× channel = views over the median of the channel's ten long-form uploads before the video "
              "(\"then\"); \"recent\" marks a video older than the history fetched, judged by the latest ten.", "",
              "| × channel | baseline | views | subs | age (d) | form | title | cues |",
              "|---:|---|---:|---:|---:|---|---|---|"]
    for r in result["winners"][:15]:
        kind = {"prior_ten": "then", "recent": "recent"}.get(r.get("baseline_kind"), "subs")
        cues = [p for p in r["patterns"] if p not in FORMS]
        lines.append(f"| {ratio(r)} | {kind} | {r['views']:,} | {r['subs']:,} | {r['days']} | {r.get('form', '')} | "
                     f"{r['title']} | {', '.join(cues) or '—'} |")
    fo, comp = result.get("form_outcomes") or {}, result.get("comparison") or []
    lines += ["", "## Title form vs. outcome: the comparison set", "",
              f"Each winning channel's ten uploads before its hit ({len(comp)} titles from {cov.get('anchored', 0)} of "
              f"{cov.get('channels', 0)} channels), each against its own preceding ten. High >= 2x, low < 0.5x. "
              f"Flops are included; the view floor does not apply here.", "",
              "| form | titles | high | ordinary | low | high rate | low rate | |", "|---|---:|---:|---:|---:|---:|---:|---|"]
    for f in FORMS:
        v = fo.get(f) or {}
        pct = lambda x: f"{x:.0%}" if x is not None else "—"  # noqa: E731
        lines.append(f"| {f} | {v.get('n', 0)} | {v.get('high', 0)} | {v.get('ordinary', 0)} | {v.get('low', 0)} | "
                     f"{pct(v.get('high_rate'))} | {pct(v.get('low_rate'))} | {'too thin' if v.get('thin') else ''} |")
    cw = result.get("channel_weighted") or {}
    weighted = "; ".join(f"{f} {cw[f]['mean_high_rate']:.0%} over {cw[f]['channels']} channels" for f in FORMS
                         if (cw.get(f) or {}).get("mean_high_rate") is not None)
    lines += ["", f"Channels weighted equally (mean of each channel's high rate): {weighted or '—'}"]
    wc = result.get("within_channel") or []
    if wc:
        lines += ["", "Within channel (same audience, voice and thumbnails; gap > 0 favours non-question titles):", "",
                  "| channel | question titles | other titles | high rate: question | high rate: other | gap |",
                  "|---|---:|---:|---:|---:|---:|"]
        lines += [f"| {w['channel']} | {w['n_question']} | {w['n_other']} | {w['high_rate_question']:.0%} | "
                  f"{w['high_rate_other']:.0%} | {w['gap']:+.0%} |" for w in wc]
    wf = result.get("winner_forms") or {}
    if wf.get("n") and comp:
        share = lambda k, n: f"{k}/{n} ({k / n:.0%})"  # noqa: E731
        lines += ["", f"Mature winners (>= 2x then, >= 30 days) vs. the comparison set: " + "; ".join(
            f"{f} {share(wf[f], wf['n'])} vs {share((fo.get(f) or {}).get('n', 0), len(comp))}" for f in FORMS)]
    lines += ["", f"**Favours: {result.get('favours', '—')}** (the highest high rate among forms with at least "
              f"{MIN_CELL} titles, when it leads the next by 10 points; observational, not a forecast for our film).", ""]
    lines += ["## Wording cues in the comparison set (median × channel with vs. without)", "",
              "| cue | titles with it | median with | median without | lift |", "|---|---:|---:|---:|---:|"]
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
    ap.add_argument("--max-pages", type=int, default=4, help="upload pages of 50 fetched per channel history")
    ap.add_argument("--thumbs", action="store_true", help="also save a sheet of the winners' thumbnails")
    ap.add_argument("--report", default="", help="markdown report path (default topics/reports/titles_<topic>_<date>.md)")
    args = ap.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.expanduser("~/ai-video-gen-local"), ".env"))
    load_dotenv(os.path.join(ROOT, ".env"))
    get = osc.Api(os.environ["YOUTUBE_API_KEY"])
    result = run(get, args.phrase, args.must, args.months, args.min_views, args.max_subs,
                 tuple(o.strip() for o in args.orders.split(",") if o.strip()), args.max_channels, args.max_pages)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=1, ensure_ascii=False)
    sheet = thumbs_sheet(result["winners"], os.path.splitext(args.out)[0] + "_thumbs.jpg") if args.thumbs else ""
    md = args.report or os.path.join(ROOT, "topics", "reports", f"titles_{args.topic}_{result['generated'][:10]}.md")
    with open(md, "w", encoding="utf-8") as handle:
        handle.write(report(result, args.topic, sheet))
    print(f"~{result['quota_used']} units; {len(result['winners'])} independent winners; "
          f"{len(result['comparison'])} comparison titles; favours {result['favours']}; report {md}")
    for r in result["winners"][:10]:
        print(f"{ratio(r):>7}x {r['views']:>11,} {r['subs']:>10,} subs  {r['title'][:80]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
