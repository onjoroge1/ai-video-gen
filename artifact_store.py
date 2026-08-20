"""Durable finished-video persistence: Vercel Blob bytes + Postgres metadata.

The module intentionally uses the existing ``requests`` dependency instead of adding Vercel's full
Python SDK to this already-large function bundle.  The request shape follows Blob API v11.
"""
from __future__ import annotations

import mimetypes
import os
from pathlib import Path
import re
import time
import uuid

import requests

import db


class ArtifactPersistenceError(RuntimeError):
    pass


def blob_token() -> str:
    return (os.environ.get("BLOB_READ_WRITE_TOKEN")
            or os.environ.get("VERCEL_BLOB_READ_WRITE_TOKEN") or "").strip()


def blob_enabled() -> bool:
    return bool(blob_token())


def durable_storage_required() -> bool:
    configured = os.environ.get("REQUIRE_DURABLE_ARTIFACTS")
    if configured is not None:
        return configured.strip().lower() not in ("0", "false", "no", "off")
    return bool(os.environ.get("VERCEL"))


def readiness() -> dict:
    return {
        "required": durable_storage_required(),
        "blob": blob_enabled(),
        "database": db.db_enabled(),
        "ready": (not durable_storage_required()) or (blob_enabled() and db.db_enabled()),
    }


def assert_ready() -> None:
    state = readiness()
    if state["ready"]:
        return
    missing = []
    if not state["blob"]:
        missing.append("BLOB_READ_WRITE_TOKEN")
    if not state["database"]:
        missing.append("DATABASE_URL")
    raise ArtifactPersistenceError(
        "Durable artifact storage is required before rendering on Vercel. Missing: "
        + ", ".join(missing)
    )


def _safe_part(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-.")
    return cleaned[:90] or "artifact"


def _upload_file(local_path: str, job_id: str, kind: str) -> dict:
    path = Path(local_path)
    if not path.is_file():
        raise ArtifactPersistenceError(f"Artifact does not exist: {path}")
    token = blob_token()
    if not token:
        raise ArtifactPersistenceError("BLOB_READ_WRITE_TOKEN is not configured")

    suffix = path.suffix.lower()
    remote = f"finished/{_safe_part(job_id)}/{_safe_part(kind)}{suffix}"
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    store_id = token.split("_")[3] if len(token.split("_")) > 3 else "store"
    request_id = f"{store_id}:{int(time.time() * 1000)}:{uuid.uuid4().hex[:8]}"
    headers = {
        "Authorization": f"Bearer {token}",
        "x-api-version": os.environ.get("VERCEL_BLOB_API_VERSION_OVERRIDE", "11"),
        "x-api-blob-request-id": request_id,
        "x-api-blob-request-attempt": "0",
        "x-content-type": content_type,
        "x-content-length": str(path.stat().st_size),
        "x-add-random-suffix": "1",
        "x-allow-overwrite": "0",
        "x-vercel-blob-access": "public",
        "x-cache-control-max-age": "31536000",
    }
    endpoint = os.environ.get("VERCEL_BLOB_API_URL", "https://vercel.com/api/blob")
    try:
        with path.open("rb") as body:
            response = requests.put(
                endpoint,
                params={"pathname": remote},
                headers=headers,
                data=body,
                timeout=(15, 900),
            )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        detail = ""
        try:
            detail = f" ({response.text[:300]})"
        except Exception:
            pass
        raise ArtifactPersistenceError(f"Vercel Blob upload failed for {kind}: {exc}{detail}") from exc

    return {
        "kind": kind,
        "url": payload["url"],
        "download_url": payload.get("downloadUrl") or payload["url"] + "?download=1",
        "pathname": payload.get("pathname") or remote,
        "content_type": payload.get("contentType") or content_type,
        "size_bytes": path.stat().st_size,
    }


def persist_finished(job_id: str, video_path: str, metadata: dict,
                     extras: dict[str, str | None] | None = None) -> dict | None:
    """Upload all surviving artifacts and atomically expose their metadata in Postgres.

    Local development without Blob keeps using the on-disk compatibility index.  Production is
    checked before paid generation begins, so a missing store cannot silently orphan a render.
    """
    if not blob_enabled():
        if durable_storage_required():
            assert_ready()
        return None

    if not db.db_enabled():
        raise ArtifactPersistenceError("DATABASE_URL is required to index Blob artifacts")

    artifacts = {"video": _upload_file(video_path, job_id, "video")}
    for kind, local_path in (extras or {}).items():
        if local_path and os.path.isfile(local_path):
            artifacts[kind] = _upload_file(local_path, job_id, kind)

    video = artifacts["video"]
    record = {
        "id": job_id,
        "title": metadata.get("title") or job_id,
        "format": metadata.get("format") or metadata.get("template") or "video",
        "status": metadata.get("status") or "done",
        "video_url": video["url"],
        "download_url": video["download_url"],
        "thumbnail_url": (artifacts.get("thumb") or artifacts.get("thumbnail") or {}).get("url"),
        "size_bytes": video["size_bytes"],
        "artifacts": artifacts,
        "metadata": metadata,
    }
    if not db.finished_video_upsert(record):
        raise ArtifactPersistenceError("Blob upload succeeded but Postgres indexing failed")
    return record
