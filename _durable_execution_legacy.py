"""Crash-safe execution primitives for paid explainer renders.

Postgres is the source of truth for jobs, leases, events, stages, and cost.  Vercel Blob stores
immutable stage outputs and checkpoint archives.  The module is intentionally framework-neutral:
FastAPI owns HTTP, while this layer owns at-least-once execution and idempotent paid stages.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import threading
import time
import uuid
from typing import Any, Callable, Iterator
from types import SimpleNamespace


SCHEMA_VERSION = 1
DEFAULT_LEASE_SECONDS = max(60, int(os.environ.get("DURABLE_JOB_LEASE_SECONDS", "900")))
DEFAULT_MAX_ATTEMPTS = max(1, int(os.environ.get("DURABLE_JOB_MAX_ATTEMPTS", "5")))
DEFAULT_MAX_INFLIGHT_USD = max(
    0.01, float(os.environ.get("DURABLE_MAX_INFLIGHT_CALL_USD", "1.00")))


class DurableExecutionError(RuntimeError):
    pass


class StorageUnavailable(DurableExecutionError):
    pass


class BudgetExceeded(DurableExecutionError):
    pass


class LeaseLost(DurableExecutionError):
    pass


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_sha256(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def enforce_budget(job: dict, reserve: float, stage_key: str) -> None:
    committed = float(job["spent_cost_usd"])
    already_reserved = float(job["reserved_cost_usd"])
    cap = float(job["max_cost_usd"])
    inflight_cap = float(job["max_inflight_call_usd"])
    if reserve > inflight_cap + 1e-9:
        raise BudgetExceeded(
            f"Stage {stage_key} reserves ${reserve:.4f}; the single-call ceiling is "
            f"${inflight_cap:.4f}")
    if committed + already_reserved + reserve > cap + 1e-9:
        raise BudgetExceeded(
            f"Stage {stage_key} would spend ${committed + already_reserved + reserve:.4f} "
            f"against the ${cap:.4f} cap")


def version_hash(root: str | os.PathLike[str]) -> str:
    root = str(root)
    digest = hashlib.sha256()
    for name in (
        "explainer_pipeline.py", "longform_retention.py", "longform_evidence.py",
        "longform_motion.py", "longform_pilots.py", "longform_production.py",
        "longform_rendered_gate.py", "durable_execution.py",
    ):
        path = os.path.join(root, name)
        digest.update(name.encode())
        if os.path.isfile(path):
            digest.update(file_sha256(path).encode())
    return digest.hexdigest()


class PostgresStore:
    """Strict Postgres adapter.  Unlike the legacy topic helpers, failures never become []."""

    def __init__(self, database_url: str | None = None):
        self.database_url = (database_url or os.environ.get("DATABASE_URL") or "").strip()
        if not self.database_url:
            raise StorageUnavailable("DATABASE_URL is required for durable execution")
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def _connect(self):
        try:
            import psycopg2
            return psycopg2.connect(self.database_url, connect_timeout=10)
        except Exception as exc:
            raise StorageUnavailable(f"Postgres unavailable: {exc}") from exc

    @contextmanager
    def _tx(self):
        conn = self._connect()
        try:
            yield conn, conn.cursor()
            conn.commit()
        except DurableExecutionError:
            conn.rollback()
            raise
        except Exception as exc:
            conn.rollback()
            raise StorageUnavailable(f"Postgres transaction failed: {exc}") from exc
        finally:
            conn.close()

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with self._tx() as (_, cur):
                cur.execute("""
                CREATE TABLE IF NOT EXISTS generation_jobs (
                    id text PRIMARY KEY,
                    kind text NOT NULL,
                    request jsonb NOT NULL,
                    status text NOT NULL,
                    max_cost_usd numeric(12,4) NOT NULL,
                    spent_cost_usd numeric(12,4) NOT NULL DEFAULT 0,
                    reserved_cost_usd numeric(12,4) NOT NULL DEFAULT 0,
                    max_inflight_call_usd numeric(12,4) NOT NULL DEFAULT 1,
                    pipeline_version text NOT NULL,
                    output_prefix text NOT NULL,
                    result jsonb NOT NULL DEFAULT '{}'::jsonb,
                    checkpoint jsonb NOT NULL DEFAULT '{}'::jsonb,
                    error text,
                    lease_owner text,
                    lease_expires_at timestamptz,
                    attempts integer NOT NULL DEFAULT 0,
                    max_attempts integer NOT NULL DEFAULT 5,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now(),
                    finished_at timestamptz
                )""")
                cur.execute("""
                CREATE TABLE IF NOT EXISTS generation_events (
                    seq bigserial PRIMARY KEY,
                    job_id text NOT NULL REFERENCES generation_jobs(id) ON DELETE CASCADE,
                    event_type text NOT NULL,
                    data text NOT NULL,
                    details jsonb NOT NULL DEFAULT '{}'::jsonb,
                    created_at timestamptz NOT NULL DEFAULT now()
                )""")
                cur.execute("CREATE INDEX IF NOT EXISTS generation_events_job_seq ON generation_events(job_id,seq)")
                cur.execute("""
                CREATE TABLE IF NOT EXISTS generation_stages (
                    job_id text NOT NULL REFERENCES generation_jobs(id) ON DELETE CASCADE,
                    stage_key text NOT NULL,
                    provider text NOT NULL,
                    idempotency_key text NOT NULL,
                    request_hash text NOT NULL,
                    status text NOT NULL,
                    reserved_cost_usd numeric(12,4) NOT NULL DEFAULT 0,
                    actual_cost_usd numeric(12,4) NOT NULL DEFAULT 0,
                    attempt integer NOT NULL DEFAULT 1,
                    result jsonb NOT NULL DEFAULT '{}'::jsonb,
                    artifact jsonb NOT NULL DEFAULT '{}'::jsonb,
                    error text,
                    started_at timestamptz NOT NULL DEFAULT now(),
                    completed_at timestamptz,
                    updated_at timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY(job_id,stage_key),
                    UNIQUE(job_id,idempotency_key)
                )""")
                cur.execute("""
                CREATE TABLE IF NOT EXISTS generation_artifacts (
                    job_id text NOT NULL REFERENCES generation_jobs(id) ON DELETE CASCADE,
                    kind text NOT NULL,
                    stage_key text NOT NULL DEFAULT '',
                    url text NOT NULL,
                    pathname text,
                    sha256 text NOT NULL,
                    size_bytes bigint NOT NULL,
                    content_type text,
                    provisional boolean NOT NULL DEFAULT true,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY(job_id,kind,stage_key)
                )""")
                cur.execute("""
                CREATE TABLE IF NOT EXISTS finished_videos (
                    id text PRIMARY KEY,
                    title text NOT NULL,
                    format text,
                    status text,
                    video_url text NOT NULL,
                    download_url text,
                    thumbnail_url text,
                    size_bytes bigint,
                    artifacts jsonb NOT NULL DEFAULT '{}'::jsonb,
                    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now()
                )""")
            self._schema_ready = True

    @staticmethod
    def _row(cur, row) -> dict | None:
        if row is None:
            return None
        return {desc.name: value for desc, value in zip(cur.description, row)}

    @staticmethod
    def _json_ready(row: dict | None) -> dict | None:
        if row is None:
            return None
        out = dict(row)
        for key, value in list(out.items()):
            if hasattr(value, "isoformat"):
                out[key] = value.isoformat()
            elif key.endswith("_usd") and value is not None:
                out[key] = float(value)
        return out

    def enqueue(self, *, job_id: str, kind: str, request: dict, max_cost_usd: float,
                pipeline_version: str, output_prefix: str) -> dict:
        self.ensure_schema()
        with self._tx() as (_, cur):
            cur.execute("""
                INSERT INTO generation_jobs
                    (id,kind,request,status,max_cost_usd,max_inflight_call_usd,
                     pipeline_version,output_prefix,max_attempts)
                VALUES (%s,%s,%s::jsonb,'queued',%s,%s,%s,%s,%s)
                ON CONFLICT(id) DO NOTHING
                RETURNING *
            """, (job_id, kind, json.dumps(request), max_cost_usd, DEFAULT_MAX_INFLIGHT_USD,
                  pipeline_version, output_prefix, DEFAULT_MAX_ATTEMPTS))
            row = self._row(cur, cur.fetchone())
            if not row:
                cur.execute("SELECT * FROM generation_jobs WHERE id=%s", (job_id,))
                row = self._row(cur, cur.fetchone())
        self.append_event(job_id, "queued", "Render queued durably")
        return self._json_ready(row) or {}

    def get_job(self, job_id: str) -> dict | None:
        self.ensure_schema()
        with self._tx() as (_, cur):
            cur.execute("SELECT * FROM generation_jobs WHERE id=%s", (job_id,))
            return self._json_ready(self._row(cur, cur.fetchone()))

    def claim(self, *, job_id: str | None = None, worker_id: str | None = None,
              lease_seconds: int = DEFAULT_LEASE_SECONDS) -> dict | None:
        self.ensure_schema()
        worker_id = worker_id or f"worker-{uuid.uuid4().hex}"
        exhausted: list[str] = []
        with self._tx() as (_, cur):
            cur.execute("""
                UPDATE generation_jobs SET status='error',error='Maximum worker attempts exhausted',
                    lease_owner=NULL,lease_expires_at=NULL,updated_at=now(),finished_at=now()
                WHERE attempts>=max_attempts
                  AND (status='retry' OR (status='processing' AND lease_expires_at < now()))
                RETURNING id
            """)
            exhausted = [row[0] for row in cur.fetchall()]
            params: list[Any] = []
            exact = ""
            if job_id:
                exact = "AND id=%s"
                params.append(job_id)
            params.extend((worker_id, int(lease_seconds)))
            cur.execute(f"""
                WITH candidate AS (
                    SELECT id FROM generation_jobs
                    WHERE (status IN ('queued','retry')
                       OR (status='processing' AND lease_expires_at < now()))
                      AND attempts < max_attempts
                    {exact}
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED LIMIT 1
                )
                UPDATE generation_jobs j SET
                    status='processing', lease_owner=%s,
                    lease_expires_at=now() + (%s || ' seconds')::interval,
                    attempts=attempts+1, updated_at=now(), error=NULL
                FROM candidate c WHERE j.id=c.id
                RETURNING j.*
            """, tuple(params))
            row = self._json_ready(self._row(cur, cur.fetchone()))
        for exhausted_id in exhausted:
            self.append_event(exhausted_id, "error", "Maximum worker attempts exhausted")
        if row:
            self.append_event(row["id"], "lease", f"Claimed by {worker_id}",
                              {"worker_id": worker_id, "attempt": row["attempts"]})
        return row

    def heartbeat(self, job_id: str, worker_id: str,
                  lease_seconds: int = DEFAULT_LEASE_SECONDS) -> None:
        with self._tx() as (_, cur):
            cur.execute("""
                UPDATE generation_jobs SET
                    lease_expires_at=now() + (%s || ' seconds')::interval, updated_at=now()
                WHERE id=%s AND lease_owner=%s AND status='processing'
            """, (int(lease_seconds), job_id, worker_id))
            if cur.rowcount != 1:
                raise LeaseLost(f"Lease for {job_id} is no longer owned by {worker_id}")

    def append_event(self, job_id: str, event_type: str, data: str,
                     details: dict | None = None) -> int:
        with self._tx() as (_, cur):
            cur.execute("""
                INSERT INTO generation_events(job_id,event_type,data,details)
                VALUES (%s,%s,%s,%s::jsonb) RETURNING seq
            """, (job_id, event_type, str(data), json.dumps(details or {})))
            return int(cur.fetchone()[0])

    def events(self, job_id: str, after: int = 0, limit: int = 500) -> list[dict]:
        self.ensure_schema()
        with self._tx() as (_, cur):
            cur.execute("""
                SELECT seq,event_type,data,details,created_at FROM generation_events
                WHERE job_id=%s AND seq>%s ORDER BY seq LIMIT %s
            """, (job_id, max(0, int(after)), max(1, min(int(limit), 1000))))
            rows = []
            for raw in cur.fetchall():
                row = self._row(cur, raw) or {}
                row["created_at"] = row["created_at"].isoformat()
                rows.append(row)
            return rows

    def prepare_stage(self, job_id: str, stage_key: str, provider: str, request_hash: str,
                      estimated_cost: float) -> dict:
        reserve = max(0.0, float(estimated_cost))
        idem = canonical_hash({"job": job_id, "stage": stage_key, "request": request_hash})
        with self._tx() as (_, cur):
            cur.execute("SELECT * FROM generation_jobs WHERE id=%s FOR UPDATE", (job_id,))
            job = self._row(cur, cur.fetchone())
            if not job:
                raise StorageUnavailable(f"Durable job {job_id} does not exist")
            cur.execute("""
                SELECT * FROM generation_stages WHERE job_id=%s AND stage_key=%s FOR UPDATE
            """, (job_id, stage_key))
            existing = self._row(cur, cur.fetchone())
            if existing:
                if existing["request_hash"] != request_hash:
                    raise DurableExecutionError(
                        f"Stage identity collision for {stage_key}; request content changed")
                return self._json_ready(existing) or {}
            enforce_budget(job, reserve, stage_key)
            cur.execute("""
                INSERT INTO generation_stages
                    (job_id,stage_key,provider,idempotency_key,request_hash,status,reserved_cost_usd)
                VALUES (%s,%s,%s,%s,%s,'running',%s) RETURNING *
            """, (job_id, stage_key, provider, idem, request_hash, reserve))
            stage = self._row(cur, cur.fetchone()) or {}
            cur.execute("""
                UPDATE generation_jobs SET reserved_cost_usd=reserved_cost_usd+%s,updated_at=now()
                WHERE id=%s
            """, (reserve, job_id))
            return self._json_ready(stage) or {}

    def note_stage(self, job_id: str, stage_key: str, patch: dict) -> None:
        with self._tx() as (_, cur):
            cur.execute("""
                UPDATE generation_stages SET result=result || %s::jsonb,updated_at=now()
                WHERE job_id=%s AND stage_key=%s
            """, (json.dumps(patch), job_id, stage_key))
            if cur.rowcount != 1:
                raise StorageUnavailable(f"Stage {stage_key} disappeared")

    def complete_stage(self, job_id: str, stage_key: str, *, actual_cost: float,
                       result: dict | None = None, artifact: dict | None = None) -> dict:
        actual = max(0.0, float(actual_cost))
        with self._tx() as (_, cur):
            cur.execute("""
                SELECT * FROM generation_stages WHERE job_id=%s AND stage_key=%s FOR UPDATE
            """, (job_id, stage_key))
            stage = self._row(cur, cur.fetchone())
            if not stage:
                raise StorageUnavailable(f"Stage {stage_key} does not exist")
            if stage["status"] == "completed":
                return self._json_ready(stage) or {}
            reserve = float(stage["reserved_cost_usd"])
            cur.execute("""
                UPDATE generation_stages SET status='completed',actual_cost_usd=%s,
                    result=%s::jsonb,artifact=%s::jsonb,error=NULL,completed_at=now(),updated_at=now()
                WHERE job_id=%s AND stage_key=%s RETURNING *
            """, (actual, json.dumps(result or {}), json.dumps(artifact or {}), job_id, stage_key))
            completed = self._row(cur, cur.fetchone()) or {}
            cur.execute("""
                UPDATE generation_jobs SET
                    reserved_cost_usd=GREATEST(0,reserved_cost_usd-%s),
                    spent_cost_usd=spent_cost_usd+%s,updated_at=now()
                WHERE id=%s
            """, (reserve, actual, job_id))
            return self._json_ready(completed) or {}

    def fail_stage(self, job_id: str, stage_key: str, error: str, *, retryable: bool = True) -> None:
        with self._tx() as (_, cur):
            cur.execute("""
                UPDATE generation_stages SET status=%s,error=%s,attempt=attempt+1,updated_at=now()
                WHERE job_id=%s AND stage_key=%s
            """, ("retry" if retryable else "failed", str(error)[:4000], job_id, stage_key))

    def update_checkpoint(self, job_id: str, checkpoint: dict) -> None:
        with self._tx() as (_, cur):
            cur.execute("""
                UPDATE generation_jobs SET checkpoint=%s::jsonb,updated_at=now() WHERE id=%s
            """, (json.dumps(checkpoint), job_id))
            if cur.rowcount != 1:
                raise StorageUnavailable(f"Durable job {job_id} does not exist")

    def set_status(self, job_id: str, status: str, *, error: str | None = None,
                   result: dict | None = None, worker_id: str | None = None) -> None:
        with self._tx() as (_, cur):
            owner = " AND lease_owner=%s" if worker_id else ""
            params: list[Any] = [status, error, json.dumps(result or {}), job_id]
            if worker_id:
                params.append(worker_id)
            cur.execute(f"""
                UPDATE generation_jobs SET status=%s,error=%s,result=result || %s::jsonb,
                    lease_owner=NULL,lease_expires_at=NULL,updated_at=now(),
                    finished_at=CASE WHEN %s IN ('done','degraded','error','rejected') THEN now()
                                     ELSE finished_at END
                WHERE id=%s{owner}
            """, (status, error, json.dumps(result or {}), status, job_id,
                  *([worker_id] if worker_id else [])))
            if cur.rowcount != 1:
                raise LeaseLost(f"Cannot transition {job_id}; worker lease was lost")

    def requeue(self, job_id: str, *, allowed_statuses: tuple[str, ...]) -> dict:
        if not allowed_statuses:
            raise ValueError("allowed_statuses cannot be empty")
        placeholders = ",".join(["%s"] * len(allowed_statuses))
        with self._tx() as (_, cur):
            cur.execute(f"""
                UPDATE generation_jobs SET status='queued',error=NULL,lease_owner=NULL,
                    lease_expires_at=NULL,updated_at=now()
                WHERE id=%s AND status IN ({placeholders}) RETURNING *
            """, (job_id, *allowed_statuses))
            row = self._json_ready(self._row(cur, cur.fetchone()))
            if not row:
                raise DurableExecutionError(
                    f"Job {job_id} is not resumable from {', '.join(allowed_statuses)}")
        self.append_event(job_id, "queued", "Resume queued durably")
        return row

    def register_artifact(self, job_id: str, kind: str, stage_key: str, artifact: dict,
                          *, provisional: bool = True) -> None:
        with self._tx() as (_, cur):
            cur.execute("""
                INSERT INTO generation_artifacts
                    (job_id,kind,stage_key,url,pathname,sha256,size_bytes,content_type,provisional)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(job_id,kind,stage_key) DO UPDATE SET
                    url=EXCLUDED.url,pathname=EXCLUDED.pathname,sha256=EXCLUDED.sha256,
                    size_bytes=EXCLUDED.size_bytes,content_type=EXCLUDED.content_type,
                    provisional=EXCLUDED.provisional
            """, (job_id, kind, stage_key, artifact["url"], artifact.get("pathname"),
                  artifact["sha256"], artifact["size_bytes"], artifact.get("content_type"),
                  provisional))

    def artifacts(self, job_id: str) -> list[dict]:
        with self._tx() as (_, cur):
            cur.execute("SELECT * FROM generation_artifacts WHERE job_id=%s ORDER BY kind,stage_key",
                        (job_id,))
            return [self._json_ready(self._row(cur, row)) or {} for row in cur.fetchall()]

    def mark_finalized(self, job_id: str) -> None:
        with self._tx() as (_, cur):
            cur.execute("UPDATE generation_artifacts SET provisional=false WHERE job_id=%s", (job_id,))

    def finalize_finished(self, job_id: str, record: dict, *, worker_id: str) -> None:
        """Atomically expose the library record and complete its durable job."""
        with self._tx() as (_, cur):
            cur.execute("SELECT lease_owner FROM generation_jobs WHERE id=%s FOR UPDATE", (job_id,))
            row = cur.fetchone()
            if not row or row[0] != worker_id:
                raise LeaseLost(f"Cannot finalize {job_id}; worker lease was lost")
            cur.execute("""
                INSERT INTO finished_videos
                    (id,title,format,status,video_url,download_url,thumbnail_url,size_bytes,
                     artifacts,metadata)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)
                ON CONFLICT(id) DO UPDATE SET
                    title=EXCLUDED.title,format=EXCLUDED.format,status=EXCLUDED.status,
                    video_url=EXCLUDED.video_url,download_url=EXCLUDED.download_url,
                    thumbnail_url=EXCLUDED.thumbnail_url,size_bytes=EXCLUDED.size_bytes,
                    artifacts=EXCLUDED.artifacts,metadata=EXCLUDED.metadata,updated_at=now()
            """, (job_id, record["title"], record.get("format"), record.get("status"),
                  record["video_url"], record.get("download_url"), record.get("thumbnail_url"),
                  record.get("size_bytes"), json.dumps(record.get("artifacts") or {}),
                  json.dumps(record.get("metadata") or {})))
            cur.execute("UPDATE generation_artifacts SET provisional=false WHERE job_id=%s", (job_id,))
            # A retry/running provider request may have been accepted before its worker vanished.
            # Charge the full reservation conservatively so completed jobs have no hidden spend.
            cur.execute("""
                UPDATE generation_stages SET status='uncertain',actual_cost_usd=reserved_cost_usd,
                    error=COALESCE(error,'Provider acceptance could not be ruled out at finalization'),
                    completed_at=now(),updated_at=now()
                WHERE job_id=%s AND status IN ('running','retry')
            """, (job_id,))
            cur.execute("""
                UPDATE generation_jobs SET status=%s,result=result || %s::jsonb,error=NULL,
                    spent_cost_usd=spent_cost_usd+reserved_cost_usd,reserved_cost_usd=0,
                    lease_owner=NULL,lease_expires_at=NULL,updated_at=now(),finished_at=now()
                WHERE id=%s
            """, (record.get("status") or "done", json.dumps({
                "title": record["title"], "artifacts": record.get("artifacts") or {},
                "video_url": record["video_url"], "archived": True,
            }), job_id))

    def finished_list(self, *, limit: int = 100, offset: int = 0,
                      query: str = "") -> list[dict]:
        self.ensure_schema()
        columns = ("id", "title", "format", "status", "video_url", "download_url",
                   "thumbnail_url", "size_bytes", "artifacts", "metadata",
                   "created_at", "updated_at")
        with self._tx() as (_, cur):
            params: list[Any] = []
            where = ""
            if query.strip():
                where = "WHERE title ILIKE %s OR id ILIKE %s"
                needle = f"%{query.strip()}%"
                params.extend((needle, needle))
            params.extend((max(1, min(int(limit), 200)), max(0, int(offset))))
            cur.execute(
                f"SELECT {','.join(columns)} FROM finished_videos {where} "
                "ORDER BY created_at DESC LIMIT %s OFFSET %s", tuple(params))
            return [self._json_ready(dict(zip(columns, row))) or {} for row in cur.fetchall()]

    def finished_get(self, video_id: str) -> dict | None:
        self.ensure_schema()
        columns = ("id", "title", "format", "status", "video_url", "download_url",
                   "thumbnail_url", "size_bytes", "artifacts", "metadata",
                   "created_at", "updated_at")
        with self._tx() as (_, cur):
            cur.execute(f"SELECT {','.join(columns)} FROM finished_videos WHERE id=%s", (video_id,))
            row = cur.fetchone()
            return self._json_ready(dict(zip(columns, row))) if row else None

    def stale_provisional(self, age_hours: int = 24, limit: int = 200) -> list[dict]:
        with self._tx() as (_, cur):
            cur.execute("""
                SELECT a.* FROM generation_artifacts a JOIN generation_jobs j ON j.id=a.job_id
                WHERE a.provisional=true AND a.created_at < now()-(%s || ' hours')::interval
                  AND j.status IN ('error','rejected') ORDER BY a.created_at LIMIT %s
            """, (max(1, age_hours), max(1, min(limit, 1000))))
            return [self._json_ready(self._row(cur, row)) or {} for row in cur.fetchall()]

    def delete_artifact_record(self, job_id: str, kind: str, stage_key: str) -> None:
        with self._tx() as (_, cur):
            cur.execute("DELETE FROM generation_artifacts WHERE job_id=%s AND kind=%s AND stage_key=%s",
                        (job_id, kind, stage_key))

    def known_pathnames(self, pathnames: list[str]) -> set[str]:
        if not pathnames:
            return set()
        with self._tx() as (_, cur):
            cur.execute(
                "SELECT pathname FROM generation_artifacts WHERE pathname=ANY(%s)",
                (pathnames,),
            )
            return {row[0] for row in cur.fetchall() if row and row[0]}


class BlobStore:
    """Small wrapper around Vercel's official Python SDK."""

    def __init__(self, token: str | None = None):
        self.token = (token or os.environ.get("BLOB_READ_WRITE_TOKEN") or "").strip()
        if not self.token:
            raise StorageUnavailable("BLOB_READ_WRITE_TOKEN is required for durable execution")
        try:
            from vercel.blob import BlobClient
            self.client = BlobClient(token=self.token)
        except Exception as exc:
            raise StorageUnavailable(f"Vercel Blob SDK unavailable: {exc}") from exc

    def upload(self, local_path: str, remote_path: str) -> dict:
        path = Path(local_path)
        if not path.is_file():
            raise StorageUnavailable(f"Artifact does not exist: {path}")
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        try:
            result = self.client.upload_file(
                path, remote_path, access="public", content_type=content_type,
                add_random_suffix=True, overwrite=False, multipart=path.stat().st_size > 100_000_000)
        except Exception as exc:
            raise StorageUnavailable(f"Blob upload failed for {remote_path}: {exc}") from exc
        return {
            "url": result.url,
            "download_url": getattr(result, "download_url", None) or result.url + "?download=1",
            "pathname": getattr(result, "pathname", None) or remote_path,
            "content_type": getattr(result, "content_type", None) or content_type,
            "size_bytes": path.stat().st_size,
            "sha256": file_sha256(path),
        }

    def download(self, artifact: dict, local_path: str) -> str:
        try:
            self.client.download_file(artifact["url"], local_path, access="public", overwrite=True)
        except Exception as exc:
            raise StorageUnavailable(f"Blob download failed: {exc}") from exc
        if file_sha256(local_path) != artifact.get("sha256"):
            raise StorageUnavailable("Downloaded checkpoint hash does not match its durable manifest")
        return local_path

    def delete(self, url_or_path: str) -> None:
        try:
            self.client.delete(url_or_path)
        except Exception as exc:
            raise StorageUnavailable(f"Blob delete failed: {exc}") from exc

    def older_objects(self, prefix: str, *, age_hours: int = 24,
                      limit: int = 1000) -> list[dict]:
        cutoff = datetime.now(timezone.utc).timestamp() - max(1, age_hours) * 3600
        objects: list[dict] = []
        try:
            for item in self.client.iter_objects(prefix=prefix, limit=max(1, min(limit, 1000))):
                uploaded = getattr(item, "uploaded_at", None)
                if uploaded and uploaded.timestamp() < cutoff:
                    objects.append({
                        "url": item.url, "pathname": item.pathname,
                        "uploaded_at": uploaded.isoformat(),
                    })
        except Exception as exc:
            raise StorageUnavailable(f"Blob orphan listing failed for {prefix}: {exc}") from exc
        return objects


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in value)[:120]


@dataclass
class DurableRuntime:
    job_id: str
    worker_id: str
    output_dir: str
    store: Any
    blob: Any
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _lease_error: Exception | None = field(default=None, init=False)
    _last_heartbeat: float = field(default=0.0, init=False)

    def assert_lease(self) -> None:
        if self._lease_error is not None:
            raise LeaseLost(f"Durable worker heartbeat failed: {self._lease_error}")

    def event(self, event_type: str, data: str, details: dict | None = None) -> None:
        self.store.append_event(self.job_id, event_type, data, details)

    def heartbeat(self) -> None:
        self.assert_lease()
        self.store.heartbeat(self.job_id, self.worker_id)
        self._last_heartbeat = time.monotonic()

    def paid_file(self, *, stage_key: str, provider: str, request: dict,
                  estimated_cost: float, output_path: str,
                  operation: Callable[[str], tuple[Any, float]]) -> tuple[Any, float, bool]:
        """Run or restore one paid file-producing operation.

        ``operation`` receives the stable provider idempotency key and returns (result, actual_cost).
        A completed stage is never called again.  If a worker dies after the provider accepted a
        request but before completion was committed, one in-flight duplicate remains possible and
        is explicitly bounded by the job's max_inflight_call_usd.
        """
        self.assert_lease()
        if time.monotonic() - self._last_heartbeat > 60:
            self.heartbeat()
        request_hash = canonical_hash(request)
        stage = self.store.prepare_stage(
            self.job_id, stage_key, provider, request_hash, estimated_cost)
        if stage.get("status") == "completed":
            artifact = stage.get("artifact") or {}
            if artifact:
                self.blob.download(artifact, output_path)
            self.event("stage_reused", stage_key, {"provider": provider})
            return stage.get("result") or {}, float(stage.get("actual_cost_usd") or 0), True
        idem = stage["idempotency_key"]
        try:
            result, actual = operation(idem)
            if not os.path.isfile(output_path) or os.path.getsize(output_path) <= 0:
                raise DurableExecutionError(f"Paid stage {stage_key} produced no file")
            suffix = Path(output_path).suffix or ".bin"
            remote = f"jobs/{_safe(self.job_id)}/stages/{_safe(stage_key)}-{uuid.uuid4().hex}{suffix}"
            artifact = self.blob.upload(output_path, remote)
            try:
                self.store.register_artifact(
                    self.job_id, "stage", stage_key, artifact, provisional=True)
            except Exception:
                try:
                    self.blob.delete(artifact["url"])
                finally:
                    raise
            self.store.complete_stage(
                self.job_id, stage_key, actual_cost=actual,
                result=result if isinstance(result, dict) else {"value": result}, artifact=artifact)
            self.event("stage_completed", stage_key,
                       {"provider": provider, "cost_usd": actual, "sha256": artifact["sha256"]})
            return result, actual, False
        except Exception as exc:
            self.store.fail_stage(self.job_id, stage_key, str(exc), retryable=True)
            self.event("stage_retry", stage_key, {"provider": provider, "error": str(exc)[:500]})
            raise

    def paid_value(self, *, stage_key: str, provider: str, request: dict,
                   estimated_cost: float,
                   operation: Callable[[str], tuple[dict, float]]) -> tuple[dict, float, bool]:
        self.assert_lease()
        if time.monotonic() - self._last_heartbeat > 60:
            self.heartbeat()
        request_hash = canonical_hash(request)
        stage = self.store.prepare_stage(
            self.job_id, stage_key, provider, request_hash, estimated_cost)
        if stage.get("status") == "completed":
            self.event("stage_reused", stage_key, {"provider": provider})
            return stage.get("result") or {}, float(stage.get("actual_cost_usd") or 0), True
        try:
            result, actual = operation(stage["idempotency_key"])
            self.store.complete_stage(
                self.job_id, stage_key, actual_cost=actual, result=result, artifact={})
            self.event("stage_completed", stage_key,
                       {"provider": provider, "cost_usd": actual})
            return result, actual, False
        except Exception as exc:
            self.store.fail_stage(self.job_id, stage_key, str(exc), retryable=True)
            self.event("stage_retry", stage_key, {"provider": provider, "error": str(exc)[:500]})
            raise

    def wrap_anthropic(self, client):
        return _AnthropicClientProxy(client, self)

    def checkpoint(self, label: str = "checkpoint", *, heartbeat: bool = True) -> dict:
        if heartbeat:
            self.heartbeat()
        os.makedirs(self.output_dir, exist_ok=True)
        tmp_dir = tempfile.mkdtemp(prefix="durable_checkpoint_")
        archive = os.path.join(tmp_dir, "checkpoint.tar.gz")
        try:
            with tarfile.open(archive, "w:gz") as tar:
                # Paid source media already has one immutable per-stage Blob object. Checkpoints
                # carry control state and review evidence, not another copy of every image/audio/
                # motion file or the final encode. Resume rehydrates those through paid_file().
                excluded_roots = {"images", "audio", "i2v", "scenes", "approved_opening"}
                review_media = {
                    "first_minute_preview.mp4", "animatic_preview.mp4",
                    "rejected_diagnostic_preview.mp4", "rendered_contact_sheet.jpg",
                }
                for child in sorted(Path(self.output_dir).rglob("*")):
                    if not child.is_file() or child.name.endswith(".tmp"):
                        continue
                    relative = child.relative_to(self.output_dir)
                    if relative.parts and relative.parts[0] in excluded_roots:
                        continue
                    if child.suffix.casefold() in {".mp3", ".wav", ".mp4"} \
                            and child.name not in review_media:
                        continue
                    tar.add(child, arcname=str(relative))
            remote = f"jobs/{_safe(self.job_id)}/checkpoints/{_safe(label)}-{uuid.uuid4().hex}.tar.gz"
            artifact = self.blob.upload(archive, remote)
            artifact.update({"label": label, "created_at": utcnow()})
            self.store.register_artifact(
                self.job_id, "checkpoint", label, artifact, provisional=True)
            self.store.update_checkpoint(self.job_id, artifact)
            self.event("checkpoint", f"Saved {label}", {"sha256": artifact["sha256"]})
            return artifact
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def restore_checkpoint(self, artifact: dict) -> None:
        if not artifact:
            return
        os.makedirs(self.output_dir, exist_ok=True)
        archive = os.path.join(tempfile.mkdtemp(prefix="durable_restore_"), "checkpoint.tar.gz")
        try:
            self.blob.download(artifact, archive)
            with tarfile.open(archive, "r:gz") as tar:
                root = Path(self.output_dir).resolve()
                for member in tar.getmembers():
                    target = (root / member.name).resolve()
                    if root not in target.parents and target != root:
                        raise StorageUnavailable("Unsafe path in checkpoint archive")
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    if not member.isfile():
                        raise StorageUnavailable("Checkpoint contains a non-regular file")
                    source = tar.extractfile(member)
                    if source is None:
                        raise StorageUnavailable("Checkpoint member could not be read")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source, open(target, "wb") as destination:
                        shutil.copyfileobj(source, destination)
        finally:
            shutil.rmtree(os.path.dirname(archive), ignore_errors=True)

    def finalize(self, video_path: str, metadata: dict,
                 extras: dict[str, str | None] | None = None) -> dict:
        self.assert_lease()
        self.heartbeat()
        uploads: dict[str, dict] = {}
        candidates = {"video": video_path, **(extras or {})}
        for kind, local_path in candidates.items():
            if not local_path or not os.path.isfile(local_path):
                continue
            suffix = Path(local_path).suffix or ".bin"
            remote = f"finished/{_safe(self.job_id)}/{_safe(kind)}-{uuid.uuid4().hex}{suffix}"
            artifact = self.blob.upload(local_path, remote)
            try:
                self.store.register_artifact(
                    self.job_id, kind, "final", artifact, provisional=True)
            except Exception:
                try:
                    self.blob.delete(artifact["url"])
                finally:
                    raise
            uploads[kind] = {"kind": kind, **artifact}
        if "video" not in uploads:
            raise StorageUnavailable("Final video could not be uploaded")
        video = uploads["video"]
        record = {
            "id": self.job_id,
            "title": metadata.get("title") or self.job_id,
            "format": metadata.get("format") or "explainer",
            "status": metadata.get("status") or "done",
            "video_url": video["url"],
            "download_url": video["download_url"],
            "thumbnail_url": (uploads.get("thumb") or uploads.get("thumbnail") or {}).get("url"),
            "size_bytes": video["size_bytes"],
            "artifacts": uploads,
            "metadata": metadata,
        }
        self.store.finalize_finished(self.job_id, record, worker_id=self.worker_id)
        self.event("finalized", "Final artifacts committed atomically",
                   {"artifact_count": len(uploads)})
        return record


_RUNTIME: ContextVar[DurableRuntime | None] = ContextVar("durable_runtime", default=None)


@contextmanager
def activate(runtime: DurableRuntime) -> Iterator[DurableRuntime]:
    token = _RUNTIME.set(runtime)
    try:
        yield runtime
    finally:
        _RUNTIME.reset(token)


def current() -> DurableRuntime | None:
    return _RUNTIME.get()


@contextmanager
def maintain_lease(runtime: DurableRuntime, *, interval_seconds: float | None = None):
    """Keep a job lease alive independently of provider polling and local FFmpeg work."""
    interval = max(5.0, float(interval_seconds or max(15, DEFAULT_LEASE_SECONDS // 3)))
    stopped = threading.Event()

    def beat() -> None:
        while not stopped.wait(interval):
            try:
                runtime.store.heartbeat(runtime.job_id, runtime.worker_id)
                runtime._last_heartbeat = time.monotonic()
            except Exception as exc:
                runtime._lease_error = exc
                stopped.set()

    runtime.heartbeat()
    thread = threading.Thread(target=beat, name=f"lease-{runtime.job_id}", daemon=True)
    thread.start()
    try:
        yield runtime
    finally:
        stopped.set()
        thread.join(timeout=2.0)


def _plain(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if hasattr(value, "model_dump"):
        return _plain(value.model_dump())
    if hasattr(value, "__dict__"):
        return {key: _plain(item) for key, item in vars(value).items() if not key.startswith("_")}
    return str(value)


class _CachedAnthropicResponse:
    def __init__(self, payload: dict):
        self._payload = payload
        self.content = [SimpleNamespace(**block) for block in payload.get("content") or []]
        self.usage = SimpleNamespace(**(payload.get("usage") or {}))

    def model_dump(self) -> dict:
        return self._payload


class _AnthropicMessagesProxy:
    def __init__(self, messages, runtime: DurableRuntime):
        self._messages = messages
        self._runtime = runtime

    def create(self, **kwargs):
        request = _plain(kwargs)
        digest = canonical_hash(request)
        stage_key = f"anthropic:{digest[:32]}"
        max_tokens = int(kwargs.get("max_tokens") or 4096)
        input_chars = len(json.dumps(request, default=str))
        estimated = min(
            DEFAULT_MAX_INFLIGHT_USD,
            max(0.01, input_chars / 4 * 5 / 1_000_000 + max_tokens * 25 / 1_000_000))

        def invoke(idempotency_key: str):
            call_kwargs = dict(kwargs)
            headers = dict(call_kwargs.pop("extra_headers", None) or {})
            headers["Idempotency-Key"] = idempotency_key
            response = self._messages.create(**call_kwargs, extra_headers=headers)
            payload = _plain(response)
            usage = payload.get("usage") or {}
            actual = (
                float(usage.get("input_tokens") or 0) * 5 / 1_000_000
                + float(usage.get("output_tokens") or 0) * 25 / 1_000_000
            )
            return payload, actual

        payload, _, _ = self._runtime.paid_value(
            stage_key=stage_key, provider="anthropic", request=request,
            estimated_cost=estimated, operation=invoke)
        return _CachedAnthropicResponse(payload)


class _AnthropicClientProxy:
    def __init__(self, client, runtime: DurableRuntime):
        self._client = client
        self.messages = _AnthropicMessagesProxy(client.messages, runtime)

    def __getattr__(self, name: str):
        return getattr(self._client, name)


def cleanup_orphans(store: PostgresStore, blob: BlobStore, *, age_hours: int = 24,
                    limit: int = 200) -> dict:
    deleted, untracked_deleted, errors = 0, 0, []
    for artifact in store.stale_provisional(age_hours=age_hours, limit=limit):
        try:
            blob.delete(artifact["url"])
            store.delete_artifact_record(
                artifact["job_id"], artifact["kind"], artifact["stage_key"])
            deleted += 1
        except Exception as exc:
            errors.append(str(exc))
    # A process can die after Blob accepted bytes but before Postgres registered the URL. Reconcile
    # aged objects under application-owned prefixes against the authoritative artifact manifest.
    if hasattr(blob, "older_objects") and hasattr(store, "known_pathnames"):
        try:
            candidates = []
            per_prefix = max(1, min(limit, 1000) // 2)
            for prefix in ("jobs/", "finished/"):
                candidates.extend(blob.older_objects(
                    prefix, age_hours=age_hours, limit=per_prefix))
            known = store.known_pathnames([item["pathname"] for item in candidates])
            for item in candidates:
                if item["pathname"] in known:
                    continue
                blob.delete(item["url"])
                untracked_deleted += 1
        except Exception as exc:
            errors.append(str(exc))
    return {"deleted": deleted, "untracked_deleted": untracked_deleted,
            "errors": errors, "passed": not errors}
