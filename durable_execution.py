"""Compatibility facade for durable execution with modern Vercel Blob auth.

The durable execution engine from the e60bbd6 baseline is preserved byte-for-byte in
``_durable_execution_legacy.py``. This facade re-exports that implementation and swaps only the
Blob storage adapter so production can authenticate with either:

* ``BLOB_READ_WRITE_TOKEN`` (legacy/static token), or
* Vercel OIDC + ``BLOB_STORE_ID`` / ``BLOB_READ_WRITE_TOKEN_STORE_ID``.

Keeping the execution engine unchanged minimizes regression risk while updating the storage
boundary to match current Vercel Blob authentication.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import mimetypes

import blob_compat
import _durable_execution_legacy as _legacy
from _durable_execution_legacy import *  # noqa: F401,F403


class BlobStore:
    """Blob adapter compatible with both Vercel Blob authentication models."""

    def __init__(self, token: str | None = None):
        try:
            self.credentials = blob_compat.resolve_credentials(token=token)
        except blob_compat.BlobAuthError as exc:
            raise StorageUnavailable(str(exc)) from exc

    def upload(self, local_path: str, remote_path: str) -> dict:
        path = Path(local_path)
        if not path.is_file():
            raise StorageUnavailable(f"Artifact does not exist: {path}")
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        try:
            artifact = blob_compat.upload_file(
                str(path),
                remote_path,
                credentials=self.credentials,
                access="public",
                content_type=content_type,
                add_random_suffix=True,
                overwrite=False,
            )
        except blob_compat.BlobAuthError as exc:
            raise StorageUnavailable(f"Blob upload failed for {remote_path}: {exc}") from exc
        artifact["sha256"] = file_sha256(path)
        return artifact

    def download(self, artifact: dict, local_path: str) -> str:
        try:
            blob_compat.download_public(artifact["url"], local_path, overwrite=True)
        except blob_compat.BlobAuthError as exc:
            raise StorageUnavailable(f"Blob download failed: {exc}") from exc
        if file_sha256(local_path) != artifact.get("sha256"):
            raise StorageUnavailable("Downloaded checkpoint hash does not match its durable manifest")
        return local_path

    def delete(self, url_or_path: str) -> None:
        try:
            blob_compat.delete(url_or_path, credentials=self.credentials)
        except blob_compat.BlobAuthError as exc:
            raise StorageUnavailable(f"Blob delete failed: {exc}") from exc

    def older_objects(self, prefix: str, *, age_hours: int = 24,
                      limit: int = 1000) -> list[dict]:
        cutoff = datetime.now(timezone.utc).timestamp() - max(1, age_hours) * 3600
        try:
            entries = blob_compat.list_objects(
                prefix, limit=max(1, min(limit, 1000)), credentials=self.credentials)
        except blob_compat.BlobAuthError as exc:
            raise StorageUnavailable(f"Blob orphan listing failed for {prefix}: {exc}") from exc
        objects: list[dict] = []
        for item in entries:
            uploaded = blob_compat.uploaded_timestamp(item)
            if uploaded is not None and uploaded < cutoff:
                raw_uploaded = item.get("uploadedAt") or item.get("uploaded_at")
                objects.append({
                    "url": item.get("url"),
                    "pathname": item.get("pathname"),
                    "uploaded_at": str(raw_uploaded or ""),
                })
        return objects


# Some helpers in the preserved implementation resolve BlobStore from their own module globals.
# Rebind that symbol as well so every durable path uses the modern adapter.
_legacy.BlobStore = BlobStore
