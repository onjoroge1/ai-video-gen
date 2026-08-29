"""Vercel Blob compatibility helpers.

Supports both authentication models used by Vercel Blob:

* legacy read/write tokens (``BLOB_READ_WRITE_TOKEN``), and
* Vercel OIDC plus a Blob store id (``VERCEL_OIDC_TOKEN`` + ``BLOB_STORE_ID``).

The ai-video-gen Vercel integration currently exposes its store id with the
configured integration prefix, so ``BLOB_READ_WRITE_TOKEN_STORE_ID`` is also
accepted as an alias for ``BLOB_STORE_ID``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import time
import uuid
from typing import Any

import requests


class BlobAuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class BlobCredentials:
    mode: str  # "read_write" | "oidc"
    token: str
    store_id: str


def normalize_store_id(value: str | None) -> str:
    value = (value or "").strip()
    return value[6:] if value.startswith("store_") else value


def read_write_token() -> str:
    return (
        os.environ.get("BLOB_READ_WRITE_TOKEN")
        or os.environ.get("VERCEL_BLOB_READ_WRITE_TOKEN")
        or ""
    ).strip()


def configured_store_id() -> str:
    return normalize_store_id(
        os.environ.get("BLOB_STORE_ID")
        or os.environ.get("BLOB_READ_WRITE_TOKEN_STORE_ID")
        or ""
    )


def _store_id_from_read_write_token(token: str) -> str:
    # Vercel read/write tokens are shaped like vercel_blob_rw_<storeId>_<secret>.
    parts = token.split("_")
    return normalize_store_id(parts[3] if len(parts) > 3 else "")


def _runtime_oidc_token() -> str:
    token = (os.environ.get("VERCEL_OIDC_TOKEN") or "").strip()
    if token:
        return token
    if not os.environ.get("VERCEL"):
        return ""
    try:
        from vercel.oidc import get_vercel_oidc_token
        return (get_vercel_oidc_token() or "").strip()
    except Exception:
        return ""


def resolve_credentials(token: str | None = None) -> BlobCredentials:
    explicit = (token or "").strip()
    legacy = explicit or read_write_token()
    if legacy:
        store_id = configured_store_id() or _store_id_from_read_write_token(legacy)
        return BlobCredentials(mode="read_write", token=legacy, store_id=store_id)

    store_id = configured_store_id()
    if store_id:
        oidc = _runtime_oidc_token()
        if oidc:
            return BlobCredentials(mode="oidc", token=oidc, store_id=store_id)

    raise BlobAuthError(
        "Vercel Blob credentials are not configured. Set BLOB_READ_WRITE_TOKEN, or use "
        "Vercel OIDC with BLOB_STORE_ID/BLOB_READ_WRITE_TOKEN_STORE_ID."
    )


def enabled() -> bool:
    try:
        resolve_credentials()
        return True
    except BlobAuthError:
        return False


def _auth_headers(credentials: BlobCredentials) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {credentials.token}"}
    if credentials.store_id:
        headers["x-vercel-blob-store-id"] = credentials.store_id
    return headers


def _endpoint() -> str:
    return (os.environ.get("VERCEL_BLOB_API_URL") or "https://vercel.com/api/blob").rstrip("/")


def configured_access() -> str:
    """Return the requested Blob visibility, defaulting to safe runtime discovery."""
    value = (os.environ.get("BLOB_ACCESS") or os.environ.get("VERCEL_BLOB_ACCESS")
             or "auto").strip().lower()
    if value not in {"auto", "public", "private"}:
        raise BlobAuthError("BLOB_ACCESS must be auto, public, or private")
    return value


def upload_file(
    local_path: str,
    remote_path: str,
    *,
    credentials: BlobCredentials | None = None,
    access: str = "auto",
    content_type: str = "application/octet-stream",
    add_random_suffix: bool = True,
    overwrite: bool = False,
    cache_control_max_age: int = 31_536_000,
) -> dict[str, Any]:
    path = Path(local_path)
    if not path.is_file():
        raise BlobAuthError(f"Artifact does not exist: {path}")
    credentials = credentials or resolve_credentials()
    request_id = (
        f"{credentials.store_id or 'store'}:{int(time.time() * 1000)}:"
        f"{uuid.uuid4().hex[:8]}"
    )
    requested_access = configured_access() if access == "auto" else access.strip().lower()
    if requested_access not in {"auto", "public", "private"}:
        raise BlobAuthError("Blob upload access must be auto, public, or private")
    candidates = [requested_access] if requested_access != "auto" else ["public", "private"]
    failure = None
    payload = None
    actual_access = ""
    for attempt, candidate in enumerate(candidates):
        headers = {
            **_auth_headers(credentials),
            "x-api-version": os.environ.get("VERCEL_BLOB_API_VERSION_OVERRIDE", "11"),
            "x-api-blob-request-id": request_id,
            "x-api-blob-request-attempt": str(attempt),
            "x-content-type": content_type,
            "x-content-length": str(path.stat().st_size),
            "x-add-random-suffix": "1" if add_random_suffix else "0",
            "x-allow-overwrite": "1" if overwrite else "0",
            "x-vercel-blob-access": candidate,
            "x-cache-control-max-age": str(max(60, int(cache_control_max_age))),
        }
        try:
            with path.open("rb") as body:
                response = requests.put(
                    _endpoint(), params={"pathname": remote_path}, headers=headers,
                    data=body, timeout=(15, 900))
            response.raise_for_status()
            payload = response.json()
            actual_access = candidate
            break
        except Exception as exc:
            detail = ""
            try:
                detail = response.text[:300]
            except Exception:
                pass
            failure = (exc, detail)
            # Auto mode retries only the exact public/private store mismatch. Other failures
            # (credentials, quota, networking, malformed requests) remain fail-closed.
            if not (requested_access == "auto" and candidate == "public"
                    and "private store" in detail.lower()):
                break
    if payload is None:
        exc, detail = failure or (RuntimeError("unknown upload failure"), "")
        suffix = f" ({detail})" if detail else ""
        raise BlobAuthError(f"Vercel Blob upload failed: {exc}{suffix}") from exc
    return {
        "url": payload["url"],
        "download_url": payload.get("downloadUrl") or payload["url"] + "?download=1",
        "pathname": payload.get("pathname") or remote_path,
        "content_type": payload.get("contentType") or content_type,
        "size_bytes": path.stat().st_size,
        "access": actual_access,
    }


def download_file(
    url: str,
    local_path: str,
    *,
    credentials: BlobCredentials | None = None,
    access: str = "auto",
    overwrite: bool = True,
) -> str:
    dest = Path(local_path)
    if dest.exists() and not overwrite:
        raise BlobAuthError(f"Destination already exists: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    requested_access = access.strip().lower()
    if requested_access not in {"auto", "public", "private"}:
        raise BlobAuthError("Blob download access must be auto, public, or private")
    candidates = [requested_access] if requested_access != "auto" else ["public", "private"]
    failure = None
    for candidate in candidates:
        response = None
        try:
            headers = {}
            if candidate == "private":
                credentials = credentials or resolve_credentials()
                headers = _auth_headers(credentials)
            response = requests.get(
                url, headers=headers, stream=True, timeout=(15, 900))
            response.raise_for_status()
            with dest.open("wb") as out:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        out.write(chunk)
            return str(dest)
        except Exception as exc:
            failure = exc
            try:
                if response is not None:
                    response.close()
            except Exception:
                pass
            if requested_access != "auto" or candidate != "public" \
                    or getattr(response, "status_code", 0) not in {401, 403}:
                break
    try:
        dest.unlink(missing_ok=True)
    except OSError:
        pass
    raise BlobAuthError(f"Vercel Blob download failed: {failure}") from failure


def download_public(url: str, local_path: str, *, overwrite: bool = True) -> str:
    """Compatibility wrapper for known-public legacy objects."""
    return download_file(url, local_path, access="public", overwrite=overwrite)


def delete(url_or_path: str, *, credentials: BlobCredentials | None = None) -> None:
    credentials = credentials or resolve_credentials()
    headers = {**_auth_headers(credentials), "Content-Type": "application/json"}
    try:
        response = requests.post(
            _endpoint() + "/delete",
            headers=headers,
            json={"urls": [url_or_path]},
            timeout=(15, 120),
        )
        response.raise_for_status()
    except Exception as exc:
        raise BlobAuthError(f"Vercel Blob delete failed: {exc}") from exc


def list_objects(
    prefix: str,
    *,
    limit: int = 1000,
    credentials: BlobCredentials | None = None,
) -> list[dict[str, Any]]:
    credentials = credentials or resolve_credentials()
    try:
        response = requests.get(
            _endpoint(),
            params={"prefix": prefix, "limit": max(1, min(int(limit), 1000))},
            headers=_auth_headers(credentials),
            timeout=(15, 120),
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise BlobAuthError(f"Vercel Blob list failed for {prefix}: {exc}") from exc
    return list(payload.get("blobs") or [])


def uploaded_timestamp(item: dict[str, Any]) -> float | None:
    value = item.get("uploadedAt") or item.get("uploaded_at")
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, (int, float)):
        # SDK/API values may be milliseconds.
        return float(value) / 1000.0 if float(value) > 10_000_000_000 else float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None
