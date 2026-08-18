"""UI adapter for the HotD pipeline: mount the package's stages as HTTP endpoints.

Thin on purpose. All the logic lives in hotd/; this only exposes it, so the UI and the CLI cannot
drift apart. Every endpoint runs the same functions `python -m hotd ...` runs.

    from hotd_api import mount
    mount(app)

Endpoints
    GET  /api/hotd/episodes                 list episode modules and whether each has a script
    POST /api/hotd/scaffold                 spec markdown -> episode skeleton (no spend)
    POST /api/hotd/plan                     validate + report shot ledger and costs (no spend)
    POST /api/hotd/build                    render, gate, package (background job)
    GET  /api/hotd/status/{job_id}          job progress
    GET  /api/hotd/download/{job_id}        finished mp4
"""
from __future__ import annotations
import glob
import json
import os
import threading
import traceback
import uuid

from fastapi import BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

hotd_jobs: dict = {}
_lock = threading.Lock()


class ScaffoldRequest(BaseModel):
    spec_path: str
    slug: str | None = None
    prev_pack: str | None = None
    force: bool = False


class EpisodeRequest(BaseModel):
    episode: str                      # path to an episode module, e.g. "episodes/s3e4.py"
    animate: bool = False
    max_clips: int = 10
    cap_usd: float = 4.0
    loose_timing: bool = False


def _event(job_id, msg):
    with _lock:
        hotd_jobs[job_id]["events"].append(msg)


def _run_build(job_id, req: EpisodeRequest):
    from hotd import deliver as D, gates, playlists as PL, render as R
    from hotd.cli import _cfg_mtime, _prepare, load_episode

    job = hotd_jobs[job_id]
    try:
        job["status"] = "preflight"
        mod = load_episode(req.episode)
        ep, script, plrep = _prepare(mod)
        info = gates.preflight(ep, script,
                               block_of=lambda i: PL.block_of(i, mod.POOLS,
                                              getattr(mod, "BLOCK_ALIASES", None)),
                               word_band=ep.word_band,
                               subject_words=getattr(mod, "SUBJECT_WORDS", None),
                               strict_target_s=not req.loose_timing
                               and not plrep.get("exact"))
        _event(job_id, f"preflight ok: {info}")

        anim = None
        if req.animate:
            job["status"] = "animating"
            from hotd import animate as AN
            plan = AN.plan(ep, script, ep.playlists, max_clips=req.max_clips)
            _event(job_id, f"animating {plan['n']} plates (est ${plan['est_usd']})")
            anim, fails = AN.generate(ep, plan["jobs"], cap_usd=req.cap_usd,
                                      progress=lambda m: _event(job_id, m.strip()))
            if fails:
                _event(job_id, f"not animated (kept as stills): {[f[0] for f in fails]}")

        job["status"] = "rendering"
        rep = R.main(ep, cfg_mtime=_cfg_mtime(os.path.abspath(req.episode), ep), animate=anim)
        job["shots"] = rep["visuals"]
        job["animated_shots"] = rep.get("animated_shots", 0)

        job["status"] = "gating"
        post = gates.postflight(ep, rep, duration_band_min=ep.duration_band_min)
        job["gates"] = {"motion_passed": post["motion"]["passed"],
                        "frozen_shots": len(post["motion"]["frozen"]),
                        "median_displacement": post["motion"]["median_displacement"],
                        "audio": post["audio"],
                        "duration_s": post.get("duration_s")}

        job["status"] = "packaging"
        if ep.chapter_groups:
            ep.meta["chapters"] = list(ep.chapter_groups)
        else:
            order, seen = [], set()
            for s in script["segments"]:
                b = PL.block_of(s["id"], mod.POOLS, getattr(mod, "BLOCK_ALIASES", None))
                if b not in seen:
                    seen.add(b); order.append(b)
            ep.meta["chapters"] = [
                (ep.chapter_titles.get(b, b.replace("_", " ").title()),
                 [s["id"] for s in script["segments"] if PL.block_of(s["id"], mod.POOLS, getattr(mod, "BLOCK_ALIASES", None)) == b])
                for b in order]
        D.deliver(ep, ep.meta)
        gates.package_gate(ep)

        job["video_path"] = os.path.join(ep.out, f"{ep.slug}.mp4")
        job["out_dir"] = ep.out
        job["status"] = "done"
        _event(job_id, "done")
    except gates.GateFailure as e:
        job["status"] = "gate_failed"
        job["error"] = str(e)
        _event(job_id, f"GATE FAILED: {e}")
    except Exception as e:
        job["status"] = "error"
        job["error"] = f"{type(e).__name__}: {e}"
        job["traceback"] = traceback.format_exc()
        _event(job_id, job["error"])


def mount(app):
    @app.get("/api/hotd/episodes")
    async def hotd_episodes():
        out = []
        for p in sorted(glob.glob("episodes/*.py")):
            try:
                from hotd.cli import load_episode
                mod = load_episode(p)
                ep = mod.episode()
                out.append({"module": p, "slug": ep.slug, "out": ep.out,
                            "has_script": os.path.exists(ep.script),
                            "rendered": os.path.exists(os.path.join(ep.out, f"{ep.slug}.mp4")),
                            "blocks": len(getattr(mod, "POOLS", {})),
                            "states": len(getattr(mod, "STATES", {}))})
            except Exception as e:
                out.append({"module": p, "error": f"{type(e).__name__}: {e}"})
        return {"episodes": out}

    @app.post("/api/hotd/scaffold")
    async def hotd_scaffold(req: ScaffoldRequest):
        from hotd import scaffold as S
        if not os.path.exists(req.spec_path):
            raise HTTPException(404, f"no spec at {req.spec_path}")
        info = S.parse(req.spec_path)
        written = None
        if req.slug:
            kw = {"force": req.force}
            if req.prev_pack:
                kw["pack_prev"] = req.prev_pack
            try:
                written = S.write(info, req.slug,
                                  req.prev_pack or "house-of-dragons/"
                                  "house_of_the_dragon_s3e4_complete_asset_pack/images",
                                  force=req.force)
            except SystemExit as e:
                raise HTTPException(409, str(e))
        return {"parsed": info, "report": S.report(info), "written": written}

    @app.post("/api/hotd/plan")
    async def hotd_plan(req: EpisodeRequest):
        """Validate and cost an episode. No spend, no render -- safe to call from the UI freely."""
        from hotd import animate as AN, gates, generate as GEN, playlists as PL, render as R
        from hotd.cli import _prepare, load_episode
        try:
            mod = load_episode(req.episode)
            ep, script, plrep = _prepare(mod)
            info = gates.preflight(ep, script,
                                   block_of=lambda i: PL.block_of(i, mod.POOLS,
                                              getattr(mod, "BLOCK_ALIASES", None)),
                                   word_band=ep.word_band,
                                   subject_words=getattr(mod, "SUBJECT_WORDS", None),
                                   strict_target_s=not req.loose_timing
                                   and not plrep.get("exact"))
        except gates.GateFailure as e:
            return {"ok": False, "gate_failure": str(e)}
        except SystemExit as e:
            return {"ok": False, "error": str(e)}
        led = R.main(ep, plan_only=True)
        images = (GEN.plan(mod.SIGIL_PROMPTS, mod.LOCATION_PROMPTS, ep.index())
                  if hasattr(mod, "SIGIL_PROMPTS") else None)
        anim = AN.plan(ep, script, ep.playlists, max_clips=req.max_clips)
        return {"ok": True, "preflight": info,
                "shots": led["visuals"], "cuts": led["cuts"][:400],
                "thin_pools": PL.thin_pools(plrep),
                "images_to_generate": images,
                "animation_plan": {"n": anim["n"], "est_usd": anim["est_usd"],
                                   "jobs": [{k: j[k] for k in
                                             ("asset", "screen_seconds", "from_segment", "prompt")}
                                            for j in anim["jobs"]]}}

    @app.post("/api/hotd/build")
    async def hotd_build(req: EpisodeRequest, background_tasks: BackgroundTasks):
        if not os.path.exists(req.episode):
            raise HTTPException(404, f"no episode module at {req.episode}")
        job_id = str(uuid.uuid4())[:8]
        hotd_jobs[job_id] = {"id": job_id, "status": "queued", "events": [],
                            "episode": req.episode, "animate": req.animate,
                            "video_path": None, "error": None}
        background_tasks.add_task(_run_build, job_id, req)
        return {"job_id": job_id}

    @app.get("/api/hotd/status/{job_id}")
    async def hotd_status(job_id: str):
        if job_id not in hotd_jobs:
            raise HTTPException(404, "job not found")
        return hotd_jobs[job_id]

    @app.get("/api/hotd/download/{job_id}")
    async def hotd_download(job_id: str):
        job = hotd_jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        p = job.get("video_path")
        if not (p and os.path.exists(p)):
            raise HTTPException(409, f"not ready (status={job['status']})")
        return FileResponse(p, media_type="video/mp4", filename=os.path.basename(p))

    return app
