"""Local-media engine jobs on ReelForge's existing durable queue and artifact store.

No provider generation is permitted by this v1 contract. A studio session may queue
bounded local assembly directly; it cannot use this route to authorize paid calls.
"""
from __future__ import annotations

import json
import math
import re
import tempfile
import uuid
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .storyboard import Storyboard

JOB_KIND = "video_engine"
VERSION = "local-engine-jobs-v1"
PINS = {
    "moneyprinterturbo": "3d5f4e421927d61f3eac729cf4b711ac0b69d688",
    "openshorts": "4b2cf58922587ecb17b990a9575e46320bdb3118",
    "motion_canvas": "3.17.2",
}
Id = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")]
Seconds = Annotated[float, Field(ge=0, le=86400, allow_inf_nan=False, strict=True)]
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_INPUT_BYTES = 1024 * 1024 * 1024


class EngineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: uuid.UUID
    engine: Literal["moneyprinterturbo", "motion_canvas", "openshorts"]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    source_video_id: Id | None = None
    material_video_ids: list[Id] = Field(default_factory=list, max_length=12)
    start_sec: Seconds = 0
    end_sec: Seconds | None = None
    aspect_ratio: Literal["9:16", "16:9"] = "9:16"
    storyboard: Storyboard | None = None
    silent: bool = False
    source_rights_confirmed: Literal[True]

    @model_validator(mode="after")
    def supported_scope(self):
        if self.engine == "openshorts":
            if not self.source_video_id or self.end_sec is None:
                raise ValueError("Repurposing requires a source video and explicit start/end")
            if not 0 < self.end_sec - self.start_sec <= 90:
                raise ValueError("A repurposed clip must be 0–90 seconds, exclusively positive")
            if self.silent or self.storyboard or self.material_video_ids:
                raise ValueError("Repurposing preserves source audio; no storyboard/material overrides")
        else:
            if self.start_sec != 0 or self.end_sec is not None:
                raise ValueError("Only repurposing accepts a source time span")
            if self.engine == "moneyprinterturbo":
                if not self.source_video_id or not self.material_video_ids or self.silent or self.storyboard:
                    raise ValueError("Stock assembly needs saved narration video and ordered saved materials")
                if self.aspect_ratio != "9:16":
                    raise ValueError("Stock Short v1 requires portrait output")
            else:
                if self.material_video_ids or self.storyboard is None:
                    raise ValueError("Motion Canvas needs a storyboard, not material-video overrides")
                if self.storyboard.flow != "motion_scene" or self.storyboard.aspect_ratio != self.aspect_ratio:
                    raise ValueError("Motion board flow/aspect must match the request")
                if self.storyboard.shots[-1].end > 90:
                    raise ValueError("Motion scene jobs are limited to 90 seconds")
                if any(s.treatment != "motion_canvas" or s.end - s.start < 1 for s in self.storyboard.shots):
                    raise ValueError("Use Motion Canvas shots at least one second long")
                if any(len(value) > 180 for shot in self.storyboard.shots
                       for value in (shot.first_frame, shot.change, shot.last_frame)):
                    raise ValueError("Motion template labels are limited to 180 characters")
                if bool(self.source_video_id) == self.silent:
                    raise ValueError("Choose existing narration OR explicitly silent motion")
        return self


def digest(value: dict) -> str:
    from durable_execution import canonical_hash
    return canonical_hash(value)


def _descriptor(record: dict, kind: str) -> dict:
    if record.get("status") not in {"done", "ready"}:
        raise ValueError("Only delivered finished sources can be reused")
    artifact = (record.get("artifacts") or {}).get(kind) or {}
    sha, size = artifact.get("sha256"), artifact.get("size_bytes")
    if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha):
        raise ValueError(f"Source {kind} has no durable checksum; re-index the source first")
    if type(size) is not int or not 0 < size <= MAX_FILE_BYTES:
        raise ValueError(f"Source {kind} size is missing or exceeds 512 MiB")
    parsed = urlsplit(artifact.get("url") or "")
    if (parsed.scheme != "https" or not (parsed.hostname or "").endswith(".blob.vercel-storage.com")
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("Source must be a stored Blob artifact, not an arbitrary URL or local path")
    return {"video_id": record["id"], "kind": kind, "sha256": sha, "size_bytes": size}


def freeze(request: EngineRequest, store) -> dict:
    """Resolve server-side references without downloading media or calling providers."""
    records = {}
    def get(video_id):
        if video_id not in records:
            records[video_id] = store.finished_get(video_id) or {}
        record = records[video_id]
        if record.get("id") != video_id:
            raise ValueError("Finished source does not exist")
        return record
    inputs = {}
    if request.source_video_id:
        source = get(request.source_video_id)
        inputs["source"] = _descriptor(source, "video")
        # Reuse captions only where the source audio is unchanged. Motion uses
        # explicitly authored board text and requires separate editorial review.
        if request.engine != "motion_canvas" and "srt" in (source.get("artifacts") or {}):
            inputs["captions"] = _descriptor(source, "srt")
    for i, video_id in enumerate(request.material_video_ids):
        inputs[f"material-{i}"] = _descriptor(get(video_id), "video")
    if sum(item["size_bytes"] for item in inputs.values()) > MAX_INPUT_BYTES:
        raise ValueError("Combined inputs exceed 1 GiB")
    body = {"version": VERSION, "engine_revision": PINS[request.engine],
            "request": request.model_dump(mode="json"), "inputs": inputs,
            "provider_budget_usd": 0, "publish": False}
    return {**body, "sha256": digest(body)}


def queue(request: EngineRequest, store) -> dict:
    job_id = "engine-" + request.request_id.hex
    existing = store.get_job(job_id)
    if existing:
        if existing.get("kind") != JOB_KIND or (existing.get("request") or {}).get("request") != request.model_dump(mode="json"):
            raise ValueError("Request ID already belongs to a different immutable job")
        return existing
    payload = freeze(request, store)
    job = store.enqueue(job_id=job_id, kind=JOB_KIND, request=payload, max_cost_usd=0,
                        pipeline_version=VERSION, output_prefix=f"jobs/{job_id}")
    if job.get("request") != payload:
        raise ValueError("Request ID collision; use a new request ID for changed inputs")
    return job


def validate_payload(job: dict) -> tuple[EngineRequest, dict]:
    body = dict(job["request"])
    expected = body.pop("sha256", None)
    if not isinstance(expected, str) or digest(body) != expected:
        raise ValueError("Queued engine request changed")
    request = EngineRequest.model_validate(body["request"])
    if (job.get("kind") != JOB_KIND or body.get("version") != VERSION
            or body.get("engine_revision") != PINS[request.engine]
            or job.get("pipeline_version") != VERSION or float(job.get("max_cost_usd", -1)) != 0
            or body.get("provider_budget_usd") != 0 or body.get("publish") is not False):
        raise ValueError("Unsupported engine version or spending scope")
    if job["id"] != "engine-" + request.request_id.hex:
        raise ValueError("Job identity differs from the immutable request")
    allowed_roles = {f"material-{i}" for i in range(len(request.material_video_ids))}
    if request.source_video_id:
        allowed_roles.add("source")
        if request.engine != "motion_canvas": allowed_roles.add("captions")
    inputs = body.get("inputs")
    if not isinstance(inputs, dict) or set(inputs) - allowed_roles:
        raise ValueError("Unsupported input role in the frozen request")
    expected_ids = {f"material-{i}": value for i, value in enumerate(request.material_video_ids)}
    if request.source_video_id: expected_ids["source"] = request.source_video_id
    if "captions" in inputs: expected_ids["captions"] = request.source_video_id
    if set(inputs) != set(expected_ids): raise ValueError("Frozen input set is incomplete")
    for role, item in inputs.items():
        if (not isinstance(item, dict) or set(item) != {"video_id", "kind", "sha256", "size_bytes"}
                or item["video_id"] != expected_ids[role]
                or item["kind"] != ("srt" if role == "captions" else "video")
                or not isinstance(item["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
                or type(item["size_bytes"]) is not int or not 0 < item["size_bytes"] <= MAX_FILE_BYTES):
            raise ValueError("Invalid frozen source descriptor")
    if sum(item["size_bytes"] for item in inputs.values()) > MAX_INPUT_BYTES:
        raise ValueError("Frozen sources exceed the input byte limit")
    return request, body


def public_job(job: dict) -> dict:
    payload = job.get("request") or {}
    request = payload.get("request") or {}
    job_id = job["id"]
    return {"id": job_id, "status": job.get("status"), "engine": request.get("engine"),
            "title": request.get("title"), "request_sha256": payload.get("sha256"),
            "parent_video_id": request.get("source_video_id"), "attempts": job.get("attempts", 0),
            "provider_spend_usd": float(job.get("spent_cost_usd") or 0),
            "error": job.get("error"),
            "artifacts": [{"kind": kind, "path": f"/api/finished/{job_id}/artifact/{kind}"}
                          for kind in sorted((job.get("result") or {}).get("artifacts") or {})],
            "status_path": f"/api/video-engines/jobs/{job_id}",
            "dispatch_path": f"/api/video-engines/jobs/{job_id}/dispatch"}


def _recover_local_stage(store, job_id, worker_id, key, request_hash):
    """Only reclaim our known zero-cost stage under the current job lease.

    Never use a blanket reset of running stages: paid acceptance stays ambiguous.
    """
    with store._tx() as (_, cur):
        cur.execute("SELECT lease_owner FROM generation_jobs WHERE id=%s FOR UPDATE", (job_id,))
        row = cur.fetchone()
        if not row or row[0] != worker_id:
            from durable_execution import LeaseLost
            raise LeaseLost("Engine worker no longer owns its lease")
        cur.execute("""UPDATE generation_stages SET status='retry',updated_at=now()
            WHERE job_id=%s AND stage_key=%s AND request_hash=%s AND provider='local_engine_v1'
            AND status='running' AND reserved_cost_usd=0 AND COALESCE(actual_cost_usd,0)=0""",
                    (job_id, key, request_hash))


def run_claimed(job: dict, store, blob, *, renderer=None, recover_stage=_recover_local_stage) -> dict:
    """Use existing DurableRuntime stage cache and atomic finished-video finalization."""
    from durable_execution import DurableRuntime, LeaseLost, maintain_lease, file_sha256
    from . import runner
    worker_id, job_id = job["lease_owner"], job["id"]
    try:
        request, body = validate_payload(job)
        with tempfile.TemporaryDirectory(prefix="rf-engine-") as directory:
            root = Path(directory)
            rt = DurableRuntime(job_id, worker_id, str(root), store, blob)
            with maintain_lease(rt):
                paths = {}
                required = sum(item["size_bytes"] for item in body["inputs"].values())
                runner.check_disk(root, required)
                for role, descriptor in body["inputs"].items():
                    live = store.finished_get(descriptor["video_id"]) or {}
                    if _descriptor(live, descriptor["kind"]) != descriptor:
                        raise ValueError("A source artifact changed after queueing")
                    suffix = ".srt" if descriptor["kind"] == "srt" else ".mp4"
                    path = root / (role + suffix)
                    blob.download(live["artifacts"][descriptor["kind"]], str(path))
                    if path.stat().st_size != descriptor["size_bytes"] or file_sha256(path) != descriptor["sha256"]:
                        raise ValueError("Source bytes do not match their frozen manifest")
                    paths[role] = str(path)
                timing = runner.inspect_inputs(request, paths)
                stage_request = {"engine_payload_sha256": job["request"]["sha256"]}
                key = "engine-render:" + digest(stage_request)[:32]
                recover_stage(store, job_id, worker_id, key, digest(stage_request))
                out = root / "video.mp4"
                def encode(_key):
                    (renderer or runner.render)(request, paths, out)
                    return runner.verify_output(out, request, timing), 0.0
                result, _, reused = rt.paid_file(stage_key=key, provider="local_engine_v1",
                    request=stage_request, estimated_cost=0, output_path=str(out), operation=encode)
                # Re-verify restored bytes too; a cached stage is not permission to skip inspection.
                technical = runner.verify_output(out, request, timing)
                provenance = {"version": VERSION, "engine": request.engine,
                    "engine_revision": body["engine_revision"], "source_artifacts": body["inputs"],
                    "parent_video_id": request.source_video_id, "start_sec": request.start_sec,
                    "end_sec": request.end_sec, "source_rights_confirmed": True,
                    "request_sha256": job["request"]["sha256"], "stage_reused": reused,
                    "external_provider_calls": 0, "scope": "local_media_only", "technical": technical,
                    "editorial_status": "needs_review", "publishable": False}
                manifest = root / "provenance.json"
                manifest.write_text(json.dumps(provenance, indent=2))
                extras = {"provenance": str(manifest)}
                if request.storyboard:
                    board = root / "storyboard.json"
                    board.write_text(request.storyboard.model_dump_json(indent=2))
                    extras["storyboard"] = str(board)
                if "captions" in paths:
                    captions = root / "captions.srt"
                    runner.copy_captions(paths["captions"], captions, request, timing)
                    extras["srt"] = str(captions)
                thumb = root / "thumb.jpg"
                runner.thumbnail(out, thumb)
                extras["thumb"] = str(thumb)
                rt.finalize(str(out), {"title": request.title, "format": JOB_KIND, "status": "done",
                    "engine": request.engine, "parent_video_id": request.source_video_id,
                    "duration_sec": technical["duration_sec"], "technical_status": "completed",
                    "editorial_status": "needs_review", "publishable": False}, extras)
                return public_job(store.get_job(job_id))
    except LeaseLost:
        raise
    except Exception as exc:
        status = "error" if isinstance(exc, ValueError) or job.get("attempts", 1) >= job.get("max_attempts", 1) else "retry"
        # No file paths, raw subprocess stderr, source URLs or credentials in the browser status.
        store.set_status(job_id, status, error=f"Engine {type(exc).__name__}; inspect worker logs", worker_id=worker_id)
        store.append_event(job_id, status, "Engine job failed; source artifacts remain unchanged")
        import logging
        logging.getLogger(__name__).exception("Engine job %s failed", job_id)
        return public_job(store.get_job(job_id))
