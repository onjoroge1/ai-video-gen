"""Durable finished-video persistence: Vercel Blob bytes + Postgres metadata.

Supports both the legacy Vercel Blob read/write token and Vercel's newer
OIDC + store-id runtime authentication.  The latter is what current Vercel
Storage integrations expose when the configured variable prefix produces
``*_STORE_ID`` and ``*_WEBHOOK_PUBLIC_KEY`` variables.
"""
from __future__ import annotations

import mimetypes
import os
from pathlib import Path
import re

import requests  # kept public for existing tests/monkeypatches

import blob_compat
import db


class ArtifactPersistenceError(RuntimeError):
    pass


def blob_token() -> str:
    """Return a legacy/static Blob token when one is configured."""
    return blob_compat.read_write_token()


def blob_enabled() -> bool:
    """True for either static-token auth or Vercel OIDC + store-id auth."""
    return blob_compat.enabled()


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
        missing.append(
            "BLOB_READ_WRITE_TOKEN or Vercel OIDC + "
            "BLOB_STORE_ID/BLOB_READ_WRITE_TOKEN_STORE_ID"
        )
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

    suffix = path.suffix.lower()
    remote = f"finished/{_safe_part(job_id)}/{_safe_part(kind)}{suffix}"
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    try:
        uploaded = blob_compat.upload_file(
            str(path),
            remote,
            access="auto",
            content_type=content_type,
            add_random_suffix=True,
            overwrite=False,
            cache_control_max_age=31_536_000,
        )
    except blob_compat.BlobAuthError as exc:
        raise ArtifactPersistenceError(str(exc)) from exc

    return {"kind": kind, **uploaded}


def persist_finished(job_id: str, video_path: str, metadata: dict,
                     extras: dict[str, str | None] | None = None) -> dict | None:
    """Upload all surviving artifacts and atomically expose their metadata in Postgres.

    Local development without Blob keeps using the on-disk compatibility index. Production is
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
