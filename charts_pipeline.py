"""
Bar Chart Race video pipeline.

Flow:
  1. Claude plans the video AND generates/locates the data
  2. Data fetched from World Bank API  — OR — generated from Claude's knowledge
  3. bar_chart_race renders the animation
  4. CC-BY background music fetched from object storage + mixed in with ffmpeg
  5. Returns final MP4 + YouTube metadata (title, description, tags)

Free data sources:
  - World Bank Open Data API  (no key — GDP, population, CO2, life expectancy …)
  - Claude's training knowledge (billionaires, music, sports, companies …)

Music:
  - Kevin MacLeod CC-BY tracks via externally stored, checksum-verified assets
"""

import os
import json
import shutil
import subprocess
from io import StringIO
import requests
import pandas as pd
import anthropic
from media_binaries import probe_duration

from music_assets import MUSIC_CREDIT, get_music_path

_client = None

# Match the rest of the codebase (explainer is on 4-8); the chart PLAN+DATA call is the most
# hallucination-exposed call in the app, so it must run on the better-recall model.
_MODEL = os.environ.get("CHARTS_MODEL", "claude-opus-4-8")


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _ep():
    """Lazy handle to the explainer pipeline so we can reuse its battle-tested helpers
    (_parse_script_json, _msg_cost, generate_thumbnail) without a heavy import at module load."""
    import explainer_pipeline as ep
    return ep


def _ensure_music(mood: str) -> str | None:
    """Compatibility wrapper around the shared object-storage resolver."""
    return get_music_path(mood)


# ── World Bank API ─────────────────────────────────────────────────────────────

class ChartDataError(Exception):
    """A genuine data-fetch failure (HTTP/JSON/transport) — distinct from a valid-but-empty
    result, so the caller can tell 'API hiccup' apart from 'no data for this query'."""


def fetch_world_bank(
    indicator: str,
    country_codes: list[str],
    start_year: int,
    end_year: int,
    divisor: float = 1.0,
) -> pd.DataFrame:
    """
    Pull World Bank indicator for given countries + year range.
    Returns DataFrame (index=year int, columns=country names, values=metric).
    """
    codes = ";".join(country_codes)
    url = f"https://api.worldbank.org/v2/country/{codes}/indicator/{indicator}"
    records: list = []
    page = 1

    while True:
        data, last_err = None, None
        for _attempt in range(2):                       # one retry on a transient blip
            try:
                r = requests.get(
                    url,
                    params={"format": "json", "per_page": 1000,
                            "date": f"{start_year}:{end_year}", "page": page},
                    timeout=30,
                )
                r.raise_for_status()
                data = r.json()
                break
            except Exception as e:                       # HTTP error / JSON decode / transport
                last_err = e
        if data is None:
            raise ChartDataError(f"World Bank API request failed: {last_err}")
        # A well-formed empty result (e.g. indicator doesn't cover these countries) → stop cleanly;
        # the caller treats an empty DataFrame as "no data for this query", not an API failure.
        if not data or len(data) < 2 or not data[1]:
            break
        records.extend(data[1])
        if page >= data[0].get("pages", 1):
            break
        page += 1

    rows: dict = {}
    for rec in records:
        if rec.get("value") is None:
            continue
        year = int(rec["date"])
        country = rec["country"]["value"]
        rows.setdefault(year, {})[country] = rec["value"] / divisor

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).T.sort_index()
    df.index = df.index.astype(int)
    return df


# ── Claude planning ────────────────────────────────────────────────────────────

_SYSTEM = (
    "You are a data-visualisation expert and YouTube content strategist. "
    "You have broad historical knowledge and know how to create viral bar chart race videos."
)

_PROMPT = """\
Create a bar chart race video for this request: "{prompt}"

Choose the best data approach:

A) "world_bank" — for country-level economic/social data:
   Use the World Bank Open Data API. Leave "data" as null.
   Common indicators:
     NY.GDP.MKTP.CD  GDP current US$ (use divisor 1e12 → trillions)
     SP.POP.TOTL     Population      (use divisor 1e6  → millions)
     EN.ATM.CO2E.KT  CO2 kt          (use divisor 1000 → Mt)
     NY.GDP.PCAP.CD  GDP per capita US$
     SP.DYN.LE00.IN  Life expectancy years
     IT.NET.USER.ZS  Internet users % of population
     MS.MIL.XPND.GD.ZS  Military spending % of GDP
   Country codes: 3-letter ISO (USA, CHN, GBR, DEU, FRA, JPN, IND, BRA, RUS, CAN, KOR, ITA, AUS, ESP, MEX, IDN, NLD, SAU, TUR, CHE, POL, SWE, BEL, NOR, AUT, NGA, ZAF, EGY, PAK, VNM, THA, PHL, SGP, ARE, ISR, QAT, ARG, CHL, COL, IRN)

B) "generated" — for ANY other topic (billionaires, music, sports, companies, movies …):
   Generate the full dataset from your knowledge. Be as accurate as possible.
   Include EVERY year in the range for smooth animation.
   Include 10–15 named entities (keep it tight to stay within token limits).
   Values are plain numbers (e.g. net worth in billions, not "$180B").
   Keep the range to ≤ 40 years unless the topic requires more.

Return ONLY a JSON object — no markdown, no commentary:
{{
  "data_source": "world_bank" | "generated",
  "title": "Compelling chart title (shown on video, ≤ 60 chars)",
  "metric_label": "Axis label e.g. Net Worth (US$ Billion)",
  "start_year": <int>,
  "end_year": <int>,
  "n_bars": 10,
  "music_mood": "energetic" | "dramatic" | "corporate" | "nostalgic" | "upbeat" | "tense",
  "wb_indicator": "code or null",
  "wb_countries": ["ISO3", ...] or null,
  "wb_divisor": 1.0,
  "annotations": [
    {{"year": <int>, "text": "Short event label e.g. Dot-com crash"}}
  ],
  "youtube_title": "SEO-optimised title ≤ 70 chars",
  "youtube_description": "Full YouTube description ≥ 150 words. Include: what the video shows, why it's interesting, key moments, hashtags at the end.",
  "youtube_tags": ["tag1", "tag2", ... at least 15 tags],
  "data": null | {{"YEAR": {{"Entity Name": numeric_value}}, ...}}
}}"""


_DATA_FACTCHECK_SYSTEM = (
    "You are a meticulous data fact-checker for a chart-race video. You receive a TITLE, a metric "
    "label, and a table of {year: {entity: value}} that was GENERATED FROM MEMORY and may contain "
    "errors. Correct any values you are confident are wrong, using your best knowledge, keeping the "
    "SAME structure, entities, years, and units. For any entity you CANNOT verify with reasonable "
    "confidence across the range, list it in drop_entities rather than show invented numbers as fact. "
    'Return ONLY JSON: {"data": {<corrected, same shape>}, "drop_entities": ["name", ...], '
    '"notes": ["short correction note", ...], "confidence": "high"|"medium"|"low"}.'
)


def factcheck_generated_data(title: str, metric_label: str, data: dict,
                             cost_sink: list | None = None) -> tuple[dict, list, str]:
    """Second-model pass over AI-generated chart numbers (the explainer's factcheck lesson applied to
    data). Returns (corrected_data, notes, confidence). DEGRADES to the original data on any failure
    so it never breaks a render."""
    if not isinstance(data, dict) or not data:
        return data, [], "unknown"
    try:
        ep = _ep()
        r = _get_client().messages.create(
            model=_MODEL, max_tokens=8000, system=_DATA_FACTCHECK_SYSTEM,
            messages=[{"role": "user", "content":
                       f'Title: "{title}"\nMetric: {metric_label}\nData JSON:\n{json.dumps(data)}'}])
        if cost_sink is not None:
            cost_sink.append(ep._msg_cost(r.usage))
        out, rc = ep._parse_script_json(r.content[0].text)
        if cost_sink is not None and rc:
            cost_sink.append(rc)
        if not isinstance(out, dict) or not isinstance(out.get("data"), dict):
            return data, [], "unknown"
        corrected = out["data"]
        drop = {str(e) for e in (out.get("drop_entities") or [])}
        if drop:
            corrected = {y: {e: v for e, v in (row or {}).items() if e not in drop}
                         for y, row in corrected.items()}
        notes = [str(n) for n in (out.get("notes") or [])][:8]
        if drop:
            notes.append("dropped (unverifiable): " + ", ".join(sorted(drop)))
        return corrected, notes, str(out.get("confidence", "unknown"))
    except Exception:
        return data, [], "unknown"


def _coverage_and_clean(df: pd.DataFrame, log=lambda m: None,
                        min_entity_real: float = 0.4) -> tuple[pd.DataFrame, dict]:
    """Honest gap handling: measure REAL coverage before interpolation, drop too-sparse entities,
    then interpolate ONLY small interior gaps (never extend a series past its real range with
    ffill/bfill). Returns (clean_df, coverage_meta)."""
    full = range(int(df.index.min()), int(df.index.max()) + 1)
    df = df.reindex(full)
    n_years = len(df)
    keep, sparse = [], []
    for col in df.columns:
        ratio = df[col].notna().sum() / max(1, n_years)
        (keep if ratio >= min_entity_real else sparse).append(col)
    dropped: list = []
    if sparse and len(keep) >= 3:                 # only prune if enough remain to still be a race
        df = df[keep]
        dropped = sparse
        log(f"Dropped {len(dropped)} sparse entit(ies) (<{int(min_entity_real*100)}% real data): "
            + ", ".join(map(str, dropped[:6])))
    real_cells = int(df.notna().sum().sum())
    total_cells = (df.shape[0] * df.shape[1]) or 1
    # interior-only, small gaps; edge gaps stay NaN → entity simply doesn't race those years
    df = df.interpolate(method="linear", axis=0, limit=2, limit_area="inside")
    meta = {
        "coverage": round(real_cells / total_cells, 3),
        "n_years": n_years,
        "entities": int(df.shape[1]),
        "dropped_entities": dropped,
        "interpolated_cells": int(df.notna().sum().sum()) - real_cells,
        "real_cells": real_cells,
        "total_cells": total_cells,
    }
    return df, meta


def plan_and_fetch(prompt: str, progress_cb=None, improve_note: str = "") -> tuple[pd.DataFrame, dict]:
    """
    Ask Claude to plan the video and supply/locate data, fact-check generated data, and honestly
    handle gaps. Returns (DataFrame, config_dict) — config carries _cost/_provenance/_coverage/
    _factcheck_notes for the caller's degraded/cost reporting. `improve_note` feeds back drama-gate
    feedback so a re-plan picks a more dynamic race.
    """
    def log(m):
        if progress_cb:
            progress_cb(m)

    log("stage:Planning with Claude AI...")
    log(f'Request: "{prompt}"')

    ep = _ep()
    cost: list[float] = []
    content = _PROMPT.format(prompt=prompt)
    if improve_note:
        content += "\n\nIMPORTANT FEEDBACK ON A PREVIOUS ATTEMPT:\n" + improve_note
    resp = _get_client().messages.create(
        model=_MODEL,
        max_tokens=16000,          # bumped: large datasets + description can exceed 8k
        system=_SYSTEM,
        messages=[{"role": "user", "content": content}],
    )
    cost.append(ep._msg_cost(resp.usage))

    # Robust parse (fence-strip + one repair retry) reused from the explainer.
    try:
        config, _rc = ep._parse_script_json(resp.content[0].text)
        cost.append(_rc)
    except Exception as exc:
        if (resp.stop_reason or "") == "max_tokens":
            raise ValueError("Claude's response was cut off (token limit reached). "
                             "Try a shorter date range or fewer entities.") from exc
        raise ValueError(f"Claude returned invalid JSON ({exc}). Try rephrasing your request.") from exc

    # Post-parse validation — catch a silently truncated/garbled plan before we render nothing useful.
    for k in ("data_source", "start_year", "end_year"):
        if k not in config:
            raise ValueError(f"Plan is missing '{k}' (response may have been truncated) — try rephrasing.")

    log(f"Title: {config.get('title')}")
    log(f"Range: {config['start_year']}–{config['end_year']} · top {config.get('n_bars', 10)} bars")
    config["_provenance"] = ("World Bank Open Data" if config["data_source"] == "world_bank"
                             else "AI-generated estimates — not verified")

    # ── Fetch / build DataFrame ────────────────────────────────────────────────
    if config["data_source"] == "world_bank":
        log("stage:Fetching data from World Bank API...")
        df = fetch_world_bank(
            config["wb_indicator"],
            config["wb_countries"],
            config["start_year"],
            config["end_year"],
            divisor=float(config.get("wb_divisor", 1.0)),
        )
        log(f"Received {len(df)} years × {len(df.columns)} countries")
    else:
        log("stage:Fact-checking AI-generated data...")
        raw_data: dict = config.get("data") or {}
        corrected, fc_notes, conf = factcheck_generated_data(
            config.get("title", ""), config.get("metric_label", ""), raw_data, cost_sink=cost)
        config["_factcheck_notes"], config["_data_confidence"] = fc_notes, conf
        if fc_notes:
            log(f"Data fact-check ({conf} confidence): {len(fc_notes)} change(s)")
            for n in fc_notes[:5]:
                log(f"  • {n}")
        log("stage:Building dataset from AI knowledge...")
        rows: dict = {}
        for y, v in (corrected or {}).items():
            try:
                yi = int(str(y).strip()[:4])          # tolerate "1990", "1990s", " 1990 "
            except Exception:
                continue
            if isinstance(v, dict):
                rows[yi] = {e: val for e, val in v.items() if isinstance(val, (int, float))}
        df = pd.DataFrame(rows).T.sort_index()
        if not df.empty:
            df.index = df.index.astype(int)
        log(f"Dataset: {len(df)} periods × {len(df.columns)} entities")

    if df.empty:
        raise ValueError("No data returned — try rephrasing your request")
    # A 1-year or 1-entity "race" means the plan/data was truncated or too thin to animate.
    if len(df) < 2 or df.shape[1] < 2:
        raise ValueError(
            f"Data is too thin to animate ({len(df)} period(s) × {df.shape[1]} entit(ies)) — "
            "the plan may have been truncated; try a wider range or rephrase.")

    # Honest gap handling + real-coverage measurement (no fabricated trends / edge flat-lines).
    df, cov = _coverage_and_clean(df, log=log)
    config["_coverage"] = cov
    config["_cost"] = round(sum(c for c in cost if c), 4)
    return df, config


# ── Render ─────────────────────────────────────────────────────────────────────

def render_chart(df: pd.DataFrame, config: dict, output_dir: str, progress_cb=None) -> str:
    """Render the bar chart race animation. Returns path to raw MP4 (no audio)."""
    import bar_chart_race as bcr
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    def log(m):
        if progress_cb:
            progress_cb(m)

    n_years = len(df)
    n_bars = min(config.get("n_bars", 10), len(df.columns))
    steps = 30  # smooth interpolation between years
    log("stage:Rendering animation...")
    log(f"{n_years} years × {steps} steps = {n_years * steps} frames")

    raw_path = os.path.join(output_dir, "chart_raw.mp4")
    metric_label = config.get("metric_label", "")

    # ── Smart scale: keep bar labels (integers) meaningful ────────────────────
    # The library formats bar values as {x:,.0f} — scale up small ranges
    # so 1.2 doesn't round to "1" and lose distinction from 0.8.
    max_val = df.max().max()
    if max_val < 5:
        df = df * 100
        scale_suffix = " ×0.01"
    elif max_val < 50:
        df = df * 10
        scale_suffix = " ×0.1"
    else:
        scale_suffix = ""
    display_metric = f"{metric_label}{scale_suffix}" if scale_suffix else metric_label

    # ── Distinct 20-color palette — saturated, easily trackable ───────────────
    PALETTE = [
        "#E63946",  # vivid red
        "#457B9D",  # steel blue
        "#2A9D8F",  # teal
        "#E9C46A",  # golden yellow
        "#F4A261",  # warm orange
        "#9B2335",  # deep crimson
        "#264653",  # dark slate
        "#8338EC",  # violet
        "#06D6A0",  # mint
        "#FB8500",  # amber
        "#7209B7",  # deep purple
        "#3A86FF",  # royal blue
        "#FF006E",  # hot pink
        "#FFBE0B",  # sunny yellow
        "#8AC926",  # lime green
        "#6A4C93",  # plum
        "#1982C4",  # medium blue
        "#FF595E",  # coral
        "#6A994E",  # olive green
        "#C77DFF",  # lavender
    ]

    # ── Per-frame text: dramatic annotation when its year is on screen, else a metric+source footer ──
    # bar_chart_race removes+re-adds the period_summary_func text every frame, and passes the current
    # (interpolated) period as values.name — so we key annotations off the live year. The library
    # exposes only ONE such text artist, so an active annotation temporarily replaces the footer.
    ann_by_year: dict[int, str] = {}
    for a in (config.get("annotations") or []):
        try:
            ann_by_year[int(a.get("year"))] = str(a.get("text", "")).strip()
        except Exception:
            pass
    provenance = config.get("_provenance", "")
    footer = f"{display_metric}   ·   Source: {provenance}" if provenance else display_metric

    def metric_annotation(values, ranks):
        try:
            yr = int(round(float(values.name)))
        except Exception:
            yr = None
        if yr is not None and ann_by_year.get(yr):
            return {                       # dramatic event label — prominent, top-center
                "x": 0.5, "y": 0.88, "s": ann_by_year[yr],
                "ha": "center", "va": "top", "size": 26, "weight": "bold", "color": "#E63946",
            }
        return {                           # metric label + data provenance — small, bottom-left
            "x": 0.01, "y": 0.01, "s": footer,
            "ha": "left", "va": "bottom", "size": 12, "color": "#555555",
        }

    # ── Light-theme rcParams ──────────────────────────────────────────────────
    # The library hardcodes ax.set_facecolor('.9') ≈ #E6E6E6 (light gray)
    # and ax.grid(True, axis='x', color='white'), so we only need to set
    # the figure background and text colours here.
    light_rc = {
        "figure.facecolor": "#EBEBEB",
        "savefig.facecolor": "#EBEBEB",
        "text.color":        "#000000",
        "axes.labelcolor":   "#000000",
        "xtick.color":       "#333333",
        "ytick.color":       "#333333",
        "font.family":       "DejaVu Sans",
    }

    with matplotlib.rc_context(light_rc):
        bcr.bar_chart_race(
            df=df,
            filename=raw_path,
            orientation="h",
            sort="desc",
            n_bars=n_bars,
            fixed_order=False,
            steps_per_period=steps,
            period_length=1200,        # ms per year
            interpolate_period=True,
            label_bars=True,
            bar_size=0.82,
            # Year watermark: massive, low-opacity white, bottom-right quadrant
            period_label={
                "x": 0.95, "y": 0.20,
                "ha": "right", "va": "center",
                "size": 130, "weight": "bold",
                "color": "white", "alpha": 0.55,
            },
            period_fmt="{x:.0f}",
            period_summary_func=metric_annotation,
            title=config.get("title", ""),
            title_size="xx-large",
            bar_label_size=13,
            tick_label_size=13,
            shared_fontdict={"family": "DejaVu Sans", "color": "#000000"},
            cmap=PALETTE,
            filter_column_colors=True,
            dpi=120,                   # 16 × 120 = 1920, 9 × 120 = 1080
            figsize=(16, 9),
            bar_kwargs={"linewidth": 0, "alpha": 0.90},
        )

    log("Animation rendered ✓")
    return raw_path


# ── Audio ──────────────────────────────────────────────────────────────────────

def add_audio(video_path: str, mood: str, output_path: str, progress_cb=None) -> bool:
    """Loop the music track to match video length and mix in with fade. Returns True if music was
    mixed, False if it fell back to a SILENT copy (so the caller can flag the render degraded)."""
    def log(m):
        if progress_cb:
            progress_cb(m)

    music_path = _ensure_music(mood)
    if not music_path:
        log("⚠ No music available (download failed) — outputting SILENT video")
        shutil.copy(video_path, output_path)
        return False

    dur = probe_duration(video_path)
    fade_out_start = max(0.0, dur - 4.0)

    log(f"Music: {mood} (Kevin MacLeod, CC-BY)")
    log(f"Mixing audio ({dur:.0f}s, fade out at {fade_out_start:.0f}s)...")

    subprocess.run(
        [
            "ffmpeg",
            "-i", video_path,
            "-stream_loop", "-1", "-i", music_path,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-t", str(dur),
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-af", f"volume=0.4,afade=t=in:ss=0:d=2,afade=t=out:st={fade_out_start:.1f}:d=4",
            "-shortest",
            output_path, "-y",
        ],
        check=True,
        capture_output=True,
    )

    log("Audio mixed ✓")
    return True


# ── Drama gate (the explainer engagement-gate lesson, applied to a race) ─────────

_CHART_DRAMA_FLOOR   = int(os.environ.get("CHART_DRAMA_FLOOR", "30"))    # below = re-plan if budget
_CHART_DRAMA_RETRIES = int(os.environ.get("CHART_DRAMA_RETRIES", "1"))   # extra re-plan attempts


def _drama_score(df: pd.DataFrame) -> tuple[int, dict]:
    """Objective 'is this race worth watching' signal from the data: #1 lead changes, distinct
    leaders, churn in the top-3, and how close the finish is. A flat 'X #1 forever' chart scores low."""
    if df.shape[1] < 2 or len(df) < 2:
        return 0, {}
    leaders = df.idxmax(axis=1)
    lead_changes = int((leaders != leaders.shift()).sum() - 1)        # # of times the #1 swaps
    distinct_leaders = int(leaders.nunique())
    top3: set = set()
    for _, row in df.iterrows():
        top3 |= set(row.dropna().nlargest(3).index)
    distinct_top3 = len(top3)
    last = df.iloc[-1].dropna().sort_values(ascending=False)
    gap = float((last.iloc[0] - last.iloc[1]) / last.iloc[0]) if len(last) > 1 and last.iloc[0] else 1.0
    score = min(100, int(lead_changes * 18 + distinct_leaders * 10 + distinct_top3 * 4
                         + (1 - min(max(gap, 0.0), 1.0)) * 20))
    return score, {"lead_changes": lead_changes, "distinct_leaders": distinct_leaders,
                   "distinct_top3": distinct_top3, "final_gap": round(gap, 2)}


def plan_fetch_graded(prompt: str, progress_cb=None) -> tuple[pd.DataFrame, dict]:
    """Plan + fetch, score the race for drama, and re-plan a STATIC race for a more dynamic angle
    (keep-best, mirroring the explainer's engagement gate). Returns the best (df, config)."""
    def log(m):
        if progress_cb:
            progress_cb(m)

    best = None  # (df, config, sortkey)
    note = ""
    for attempt in range(1 + max(0, _CHART_DRAMA_RETRIES)):
        df, config = plan_and_fetch(prompt, progress_cb=progress_cb, improve_note=note)
        score, sig = _drama_score(df)
        lead_changes = sig.get("lead_changes", 0)
        config["_drama"] = {"score": score, **sig}
        log(f"Race drama: {score}/100 ({lead_changes} lead-changes, "
            f"{sig.get('distinct_leaders')} distinct leaders, {sig.get('distinct_top3')} in top-3)")
        # Keep-best PREFERS a race with an actual top-spot overtake, THEN higher score — so a livelier
        # re-plan wins even if its composite is a hair lower.
        sortkey = (1 if lead_changes >= 1 else 0, score)
        if best is None or sortkey > best[2]:
            best = (df, config, sortkey)
        # Accept only a race that clears the floor AND has >=1 lead change. A #1 that NEVER changes is
        # the format's weakest outcome, so re-plan for an overtake even if mid-pack churn pushed the
        # composite over the floor (option 2).
        if score >= _CHART_DRAMA_FLOOR and lead_changes >= 1:
            break
        if lead_changes < 1:
            note = ("Your previous plan had NO lead change — the #1 spot never moved the entire race, "
                    "which is the most boring outcome for this format. Pick a metric / timespan / "
                    "entity set where the LEAD ACTUALLY CHANGES HANDS (a clear overtake at #1), not "
                    "just churn lower down. A late-emerging entity that overtakes an early leader is ideal.")
            log(f"No lead change (#1 never moves) — re-planning for a top-spot overtake…")
        else:
            note = (f"Your previous plan was a STATIC race (drama {score}/100). Choose a MORE DYNAMIC "
                    "angle where the ranking changes a lot — leads swap, newcomers surge, big overtakes.")
            log(f"Race too static (<{_CHART_DRAMA_FLOOR}) — re-planning for more drama…")
    return best[0], best[1]


# ── Main entry point ───────────────────────────────────────────────────────────

def run_charts_pipeline(prompt: str, output_dir: str, progress_cb=None) -> dict:
    """
    Full pipeline: plan → fetch → render → audio → thumbnail.
    Returns dict incl. honest status/degraded_reasons, provenance, coverage, cost, thumbnail.
    """
    def log(m):
        if progress_cb:
            progress_cb(m)

    # ── Checkpoint: skip the (paid) plan+factcheck if we already did it for this output_dir ──
    ckpt = os.path.join(output_dir, "chart_state.json")
    df = config = None
    if os.path.exists(ckpt):
        try:
            with open(ckpt) as f:
                _st = json.load(f)
            df = pd.read_json(StringIO(_st["df"]), orient="split").astype("float64")
            df.index = df.index.astype(int)
            config = _st["config"]
            log("▶ Resuming from checkpoint — plan + fact-check reused (no re-pay)")
        except Exception:
            df = config = None
    if df is None:
        df, config = plan_fetch_graded(prompt, progress_cb=progress_cb)
        try:
            tmp = ckpt + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"df": df.to_json(orient="split"), "config": config}, f)
            os.replace(tmp, ckpt)            # atomic, mirrors the explainer _state.json pattern
        except Exception:
            pass

    # ── Data-integrity FLOOR: refuse to render a chart built on almost nothing ──
    cov = config.get("_coverage", {}) or {}
    coverage = cov.get("coverage", 1.0)
    if coverage < 0.25:
        raise ValueError(
            f"Only {coverage*100:.0f}% of the requested data is real "
            f"({cov.get('real_cells')}/{cov.get('total_cells')} cells) — refusing to render a chart "
            "that would be mostly fabricated. Try a different metric, range, or set of entities.")

    raw_path = render_chart(df, config, output_dir, progress_cb=progress_cb)

    log("stage:Adding audio...")
    final_path = os.path.join(output_dir, "chart_final.mp4")
    music_ok = add_audio(raw_path, config.get("music_mood", "corporate"), final_path, progress_cb=progress_cb)
    if music_ok:
        # CC-BY requires a credit; append it to the description so an upload is license-compliant.
        desc = config.get("youtube_description", "") or ""
        if MUSIC_CREDIT not in desc:
            config["youtube_description"] = (desc + "\n\n" + MUSIC_CREDIT).strip()

    # ── Graded thumbnail (reused from the explainer) — best-effort, never fails the video ──
    thumbnail_path = ""
    try:
        log("stage:Generating thumbnail...")
        ep = _ep()
        tcost: list[float] = []
        thumbnail_path = ep.generate_thumbnail(
            title=config.get("youtube_title") or config.get("title", ""),
            question=prompt, style_mode="scientific", video_format="landscape",
            out_dir=output_dir, cost_sink=tcost) or ""
        config["_cost"] = round(float(config.get("_cost", 0) or 0) + sum(c for c in tcost if c), 4)
        log("Thumbnail ✓" if thumbnail_path else "Thumbnail skipped")
    except Exception as e:
        log(f"Thumbnail skipped: {type(e).__name__}")

    # ── Honest status (the explainer degraded pattern) — tell the truth about a thin chart ──
    reasons: list[str] = []
    n_bars_req = int(config.get("n_bars", 10) or 10)
    if cov.get("entities", 0) < min(n_bars_req, 5):
        reasons.append(f"only {cov.get('entities')} entities had usable data (wanted {n_bars_req})")
    if coverage < 0.5:
        reasons.append(f"{coverage*100:.0f}% real data — {cov.get('interpolated_cells', 0)} cells interpolated")
    if cov.get("dropped_entities"):
        reasons.append(f"dropped {len(cov['dropped_entities'])} too-sparse entit(ies)")
    if config.get("_data_confidence") == "low":
        reasons.append("AI-generated data flagged LOW confidence by fact-check")
    if not music_ok:
        reasons.append("no background music (download failed) — silent video")
    drama_meta = config.get("_drama") or {}
    drama = drama_meta.get("score", 100)
    if drama_meta.get("lead_changes", 1) == 0:
        reasons.append("no overtake — the #1 spot never changes (the format's weakest outcome, even after re-planning)")
    elif drama < _CHART_DRAMA_FLOOR:
        reasons.append(f"low drama ({drama}/100) — the ranking barely changes, even after re-planning")
    status = "degraded" if reasons else "ok"

    log("Video complete ✓")
    if status == "degraded":
        log("⚠ DEGRADED: " + "; ".join(reasons))

    return {
        "video_path": final_path,
        "title": config.get("title", ""),
        "youtube_title": config.get("youtube_title", ""),
        "youtube_description": config.get("youtube_description", ""),
        "youtube_tags": config.get("youtube_tags", []),
        "annotations": config.get("annotations", []),
        "thumbnail_path": thumbnail_path,
        "provenance": config.get("_provenance", ""),
        "data_confidence": config.get("_data_confidence", ""),
        "coverage": coverage,
        "drama": config.get("_drama"),
        "factcheck_notes": config.get("_factcheck_notes", []),
        "cost_usd": config.get("_cost", 0.0),
        "status": status,
        "degraded_reasons": reasons,
    }
