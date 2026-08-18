"""
FastAPI backend for the YouTube Video Generation Pipeline.
Exposes:
  POST /api/generate        — start a generation job
  GET  /api/status/{job_id} — SSE stream of progress events
  GET  /api/download/{job_id} — download the final MP4
  GET  /api/script/{job_id}   — get the generated script JSON
"""

import os
import time
from dotenv import load_dotenv
load_dotenv(override=True)   # override so .env edits (e.g. I2V_PROVIDER) reliably take on reload
import uuid
import asyncio
import json
import shutil
import tempfile
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException, File, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="YouTube Pipeline API")

# Opt-in shared-secret auth. When APP_SHARED_SECRET is set, every MUTATING request (non GET/HEAD/
# OPTIONS — the credit-spending /generate, the file upload, refresh) must carry a matching
# `X-App-Secret` header. GETs (SSE status, downloads, the static UI) stay open so browser reads
# work. Unset (default) = no auth, fine for a localhost-only dev box; REQUIRED before you bind to a
# reachable host (see __main__). Implemented as PURE ASGI (not BaseHTTPMiddleware) so it never
# buffers the long-lived SSE progress streams.
APP_SHARED_SECRET = os.environ.get("APP_SHARED_SECRET", "").strip()


class SharedSecretMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope.get("type") == "http" and APP_SHARED_SECRET
                and scope.get("method") not in ("GET", "HEAD", "OPTIONS")):
            hdrs = dict(scope.get("headers") or [])
            if hdrs.get(b"x-app-secret", b"").decode() != APP_SHARED_SECRET:
                from starlette.responses import JSONResponse
                await JSONResponse({"detail": "unauthorized — missing/invalid X-App-Secret"},
                                   status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


# CORS: default to localhost only (a wildcard let any site a browser visits POST here). Override
# with ALLOWED_ORIGINS (comma list; "*" to truly open for dev).
# The port is not always 8000: with autoPort the harness picks a free one and passes it in PORT, so
# hardcoding 8000 here would leave the browser preview blocked by CORS on any other port.
_PORT = os.environ.get("PORT", "8000")
_DEFAULT_ORIGINS = ",".join(f"http://{h}:{_PORT}" for h in ("localhost", "127.0.0.1"))
_ALLOWED_ORIGINS = [o.strip() for o in os.environ.get(
    "ALLOWED_ORIGINS", _DEFAULT_ORIGINS).split(",") if o.strip()]

# Order matters (Starlette wraps last-added = OUTERMOST): add auth FIRST (inner), CORS LAST so CORS
# stays outermost and even a 401 carries CORS headers (a cross-origin client can read the error).
app.add_middleware(SharedSecretMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── State store (in-memory; use Redis for production) ─────────────────────────

jobs: dict[str, dict] = {}
hl_jobs: dict[str, dict] = {}
chart_jobs: dict[str, dict] = {}
explainer_jobs: dict[str, dict] = {}
stateboard_jobs: dict[str, dict] = {}

# Finished explainer videos are copied here with a small index, so a dev-server
# reload (which wipes the in-memory job store) can't orphan a completed video.
FINISHED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "finished_videos")
# Working dirs for UI jobs. Persisted (not tempfile) so a finished video can be REPAIRED rather than
# regenerated -- see the note at the mkdtemp call site.
JOBS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "renders", "_ui_jobs")
os.makedirs(JOBS_DIR, exist_ok=True)
JOBS_KEEP_DAYS = float(os.environ.get("JOBS_KEEP_DAYS", "14"))


def _sweep_old_jobs(keep_days: float = None):
    """Delete job dirs older than JOBS_KEEP_DAYS. Persisting working dirs trades disk for the
    ability to repair a finished video, so the disk has to be reclaimed on a timer instead."""
    import shutil as _sh
    import time as _t
    cutoff = _t.time() - (keep_days if keep_days is not None else JOBS_KEEP_DAYS) * 86400
    try:
        for name in os.listdir(JOBS_DIR):
            d = os.path.join(JOBS_DIR, name)
            if os.path.isdir(d) and os.path.getmtime(d) < cutoff:
                _sh.rmtree(d, ignore_errors=True)
    except Exception:
        pass
_FINISHED_INDEX = os.path.join(FINISHED_DIR, "index.json")

# Curiosity-gap "trending questions" cache — populated by the topic engine (manually, on startup,
# or by a cron hitting /api/explainer/refresh-trending) and served to the UI's chips.
_TRENDING_FILE = os.path.join(FINISHED_DIR, "trending_questions.json")
# Manual per-video metrics — the real-audience feedback loop. Persisted to Neon (db.video_metrics)
# AND mirrored to this local JSON so it survives a DB outage and works even with no DATABASE_URL.
_METRICS_FILE = os.path.join(FINISHED_DIR, "video_metrics.json")
import threading
_TRENDING_LOCK = threading.Lock()   # serialize the 3 callers (scheduler / GET auto-seed / manual POST)

# Generate curiosity-gap topics for BOTH channels. Edit this to add/rename channels.
CHANNELS = [
    {"label": "Bolt explains the world",
     # Broadened 2026-07-15: was steered HARD to planet/space what-ifs, which made the pool CLUSTER
     # (repetitive — the user had "nothing to use"). Now ROTATES across 5 archetypes so a single refresh
     # yields a diverse pool (what-if planet/space/body · counterintuitive-why · hidden-systems ·
     # origins/firsts · survival-failure). Diversity via a BROAD niche, not more channels (quota-safe).
     "niche": ("Grounded, believable curiosity-gap explainers — ROTATE WIDELY across these angles so "
               "the pool NEVER clusters on one subject: (1) 'What if [a real thing about a PLANET/SPACE/"
               "physics OR the human BODY/biology] changed by a small amount?' (Moon distance, magnetic "
               "field, oxygen %, air pressure, day length, a body reflex, an organ, a cell behaviour) "
               "cascading into shocking REAL consequences; (2) counterintuitive 'WHY is [everyday thing] "
               "actually [surprising truth] / the real reason [X] happens' where the OBVIOUS answer is "
               "WRONG; (3) hidden invisible everyday SYSTEMS — 'where does [X] actually go/come from', "
               "how a system nobody sees works (returns, deleted files, the power grid at 3am, sewage); "
               "(4) ORIGINS/firsts — the first time humans did [X], why we began [a universal habit]; "
               "(5) SURVIVAL — what actually happens if [a system we all depend on] fails (GPS, the "
               "power grid, refrigeration, pollinators, an ocean current). STRONGLY favour SPECIFIC, "
               "high-stakes, FRESH angles a SMALL channel can win; vary the SUBJECT every time (do NOT "
               "stack planet what-ifs); AVOID fantasy (no Earth-explodes/aliens) and generic 'how does "
               "X work'")},
    {"label": "Bolt explains Ancient Humans",
     # Competitor-validated engine (2026-07-05): "how did humans solve a BASIC UNIVERSAL problem
     # before modern tools?" — everyday body/mind/daily-life questions everyone instantly gets,
     # pushed back to primitive times, with survival/fear/body/origin stakes. Lean UNIVERSAL &
     # visceral, NOT academic history. Title formats do heavy lifting.
     "niche": ("'How did ancient humans survive/handle/know [a basic UNIVERSAL problem] before "
               "[modern tools]?' — everyday body, mind & daily-life questions everyone understands "
               "(sleep, teeth, babies, cold, food-safety, smells, boredom, broken bones, going bald, "
               "fear, death), pushed back to primitive times with survival / fear / body / origin "
               "stakes. Title formats: 'How Did Ancient Humans Survive ___?', 'What Did Humans Do "
               "Before ___?', 'Why Did Humans First ___?', 'How Did Humans Know ___?'. Lean UNIVERSAL "
               "and visceral — NOT academic prehistory lectures")},
    {"label": "Bolt explains Airplanes",
     # Broadened 2026-07-15 to match the main channel: aviation PLUS critical-system-failure survival,
     # so the lane isn't limited to planes alone.
     "niche": ("aviation + critical-system-failure survival (respectful, curiosity-driven, NOT gore or "
               "body-count): airplane everyday mysteries passengers wonder about (brace position, cabin "
               "lights, window holes, no parachutes, engine-out gliding, why turbulence won't crash you) "
               "AND what actually happens if [a system we all depend on] fails for a while — GPS, the "
               "power grid, refrigeration, pollinators, the Gulf Stream, the internet backbone — real "
               "grounded cascades")},
    # SHORTS SIMULATION LANE — "What If You [change] N<unit> Every Second?" (BoneLab-style). Uses the
    # dedicated sim topic engine (engine="simulation"), which hard-filters to math-parseable linear
    # rates so every suggested title renders with correct numbers. Skips the title-reframe pass (the
    # "every second" format IS the title and must be preserved for the sim lane to trigger).
    {"label": "Bolt Shorts — Simulations",
     "engine": "simulation",
     "niche": ("'What If You [change] by [a number] Every Second?' viewer-as-subject science "
               "simulations — you grow/shrink/gain weight/speed up/heat up/get smarter, escalating on "
               "a clock to a real, grounded science limit")},
]


def _load_trending() -> dict:
    try:
        with open(_TRENDING_FILE) as f:
            return json.load(f)
    except Exception:
        return {"questions": [], "channels": [], "generated_at": None}


# Share of every refresh spent instantiating a PROVEN mould rather than inventing a new shape. The
# five moulds are the only structures that have repeated on this channel, so most of the batch should
# exploit them — but a channel that only ever re-cuts its own winners goes stale, and the exploratory
# remainder is the only place a SIXTH mould can come from. 70/30 is the split agreed with the user.
_MOULD_SHARE = 0.7

# Spare candidates requested per lane beyond what will be accepted, so a cross-source duplicate is
# absorbed rather than costing a topic. 2 covers the collision rate seen in testing without asking
# for a batch so long the model starts padding it with weak ideas.
_MIX_OVERASK = 2


def _mix_topics(mould_fn, explore_fn, n: int, exclude: list | None = None) -> tuple[list, dict]:
    """Fill n topic slots ~70% from the proven-mould generator and ~30% from the channel's own
    exploratory generator, deduping ACROSS the two sources. Returns (topics, mix stats).

    Both callables take (n, exclude) and return the generators' usual [{question, ...}]. Both are
    best-effort: whatever the mould lane cannot fill (Claude failure, everything deduped away) falls
    through to the exploratory lane, so a refresh NEVER returns fewer topics because the new path
    broke — the exploratory generator alone is exactly the old behaviour.

    Cross-source dedupe is the other reason this is a function and not two calls. Each generator
    already filters within its own batch and against `exclude`, but neither can see the other, so
    "Why Sharks Are Older Than Trees" from the mould lane and "Why Sharks Predate Trees" from the
    curiosity lane both survived into the same refresh. Accepted questions are also appended to the
    `exclude` handed to the SECOND generator, so the collision is usually avoided before it is paid
    for rather than filtered after.
    """
    import explainer_pipeline as ep
    n = max(0, int(n or 0))
    stats = {"mould": 0, "explore": 0, "dupes": 0}
    if not n:
        return [], stats
    used = [str(e).strip() for e in (exclude or []) if str(e).strip()]
    # ep's dedupe state, not a bare key set: it strips a mould's FRAME before comparing, so two
    # faithful instantiations of one mould are not read as the same video. Comparing whole titles
    # here threw away topics the generator had already correctly kept — every one_percent_daily
    # title shares "lost ... a day" and scores 0.667 against its own siblings.
    prior = ep.dedupe_state(used)      # already-used topics (from `exclude`)
    mix = ep.dedupe_state()            # accepted THIS refresh, so the count below is honestly
    out = []                           # "cross-source", not "collided with an old video"

    def _fill(fn, want: int, source: str) -> int:
        """Ask `fn` for `want` topics and keep the ones that aren't a near-duplicate of anything
        already used or already accepted. Returns how many were accepted. Never raises — a dead
        generator is a zero here, which the caller absorbs."""
        if want <= 0:
            return 0
        try:
            # Ask for a couple MORE than we will accept. Neither generator can see the other, so a
            # cross-source collision used to cost a slot outright — a refresh returned 9 where the
            # old single-generator path returned 10. The over-ask is free: it is the same ONE Claude
            # call either way, only a slightly longer reply, and _MIX_OVERASK spare candidates cover
            # the collisions instead of a second top-up call.
            qs = fn(want + _MIX_OVERASK, list(used)) or []
        except Exception as e:
            print(f"[trending] {source} topics failed: {e}")
            return 0
        got = 0
        for q in qs:
            if got >= want:
                break
            if not isinstance(q, dict):
                continue
            question = str(q.get("question") or "").strip()
            if not question:
                continue
            mould = str(q.get("mould") or "")
            if ep.dedupe_is_dup(mix, question, mould):
                stats["dupes"] += 1     # the other lane already produced this same video
                continue
            if ep.dedupe_is_dup(prior, question, mould):
                continue                # already-used topic; each generator should have caught this
            ep.dedupe_add(mix, question)
            used.append(question)       # so the NEXT generator is told about it up front
            q.setdefault("source", source)
            out.append(q)
            got += 1
        return got

    stats["mould"] = _fill(mould_fn, min(n, int(round(n * _MOULD_SHARE))), "mould")
    stats["explore"] = _fill(explore_fn, n - stats["mould"], "explore")
    return out, stats


def _refresh_trending() -> dict:
    """Regenerate curiosity-gap topics for every channel, market-validate them, and cache.
    Blocking (~10-15s/channel Claude call + YouTube). Coalesced (a second concurrent caller
    returns the current cache instead of double-spending quota) and written atomically so the
    3 callers can't corrupt the file. Never overwrites a good cache with an empty result, and
    never overwrites a previously-validated cache with a TOTAL validation failure (quota/network)."""
    import datetime
    import explainer_pipeline as ep
    if not _TRENDING_LOCK.acquire(blocking=False):
        print("[trending] refresh already in progress — returning current cache")
        return _load_trending()
    try:
        groups, flat = [], []
        for ch in CHANNELS:
            # Exclude topics already turned into videos so the refresh stops resurfacing them.
            exclude = []
            try:
                import db
                if db.db_enabled():
                    exclude = db.used_questions(ch["label"])
            except Exception as e:
                print(f"[trending] used-topic exclusion skipped for {ch['label']}: {e}")
            # 70% proven moulds / 30% the channel's own exploratory generator, deduped across both.
            # The exploratory lane stays the SAME generator as before (simulation vs curiosity) so
            # novelty does not disappear when the mould lane starts eating most of the batch.
            if ch.get("engine") == "simulation":
                _explore = lambda k, ex: ep.generate_simulation_topics(n=k, exclude=ex)
            else:
                _explore = lambda k, ex: ep.generate_curiosity_topics(niche=ch["niche"], n=k, exclude=ex)
            qs, mix = _mix_topics(
                lambda k, ex: ep.generate_mould_topics(n=k, exclude=ex, niche=ch["niche"]),
                _explore, n=10, exclude=exclude)
            # Print the mix that was ACHIEVED, not the one that was asked for — the mould lane
            # silently falling back to exploratory is exactly the failure this line exists to expose.
            print(f"[trending] {ch['label']}: {mix['mould']} mould + {mix['explore']} exploratory"
                  f" of 10, {mix['dupes']} cross-dupes dropped")
            for q in qs:
                q["channel"] = ch["label"]
            # `short_template`/`mould` only exist on mould topics and only the mould lane can produce
            # them. Snapshot them now so they can be restored after the enrichment passes below:
            # `short_template` is what routes a topic into the simulation lane AND `mould` is what
            # joins it to a measured prior, and a pass that ever rebuilt its dicts instead of
            # mutating them would drop both silently.
            _mould_fields = {str(q.get("question") or "").strip().lower():
                             {k: q[k] for k in ("mould", "short_template", "mould_stayed", "source")
                              if k in q}
                             for q in qs}
            # Validate against real YouTube market data (demand/outlier/competition) and re-rank
            # by opportunity. No-op when YOUTUBE_API_KEY is unset; never lets an API blip kill the
            # refresh — on any error we keep the curiosity-ranked list.
            try:
                qs = ep.validate_topics_youtube(qs)
            except Exception as e:
                print(f"[trending] youtube validation skipped for {ch['label']}: {e}")
            for q in qs:                                # no-op while validation mutates in place
                for k, v in _mould_fields.get(str(q.get("question") or "").strip().lower(), {}).items():
                    q.setdefault(k, v)
            # Add a click-optimized suggested_title per topic (separate from question). Best-effort.
            # SKIP the simulation lane: the "…Every Second?" phrasing IS the title and must stay
            # verbatim so the sim lane + math engine keep triggering off it. That is a PER-TOPIC
            # decision as well as a per-channel one, but it must be decided by the phrasing itself —
            # keying it off a stamped label skipped four titles per channel that do NOT trigger
            # _is_simulation_short at all, silently dropping 40% of the suggested titles to protect
            # phrasing nothing was reading.
            # Purely per-topic now. The old per-CHANNEL skip is subsumed: everything the simulation
            # channel's generator emits is sim-shaped by construction (it hard-filters on exactly
            # this test), while the mould topics that channel also carries are NOT, and the channel
            # gate was denying those a title for a lane they were never going to run in.
            _reframe = [q for q in qs
                        if ep.short_template_for(str(q.get("question") or "")) != "simulation"]
            if _reframe:
                try:
                    ep.suggest_titles(_reframe)       # mutates the same dicts qs holds
                except Exception as e:
                    print(f"[trending] title reframe skipped for {ch['label']}: {e}")
            # Persist to Neon (dedup + history) — best-effort; a DB outage never breaks the refresh.
            try:
                import db
                if db.db_enabled():
                    n_db = db.upsert_topics(ch["label"], qs)
                    if n_db:
                        print(f"[trending] stored {n_db} topics to db for {ch['label']}")
            except Exception as e:
                print(f"[trending] db store skipped for {ch['label']}: {e}")
            groups.append({"label": ch["label"], "niche": ch["niche"], "questions": qs})
            flat.extend(qs)
        # Pin the user's QUEUED topics (hand-picked ideas) to the TOP of each channel so they
        # survive the 12h regen and stay visible on the dashboard. Deduped; best-effort.
        try:
            import db
            if db.db_enabled():
                for g in groups:
                    pinned = db.queued_topics(g["label"])
                    if not pinned:
                        continue
                    have = {t.get("question", "").strip().lower() for t in g["questions"]}
                    fresh = [t for t in pinned if t.get("question", "").strip().lower() not in have]
                    for t in fresh:
                        t["channel"] = g["label"]
                    g["questions"] = fresh + g["questions"]
                    flat[:0] = fresh
        except Exception as e:
            print(f"[trending] queued merge skipped: {e}")
        n_validated = sum(1 for q in flat if q.get("validated"))
        payload = {"questions": flat, "channels": groups,
                   # truthful: did ANY topic actually validate (not merely "is a key configured")
                   "validated": n_validated > 0,
                   "validation_active": ep.youtube_validation_active(),
                   "validated_count": n_validated, "total_topics": len(flat),
                   "generated_at": datetime.datetime.now().isoformat(timespec="seconds")}
        # Don't clobber a previously-good cache when validation was active but TOTALLY failed
        # (quota/network) — keep the prior data rather than overwrite with all-unvalidated topics.
        if flat and ep.youtube_validation_active() and n_validated == 0:
            prior = _load_trending()
            if prior.get("validated_count", 0) > 0:
                print(f"[trending] validation produced 0/{len(flat)} (quota/network?) — keeping prior cache")
                return prior
        if flat:
            os.makedirs(FINISHED_DIR, exist_ok=True)
            try:
                tmp = _TRENDING_FILE + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(payload, f, indent=2)
                os.replace(tmp, _TRENDING_FILE)        # atomic swap — no partial/garbled file
            except OSError:
                pass
        return payload
    finally:
        _TRENDING_LOCK.release()


_INPROGRESS_INDEX = os.path.join(FINISHED_DIR, "inprogress.json")
_INDEX_LOCK = threading.Lock()   # serialize read-modify-write of the shared JSON indexes


def _atomic_write_json(path: str, data) -> None:
    """tmp + os.replace so a crash mid-dump can't truncate a shared index/checkpoint."""
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _record_inprogress(job_id: str, output_dir: str, request) -> None:
    """Record a started job (id → output_dir + request) so it can be RESUMED after a
    crash/reload without re-paying for already-generated scenes. Locked + atomic so two jobs
    starting at once can't lose each other (last-writer-wins) or corrupt the file."""
    try:
        os.makedirs(FINISHED_DIR, exist_ok=True)
        with _INDEX_LOCK:
            idx = {}
            if os.path.exists(_INPROGRESS_INDEX):
                with open(_INPROGRESS_INDEX) as f:
                    idx = json.load(f)
            req = request.model_dump() if hasattr(request, "model_dump") else request.dict()
            idx[job_id] = {"output_dir": output_dir, "request": req}
            _atomic_write_json(_INPROGRESS_INDEX, idx)
    except Exception:
        pass


def _clear_inprogress(job_id: str) -> None:
    """Drop a finished job from the resume index (it grew unbounded — never pruned on success)."""
    try:
        with _INDEX_LOCK:
            if not os.path.exists(_INPROGRESS_INDEX):
                return
            with open(_INPROGRESS_INDEX) as f:
                idx = json.load(f)
            if idx.pop(job_id, None) is not None:
                _atomic_write_json(_INPROGRESS_INDEX, idx)
    except Exception:
        pass


def _get_inprogress(job_id: str):
    try:
        with open(_INPROGRESS_INDEX) as f:
            return json.load(f).get(job_id)
    except Exception:
        return None


def _effective_template(request, result: dict | None = None) -> str:
    """Which lane a finished video was ACTUALLY produced in ("explainer" | "simulation" | "quiz").

    This is the ROUTING fact — what beat map generate_script used — recorded so an outcome can be
    traced back to the machinery that produced it. It is deliberately NOT the same question as
    metrics_import.classify(), which reads the shipped TITLE's shape; the two disagree on real rows
    and the measured aggregations (performance_block, _channel_fit_table) therefore key on classify()
    and fall back to this column only for a title-less row. Recording the routing fact is still the
    more useful of the two here, because it is the only record of it that survives the job sweep.

    `short_template` is the OPERATOR's request and is "auto" for most jobs; auto resolves through the
    very heuristic the script generator routes on (ep._is_simulation_short), so what gets recorded is
    what actually ran, not what was asked for. Long-form has no template switch — it is always the
    explainer beat map. Returns "" rather than raising: a missing join key must never fail a render
    that already succeeded."""
    try:
        fmt = ((result or {}).get("video_format") or getattr(request, "video_format", "") or "").strip()
        if fmt != "social":
            return "explainer"
        want = (getattr(request, "short_template", "") or "auto").strip().lower()
        if want in ("explainer", "simulation", "quiz"):
            return want
        import explainer_pipeline as ep
        return "simulation" if ep._is_simulation_short(getattr(request, "question", "") or "") else "explainer"
    except Exception:
        return ""


def _persist_finished(job_id: str, src_path: str, meta: dict, extra: dict | None = None) -> str:
    """Copy a finished video (+ optional transcript/srt) to the stable dir and index it.

    `meta` carries the JOIN KEY — question / template / video_format. Measured: of the 27 rows in the
    28-day Studio export, 0 could be traced back to the topic that produced them, because this index
    stored only the title and the job dirs holding the rest are swept at 14 days. Title matching is
    not a join (Studio titles pick up hashtags and emoji, and get edited after upload). The three keys
    are written empty rather than omitted when a caller has nothing, so "not recorded" is
    distinguishable from "never had one"; every entry written BEFORE this change simply lacks them,
    so readers must keep using .get()."""
    os.makedirs(FINISHED_DIR, exist_ok=True)
    dest = os.path.join(FINISHED_DIR, f"{job_id}.mp4")
    try:
        shutil.copy(src_path, dest)
        entry = {**meta, "path": dest}
        for k in ("question", "template", "video_format"):
            entry.setdefault(k, "")
        for ext, p in (extra or {}).items():   # e.g. {"txt": ..., "srt": ...}
            if p and os.path.exists(p):
                d = os.path.join(FINISHED_DIR, f"{job_id}.{ext}")
                shutil.copy(p, d)
                entry[f"{ext}_path"] = d
        with _INDEX_LOCK:
            index = {}
            if os.path.exists(_FINISHED_INDEX):
                with open(_FINISHED_INDEX) as f:
                    index = json.load(f)
            index[job_id] = entry
            _atomic_write_json(_FINISHED_INDEX, index)
    except OSError:
        return src_path
    return dest


def _load_finished(job_id: str) -> dict | None:
    """Look up a finished video by id from the on-disk index (survives reload)."""
    try:
        with open(_FINISHED_INDEX) as f:
            entry = json.load(f).get(job_id)
        if entry and os.path.exists(entry.get("path", "")):
            return entry
    except (OSError, ValueError):
        pass
    return None
# job schema:
# {
#   "id": str,
#   "status": "queued" | "running" | "done" | "error",
#   "events": [{"type": "stage"|"log"|"done"|"error", "data": str}],
#   "output_path": str | None,
#   "script": dict | None,
#   "error": str | None,
# }


# ─── Request / Response models ─────────────────────────────────────────────────

class BrandConfig(BaseModel):
    logo_url: Optional[str] = None
    primary_color: str = "#e63946"
    cta_text: Optional[str] = None
    font_name: str = "DejaVu-Sans-Bold"


class GenerateRequest(BaseModel):
    prompt: str
    duration_minutes: int = 3
    visual_mode: str = "both"           # "pexels" | "dalle" | "both" | "ai_video"
    voice_name: str = "en-US-Journey-D" # Google TTS voice name
    video_type: str = "explainer"       # "explainer" | "promo"
    script_mode: str = "generate"       # "generate" | "custom"
    custom_script: Optional[str] = None # voiceover text when script_mode="custom"
    brand_config: Optional[BrandConfig] = None


class GenerateResponse(BaseModel):
    job_id: str


# ─── Pipeline runner ────────────────────────────────────────────────────────────

async def run_pipeline(job_id: str, request: GenerateRequest):
    """Background task that runs the full pipeline and pushes events."""
    import pipeline as p

    job = jobs[job_id]

    def push(event_type: str, data: str):
        job["events"].append({"type": event_type, "data": data})

    try:
        job["status"] = "running"
        # Keep the working directory. tempfile.mkdtemp put it under /var/folders, where it was
        # destroyed on completion -- so a finished video could never be re-assembled, only
        # regenerated from scratch. That cost a $7.66 long-form re-render to fix a 3-second freeze,
        # and made an otherwise-good Short unsalvageable once its scene images were gone.
        # Scene images, per-scene audio and i2v clips are the expensive artifacts; keeping them makes
        # every later fix an ffmpeg operation instead of a re-buy.
        output_dir = os.path.join(JOBS_DIR, f"job_{job_id}")
        os.makedirs(output_dir, exist_ok=True)

        # ── Stage 1: Script ──────────────────────────────────────────────────
        if request.script_mode == "custom" and request.custom_script:
            push("stage", "Processing custom script with Claude...")
            script = await p.process_custom_script(request.custom_script, request.duration_minutes)
        else:
            push("stage", "Generating script with Claude...")
            script = await p.generate_script(
                request.prompt, request.duration_minutes, video_type=request.video_type
            )
        job["script"] = script
        push("log", f"Script ready: {len(script.get('scenes', []))} scenes — \"{script.get('title', '')}\"")

        scenes = script.get("scenes", [])

        # ── Stage 2: Audio ───────────────────────────────────────────────────
        push("stage", "Generating voiceover with Google Cloud TTS...")

        def audio_progress(msg: str):
            push("log", msg)

        audio_files = await p.generate_audio(scenes, output_dir, progress_cb=audio_progress)
        push("log", f"Audio complete — {len([a for a in audio_files if a])} files generated")

        # ── Stage 3: Visuals ─────────────────────────────────────────────────
        push("stage", f"Fetching visuals (mode: {request.visual_mode})...")

        def visual_progress(msg: str):
            push("log", msg)

        visual_files = await p.fetch_visuals(
            scenes, output_dir,
            mode=request.visual_mode,
            progress_cb=visual_progress,
            single_prompt=(request.prompt or script.get("title", "")),
        )
        push("log", f"Visuals complete — {len(visual_files)} acquired")

        # ── Stage 4: Assembly ────────────────────────────────────────────────
        push("stage", "Assembling final video...")

        def assembly_progress(msg: str):
            push("log", msg)

        output_path = os.path.join(output_dir, f"final_{job_id}.mp4")

        # Run blocking MoviePy work in a thread pool
        loop = asyncio.get_event_loop()
        brand_dict = request.brand_config.dict() if request.brand_config else None
        await loop.run_in_executor(
            None,
            lambda: p.assemble_video(
                script, audio_files, visual_files, output_path,
                assembly_progress, brand_config=brand_dict,
            )
        )

        job["output_path"] = output_path
        job["status"] = "done"
        push("done", f"Video ready! ({_human_size(os.path.getsize(output_path))})")

    except Exception as exc:
        import traceback
        err = traceback.format_exc()
        job["status"] = "error"
        job["error"] = str(exc)
        push("error", f"Pipeline failed: {exc}")
        push("error", err)


def _human_size(n: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# ─── Endpoints ──────────────────────────────────────────────────────────────────

@app.post("/api/generate", response_model=GenerateResponse)
async def generate(request: GenerateRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "id": job_id,
        "status": "queued",
        "events": [],
        "output_path": None,
        "script": None,
        "error": None,
        "prompt": request.prompt,
    }
    background_tasks.add_task(run_pipeline, job_id, request)
    return GenerateResponse(job_id=job_id)


@app.get("/api/status/{job_id}")
async def status_stream(job_id: str):
    """Server-Sent Events stream — push all buffered events then tail new ones."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        job = jobs[job_id]
        sent = 0
        while True:
            events = job["events"]
            while sent < len(events):
                ev = events[sent]
                yield f"data: {json.dumps(ev)}\n\n"
                sent += 1
            if job["status"] in ("done", "error"):
                break
            await asyncio.sleep(0.3)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/job/{job_id}")
async def get_job(job_id: str):
    """Get full job state (status, script, etc.)."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    return {
        "id": job["id"],
        "status": job["status"],
        "prompt": job.get("prompt"),
        "script": job.get("script"),
        "error": job.get("error"),
        "has_video": job.get("output_path") is not None and os.path.exists(job.get("output_path", "")),
    }


@app.get("/api/download/{job_id}")
async def download_video(job_id: str):
    """Download the generated MP4."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    if job["status"] != "done" or not job.get("output_path"):
        raise HTTPException(status_code=400, detail="Video not ready")
    path = job["output_path"]
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found on disk")
    title = job.get("script", {}).get("title", "video")
    safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=f"{safe_title}.mp4",
    )


@app.get("/api/script/{job_id}")
async def get_script(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    script = jobs[job_id].get("script")
    if not script:
        raise HTTPException(status_code=400, detail="Script not yet generated")
    return script


# ─── Highlights pipeline ────────────────────────────────────────────────────────

def _hl_overlay_kwargs(job: dict) -> dict:
    """Extract overlay keyword arguments from a stored job dict."""
    return {
        "score":             job.get("score", ""),
        "predicted_team":    job.get("predicted_team", ""),
        "prediction_result": job.get("prediction_result", ""),
        "win_probability":   job.get("win_probability", 68),
        "confidence":        job.get("confidence", "HIGH"),
        "model_accuracy":    job.get("model_accuracy", 61),
    }


async def run_hl_pipeline(job_id: str, video_path: str, output_dir: str,
                           max_clips: int, pre_sec: float, post_sec: float,
                           vertical: bool = True):
    import highlights as hl

    job = hl_jobs[job_id]
    job["status"] = "processing"

    def push(msg: str):
        if msg.startswith("stage:"):
            job["events"].append({"type": "stage", "data": msg[6:]})
        else:
            job["events"].append({"type": "log", "data": msg})

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: hl.run_highlights(
                video_path, output_dir,
                pre_sec=pre_sec, post_sec=post_sec,
                max_clips=max_clips,
                vertical=vertical,
                progress_cb=push,
                **_hl_overlay_kwargs(job),
            ),
        )
        job["clips"] = result["clips"]
        job["reel_path"] = result.get("reel_path")
        job["status"] = "done"
        n = len(result["clips"])
        job["events"].append({"type": "done", "data": f"{n} clip(s) + highlight reel ready"})
    except Exception as exc:
        import traceback
        job["status"] = "error"
        job["error"] = str(exc)
        job["events"].append({"type": "error", "data": f"Pipeline failed: {exc}"})
        job["events"].append({"type": "error", "data": traceback.format_exc()})


class HighlightsUrlRequest(BaseModel):
    url: str
    max_clips: int = 6
    pre_sec: float = 15.0
    post_sec: float = 20.0
    vertical: bool = True
    home_team: str = ""
    away_team: str = ""
    # Overlay fields
    score: str = ""
    predicted_team: str = ""
    prediction_result: str = ""   # "hit" | "missed" | ""
    win_probability: int = 68
    confidence: str = "HIGH"
    model_accuracy: int = 61


async def run_hl_pipeline_from_url(job_id: str, url: str, output_dir: str,
                                    max_clips: int, pre_sec: float, post_sec: float,
                                    vertical: bool = True):
    import highlights as hl

    job = hl_jobs[job_id]
    job["status"] = "processing"

    def push(msg: str):
        if msg.startswith("stage:"):
            job["events"].append({"type": "stage", "data": msg[6:]})
        else:
            job["events"].append({"type": "log", "data": msg})

    try:
        loop = asyncio.get_event_loop()

        push("stage:Downloading video...")
        video_path = await loop.run_in_executor(
            None,
            lambda: hl.download_youtube(url, output_dir, progress_cb=push),
        )
        job["video_path"] = video_path
        push(f"Download complete: {os.path.basename(video_path)}")

        result = await loop.run_in_executor(
            None,
            lambda: hl.run_highlights(
                video_path, output_dir,
                pre_sec=pre_sec, post_sec=post_sec,
                max_clips=max_clips,
                vertical=vertical,
                progress_cb=push,
                **_hl_overlay_kwargs(job),
            ),
        )
        job["clips"] = result["clips"]
        job["reel_path"] = result.get("reel_path")
        job["status"] = "done"
        n = len(result["clips"])
        job["events"].append({"type": "done", "data": f"{n} clip(s) + highlight reel ready"})

    except Exception as exc:
        import traceback
        job["status"] = "error"
        job["error"] = str(exc)
        job["events"].append({"type": "error", "data": f"Pipeline failed: {exc}"})
        job["events"].append({"type": "error", "data": traceback.format_exc()})


@app.post("/api/highlights/from-url")
async def highlights_from_url(request: HighlightsUrlRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())[:8]
    output_dir = tempfile.mkdtemp(prefix=f"hl_{job_id}_")

    hl_jobs[job_id] = {
        "id": job_id,
        "status": "queued",
        "events": [],
        "clips": [],
        "reel_path": None,
        "video_path": None,
        "output_dir": output_dir,
        "home_team": request.home_team,
        "away_team": request.away_team,
        "score": request.score,
        "predicted_team": request.predicted_team,
        "prediction_result": request.prediction_result,
        "win_probability": request.win_probability,
        "confidence": request.confidence,
        "model_accuracy": request.model_accuracy,
        "error": None,
    }
    background_tasks.add_task(
        run_hl_pipeline_from_url,
        job_id, request.url, output_dir,
        request.max_clips, request.pre_sec, request.post_sec, request.vertical,
    )
    return {"job_id": job_id}


@app.post("/api/highlights/upload")
async def highlights_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    max_clips: int = 6,
    pre_sec: float = 15.0,
    post_sec: float = 20.0,
    vertical: bool = True,
    home_team: str = "",
    away_team: str = "",
    score: str = "",
    predicted_team: str = "",
    prediction_result: str = "",
    win_probability: int = 68,
    confidence: str = "HIGH",
    model_accuracy: int = 61,
):
    job_id = str(uuid.uuid4())[:8]
    output_dir = tempfile.mkdtemp(prefix=f"hl_{job_id}_")
    ext = Path(file.filename).suffix if file.filename else ".mp4"
    video_path = os.path.join(output_dir, f"input{ext}")

    with open(video_path, "wb") as out:
        shutil.copyfileobj(file.file, out)

    hl_jobs[job_id] = {
        "id": job_id,
        "status": "queued",
        "events": [],
        "clips": [],
        "reel_path": None,
        "video_path": video_path,
        "output_dir": output_dir,
        "home_team": home_team,
        "away_team": away_team,
        "score": score,
        "predicted_team": predicted_team,
        "prediction_result": prediction_result,
        "win_probability": win_probability,
        "confidence": confidence,
        "model_accuracy": model_accuracy,
        "error": None,
    }
    background_tasks.add_task(run_hl_pipeline, job_id, video_path, output_dir,
                               max_clips, pre_sec, post_sec, vertical)
    return {"job_id": job_id}


@app.get("/api/highlights/status/{job_id}")
async def highlights_status_stream(job_id: str):
    if job_id not in hl_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        job = hl_jobs[job_id]
        sent = 0
        while True:
            events = job["events"]
            while sent < len(events):
                yield f"data: {json.dumps(events[sent])}\n\n"
                sent += 1
            if job["status"] in ("done", "error"):
                break
            await asyncio.sleep(0.3)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/highlights/clips/{job_id}")
async def get_highlight_clips(job_id: str):
    if job_id not in hl_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = hl_jobs[job_id]
    safe_clips = [
        {k: v for k, v in c.items() if k != "clip_path"}
        for c in job.get("clips", [])
    ]
    reel_path = job.get("reel_path")
    reel_available = bool(reel_path and os.path.exists(reel_path))
    return {"job_id": job_id, "status": job["status"], "clips": safe_clips,
            "reel_available": reel_available}


@app.get("/api/highlights/reel/{job_id}")
async def download_highlight_reel(job_id: str):
    if job_id not in hl_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    reel_path = hl_jobs[job_id].get("reel_path")
    if not reel_path or not os.path.exists(reel_path):
        raise HTTPException(status_code=404, detail="Reel not ready")
    prefix = _match_prefix(hl_jobs[job_id])
    fname = f"{prefix}_highlight_reel.mp4" if prefix else "highlight_reel.mp4"
    return FileResponse(reel_path, media_type="video/mp4", filename=fname)


def _match_prefix(job: dict) -> str:
    import re
    def clean(s): return re.sub(r'[^a-zA-Z0-9]', '_', s.strip()).strip('_')
    home = clean(job.get("home_team", ""))
    away = clean(job.get("away_team", ""))
    return f"{home}_vs_{away}" if home and away else ""


@app.get("/api/highlights/download/{job_id}/{index}")
async def download_highlight_clip(job_id: str, index: int):
    if job_id not in hl_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    clips = hl_jobs[job_id].get("clips", [])
    match = next((c for c in clips if c["index"] == index), None)
    if not match:
        raise HTTPException(status_code=404, detail="Clip not found")
    path = match["clip_path"]
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Clip file missing")
    prefix = _match_prefix(hl_jobs[job_id])
    fname = f"{prefix}_download_{index + 1:02d}.mp4" if prefix else match["filename"]
    return FileResponse(path, media_type="video/mp4", filename=fname)


# ─── Charts pipeline ────────────────────────────────────────────────────────────

class ChartsRequest(BaseModel):
    prompt: str


async def run_chart_task(job_id: str, prompt: str, output_dir: str):
    import charts_pipeline as cp

    job = chart_jobs[job_id]
    job["status"] = "processing"

    def push(msg: str):
        if msg.startswith("stage:"):
            job["events"].append({"type": "stage", "data": msg[6:]})
        else:
            job["events"].append({"type": "log", "data": msg})

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: cp.run_charts_pipeline(prompt, output_dir, progress_cb=push),
        )
        job.update(result)
        quality = result.get("status", "ok")
        reasons = result.get("degraded_reasons", [])
        job["status"] = "degraded" if quality == "degraded" else "done"
        if quality == "degraded":
            job["events"].append({"type": "error", "data": "⚠ DEGRADED — " + "; ".join(reasons)})
        # Honesty: AI-generated chart data is not an official source — prompt a human check.
        if str(result.get("provenance", "")).startswith("AI-generated"):
            job["events"].append({"type": "log", "data":
                "ℹ Data is AI-generated (not an official source) — verify the key numbers before publishing."})
        cost = result.get("cost_usd")
        deg = " (DEGRADED)" if quality == "degraded" else ""
        job["events"].append({"type": "done",
            "data": f"Video ready{deg}: {result['title']}" + (f" · ${cost}" if cost else "")})
    except Exception as exc:
        import traceback
        job["status"] = "error"
        job["error"] = str(exc)
        job["events"].append({"type": "error", "data": f"Failed: {exc}"})
        job["events"].append({"type": "error", "data": traceback.format_exc()})


@app.post("/api/charts/generate")
async def charts_generate(request: ChartsRequest, background_tasks: BackgroundTasks):
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is required")
    job_id = str(uuid.uuid4())[:8]
    output_dir = tempfile.mkdtemp(prefix=f"chart_{job_id}_")
    chart_jobs[job_id] = {
        "id": job_id, "status": "queued", "events": [],
        "video_path": None, "title": "",
        "youtube_title": "", "youtube_description": "",
        "youtube_tags": [], "annotations": [], "error": None,
    }
    background_tasks.add_task(run_chart_task, job_id, request.prompt, output_dir)
    return {"job_id": job_id}


@app.get("/api/charts/status/{job_id}")
async def charts_status_stream(job_id: str):
    if job_id not in chart_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    async def gen():
        job = chart_jobs[job_id]
        sent = 0
        while True:
            while sent < len(job["events"]):
                yield f"data: {json.dumps(job['events'][sent])}\n\n"
                sent += 1
            if job["status"] in ("done", "error", "degraded"):
                break
            await asyncio.sleep(0.3)

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/charts/thumbnail/{job_id}")
async def charts_thumbnail(job_id: str):
    if job_id not in chart_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = chart_jobs[job_id]
    path = job.get("thumbnail_path")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    title = job.get("title", "thumbnail")
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
    return FileResponse(path, media_type="image/jpeg", filename=f"{safe} - thumbnail.jpg")


@app.get("/api/charts/download/{job_id}")
async def charts_download(job_id: str):
    if job_id not in chart_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = chart_jobs[job_id]
    path = job.get("video_path")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=400, detail="Video not ready")
    title = job.get("title", "chart")
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
    return FileResponse(path, media_type="video/mp4", filename=f"{safe}.mp4")


@app.get("/api/charts/metadata/{job_id}")
async def charts_metadata(job_id: str):
    if job_id not in chart_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = chart_jobs[job_id]
    return {
        "title":               job.get("title"),
        "youtube_title":       job.get("youtube_title"),
        "youtube_description": job.get("youtube_description"),
        "youtube_tags":        job.get("youtube_tags"),
        "annotations":         job.get("annotations"),
        "provenance":          job.get("provenance"),
        "data_confidence":     job.get("data_confidence"),
        "coverage":            job.get("coverage"),
        "factcheck_notes":     job.get("factcheck_notes"),
        "cost_usd":            job.get("cost_usd"),
        "status":              job.get("status"),
        "degraded_reasons":    job.get("degraded_reasons"),
        "has_thumbnail":       bool(job.get("thumbnail_path")),
    }


# ─── Explainer pipeline ─────────────────────────────────────────────────────────

class ExplainerRequest(BaseModel):
    question: str
    duration_sec: int = 90
    voice: str = "echo"
    style: str = "engaging and scientific"
    image_guidance: str = ""   # optional theme/setting steer (e.g. "football", "yard work")
    fact_check: bool = True
    video_format: str = "landscape"   # "landscape" (16:9 YouTube) | "social" (9:16 + karaoke captions)
    speech_bubble: bool = False       # landscape only: Bolt "talks" via a synced phrase bubble
    motion: str = "standard"          # UI preset: none | standard | full
    max_cost_usd: float | None = None # was never sent, so every job silently used the $25 default
    i2v: bool | None = None           # image-to-video motion (Veo/Sora). None=default (social on,
                                      # long-form off); True/False forces it for ANY length
    series: str = ""                  # format-series mode: a recurring series name/pattern
    short_template: str = "auto"      # social only: "auto" (title heuristic) | "explainer"
                                      # (curiosity-gap mystery) | "simulation" (you-change escalation)
    story_format: str = ""
    n_items: int = 3                  # quiz template only: number of guess rounds (clamped 2-6)
    operator_direction: str = ""      # optional creative direction; enriches the script prompt,
                                      # subordinate to the format/structure/safety rules


async def run_explainer_task(job_id: str, request: ExplainerRequest, output_dir: str,
                             resume: bool = False):
    import explainer_pipeline as ep

    job = explainer_jobs[job_id]
    job["status"] = "processing"

    def push(msg: str):
        if msg.startswith("stage:"):
            job["events"].append({"type": "stage", "data": msg[6:]})
        else:
            job["events"].append({"type": "log", "data": msg})

    try:
        loop = asyncio.get_event_loop()
        # QUIZ template (social only): a different backend — Bolt hosts a "What is it?" guessing quiz.
        # The `question` field carries the CATEGORY (e.g. "animals"). Returns an explainer-shaped result.
        if request.video_format == "social" and request.short_template == "quiz":
            import quiz_pipeline as qp
            result = await loop.run_in_executor(
                None,
                lambda: qp.run_quiz_pipeline(
                    category=request.question, output_dir=output_dir,
                    n_items=max(2, min(6, request.n_items or 3)),
                    voice=request.voice, operator_direction=request.operator_direction, progress_cb=push),
            )
        else:
            result = await loop.run_in_executor(
                None,
                lambda: ep.run_explainer_pipeline(
                    question=request.question,
                    output_dir=output_dir,
                    duration_sec=request.duration_sec,
                    voice=request.voice,
                    style=request.style,
                    image_guidance=request.image_guidance,
                    fact_check=request.fact_check,
                    video_format=request.video_format,
                    speech_bubble=request.speech_bubble,
                    i2v=request.i2v,
                    motion=getattr(request, "motion", "standard"),
                    **({"max_cost_usd": request.max_cost_usd}
                       if getattr(request, "max_cost_usd", None) else {}),
                    series=request.series,
                    short_template=request.short_template,
                    operator_direction=request.operator_direction,
                    story_format=request.story_format,
                    resume=resume,
                    progress_cb=push,
                ),
            )
        quality = result.get("status", "ok")           # "ok" | "degraded"
        reasons = result.get("degraded_reasons", [])

        job.update({
            "status":      "degraded" if quality == "degraded" else "done",
            "quality":     quality,
            "output_path": result["output_path"],
            "script":      result["script"],
            "title":       result["title"],
            "hook":        result["hook"],
            "scene_count": result["scene_count"],
            "video_format": result.get("video_format"),
            "est_cost":    result.get("est_cost"),
            "actual_cost": result.get("actual_cost"),
            # The pipeline reports these two; the app used to discard them, which is why a run
            # that lost half its clips still looked like a success in the browser.
            "i2v_requested": result.get("i2v_requested", 0),
            "i2v_animated":  result.get("i2v_animated", 0),
            "dropped":     result.get("dropped", 0),
            "filler":      result.get("filler", 0),
            "duration_sec": result.get("duration_sec"),
            "degraded_reasons": reasons,
            "transcript_path": result.get("transcript_path"),
            "srt_path": result.get("srt_path"),
            "description_path": result.get("description_path"),
            "thumbnail_path": result.get("thumbnail_path"),
            "grade_path": result.get("grade_path"),
            "short_grade": result.get("short_grade"),
        })
        # Persist to the stable dir so a later reload can't orphan the video or its artifacts.
        try:
            _persist_finished(job_id, result["output_path"], {
                "title": result["title"], "status": job["status"],
                "scene_count": result["scene_count"], "actual_cost": result.get("actual_cost"),
                # The join key back to the topic engine. Without these three an imported Studio row
                # can only be matched on title, which matched 0 of 27 rows on the 28-day export.
                # (Quiz jobs put the CATEGORY in `question` — that is still the string the operator
                # picked the video from, so it is still the right key to store.)
                "question": request.question,
                "template": _effective_template(request, result),
                # The NARRATIVE structure, recorded separately from the routing lane. Long-form
                # always reports template="explainer", so without this an evidence-led render is
                # indistinguishable from a default one in the retention data and the A/B is
                # unmeasurable. Read off the script (what actually ran) before the request (what was
                # asked for), because the env var can override the request.
                "story_format": (result.get("script") or {}).get("_story_format")
                                or getattr(request, "story_format", "") or "",
                "video_format": result.get("video_format") or request.video_format,
            }, extra={"txt": result.get("transcript_path"), "srt": result.get("srt_path"),
                      "desc": result.get("description_path"), "thumb": result.get("thumbnail_path"),
                      "grade": result.get("grade_path")})
        except Exception:
            pass
        _clear_inprogress(job_id)   # job finished → drop from the resume index (no unbounded growth)
        # NOTE: topics are NOT auto-marked 'done' here on purpose — one topic may become BOTH a
        # long-form AND a short. The USER marks a topic done from the Topics dashboard (POST
        # /api/explainer/topic-status) when they're finished with it; only then is it excluded
        # from future curiosity-engine generation.

        # Compliance reminder: manual upload keeps a human on the disclosure checkbox.
        job["events"].append({"type": "log",
            "data": "ℹ Compliance: when you upload, tick 'Altered/synthetic content' in "
                    "YouTube Studio (or the platform's AI-content label) and set the audience."})

        cost = result.get("actual_cost")
        if quality == "degraded":
            job["events"].append({"type": "error",
                                  "data": "⚠ DEGRADED — " + "; ".join(reasons)})
            job["events"].append({"type": "done",
                                  "data": f"Video ready (DEGRADED): {result['title']} · ${cost}"})
        else:
            job["events"].append({"type": "done",
                                  "data": f"Video ready: {result['title']} · ${cost}"})
    except Exception as exc:
        import traceback
        job["status"] = "error"
        job["error"] = str(exc)
        job["events"].append({"type": "error", "data": f"Failed: {exc}"})
        job["events"].append({"type": "error", "data": traceback.format_exc()})


def _sweep_old_temp(prefix: str, max_age_hours: float = 6.0):
    """Best-effort: delete leftover temp dirs older than max_age_hours (bounds disk leak)."""
    import glob, time as _t
    root = tempfile.gettempdir()
    cutoff = _t.time() - max_age_hours * 3600
    for d in glob.glob(os.path.join(root, f"{prefix}*")):
        try:
            if os.path.isdir(d) and os.path.getmtime(d) < cutoff:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


# --- House of the Dragon pipeline (hotd/ package) --------------------------------------------
# The UI and the CLI call the same functions, so they cannot drift apart.
try:
    from hotd_api import mount as _mount_hotd
    _mount_hotd(app)
except Exception as _e:                      # the rest of the API must still start
    print(f"[hotd] endpoints unavailable: {type(_e).__name__}: {_e}")


@app.get("/api/explainer/config")
async def explainer_config():
    """Live i2v config of the RUNNING server — confirms .env actually took effect (no guessing
    whether a stale process is using an old provider chain)."""
    import explainer_pipeline as ep
    return {
        "i2v_provider_env": os.environ.get("I2V_PROVIDER", ""),
        "i2v_chain": ep._I2V_CHAIN,
        "veo_model": ep._VEO_MODEL,
        "sora_model": ep._SORA_MODEL,
        "i2v_rate_per_sec": ep._RATE_I2V_SEC,
        "max_i2v_clips": ep.MAX_I2V_CLIPS,
        "youtube_validation": ep.youtube_validation_active(),
        "script_gate_pass": ep._SCRIPT_GATE_PASS,
        "script_gate_retries": ep._SCRIPT_GATE_RETRIES,
    }


@app.get("/api/explainer/trending")
async def explainer_trending(background_tasks: BackgroundTasks):
    """Curiosity-gap question pool for the UI chips. Returns the cache; if it's empty (first run),
    kicks off a background refresh so it populates within ~15s without blocking this request."""
    data = _load_trending()
    if not data.get("questions"):
        background_tasks.add_task(_refresh_trending)
    return data


_LAST_MANUAL_REFRESH = [0.0]
_REFRESH_MIN_INTERVAL = float(os.environ.get("REFRESH_MIN_INTERVAL_SEC", "300"))


@app.post("/api/explainer/refresh-trending")
async def explainer_refresh_trending():
    """Regenerate the curiosity-gap pool for all channels now (manual trigger). Throttled: each
    refresh spends ~2040 YouTube quota units (2 channels × 10 topics), so ~5 unthrottled clicks
    would blow the default 10k/day. Min interval is REFRESH_MIN_INTERVAL_SEC (default 300s)."""
    import time
    now = time.monotonic()
    elapsed = now - _LAST_MANUAL_REFRESH[0]
    if _LAST_MANUAL_REFRESH[0] and elapsed < _REFRESH_MIN_INTERVAL:
        wait = int(_REFRESH_MIN_INTERVAL - elapsed)
        return {**_load_trending(), "throttled": True,
                "detail": f"Refresh throttled — try again in {wait}s "
                          f"(each refresh spends ~2040 YouTube quota units)."}
    _LAST_MANUAL_REFRESH[0] = now
    return _refresh_trending()


class TopicStatusRequest(BaseModel):
    channel: str = ""
    question: str
    status: str = "done"   # "done" excludes it from future generation; "new" un-marks it


def _patch_trending_status(channel: str, question: str, status: str) -> None:
    """Reflect a manual done/un-done in the cached pool immediately (atomic), so the dashboard shows
    it before the next refresh (after which a 'done' topic is excluded from generation entirely)."""
    with _TRENDING_LOCK:
        data = _load_trending()
        changed = False
        for q in data.get("questions", []):
            if q.get("question") == question and (not channel or q.get("channel") == channel):
                q["status"] = status; changed = True
        for grp in data.get("channels", []):
            if channel and grp.get("label") != channel:
                continue
            for q in grp.get("questions", []):
                if q.get("question") == question:
                    q["status"] = status; changed = True
        if changed:
            try:
                tmp = _TRENDING_FILE + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(data, f, indent=2)
                os.replace(tmp, _TRENDING_FILE)
            except OSError:
                pass


@app.post("/api/explainer/topic-status")
async def explainer_topic_status(req: TopicStatusRequest):
    """User marks a topic done (or 'new' to un-mark). Done topics are excluded from future
    curiosity-engine generation. MANUAL on purpose — one topic may become both a long-form and a
    short, so it's never auto-marked on render."""
    status = (req.status or "done").strip().lower()
    if status not in ("done", "new", "used", "published"):
        status = "done"
    ok = False
    try:
        import db
        if db.db_enabled():
            ok = db.mark_topic_status(req.channel, req.question, status)
    except Exception as e:
        print(f"[topic-status] db update failed: {e}")
    try:
        _patch_trending_status(req.channel, req.question, status)
    except Exception:
        pass
    return {"ok": ok, "status": status}


# ── Manual video metrics (real-audience feedback loop) ───────────────────────────────
_METRICS_FIELDS = ("slug", "title", "format", "template", "question", "published_at", "video_len_sec",
                   "views", "engaged_views", "stayed_pct", "avg_view_dur_sec", "subs_gained",
                   "watch_hours", "notes", "tags", "shown_in_feed", "feed_pct", "search_pct",
                   "impressions", "ctr")


class MetricsRequest(BaseModel):
    slug: str = ""
    title: str = ""
    format: str = ""            # landscape | social
    template: str = ""          # explainer | simulation | curiosity | ...
    question: str = ""
    published_at: str = ""      # YYYY-MM-DD
    video_len_sec: float | None = None
    views: int | None = None
    engaged_views: int | None = None
    stayed_pct: float | None = None        # % viewed vs swiped (Shorts)
    avg_view_dur_sec: float | None = None
    subs_gained: int | None = None
    watch_hours: float | None = None
    notes: str = ""
    tags: str = ""                          # comma tags actually used on the upload
    shown_in_feed: int | None = None        # Shorts feed impressions
    feed_pct: float | None = None           # % of traffic from the Shorts/browse feed
    search_pct: float | None = None         # % of traffic from YouTube search
    impressions: int | None = None          # long-form: thumbnail impressions
    ctr: float | None = None                # long-form: impressions click-through rate (%)
    tags: str = ""                         # the exact tags used (to test the tag→distribution theory)
    shown_in_feed: int | None = None       # YouTube "shown in feed" (impressions into the Shorts feed)
    feed_pct: float | None = None          # % of views from the Shorts feed
    search_pct: float | None = None        # % of views from YouTube search


def _metrics_json_load() -> list:
    try:
        with open(_METRICS_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def _metrics_json_upsert(row: dict) -> None:
    """Mirror a row into the local JSON store (dedup on slug), atomically."""
    rows = [r for r in _metrics_json_load() if r.get("slug") != row.get("slug")]
    rows.append(row)
    rows.sort(key=lambda r: (r.get("published_at") or "", r.get("slug") or ""), reverse=True)
    tmp = _METRICS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(rows, f, indent=1, default=str)
    os.replace(tmp, _METRICS_FILE)


@app.post("/api/metrics/save")
async def metrics_save(req: MetricsRequest):
    """Log/update one published video's real stats. Keyed on slug (falls back to the title)."""
    row = {k: getattr(req, k) for k in _METRICS_FIELDS}
    row["slug"] = (req.slug or req.title or "").strip()
    if not row["slug"]:
        return {"ok": False, "error": "slug or title required"}
    # blank strings → None so numeric columns stay clean
    for k in ("video_len_sec", "views", "engaged_views", "stayed_pct", "avg_view_dur_sec",
              "subs_gained", "watch_hours", "published_at", "shown_in_feed", "feed_pct", "search_pct",
              "impressions", "ctr"):
        if row.get(k) == "":
            row[k] = None                  # blank → NULL (esp. the date column, which rejects "")
    db_ok = False
    try:
        import db
        if db.db_enabled():
            db_ok = db.metrics_upsert(row)
    except Exception as e:
        print(f"[metrics] db upsert failed: {e}")
    try:
        _metrics_json_upsert(row)          # always mirror locally (durable + no-DB fallback)
    except Exception as e:
        print(f"[metrics] json mirror failed: {e}")
    return {"ok": True, "db": db_ok}


@app.post("/api/metrics/import-csv")
async def metrics_import_csv(file: UploadFile = File(...)):
    """Ingest a YouTube Studio CSV export into `video_metrics`.

    Hand-entry was the only path before this, which is why the table held 4 rows while the channel
    had 27 videos -- and why topic generation had no performance signal at all. Reports matched and
    unmatched rows rather than failing quietly on a title mismatch."""
    import metrics_import
    raw = await file.read()
    tmp = os.path.join(JOBS_DIR, f"_metrics_{int(time.time())}.csv")
    os.makedirs(JOBS_DIR, exist_ok=True)
    with open(tmp, "wb") as fh:
        fh.write(raw)
    try:
        rep = metrics_import.run(tmp)
        for r in rep["rows"]:                       # mirror locally so a DB outage is not data loss
            try:
                _metrics_json_upsert({k: v for k, v in r.items() if not k.startswith("_")})
            except Exception:
                pass
        return {"ok": True, "parsed": rep["parsed"], "saved": rep["saved"],
                "topic_matched": rep["rows_enriched"], "topic_inferred": rep["unmatched_to_job"],
                "summary": rep["summary"], "failed": rep["failed"][:10]}
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


@app.get("/api/metrics/list")
async def metrics_list():
    """All logged videos + derived rates (percent-viewed, sub-rate). DB is source of truth; falls
    back to the local JSON mirror when the DB is empty/unavailable."""
    rows = []
    try:
        import db
        if db.db_enabled():
            rows = db.metrics_all()
    except Exception as e:
        print(f"[metrics] db list failed: {e}")
    if not rows:
        rows = _metrics_json_load()

    def _num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None
    for r in rows:
        ln, avd, views, subs = _num(r.get("video_len_sec")), _num(r.get("avg_view_dur_sec")), \
            _num(r.get("views")), _num(r.get("subs_gained"))
        r["pct_viewed"] = round(100 * avd / ln, 1) if (ln and avd) else None
        r["sub_rate_pct"] = round(100 * subs / views, 2) if (views and subs is not None) else None
    return {"videos": rows, "count": len(rows)}


class DescPreviewRequest(BaseModel):
    question: str = ""
    video_format: str = "landscape"     # landscape | social


class EstimateRequest(BaseModel):
    duration_sec: int = 90
    video_format: str = "landscape"
    motion: str = "standard"


@app.post("/api/explainer/estimate")
async def explainer_estimate(req: EstimateRequest):
    """Price a job WITHOUT running it. No network, no script, no spend.

    Honest limitation: an exact figure needs the scene count, which needs the script, which costs
    money. Before the script exists the scene count is approximated from duration using measured
    seconds-per-scene, so the number is labelled approximate. The exact estimate still appears in
    the run log once the script lands.
    """
    import explainer_pipeline as ep
    per = ep.SECS_PER_SCENE.get(req.video_format, 8.5)
    n_scenes = max(1, round(req.duration_sec / per))
    motion_est = ep.estimate_i2v_cost(n_scenes, req.video_format, req.motion)
    base = ep.estimate_cost(n_scenes, n_scenes // 2, req.duration_sec * 16)  # ~16 chars/s of speech
    return {
        "scenes_approx": n_scenes,
        "clips": motion_est["clips"],
        "motion_usd": motion_est["usd"],
        "base_usd": round(base, 2),
        "total_usd": round(base + motion_est["usd"], 2),
        "note": "approximate until the script is written",
    }


@app.post("/api/explainer/preview-description")
async def explainer_preview_description(req: DescPreviewRequest):
    """Generate an SEO description + architecture tags for a topic WITHOUT rendering a video."""
    q = (req.question or "").strip()
    if not q:
        return {"ok": False, "error": "topic required"}
    fmt = "social" if req.video_format == "social" else "landscape"

    def _gen():
        import explainer_pipeline as ep
        d = tempfile.mkdtemp()
        stub = f"{q}. An explainer video that answers: {q}"
        path = ep.generate_description(q, q, stub, d, question=q, video_format=fmt)
        text = open(path).read().strip()
        tags = []
        for line in text.splitlines():
            if line.startswith("Tags:"):
                tags = [t.strip() for t in line[5:].split(",") if t.strip()]
                break
        return text, tags

    try:
        # offload the blocking Claude call so it doesn't stall the event loop
        text, tags = await asyncio.get_event_loop().run_in_executor(None, _gen)
        return {"ok": True, "description": text, "tags": tags}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.on_event("startup")
def _start_trending_scheduler():
    """Built-in 12-hour 'cron': seed the trending pool on boot if empty, then refresh every 12h for
    as long as the server runs (no external crontab needed; survives across reloads)."""
    import threading, time

    def _loop():
        if not _load_trending().get("questions"):
            try:
                _refresh_trending()
            except Exception:
                pass
        while True:
            time.sleep(12 * 3600)
            try:
                _refresh_trending()
            except Exception:
                pass

    threading.Thread(target=_loop, daemon=True).start()


@app.post("/api/explainer/generate")
async def explainer_generate(request: ExplainerRequest, background_tasks: BackgroundTasks):
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question is required")
    job_id = str(uuid.uuid4())[:8]
    # Persisted, not tempfile. This is the path BOTH the explainer and the quiz use, so a killed or
    # finished job keeps its scene images, per-scene audio and i2v clips -- the expensive artifacts.
    # Losing them is what turned a 3-second fix into a $7.66 regeneration and made a stuck quiz
    # unrecoverable. _sweep_old_jobs() below reclaims disk instead of tempfile's cleanup.
    output_dir = os.path.join(JOBS_DIR, f"expl_{job_id}")
    os.makedirs(output_dir, exist_ok=True)
    _sweep_old_jobs()
    explainer_jobs[job_id] = {
        "id": job_id, "status": "queued", "events": [],
        "output_path": None, "script": None,
        "title": "", "hook": "", "scene_count": 0, "error": None,
    }
    _record_inprogress(job_id, output_dir, request)   # so a crash/reload can be resumed
    background_tasks.add_task(run_explainer_task, job_id, request, output_dir)
    return {"job_id": job_id}


@app.post("/api/explainer/resume/{job_id}")
async def explainer_resume(job_id: str, background_tasks: BackgroundTasks):
    """Resume a job that died mid-render — reuses the on-disk script + already-paid scene
    images/audio from its checkpoint, regenerating only what's missing."""
    rec = _get_inprogress(job_id)
    if not rec or not os.path.isdir(rec.get("output_dir", "")):
        raise HTTPException(status_code=404,
                            detail="No resumable checkpoint for this job (missing or expired).")
    if not os.path.exists(os.path.join(rec["output_dir"], "_state.json")):
        raise HTTPException(status_code=409,
                            detail="Checkpoint has no saved script yet — nothing to resume; start fresh.")
    request = ExplainerRequest(**rec["request"])
    explainer_jobs[job_id] = {
        "id": job_id, "status": "queued", "events": [],
        "output_path": None, "script": None,
        "title": "", "hook": "", "scene_count": 0, "error": None,
    }
    background_tasks.add_task(run_explainer_task, job_id, request, rec["output_dir"], True)
    return {"job_id": job_id, "resuming": True}


@app.get("/api/explainer/status/{job_id}")
async def explainer_status_stream(job_id: str):
    if job_id not in explainer_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    async def gen():
        job = explainer_jobs[job_id]
        sent = 0
        ticks = 0
        while True:
            while sent < len(job["events"]):
                yield f"data: {json.dumps(job['events'][sent])}\n\n"
                sent += 1
            if job["status"] in ("done", "error", "degraded"):
                break
            # Heartbeat every ~3s of quiet so the browser detects a dead connection
            # and auto-reconnects (replaying buffered events) instead of freezing.
            ticks += 1
            if ticks % 10 == 0:
                yield ": keepalive\n\n"
            await asyncio.sleep(0.3)

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/explainer/download/{job_id}")
async def explainer_download(job_id: str):
    job = explainer_jobs.get(job_id)
    if job and job.get("output_path") and os.path.exists(job["output_path"]):
        path, title = job["output_path"], job.get("title", "explainer")
    else:
        # Fall back to the on-disk index (job may have been wiped by a reload).
        entry = _load_finished(job_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Job not found")
        path, title = entry["path"], entry.get("title", "explainer")
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
    return FileResponse(path, media_type="video/mp4", filename=f"{safe}.mp4")


# ─── State Board (standalone recap format) ────────────────────────────────────────
class StateBoardRequest(BaseModel):
    topic: str                     # video title / topic (drives title card + extractor context)
    script: str                    # pasted narration; chapters separated by a blank line
    voice: str = "onyx"            # OpenAI TTS voice
    subtitle: str = ""             # optional kicker line on the title card


async def run_stateboard_task(job_id: str, request: StateBoardRequest, output_dir: str):
    import stateboard_pipeline as sbp
    job = stateboard_jobs[job_id]
    job["status"] = "processing"

    def push(msg: str):
        if msg.startswith("stage:"):
            job["events"].append({"type": "stage", "data": msg[6:]})
        else:
            job["events"].append({"type": "log", "data": msg})

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: sbp.run_stateboard_pipeline(
                topic=request.topic, script_text=request.script,
                output_dir=output_dir, voice=request.voice,
                subtitle=request.subtitle, progress_cb=push),
        )
        job.update({
            "status": "degraded" if result.get("status") == "degraded" else "done",
            "output_path": result["output_path"], "title": result.get("title", request.topic),
            "chapters": result.get("chapters"), "duration_sec": result.get("duration_sec"),
            "thumbnail_path": result.get("thumbnail_path"),
            "degraded_reasons": result.get("degraded_reasons", []),
        })
        job["events"].append({"type": "done", "data": "complete"})
    except Exception as e:
        job["status"] = "error"; job["error"] = str(e)
        job["events"].append({"type": "error", "data": str(e)})


@app.post("/api/stateboard/generate")
async def stateboard_generate(request: StateBoardRequest, background_tasks: BackgroundTasks):
    if not request.topic.strip() or not request.script.strip():
        raise HTTPException(status_code=400, detail="topic and script are required")
    _sweep_old_temp("sb_")
    job_id = str(uuid.uuid4())[:8]
    output_dir = tempfile.mkdtemp(prefix=f"sb_{job_id}_")
    stateboard_jobs[job_id] = {"id": job_id, "status": "queued", "events": [],
                               "output_path": None, "title": "", "error": None}
    background_tasks.add_task(run_stateboard_task, job_id, request, output_dir)
    return {"job_id": job_id}


@app.get("/api/stateboard/status/{job_id}")
async def stateboard_status_stream(job_id: str):
    if job_id not in stateboard_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    async def gen():
        job = stateboard_jobs[job_id]; sent = 0; ticks = 0
        while True:
            while sent < len(job["events"]):
                yield f"data: {json.dumps(job['events'][sent])}\n\n"; sent += 1
            if job["status"] in ("done", "error", "degraded"):
                break
            ticks += 1
            if ticks % 10 == 0:
                yield ": keepalive\n\n"
            await asyncio.sleep(0.3)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/stateboard/download/{job_id}")
async def stateboard_download(job_id: str):
    job = stateboard_jobs.get(job_id)
    if not job or not job.get("output_path") or not os.path.exists(job["output_path"]):
        raise HTTPException(status_code=404, detail="Job not found")
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in job.get("title", "stateboard"))
    return FileResponse(job["output_path"], media_type="video/mp4", filename=f"{safe}.mp4")


@app.get("/api/stateboard/thumbnail/{job_id}")
async def stateboard_thumbnail(job_id: str):
    job = stateboard_jobs.get(job_id)
    if not job or not job.get("thumbnail_path") or not os.path.exists(job["thumbnail_path"]):
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(job["thumbnail_path"], media_type="image/jpeg")


def _explainer_text_artifact(job_id: str, kind: str):
    """Resolve a transcript ('txt'), captions ('srt'), description ('desc') or grade path."""
    job_key = {"txt": "transcript_path", "srt": "srt_path", "desc": "description_path",
               "grade": "grade_path"}[kind]
    job = explainer_jobs.get(job_id)
    if job and job.get(job_key) and os.path.exists(job[job_key]):
        return job[job_key], job.get("title", "explainer")
    entry = _load_finished(job_id)
    if entry and entry.get(f"{kind}_path") and os.path.exists(entry[f"{kind}_path"]):
        return entry[f"{kind}_path"], entry.get("title", "explainer")
    return None, None


@app.get("/api/explainer/transcript/{job_id}")
async def explainer_transcript(job_id: str):
    path, title = _explainer_text_artifact(job_id, "txt")
    if not path:
        raise HTTPException(status_code=404, detail="Transcript not found")
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
    return FileResponse(path, media_type="text/plain", filename=f"{safe} - transcript.txt")


@app.get("/api/explainer/captions/{job_id}")
async def explainer_captions(job_id: str):
    path, title = _explainer_text_artifact(job_id, "srt")
    if not path:
        raise HTTPException(status_code=404, detail="Captions not found")
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
    return FileResponse(path, media_type="application/x-subrip", filename=f"{safe}.srt")


@app.get("/api/explainer/description/{job_id}")
async def explainer_description(job_id: str):
    path, title = _explainer_text_artifact(job_id, "desc")
    if not path:
        raise HTTPException(status_code=404, detail="Description not found")
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
    return FileResponse(path, media_type="text/plain", filename=f"{safe} - description.txt")


@app.get("/api/explainer/grade/{job_id}")
async def explainer_grade(job_id: str):
    path, title = _explainer_text_artifact(job_id, "grade")
    if not path:
        raise HTTPException(status_code=404, detail="Grade not found (social shorts only)")
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
    return FileResponse(path, media_type="text/plain", filename=f"{safe} - grade.txt")


@app.get("/api/explainer/thumbnail/{job_id}")
async def explainer_thumbnail(job_id: str):
    job = explainer_jobs.get(job_id)
    path = title = None
    if job and job.get("thumbnail_path") and os.path.exists(job["thumbnail_path"]):
        path, title = job["thumbnail_path"], job.get("title", "thumbnail")
    else:
        entry = _load_finished(job_id)
        if entry and entry.get("thumb_path") and os.path.exists(entry["thumb_path"]):
            path, title = entry["thumb_path"], entry.get("title", "thumbnail")
    if not path:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
    return FileResponse(path, media_type="image/jpeg", filename=f"{safe} - thumbnail.jpg")


@app.get("/api/explainer/script/{job_id}")
async def explainer_script(job_id: str):
    if job_id not in explainer_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = explainer_jobs[job_id]
    script = job.get("script")
    if not script:
        raise HTTPException(status_code=400, detail="Script not yet generated")
    # Attach what actually happened to the motion budget. Without this the browser has no way to
    # tell a fully-animated render from one that lost every clip -- both looked like success.
    out = dict(script) if isinstance(script, dict) else {"scenes": script}
    out["i2v_requested"] = job.get("i2v_requested", 0)
    out["i2v_animated"] = job.get("i2v_animated", 0)
    out["actual_cost"] = job.get("actual_cost")
    out["quality"] = job.get("quality")
    return out


# ─── Serve frontend ─────────────────────────────────────────────────────────────

@app.get("/")
def _serve_index():
    # Serve the SPA shell with no-cache so a browser never shows a stale UI after an
    # edit (a cached index.html made a newly-added form field look "removed"). Other
    # static assets below keep normal caching. Registered before the mount so it wins for "/".
    resp = FileResponse("static/index.html", media_type="text/html")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


# Mounted BEFORE the static catch-all: `app.mount("/")` swallows every unmatched route, so any
# router added after it is unreachable.
try:
    import finished_api
    finished_api.mount(app)
except Exception as _e:
    print(f"finished_api not mounted: {type(_e).__name__}: {_e}")

app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    # Defaults: localhost-only (not 0.0.0.0) so an un-firewalled box isn't an open wallet, and
    # reload ON (dev convenience). For real renders run `RELOAD=0 python app.py` — reload=True
    # SIGTERMs the worker on any .py save and KILLS an in-flight render. To expose the server,
    # set HOST=0.0.0.0 AND APP_SHARED_SECRET (the warning below fires if you forget).
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    reload = os.environ.get("RELOAD", "1") == "1"
    if host not in ("127.0.0.1", "localhost", "::1") and not APP_SHARED_SECRET:
        print("⚠ SECURITY: binding to a non-loopback host with NO APP_SHARED_SECRET — anyone who "
              "can reach this port can spend your Anthropic/OpenAI/Veo credits. Set APP_SHARED_SECRET.")
    if reload:
        print("⚠ RELOAD=1: editing any .py during a render will KILL it. Use RELOAD=0 for real runs.")
    uvicorn.run("app:app", host=host, port=port, reload=reload)
