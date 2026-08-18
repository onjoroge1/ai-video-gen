"""Import a YouTube Studio CSV export into `video_metrics`.

Why this exists: the performance -> topics feedback loop had no input. `video_metrics` has the right
schema and four hand-typed rows, read by nothing but a display table, while the topic generators
receive not a single number from this channel. Hand-entry was never going to keep up, so the export
you already download becomes the input.

What it does NOT do: invent a join key. `video_metrics.question` is empty on every existing row and
`finished_videos/index.json` records no question or template, so an imported row can be matched to a
video by title but not yet to the TOPIC that produced it. `backfill_questions()` closes that where a
job dir survives; everything else is reported as unmatched rather than silently guessed.
"""
from __future__ import annotations
import csv
import glob
import json
import os
import re

STUDIO_COLUMNS = {                       # YouTube Studio header -> video_metrics column
    "Video title": "title",
    "Views": "views",
    "Stayed to watch (%)": "stayed_pct",
    "Average percentage viewed (%)": "pct_viewed",
    "Average view duration": "avg_view_dur_sec",
    "Duration": "video_len_sec",
    "Video publish time": "published_at",
    "Impressions": "impressions",
    "Impressions click-through rate (%)": "ctr",
    "Subscribers": "subs_gained",
    "Watch time (hours)": "watch_hours",
    "Engaged views": "engaged_views",
}


def norm_title(t: str) -> str:
    """Match key. Studio titles carry hashtags and emoji that our slugs never had."""
    t = re.sub(r"#\w+", " ", (t or "").lower())
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return " ".join(t.split())


def _num(v):
    if v is None:
        return None
    s = str(v).strip().replace("%", "").replace(",", "")
    if not s:
        return None
    if ":" in s:                                     # "1:23" duration -> seconds
        parts = [int(x) for x in s.split(":") if x.isdigit()]
        return sum(p * 60 ** i for i, p in enumerate(reversed(parts))) if parts else None
    try:
        return float(s) if "." in s else int(s)
    except ValueError:
        return None


def parse(csv_path: str) -> list:
    """Rows from a Studio export, mapped onto video_metrics columns. Unknown headers are ignored
    rather than fatal, because Studio's column set varies with what you tick on export."""
    out = []
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        for raw in csv.DictReader(fh):
            title = (raw.get("Video title") or "").strip()
            # the export's first row is a channel-total with an empty title
            if not title or (raw.get("Content") or "").strip().lower() == "total":
                continue
            row = {}
            for src, dst in STUDIO_COLUMNS.items():
                if src in raw:
                    val = _num(raw[src]) if dst != "title" and dst != "published_at" else raw[src]
                    if val not in (None, ""):
                        row[dst] = val
            if row.get("title"):
                row["slug"] = row["title"]
                row["_key"] = norm_title(row["title"])
                out.append(row)
    return out


# Job dirs are swept at 14 days, so for any video older than a fortnight there is no `_state.json`
# left to recover the topic from -- on the 28-day export that is 27 rows out of 27. Inferring the
# format from the title is how the manual analysis grouped these in the first place, and it is
# available for the whole back catalogue. Marked `inferred` so it is never mistaken for a real join.
_CLASSIFIERS = (
    ("quiz",       r"\b(can you (name|guess)|guess (all|the)|name all|from (their|the) (shadow|close))"),
    ("simulation", r"\b(what if|what would happen|drop (a|your)|every planet|on every)"),
    ("explainer",  r"\b(why|how|what is|explained)\b"),
)


def classify(title: str) -> str:
    t = (title or "").lower()
    for name, pat in _CLASSIFIERS:
        if re.search(pat, t):
            return name
    return "explainer"


def backfill(rows: list, jobs_dir: str = "renders/_ui_jobs") -> dict:
    """Attach `question`, `template` and `format` from surviving job dirs, matching on title.

    This is the missing join key. Without it an outcome cannot be traced back to the topic that
    produced it, which is the whole point of importing the numbers.
    """
    index = {}
    for st in glob.glob(os.path.join(jobs_dir, "*", "_state.json")):
        try:
            d = json.load(open(st))
        except Exception:
            continue
        sc = d.get("script") or {}
        t = sc.get("title") or ""
        if t:
            index[norm_title(t)] = {
                "question": sc.get("question") or d.get("question") or "",
                "template": d.get("style_mode") or sc.get("template") or "",
                "format": d.get("video_format") or "",
            }
    hit = 0
    for r in rows:
        m = index.get(r["_key"])
        if m:
            hit += 1
            for k, v in m.items():
                if v:
                    r.setdefault(k, v)
            r["template_source"] = "job"
        else:
            r["template"] = classify(r.get("title", ""))
            r["template_source"] = "inferred"
    return {"job_dirs_indexed": len(index), "rows_enriched": hit}


def summarise(rows: list) -> dict:
    """View-weighted stayed-to-watch per template. This is what the topic prompts consume: an
    average over videos would let a 41-view fluke outrank a 1,500-view result."""
    agg = {}
    for r in rows:
        t = r.get("template") or "explainer"
        v, s = r.get("views") or 0, r.get("stayed_pct")
        if s is None:
            continue
        a = agg.setdefault(t, {"views": 0, "num": 0.0, "n": 0})
        a["views"] += v
        a["num"] += float(s) * v
        a["n"] += 1
    for a in agg.values():
        a["stayed"] = round(a["num"] / a["views"], 1) if a["views"] else 0.0
    ranked = sorted(rows, key=lambda r: -(float(r.get("stayed_pct") or 0)))
    strong = [r for r in ranked if (r.get("views") or 0) >= 200]
    return {"by_template": agg,
            "best": [(r["title"], r.get("stayed_pct")) for r in strong[:4]],
            "worst": [(r["title"], r.get("stayed_pct")) for r in strong[-3:]]}


def run(csv_path: str, jobs_dir: str = "renders/_ui_jobs", write: bool = True) -> dict:
    rows = parse(csv_path)
    bf = backfill(rows, jobs_dir)
    saved, failed, db_on = 0, [], False
    if write:
        try:
            # .env holds DATABASE_URL. app.py loads it at import; a bare CLI run does not, and
            # without this the importer reports "db disabled" and silently persists nothing.
            try:
                from dotenv import load_dotenv
                load_dotenv()
            except Exception:
                pass
            import db
            db_on = bool(db.db_enabled())
            if not db_on:
                failed.append(("<db disabled>", "no DATABASE_URL - rows parsed but not persisted"))
            else:
                for r in rows:
                    payload = {k: v for k, v in r.items() if not k.startswith("_")}
                    # metrics_upsert is best-effort and returns False rather than raising, so a
                    # bare try/except counted every failure as a save. Check the return value.
                    if db.metrics_upsert(payload):
                        saved += 1
                    else:
                        failed.append((r.get("title", "?"), "metrics_upsert returned False"))
        except Exception as e:
            failed.append(("<db unavailable>", str(e)[:80]))
    return {"parsed": len(rows), "saved": saved, "failed": failed,
            "unmatched_to_job": len(rows) - bf["rows_enriched"], **bf,
            "db_enabled": db_on, "summary": summarise(rows), "rows": rows}


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "Table data.csv"
    rep = run(path, write="--dry" not in sys.argv)
    print(f"parsed {rep['parsed']} rows from {path}")
    print(f"  job dirs indexed : {rep['job_dirs_indexed']}")
    print(f"  enriched w/ topic: {rep['rows_enriched']}  (unmatched {rep['unmatched_to_job']})")
    print(f"  saved to db      : {rep['saved']}")
    for t, e in rep["failed"][:5]:
        print(f"    FAILED {t[:44]}: {e}")
    print()
    for r in sorted(rep["rows"], key=lambda x: -(x.get("views") or 0))[:12]:
        print(f"  {(r.get('title') or '')[:46]:46s} {r.get('views','?'):>6} "
              f"{r.get('stayed_pct','?'):>6}%")
