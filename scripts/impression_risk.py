#!/usr/bin/env python3
"""Impression risk before production: will YouTube show this film to anyone?

    python3 scripts/impression_risk.py history                      # refresh our films' outcomes
    python3 scripts/impression_risk.py reach                        # merge the Reporting API reach reports
    python3 scripts/impression_risk.py check --slug chernobyl-wildlife
    python3 scripts/impression_risk.py check --title "..." --search "lionfish invasion"

Operator request (2026-10-21): our films are hit or miss on impressions, and the title scouts
measure the market but not whether YouTube will test the film at all. YouTube shows a new video
first to people it expects to want it, judged by topic against who already watches the channel;
title and thumbnail CTR then decide whether that test grows. So before production the risk is
mostly audience fit and demand, and this check reports three things:

1. AUDIENCE FIT: our past long-form films most like the proposed one (title, tags and description
   words), and how many of them landed in our bottom quarter of first-week exposure.
2. DEMAND: the measured market for the topic (topics/schedule.json `market`, from the market
   check): typical views, the count of 100K+ videos and small-channel breakouts.
3. SEED: our own Shorts on the topic, which give YouTube viewers to test the film on.

The outcome is first-7-day thumbnail impressions from the reach report (channel_reach_basic_a1,
reporting job created 2026-10-21) once enough films have it; until then, first-7-day views from
the home feed and suggested videos (YouTube's own recommendations), which is the part impressions
drive. "Low" is our own bottom quarter, so the threshold moves as the channel grows.

The verdict is a band (low risk / uncertain / high risk) with its reasons, never a percentage:
with under about 30 labelled films a probability would be false precision. Every check is
appended to predictions.jsonl so the bands can be scored against what happened (backtest).
Data stays in jobs/yt/impression_risk (git-ignored: analytics never enter the public repo).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

DATA = os.path.join(ROOT, "jobs", "yt", "impression_risk")
# YouTube choosing to show it: the Analytics API names the home feed SUBSCRIBER (it is not subscribers:
# 2,185 of cane toad's 2,186 viewers were unsubscribed) and suggested videos RELATED_VIDEO.
RECOMMENDED_SOURCES = ("SUBSCRIBER", "RELATED_VIDEO", "BROWSE", "SUGGESTED")
MIN_LABELLED = 8         # fewer comparable films than this and no band is given
MIN_IMPRESSION_FILMS = 8  # switch the outcome to impressions once this many films have 7 days of them
NEIGHBOURS = 5
MIN_SIMILARITY = 0.3
STRONG_MEDIAN = 200_000  # the operator's 200K topic rule (2026-10-15)

_STOP = set("""a an and are as at be but by can could did do does for from had has have how i if in into is it
its just me my no not of on or our out so than that the their them then there these they this those to too up
us was we were what when where which who why will with would you your about after again all also any because
been before being between both each few more most much now off once only other over own same she should some
still such through under until very while yes video videos film documentary explained shorts short bolt
world explains new why how""".split())


# --- text -------------------------------------------------------------------------------------

def _stem(word: str) -> str:
    for suffix in ("ies", "es", "s", "ing", "ed"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return word


def words(text: str) -> set[str]:
    """Content words, stemmed: the topic of a title, tags or description."""
    text = re.sub(r"'s\b", "", (text or "").lower().replace("’", "'"))  # Chernobyl's -> chernobyl
    return {_stem(w) for w in re.findall(r"[a-z][a-z-]+", text.replace("'", ""))
            if w not in _STOP and len(w) > 2}


def similarity(candidate: set[str], other: set[str]) -> float:
    """The share of the proposed film's topic words a past video also carries. Not Jaccard: a
    Short's 30 tags would swamp the union and hide a Short squarely on the topic."""
    return len(candidate & other) / len(candidate) if candidate and other else 0.0


def film_words(film: dict) -> set[str]:
    return words(" ".join([film.get("title", ""), " ".join(film.get("tags") or []),
                           film.get("description_head", "")]))


# --- outcomes ---------------------------------------------------------------------------------

def outcome_metric(films: list[dict]) -> str:
    """Impressions once enough films have seven days of them; recommended views until then."""
    n = sum(1 for f in films if f.get("impressions_7d") is not None)
    return "impressions_7d" if n >= MIN_IMPRESSION_FILMS else "recommended_views_7d"


def labelled(films: list[dict], metric: str) -> list[dict]:
    return [f for f in films if f.get("format") == "long" and f.get(metric) is not None]


def low_threshold(values: list[float]) -> float | None:
    """The bottom-quarter line (25th percentile, nearest rank) of our own films."""
    vals = sorted(values)
    if len(vals) < MIN_LABELLED:
        return None
    return vals[max(0, int(round(0.25 * (len(vals) - 1))))]


def neighbours(candidate: set[str], films: list[dict], k: int = NEIGHBOURS) -> list[dict]:
    scored = [dict(f, similarity=round(similarity(candidate, film_words(f)), 3)) for f in films]
    scored = [f for f in scored if f["similarity"] >= MIN_SIMILARITY]
    return sorted(scored, key=lambda f: -f["similarity"])[:k]


def demand(market: dict | None) -> tuple[int, str]:
    """+1 strong, -1 weak, 0 unmeasured or middling, with the reason."""
    if not market:
        return 0, "demand not measured: run the market check (topics/schedule.json `market`)"
    median, breakouts = int(market.get("median_views") or 0), int(market.get("small_breakouts") or 0)
    text = (f"market for {market.get('search')!r}: typical {median:,} views, "
            f"{market.get('n_100k', '?')} videos over 100K, {breakouts} small-channel breakouts")
    if median >= STRONG_MEDIAN and breakouts >= 3:
        return 1, "+ " + text
    if median < STRONG_MEDIAN or breakouts == 0:
        return -1, "- " + text
    return 0, "~ " + text


def assess(candidate_text: str, films: list[dict], market: dict | None = None,
           shorts: list[dict] | None = None) -> dict:
    """The band, its reasons and the evidence. Pure: everything it needs is passed in."""
    metric = outcome_metric(films)
    pool = labelled(films, metric)
    line = low_threshold([f[metric] for f in pool])
    cand = words(candidate_text)
    result = {"metric": metric, "films_labelled": len(pool), "low_line": line, "reasons": [],
              "neighbours": [], "band": "uncertain"}
    score = 0
    near = neighbours(cand, pool if line is not None else [f for f in films if f.get("format") == "long"])
    for f in near:
        f["low"] = line is not None and f[metric] <= line
    result["neighbours"] = [{k: f.get(k) for k in ("id", "title", "similarity", metric, "views", "low")}
                            for f in near]
    if line is None:
        result["reasons"].append(f"~ only {len(pool)} of our films have a full first week "
                                 f"(need {MIN_LABELLED}): evidence below, no band yet")
    elif len(near) >= 3:
        low = sum(f["low"] for f in near)
        rate = low / len(near)
        text = f"{low} of the {len(near)} most similar films we made landed in our bottom quarter"
        if rate >= 0.5:
            score -= 1
            result["reasons"].append("- " + text)
        elif rate <= 0.25:
            score += 1
            result["reasons"].append("+ " + text)
        else:
            result["reasons"].append("~ " + text)
    else:
        result["reasons"].append(f"~ only {len(near)} past film(s) on a similar topic: YouTube has "
                                 "little viewer history to match this film against")
    d, text = demand(market)
    score += d
    result["reasons"].append(text)
    seed = [s for s in shorts or [] if similarity(cand, film_words(s)) >= MIN_SIMILARITY]
    if seed:
        views = sorted(int(s.get("views") or 0) for s in seed)
        result["reasons"].append(f"+ {len(seed)} of our Shorts share the topic (median "
                                 f"{views[len(views) // 2]:,} views): viewers to test the film on")
        score += 1 if views[len(views) // 2] >= 500 else 0
    else:
        result["reasons"].append("~ no Shorts of ours on this topic yet")
    result["score"] = score
    if line is None:
        result["band"] = "insufficient data"
    else:
        result["band"] = "low risk" if score >= 2 else ("high risk" if score <= -1 else "uncertain")
    return result


def text_report(name: str, r: dict) -> str:
    lines = [f"IMPRESSION RISK: {name}", f"Band: {r['band'].upper()}"
             + (f" (score {r['score']:+d})" if "score" in r else ""),
             f"Outcome: {r['metric']} over {r['films_labelled']} of our long-form films; "
             f"bottom-quarter line {r['low_line']}", "", "Reasons:"]
    lines += [f"  {x}" for x in r["reasons"]]
    if r["neighbours"]:
        lines += ["", "Most similar films we made:"]
        for f in r["neighbours"]:
            first = f.get(r["metric"])
            lines.append(f"  {'LOW ' if f['low'] else '    '}"
                         + (f"{first:>6} {r['metric']}" if first is not None else f"{'—':>6} (week not over)")
                         + f"  {f.get('views', 0):>6} views now  sim {f['similarity']:.2f}  {f['title']}")
    lines += ["", "A band with reasons, not a probability: too few films yet for a calibrated number.",
              "Thumbnails and titles drive the second wave (CTR); test them after upload."]
    return "\n".join(lines)


# --- data -------------------------------------------------------------------------------------

def _creds():
    from dotenv import load_dotenv
    for env in (os.path.join(ROOT, ".env"), os.path.expanduser("~/ai-video-gen-local/.env")):
        if os.path.exists(env):
            load_dotenv(env)
            break
    import youtube_channel_report as ycr
    return ycr._creds()


def _iso_seconds(value: str) -> int:
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    return sum(int(x or 0) * k for x, k in zip(m.groups(), (3600, 60, 1))) if m else 0


def pull_history(data: str) -> list[dict]:
    """Our uploads with first-week recommended views; keeps impressions merged earlier."""
    from googleapiclient.discovery import build
    creds = _creds()
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    ya = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)
    ch = yt.channels().list(part="id,contentDetails", mine=True).execute()["items"][0]
    uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    old = {f["id"]: f for f in load(data)}
    films, page, today = [], None, dt.date.today()
    while True:
        pl = yt.playlistItems().list(part="contentDetails", playlistId=uploads, maxResults=50,
                                     pageToken=page).execute()
        ids = [it["contentDetails"]["videoId"] for it in pl.get("items", [])]
        if ids:
            for v in yt.videos().list(part="snippet,contentDetails,statistics,status",
                                      id=",".join(ids)).execute().get("items", []):
                if v["status"].get("privacyStatus") != "public":
                    continue
                sec = _iso_seconds(v["contentDetails"].get("duration", ""))
                f = dict(old.get(v["id"], {}), id=v["id"], title=v["snippet"]["title"],
                         published=v["snippet"]["publishedAt"][:10], seconds=sec,
                         format="short" if sec <= 180 else "long",
                         views=int(v["statistics"].get("viewCount", 0)),
                         tags=v["snippet"].get("tags", []),
                         description_head=(v["snippet"].get("description") or "")[:300])
                start = dt.date.fromisoformat(f["published"])
                end = start + dt.timedelta(days=6)
                if end < today and f.get("sources_7d") is None:
                    rows = ya.reports().query(ids="channel==MINE", startDate=start.isoformat(),
                                              endDate=end.isoformat(), metrics="views",
                                              dimensions="insightTrafficSourceType",
                                              filters=f"video=={v['id']}").execute().get("rows", [])
                    by = {r[0]: int(r[1]) for r in rows}
                    f["views_7d"] = sum(by.values())
                    f["recommended_views_7d"] = sum(by.get(s, 0) for s in RECOMMENDED_SOURCES)
                    f["sources_7d"] = by
                if f.get("sources_7d") is not None:
                    f["recommended_views_7d"] = sum(f["sources_7d"].get(s, 0) for s in RECOMMENDED_SOURCES)
                films.append(f)
        page = pl.get("nextPageToken")
        if not page:
            break
    save(data, films)
    return films


def merge_reach(data: str) -> int:
    """Download every reach report not yet seen and set impressions_7d where 7 days are covered."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    yr = build("youtubereporting", "v1", credentials=_creds(), cache_discovery=False)
    jobs = [j for j in yr.jobs().list().execute().get("jobs", [])
            if j["reportTypeId"] == "channel_reach_basic_a1"]
    if not jobs:
        sys.exit("no channel_reach_basic_a1 reporting job: create one first")
    daily_path = os.path.join(data, "reach_daily.json")
    daily = json.load(open(daily_path)) if os.path.exists(daily_path) else {"seen": [], "rows": {}}
    reports = yr.jobs().reports().list(jobId=jobs[0]["id"]).execute().get("reports", [])
    for rep in reports:
        if rep["id"] in daily["seen"]:
            continue
        buf = io.BytesIO()
        req = yr.media().download_media(resourceName="")
        req.uri = rep["downloadUrl"]
        dl = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _, done = dl.next_chunk()
        for row in csv.DictReader(io.StringIO(buf.getvalue().decode())):
            key = f"{row['video_id']}|{row['date']}"
            imp = int(float(row.get("video_thumbnail_impressions") or 0))
            daily["rows"][key] = daily["rows"].get(key, 0) + imp
        daily["seen"].append(rep["id"])
    json.dump(daily, open(daily_path, "w"))
    films, n = load(data), 0
    for f in films:
        start = dt.date.fromisoformat(f["published"])
        days = [(start + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range(7)]
        vals = [daily["rows"].get(f"{f['id']}|{d}") for d in days]
        if all(v is not None for v in vals):
            f["impressions_7d"] = sum(vals)
            n += 1
    save(data, films)
    return n


def load(data: str) -> list[dict]:
    path = os.path.join(data, "history.json")
    return json.load(open(path)) if os.path.exists(path) else []


def save(data: str, films: list[dict]) -> None:
    os.makedirs(data, exist_ok=True)
    json.dump(films, open(os.path.join(data, "history.json"), "w"), indent=1, ensure_ascii=False)


def schedule_item(slug: str, root: str = ROOT) -> dict:
    for name in ("schedule.json", "history_schedule.json"):
        path = os.path.join(root, "topics", name)
        if os.path.exists(path):
            for item in json.load(open(path)).get("items") or []:
                if item.get("slug") == slug:
                    return item
    sys.exit(f"{slug!r} is not in topics/schedule.json")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", choices=("history", "reach", "check"))
    ap.add_argument("--slug", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--search", default="")
    ap.add_argument("--data", default=DATA)
    ap.add_argument("--root", default=ROOT, help="repo whose topics/ holds the schedule")
    args = ap.parse_args(argv)
    if args.command == "history":
        films = pull_history(args.data)
        long_ = [f for f in films if f["format"] == "long"]
        print(f"{len(films)} public uploads, {len(long_)} long-form, "
              f"{sum(1 for f in long_ if f.get('recommended_views_7d') is not None)} with a first week")
        return 0
    if args.command == "reach":
        print(f"{merge_reach(args.data)} films now have first-week impressions")
        return 0
    item = schedule_item(args.slug, args.root) if args.slug else {}
    title = args.title or item.get("question", "")
    market = item.get("market")
    if args.search and not market:
        market = None
    text = " ".join([title, args.search or (market or {}).get("search", ""),
                     (args.slug or "").replace("-", " ")])
    films = load(args.data)
    if not films:
        sys.exit("no history yet: run `impression_risk.py history` first")
    r = assess(text, films, market, [f for f in films if f.get("format") == "short"])
    print(text_report(args.slug or title, r))
    os.makedirs(args.data, exist_ok=True)
    with open(os.path.join(args.data, "predictions.jsonl"), "a") as fh:
        fh.write(json.dumps({"date": dt.date.today().isoformat(), "slug": args.slug, "title": title,
                             "band": r["band"], "score": r.get("score"), "metric": r["metric"],
                             "films_labelled": r["films_labelled"]}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
