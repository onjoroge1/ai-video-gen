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
import hashlib
import json
import mimetypes
import os
import re
import uuid

import blob_compat
import _durable_execution_legacy as _legacy
from _durable_execution_legacy import *  # noqa: F401,F403


def _numeric_env_value(name: str) -> str | None:
    """Return a stripped numeric env value, treating blank/invalid values as unset."""
    value = (os.environ.get(name) or "").strip()
    if not value:
        return None
    try:
        float(value)
    except (TypeError, ValueError):
        return None
    return value


def normalize_durable_job_max_cost_env() -> float:
    """Make the durable job cap safe for app.py's direct ``float(os.environ[...])`` read.

    Vercel may expose an environment variable with an empty value. ``os.environ.get(name,
    default)`` does not use the default in that case, so ``float(\"\")`` crashes the request before
    the job is queued. Treat blank/invalid values as unset and preserve the intended fallback order:
    DURABLE_JOB_MAX_COST_USD -> MAX_VIDEO_COST_USD -> 10.00.
    """
    value = (
        _numeric_env_value("DURABLE_JOB_MAX_COST_USD")
        or _numeric_env_value("MAX_VIDEO_COST_USD")
        or "10.00"
    )
    os.environ["DURABLE_JOB_MAX_COST_USD"] = value
    return float(value)


# app.py imports this module after load_dotenv(), so normalize once before any request handler reads
# the durable cap. The helper remains callable for tests and future configuration refreshes.
normalize_durable_job_max_cost_env()


class PostgresStore(_legacy.PostgresStore):
    """PR7 additions to the durable job store without weakening the PR6 engine."""

    _pilot_schema_ready = False

    def ensure_pilot_schema(self) -> None:
        self.ensure_schema()
        if self._pilot_schema_ready:
            return
        with self._tx() as (_, cur):
            cur.execute("""
                CREATE TABLE IF NOT EXISTS controlled_pilot_batches (
                    id text PRIMARY KEY,
                    request_hash text NOT NULL,
                    standard_job_id text NOT NULL REFERENCES generation_jobs(id),
                    mystery_job_id text NOT NULL REFERENCES generation_jobs(id),
                    status text NOT NULL DEFAULT 'queued',
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now()
                )""")
        self._pilot_schema_ready = True

    def enqueue_pilot_batch(self, *, batch_id: str, jobs: list[dict], max_cost_usd: float,
                            pipeline_version: str) -> dict:
        """Atomically create exactly one Standard and one Mystery durable pilot job."""
        from longform_pilots import PILOT_KINDS, validate_pilot_request

        if len(jobs) != 2 or {job.get("request", {}).get("pilot_kind") for job in jobs} \
                != set(PILOT_KINDS):
            raise DurableExecutionError(
                "A controlled pilot batch requires exactly one Standard and one Evidence Mystery job")
        for job in jobs:
            validate_pilot_request(job.get("request") or {})
        self.ensure_pilot_schema()
        canonical_jobs = sorted(
            [{"job_id": item["job_id"], "request": item["request"]} for item in jobs],
            key=lambda item: item["job_id"])
        request_hash = canonical_hash(canonical_jobs)
        by_kind = {item["request"]["pilot_kind"]: item for item in jobs}
        created = []
        with self._tx() as (_, cur):
            cur.execute("SELECT * FROM controlled_pilot_batches WHERE id=%s FOR UPDATE", (batch_id,))
            existing = self._row(cur, cur.fetchone())
            if existing:
                if existing.get("request_hash") != request_hash:
                    raise DurableExecutionError(
                        f"Pilot batch {batch_id} already exists with a different immutable request")
                cur.execute("""
                    SELECT * FROM generation_jobs WHERE id IN (%s,%s) ORDER BY id
                """, (existing["standard_job_id"], existing["mystery_job_id"]))
                existing_jobs = [
                    self._json_ready(self._row(cur, row)) or {} for row in cur.fetchall()
                ]
                return {**(self._json_ready(existing) or {}), "jobs": existing_jobs}
            for item in canonical_jobs:
                cur.execute("""
                    INSERT INTO generation_jobs
                        (id,kind,request,status,max_cost_usd,max_inflight_call_usd,
                         pipeline_version,output_prefix,max_attempts)
                    VALUES (%s,'explainer_pilot',%s::jsonb,'queued',%s,%s,%s,%s,1)
                    RETURNING *
                """, (item["job_id"], json.dumps(item["request"]), max_cost_usd,
                      _legacy.DEFAULT_MAX_INFLIGHT_USD, pipeline_version,
                      f"pilots/{batch_id}/{item['request']['pilot_kind']}"))
                created.append(self._json_ready(self._row(cur, cur.fetchone())) or {})
            cur.execute("""
                INSERT INTO controlled_pilot_batches
                    (id,request_hash,standard_job_id,mystery_job_id,status)
                VALUES (%s,%s,%s,%s,'queued')
            """, (batch_id, request_hash, by_kind["standard"]["job_id"],
                  by_kind["evidence_mystery"]["job_id"]))
        for job in created:
            self.append_event(job["id"], "queued", "Controlled PR7 pilot queued durably", {
                "batch_id": batch_id,
                "pilot_kind": (job.get("request") or {}).get("pilot_kind"),
            })
        return {"id": batch_id, "request_hash": request_hash, "status": "queued",
                "jobs": created}

    def get_pilot_batch(self, batch_id: str) -> dict | None:
        self.ensure_pilot_schema()
        with self._tx() as (_, cur):
            cur.execute("SELECT * FROM controlled_pilot_batches WHERE id=%s", (batch_id,))
            batch = self._json_ready(self._row(cur, cur.fetchone()))
            if not batch:
                return None
            cur.execute("""
                SELECT * FROM generation_jobs WHERE id IN (%s,%s) ORDER BY id
            """, (batch["standard_job_id"], batch["mystery_job_id"]))
            jobs = [self._json_ready(self._row(cur, row)) or {} for row in cur.fetchall()]
        statuses = {job.get("status") for job in jobs}
        if statuses and statuses.issubset({"pilot_passed", "pilot_failed", "storage_error"}):
            batch["status"] = "complete"
        elif "processing" in statuses:
            batch["status"] = "processing"
        elif "pilot_awaiting_editorial" in statuses:
            batch["status"] = "awaiting_editorial"
        batch["jobs"] = jobs
        return batch

    def set_status(self, job_id: str, status: str, *, error: str | None = None,
                   result: dict | None = None, worker_id: str | None = None) -> None:
        terminal = {"done", "degraded", "error", "rejected", "pilot_passed", "pilot_failed"}
        finished_at = status in terminal
        with self._tx() as (_, cur):
            owner = " AND lease_owner=%s" if worker_id else ""
            cur.execute(f"""
                UPDATE generation_jobs SET status=%s,error=%s,result=result || %s::jsonb,
                    lease_owner=NULL,lease_expires_at=NULL,updated_at=now(),
                    finished_at=CASE WHEN %s THEN now() ELSE finished_at END
                WHERE id=%s{owner}
            """, (status, error, json.dumps(result or {}), finished_at, job_id,
                  *([worker_id] if worker_id else [])))
            if cur.rowcount != 1:
                raise LeaseLost(f"Cannot transition {job_id}; worker lease was lost")


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


def _pilot_safe_path(relative: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", relative.replace(os.sep, "--"))
    return cleaned.strip("-.")[:180] or "artifact"


def _pilot_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def persist_pilot_snapshot(self, label: str, *, metadata: dict | None = None,
                           final: bool = False, heartbeat: bool = True) -> dict:
    """Persist every current pilot artifact as an immutable, hash-addressed Blob object.

    A later editorial review may add a new hash/version of a control artifact, but it never
    overwrites or deletes the bytes that were graded automatically.
    """
    if heartbeat:
        self.assert_lease()
        self.heartbeat()
    root = Path(self.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "pilot_artifact_manifest.json"

    def files() -> list[Path]:
        return sorted(
            path for path in root.rglob("*")
            if path.is_file() and not path.is_symlink() and not path.name.endswith(".tmp"))

    pre_manifest = []
    for path in files():
        if path == manifest_path:
            continue
        relative = path.relative_to(root).as_posix()
        pre_manifest.append({
            "relative_path": relative,
            "sha256": _pilot_file_sha256(path),
            "size_bytes": path.stat().st_size,
            "content_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        })
    manifest = {
        "schema_version": 1,
        "job_id": self.job_id,
        "label": str(label),
        "terminal": bool(final),
        "metadata": metadata or {},
        "artifact_count_excluding_manifest": len(pre_manifest),
        "artifacts": pre_manifest,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    temporary = manifest_path.with_name(manifest_path.name + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, manifest_path)

    existing = {
        (item.get("kind"), item.get("stage_key")): item
        for item in self.store.artifacts(self.job_id)
    }
    uploaded = []
    for path in files():
        relative = path.relative_to(root).as_posix()
        expected_sha = _pilot_file_sha256(path)
        stage_key = f"{relative}#{expected_sha[:16]}"
        prior = existing.get(("pilot_artifact", stage_key))
        if prior and prior.get("sha256") == expected_sha:
            uploaded.append({
                "relative_path": relative, "sha256": expected_sha,
                "url": prior.get("url"), "reused": True,
            })
            continue
        suffix = path.suffix or ".bin"
        remote = (
            f"pilots/{_pilot_safe_path(self.job_id)}/{_pilot_safe_path(label)}/"
            f"{_pilot_safe_path(relative)}-{expected_sha[:16]}-{uuid.uuid4().hex}{suffix}"
        )
        artifact = self.blob.upload(str(path), remote)
        if artifact.get("sha256") != expected_sha:
            try:
                self.blob.delete(artifact.get("url") or artifact.get("pathname"))
            finally:
                raise StorageUnavailable(
                    f"Pilot artifact changed during upload: {relative}")
        try:
            self.store.register_artifact(
                self.job_id, "pilot_artifact", stage_key, artifact,
                provisional=not final)
        except Exception:
            try:
                self.blob.delete(artifact.get("url") or artifact.get("pathname"))
            finally:
                raise
        uploaded.append({
            "relative_path": relative, "sha256": expected_sha,
            "url": artifact.get("url"), "reused": False,
        })
    if len(uploaded) != len(files()):
        raise StorageUnavailable("Pilot artifact snapshot did not persist every file")
    if final:
        self.store.mark_finalized(self.job_id)
    self.event("pilot_artifacts_persisted", f"Persisted {label}", {
        "artifact_count": len(uploaded), "terminal": bool(final),
        "manifest_sha256": _pilot_file_sha256(manifest_path),
    })
    return {
        "label": label,
        "artifact_count": len(uploaded),
        "manifest_sha256": _pilot_file_sha256(manifest_path),
        "terminal": bool(final),
        "artifacts": uploaded,
    }


# Some helpers in the preserved implementation resolve BlobStore from their own module globals.
# Rebind that symbol as well so every durable path uses the modern adapter.
_legacy.BlobStore = BlobStore
_legacy.PostgresStore = PostgresStore
_legacy.DurableRuntime.persist_pilot_snapshot = persist_pilot_snapshot
