"""Authenticated finished-video library backed by Postgres/Blob with a local fallback."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from starlette.background import BackgroundTask

import db
import artifact_store
from durable_execution import BlobStore, PostgresStore, StorageUnavailable


def _local_index(finished_dir: str) -> dict:
    try:
        with open(os.path.join(finished_dir, "index.json"), encoding="utf-8") as stream:
            return json.load(stream)
    except Exception:
        return {}


def _local_record(video_id: str, raw: dict) -> dict:
    artifacts = {}
    mtime = 0.0
    if raw.get("path") and os.path.isfile(raw["path"]):
        artifacts["video"] = {"kind": "video", "local_path": raw["path"],
                              "size_bytes": os.path.getsize(raw["path"]),
                              "content_type": "video/mp4"}
        mtime = os.path.getmtime(raw["path"])
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
        # The index carries no timestamp, so recency comes from the rendered file itself. Without
        # this the library was ordered by insertion and every new render landed at the bottom of
        # a 150-entry list — past the default page size, so a fresh video looked like it had
        # never been saved.
        "created_at": (datetime.fromtimestamp(mtime, timezone.utc).isoformat()
                       if mtime else None),
        "_sort_key": mtime,
        "storage": "local",
    }


def _local_rows(finished_dir: str, query: str, limit: int, offset: int) -> list:
    rows = [_local_record(video_id, raw)
            for video_id, raw in _local_index(finished_dir).items()]
    if query:
        needle = query.lower()
        rows = [row for row in rows
                if needle in row["title"].lower() or needle in row["id"].lower()]
    # Newest first, and before the slice — sorting after paging would just reorder page one.
    rows.sort(key=lambda row: row.get("_sort_key") or 0.0, reverse=True)
    page = rows[offset:offset + max(1, min(limit, 200))]
    for row in page:
        row.pop("_sort_key", None)
    return page


def _get(video_id: str, finished_dir: str) -> dict | None:
    if db.db_enabled():
        record = PostgresStore().finished_get(video_id)
        if record:
            record["storage"] = "blob"
            return record
    # A configured database that simply has no row for this id must not hide a local copy that
    # is sitting on disk. Renders always write finished_videos/<id>.{mp4,srt,txt,desc} and index
    # them, but the Postgres row is only created when Blob upload is also configured — so with
    # DATABASE_URL set and no blob token, every local render became invisible to this library
    # even though its files existed. Production still fails closed: durable_storage_required()
    # is what forbids serving local bytes there, not the mere presence of a database.
    if artifact_store.durable_storage_required():
        if not db.db_enabled():
            raise StorageUnavailable("Finished library database is not configured")
        return None
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
        try:
            rows = (PostgresStore().finished_list(limit=limit, offset=offset, query=q)
                    if db.db_enabled() else [])
        except StorageUnavailable as exc:
            raise HTTPException(status_code=503, detail={
                "code": "FINISHED_STORAGE_UNAVAILABLE", "message": str(exc), "retryable": True,
            }) from exc
        # Same rule as _get: an empty database must not hide local renders. Falling back only
        # when the database returned nothing keeps Postgres authoritative wherever it is
        # populated, and keeps production fail-closed via durable_storage_required().
        if not rows:
            if artifact_store.durable_storage_required():
                if not db.db_enabled():
                    raise HTTPException(status_code=503, detail={
                        "code": "FINISHED_STORAGE_UNAVAILABLE",
                        "message": "DATABASE_URL is required for the finished library",
                        "retryable": True,
                    })
            else:
                rows = _local_rows(finished_dir, q, limit, offset)
        for row in rows:
            row.setdefault("storage", "blob" if row.get("video_url") else "local")
        return {"videos": rows, "count": len(rows), "limit": limit, "offset": offset}

    @app.get("/api/finished/{video_id}")
    async def finished_detail(video_id: str):
        try:
            record = _get(video_id, finished_dir)
        except StorageUnavailable as exc:
            raise HTTPException(status_code=503, detail={
                "code": "FINISHED_STORAGE_UNAVAILABLE", "message": str(exc), "retryable": True,
            }) from exc
        if not record:
            raise HTTPException(status_code=404, detail="Finished video not found")
        return record

    @app.get("/api/finished/{video_id}/artifact/{kind}")
    async def finished_artifact(video_id: str, kind: str, download: bool = False):
        try:
            record = _get(video_id, finished_dir)
        except StorageUnavailable as exc:
            raise HTTPException(status_code=503, detail={
                "code": "FINISHED_STORAGE_UNAVAILABLE", "message": str(exc), "retryable": True,
            }) from exc
        if not record:
            raise HTTPException(status_code=404, detail="Finished video not found")
        artifact = (record.get("artifacts") or {}).get(kind)
        if not artifact:
            raise HTTPException(status_code=404, detail=f"Artifact {kind!r} not found")
        remote = artifact.get("download_url") if download else artifact.get("url")
        if remote:
            if artifact.get("access") == "private":
                root = tempfile.mkdtemp(prefix=f"finished_{video_id}_")
                suffix = Path(artifact.get("pathname") or remote).suffix or ".bin"
                local_path = os.path.join(root, f"{kind}{suffix}")
                try:
                    BlobStore().download(artifact, local_path)
                except StorageUnavailable as exc:
                    shutil.rmtree(root, ignore_errors=True)
                    raise HTTPException(status_code=503, detail={
                        "code": "FINISHED_ARTIFACT_UNAVAILABLE",
                        "message": str(exc), "retryable": True,
                    }) from exc
                filename = os.path.basename(local_path) if download else None
                return FileResponse(
                    local_path, media_type=artifact.get("content_type"), filename=filename,
                    background=BackgroundTask(shutil.rmtree, root, ignore_errors=True))
            return RedirectResponse(remote, status_code=307)
        local_path = artifact.get("local_path")
        if local_path and os.path.isfile(local_path):
            filename = os.path.basename(local_path) if download else None
            return FileResponse(local_path, media_type=artifact.get("content_type"), filename=filename)
        raise HTTPException(status_code=404, detail="Artifact bytes are unavailable")
