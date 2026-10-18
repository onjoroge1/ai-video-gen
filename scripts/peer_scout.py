#!/usr/bin/env python3
"""Peer scout: how often channels like ours break out, measured upload by upload.

    python3 scripts/peer_scout.py \
        --handoff ~/Documents/video/assets/user_provided_doc/consequence_research_audit_2026-10-18.json \
        --out topics/peers/peers_2026-10-19.json --report topics/reports/peers_2026-10-19.md
    python3 scripts/peer_scout.py --channel UCxxxx --channel UCyyyy --out ...

Every public long-form upload in the window is scored against the median of the ten long-form uploads
immediately before it, the same baseline title_scout uses for a winner. High is at least 2x, low under
0.5x. An upload with fewer than ten earlier uploads stays unscored and is never padded. Uploads under
30 days old are listed but kept out of the rates. Shorts and past live streams are not long-form uploads.

Per channel: subscribers, long-form uploads in the last 12 months, the latest ten uploads' median views
and runtime, how many uploads could be scored, the share at >= 2x and >= 10x, and the three biggest
multiples beside the three biggest raw view counts (a raw leader with a short history has no multiple).
Pooled: high and low rates by title form and by runtime band, also with every channel weighted equally.

Why: ChatGPT's 10-18 peer pass verified 17 faceless, illustrated candidate channels but could not count
their full catalogues, and handed the channel IDs to our API (scout_handoff.B in its audit JSON). The
benchmark question is what a channel like ours can expect: how often a typical upload doubles its
channel's norm, and at what runtime. Cipher's 6.3M-view upload had fewer than ten earlier uploads, so a
raw view count is not a breakout.

Quota: 1 unit per 50 channels, plus 2 per page of 50 uploads (up to --max-pages per channel). Seventeen
channels at 8 pages is at most about 275 units.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import outlier_scout as osc  # noqa: E402
import title_scout as ts  # noqa: E402

PRIOR = 10                  # earlier uploads a score needs
MIN_AGE_DAYS = 30
BANDS = ((0, 480, "under 8 min"), (480, 900, "8-15 min"), (900, 1500, "15-25 min"), (1500, 10 ** 9, "25+ min"))


def band(seconds: int) -> str:
    return next(name for lo, hi, name in BANDS if lo <= seconds < hi)


def load_handoff(path: str) -> tuple[list[dict], str, str]:
    """Channel IDs and the window from the ChatGPT audit's scout handoff."""
    data = json.load(open(os.path.expanduser(path)))
    b = (data.get("scout_handoff") or {}).get("B") or {}
    channels = [{"channel_id": c["channel_id"], "name": c.get("name", "")} for c in b.get("channels") or []]
    return channels, b.get("window_start", ""), b.get("window_end", "")


def score_uploads(history: list[dict], start: str, end: str, now: dt.datetime) -> tuple[list[dict], list[dict]]:
    """(scored, unscored) for every upload published in [start, end]. Scored rows carry the multiple of
    views over the median of exactly the ten uploads before; unscored rows carry the reason."""
    scored, unscored = [], []
    for i, h in enumerate(history):
        day = h["published"][:10]
        if not (start <= day <= end):
            continue
        days = ts._days(h["published"], now)
        base_row = {"video_id": h["video_id"], "title": h["title"], "channel": h.get("channel", ""),
                    "channel_id": h.get("channel_id", ""), "published": day, "days": days, "views": h["views"],
                    "duration_sec": h.get("duration_sec", 0), "form": ts.title_form(h["title"])}
        prior = [p["views"] for p in history[max(0, i - PRIOR):i]]
        if len(prior) < PRIOR:
            unscored.append(dict(base_row, reason=f"{len(prior)} earlier long-form uploads fetched, ten needed"))
            continue
        base = float(statistics.median(prior))
        if base <= 0:
            unscored.append(dict(base_row, reason="the ten earlier uploads have no views"))
            continue
        r = h["views"] / base
        scored.append(dict(base_row, baseline=base, multiple=round(r, 3),
                           outcome=ts.outcome(r) if days >= MIN_AGE_DAYS else "young"))
    return scored, unscored


def mature(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["outcome"] in ("high", "ordinary", "low")]


def channel_summary(channel: dict, history: list[dict], scored: list[dict], unscored: list[dict],
                    info: dict, start: str, now: dt.datetime) -> dict:
    latest = history[-PRIOR:]
    year_ago = (now - dt.timedelta(days=365)).strftime("%Y-%m-%d")
    last_year = sum(1 for h in history if h["published"][:10] >= year_ago)
    earliest = history[0]["published"][:10] if history else ""
    # A history that stopped while older uploads remained and never reached the window start is partial.
    complete = bool(history) and (not info.get("more") or earliest <= start)
    m = mature(scored)
    n = len(m)
    hi2 = sum(r["multiple"] >= 2 for r in m)
    hi10 = sum(r["multiple"] >= 10 for r in m)
    lo = sum(r["outcome"] == "low" for r in m)
    top_multiple = sorted(m, key=lambda r: -r["multiple"])[:3]
    by_views = sorted(scored + unscored, key=lambda r: -r["views"])[:3]
    return {
        "channel_id": channel["channel_id"], "name": channel.get("name") or (latest[-1]["channel"] if latest else ""),
        "subs": channel.get("subs", 0), "history_uploads": len(history), "earliest_fetched": earliest,
        "window_covered": complete, "pages": info.get("pages", 0),
        "uploads_12m": last_year, "uploads_12m_is_lower_bound": bool(info.get("more")) and earliest > year_ago,
        "latest10_median_views": float(statistics.median(h["views"] for h in latest)) if latest else None,
        "latest10_median_runtime_sec": float(statistics.median(h.get("duration_sec", 0) for h in latest)) if latest else None,
        "scored": n, "unscored": len(unscored), "young": len(scored) - n,
        "share_2x": ts._rate(hi2, n), "share_10x": ts._rate(hi10, n), "share_low": ts._rate(lo, n),
        "top_multiples": [{k: r[k] for k in ("title", "published", "views", "multiple", "duration_sec")} for r in top_multiple],
        "top_views": [{"title": r["title"], "published": r["published"], "views": r["views"],
                       "multiple": r.get("multiple"), "reason": r.get("reason", "")} for r in by_views],
    }


def band_outcomes(rows: list[dict]) -> dict:
    out = {}
    for _, _, name in BANDS:
        grp = [r for r in rows if band(r["duration_sec"]) == name]
        hi = sum(r["outcome"] == "high" for r in grp)
        lo = sum(r["outcome"] == "low" for r in grp)
        out[name] = {"n": len(grp), "channels": len({r["channel_id"] for r in grp}), "high": hi, "low": lo,
                     "high_rate": ts._rate(hi, len(grp)), "low_rate": ts._rate(lo, len(grp)),
                     "thin": len(grp) < ts.MIN_CELL}
    return out


def run(get, channels: list[dict], start: str, end: str, max_pages: int = 8) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    meta = osc.fetch_channels(get, [c["channel_id"] for c in channels])
    summaries, scored_all, unscored_all = [], [], []
    for c in channels:
        ch = dict(c, **(meta.get(c["channel_id"]) or {}))
        info: dict = {}
        try:
            history = ts.channel_history(get, ch.get("uploads", ""), back_to=start + "T00:00:00Z",
                                         max_pages=max_pages, cushion=PRIOR + 2, info=info)
        except Exception as exc:  # noqa: BLE001 - one channel's error must not lose the run
            summaries.append({"channel_id": c["channel_id"], "name": c.get("name", ""), "error": str(exc)[:200]})
            continue
        for h in history:
            h["channel_id"] = c["channel_id"]
        scored, unscored = score_uploads(history, start, end, now)
        summaries.append(channel_summary(ch, history, scored, unscored, info, start, now))
        scored_all += scored
        unscored_all += unscored
    m = mature(scored_all)
    outcomes = ts.form_outcomes(m)
    return {"generated": now.isoformat(timespec="seconds"), "window": [start, end], "max_pages": max_pages,
            "quota_used": getattr(get, "units", None), "channels": summaries,
            "pooled": {"scored": len(m), "high": sum(r["outcome"] == "high" for r in m),
                       "low": sum(r["outcome"] == "low" for r in m)},
            "form_outcomes": outcomes, "channel_weighted": ts.channel_weighted(m),
            "within_channel": ts.within_channel(m), "favours": ts.favours(outcomes),
            "runtime_outcomes": band_outcomes(m), "rows": scored_all, "unscored": unscored_all}


def _pct(x) -> str:
    return f"{x:.0%}" if x is not None else "—"


def _mmss(sec) -> str:
    return f"{int(sec // 60)}:{int(sec % 60):02d}" if sec is not None else "—"


def report(result: dict) -> str:
    start, end = result["window"]
    lines = [f"# Peer scout ({result['generated'][:10]})", "",
             f"Window {start} to {end}. Each long-form upload against the median of the ten long-form uploads "
             f"before it; high >= 2x, low < 0.5x; under {MIN_AGE_DAYS} days old is kept out of the rates; an "
             f"upload without ten earlier uploads stays unscored. ~{result['quota_used']} units.", "",
             "| channel | subs | uploads 12m | latest-10 median views | latest-10 runtime | scored | >= 2x | >= 10x | low | window |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for c in result["channels"]:
        if c.get("error"):
            lines.append(f"| {c['name']} | error: {c['error']} |||||||||")
            continue
        twelve = ("≥" if c["uploads_12m_is_lower_bound"] else "") + str(c["uploads_12m"])
        views = f"{c['latest10_median_views']:,.0f}" if c["latest10_median_views"] is not None else "—"
        lines.append(f"| {c['name']} | {c['subs']:,} | {twelve} | {views} | {_mmss(c['latest10_median_runtime_sec'])} | "
                     f"{c['scored']} | {_pct(c['share_2x'])} | {_pct(c['share_10x'])} | {_pct(c['share_low'])} | "
                     f"{'complete' if c['window_covered'] else 'partial from ' + c['earliest_fetched']} |")
    p = result["pooled"]
    lines += ["", f"Pooled: {p['scored']} scored uploads, {p['high']} high, {p['low']} low.", "",
              "## Biggest multiples vs. biggest raw views", ""]
    for c in result["channels"]:
        if c.get("error"):
            continue
        tm = "; ".join(f"{r['multiple']:.1f}x {r['title'][:60]} ({r['views']:,})" for r in c["top_multiples"]) or "—"
        tv = "; ".join(f"{r['views']:,} {r['title'][:50]} ({str(r['multiple']) + 'x' if r['multiple'] is not None else 'no multiple'})"
                       for r in c["top_views"]) or "—"
        lines += [f"- **{c['name']}** — multiples: {tm}", f"  - raw views: {tv}"]
    lines += ["", "## Title form vs. outcome (pooled scored uploads)", "",
              "| form | uploads | high | low | high rate | low rate | |", "|---|---:|---:|---:|---:|---:|---|"]
    for f in ts.FORMS:
        v = result["form_outcomes"][f]
        lines.append(f"| {f} | {v['n']} | {v['high']} | {v['low']} | {_pct(v['high_rate'])} | {_pct(v['low_rate'])} | "
                     f"{'too thin' if v['thin'] else ''} |")
    cw = result["channel_weighted"]
    lines += ["", "Channels weighted equally: " + ("; ".join(
        f"{f} {_pct(cw[f]['mean_high_rate'])} over {cw[f]['channels']} channels" for f in ts.FORMS
        if cw[f]["mean_high_rate"] is not None) or "—"), "", f"**Favours: {result['favours']}**", "",
              "## Runtime band vs. outcome (pooled scored uploads)", "",
              "Descriptive only: runtime travels with channel, topic and production budget.", "",
              "| runtime | uploads | channels | high | low | high rate | low rate | |", "|---|---:|---:|---:|---:|---:|---:|---|"]
    for name, v in result["runtime_outcomes"].items():
        lines.append(f"| {name} | {v['n']} | {v['channels']} | {v['high']} | {v['low']} | {_pct(v['high_rate'])} | "
                     f"{_pct(v['low_rate'])} | {'too thin' if v['thin'] else ''} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--handoff", default="", help="ChatGPT audit JSON with scout_handoff.B (channel IDs and window)")
    ap.add_argument("--channel", action="append", default=[], help="a channel ID (repeatable)")
    ap.add_argument("--start", default="", help="window start YYYY-MM-DD (default: handoff, else three years ago)")
    ap.add_argument("--end", default="", help="window end YYYY-MM-DD (default: handoff, else today)")
    ap.add_argument("--max-pages", type=int, default=8)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", default="")
    args = ap.parse_args(argv)
    channels, start, end = load_handoff(args.handoff) if args.handoff else ([], "", "")
    channels += [{"channel_id": c, "name": ""} for c in args.channel]
    if not channels:
        ap.error("give --handoff or at least one --channel")
    today = dt.date.today()
    start = args.start or start or (today - dt.timedelta(days=3 * 365)).isoformat()
    end = args.end or end or today.isoformat()
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.expanduser("~/ai-video-gen-local"), ".env"))
    load_dotenv(os.path.join(ROOT, ".env"))
    get = osc.Api(os.environ["YOUTUBE_API_KEY"])
    result = run(get, channels, start, end, args.max_pages)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=1, ensure_ascii=False)
    md = args.report or os.path.join(ROOT, "topics", "reports", f"peers_{result['generated'][:10]}.md")
    with open(md, "w", encoding="utf-8") as handle:
        handle.write(report(result))
    p = result["pooled"]
    print(f"~{result['quota_used']} units; {len(result['channels'])} channels; {p['scored']} scored uploads, "
          f"{p['high']} high; favours {result['favours']}; report {md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
