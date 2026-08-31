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
# A worker must become reclaimable before the hosting function ceiling.
os.environ.setdefault("DURABLE_JOB_LEASE_SECONDS", "600")
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
    """PR7/PR8 additions to the durable job store without weakening the PR6 engine."""

    _pilot_schema_ready = False
    _production_schema_ready = False

    def reclassify_delivered_directed_pilot(self, job_id: str, grading: dict) -> dict:
        """Correct the legacy `degraded` overload after inspecting immutable grade evidence.

        This changes lifecycle labels only. It never edits the rendered contract, video, spend,
        request, or artifact hashes. Deterministic hard failures remain ineligible.
        """
        if grading.get("technical_status") != "completed" or grading.get("hard_failures"):
            raise DurableExecutionError("Only technically complete pilots without hard failures qualify")
        patch = {
            "technical_status": "completed",
            "automated_grade_status": grading.get("automated_status"),
            "editorial_status": grading.get("editorial_status"),
            "promotion_status": grading.get("promotion_status"),
            "legacy_delivery_status": "degraded",
        }
        changed = False
        with self._tx() as (_, cur):
            cur.execute("SELECT * FROM generation_jobs WHERE id=%s FOR UPDATE", (job_id,))
            row = self._json_ready(self._row(cur, cur.fetchone())) or {}
            if not row:
                raise DurableExecutionError(f"Directed pilot job {job_id} does not exist")
            if row.get("status") == "degraded":
                cur.execute("""
                    UPDATE generation_jobs SET status='done',result=result || %s::jsonb,
                        updated_at=now() WHERE id=%s
                """, (json.dumps(patch), job_id))
                changed = True
            elif row.get("status") != "done":
                raise DurableExecutionError(
                    f"Directed pilot {job_id} is not a delivered legacy job")
            cur.execute("""
                UPDATE finished_videos SET status='done',metadata=metadata || %s::jsonb,
                    updated_at=now() WHERE id=%s
            """, (json.dumps(patch), job_id))
            if cur.rowcount != 1:
                raise DurableExecutionError(f"Finished directed pilot {job_id} does not exist")
        if changed:
            self.append_event(
                job_id, "delivery_reclassified",
                "Technical delivery separated from unavailable automated grade", patch)
        return self.get_job(job_id) or {}

    def rearm_infrastructure_failure(
            self, job_id: str, *, error_fragment: str, extra_attempts: int = 3) -> dict:
        """Add a bounded retry window without changing payload, stages, spend, or cost ceiling."""
        fragment = str(error_fragment or "").strip()
        if not fragment or len(fragment) > 160:
            raise DurableExecutionError("A bounded infrastructure error fragment is required")
        retries = max(1, min(int(extra_attempts), 3))
        with self._tx() as (_, cur):
            cur.execute("SELECT * FROM generation_jobs WHERE id=%s FOR UPDATE", (job_id,))
            current = self._json_ready(self._row(cur, cur.fetchone())) or {}
            if (not current or current.get("status") != "error"
                    or fragment not in str(current.get("error") or "")
                    or float(current.get("reserved_cost_usd") or 0) != 0
                    or float(current.get("spent_cost_usd") or 0)
                    >= float(current.get("max_cost_usd") or 0)):
                raise DurableExecutionError(
                    f"Job {job_id} is not eligible for infrastructure rearm")
            cur.execute("""
                UPDATE generation_jobs SET status='queued',error=NULL,
                    max_attempts=GREATEST(max_attempts,attempts+%s),
                    lease_owner=NULL,lease_expires_at=NULL,updated_at=now()
                WHERE id=%s RETURNING *
            """, (retries, job_id))
            row = self._json_ready(self._row(cur, cur.fetchone())) or {}
        self.append_event(job_id, "infrastructure_rearmed", "Infrastructure retry window added", {
            "prior_error": fragment, "extra_attempts": retries,
            "spent_cost_usd": row.get("spent_cost_usd"),
            "max_cost_usd": row.get("max_cost_usd"),
        })
        return row

    def rearm_disk_exhaustion(self, job_id: str, *, extra_attempts: int = 3) -> dict:
        """Resume one ENOSPC job while preserving a single ambiguous paid-stage reservation.

        A worker can run out of local disk while restoring an already-completed Blob artifact.
        Another paid stage may still be in ``retry`` from an earlier interrupted attempt.  Its
        reservation must not be erased: prepare_stage will reuse its stable idempotency key, and
        complete_stage will settle the same reservation.  This method therefore accepts exactly
        one bounded retry/running stage whose reservation reconciles to the job total.
        """
        retries = max(1, min(int(extra_attempts), 3))
        error_fragment = "No space left on device"
        with self._tx() as (_, cur):
            cur.execute("SELECT * FROM generation_jobs WHERE id=%s FOR UPDATE", (job_id,))
            current = self._json_ready(self._row(cur, cur.fetchone())) or {}
            reserved = float(current.get("reserved_cost_usd") or 0)
            if (not current or current.get("status") != "error"
                    or error_fragment not in str(current.get("error") or "")
                    or float(current.get("spent_cost_usd") or 0)
                    >= float(current.get("max_cost_usd") or 0)):
                raise DurableExecutionError(f"Job {job_id} is not eligible for disk recovery")
            cur.execute("""
                SELECT stage_key,status,reserved_cost_usd FROM generation_stages
                WHERE job_id=%s AND status IN ('running','retry') FOR UPDATE
            """, (job_id,))
            open_stages = [self._json_ready(self._row(cur, raw)) or {}
                           for raw in cur.fetchall()]
            stage_reserved = sum(float(item.get("reserved_cost_usd") or 0)
                                 for item in open_stages)
            if (reserved == 0 and open_stages) or len(open_stages) > 1 \
                    or abs(stage_reserved - reserved) > 0.0001 \
                    or reserved > float(current.get("max_inflight_call_usd") or 0):
                raise DurableExecutionError(
                    f"Job {job_id} has ambiguous stage reservations; disk recovery stopped")
            cur.execute("""
                UPDATE generation_jobs SET status='queued',error=NULL,
                    max_attempts=GREATEST(max_attempts,attempts+%s),
                    lease_owner=NULL,lease_expires_at=NULL,updated_at=now()
                WHERE id=%s RETURNING *
            """, (retries, job_id))
            row = self._json_ready(self._row(cur, cur.fetchone())) or {}
        self.append_event(job_id, "disk_exhaustion_rearmed",
                          "Bounded local-disk recovery window added", {
            "prior_error": error_fragment,
            "extra_attempts": retries,
            "preserved_reserved_cost_usd": reserved,
            "preserved_stage_key": (open_stages[0].get("stage_key") if open_stages else None),
            "spent_cost_usd": row.get("spent_cost_usd"),
            "max_cost_usd": row.get("max_cost_usd"),
        })
        return row

    def ensure_directed_full_film_recovery_window(
            self, job_id: str, *, minimum_remaining_attempts: int = 12) -> dict:
        """Keep an approved, stage-idempotent full film resumable across function windows.

        A five-minute directed film can legitimately require several serverless invocations even
        after every paid provider result is durable.  This changes only the retry counter; the
        immutable request, authorization hash, stage idempotency keys, reservations, accumulated
        spend, and hard cost ceiling remain untouched.
        """
        remaining = max(1, min(int(minimum_remaining_attempts), 12))
        with self._tx() as (_, cur):
            cur.execute("SELECT * FROM generation_jobs WHERE id=%s FOR UPDATE", (job_id,))
            current = self._json_ready(self._row(cur, cur.fetchone())) or {}
            request = current.get("request") if isinstance(current.get("request"), dict) else {}
            if (not current or request.get("directed_full_film") is not True
                    or float(current.get("spent_cost_usd") or 0)
                    >= float(current.get("max_cost_usd") or 0)):
                raise DurableExecutionError(
                    f"Job {job_id} is not eligible for directed full-film recovery")
            cur.execute("""
                UPDATE generation_jobs
                SET max_attempts=GREATEST(max_attempts,attempts+%s),updated_at=now()
                WHERE id=%s RETURNING *
            """, (remaining, job_id))
            row = self._json_ready(self._row(cur, cur.fetchone())) or {}
        return row

    def requeue_next_directed_storage_error(self) -> dict | None:
        """Requeue one approved checkpointed ENOSPC film once for automatic recovery.

        Selection is deliberately narrow: full-film request, approved queued action, checkpoint,
        zero reservation, remaining budget, and no prior automatic disk rearm. Persistent failures
        therefore stop after one automatic continuation and remain visible to the operator.
        """
        self.ensure_schema()
        with self._tx() as (_, cur):
            cur.execute("""
                SELECT j.* FROM generation_jobs j
                WHERE j.status='storage_error'
                  AND j.error ILIKE '%No space left on device%'
                  AND j.request->>'directed_full_film'='true'
                  AND j.reserved_cost_usd=0
                  AND j.spent_cost_usd < j.max_cost_usd
                  AND j.checkpoint <> '{}'::jsonb
                  AND EXISTS (
                      SELECT 1 FROM agent_actions a
                      WHERE a.job_id=j.id
                        AND a.operation='directed_full_film'
                        AND a.status='queued'
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM generation_events e
                      WHERE e.job_id=j.id
                        AND e.event_type='directed_storage_auto_rearmed'
                  )
                ORDER BY j.updated_at ASC
                FOR UPDATE SKIP LOCKED LIMIT 1
            """)
            current = self._json_ready(self._row(cur, cur.fetchone()))
            if not current:
                return None
            cur.execute("""
                UPDATE generation_jobs SET status='queued',error=NULL,
                    max_attempts=GREATEST(max_attempts,attempts+3),
                    lease_owner=NULL,lease_expires_at=NULL,updated_at=now()
                WHERE id=%s RETURNING *
            """, (current["id"],))
            row = self._json_ready(self._row(cur, cur.fetchone())) or {}
            cur.execute("""
                INSERT INTO generation_events(job_id,event_type,data,details)
                VALUES (%s,'directed_storage_auto_rearmed',
                        'Checkpointed directed film automatically rearmed after local disk repair',
                        %s::jsonb)
            """, (row["id"], json.dumps({
                "prior_error": current.get("error"),
                "spent_cost_usd": row.get("spent_cost_usd"),
                "max_cost_usd": row.get("max_cost_usd"),
            })))
            return row

    def rearm_next_directed_audio_runtime_failure(self) -> dict | None:
        """Requeue one approved directed pilot stopped at the pre-image audio runtime gate.

        The immutable request, completed TTS stages, checkpoint and cost ceiling are untouched.
        A generation event makes this a one-shot salvage so a persistent failure cannot loop.
        """
        self.ensure_schema()
        with self._tx() as (_, cur):
            cur.execute("""
                SELECT j.* FROM generation_jobs j
                WHERE j.status='error'
                  AND j.error ILIKE '%measured pilot narration %visual spending stopped%'
                  AND j.reserved_cost_usd=0
                  AND j.spent_cost_usd < j.max_cost_usd
                  AND j.checkpoint <> '{}'::jsonb
                  AND EXISTS (
                      SELECT 1 FROM agent_actions a
                      WHERE a.job_id=j.id AND a.operation='directed_pilot'
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM generation_events e
                      WHERE e.job_id=j.id AND e.event_type='directed_audio_fit_rearmed'
                  )
                ORDER BY j.updated_at ASC
                FOR UPDATE SKIP LOCKED LIMIT 1
            """)
            current = self._json_ready(self._row(cur, cur.fetchone()))
            if not current:
                return None
            cur.execute("""
                UPDATE generation_jobs SET status='queued',error=NULL,
                    max_attempts=GREATEST(max_attempts,attempts+2),
                    lease_owner=NULL,lease_expires_at=NULL,updated_at=now()
                WHERE id=%s RETURNING *
            """, (current["id"],))
            row = self._json_ready(self._row(cur, cur.fetchone())) or {}
            cur.execute("""
                INSERT INTO generation_events(job_id,event_type,data,details)
                VALUES (%s,'directed_audio_fit_rearmed',
                        'Approved directed pilot rearmed for bounded audio runtime fit',
                        %s::jsonb)
            """, (row["id"], json.dumps({
                "prior_error": current.get("error"),
                "spent_cost_usd": row.get("spent_cost_usd"),
                "max_cost_usd": row.get("max_cost_usd"),
            })))
            return row

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

    def ensure_production_schema(self) -> None:
        self.ensure_schema()
        if self._production_schema_ready:
            return
        with self._tx() as (_, cur):
            cur.execute("""
                CREATE TABLE IF NOT EXISTS controlled_production_runs (
                    id text PRIMARY KEY,
                    request_hash text NOT NULL,
                    selection_sha256 text NOT NULL,
                    source_batch_id text NOT NULL,
                    job_id text NOT NULL REFERENCES generation_jobs(id),
                    status text NOT NULL DEFAULT 'queued',
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now()
                )""")
        self._production_schema_ready = True

    def enqueue_production_run(self, *, production_id: str, request: dict, source_batch_id: str,
                               max_cost_usd: float, pipeline_version: str) -> dict:
        """Create the single durable 90-second production job for an already-won PR7 structure.

        A production run is unique per ``production_id``: re-posting the same id returns the
        existing job, and a different immutable request under that id is rejected rather than
        silently replacing a run that may already have spent money.
        """
        from longform_production import validate_production_request

        validate_production_request(request)
        source_batch_id = str(source_batch_id or "").strip()
        if not source_batch_id:
            raise DurableExecutionError("A production run must name its source PR7 batch")
        self.ensure_production_schema()
        request_hash = canonical_hash(request)
        job_id = f"{production_id}-video"
        with self._tx() as (_, cur):
            cur.execute("SELECT * FROM controlled_production_runs WHERE id=%s FOR UPDATE",
                        (production_id,))
            existing = self._row(cur, cur.fetchone())
            if existing:
                if existing.get("request_hash") != request_hash:
                    raise DurableExecutionError(
                        f"Production run {production_id} already exists with a different "
                        f"immutable request")
                cur.execute("SELECT * FROM generation_jobs WHERE id=%s", (existing["job_id"],))
                job = self._json_ready(self._row(cur, cur.fetchone())) or {}
                return {**(self._json_ready(existing) or {}), "job": job}
            cur.execute("""
                INSERT INTO generation_jobs
                    (id,kind,request,status,max_cost_usd,max_inflight_call_usd,
                     pipeline_version,output_prefix,max_attempts)
                VALUES (%s,'explainer_production',%s::jsonb,'queued',%s,%s,%s,%s,1)
                RETURNING *
            """, (job_id, json.dumps(request), max_cost_usd, _legacy.DEFAULT_MAX_INFLIGHT_USD,
                  pipeline_version, f"production/{production_id}"))
            job = self._json_ready(self._row(cur, cur.fetchone())) or {}
            cur.execute("""
                INSERT INTO controlled_production_runs
                    (id,request_hash,selection_sha256,source_batch_id,job_id,status)
                VALUES (%s,%s,%s,%s,%s,'queued')
            """, (production_id, request_hash, request["selection_sha256"], source_batch_id,
                  job_id))
        self.append_event(job_id, "queued", "Controlled PR8 production run queued durably", {
            "production_id": production_id,
            "source_batch_id": source_batch_id,
            "selection_sha256": request["selection_sha256"],
        })
        return {"id": production_id, "request_hash": request_hash,
                "selection_sha256": request["selection_sha256"],
                "source_batch_id": source_batch_id, "status": "queued", "job": job}

    def get_production_run(self, production_id: str) -> dict | None:
        self.ensure_production_schema()
        with self._tx() as (_, cur):
            cur.execute("SELECT * FROM controlled_production_runs WHERE id=%s", (production_id,))
            run = self._json_ready(self._row(cur, cur.fetchone()))
            if not run:
                return None
            cur.execute("SELECT * FROM generation_jobs WHERE id=%s", (run["job_id"],))
            job = self._json_ready(self._row(cur, cur.fetchone())) or {}
        status = job.get("status")
        if status in ("production_passed", "production_failed", "storage_error"):
            run["status"] = "complete"
        elif status == "production_awaiting_editorial":
            run["status"] = "awaiting_editorial"
        elif status == "processing":
            run["status"] = "processing"
        run["job"] = job
        return run

    def set_status(self, job_id: str, status: str, *, error: str | None = None,
                   result: dict | None = None, worker_id: str | None = None) -> None:
        terminal = {"done", "degraded", "error", "rejected", "pilot_passed", "pilot_failed",
                    "production_passed", "production_failed"}
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
                access="auto",
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
            blob_compat.download_file(
                artifact["url"], local_path, credentials=self.credentials,
                access=artifact.get("access") or "auto", overwrite=True)
        except blob_compat.BlobAuthError as exc:
            raise StorageUnavailable(f"Blob download failed: {exc}") from exc
        if artifact.get("sha256") and file_sha256(local_path) != artifact.get("sha256"):
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
