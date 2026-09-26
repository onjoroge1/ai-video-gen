Warning: truncated output (original token count: 60224)
Total output lines: 4855

"""
FastAPI backend for the YouTube Video Generation Pipeline.
Exposes:
  POST /api/generate        — start a generation job
  GET  /api/status/{job_id} — SSE stream of progress events
  GET  /api/download/{job_id} — download the final MP4
  GET  /api/script/{job_id}   — get the generated script JSON
"""

import os
from dotenv import load_dotenv
load_dotenv(override=True)   # override so .env edits (e.g. I2V_PROVIDER) reliably take on reload
import uuid
import asyncio
import html
import json
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException, File, UploadFile, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse, RedirectResponse, Response
from starlette.background import BackgroundTask
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import artifact_store
import media_binaries
import private_access
import durable_execution
import agent_actions

app = FastAPI(title="YouTube Pipeline API")

BASE_DIR = Path(__file__).resolve().parent
IS_VERCEL = bool(os.environ.get("VERCEL"))
STATIC_DIR = BASE_DIR / "static"


@app.get("/api/formats")
async def format_catalog():
    """Phase-1 format discovery contract for UI and future workers."""
    from bolt_video.core.registry import list_formats
    return {"formats": list_formats()}

# Signed HttpOnly-cookie auth protects the entire UI and every API route in production.  Existing
# X-App-Secret clients remain compatible, but browsers no longer store a credential in localStorage.
APP_SHARED_SECRET = os.environ.get("APP_SHARED_SECRET", "").strip()


# CORS: default to localhost only (a wildcard let any site a browser visits POST here). Override
# with ALLOWED_ORIGINS (comma list; "*" to truly open for dev).
_ALLOWED_ORIGINS = [o.strip() for o in os.environ.get(
    "ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",") if o.strip()]

# Order matters (Starlette wraps last-added = OUTERMOST): add auth FIRST (inner), CORS LAST so CORS
# stays outermost and even a 401 carries CORS headers (a cross-origin client can read the error).
app.add_middleware(private_access.PrivateAccessMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

private_access.mount_auth_routes(app, STATIC_DIR)


def _require_render_storage() -> None:
    try:
        artifact_store.assert_ready()
    except artifact_store.ArtifactPersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/production-readiness")
async def production_readiness():
    from provider_readiness import illustrated_provider_readiness

    storage = artifact_store.readiness()
    # A render spends real money on script, image, motion, and narration calls long before
    # its first encode, so a host that cannot run ffmpeg must be visible here rather than
    # after the spend.
    media = media_binaries.preflight()
    illustrated = illustrated_provider_readiness()
    checks = {
        "media_binaries": media["ready"],
        "private_access": private_access.auth_configured(),
        "durable_artifacts": storage["ready"],
        "database": storage["database"],
        "blob": storage["blob"],
        "youtube_validation": bool(os.environ.get("YOUTUBE_API_KEY", "").strip()),
        "fal_i2v": bool(os.environ.get("FAL_KEY", "").strip())
                   and os.environ.get("I2V_PROVIDER", "").strip().lower() == "fal",
        "durable_execution": (not _durable_execution_required()) or
                             (storage["blob"] and storage["database"]),
        "worker_auth": (not _durable_execution_required()) or bool(
            os.environ.get("CRON_SECRET", "").strip()
            or os.environ.get("RENDER_WORKER_SECRET", "").strip()),
        "illustrated_providers": illustrated["configured"],
    }
    infrastructure_ready = all((checks["private_access"], checks["durable_artifacts"],
                                checks["durable_execution"], checks["worker_auth"],
                                checks["media_binaries"]))
    return {"ready": infrastructure_ready and illustrated["configured"],
            "infrastructure_ready": infrastructure_ready,
            "readiness_scope": "configuration_only",
            "generation_verified": False,
            "checks": checks, "media": media,
            "providers": {"illustrated": illustrated}}

# ─── State store (in-memory; use Redis for production) ─────────────────────────

jobs: dict[str, dict] = {}
hl_jobs: dict[str, dict] = {}
chart_jobs: dict[str, dict] = {}
explainer_jobs: dict[str, dict] = {}
stateboard_jobs: dict[str, dict] = {}


def _durable_execution_required() -> bool:
    configured = os.environ.get("DURABLE_EXECUTION")
    if configured is not None:
        return configured.strip().lower() not in ("0", "false", "no", "off")
    return IS_VERCEL


def _durable_components():
    try:
        return durable_execution.PostgresStore(), durable_execution.BlobStore()
    except durable_execution.StorageUnavailable:
        raise
    except Exception as exc:
        raise durable_execution.StorageUnavailable(str(exc)) from exc


def _durable_job_view(row: dict) -> dict:
    result = row.get("result") or {}
    return {
        "id": row["id"], "status": row.get("status"), "events": [],
        "error": row.get("error"), "output_path": None,
        "script": result.get("script"), "title": result.get("title", ""),
        "hook": result.get("hook", ""), "scene_count": result.get("scene_count", 0),
        "actual_cost": row.get("spent_cost_usd"), "max_cost_usd": row.get("max_cost_usd"),
        "attempts": row.get("attempts"), "checkpoint": row.get("checkpoint") or {},
        **{key: value for key, value in result.items() if key not in {"events"}},
    }

# Finished explainer videos are copied here with a small index, so a dev-server reload (which wipes
# the in-memory job store) can't orphan a completed video. Vercel's deployment bundle is read-only;
# /tmp is writable but ephemeral, so durable production artifacts must ultimately live in object
# storage + Postgres rather than this compatibility path.
_default_data_dir = (Path(tempfile.gettempdir()) / "reelforge" / "finished_videos"
                     if IS_VERCEL else BASE_DIR / "finished_videos")
FINISHED_DIR = os.environ.get("REELFORGE_DATA_DIR", str(_default_data_dir))
_FINISHED_INDEX = os.path.join(FINISHED_DIR, "index.json")

# Curiosity-gap "trending questions" cache — populated by the topic engine (manually, on startup,
# or by a cron hitting /api/explainer/refresh-trending) and served to the UI's chips.
_TRENDING_FILE = os.path.join(FINISHED_DIR, "trending_questions.json")
# Manual per-video metrics — the real-audience feedback loop. Persisted to Neon (db.video_metrics)
# AND mirrored to this local JSON so it survives a DB outage and works even with no DATABASE_URL.
_METRICS_FILE = os.path.join(FINISHED_DIR, "video_metrics.json")
import threading
_TRENDING_LOCK = threading.Lock()   # serialize the 3 callers (scheduler / GET auto-seed / manual POST)

TOPICS_PER_FORMAT = max(2, min(8, int(os.environ.get("TOPICS_PER_FORMAT", "4"))))

# One editorial definition for topic research, screening, and the UI.
import topic_fit as _topic_fit
CHANNELS = [{"label": spec["name"], "topic_channel": key,
             "niche": spec["promise"] + " " + spec["requires"]}
            for key, spec in _topic_fit.CHANNELS.items()]


def _current_topic_cache(cached) -> bool:
    return (isinstance(cached, dict) and cached.get("roi_version") == 2
            and cached.get("editorial_version") == _topic_fit.EDITORIAL_VERSION
            and all(group.get("label") in {c["label"] for c in CHANNELS}
                    for group in cached.get("channels", [])))


def _load_trending() -> dict:
    try:
        with open(_TRENDING_FILE) as f:
            cached = json.load(f)
        if _current_topic_cache(cached):
            return cached
    except Exception:
        pass
    try:
        import db
        cached = db.cache_get("topic_roi_v2") if db.db_enabled() else None
        if _current_topic_cache(cached):
            return cached
    except Exception:
        pass
    return {"questions": [], "channels": [], "generated_at": None, "roi_version": 2,
            "editorial_version": _topic_fit.EDITORIAL_VERSION}


def _refresh_trending() -> dict:
    """Regenerate curiosity-gap topics for every channel, market-validate them, and cache.
    Blocking (~10-15s/channel Claude call + YouTube). Coalesced (a second concurrent caller
    returns the current cache instead of double-spending quota) and written atomically so the
    3 callers can't corrupt the file. Never overwrites a good cache with an empty result, and
    never overwrites a previously-validated cache with a TOTAL validation failure (quota/network)."""
    import datetime
    import explainer_pipeline as ep
    import topic_roi
    if not _TRENDING_LOCK.acquire(blocking=False):
        print("[trending] refresh already in progress — returning current cache")
        return _load_trending()
    try:
        try:
            import db
            audience_metrics = db.metrics_all() if db.db_enabled() else _metrics_json_load()
        except Exception:
            audience_metrics = _metrics_json_load()

        groups = []
        for channel in CHANNELS:
            exclude = []
            try:
                import db
                if db.db_enabled():
                    exclude = db.used_questions(channel["label"])
            except Exception as exc:
                print(f"[trending] used-topic exclusion skipped for {channel['label']}: {exc}")

            channel_topics = []
            # The illustrated route currently supports landscape only. Vertical adaptations
            # need their own delivery verification before the topic UI offers them as renders.
            for content_format in ("long",):
                # A causal channel proposes through the screened generator, so every topic that
                # reaches the operator has already survived the check the pipeline applies before
                # buying research. A topic suggested here and refused there is the UI arguing with
                # its own back end.
                if channel.get("topic_channel"):
                    topics = ep.generate_causal_topics(
                        channel=channel["topic_channel"], n=TOPICS_PER_FORMAT, avoid=exclude)
                else:
                    topics = ep.generate_curiosity_topics(
                        niche=channel["niche"], n=TOPICS_PER_FORMAT,
                        exclude=exclude, content_format=content_format,
                    )
                for topic in topics:
                    topic["channel"] = channel["label"]
                    topic["topic_channel"] = channel["topic_channel"]
                    topic["visual_style"] = "illustrated_story"
                    topic["content_format"] = content_format
                    topic["status"] = "research_candidate"
                try:
                    topics = ep.validate_topics_youtube(
                        topics, content_format=content_format, metrics=audience_metrics)
                except Exception as exc:
                    print(f"[trending] validation skipped for {channel['label']}/{content_format}: {exc}")
                try:
                    topics = ep.suggest_titles(topics)
                except Exception as exc:
                    print(f"[trending] title reframe skipped for {channel['label']}/{content_format}: {exc}")
                channel_topics.extend(topics)
            groups.append({"label": channel["label"], "niche": channel["niche"],
                           "questions": channel_topics})

        # One idea often fits multiple science lanes. Keep the version with the strongest evidence.
        groups = topic_roi.dedupe_topic_groups(groups)
        for group in groups:
            try:
                import db
                if db.db_enabled():
                    written = db.upsert_topics(group["label"], group["questions"])
                    if written:
                        print(f"[trending] stored {written} topics for {group['label']}")
            except Exception as exc:
                print(f"[trending] db store skipped for {group['label']}: {exc}")

        # User-pinned topics survive refreshes, but still pass through global duplicate removal.
        try:
            import db
            if db.db_enabled():
                for group in groups:
                    pinned = db.queued_topics(group["label"])
                    have = {t.get("question", "").strip().lower() for t in group["questions"]}
                    fresh = [t for t in pinned if t.get("question", "").strip().lower() not in have]
                    for topic in fresh:
                        topic["channel"] = group["label"]
                        topic.setdefault("content_format", "long")
                    group["questions"] = fresh + group["questions"]
        except Exception as exc:
            print(f"[trending] queued merge skipped: {exc}")

        groups = topic_roi.dedupe_topic_groups(groups)
        flat = [topic for group in groups for topic in group.get("questions", [])]
        validated_count = sum(1 for topic in flat if topic.get("validated"))
        payload = {
            "questions": flat, "channels": groups,
            "validated": validated_count > 0,
            "validation_active": ep.youtube_validation_active(),
            "validated_count": validated_count, "total_topics": len(flat),
            "roi_version": 2, "formats": ["long"],
            "editorial_version": _topic_fit.EDITORIAL_VERSION,
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        if flat and ep.youtube_validation_active() and validated_count == 0:
            prior = _load_trending()
            if prior.get("validated_count", 0) > 0:
                print(f"[trending] validation produced 0/{len(flat)} — keeping prior cache")
                return prior
        if flat:
            os.makedirs(FINISHED_DIR, exist_ok=True)
            try:
                tmp = _TRENDING_FILE + ".tmp"
                with open(tmp, "w") as stream:
                    json.dump(payload, stream, indent=2)
                os.replace(tmp, _TRENDING_FILE)
            except OSError:
                pass
            try:
                import db
                if db.db_enabled():
                    db.cache_set("topic_roi_v2", payload)
            except Exception as exc:
                print(f"[trending] durable cache skipped: {exc}")
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


# The Finished Videos library groups on one string. Quizzes have always had their own
# ("short-quiz"); the illustrated lane borrowed "explainer" and disappeared into it. This is the
# lane's label. One hand-imported legacy row in the library says "illustrated-causal-longform" —
# static/finished.html folds that spelling into the same lane so the library is not split in two.
ILLUSTRATED_FINISHED_FORMAT = "illustrated-story"


def finished_library_format(*, visual_style: str, video_format: str, short_template: str,
                            directed_spec: bool, directed_full_film: bool) -> str:
    """The library lane label for one render. One expression, one caller, one test.

    This used to be a ternary inlined in the archive call. A test can only pin an inlined
    expression by copying it, and a copied expression is not a test — reordering the branches here
    would leave both the copy and the suite green while every illustrated render silently went
    back to being an "explainer".
    """
    if directed_full_film:
        return "directed-v1-full"
    if directed_spec:
        return "directed-v1-pilot"
    if video_format == "social":
        return f"short-{short_template}"
    if visual_style == "illustrated_story":
        return ILLUSTRATED_FINISHED_FORMAT
    return "explainer"


def _read_json_file(path: str | None) -> dict:
    """Best-effort read of a pipeline side-car. Never let a bad artifact block archival."""
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _illustrated_library_fields(result: dict, visual_style: str) -> dict:
    """Lane facts the library needs to describe an illustrated render without opening the MP4.

    These come from artifacts the run already wrote, so nothing here re-derives or re-judges
    anything. Absent values stay absent rather than defaulting to something reassuring: a
    storyboard that never validated must not read as validated because a key was missing.
    """
    if visual_style != "illustrated_story":
        return {}
    manifest = _read_json_file(result.get("generation_manifest_path"))
    storyboard = _read_json_file(result.get("storyboard_path"))
    lane = manifest.get("illustrated_story") if isinstance(
        manifest.get("illustrated_story"), dict) else {}
    music = manifest.get("music") if isinstance(manifest.get("music"), dict) else {}
    validation = storyboard.get("validation") if isinstance(
        storyboard.get("validation"), dict) else {}
    fields = {
        "creative_lane": manifest.get("creative_lane") or "illustrated_story_v1",
        "creative_profile": manifest.get("creative_profile"),
        "story_engine": storyboard.get("story_engine") or None,
        "chapter_count": storyboard.get("chapter_count"),
        # Story beats and rendered scenes are different numbers since a beat can span several
        # scenes. The fallback counts asserting rows rather than all of them, so an older manifest
        # without the split still reports the story's size and not the edit's.
        "beat_count": lane.get("beat_count") or len([
            row for row in (storyboard.get("beats") or [])
            if not str(row.get("continues") or "").strip()]) or None,
        "scene_count_rendered": lane.get("scene_count") or len(storyboard.get("beats") or []) or None,
        "location_count": lane.get("location_count") or None,
        "storyboard_validated": validation.get("passed"),
        "music_status": music.get("status") or ("ready" if music.get("spec") else None),
        "motion_mode": result.get("motion_mode") or manifest.get("motion_mode"),
    }
    return {key: value for key, value in fields.items() if value is not None}


def _persist_finished(job_id: str, src_path: str, meta: dict, extra: dict | None = None) -> str:
    """Keep a local compatibility copy and upload the durable Blob/Postgres record when enabled."""
    dest = os.path.join(FINISHED_DIR, f"{job_id}.mp4")
    entry = {**meta, "path": src_path}
    upload_video = src_path
    upload_extras = {kind: path for kind, path in (extra or {}).items()
                     if path and os.path.isfile(path)}
    local_copy_ready = False

    # Vercel's deployed source tree can be read-only; local persistence is only a development and
    # single-process compatibility layer. A failure here must never skip the durable Blob upload.
    try:
        os.makedirs(FINISHED_DIR, exist_ok=True)
        shutil.copy(src_path, dest)
        entry["path"] = dest
        upload_video = dest
        for ext, p in (extra or {}).items():   # e.g. {"txt": ..., "srt": ...}
            if p and os.path.exists(p):
                d = os.path.join(FINISHED_DIR, f"{job_id}.{ext}")
                shutil.copy(p, d)
                entry[f"{ext}_path"] = d
                upload_extras[ext] = d
        with _INDEX_LOCK:
            index = {}
            if os.path.exists(_FINISHED_INDEX):
                with open(_FINISHED_INDEX) as f:
                    index = json.load(f)
            index[job_id] = entry
            _atomic_write_json(_FINISHED_INDEX, index)
        local_copy_ready = True
    except Exception as exc:
        print(f"[finished] local compatibility copy skipped: {exc}")

    # Upload outside the index lock: a large MP4 must not block unrelated local index readers.
    remote = artifact_store.persist_finished(job_id, upload_video, meta, upload_extras)
    if remote and local_copy_ready:
        entry["remote"] = remote
        try:
            with _INDEX_LOCK:
                with open(_FINISHED_INDEX) as f:
                    index = json.load(f)
                index[job_id] = entry
                _atomic_write_json(_FINISHED_INDEX, index)
        except Exception as exc:
            print(f"[finished] local remote metadata update skipped: {exc}")
    return dest if local_copy_ready else src_path


async def _archive_finished(job: dict, job_id: str, video_path: str, meta: dict,
                            extra: dict | None = None,
                            durable_runtime: durable_execution.DurableRuntime | None = None) -> None:
    """Run file/Blob I/O off the event loop and surface persistence failure as degradation."""
    try:
        if durable_runtime:
            remote = await asyncio.to_thread(
                durable_runtime.finalize, video_path, meta, extra)
            job["remote"] = remote
        else:
            await asyncio.to_thread(_persist_finished, job_id, video_path, meta, extra)
        job["archived"] = True
    except Exception as exc:
        job["archived"] = False
        job["storage_error"] = str(exc)
        if IS_VERCEL:
            job["status"] = "degraded"
        if isinstance(job.get("events"), list):
            job["events"].append({"type": "error", "data": f"Artifact archive failed: {exc}"})
        if durable_runtime:
            raise


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
        output_dir = tempfile.mkdtemp(prefix=f"yt_job_{job_id}_")

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
        await _archive_finished(job, job_id, output_path, {
            "title": script.get("title") or request.prompt,
            "format": "standard",
            "status": "done",
            "prompt": request.prompt,
        })
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
    _require_render_storage()
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
            if job["status"] in ("done", "degraded", "error"):
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
    if job["status"] not in ("done", "degraded") or not job.get("output_path"):
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
        if job.get("reel_path"):
            clips = {f"clip_{i + 1:02d}": clip.get("clip_path")
                     for i, clip in enumerate(result.get("clips") or [])}
            await _archive_finished(job, job_id, job["reel_path"], {
                "title": _match_prefix(job).replace("_", " ") or "Highlight reel",
                "format": "highlights", "status": "done", "clip_count": n,
            }, clips)
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
        if job.get("reel_path"):
            clips = {f"clip_{i + 1:02d}": clip.get("clip_path")
                     for i, clip in enumerate(result.get("clips") or [])}
            await _archive_finished(job, job_id, job["reel_path"], {
                "title": _match_prefix(job).replace("_", " ") or "Highlight reel",
                "format": "highlights", "status": "done", "clip_count": n,
            }, clips)
        job["events"].append({"type": "done", "data": f"{n} clip(s) + highlight reel ready"})

    except Exception as exc:
        import traceback
        job["status"] = "error"
        job["error"] = str(exc)
        job["events"].append({"type": "error", "data": f"Pipeline failed: {exc}"})
        job["events"].append({"type": "error", "data": traceback.format_exc()})


@app.post("/api/highlights/from-url")
async def highlights_from_url(request: HighlightsUrlRequest, background_tasks: BackgroundTasks):
    _require_render_storage()
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
    _require_render_storage()
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
            if job["status"] in ("done", "degraded", "error"):
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
        await _archive_finished(job, job_id, result["video_path"], {
            "title": result.get("title") or prompt,
            "format": "chart", "status": job["status"],
            "youtube_title": result.get("youtube_title"),
            "youtube_description": result.get("youtube_description"),
            "youtube_tags": result.get("youtube_tags") or [],
            "cost_usd": cost,
        }, {"thumb": result.get("thumbnail_path")})
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
    _require_render_storage()
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
    topic_channel: Literal["", "world", "history", "nature"] = ""
    # Stop after the script passes every pre-spend gate and write it for editorial approval;
    # nothing beyond text is bought. The approved rerun reuses the cached script.
    stop_after_script: bool = False
    # An editor's targeted note: revise the cached script beat by beat instead of writing a
    # fresh draft. Beats may merge or shorten, never drop; the ledger re-judges every sentence.
    revision_note: str = Field(default="", max_length=6000)
    duration_sec: int = 90
    voice: str = "echo"
    style: str = "engaging and scientific"
    image_guidance: str = ""   # optional theme/setting steer (e.g. "football", "yard work")
    fact_check: bool = True
    video_format: str = "landscape"   # "landscape" (16:9 YouTube) | "social" (9:16 + karaoke captions)
    speech_bubble: bool = False       # landscape only: Bolt "talks" via a synced phrase bubble
    i2v: bool | None = None           # image-to-video motion (Veo/Sora). None=default (social on,
                                      # long-form off); True/False forces it for ANY length
    motion_mode: Literal["stills", "standard", "full_motion"] | None = None
    series: str = ""                  # format-series mode: a recurring series name/pattern
    short_template: str = "auto"      # social only: "auto" (title heuristic) | "explainer"
                                      # (curiosity-gap mystery) | "simulation" (you-change escalation)
    n_items: int = 3                  # rapid quiz default: three rounds; capped by the quiz contract
    operator_direction: str = ""      # optional creative direction; enriches the script prompt,
                                      # subordinate to the format/structure/safety rules
    story_format: Literal["standard_explainer", "evidence_led_mystery"] = "standard_explainer"
    visual_style: Literal["cinematic", "illustrated_story"] = "cinematic"
    # Internal, immutable topic recipe; only an approved generic_illustrated action sets this.
    illustrated_authorization: dict = Field(default_factory=dict)
    # Internal directed-v1 fields. Public callers must use the validation/process endpoints,
    # which bind paid approval to an immutable spec hash before constructing this request.
    directed_spec: dict | None = None
    directed_spec_sha256: str = ""
    directed_paid_authorized: bool = False
    # Internal continuation fields. Only a separately approved directed_full_film agent action may
    # construct them; the public generic endpoint rejects every one below.
    directed_full_film: bool = False
    directed_authorization_sha256: str = ""
    directed_promotion: dict = Field(default_factory=dict)
    directed_parent_action_id: str = ""
    directed_parent_job_id: str = ""
    directed_parent_video_sha256: str = ""
    # Internal PR7 fields are accepted when a durable worker reconstructs a queued pilot request.
    # The public explainer endpoint rejects controlled_pilot=True; only the paired pilot endpoint
    # can create these values.
    controlled_pilot: bool = False
    pilot_batch_id: str = ""
    pilot_kind: Literal["", "standard", "evidence_mystery"] = ""
    pilot_policy: dict = Field(default_factory=dict)
    # Internal PR8 fields, on the same terms: the public endpoint rejects
    # controlled_production=True, and only /api/explainer/production can create these values.
    controlled_production: bool = False
    production_id: str = ""
    selection_sha256: str = ""
    frozen_opening_sha256: str = ""
    production_policy: dict = Field(default_factory=dict)


class DirectedLongformValidateRequest(BaseModel):
    spec: dict


class DirectedLongformProcessRequest(BaseModel):
    spec: dict
    spec_sha256: str
    authorize_paid: bool = False


class AgentActionCreateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    operation: Literal["directed_pilot", "directed_full_film", "generic_illustrated"] = "directed_pilot"
    topic: str = Field(default="", max_length=500)
    duration_sec: int = Field(default=90, ge=agent_actions.ILLUSTRATED_MIN_SECONDS,
                              le=agent_actions.ILLUSTRATED_MAX_SECONDS, strict=True)
    creative_direction: str = Field(default="", max_length=2000)
    spec: dict | None = None
    bundled_spec_id: Literal[
        "hippo_illustrated_story_v4", "hippo_illustrated_story_v4_full_5m",
        "hippo_illustrated_story_v4_recovery_opening",
        "harp_seal_nature_short_v1", ""
    ] = ""
    cost_ceiling_usd: float = Field(gt=0, le=25)
    parent_action_id: str = ""
    parent_job_id: str = ""


class AgentActionApprovalRequest(BaseModel):
    model_config = {"extra": "forbid"}

    spec_sha256: str = Field(min_length=64, max_length=64)
    cost_ceiling_usd: float = Field(gt=0, le=25)


class ExplainerPilotBatchRequest(BaseModel):
    model_config = {"extra": "forbid"}

    standard_question: str
    mystery_question: str
    voice: str = "echo"
    standard_direction: str = ""
    mystery_direction: str = ""


class ExplainerProductionRequest(BaseModel):
    """Start the single PR8 90-second run for a PR7 batch that already passed.

    The caller supplies only the source batch and the question. Runtime, story format, thresholds,
    and the score floor come from the frozen contract, and the winning structure is derived from
    the recorded PR7 scores rather than chosen here.
    """
    model_config = {"extra": "forbid"}

    batch_id: str
    question: str
    voice: str = "echo"
    operator_direction: str = ""
    tie_break_reviewer: str = ""
    tie_break_reason: str = ""
    tie_break_pilot_kind: Literal["", "standard", "evidence_mystery"] = ""


class ExplainerHumanReviewRequest(BaseModel):
    reviewer: str
    decision: Literal["approve", "reject"]
    checklist: list[dict]


class ExplainerStoryFormatReviewRequest(BaseModel):
    reviewer: str
    decision: Literal["accept", "reject"]


def _checkpoint_generation_manifest(output_dir: str, *, status: str, error: str = "") -> None:
    """Make paused/failed manifests describe work actually completed before the stop."""
    manifest_path = os.path.join(output_dir, "generation_manifest.json")
    if not os.path.isfile(manifest_path):
        return
    try:
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        timing_path = os.path.join(output_dir, "audio_timing_report.json")
        if os.path.isfile(timing_path):
            with open(timing_path, encoding="utf-8") as handle:
                timing = json.load(handle)
            manifest["actual_audio_transformations"] = timing.get("audio_transformations") or []
        motion_path = os.path.join(output_dir, "motion_report.json")
        if os.path.isfile(motion_path):
            with open(motion_path, encoding="utf-8") as handle:
                motion = json.load(handle)
            manifest["actual_motion"] = [
                {key: candidate.get(key) for key in (
                    "state_id", "provider", "model_id", "generation_status",
                    "provider_attempts")}
                for candidate in motion.get("candidates") or [] if candidate.get("selected")
            ]
        manifest["status"] = status
        manifest["status_recorded_at"] = datetime.now(timezone.utc).isoformat()
        if error:
            manifest["error"] = error[:500]
        _atomic_write_json(manifest_path, manifest)
    except (OSError, ValueError, TypeError):
        # The primary task exception still owns job disposition. A malformed manifest must never
        # convert a failed render into a successful one.
        return


async def run_explainer_task(job_id: str, request: ExplainerRequest, output_dir: str,
                             resume: bool = False,
                             durable_runtime: durable_execution.DurableRuntime | None = None):
    import explainer_pipeline as ep

    job = explainer_jobs.setdefault(job_id, {
        "id": job_id, "status": "queued", "events": [], "output_path": None,
        "script": None, "title": "", "hook": "", "scene_count": 0, "error": None,
    })
    job["status"] = "processing"

    def push(msg: str):
        if msg.startswith("stage:"):
            event_type, data = "stage", msg[6:]
        else:
            event_type, data = "log", msg
        job["events"].append({"type": event_type, "data": data})
        if durable_runtime:
            durable_runtime.event(event_type, data)

    def _run_with_runtime(fn):
        if not durable_runtime:
            return fn()
        with durable_execution.activate(durable_runtime):
            return fn()

    try:
        loop = asyncio.get_event_loop()
        # Directed v1 is a separate, operator-authored job.  It never enters the model-authored
        # explainer pipeline and this internal branch is reachable only through validate/process.
        if request.directed_spec:
            import directed_longform as dl

            directed = dl.DirectedLongformSpec.model_validate(request.directed_spec)
            if request.directed_full_film:
                if not durable_runtime:
                    raise RuntimeError("Directed full films require durable Blob/Postgres storage")
                import db
                finished = await asyncio.to_thread(
                    db.finished_video_get, request.directed_parent_job_id) or {}
                artifact = (finished.get("artifacts") or {}).get("video") or {}
                if artifact.get("sha256") != request.directed_parent_video_sha256:
                    raise RuntimeError("Accepted parent pilot artifact no longer matches approval")
                parent_path = os.path.join(output_dir, "accepted_pilot.mp4")

                def restore_parent_video(path: str) -> str:
                    # The finished-video pointer may outlive its Blob object. Directed pilots also
                    # persist immutable snapshot artifacts, so recover only from another MP4 with
                    # the exact SHA approved for promotion; never regenerate or accept new bytes.
                    expected_sha = request.directed_parent_video_sha256
                    candidates = [artifact]
                    for item in durable_runtime.store.artifacts(
                            str(request.directed_parent_job_id)):
                        same_hash = item.get("sha256") == expected_sha
                        media = str(item.get("content_type") or "").casefold().startswith("video/") \
                            or str(item.get("pathname") or "").casefold().endswith(".mp4")
                        if same_hash and media and item.get("url") != artifact.get("url"):
                            candidates.append(item)
                    missing = []
                    for candidate in candidates:
                        try:
                            durable_runtime.blob.download(candidate, path)
                            if candidate.get("url") != artifact.get("url"):
                                durable_runtime.event(
                                    "parent_pilot_snapshot_restored",
                                    "Accepted pilot restored from immutable snapshot",
                                    {"sha256": expected_sha,
                                     "stage_key": candidate.get("stage_key")},
                                )
                            return path
                        except durable_execution.StorageUnavailable as exc:
                            if "404" not in str(exc) and "Not Found" not in str(exc):
                                raise
                            missing.append(str(candidate.get("pathname") or "unknown"))
                    # A checkpoint archive may still contain the rendered preview even
                    # when direct final/snapshot objects were removed. Inspect archives without
                    # extracting paths, and accept bytes only if they match the approved SHA.
                    import hashlib
                    import tempfile
                    import tarfile
                    checkpoint_records = [
                        item for item in durable_runtime.store.artifacts(
                            str(request.directed_parent_job_id))
                        if item.get("kind") == "checkpoint"
                    ]
                    for checkpoint in checkpoint_records:
                        work = tempfile.mkdtemp(prefix="parent_pilot_recovery_")
                        archive = os.path.join(work, "checkpoint.tar.gz")
                        candidate_path = os.path.join(work, "candidate.mp4")
                        try:
                            try:
                                durable_runtime.blob.download(checkpoint, archive)
                            except durable_execution.StorageUnavailable as exc:
                                if "404" in str(exc) or "Not Found" in str(exc):
                                    continue
                                raise
                            with tarfile.open(archive, "r:gz") as bundle:
                                for member in bundle.getmembers():
                                    if not member.isfile() or not member.name.casefold().endswith(".mp4"):
                                        continue
                                    source = bundle.extractfile(member)
                                    if source is None:
                                        continue
                                    digest = hashlib.sha256()
                                    with source, open(candidate_path, "wb") as destination:
                                        for chunk in iter(lambda: source.read(1024 * 1024), b""):
                                            digest.update(chunk)
                                            destination.write(chunk)
                                    if digest.hexdigest() == expected_sha:
                                        shutil.copyfile(candidate_path, path)
                                        durable_runtime.event(
                                            "parent_pilot_checkpoint_restored",
                                            "Accepted pilot restored from durable checkpoint archive",
                                            {"sha256": expected_sha,
                                             "stage_key": checkpoint.get("stage_key")},
                                        )
                                        return path
                        finally:
                            shutil.rmtree(work, ignore_errors=True)
                    raise durable_execution.StorageUnavailable(
                        "Accepted pilot bytes are absent from finished, snapshot, and checkpoint "
                        f"artifacts ({len(missing)} direct candidates and "
                        f"{len(checkpoint_records)} checkpoints checked)")

                parent_video_available = True
                try:
                    await asyncio.to_thread(restore_parent_video, parent_path)
                except durable_execution.StorageUnavailable as exc:
                    if "Accepted pilot bytes are absent" not in str(exc):
                        raise
                    parent_video_available = False
                    durable_runtime.event(
                        "parent_pilot_irretrievable",
                        "Approved opening object is gone; preserving the authorized remainder",
                        {"parent_job_id": request.directed_parent_job_id,
                         "sha256": request.directed_parent_video_sha256},
                    )
                import directed_full_film as dff
                envelope = {"spec": request.directed_spec,
                            "promotion": request.directed_promotion}
                result = await loop.run_in_executor(
                    None,
                    lambda: _run_with_runtime(lambda: dff.render_remaining(
                        envelope=envelope,
                        authorization_hash=request.directed_authorization_sha256,
                        parent_video_path=parent_path,
                        out_dir=output_dir,
                        voice=directed.target.voice,
                        authorize_paid=request.directed_paid_authorized,
                        restore_parent_video=(restore_parent_video
                                              if parent_video_available else None),
                        parent_video_available=parent_video_available,
                        log=push)),
                )
            else:
                import spec_pilot
                pilot = await loop.run_in_executor(
                    None,
                    lambda: _run_with_runtime(lambda: spec_pilot.render_pilot(
                        request.directed_spec, output_dir,
                        voice=directed.target.voice,
                        window=(0.0, directed.target.pilot_end_sec),
                        use_i2v=True,
                        validated_sha256=request.directed_spec_sha256,
                        authorize_paid=request.directed_paid_authorized,
                        require_validation=True,
                        log=push)),
                )
                from longform_rendered_gate import rendered_grade_summary
                grade_summary = rendered_grade_summary(pilot.get("rendered_contract") or {})
                result = {
                    "output_path": pilot["preview_path"],
                    "title": directed.title,
                    "script": request.directed_spec,
                    "hook": directed.narration[0].narration,
                    "scene_count": pilot["shots"],
                    "duration_sec": pilot["measured_seconds"],
                    "video_format": directed.target.format,
                    "actual_cost": pilot["total_cost_usd"],
                    "est_cost": pilot["total_cost_usd"],
                    "generation_manifest_path": pilot["generation_manifest_path"],
                    "directed_spec_path": pilot["directed_spec_path"],
                    "validation_report_path": pilot["validation_report_path"],
                    "rendered_contract": pilot.get("rendered_contract") or {},
                    "rendered_contract_path": pilot.get("rendered_contract_path"),
                    "rendered_contact_sheet_path": pilot.get("rendered_contact_sheet_path"),
                    "human_review_path": pilot.get("human_review_path"),
                    "first_minute_preview_path": pilot["preview_path"],
                    "directed_pilot": True,
                    # Delivery and review are orthogonal. A complete MP4 is technically complete;
                    # automated/editorial/promotion state is carried explicitly below.
                    "status": "ok",
                    "technical_status": grade_summary["technical_status"],
                    "automated_grade_status": grade_summary["automated_status"],
                    "editorial_status": grade_summary["editorial_status"],
                    "promotion_status": grade_summary["promotion_status"],
                    "degraded_reasons": [],
                }
        # QUIZ template (social only): a different backend — Bolt hosts a "What is it?" guessing quiz.
        # The `question` field carries the CATEGORY (e.g. "animals"). Returns an explainer-shaped result.
        elif request.video_format == "social" and request.short_template == "quiz":
            import quiz_pipeline as qp
            result = await loop.run_in_executor(
                None,
                lambda: _run_with_runtime(lambda: qp.run_quiz_pipeline(
                    category=request.question, output_dir=output_dir,
                    # Clamp from the creative contract, not a literal. This route had its own
        …25224 tokens truncated…               and "No space left on device" in str(job.get("error") or "")):
            # Reconcile all unfinished local encodes before one scratch-lifecycle
            # recovery. This branch also blocks a consumed marker from falling
            # through to the older unrestricted storage_error requeue below.
            try:
                await asyncio.to_thread(
                    store.rearm_local_render_failure, str(action["job_id"]),
                    expected_checkpoint_sha256=(job.get("checkpoint") or {}).get("sha256", ""),
                    failure_kind="disk")
            except durable_execution.DurableExecutionError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        elif (job and job.get("status") == "error"
                and action.get("operation") == agent_actions.GENERIC_ILLUSTRATED_OPERATION
                and not (job.get("result") or {}).get("render_memory_recovery_v1")
                and (job.get("error") == "Maximum worker attempts exhausted" or (
                    str(job.get("error") or "").startswith("Paid stage render:")
                    and "unresolved prior provider attempt" in str(job.get("error") or "")))):
            try:
                await asyncio.to_thread(
                    store.rearm_local_render_failure, str(action["job_id"]),
                    expected_checkpoint_sha256=(job.get("checkpoint") or {}).get("sha256", ""))
            except durable_execution.DurableExecutionError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        elif (job and job.get("status") == "error"
                and action.get("operation") == agent_actions.GENERIC_ILLUSTRATED_OPERATION
                and str(job.get("error") or "").startswith("STORY_SPINE_UNSUPPORTED")
                and not (job.get("result") or {}).get("compiled_function_recovery_v1")
                and await asyncio.to_thread(_compiled_function_checkpoint_repairable, job, store, blob)):
            await asyncio.to_thread(
                store.rearm_infrastructure_failure, str(action["job_id"]),
                error_fragment="STORY_SPINE_UNSUPPORTED", extra_attempts=1,
                recovery_key="compiled_function_recovery_v1",
                expected_checkpoint_sha256=job["checkpoint"]["sha256"])
        elif (job and job.get("status") == "error"
                and action.get("operation") == agent_actions.GENERIC_ILLUSTRATED_OPERATION
                and is_legacy_scope_label_failure(str(job.get("error") or ""))
                and not (job.get("result") or {}).get("scope_label_recovery_v1")
                and await asyncio.to_thread(_scope_label_checkpoint_repaired, job, store, blob)):
            # PR92 fixed the validator; this resumes its terminal pre-script failure once.
            # Revalidate the checkpoint first, then bind the recovery atomically to that hash.
            # The unchanged job replays its completed provider stages under the same approval.
            await asyncio.to_thread(
                store.rearm_infrastructure_failure, str(action["job_id"]),
                error_fragment="scope_inflationx1", extra_attempts=1,
                recovery_key="scope_label_recovery_v1",
                expected_checkpoint_sha256=job["checkpoint"]["sha256"])
        elif (job and job.get("status") == "error"
                and action.get("operation") == agent_actions.GENERIC_ILLUSTRATED_OPERATION
                and legacy_setup_failure(str(job.get("error") or ""))
                and not (job.get("result") or {}).get("evidence_coverage_recovery_v1")
                and await asyncio.to_thread(_ecosystem_checkpoint_repairable, job, store, blob)):
            # Continue this corrected pre-narration failure once. Evidence repair runs through
            # normal paid stages and must succeed within the original immutable approval.
            await asyncio.to_thread(
                store.rearm_infrastructure_failure, str(action["job_id"]),
                error_fragment="STORY_SPINE_UNSUPPORTED", extra_attempts=1,
                recovery_key="evidence_coverage_recovery_v1",
                expected_checkpoint_sha256=job["checkpoint"]["sha256"])
        elif (job and job.get("status") == "error"
                and action.get("operation") == agent_actions.GENERIC_ILLUSTRATED_OPERATION
                and legacy_introduction_contract_failure(str(job.get("error") or ""))
                and not (job.get("result") or {}).get("introduction_contract_recovery_v1")
                and await asyncio.to_thread(
                    _introduction_checkpoint_repairable, job, store, blob)):
            # v1 allowed mechanism evidence into setup, but still described setup and the hidden
            # link as removal-only jobs. Replan once from this exact validated checkpoint under
            # the directional introduction/removal contract; v2 may research only its new gaps.
            await asyncio.to_thread(
                store.rearm_infrastructure_failure, str(action["job_id"]),
                error_fragment="STORY_SPINE_UNSUPPORTED", extra_attempts=1,
                recovery_key="introduction_contract_recovery_v1",
                expected_checkpoint_sha256=job["checkpoint"]["sha256"])
        elif (job and job.get("status") == "error"
                and action.get("operation") == agent_actions.GENERIC_ILLUSTRATED_OPERATION
                and focused_provenance_failure(str(job.get("error") or ""))
                and not (job.get("result") or {}).get("focused_evidence_provenance_recovery_v1")
                and await asyncio.to_thread(
                    _focused_provenance_checkpoint_repairable, job, store, blob)):
            # Search found candidate URLs, but this host could fetch none of their pages and the
            # provider emitted URL-only search blocks. Replay the focused step once so its saved
            # search context can expose native cited excerpts; every resulting claim still passes
            # the unchanged quote, source, and Boundary A checks.
            await asyncio.to_thread(
                store.rearm_infrastructure_failure, str(action["job_id"]),
                error_fragment="0 quotable excerpts available", extra_attempts=1,
                recovery_key="focused_evidence_provenance_recovery_v1",
                expected_checkpoint_sha256=job["checkpoint"]["sha256"])
        elif (job and job.get("status") == "error"
                and action.get("operation") == agent_actions.GENERIC_ILLUSTRATED_OPERATION
                and focused_provenance_failure(str(job.get("error") or ""))
                and (job.get("result") or {}).get("focused_evidence_provenance_recovery_v1")
                and not (job.get("result") or {}).get("verified_source_reuse_recovery_v1")
                and await asyncio.to_thread(
                    _verified_source_reuse_checkpoint_repairable, job, store, blob)):
            # PR101 can satisfy a gap from exact passages on the already page-verified base
            # sources before another search. Continue this exact failed checkpoint once; the
            # action payload, prior spend, provider stages, gates and $5 ceiling stay unchanged.
            await asyncio.to_thread(
                store.rearm_infrastructure_failure, str(action["job_id"]),
                error_fragment="0 quotable excerpts available", extra_attempts=1,
                recovery_key="verified_source_reuse_recovery_v1",
                expected_checkpoint_sha256=job["checkpoint"]["sha256"])
        elif (job and job.get("status") == "error"
                and action.get("operation") == agent_actions.GENERIC_ILLUSTRATED_OPERATION
                and str(job.get("error") or "").startswith(
                    "Evidence coverage judgment unavailable; no new claim accepted")
                and (job.get("result") or {}).get("verified_source_reuse_recovery_v1")
                and not (job.get("result") or {}).get("boundary_a_provider_recovery_v1")
                and (job.get("checkpoint") or {}).get("sha256")):
            # PR102 reached the reused source passage, then its one bounded entailment call
            # failed operationally. Preserve that call's reservation and stable idempotency key;
            # the store admits only one reconciled Anthropic retry stage for this continuation.
            await asyncio.to_thread(
                store.rearm_retryable_provider_stage, str(action["job_id"]),
                error_prefix="Evidence coverage judgment unavailable; no new claim accepted",
                recovery_key="boundary_a_provider_recovery_v1",
                expected_checkpoint_sha256=job["checkpoint"]["sha256"], extra_attempts=1)
        elif (job and job.get("status") == "error"
                and str(job.get("error") or "") == LEGACY_DOSSIER_JSON_ERROR):
            # One migration of the legacy parser failure. The provider request is
            # unchanged, so durable execution replays its paid response. The new
            # parser emits different errors for genuinely malformed evidence,
            # preventing repeated dispatches from rearming an unrecoverable ledger.
            await asyncio.to_thread(
                store.rearm_infrastructure_failure, str(action["job_id"]),
                error_fragment="Research provider returned malformed dossier JSON;",
                extra_attempts=1)
        elif (job and job.get("status") == "error"
              and is_legacy_weak_source_failure(str(job.get("error") or ""))):
            # Re-evaluate the existing paid research candidates after quarantine
            # filtering. Payload, request hashes and spend remain unchanged; all
            # retained claims and the resulting story must still pass their gates.
            # A subsequent empty/invalid ledger error does not match this migration.
            await asyncio.to_thread(
                store.rearm_infrastructure_failure, str(action["job_id"]),
                error_fragment="weak_source_domainx", extra_attempts=1)
        elif (job and job.get("status") == "error"
                and action.get("operation") == agent_actions.GENERIC_ILLUSTRATED_OPERATION
                and focused_provenance_failure(str(job.get("error") or ""))
                and (job.get("result") or {}).get("verified_source_reuse_recovery_v1")
                and not (job.get("result") or {}).get("evidence_composition_recovery_v1")
                and await asyncio.to_thread(_composed_evidence_checkpoint_repairable, job, store, blob)):
            await asyncio.to_thread(
                store.rearm_infrastructure_failure, str(action["job_id"]),
                error_fragment="0 quotable excerpts available", extra_attempts=1,
                recovery_key="evidence_composition_recovery_v1",
                expected_checkpoint_sha256=job["checkpoint"]["sha256"])
        elif (job and job.get("status") == "error"
                and str(job.get("error") or "").startswith(
                  "Claim ledger failed after script/fact-check before asset spend:")
              and "A speculative claim is narrated as certain." in str(job.get("error") or "")):
            # PR81 replaces the six-word binding that caused false rejections and adds one
            # evidence-locked repair for genuinely unhedged scenes. Rearm only this exact legacy
            # failure class; the approved payload, spend ceiling, provider stages and claim ledger
            # remain immutable.
            await asyncio.to_thread(
                store.rearm_infrastructure_failure, str(action["job_id"]),
                error_fragment="Claim ledger failed after script/fact-check before asset spend:",
                extra_attempts=1)
        elif (job and job.get("status") == "error"
              and is_legacy_negation_scope_failure(str(job.get("error") or ""))):
            # PR82 scopes negation to the proposition it governs. Re-evaluate the same paid
            # dossier once; true claim/quote contradictions remain terminal under the new rule.
            await asyncio.to_thread(
                store.rearm_infrastructure_failure, str(action["job_id"]),
                error_fragment="support_contradicts_claimx", extra_attempts=1)
        elif (job and job.get("status") == "error"
              and is_legacy_anaphoric_claim_failure(str(job.get("error") or ""))):
            # PR83 gives the evidence-locked repair the neighbouring context needed to replace
            # an anaphoric factual payoff with a self-contained supported assertion.
            await asyncio.to_thread(
                store.rearm_infrastructure_failure, str(action["job_id"]),
                error_fragment="role=payoff: It worked.", extra_attempts=1)
        elif job and job.get("status") == "storage_error":
            await asyncio.to_thread(
                store.requeue, str(action["job_id"]), allowed_statuses=("storage_error",))
        elif (job and job.get("status") == "error"
              and "Required media binary 'ffprobe' was not found" in str(job.get("error") or "")):
            import media_binaries
            if not media_binaries.preflight().get("ready"):
                raise HTTPException(
                    status_code=409, detail="Media probe repair is not ready on this deployment")
            await asyncio.to_thread(
                store.rearm_infrastructure_failure, str(action["job_id"]),
                error_fragment="Required media binary 'ffprobe' was not found",
                extra_attempts=3)
        elif (job and job.get("status") == "error"
              and str(job.get("error") or "").strip() == "'cache_path'"):
            # PR39 repairs a post-render manifest KeyError. The exact match plus the store's
            # no-reservation/under-cap checks make this a bounded continuation of the immutable
            # approved job, not a general-purpose retry or new spending authority.
            await asyncio.to_thread(
                store.rearm_infrastructure_failure, str(action["job_id"]),
                error_fragment="'cache_path'", extra_attempts=3)
        elif (job and job.get("status") == "error"
              and "No space left on device" in str(job.get("error") or "")):
            # Resume the immutable approved job after the bounded-media-cache repair.  The store
            # verifies any outstanding reservation belongs to at most one retry stage and keeps
            # its idempotency key; completed narration/images remain reuse-only.
            await asyncio.to_thread(
                store.rearm_disk_exhaustion, str(action["job_id"]), extra_attempts=3)
        elif (job and job.get("status") == "error"
              and str(job.get("error") or "").strip()
              == "Directed segment streaming requires a public unlisted Blob store"):
            # PR61 added authenticated localhost streaming for private Blob stores. Rearm only
            # the exact obsolete fail-closed guard; payload, stages, spend, and ceiling remain
            # immutable, and the generic infrastructure helper requires zero reservation.
            await asyncio.to_thread(
                store.rearm_infrastructure_failure, str(action["job_id"]),
                error_fragment="Directed segment streaming requires a public unlisted Blob store",
                extra_attempts=3)
        if job and ((job.get("request") or {}).get("directed_full_film") is True):
            # Paid stages are individually durable and idempotent, but a five-minute film can
            # span several hosting-function windows. Preserve enough claim attempts to finish
            # the same hash-bound job; this does not raise or replace its approved cost ceiling.
            await asyncio.to_thread(
                store.ensure_directed_full_film_recovery_window, str(action["job_id"]),
                minimum_remaining_attempts=12)
        return await _run_durable_explainer_worker(str(action["job_id"]))
    except durable_execution.StorageUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/explainer/generate")
async def explainer_generate(request: ExplainerRequest, background_tasks: BackgroundTasks):
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question is required")
    if request.topic_channel and (request.visual_style != "illustrated_story"
                                  or request.video_format != "landscape"):
        raise HTTPException(status_code=400, detail=(
            "Channel stories currently use Illustrated Story in landscape. "
            "Choose those settings to generate this episode."))
    if request.illustrated_authorization:
        raise HTTPException(status_code=403, detail=(
            "Illustrated authorization is internal; create a generic_illustrated agent action"))
    import illustrated_story as illustrated_story_lane
    try:
        illustrated_story_lane.validate_request(
            visual_style=request.visual_style,
            video_format=request.video_format,
            story_format=request.story_format,
            controlled_pilot=request.controlled_pilot,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if (request.directed_spec or request.directed_spec_sha256
            or request.directed_paid_authorized or request.directed_full_film
            or request.directed_authorization_sha256 or request.directed_promotion
            or request.directed_parent_action_id or request.directed_parent_job_id
            or request.directed_parent_video_sha256):
        raise HTTPException(
            status_code=403,
            detail="Directed fields are internal; use /api/explainer/directed/validate then /process.")
    if request.controlled_pilot:
        raise HTTPException(
            status_code=403,
            detail="Controlled pilot fields are internal; use /api/explainer/pilots.")
    if request.controlled_production:
        raise HTTPException(
            status_code=403,
            detail="Controlled production fields are internal; use /api/explainer/production.")
    return await _enqueue_explainer_request(request, background_tasks)


async def _run_durable_explainer_worker(job_id: str | None = None) -> dict:
    store, blob = _durable_components()
    worker_id = f"vercel-{uuid.uuid4().hex}"
    claimed = await asyncio.to_thread(store.claim, job_id=job_id, worker_id=worker_id)
    if not claimed:
        current = await asyncio.to_thread(store.get_job, job_id) if job_id else None
        return {"claimed": False, "job": current}
    job_id = claimed["id"]
    output_dir = tempfile.mkdtemp(prefix=f"expl_{job_id}_")
    # Leave 320 seconds of the 800-second host window for an accepted provider call, checkpoint
    # upload and response. Continuations are queued jobs claimed by the existing minute cron or
    # the idempotent dispatch route; no new action or spending approval is created.
    try:
        work_seconds = float(os.environ.get("DURABLE_WORKER_WINDOW_SECONDS", "480"))
    except (ValueError, TypeError):
        work_seconds = 480.0
    runtime = durable_execution.DurableRuntime(
        job_id=job_id, worker_id=worker_id, output_dir=output_dir, store=store, blob=blob,
        time_budget_seconds=max(60.0, min(work_seconds, 480.0)))
    try:
        with durable_execution.maintain_lease(runtime):
            if claimed.get("checkpoint"):
                await asyncio.to_thread(runtime.restore_checkpoint, claimed["checkpoint"])
            request = ExplainerRequest(**(claimed.get("request") or {}))
            runtime.cache_local_renders = request.visual_style == "illustrated_story"
            if getattr(request, "illustrated_authorization", None):
                _validate_illustrated_request_authorization(request)
                approved_cap = float(request.illustrated_authorization["cost_ceiling_usd"])
                if float(claimed.get("max_cost_usd") or 0) > approved_cap + 1e-9:
                    raise ValueError("Durable job budget exceeds the illustrated approval ceiling")
            explainer_jobs[job_id] = _durable_job_view(claimed)
            resume = os.path.isfile(os.path.join(output_dir, "_state.json"))
            await run_explainer_task(
                job_id, request, output_dir, resume=resume, durable_runtime=runtime)
        return {"claimed": True, "job": await asyncio.to_thread(store.get_job, job_id)}
    except durable_execution.ProviderBlocked as exc:
        # Account problems are pauses, not creative failures or automatic retry loops.
        # The explicit action dispatch is the sole resume path after access is restored.
        await asyncio.to_thread(runtime.checkpoint, "provider-blocked")
        await asyncio.to_thread(
            store.set_status, job_id, "provider_blocked", error=str(exc),
            result={"provider_block": exc.block}, worker_id=worker_id)
        await asyncio.to_thread(store.append_event, job_id, "provider_blocked", str(exc))
        row = await asyncio.to_thread(store.get_job, job_id)
        explainer_jobs[job_id] = _durable_job_view(row)
        return {"claimed": True, "blocked": True, "job": row}
    except durable_execution.CooperativeYield:
        # All pipeline threads have unwound before the checkpoint and lease release. Completed
        # paid outputs already exist in Blob; future invocations restore them with the same keys.
        checkpoint = await asyncio.to_thread(runtime.checkpoint, "worker-continuation")
        row = await asyncio.to_thread(
            store.yield_job, job_id, worker_id=worker_id, checkpoint=checkpoint)
        explainer_jobs[job_id] = _durable_job_view(row)
        return {"claimed": True, "continued": row.get("status") == "queued", "job": row}
    except (Exception, durable_execution.AmbiguousProviderOutcome) as exc:
        # Restore/configuration failures occur before run_explainer_task's handler. Release their
        # lease too, retaining the prior checkpoint and allowing only the normal bounded retries.
        if isinstance(exc, durable_execution.LeaseLost):
            raise
        hard_failure = isinstance(exc, (
            ValueError, durable_execution.BudgetExceeded,
            durable_execution.AmbiguousProviderOutcome,
        ))
        status = ("error" if hard_failure or int(claimed.get("attempts") or 1)
                  >= int(claimed.get("max_attempts") or 1) else "retry")
        await asyncio.to_thread(
            store.set_status, job_id, status, error=str(exc), worker_id=worker_id)
        await asyncio.to_thread(store.append_event, job_id, status, str(exc))
        return {"claimed": True, "job": await asyncio.to_thread(store.get_job, job_id)}
    finally:
        # Blob contains every paid stage and the latest checkpoint. Local /tmp is never authoritative.
        shutil.rmtree(output_dir, ignore_errors=True)


def _materialize_durable_explainer(job_id: str) -> dict | None:
    existing = explainer_jobs.get(job_id)
    if existing and existing.get("_materialized_dir") and os.path.isdir(existing["_materialized_dir"]):
        return existing
    store, blob = _durable_components()
    row = store.get_job(job_id)
    if not row:
        return None
    output_dir = tempfile.mkdtemp(prefix=f"expl_read_{job_id}_")
    runtime = durable_execution.DurableRuntime(
        job_id=job_id, worker_id="read-only", output_dir=output_dir, store=store, blob=blob)
    if row.get("checkpoint"):
        runtime.restore_checkpoint(row["checkpoint"])
    job = _durable_job_view(row)
    job["_materialized_dir"] = output_dir
    names = {
        "script_path": "_state.json",
        "transcript_path": "transcript.txt", "srt_path": "captions.srt",
        "description_path": "youtube_description.txt", "thumbnail_path": "thumbnail.jpg",
        "research_report_path": "research_dossier.json",
        "research_supplement_path": "research_supplement.json",
        "research_handoff_path": "research_handoff.json",
        "spine_failure_path": "semantic_failure_story-spine.json",
        "spine_after_research_path": "semantic_failure_story-spine-after-research.json",
        "claim_report_path": "claim_ledger_report.json",
        "audio_timing_report_path": "audio_timing_report.json",
        "evidence_plan_path": "evidence_asset_plan.json",
        "evidence_validation_path": "evidence_validation.json",
        "continuity_pack_path": "continuity_pack.json", "motion_report_path": "motion_report.json",
        "opening_freeze_path": "opening_freeze.json", "animatic_report_path": "animatic_gate.json",
        "animatic_preview_path": "animatic_preview.mp4",
        "rendered_contract_path": "rendered_contract.json",
        "rendered_contact_sheet_path": "rendered_contact_sheet.jpg",
        "human_review_path": "human_review.json",
        "story_format_review_path": "story_format_review.json",
        "storyboard_path": "illustrated_storyboard.json",
        "generation_manifest_path": "generation_manifest.json",
        "pilot_control_path": "pilot_control.json",
        "pilot_script_path": "pilot_script.json",
        "pilot_cost_report_path": "pilot_cost_report.json",
        "pilot_artifact_manifest_path": "pilot_artifact_manifest.json",
        "pilot_failure_path": "pilot_failure.json",
        "pilot_outcome_path": "pilot_outcome.json",
        "diagnostic_preview_path": "rejected_diagnostic_preview.mp4",
        "first_minute_preview_path": "first_minute_preview.mp4",
        "readiness_json_path": "retention_readiness.json",
    }
    for key, filename in names.items():
        path = os.path.join(output_dir, filename)
        if os.path.isfile(path):
            job[key] = path
    state_path = os.path.join(output_dir, "_state.json")
    if os.path.isfile(state_path):
        try:
            with open(state_path) as handle:
                state = json.load(handle)
            job["script"] = state.get("script") or job.get("script")
            if job.get("script"):
                job["title"] = job["script"].get("title") or job.get("title")
        except (OSError, ValueError, TypeError):
            pass
    explainer_jobs[job_id] = job
    return job


@app.post("/api/explainer/dispatch/{job_id}")
async def explainer_dispatch(job_id: str):
    """Run a queued render in a request separate from creation; leases make it crash-recoverable."""
    if not _durable_execution_required():
        raise HTTPException(status_code=409, detail="Durable execution is not enabled")
    try:
        return await _run_durable_explainer_worker(job_id)
    except durable_execution.StorageUnavailable as exc:
        raise HTTPException(status_code=503, detail={
            "code": "DURABLE_WORKER_STORAGE_FAILURE", "message": str(exc), "retryable": True,
        }) from exc


@app.post("/api/internal/render-worker")
async def internal_render_worker():
    try:
        return await _run_durable_explainer_worker()
    except durable_execution.StorageUnavailable as exc:
        raise HTTPException(status_code=503, detail={
            "code": "DURABLE_WORKER_STORAGE_FAILURE", "message": str(exc), "retryable": True,
        }) from exc


@app.get("/api/cron/render-recovery")
async def render_recovery_cron():
    try:
        store, blob = _durable_components()
        audio_salvage = await asyncio.to_thread(store.rearm_next_portrait_audio_boundary_failure)
        if not audio_salvage:
            audio_salvage = await asyncio.to_thread(store.rearm_next_directed_audio_runtime_failure)
        parent_blob_salvage = None
        parent_archive_salvage = None
        remainder_salvage = None
        disk_salvage = None
        if not audio_salvage:
            parent_blob_salvage = await asyncio.to_thread(
                store.rearm_next_directed_parent_blob_failure)
        if not audio_salvage and not parent_blob_salvage:
            parent_archive_salvage = await asyncio.to_thread(
                store.rearm_next_directed_parent_archive_failure)
        if not audio_salvage and not parent_blob_salvage and not parent_archive_salvage:
            remainder_salvage = await asyncio.to_thread(
                store.rearm_next_directed_remainder_salvage)
        if (not audio_salvage and not parent_blob_salvage and not parent_archive_salvage
                and not remainder_salvage):
            disk_salvage = await asyncio.to_thread(store.requeue_next_directed_storage_error)
        selected = (audio_salvage or parent_blob_salvage or parent_archive_salvage
                    or remainder_salvage or disk_salvage)
        result = await _run_durable_explainer_worker(
            str(selected["id"]) if selected else None)
        cleanup = await asyncio.to_thread(durable_execution.cleanup_orphans, store, blob)
        import hippo_recovery
        recovered_full_film = await asyncio.to_thread(
            hippo_recovery.assemble_if_ready,
            opening_job_id="5937d67c",
            remainder_job_id="54696b1d",
            target_id="hippo-v4-recovered-full",
            blob=blob,
        )
        return {**result, "directed_audio_salvage": audio_salvage or {},
                "directed_parent_blob_salvage": parent_blob_salvage or {},
                "directed_parent_archive_salvage": parent_archive_salvage or {},
                "directed_remainder_salvage": remainder_salvage or {},
                "directed_storage_salvage": disk_salvage or {},
                "recovered_full_film": recovered_full_film,
                "orphan_cleanup": cleanup}
    except durable_execution.StorageUnavailable as exc:
        raise HTTPException(status_code=503, detail={
            "code": "DURABLE_RECOVERY_STORAGE_FAILURE", "message": str(exc), "retryable": True,
        }) from exc


def _pending_review_blocks_resume(output_dir: str) -> bool:
    """Does a PENDING rendered-opening review stop this checkpoint from resuming?

    The run writes human_review.json whenever the rendered opening fails automation, then either
    waits on it (gate live) or logs "[HUMAN REVIEW, advisory] skipping editorial approval" and
    buys the remaining scenes anyway (stable_standard_longform profile, or DIAGNOSTIC_RENDER).
    The resume endpoint used to read only the record, so a run the gate had already waved
    through could die mid-render on a provider outage and then refuse to resume for want of an
    approval the run itself never asked for. Measured on the emperor penguin long-form
    (2026-09-24): 31 of 45 images bought, Anthropic balance exhausted at image 11.2, resume 409.

    The manifest records the profile the run actually used; a pending record blocks only when
    that profile kept the gate live. A rejected record blocks regardless (the caller checks it
    first)."""
    import explainer_pipeline as ep
    if ep._diagnostic_render():
        return False
    manifest_path = os.path.join(output_dir, "generation_manifest.json")
    try:
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError, TypeError):
        return True
    return manifest.get("pipeline_profile") != "stable_standard_longform"


@app.post("/api/explainer/resume/{job_id}")
async def explainer_resume(job_id: str, background_tasks: BackgroundTasks):
    """Resume a job that died mid-render — reuses the on-disk script + already-paid scene
    images/audio from its checkpoint, regenerating only what's missing."""
    _require_render_storage()
    if _durable_execution_required():
        try:
            store, _ = _durable_components()
            row = await asyncio.to_thread(store.get_job, job_id)
            if not row:
                raise HTTPException(status_code=404, detail="Durable job not found")
            if row.get("kind") == "explainer_pilot" or (row.get("request") or {}).get(
                    "controlled_pilot"):
                raise HTTPException(
                    status_code=409,
                    detail="Controlled 45-second pilots never resume into a full video; create a new "
                           "pilot batch for another attempt.")
            if row.get("status") == "human_rejected":
                raise HTTPException(status_code=409, detail="Human editor rejected this opening")
            if row.get("status") == "format_rejected":
                raise HTTPException(status_code=409, detail="Operator rejected the story-format fallback")
            await asyncio.to_thread(
                store.requeue, job_id,
                allowed_statuses=("review_approved", "format_acknowledged", "retry", "storage_error"))
            return {"job_id": job_id, "resuming": True, "durable": True,
                    "dispatch_url": f"/api/explainer/dispatch/{job_id}"}
        except durable_execution.StorageUnavailable as exc:
            raise HTTPException(status_code=503, detail={
                "code": "DURABLE_RESUME_STORAGE_FAILURE", "message": str(exc), "retryable": True,
            }) from exc
        except durable_execution.DurableExecutionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    rec = _get_inprogress(job_id)
    if not rec or not os.path.isdir(rec.get("output_dir", "")):
        raise HTTPException(status_code=404,
                            detail="No resumable checkpoint for this job (missing or expired).")
    if not os.path.exists(os.path.join(rec["output_dir"], "_state.json")):
        raise HTTPException(status_code=409,
                            detail="Checkpoint has no saved script yet — nothing to resume; start fresh.")
    review_path = os.path.join(rec["output_dir"], "human_review.json")
    if os.path.isfile(review_path):
        try:
            with open(review_path) as handle:
                review = json.load(handle)
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=409, detail="Human review record is invalid.") from exc
        if review.get("decision") == "reject":
            raise HTTPException(status_code=409, detail="Human editor rejected this opening.")
        if review.get("decision") != "approve" and _pending_review_blocks_resume(rec["output_dir"]):
            raise HTTPException(
                status_code=409,
                detail="Complete and approve the rendered-opening checklist before resuming.")
    format_review_path = os.path.join(rec["output_dir"], "story_format_review.json")
    if os.path.isfile(format_review_path):
        try:
            with open(format_review_path, encoding="utf-8") as handle:
                format_review = json.load(handle)
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=409, detail="Story-format review record is invalid.") from exc
        if format_review.get("decision") == "reject":
            raise HTTPException(status_code=409, detail="Operator rejected the story-format fallback.")
        if format_review.get("decision") != "accept":
            raise HTTPException(
                status_code=409,
                detail="Acknowledge the Mystery-to-Standard fallback before resuming.")
    request = ExplainerRequest(**rec["request"])
    explainer_jobs[job_id] = {
        "id": job_id, "status": "queued", "events": [],
        "output_path": None, "script": None,
        "title": "", "hook": "", "scene_count": 0, "error": None,
    }
    background_tasks.add_task(run_explainer_task, job_id, request, rec["output_dir"], True)
    return {"job_id": job_id, "resuming": True}


@app.get("/api/explainer/status/{job_id}")
async def explainer_status_stream(job_id: str, request: Request, after: int = 0):
    durable = _durable_execution_required()
    store = None
    if durable:
        try:
            store, _ = _durable_components()
            if not await asyncio.to_thread(store.get_job, job_id):
                raise HTTPException(status_code=404, detail="Job not found")
        except durable_execution.StorageUnavailable as exc:
            raise HTTPException(status_code=503, detail={
                "code": "DURABLE_STATUS_UNAVAILABLE", "message": str(exc), "retryable": True,
            }) from exc
    elif job_id not in explainer_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    async def gen():
        if durable:
            try:
                last_event_id = int(request.headers.get("last-event-id") or 0)
            except ValueError:
                last_event_id = 0
            cursor = max(0, int(after), last_event_id)
            while True:
                try:
                    events = await asyncio.to_thread(store.events, job_id, cursor, 500)
                    for event in events:
                        cursor = max(cursor, int(event["seq"]))
                        yield f"id: {cursor}\ndata: {json.dumps({'type': event['event_type'], 'data': event['data'], 'seq': cursor})}\n\n"
                    row = await asyncio.to_thread(store.get_job, job_id)
                    if not row:
                        yield f"data: {json.dumps({'type': 'error', 'data': 'Durable job disappeared'})}\n\n"
                        break
                    if row["status"] in (
                            "done", "degraded", "error", "awaiting_review", "human_rejected",
                            "format_acknowledgement_required", "format_rejected",
                            "storage_error", "pilot_awaiting_editorial", "pilot_passed",
                            "pilot_failed"):
                        break
                    yield ": keepalive\n\n"
                except durable_execution.StorageUnavailable as exc:
                    yield f"data: {json.dumps({'type': 'storage_error', 'data': str(exc)})}\n\n"
                    break
                await asyncio.sleep(1.0)
            return
        job = explainer_jobs[job_id]
        sent = 0
        ticks = 0
        while True:
            while sent < len(job["events"]):
                yield f"data: {json.dumps(job['events'][sent])}\n\n"
                sent += 1
            if job["status"] in (
                    "done", "error", "degraded", "awaiting_review",
                    "format_acknowledgement_required", "format_rejected",
                    "pilot_awaiting_editorial", "pilot_passed", "pilot_failed"):
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
        if _durable_execution_required():
            try:
                store, _ = _durable_components()
                record = await asyncio.to_thread(store.finished_get, job_id)
                if record and record.get("download_url"):
                    artifact = (record.get("artifacts") or {}).get("video") or {}
                    if artifact.get("access") == "private":
                        _, blob = _durable_components()
                        root = tempfile.mkdtemp(prefix=f"expl_download_{job_id}_")
                        local_path = os.path.join(root, "video.mp4")
                        try:
                            await asyncio.to_thread(blob.download, artifact, local_path)
                        except durable_execution.StorageUnavailable:
                            shutil.rmtree(root, ignore_errors=True)
                            raise
                        safe = "".join(
                            c if c.isalnum() or c in " -_" else "_"
                            for c in record.get("title", "explainer"))
                        return FileResponse(
                            local_path, media_type="video/mp4", filename=f"{safe}.mp4",
                            background=BackgroundTask(
                                shutil.rmtree, root, ignore_errors=True))
                    return RedirectResponse(record["download_url"], status_code=307)
            except durable_execution.StorageUnavailable as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
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
    show_name: str = ""
    season: Optional[int] = Field(default=None, ge=1)
    episode: Optional[int] = Field(default=None, ge=1)
    spoiler_scope: Literal["none", "episode", "season", "series"] = "episode"
    review_angle: Literal["analysis", "character", "theories", "verdict"] = "analysis"


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
                subtitle=request.subtitle, progress_cb=push,
                review_context={"show_name": request.show_name, "season": request.season,
                                "episode": request.episode, "spoiler_scope": request.spoiler_scope,
                                "review_angle": request.review_angle}),
        )
        job.update({
            "status": "degraded" if result.get("status") == "degraded" else "done",
            "output_path": result["output_path"], "title": result.get("title", request.topic),
            "chapters": result.get("chapters"), "duration_sec": result.get("duration_sec"),
            "thumbnail_path": result.get("thumbnail_path"),
            "degraded_reasons": result.get("degraded_reasons", []),
        })
        await _archive_finished(job, job_id, result["output_path"], {
            "title": job["title"], "format": "tv-review", "status": job["status"],
            "show_name": request.show_name, "season": request.season,
            "episode": request.episode, "spoiler_scope": request.spoiler_scope,
            "review_angle": request.review_angle, "duration_sec": result.get("duration_sec"),
        }, {"thumb": result.get("thumbnail_path")})
        job["events"].append({"type": "done", "data": "complete"})
    except Exception as e:
        job["status"] = "error"; job["error"] = str(e)
        job["events"].append({"type": "error", "data": str(e)})


@app.post("/api/tv-review/generate")
@app.post("/api/stateboard/generate", deprecated=True)
async def stateboard_generate(request: StateBoardRequest, background_tasks: BackgroundTasks):
    if not request.topic.strip() or not request.script.strip():
        raise HTTPException(status_code=400, detail="topic and script are required")
    _require_render_storage()
    _sweep_old_temp("sb_")
    job_id = str(uuid.uuid4())[:8]
    output_dir = tempfile.mkdtemp(prefix=f"sb_{job_id}_")
    stateboard_jobs[job_id] = {"id": job_id, "status": "queued", "events": [],
                               "output_path": None, "title": "", "error": None}
    background_tasks.add_task(run_stateboard_task, job_id, request, output_dir)
    return {"job_id": job_id}


@app.get("/api/tv-review/status/{job_id}")
@app.get("/api/stateboard/status/{job_id}", deprecated=True)
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


@app.get("/api/tv-review/download/{job_id}")
@app.get("/api/stateboard/download/{job_id}", deprecated=True)
async def stateboard_download(job_id: str):
    job = stateboard_jobs.get(job_id)
    if not job or not job.get("output_path") or not os.path.exists(job["output_path"]):
        raise HTTPException(status_code=404, detail="Job not found")
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in job.get("title", "tv-review"))
    return FileResponse(job["output_path"], media_type="video/mp4", filename=f"{safe}.mp4")


@app.get("/api/tv-review/thumbnail/{job_id}")
@app.get("/api/stateboard/thumbnail/{job_id}", deprecated=True)
async def stateboard_thumbnail(job_id: str):
    job = stateboard_jobs.get(job_id)
    if not job or not job.get("thumbnail_path") or not os.path.exists(job["thumbnail_path"]):
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(job["thumbnail_path"], media_type="image/jpeg")


def _explainer_text_artifact(job_id: str, kind: str):
    """Resolve a transcript ('txt'), captions ('srt'), description ('desc') or grade path."""
    job_key = {
        "script": "script_path", "txt": "transcript_path", "srt": "srt_path",
        "desc": "description_path",
        "grade": "grade_path", "research": "research_report_path",
        "research-supplement": "research_supplement_path",
        "research-handoff": "research_handoff_path",
        "spine-failure": "spine_failure_path",
        "spine-after-research": "spine_after_research_path",
        "claims": "claim_report_path", "timing": "audio_timing_report_path",
        "evidence-plan": "evidence_plan_path",
        "evidence-validation": "evidence_validation_path",
        "continuity": "continuity_pack_path",
        "motion": "motion_report_path",
        "opening-freeze": "opening_freeze_path",
        "animatic": "animatic_report_path",
        "animatic-preview": "animatic_preview_path",
        "rendered-contract": "rendered_contract_path",
        "rendered-contact-sheet": "rendered_contact_sheet_path",
        "human-review": "human_review_path",
        "story-format-review": "story_format_review_path",
        "generation-manifest": "generation_manifest_path",
        "diagnostic-preview": "diagnostic_preview_path",
        "opening-preview": "first_minute_preview_path", "thumb": "thumbnail_path",
    }[kind]
    job = explainer_jobs.get(job_id)
    if _durable_execution_required() and (not job or not job.get(job_key)):
        try:
            job = _materialize_durable_explainer(job_id)
        except durable_execution.StorageUnavailable:
            raise
    if job and job.get(job_key) and os.path.exists(job[job_key]):
        return job[job_key], job.get("title", "explainer")
    if _durable_execution_required():
        store, blob = _durable_components()
        record = store.finished_get(job_id)
        remote_kind = {"opening-preview": "opening_preview"}.get(kind, kind)
        artifact = (record.get("artifacts") or {}).get(remote_kind) if record else None
        if artifact:
            root = (job or {}).get("_materialized_dir") or tempfile.mkdtemp(prefix=f"expl_read_{job_id}_")
            suffix = Path(artifact.get("pathname") or artifact.get("url") or "").suffix or ".bin"
            local = os.path.join(root, f"finished-{kind}{suffix}")
            blob.download(artifact, local)
            if job is not None:
                job[job_key] = local
            return local, (record or {}).get("title", "explainer")
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
        raise HTTPException(status_code=404, detail="Quality report not found")
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
    base = os.path.basename(path)
    label = ("retention-readiness" if base.startswith("retention_readiness")
             else ("retention-report" if base.startswith("retention_report") else "grade"))
    return FileResponse(path, media_type="text/plain", filename=f"{safe} - {label}.txt")


def _explainer_json_response(job_id: str, kind: str, label: str, *, inline: bool = False):
    path, title = _explainer_text_artifact(job_id, kind)
    if not path:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    if inline:
        try:
            with open(path, encoding="utf-8") as handle:
                return JSONResponse(content=json.load(handle))
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=409, detail=f"Invalid {label}: {exc}") from exc
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
    return FileResponse(path, media_type="application/json", filename=f"{safe} - {label}.json")


@app.get("/api/explainer/story-format-review/{job_id}")
async def explainer_story_format_review(job_id: str):
    return _explainer_json_response(job_id, "story-format-review", "story-format-review")


@app.post("/api/explainer/story-format-review/{job_id}")
async def explainer_record_story_format_review(
        job_id: str, request: ExplainerStoryFormatReviewRequest):
    from longform_retention import apply_story_format_review

    job = explainer_jobs.get(job_id)
    if not job and _durable_execution_required():
        try:
            job = await asyncio.to_thread(_materialize_durable_explainer, job_id)
        except durable_execution.StorageUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    review_path = job.get("story_format_review_path")
    script = job.get("script")
    if not review_path or not os.path.isfile(review_path) or not isinstance(script, dict):
        raise HTTPException(status_code=409, detail="Story-format review artifacts are incomplete")
    try:
        with open(review_path, encoding="utf-8") as handle:
            current = json.load(handle)
        reviewed = apply_story_format_review(
            current, script=script, reviewer=request.reviewer, decision=request.decision)
        with open(review_path, "w", encoding="utf-8") as handle:
            json.dump(reviewed, handle, indent=2, ensure_ascii=False)
        job["status"] = "format_acknowledged" if request.decision == "accept" else "format_rejected"
        resume_after_event_seq = 0
        if _durable_execution_required():
            store, blob = _durable_components()
            runtime = durable_execution.DurableRuntime(
                job_id=job_id, worker_id="story-format-review",
                output_dir=job["_materialized_dir"], store=store, blob=blob)
            await asyncio.to_thread(runtime.checkpoint, "story-format-review", heartbeat=False)
            await asyncio.to_thread(
                store.set_status, job_id, job["status"], result={"story_format_review": reviewed})
            resume_after_event_seq = await asyncio.to_thread(
                store.append_event, job_id,
                "format_acknowledged" if request.decision == "accept" else "format_rejected",
                f"Story-format fallback {request.decision} by {request.reviewer}")
        return {**reviewed, "resume_after_event_seq": resume_after_event_seq}
    except durable_execution.StorageUnavailable as exc:
        raise HTTPException(status_code=503, detail={
            "code": "DURABLE_FORMAT_REVIEW_STORAGE_FAILURE", "message": str(exc),
            "retryable": True,
        }) from exc
    except (OSError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/explainer/generation-manifest/{job_id}")
async def explainer_generation_manifest(job_id: str):
    return _explainer_json_response(job_id, "generation-manifest", "generation-manifest")


@app.get("/api/explainer/research/{job_id}")
async def explainer_research(job_id: str):
    return _explainer_json_response(job_id, "research", "research-dossier")


@app.get("/api/explainer/research-supplement/{job_id}")
async def explainer_research_supplement(job_id: str, inline: bool = False):
    """Download the saved follow-up evidence, including failed validation, without rerunning it.

    Uses the existing studio-session boundary and read-only checkpoint restoration. This is
    diagnostic evidence; downloading it neither accepts its claims nor resumes a paid job.
    """
    return _explainer_json_response(
        job_id, "research-supplement", "research-supplement", inline=inline)


@app.get("/api/explainer/claims/{job_id}")
async def explainer_claims(job_id: str):
    return _explainer_json_response(job_id, "claims", "claim-ledger")


@app.get("/api/explainer/audio-timing/{job_id}")
async def explainer_audio_timing(job_id: str):
    return _explainer_json_response(job_id, "timing", "audio-timing")


@app.get("/api/explainer/evidence-plan/{job_id}")
async def explainer_evidence_plan(job_id: str):
    return _explainer_json_response(job_id, "evidence-plan", "evidence-plan")


@app.get("/api/explainer/evidence-validation/{job_id}")
async def explainer_evidence_validation(job_id: str):
    return _explainer_json_response(job_id, "evidence-validation", "evidence-validation")


@app.get("/api/explainer/continuity/{job_id}")
async def explainer_continuity(job_id: str):
    return _explainer_json_response(job_id, "continuity", "continuity-pack")


@app.get("/api/explainer/motion/{job_id}")
async def explainer_motion(job_id: str):
    return _explainer_json_response(job_id, "motion", "motion-report")


@app.get("/api/explainer/opening-freeze/{job_id}")
async def explainer_opening_freeze(job_id: str):
    return _explainer_json_response(job_id, "opening-freeze", "opening-freeze")


@app.get("/api/explainer/animatic/{job_id}")
async def explainer_animatic(job_id: str):
    return _explainer_json_response(job_id, "animatic", "animatic-gate")


@app.get("/api/explainer/animatic-preview/{job_id}")
async def explainer_animatic_preview(job_id: str):
    path, title = _explainer_text_artifact(job_id, "animatic-preview")
    if not path:
        raise HTTPException(status_code=404, detail="Animatic preview not found")
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
    return FileResponse(path, media_type="video/mp4", filename=f"{safe} - animatic-preview.mp4")


@app.get("/api/explainer/opening-preview/{job_id}")
async def explainer_opening_preview(job_id: str):
    path, title = _explainer_text_artifact(job_id, "opening-preview")
    if not path:
        raise HTTPException(status_code=404, detail="Rendered opening preview not found")
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
    return FileResponse(path, media_type="video/mp4", filename=f"{safe} - opening-preview.mp4")


@app.get("/api/explainer/rendered-contract/{job_id}")
async def explainer_rendered_contract(job_id: str):
    return _explainer_json_response(job_id, "rendered-contract", "rendered-contract")


@app.get("/api/explainer/human-review/{job_id}")
async def explainer_human_review(job_id: str):
    return _explainer_json_response(job_id, "human-review", "human-review")


@app.post("/api/explainer/human-review/{job_id}")
async def explainer_record_human_review(job_id: str, request: ExplainerHumanReviewRequest):
    from longform_rendered_gate import apply_human_review
    from longform_pilots import artifact_completeness, final_pilot_outcome

    job = explainer_jobs.get(job_id)
    if not job and _durable_execution_required():
        try:
            job = await asyncio.to_thread(_materialize_durable_explainer, job_id)
        except durable_execution.StorageUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    required = (job.get("human_review_path"), job.get("rendered_contract_path"),
                job.get("first_minute_preview_path"))
    if not all(path and os.path.isfile(path) for path in required):
        raise HTTPException(status_code=409, detail="Rendered review artifacts are incomplete")
    review_path, report_path, preview_path = required
    try:
        with open(review_path) as handle:
            current = json.load(handle)
        reviewed = apply_human_review(
            current, reviewer=request.reviewer, decision=request.decision,
            checklist=request.checklist, report_path=report_path, preview_path=preview_path)
        with open(review_path, "w") as handle:
            json.dump(reviewed, handle, indent=2, ensure_ascii=False)
        with open(report_path) as handle:
            report = json.load(handle)
        if job.get("controlled_pilot"):
            completeness = artifact_completeness(job["_materialized_dir"])
            outcome = final_pilot_outcome(
                rendered_contract=report,
                human_review=reviewed,
                completeness=completeness,
            )
            outcome_path = os.path.join(job["_materialized_dir"], "pilot_outcome.json")
            _atomic_write_json(outcome_path, outcome)
            job["pilot_outcome_path"] = outcome_path
            job["pilot_outcome"] = outcome
            job["rendered_contract"] = {
                **report,
                "human_review": reviewed,
                "pilot_outcome": outcome,
                "status": "PILOT_PASS" if outcome["pilot_passed"] else "PILOT_FAIL",
                "passed": outcome["pilot_passed"],
                # A 45-second evaluation opening is never a publishable full-video artifact.
                "publishable": False,
            }
            job["status"] = outcome["status"]
            if not _durable_execution_required():
                raise HTTPException(
                    status_code=409,
                    detail="Controlled pilot editorial review requires durable execution")
            store, blob = _durable_components()
            runtime = durable_execution.DurableRuntime(
                job_id=job_id, worker_id="pilot-editorial",
                output_dir=job["_materialized_dir"], store=store, blob=blob)
            checkpoint = await asyncio.to_thread(
                runtime.checkpoint, "pilot-editorial-review", heartbeat=False)
            snapshot = await asyncio.to_thread(
                runtime.persist_pilot_snapshot, "editorial-review",
                metadata={
                    "status": outcome["status"],
                    "pilot_passed": outcome["pilot_passed"],
                    "reviewer": reviewed.get("reviewer"),
                    "automated_score": outcome["automated"]["score"],
                },
                final=True,
                heartbeat=False,
            )
            await asyncio.to_thread(
                store.set_status, job_id, outcome["status"],
                error=None if outcome["pilot_passed"] else "; ".join(outcome["failure_reasons"]),
                result={
                    "human_review": reviewed,
                    "rendered_contract": job["rendered_contract"],
                    "pilot_outcome": outcome,
                    "pilot_snapshot": snapshot,
                    "checkpoint_sha256": checkpoint.get("sha256"),
                })
            resume_after_event_seq = await asyncio.to_thread(
                store.append_event, job_id, outcome["status"],
                f"Controlled pilot editorial decision recorded by {request.reviewer}",
                {"pilot_passed": outcome["pilot_passed"],
                 "artifact_count": snapshot.get("artifact_count")})
            return {
                **reviewed,
                "pilot_outcome": outcome,
                "resume_allowed": False,
                "resume_after_event_seq": resume_after_event_seq,
            }
        # Keep the reviewed report byte-identical. Resume re-runs the deterministic/vision gate,
        # verifies this approval against both frozen hashes, and only then writes the final PASS.
        job["rendered_contract"] = {**report, "human_review": reviewed,
                                    "status": "HUMAN_APPROVED_RESUME_REQUIRED"
                                    if request.decision == "approve" else "HUMAN_REJECT"}
        job["status"] = ("review_approved" if request.decision == "approve"
                         else "human_rejected")
        resume_after_event_seq = 0
        if _durable_execution_required():
            store, blob = _durable_components()
            runtime = durable_execution.DurableRuntime(
                job_id=job_id, worker_id="human-review",
                output_dir=job["_materialized_dir"], store=store, blob=blob)
            await asyncio.to_thread(
                runtime.checkpoint, "human-review", heartbeat=False)
            await asyncio.to_thread(
                store.set_status, job_id, job["status"],
                result={"human_review": reviewed,
                        "rendered_contract": job["rendered_contract"]})
            resume_after_event_seq = await asyncio.to_thread(
                store.append_event, job_id,
                "review_approved" if request.decision == "approve" else "human_rejected",
                f"Human review {request.decision} by {request.reviewer}")
        return {**reviewed, "resume_after_event_seq": resume_after_event_seq}
    except durable_execution.StorageUnavailable as exc:
        raise HTTPException(status_code=503, detail={
            "code": "DURABLE_REVIEW_STORAGE_FAILURE", "message": str(exc), "retryable": True,
        }) from exc
    except (OSError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/explainer/rendered-contact-sheet/{job_id}")
async def explainer_rendered_contact_sheet(job_id: str):
    path, title = _explainer_text_artifact(job_id, "rendered-contact-sheet")
    if not path:
        raise HTTPException(status_code=404, detail="Rendered contact sheet not found")
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
    return FileResponse(path, media_type="image/jpeg", filename=f"{safe} - rendered-contact-sheet.jpg")


@app.get("/api/explainer/diagnostic-preview/{job_id}")
async def explainer_diagnostic_preview(job_id: str):
    path, title = _explainer_text_artifact(job_id, "diagnostic-preview")
    if not path:
        raise HTTPException(status_code=404, detail="Rejected diagnostic preview not found")
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
    return FileResponse(path, media_type="video/mp4", filename=f"{safe} - REJECTED-DIAGNOSTIC.mp4")


@app.get("/api/explainer/thumbnail/{job_id}")
async def explainer_thumbnail(job_id: str):
    job = explainer_jobs.get(job_id)
    path = title = None
    if job and job.get("thumbnail_path") and os.path.exists(job["thumbnail_path"]):
        path, title = job["thumbnail_path"], job.get("title", "thumbnail")
    else:
        if _durable_execution_required():
            path, title = _explainer_text_artifact(job_id, "thumb")
        entry = _load_finished(job_id)
        if not path and entry and entry.get("thumb_path") and os.path.exists(entry["thumb_path"]):
            path, title = entry["thumb_path"], entry.get("title", "thumbnail")
    if not path:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
    return FileResponse(path, media_type="image/jpeg", filename=f"{safe} - thumbnail.jpg")


@app.get("/api/explainer/script/{job_id}")
async def explainer_script(job_id: str):
    if job_id not in explainer_jobs and _durable_execution_required():
        try:
            await asyncio.to_thread(_materialize_durable_explainer, job_id)
        except durable_execution.StorageUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    if job_id not in explainer_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = explainer_jobs[job_id]
    script = job.get("script")
    if not script and _durable_execution_required():
        try:
            path, _ = await asyncio.to_thread(_explainer_text_artifact, job_id, "script")
            if path:
                with open(path) as handle:
                    script = (json.load(handle) or {}).get("script")
                job["script"] = script
        except durable_execution.StorageUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (OSError, ValueError, TypeError):
            script = None
    if not script:
        raise HTTPException(status_code=400, detail="Script not yet generated")
    return script


# ─── Serve frontend ─────────────────────────────────────────────────────────────

import finished_api
finished_api.mount(app, FINISHED_DIR, STATIC_DIR)

@app.get("/")
def _serve_index():
    # Serve the SPA shell with no-cache so a browser never shows a stale UI after an
    # edit (a cached index.html made a newly-added form field look "removed"). Other
    # static assets below keep normal caching. Registered before the mount so it wins for "/".
    resp = FileResponse(str(STATIC_DIR / "index.html"), media_type="text/html")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    # Defaults: localhost-only (not 0.0.0.0) so an un-firewalled box isn't an open wallet, and
    # reload ON (dev convenience). For real renders run `RELOAD=0 python app.py` — reload=True
    # SIGTERMs the worker on any .py save and KILLS an in-flight render. To expose the server,
    # set HOST=0.0.0.0 AND APP_PASSWORD (the warning below fires if you forget).
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    reload = os.environ.get("RELOAD", "1") == "1"
    if host not in ("127.0.0.1", "localhost", "::1") and not private_access.auth_configured():
        print("⚠ SECURITY: binding to a non-loopback host with NO APP_PASSWORD — anyone who "
              "can reach this port can spend provider credits. Set APP_PASSWORD.")
    if reload:
        print("⚠ RELOAD=1: editing any .py during a render will KILL it. Use RELOAD=0 for real runs.")
    uvicorn.run("app:app", host=host, port=port, reload=reload)
