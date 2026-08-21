"""Authenticated finished-video library backed by Postgres/Blob with a local fallback."""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

import db


def _local_index(finished_dir: str) -> dict:
    try:
        with open(os.path.join(finished_dir, "index.json"), encoding="utf-8") as stream:
            return json.load(stream)
    except Exception:
        return {}


def _local_record(video_id: str, raw: dict) -> dict:
    artifacts = {}
    if raw.get("path") and os.path.isfile(raw["path"]):
        artifacts["video"] = {"kind": "video", "local_path": raw["path"],
                              "size_bytes": os.path.getsize(raw["path"]),
                              "content_type": "video/mp4"}
    for key, value in raw.items():
        if key.endswith("_path") and value and os.path.isfile(value):
            kind = key[:-5]
            artifacts[kind] = {"kind": kind, "local_path": value}
    return {
        "id": video_id,
        "title": raw.get("title") or video_id,
        "format": raw.get("format") or raw.get("template") or "video",
        "status": raw.get("status") or "done",
        "size_bytes": (artifacts.get("video") or {}).get("size_bytes"),
        "thumbnail_url": None,
        "artifacts": artifacts,
        "metadata": {k: v for k, v in raw.items() if not k.endswith("_path") and k != "path"},
        "created_at": None,
        "storage": "local",
    }


def _get(video_id: str, finished_dir: str) -> dict | None:
    if db.db_enabled():
        record = db.finished_video_get(video_id)
        if record:
            record["storage"] = "blob"
            return record
    raw = _local_index(finished_dir).get(video_id)
    return _local_record(video_id, raw) if raw else None


def mount(app: FastAPI, finished_dir: str, static_dir: Path) -> None:
    @app.get("/finished")
    async def finished_page():
        response = FileResponse(str(static_dir / "finished.html"), media_type="text/html")
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

    @app.get("/api/finished")
    async def finished_list(limit: int = 100, offset: int = 0, q: str = ""):
        rows = db.finished_videos_list(limit=limit, offset=offset, query=q) if db.db_enabled() else []
        if not rows:
            rows = [_local_record(video_id, raw)
                    for video_id, raw in _local_index(finished_dir).items()]
            if q:
                needle = q.lower()
                rows = [row for row in rows if needle in row["title"].lower()
                        or needle in row["id"].lower()]
            rows = rows[offset:offset + max(1, min(limit, 200))]
        for row in rows:
            row.setdefault("storage", "blob" if row.get("video_url") else "local")
        return {"videos": rows, "count": len(rows), "limit": limit, "offset": offset}

    @app.get("/api/finished/{video_id}")
    async def finished_detail(video_id: str):
        record = _get(video_id, finished_dir)
        if not record:
            raise HTTPException(status_code=404, detail="Finished video not found")
        return record

    @app.get("/api/finished/{video_id}/artifact/{kind}")
    async def finished_artifact(video_id: str, kind: str, download: bool = False):
        record = _get(video_id, finished_dir)
        if not record:
            raise HTTPException(status_code=404, detail="Finished video not found")
        artifact = (record.get("artifacts") or {}).get(kind)
        if not artifact:
            raise HTTPException(status_code=404, detail=f"Artifact {kind!r} not found")
        remote = artifact.get("download_url") if download else artifact.get("url")
        if remote:
            return RedirectResponse(remote, status_code=307)
        local_path = artifact.get("local_path")
        if local_path and os.path.isfile(local_path):
            filename = os.path.basename(local_path) if download else None
            return FileResponse(local_path, media_type=artifact.get("content_type"), filename=filename)
        raise HTTPException(status_code=404, detail="Artifact bytes are unavailable")
