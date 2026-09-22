"""Studio-authenticated engine endpoints; no second queue, login, or publishing API."""
import asyncio
import uuid
from fastapi import FastAPI, HTTPException, Request
from durable_execution import PostgresStore, BlobStore, StorageUnavailable
from .jobs import EngineRequest, JOB_KIND, PINS, queue, public_job, run_claimed
from .runner import readiness


def components():
    return PostgresStore(), BlobStore()


def same_origin(request: Request):
    # Signed studio cookies already apply; also reject browser cross-origin writes.
    from urllib.parse import urlsplit
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.url.netloc:
        raise HTTPException(403, "Cross-origin engine mutation is not allowed")


def mount(app: FastAPI):
    @app.get("/api/video-engines")
    async def capabilities():
        states = await asyncio.gather(*(asyncio.to_thread(readiness, e) for e in PINS))
        return {"engines": states, "scope": "local_media_only", "worker_command": "python -m bolt_video.engines.worker --poll"}

    @app.post("/api/video-engines/jobs", status_code=202)
    async def create(body: EngineRequest, request: Request):
        same_origin(request)
        try:
            store, _ = components()
            return public_job(await asyncio.to_thread(queue, body, store))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        except StorageUnavailable:
            raise HTTPException(503, "Durable queue and Blob storage must be configured") from None

    @app.get("/api/video-engines/jobs/{job_id}")
    async def status(job_id: str):
        try:
            store, _ = components()
            job = await asyncio.to_thread(store.get_job, job_id)
        except StorageUnavailable:
            raise HTTPException(503, "Durable storage is unavailable") from None
        if not job or job.get("kind") != JOB_KIND:
            raise HTTPException(404, "Engine job not found")
        return public_job(job)

    @app.post("/api/video-engines/jobs/{job_id}/dispatch")
    async def dispatch(job_id: str, request: Request):
        same_origin(request)
        try:
            store, blob = components()
            job = await asyncio.to_thread(store.get_job, job_id)
            if not job or job.get("kind") != JOB_KIND:
                raise HTTPException(404, "Engine job not found")
            if job.get("status") == "done":
                return {"claimed": False, "job": public_job(job)}
            state = await asyncio.to_thread(readiness, job["request"]["request"]["engine"])
            if not state["ready_on_this_host"]:
                return {"claimed": False, "worker_required": True, "job": public_job(job),
                        "message": "Queued for a dedicated engine worker; this API host cannot render it"}
            claimed = await asyncio.to_thread(store.claim, job_id=job_id, kind=JOB_KIND,
                                              worker_id="engine-" + uuid.uuid4().hex)
            if not claimed:
                return {"claimed": False, "job": public_job(await asyncio.to_thread(store.get_job, job_id))}
            return {"claimed": True, "job": await asyncio.to_thread(run_claimed, claimed, store, blob)}
        except StorageUnavailable:
            raise HTTPException(503, "Durable worker storage is unavailable") from None
