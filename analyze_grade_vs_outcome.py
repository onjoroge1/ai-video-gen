"""GRADE vs OUTCOME — does the self-grader predict anything real?

We have held two things separately and never put them together. Every short gets a `SHORT SELF-GRADE`
written at render time (first second hook, pacing, loop ending, ...), and every published short now
has a measured stayed-to-watch from the Studio export. If `first second hook` tracks stayed-to-watch,
the grader is a pre-publish forecast and deserves to gate spend BEFORE motion is bought. If it does
not, the grader is theatre and must stop gating anything.

Why this has never been run: there was no join. A grade lives in a render dir; a metric is keyed by
title. The key turned out to exist all along — `finished_videos/<job_id>.grade` sits next to
`finished_videos/index.json`, which maps that same job id to the title the video shipped under. That
is 63 grades with a hard join, against the 9 loose `grade.txt` render dirs that motivated this script
and that turn out to be entirely unpublished experiments — not one of them reaches the numbers.

Design rules, same as video_audit.py:
  * Report n beside every coefficient, and say out loud when n is too small to mean anything. A rho
    on 5 points is not evidence and this script must say so itself rather than let a reader infer it.
  * Never silently drop a row. Matched, review-band and unmatched are all counted and printed.
  * Never invent a match. A fuzzy title pair that could plausibly be two different videos goes to a
    human, not into the numbers (see FUZZY_AUTO below for the case that forced this).

Read-only: no writes, no API calls, no spend. Run with:
    /opt/homebrew/bin/python3 analyze_grade_vs_outcome.py
"""
from __future__ import annotations
import difflib
import glob
import itertools
import json
import math
import os
import random
import re
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)

from metrics_import import norm_title           # the match key the importer already agreed on

# --------------------------------------------------------------------------------------------------
# THRESHOLDS (each one has a reason, not a taste)
#
# A published short with 3 views has a stayed-to-watch of 0%, 33%, 66% or 100% and nothing else — one
# viewer swiping is a 33-point move. Correlating a grade against that is correlating against a coin.
# So the analysis is repeated at rising view floors and the reader gets to watch n collapse.
VIEW_FLOORS = (0, 10, 30, 200)
NOISE_FLOOR_VIEWS = 30          # below this, stayed_pct is quantisation noise, not a measurement
MIN_N_FOR_A_NUMBER = 4          # fewer than this and we refuse to print a coefficient at all
MIN_N_FOR_EVIDENCE = 12         # fewer than this and a coefficient is a hint, never a decision

# Fuzzy title matching. Ratio alone CANNOT separate a retitle from a different video: "What If You
# Grew 1cm Every Second?" scores 0.88 against the published "What If You Shrank 1cm Every Second?"
# and they are opposite videos, while the genuine retitle "What If Earth Lost Just 1% Oxygen?" scores
# only 0.82 against "What If Earth's Atmosphere Lost 1% of Its Oxygen?". Auto-accepting anything that
# separates those two would be guessing. So: accept high-ratio pairs, show the middle band to a human
# and count it nowhere, and block any pair whose difference is a polarity word at any ratio.
FUZZY_AUTO = 0.90
FUZZY_REVIEW = 0.72
POLARITY = {"grew", "grow", "shrank", "shrink", "gained", "lost", "faster", "slower", "more", "less",
            "never", "always", "hotter", "colder", "bigger", "smaller", "warmer", "cooler",
            "stopped", "started", "without", "with", "before", "after"}

GRADE_LINE = re.compile(r"^\s{2,}([A-Za-z][A-Za-z \-']*?)\s{2,}(\d+)\s*/\s*10\s*$", re.M)
OVERALL_LINE = re.compile(r"overall\s+(\d+)\s*/\s*100", re.I)


# --------------------------------------------------------------------------------------------------
# PARSING

def parse_grade(path: str) -> dict:
    """grade.txt / .grade -> {overall, criteria: {name: score}, biggest_fix}.

    The criterion list VARIES between files — over the 72 files present, `story_coherence` appears in
    54, `escalation` in 58 and `conceit_consistency` in 71, the other seven in all 72 — so this reads
    whatever rows are present instead of expecting a fixed schema. Best-effort: an unreadable file returns empty rather than
    killing the run, because one malformed grade must not cost us the other sixty-nine."""
    out = {"overall": None, "criteria": {}, "biggest_fix": "", "path": path}
    try:
        txt = open(path, encoding="utf-8", errors="replace").read()
    except Exception:
        return out
    m = OVERALL_LINE.search(txt)
    if m:
        out["overall"] = int(m.group(1))
    for name, score in GRADE_LINE.findall(txt):
        out["criteria"][name.strip().lower().replace(" ", "_").replace("-", "_")] = int(score)
    fix = re.search(r"Biggest fix:\s*(.+)", txt, re.S)
    if fix:
        out["biggest_fix"] = " ".join(fix.group(1).split())
    return out


def _render_dir_title(d: str) -> str:
    """Title for a loose render dir. `_state.json` carries `script.title` for everything the UI
    produced; the older dirs (short_finger_wrinkle) have no state left and only the rendered mp4
    filename, which IS the title for those — that is how the pipeline named the export."""
    try:
        st = json.load(open(os.path.join(d, "_state.json"), encoding="utf-8"))
        t = ((st.get("script") or {}).get("title") or "").strip()
        if t:
            return t
    except Exception:
        pass
    for mp4 in sorted(glob.glob(os.path.join(d, "*.mp4"))):
        base = os.path.basename(mp4)[:-4]
        if not base.startswith(("_", "explainer", "review")):
            return base.replace("-", " ")
    return ""


def collect_grades() -> list:
    """Every grade on disk, each carrying the best title we can attach to it.

    Two populations, and they are not equal. `finished_videos/*.grade` is keyed by job id and
    `index.json` resolves that job id to a shipped title — a hard join, no guessing. The `grade.txt`
    render dirs have no id and have to go through their own title, which is why they are labelled
    separately in the report."""
    grades = []
    try:
        index = json.load(open(os.path.join(_ROOT, "finished_videos", "index.json"), encoding="utf-8"))
    except Exception:
        index = {}
    for p in sorted(glob.glob(os.path.join(_ROOT, "finished_videos", "*.grade"))):
        job_id = os.path.basename(p)[:-len(".grade")]
        g = parse_grade(p)
        g["job_id"] = job_id
        g["title"] = ((index.get(job_id) or {}).get("title") or "").strip()
        g["source"] = "finished_videos"
        grades.append(g)
    seen = {os.path.dirname(g["path"]) for g in grades}
    for p in sorted(glob.glob(os.path.join(_ROOT, "**", "grade.txt"), recursive=True)):
        d = os.path.dirname(p)
        if d in seen:
            continue
        g = parse_grade(p)
        g["job_id"] = ""
        g["title"] = _render_dir_title(d)
        g["source"] = "render_dir"
        grades.append(g)
    return grades


# --------------------------------------------------------------------------------------------------
# METRICS

def load_metrics() -> tuple:
    """(rows, source_label). db.metrics_all() first, `finished_videos/video_metrics.json` as fallback.

    The explicit .env path matters: db.metrics_all() swallows its own failures and returns [], so a
    missing DATABASE_URL looks exactly like "no videos have metrics" — a silent 31-row-to-0-row
    downgrade that would make this whole analysis print a confident nothing. The label is printed so
    a degraded read is visible instead of inferred."""
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(_ROOT, ".env"))
    except Exception:
        pass
    try:
        import db
        rows = db.metrics_all()
        if rows:
            return rows, "db.metrics_all()"
    except Exception:
        pass
    try:
        rows = json.load(open(os.path.join(_ROOT, "finished_videos", "video_metrics.json"),
                              encoding="utf-8"))
        return (rows or []), "finished_videos/video_metrics.json (FALLBACK — db unavailable)"
    except Exception:
        return [], "NONE (no db, no json)"


def index_metrics(rows: list) -> tuple:
    """norm_title -> row, keeping the highest-view row on collision.

    Collisions are real: 'Can You Name All 3 Planets...' and 'What If Light Traveled 1% Slower' each
    have two rows. Keeping the larger avoids counting one video as two data points.

    It does NOT catch every duplicate, and the one it misses matters: the oxygen video is in the
    table twice under titles that normalise differently ('what if earth lost 1 of its oxygen' at 1124
    views vs 'what if earth s atmosphere lost 1 of its oxygen' at 1120), 4 views apart, almost
    certainly one upload. No joined data point is affected, but do not read `collapsed` as a
    guarantee that the metric table holds one row per video."""
    by_key, collapsed = {}, 0
    for r in rows:
        k = norm_title(r.get("title") or r.get("slug") or "")
        if not k:
            continue
        if k in by_key:
            collapsed += 1
            if (r.get("views") or 0) <= (by_key[k].get("views") or 0):
                continue
        by_key[k] = r
    return by_key, collapsed


def _sorted_key(t: str) -> str:
    """Title tokens sorted, so a rewritten title matches its own earlier draft. "The Marching Band
    That Broke a Bridge" and "The Bridge That Fell to a Marching Band" are the same video and score
    only 0.46 in order, but 0.87 sorted."""
    return " ".join(sorted(norm_title(t).split()))


def possible_siblings(unmatched: list, matched: dict) -> list:
    """Unmatched grades that look like a RETITLED DRAFT of a video we already joined.

    This is not a join, it is a confession: when one of these exists, the grade we scored that video
    with was picked by which title happened to survive, and a different pick would have changed the
    number. Reported so nobody reads the sample as cleaner than it is."""
    out = []
    known = {norm_title(g.get("title") or "") for gs in matched.values() for g in gs}
    known = {t for t in known if t}
    for g, _c, _r, _w in unmatched:
        t = g.get("title") or ""
        if not t:
            continue
        best, score = "", 0.0
        for kt in known:
            r = difflib.SequenceMatcher(None, _sorted_key(kt), _sorted_key(t)).ratio()
            if r > score:
                best, score = kt, r
        if score >= 0.80:
            out.append((score, t, best))
    return sorted(out, reverse=True)


def _polarity_blocked(a: str, b: str) -> bool:
    """True when the two titles differ by a word that flips meaning (grew/shrank). Only tokens unique
    to one side count — 'lost' appearing in both titles is not a difference."""
    ta, tb = set(a.split()), set(b.split())
    return bool((ta ^ tb) & POLARITY)


def join(grades: list, by_key: dict) -> tuple:
    """(matched, review, unmatched). matched maps metric-key -> [grade, ...]."""
    matched, review, unmatched = {}, [], []
    keys = list(by_key)
    for g in grades:
        k = norm_title(g.get("title") or "")
        if not k:
            unmatched.append((g, "", 0.0, "no title recoverable"))
            continue
        if k in by_key:
            matched.setdefault(k, []).append(g)
            continue
        cand = difflib.get_close_matches(k, keys, n=1, cutoff=FUZZY_REVIEW)
        if not cand:
            # Deliberately NOT called "never published". A short was graded under one working title
            # and shipped under another more than once (three renders of the marching-band story
            # carry two different titles), so a missing metric row means "no title matched", which
            # is not the same claim as "this video never went out".
            unmatched.append((g, "", 0.0, "no metric row matched"))
            continue
        # Argument order matters: get_close_matches scores ratio(seq1=candidate, seq2=key), and
        # SequenceMatcher is not quite symmetric. Scoring the other way round reported 0.70 for a
        # pair that had just cleared a 0.72 cutoff, which looked like a bug in the threshold.
        ratio = difflib.SequenceMatcher(None, cand[0], k).ratio()
        if _polarity_blocked(k, cand[0]):
            review.append((g, cand[0], ratio, "polarity word differs — could be a different video"))
        elif ratio >= FUZZY_AUTO:
            g["fuzzy"] = ratio
            matched.setdefault(cand[0], []).append(g)
        else:
            review.append((g, cand[0], ratio, "below auto-accept ratio"))
    return matched, review, unmatched


# --------------------------------------------------------------------------------------------------
# STATISTICS
#
# stdlib only, deliberately. numpy and scipy both happen to be installed on this machine (video_audit
# imports numpy for frame decoding), and scipy.stats.spearmanr would be one line — but this script is
# meant to run anywhere the repo does, and a tie-corrected rank coefficient is four lines. The
# implementations below were checked against scipy.stats.spearmanr on ten cases including ties and
# agree to 5 decimal places; the permutation p was checked against the exact 2/120 for a perfect
# monotonic n=5.

def _ranks(vals: list) -> list:
    """Fractional (tie-averaged) ranks. Ties MUST share a rank: the criteria are integers 1-10, so on
    a dozen points `pacing` is 8/10 six times over. Ordinal ranking would invent an ordering that is
    not in the data and inflate every coefficient."""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    out = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            out[order[k]] = avg
        i = j + 1
    return out


def spearman(xs: list, ys: list):
    """Spearman rho with tie correction = Pearson on fractional ranks. None when it is undefined —
    a criterion every video scored 8/10 has zero variance and no correlation exists, which is a
    finding about the grader (it does not discriminate) rather than an error."""
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx)
    dy = sum((b - my) ** 2 for b in ry)
    if dx <= 0 or dy <= 0:
        return None
    return num / math.sqrt(dx * dy)


def perm_p(xs: list, ys: list, rho, seed: int = 1234) -> tuple:
    """(two-sided p, method). Permutation, not the scipy t-approximation: at n=5 the asymptotic
    p-value is a fiction, whereas shuffling the outcomes is exact whenever n! is small enough to
    enumerate. Falls back to seeded Monte Carlo above 8 points so the run stays reproducible."""
    if rho is None:
        return None, ""
    n, obs = len(xs), abs(rho)
    if math.factorial(n) <= 200000:
        tot = hit = 0
        for perm in itertools.permutations(ys):
            r = spearman(xs, list(perm))
            tot += 1
            if r is not None and abs(r) >= obs - 1e-12:
                hit += 1
        return (hit / tot if tot else None), f"exact, {tot} permutations"
    rnd = random.Random(seed)
    shuffled, tot, hit = list(ys), 20000, 0
    for _ in range(tot):
        rnd.shuffle(shuffled)
        r = spearman(xs, shuffled)
        if r is not None and abs(r) >= obs - 1e-12:
            hit += 1
    return (hit + 1) / (tot + 1), f"monte-carlo, {tot} shuffles"


def loo_range(xs: list, ys: list) -> tuple:
    """(min rho, max rho) over every leave-one-out subset. On a dozen points this is the number that
    matters: if dropping one video swings rho across zero, the coefficient describes that video and
    not the grader."""
    if len(xs) < MIN_N_FOR_A_NUMBER + 1:
        return None, None
    vals = []
    for i in range(len(xs)):
        r = spearman(xs[:i] + xs[i + 1:], ys[:i] + ys[i + 1:])
        if r is not None:
            vals.append(r)
    return (min(vals), max(vals)) if vals else (None, None)


# --------------------------------------------------------------------------------------------------
# ANALYSIS

def build_points(matched: dict, by_key: dict) -> list:
    """One point per PUBLISHED VIDEO, not per grade file. Several job ids can resolve to one shipped
    title (three separate renders of the gravity short all graded, one upload), and re-grades of the
    same render are duplicated on disk. Averaging the grades is the only honest option — we cannot
    tell which render was uploaded — so the spread is carried along and printed."""
    pts = []
    for key, gs in matched.items():
        row = by_key[key]
        stayed = row.get("stayed_pct")
        if stayed is None:
            continue
        names = set()
        for g in gs:
            names.update(g["criteria"])
        crit = {}
        for nm in names:
            vals = [g["criteria"][nm] for g in gs if nm in g["criteria"]]
            crit[nm] = sum(vals) / len(vals)
        overalls = [g["overall"] for g in gs if g["overall"] is not None]
        pts.append({
            "key": key,
            "title": row.get("title") or row.get("slug") or key,
            "views": row.get("views") or 0,
            "stayed": float(stayed),
            "pct_viewed": row.get("pct_viewed"),
            "criteria": crit,
            "overall": (sum(overalls) / len(overalls)) if overalls else None,
            "overall_spread": (max(overalls) - min(overalls)) if len(overalls) > 1 else 0,
            "n_grades": len(gs),
        })
    return sorted(pts, key=lambda p: -p["views"])


def correlate(pts: list, field: str, outcome: str = "stayed") -> dict:
    """rho / p / n / leave-one-out range for one criterion against one outcome."""
    xs, ys = [], []
    for p in pts:
        v = p["overall"] if field == "overall" else p["criteria"].get(field)
        o = p.get(outcome)
        if v is None or o is None:
            continue
        xs.append(float(v))
        ys.append(float(o))
    n = len(xs)
    if n < MIN_N_FOR_A_NUMBER:
        return {"field": field, "n": n, "rho": None, "p": None, "method": "", "lo": None, "hi": None}
    rho = spearman(xs, ys)
    p, method = perm_p(xs, ys, rho)
    lo, hi = loo_range(xs, ys)
    return {"field": field, "n": n, "rho": rho, "p": p, "method": method, "lo": lo, "hi": hi}


# --------------------------------------------------------------------------------------------------
# REPORT

def _rule(ch: str = "=") -> str:
    return ch * 98


def _fmt(x, spec: str = "6.2f") -> str:
    """None-safe format. The width is optional in the spec ('.2f'), so parse it defensively rather
    than int('') — this crashed the verdict line the first time a p-value came back undefined."""
    if x is not None:
        return format(x, spec)
    width = spec.split(".")[0].lstrip("+-")
    return "n/a".rjust(int(width)) if width.isdigit() else "n/a"


def n_for_power(rho_target: float = 0.5, alpha: float = 0.05, power: float = 0.80) -> int:
    """How many published graded videos it would take to detect a correlation of `rho_target`.

    Fisher z, the standard sample-size formula — printed instead of asserted so the "we need about
    thirty" line in the verdict is arithmetic a reader can check, not a number someone felt. Uses
    statistics.NormalDist, which is stdlib."""
    try:
        from statistics import NormalDist
        z_a = NormalDist().inv_cdf(1 - alpha / 2)
        z_b = NormalDist().inv_cdf(power)
        return int(math.ceil(3 + ((z_a + z_b) / math.atanh(rho_target)) ** 2))
    except Exception:
        return 0


def main() -> int:
    print(_rule())
    print("GRADE vs OUTCOME — does the self-grader predict stayed-to-watch?")
    print(_rule())

    grades = collect_grades()
    rows, src = load_metrics()
    by_key, collapsed = index_metrics(rows)
    matched, review, unmatched = join(grades, by_key)
    pts = build_points(matched, by_key)

    n_fin = sum(1 for g in grades if g["source"] == "finished_videos")
    n_ren = len(grades) - n_fin
    print("\nSOURCES")
    print(f"  grade files parsed        : {len(grades)}  ({n_fin} finished_videos/*.grade, "
          f"{n_ren} render-dir grade.txt)")
    print(f"  grades with no scores     : {sum(1 for g in grades if not g['criteria'])}")
    print(f"  metrics source            : {src}")
    print(f"  metric rows               : {len(rows)}  "
          f"({len(by_key)} distinct titles, {collapsed} duplicate rows collapsed)")
    have_stayed = sum(1 for r in rows if r.get("stayed_pct") is not None)
    have_pv = sum(1 for r in rows if r.get("pct_viewed") is not None)
    print(f"  rows with stayed_pct      : {have_stayed}")
    print(f"  rows with pct_viewed      : {have_pv}"
          + ("   <- the Studio export we import has no such column, so this outcome does not exist"
             if not have_pv else ""))

    print("\nJOIN  (nothing is silently dropped — every grade file lands in exactly one bucket)")
    print(f"  matched to a metric row   : {sum(len(v) for v in matched.values())} grade files "
          f"-> {len(matched)} distinct published videos")
    print(f"  needs human review        : {len(review)}   (counted NOWHERE)")
    print(f"  no metric row matched     : {len(unmatched)}")

    if review:
        # Collapse re-grades of the same title: three identical rows would read as three separate
        # judgement calls when it is one call a human has to make once.
        uniq = {}
        for g, cand, ratio, why in review:
            uniq.setdefault((g["title"], cand), [ratio, why, 0])[2] += 1
        print("\n  REVIEW BAND — plausible title pairs this script refuses to decide:")
        for (title, cand), (ratio, why, cnt) in sorted(uniq.items(), key=lambda kv: -kv[1][0]):
            mv = (by_key.get(cand) or {}).get("views")
            dup = f" x{cnt}" if cnt > 1 else ""
            print(f"    {ratio:4.2f}  {title[:40]:40s} -> {cand[:40]:40s} "
                  f"[{mv if mv is not None else '?'} views] {why}{dup}")
        # The ceiling is DISTINCT NEW VIDEOS, not review pairs. Counting pairs overstated it: two
        # of these pairs point at the same oxygen metric row and one points at a row that is already
        # in `pts`, so "14 -> 18" was really 14 -> 16. A follow-up sized by the wrong number is a
        # follow-up someone does expecting twice the statistical power it can deliver.
        new_keys = {cand for (_t, cand) in uniq if cand not in matched}
        print(f"    These {len(uniq)} pairs point at {len(new_keys)} metric row(s) not already "
              f"joined ({len(uniq) - len(new_keys)} are re-grades or already in the sample).")
        print(f"    Confirming ALL of them by hand would take the sample from {len(pts)} "
              f"to at most {len(pts) + len(new_keys)} videos.")

    npub = [g for g in unmatched if g[3].startswith("no metric row")]
    if npub:
        print(f"\n  NO METRIC ROW ({len(npub)}) — graded but no title matched. Mostly unpublished "
              "experiments; this is why the join is lossy:")
        for g, _, _, _ in npub[:8]:
            print(f"    {g['source']:16s} {(g['title'] or '?')[:60]}")
        if len(npub) > 8:
            print(f"    ... and {len(npub) - 8} more")

    sibs = possible_siblings(unmatched, matched)
    if sibs:
        print(f"\n  RETITLE HAZARD ({len(sibs)}) — unmatched grades that look like earlier drafts of "
              "a video we DID join:")
        for score, t, kt in sibs:
            print(f"    {score:4.2f}  {t[:44]:44s} ~ {kt[:44]}")
        print("    Where this happens the joined video's grade is whichever title survived. Treat "
              "those rows as approximate.")

    if len(pts) < MIN_N_FOR_A_NUMBER:
        print(f"\nSTOP. {len(pts)} joined videos is below the {MIN_N_FOR_A_NUMBER}-point minimum. "
              "No coefficient will be printed, because none would mean anything.")
        print("\nVERDICT: the grader is UNVALIDATED — not disproven, just never tested. It must not "
              "gate spend on the strength of numbers that do not exist.")
        return 0

    print(f"\nJOINED DATA  (n={len(pts)} published videos, one row per video)")
    print(f"  {'views':>6} {'stayed%':>8} {'overall':>8} {'hook':>5} {'grades':>7}  title")
    for p in pts:
        hk = p["criteria"].get("first_second_hook")
        spread = f" (+/-{p['overall_spread']})" if p["overall_spread"] else ""
        print(f"  {p['views']:>6} {p['stayed']:>8.2f} {_fmt(p['overall'], '8.1f')}{spread:>7} "
              f"{_fmt(hk, '5.1f')} {p['n_grades']:>7}  {p['title'][:44]}")

    thin = [p for p in pts if p["views"] < NOISE_FLOOR_VIEWS]
    if thin:
        worst = min(p["views"] for p in thin)
        step = 100.0 / worst if worst else 0.0
        print(f"\n  WARNING: {len(thin)} of {len(pts)} of these videos have under "
              f"{NOISE_FLOOR_VIEWS} views. The thinnest has {worst} view(s), where one viewer "
              f"swiping moves stayed_pct by {step:.0f}")
        print("  points — those rows carry a grade but not a measurement, and they are half the "
              "sample.")

    fields = ["overall"] + sorted({k for p in pts for k in p["criteria"]})
    print(f"\nSPEARMAN vs stayed-to-watch   (all {len(pts)} joined videos, no view floor)")
    print(f"  {'criterion':24s} {'n':>3} {'rho':>6} {'p':>7} {'leave-one-out range':>22}   note")
    results = {}
    for f in fields:
        r = correlate(pts, f)
        results[f] = r
        if r["rho"] is None:
            note = f"only {r['n']} points" if r["n"] < MIN_N_FOR_A_NUMBER else "no variance in grades"
            print(f"  {f:24s} {r['n']:>3} {'n/a':>6} {'n/a':>7} {'n/a':>22}   {note}")
            continue
        loo = f"{r['lo']:+.2f} .. {r['hi']:+.2f}" if r["lo"] is not None else "n/a"
        flips = r["lo"] is not None and r["lo"] * r["hi"] < 0
        note = "SIGN FLIPS on dropping 1 video" if flips else ""
        if r["p"] is not None and r["p"] < 0.05 and not flips:
            note = "survives permutation test"
        print(f"  {f:24s} {r['n']:>3} {r['rho']:>+6.2f} {_fmt(r['p'], '7.3f')} {loo:>22}   {note}")
    meth = next((r["method"] for r in results.values() if r["method"]), "")
    if meth:
        print(f"  p-values: {meth}, two-sided — shuffled outcomes, not an asymptotic approximation, "
              "which at this n would be a fiction.")

    print("\nSTABILITY ACROSS VIEW FLOORS  (does any of this survive dropping the low-view noise?)")
    print(f"  {'min views':>10} {'n':>3} {'rho(overall)':>13} {'rho(first_second_hook)':>23}")
    for floor in VIEW_FLOORS:
        sub = [p for p in pts if p["views"] >= floor]
        ro = correlate(sub, "overall")
        rh = correlate(sub, "first_second_hook")
        print(f"  {floor:>10} {len(sub):>3} {_fmt(ro['rho'], '13.2f')} {_fmt(rh['rho'], '23.2f')}")

    # ---- verdict. Computed from what was actually found, never asserted.
    hook, overall = results.get("first_second_hook", {}), results.get("overall", {})
    n = len(pts)
    usable = [p for p in pts if p["views"] >= NOISE_FLOOR_VIEWS]
    survivors = [f for f, r in results.items()
                 if r["rho"] is not None and r["p"] is not None and r["p"] < 0.05
                 and r["lo"] is not None and r["lo"] * r["hi"] > 0]

    print("\n" + _rule("-"))
    print("HOW MUCH OF THIS IS EVIDENCE")
    print(_rule("-"))
    print(f"  Videos joined                     : {n}")
    print(f"  ... with enough views to be real  : {len(usable)}  (>= {NOISE_FLOOR_VIEWS} views)")
    print(f"  Criteria surviving p<0.05 AND leave-one-out sign stability : {len(survivors)}"
          + (f"  {survivors}" if survivors else ""))
    # The gate is the USABLE count, not the joined count. Fourteen points of which eight are
    # 1-to-27-view videos is not a fourteen-point study; padding n with rows whose outcome is a coin
    # flip makes the sample look twice as strong as it is.
    n_eff = len(usable)
    if n_eff < MIN_N_FOR_EVIDENCE:
        print(f"\n  EFFECTIVE n = {n_eff}, not {n}. That is below the {MIN_N_FOR_EVIDENCE} points "
              "this script will call evidence, so every")
        print("  coefficient in the table above is a hint. Read them as directions to test, not as "
              "facts: a rho on a handful of")
        print("  videos is one lucky short away from reversing, which is exactly what the "
              "leave-one-out column is showing you.")

    print("\nVERDICT")
    if not survivors:
        print("  The self-grader is NOT SHOWN to predict stayed-to-watch. Not one criterion — "
              "including first_second_hook,")
        print(f"  the one the grader exists to measure — clears p<0.05 with a sign that survives "
              f"dropping a single video.")
        print("  This is an ABSENCE OF EVIDENCE, not proof the grader is worthless: at "
              f"n={n} (and only {len(usable)} videos")
        print("  with enough views for stayed_pct to mean anything) this test could not detect a "
              "real effect unless it were enormous.")
        print("  ACTION: the grader must NOT gate spend. It has never been validated and this data "
              "cannot validate it.")
        print("  Keep writing grades — they are the input to the test — but let them advise a human, "
              "not block a render.")
        need = n_for_power()
        print("  To actually answer the question, the cheapest path is more PUBLISHED graded videos, "
              "not more analysis:")
        print(f"  detecting a moderate rho (0.5) at p<0.05 with 80% power needs n={need} published "
              f"shorts with grades. We have {n_eff}.")
        # Name the best candidate anyway. "Nothing was significant" is the honest headline, but the
        # largest stable coefficient is the hypothesis worth spending the next twenty videos on.
        best = max((r for r in results.values()
                    if r["rho"] is not None and r["lo"] is not None and r["lo"] * r["hi"] > 0),
                   key=lambda r: abs(r["rho"]), default=None)
        if best:
            print(f"  If you test one thing next, test '{best['field']}': rho={best['rho']:+.2f} "
                  f"(p={_fmt(best['p'], '.3f').strip()}, n={best['n']}) is the largest coefficient "
                  "whose sign")
            print("  survives leave-one-out. That is a hypothesis, not a result.")
    else:
        print(f"  {len(survivors)} criterion/criteria correlate with stayed-to-watch and survive "
              "leave-one-out: " + ", ".join(survivors))
        print(f"  On n={n} videos this is suggestive, not settled"
              + ("" if n >= MIN_N_FOR_EVIDENCE else f" — n is below the {MIN_N_FOR_EVIDENCE}-point bar "
                                                    "this script sets for evidence."))
        print("  ACTION: the grader may ADVISE spend (rank two candidate scripts) but must not "
              "hard-gate it until n is larger.")
    if hook.get("rho") is not None:
        print(f"\n  For the record: first_second_hook vs stayed-to-watch is rho={hook['rho']:+.2f} "
              f"at n={hook['n']}, p={_fmt(hook['p'], '.3f').strip()},")
        print(f"  swinging {hook['lo']:+.2f}..{hook['hi']:+.2f} if any single video is removed. "
              f"overall/100 is rho={_fmt(overall.get('rho'), '.2f').strip()}.")
    print(_rule())
    return 0


if __name__ == "__main__":
    sys.exit(main())
