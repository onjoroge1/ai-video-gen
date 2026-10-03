"""Compatibility facade for durable execution with modern Vercel Blob auth.

The durable execution engine in ``_durable_execution_legacy.py`` owns leases, paid stages and
bounded cooperative continuation. This facade re-exports it and supplies the
Blob storage adapter so production can authenticate with either:

* ``BLOB_READ_WRITE_TOKEN`` (legacy/static token), or
* Vercel OIDC + ``BLOB_STORE_ID`` / ``BLOB_READ_WRITE_TOKEN_STORE_ID``.

Provider responses and control-state checkpoints remain durable across worker windows.
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


RESEARCH_BUDGET_RECOVERY = "research_search_budget_recovery_v1"
STORYBOARD_RECOVERY = "illustrated_storyboard_recovery_v1"
STORYBOARD_BUDGET_RECOVERY = "illustrated_storyboard_opening_budget_recovery_v2"
_RESERVATION_FAILURE = re.compile(
    r"Stage (anthropic:[0-9a-f]{32}) reserves \$([0-9]+\.[0-9]{4}); "
    r"the single-call ceiling is \$([0-9]+\.[0-9]{4})")


def research_budget_recovery(job: dict) -> dict:
    """Recognize an unspent search-sized overflow, without changing any job state.

    Dispatch additionally locks and reconciles the stage ledger. This intentionally excludes
    settlement overruns, total-budget exhaustion and all content/quality failures.
    """
    match = _RESERVATION_FAILURE.fullmatch(str(job.get("error") or ""))
    if not match or job.get("status") != "error":
        return {}
    stage_key, reserve, ceiling = match.group(1), float(match.group(2)), float(match.group(3))
    if (not 0 < reserve - ceiling <= .0601 or ceiling <= 0
            or abs(float(job.get("max_inflight_call_usd") or 0) - ceiling) > .000051
            or job.get("lease_owner") or job.get("lease_expires_at")
            or float(job.get("reserved_cost_usd") or 0) != 0
            or float(job.get("spent_cost_usd") or 0) + ceiling
            > float(job.get("max_cost_usd") or 0) + 1e-9
            or not re.fullmatch(r"[0-9a-f]{64}", str((job.get("checkpoint") or {}).get("sha256") or ""))
            or (job.get("result") or {}).get(RESEARCH_BUDGET_RECOVERY)):
        return {}
    return {"stage_key": stage_key, "reserve": reserve, "ceiling": ceiling}


def storyboard_recovery(job: dict) -> bool:
    """Candidate for a single repair; dispatch must also reproduce the saved failure."""
    from storyboard_repair import repairable_failure
    return bool(job.get("status") == "error" and repairable_failure(job.get("error"))
                and not job.get("lease_owner") and not job.get("lease_expires_at")
                and float(job.get("reserved_cost_usd") or 0) == 0
                and float(job.get("spent_cost_usd") or 0) < float(job.get("max_cost_usd") or 0)
                and re.fullmatch(r"[0-9a-f]{64}", str((job.get("checkpoint") or {}).get("sha256") or ""))
                and not (job.get("result") or {}).get(STORYBOARD_RECOVERY))


def storyboard_budget_recovery(job: dict) -> bool:
    """Candidate for one stricter edit after the saved v1 response missed its word budget."""
    from storyboard_repair import repairable_failure
    result = job.get("result") or {}
    return bool(job.get("status") == "error" and repairable_failure(job.get("error"))
                and not job.get("lease_owner") and not job.get("lease_expires_at")
                and float(job.get("reserved_cost_usd") or 0) == 0
                and float(job.get("spent_cost_usd") or 0) < float(job.get("max_cost_usd") or 0)
                and re.fullmatch(r"[0-9a-f]{64}", str((job.get("checkpoint") or {}).get("sha256") or ""))
                and result.get(STORYBOARD_RECOVERY)
                and not result.get(STORYBOARD_BUDGET_RECOVERY))


class PostgresStore(_legacy.PostgresStore):
    """PR7/PR8 additions to the durable job store without weakening the PR6 engine."""

    _pilot_schema_ready = False
    _production_schema_ready = False

    def resume_storyboard_failure(self, job_id: str, *, expected_checkpoint_sha256: str,
                                  expected_error: str, failure_sha256: str) -> dict:
        """Queue the exact reproduced pre-media failure once, preserving every paid stage."""
        if not all(re.fullmatch(r"[0-9a-f]{64}", h)
                   for h in (expected_checkpoint_sha256, failure_sha256)):
            raise DurableExecutionError("Storyboard recovery requires exact saved hashes")
        with self._tx() as (_, cur):
            cur.execute("SELECT * FROM generation_jobs WHERE id=%s FOR UPDATE", (job_id,))
            job = self._json_ready(self._row(cur, cur.fetchone())) or {}
            if job.get("status") in {"queued", "processing"}:
                return job
            if (not storyboard_recovery(job) or job.get("error") != expected_error
                    or (job.get("checkpoint") or {}).get("sha256") != expected_checkpoint_sha256):
                raise DurableExecutionError("Job is not eligible for storyboard recovery")
            cur.execute("""
                SELECT stage_key,status FROM generation_stages WHERE job_id=%s
                AND status NOT IN ('completed','incomplete') FOR UPDATE
            """, (job_id,))
            if cur.fetchall():
                raise DurableExecutionError("Storyboard recovery has an unresolved provider stage")
            marker = {STORYBOARD_RECOVERY: {"checkpoint_sha256": expected_checkpoint_sha256,
                                          "failure_sha256": failure_sha256,
                                          "prior_error": expected_error}}
            cur.execute("""
                UPDATE generation_jobs SET status='queued',error=NULL,
                    max_attempts=GREATEST(max_attempts,attempts+1),
                    result=result || %s::jsonb,updated_at=now()
                WHERE id=%s RETURNING *
            """, (json.dumps(marker), job_id))
            row = self._json_ready(self._row(cur, cur.fetchone())) or {}
        self.append_event(job_id, "infrastructure_rearmed",
                          "Saved storyboard queued for one bounded narration repair")
        return row

    def resume_storyboard_budget_failure(self, job_id: str, *, expected_checkpoint_sha256: str,
                                         expected_error: str, failure_sha256: str,
                                         prior_repair_sha256: str) -> dict:
        """Queue one exact v2 edit after v1 exceeded the opening narration budget."""
        hashes = (expected_checkpoint_sha256, failure_sha256, prior_repair_sha256)
        if not all(re.fullmatch(r"[0-9a-f]{64}", value) for value in hashes):
            raise DurableExecutionError("Storyboard budget recovery requires exact saved hashes")
        with self._tx() as (_, cur):
            cur.execute("SELECT * FROM generation_jobs WHERE id=%s FOR UPDATE", (job_id,))
            job = self._json_ready(self._row(cur, cur.fetchone())) or {}
            if job.get("status") in {"queued", "processing"}:
                return job
            prior = (job.get("result") or {}).get(STORYBOARD_RECOVERY) or {}
            if (not storyboard_budget_recovery(job) or job.get("error") != expected_error
                    or (job.get("checkpoint") or {}).get("sha256") != expected_checkpoint_sha256
                    or not re.fullmatch(r"[0-9a-f]{64}", str(prior.get("failure_sha256") or ""))):
                raise DurableExecutionError("Job is not eligible for storyboard budget recovery")
            cur.execute("""
                SELECT stage_key,status FROM generation_stages WHERE job_id=%s
                AND status NOT IN ('completed','incomplete') FOR UPDATE
            """, (job_id,))
            if cur.fetchall():
                raise DurableExecutionError(
                    "Storyboard budget recovery has an unresolved provider stage")
            marker = {STORYBOARD_BUDGET_RECOVERY: {
                "checkpoint_sha256": expected_checkpoint_sha256,
                "failure_sha256": failure_sha256,
                "prior_repair_sha256": prior_repair_sha256,
                "prior_error": expected_error,
            }}
            cur.execute("""
                UPDATE generation_jobs SET status='queued',error=NULL,
                    max_attempts=GREATEST(max_attempts,attempts+1),
                    result=result || %s::jsonb,updated_at=now()
                WHERE id=%s RETURNING *
            """, (json.dumps(marker), job_id))
            row = self._json_ready(self._row(cur, cur.fetchone())) or {}
        self.append_event(job_id, "infrastructure_rearmed",
                          "Saved storyboard queued with exact opening scene budgets")
        return row

    def resume_research_budget_block(self, job_id: str, *, expected_checkpoint_sha256: str) -> dict:
        """One explicit recovery of a rejected, unpurchased call under unchanged limits."""
        if not re.fullmatch(r"[0-9a-f]{64}", expected_checkpoint_sha256):
            raise DurableExecutionError("Budget recovery requires the saved checkpoint hash")
        with self._tx() as (_, cur):
            cur.execute("SELECT * FROM generation_jobs WHERE id=%s FOR UPDATE", (job_id,))
            job = self._json_ready(self._row(cur, cur.fetchone())) or {}
            if job.get("status") in {"queued", "processing"}:
                return job
            block = research_budget_recovery(job)
            if (not block or (job.get("checkpoint") or {}).get("sha256")
                    != expected_checkpoint_sha256):
                raise DurableExecutionError("Job is not eligible for research-budget recovery")
            cur.execute("""
                SELECT stage_key,status FROM generation_stages WHERE job_id=%s
                AND (stage_key=%s OR status NOT IN ('completed','incomplete')) FOR UPDATE
            """, (job_id, block["stage_key"]))
            if cur.fetchall():
                raise DurableExecutionError("Research recovery has an existing or unresolved provider stage")
            patch = {RESEARCH_BUDGET_RECOVERY: {
                "checkpoint_sha256": expected_checkpoint_sha256,
                "stage_key": block["stage_key"], "prior_error": job["error"],
            }}
            cur.execute("""
                UPDATE generation_jobs SET status='queued',error=NULL,
                    max_attempts=GREATEST(max_attempts,attempts+1),
                    result=result || %s::jsonb,updated_at=now()
                WHERE id=%s RETURNING *
            """, (json.dumps(patch), job_id))
            row = self._json_ready(self._row(cur, cur.fetchone())) or {}
        self.append_event(job_id, "infrastructure_rearmed",
                          "Research resumed within the existing spending limits")
        return row

    def resume_planning_review(self, job_id, *, expected_checkpoint_sha256, evidence):
        """One contract migration; all prior paid stages and the cap stay intact."""
        import planning_review_recovery as recovery
        import planning_evidence
        from _durable_execution_legacy import _CachedAnthropicResponse
        with self._tx() as (_, cur):
            cur.execute("SELECT * FROM generation_jobs WHERE id=%s FOR UPDATE", (job_id,))
            job = self._json_ready(self._row(cur, cur.fetchone())) or {}
            prior = (job.get("result") or {}).get(recovery.MARKER) or {}
            if (job.get("status") in {"queued", "processing"}
                    and prior.get("checkpoint_sha256") == expected_checkpoint_sha256):
                return job
            if (not recovery.eligible(job) or (job.get("checkpoint") or {}).get("sha256")
                    != expected_checkpoint_sha256):
                raise DurableExecutionError("Job is not eligible for planning review migration")
            cur.execute("SELECT * FROM generation_stages WHERE job_id=%s FOR UPDATE", (job_id,))
            stages = [self._json_ready(self._row(cur, raw)) or {} for raw in cur.fetchall()]
            if not stages or any(s.get("status") != "completed" or s.get("provider") != "anthropic"
                                 for s in stages):
                raise DurableExecutionError("Review migration has unfinished or non-script provider work")
            failures = 0
            for stage in stages:
                value = stage.get("result") or {}
                if not any(b.get("type") == "tool_use" and b.get("name") == "submit_claim_support"
                           for b in value.get("content", []) if isinstance(b, dict)):
                    continue
                try:
                    planning_evidence._verdicts(_CachedAnthropicResponse(value), evidence["claim_ids"])
                except ValueError as exc:
                    if str(exc) == recovery.LEGACY_ERROR:
                        failures += 1
                    else:
                        raise DurableExecutionError("Saved review does not reproduce the coverage failure") from exc
            if failures != 1:
                raise DurableExecutionError("Expected one saved incomplete claim review")
            marker = {recovery.MARKER: {"checkpoint_sha256": expected_checkpoint_sha256,
                                       "research_hash": evidence["research_hash"]}}
            cur.execute("""
                UPDATE generation_jobs SET status='queued',error=NULL,
                    max_attempts=GREATEST(max_attempts,attempts+1),
                    result=result || %s::jsonb,finished_at=NULL,updated_at=now()
                WHERE id=%s RETURNING *
            """, (json.dumps(marker), job_id))
            row = self._json_ready(self._row(cur, cur.fetchone())) or {}
        self.append_event(job_id, "infrastructure_rearmed", "Resuming saved research with bounded claim review")
        return row

    def resume_provider_block(self, job_id: str, *, expected_checkpoint_sha256: str) -> dict:
        """One explicit resume of a provider account block, for any topic or stage.

        No automatic worker/cron path calls this. A rejected retry pauses again. Unknown
        outcomes, content failures and budget exhaustion do not qualify. Preserve the
        existing stage identity and reservation until actual usage is settled.
        """
        import provider_blocks
        if not re.fullmatch(r"[0-9a-f]{64}", expected_checkpoint_sha256):
            raise DurableExecutionError("Provider resume requires the saved checkpoint hash")
        with self._tx() as (_, cur):
            cur.execute("SELECT * FROM generation_jobs WHERE id=%s FOR UPDATE", (job_id,))
            job = self._json_ready(self._row(cur, cur.fetchone())) or {}
            if job.get("status") in {"queued", "processing"}:
                return job  # concurrent clicks cannot create two recovery attempts
            block = provider_blocks.for_job(job)
            reserved = float(job.get("reserved_cost_usd") or 0)
            if (not block or (job.get("checkpoint") or {}).get("sha256")
                    != expected_checkpoint_sha256 or reserved <= 0
                    or float(job.get("spent_cost_usd") or 0) + reserved
                    > float(job.get("max_cost_usd") or 0) + 1e-9
                    or reserved > float(job.get("max_inflight_call_usd") or 0) + 1e-9):
                raise DurableExecutionError("Job is not eligible for provider-account resume")
            cur.execute("""
                SELECT * FROM generation_stages WHERE job_id=%s
                AND status IN ('running','retry') FOR UPDATE
            """, (job_id,))
            stages = [self._json_ready(self._row(cur, raw)) or {} for raw in cur.fetchall()]
            stage = stages[0] if len(stages) == 1 else {}
            recorded = (stage.get("result") or {}).get("provider_block") or (
                provider_blocks.from_recorded_error(stage.get("error")))
            if (len(stages) != 1 or stage.get("status") != "retry"
                    or stage.get("provider") != "anthropic"
                    or not str(stage.get("stage_key") or "").startswith("anthropic:")
                    or recorded.get("code") != block["code"]
                    or recorded.get("http_status") != block["http_status"]
                    or abs(float(stage.get("reserved_cost_usd") or 0) - reserved) > 0.0001):
                raise DurableExecutionError("Provider stage outcome or reservation is ambiguous")
            patch = {"provider_block": block,
                     "provider_resume_count": int((job.get("result") or {}).get(
                         "provider_resume_count") or 0) + 1}
            cur.execute("""
                UPDATE generation_jobs SET status='queued',error=NULL,
                    max_attempts=GREATEST(max_attempts,attempts+1),
                    result=result || %s::jsonb,lease_owner=NULL,lease_expires_at=NULL,
                    finished_at=NULL,updated_at=now() WHERE id=%s RETURNING *
            """, (json.dumps(patch), job_id))
            row = self._json_ready(self._row(cur, cur.fetchone())) or {}
        self.append_event(job_id, "provider_resumed", "Resuming after provider access repair")
        return row

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
            self, job_id: str, *, error_fragment: str, extra_attempts: int = 3,
            recovery_key: str = "", expected_checkpoint_sha256: str = "") -> dict:
        """Add a bounded retry window without changing payload, stages, spend, or cost ceiling."""
        fragment = str(error_fragment or "").strip()
        if not fragment or len(fragment) > 160:
            raise DurableExecutionError("A bounded infrastructure error fragment is required")
        if recovery_key or expected_checkpoint_sha256:
            if (not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", recovery_key)
                    or not re.fullmatch(r"[0-9a-f]{64}", expected_checkpoint_sha256)):
                raise DurableExecutionError("Recovery requires a key and exact checkpoint hash")
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
            recovery = {}
            if recovery_key:
                if ((current.get("result") or {}).get(recovery_key)
                        or (current.get("checkpoint") or {}).get("sha256")
                        != expected_checkpoint_sha256):
                    raise DurableExecutionError("Recovery was already used or its checkpoint changed")
                recovery[recovery_key] = {
                    "checkpoint_sha256": expected_checkpoint_sha256,
                    "prior_error": current.get("error"),
                }
            cur.execute("""
                UPDATE generation_jobs SET status='queued',error=NULL,
                    max_attempts=GREATEST(max_attempts,attempts+%s),
                    result=result || %s::jsonb,
                    lease_owner=NULL,lease_expires_at=NULL,updated_at=now()
                WHERE id=%s RETURNING *
            """, (retries, json.dumps(recovery), job_id))
            row = self._json_ready(self._row(cur, cur.fetchone())) or {}
        self.append_event(job_id, "infrastructure_rearmed", "Infrastructure retry window added", {
            "prior_error": fragment, "extra_attempts": retries,
            "spent_cost_usd": row.get("spent_cost_usd"),
            "max_cost_usd": row.get("max_cost_usd"),
        })
        return row

    def rearm_local_render_failure(self, job_id: str, *, expected_checkpoint_sha256: str,
                                  failure_kind: str = "memory") -> dict:
        """One continuation after a lost local encoder, with no ambiguous paid calls.

        FFmpeg has no remote billing or side effect to reconcile. Only its zero-cost
        unfinished rows can become retryable; all provider results stay untouched.
        A separate versioned marker bounds each diagnosed memory or disk repair.
        """
        if failure_kind not in {"memory", "disk"}:
            raise DurableExecutionError("Unknown local-render recovery kind")
        recovery_key = f"render_{failure_kind}_recovery_v1"
        if not re.fullmatch(r"[0-9a-f]{64}", expected_checkpoint_sha256):
            raise DurableExecutionError("Render recovery requires the saved checkpoint hash")
        with self._tx() as (_, cur):
            cur.execute("SELECT * FROM generation_jobs WHERE id=%s FOR UPDATE", (job_id,))
            job = self._json_ready(self._row(cur, cur.fetchone())) or {}
            error = str(job.get("error") or "")
            lost_render = (error == "Maximum worker attempts exhausted" or (
                error.startswith("Paid stage render:")
                and "unresolved prior provider attempt" in error))
            eligible_statuses = {"error"}
            if failure_kind == "disk":
                lost_render = "No space left on device" in error
                eligible_statuses.add("storage_error")
            if (job.get("status") not in eligible_statuses or not lost_render
                    or job.get("lease_owner") or job.get("lease_expires_at")
                    or (job.get("result") or {}).get(recovery_key)
                    or (job.get("checkpoint") or {}).get("sha256") != expected_checkpoint_sha256
                    or float(job.get("reserved_cost_usd") or 0) != 0
                    or float(job.get("spent_cost_usd") or 0) >= float(job.get("max_cost_usd") or 0)):
                raise DurableExecutionError("Job is not eligible for local-render recovery")
            cur.execute("""
                SELECT * FROM generation_stages WHERE job_id=%s
                AND status NOT IN ('completed','incomplete') FOR UPDATE
            """, (job_id,))
            stages = [self._json_ready(self._row(cur, raw)) or {} for raw in cur.fetchall()]
            if not stages or any(
                    stage.get("provider") != "ffmpeg"
                    or not re.fullmatch(r"render:[0-9a-f]{32}", str(stage.get("stage_key") or ""))
                    or stage.get("status") not in {"running", "retry"}
                    or float(stage.get("reserved_cost_usd") or 0) != 0
                    or float(stage.get("actual_cost_usd") or 0) != 0 for stage in stages):
                raise DurableExecutionError("Recovery requires only unfinished zero-cost local renders")
            keys = [stage["stage_key"] for stage in stages]
            cur.execute("""
                UPDATE generation_stages SET status='retry',updated_at=now()
                WHERE job_id=%s AND stage_key=ANY(%s)
            """, (job_id, keys))
            marker = {recovery_key: {"checkpoint_sha256": expected_checkpoint_sha256,
                                     "prior_error": error, "local_stages": keys}}
            cur.execute("""
                UPDATE generation_jobs SET status='queued',error=NULL,
                    max_attempts=GREATEST(max_attempts,attempts+1),
                    result=result || %s::jsonb,updated_at=now(),finished_at=NULL
                WHERE id=%s RETURNING *
            """, (json.dumps(marker), job_id))
            row = self._json_ready(self._row(cur, cur.fetchone())) or {}
        self.append_event(job_id, "infrastructure_rearmed", "Local render continuation ready", {
            "extra_attempts": 1, "checkpoint_sha256": expected_checkpoint_sha256})
        return row

    def rearm_retryable_provider_stage(
            self, job_id: str, *, error_prefix: str, recovery_key: str,
            expected_checkpoint_sha256: str, extra_attempts: int = 1) -> dict:
        """Resume one exact failed provider stage without clearing its reservation.

        This is deliberately narrower than an infrastructure rearm.  The job must reconcile to
        exactly one Anthropic retry stage, bounded by the existing single-call liability cap.
        Its stable request hash, idempotency key, reservation, approved payload and cost ceiling
        remain unchanged.
        """
        prefix = str(error_prefix or "").strip()
        if (not prefix or len(prefix) > 200
                or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", recovery_key)
                or not re.fullmatch(r"[0-9a-f]{64}", expected_checkpoint_sha256)):
            raise DurableExecutionError("Provider recovery requires an exact bounded identity")
        retries = max(1, min(int(extra_attempts), 1))
        with self._tx() as (_, cur):
            cur.execute("SELECT * FROM generation_jobs WHERE id=%s FOR UPDATE", (job_id,))
            current = self._json_ready(self._row(cur, cur.fetchone())) or {}
            reserved = float(current.get("reserved_cost_usd") or 0)
            if (not current or current.get("status") != "error"
                    or not str(current.get("error") or "").startswith(prefix)
                    or reserved <= 0
                    or float(current.get("spent_cost_usd") or 0)
                    >= float(current.get("max_cost_usd") or 0)
                    or (current.get("result") or {}).get(recovery_key)
                    or (current.get("checkpoint") or {}).get("sha256")
                    != expected_checkpoint_sha256):
                raise DurableExecutionError(f"Job {job_id} is not eligible for provider recovery")
            cur.execute("""
                SELECT stage_key,status,provider,reserved_cost_usd,error
                FROM generation_stages
                WHERE job_id=%s AND status IN ('running','retry') FOR UPDATE
            """, (job_id,))
            open_stages = [self._json_ready(self._row(cur, raw)) or {}
                           for raw in cur.fetchall()]
            stage = open_stages[0] if len(open_stages) == 1 else {}
            if (len(open_stages) != 1 or stage.get("status") != "retry"
                    or stage.get("provider") != "anthropic"
                    or not str(stage.get("stage_key") or "").startswith("anthropic:")
                    or not str(stage.get("error") or "").strip()
                    or abs(float(stage.get("reserved_cost_usd") or 0) - reserved) > 0.0001
                    or reserved > float(current.get("max_inflight_call_usd") or 0)):
                raise DurableExecutionError(
                    f"Job {job_id} has an ambiguous provider reservation; recovery stopped")
            marker = {recovery_key: {
                "checkpoint_sha256": expected_checkpoint_sha256,
                "stage_key": stage["stage_key"],
                "preserved_reserved_cost_usd": reserved,
            }}
            cur.execute("""
                UPDATE generation_jobs SET status='queued',error=NULL,
                    max_attempts=GREATEST(max_attempts,attempts+%s),
                    result=result || %s::jsonb,
                    lease_owner=NULL,lease_expires_at=NULL,updated_at=now()
                WHERE id=%s RETURNING *
            """, (retries, json.dumps(marker), job_id))
            row = self._json_ready(self._row(cur, cur.fetchone())) or {}
        self.append_event(job_id, "provider_stage_rearmed",
                          "Retrying one idempotent provider judgment", {
                              "extra_attempts": retries,
                              "preserved_reserved_cost_usd": reserved,
                              "stage_key": stage["stage_key"],
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

    def rearm_next_nature_motion_disk_failure(self) -> dict | None:
        """Resume one Nature v2 pilot after /tmp filled during an idempotent motion stage."""
        self.ensure_schema()
        with self._tx() as (_, cur):
            cur.execute("""
                SELECT j.* FROM generation_jobs j
                WHERE j.status='storage_error'
                  AND j.error ILIKE '%No space left on device%'
                  AND (j.lease_expires_at IS NULL OR j.lease_expires_at < now())
                  AND j.reserved_cost_usd > 0
                  AND j.spent_cost_usd < j.max_cost_usd
                  AND j.checkpoint <> '{}'::jsonb
                  AND EXISTS (
                      SELECT 1 FROM agent_actions a
                      WHERE a.job_id=j.id AND a.operation='directed_pilot'
                        AND a.status='queued' AND a.approved_at IS NOT NULL
                        AND a.payload #>> '{nature_short,version}' = 'nature_short_v2'
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM generation_events e
                      WHERE e.job_id=j.id AND e.event_type='infrastructure_rearmed'
                        AND e.details #>> '{recovery_key}' = 'nature_motion_disk_v1'
                  )
                ORDER BY j.updated_at ASC
                FOR UPDATE SKIP LOCKED LIMIT 1
            """)
            current = self._json_ready(self._row(cur, cur.fetchone()))
            if not current:
                return None
            cur.execute("""
                SELECT stage_key,status,provider,reserved_cost_usd
                FROM generation_stages
                WHERE job_id=%s AND status IN ('running','retry') FOR UPDATE
            """, (current["id"],))
            open_stages = [self._json_ready(self._row(cur, raw)) or {}
                           for raw in cur.fetchall()]
            stage = open_stages[0] if len(open_stages) == 1 else {}
            reserved = float(current.get("reserved_cost_usd") or 0)
            if (len(open_stages) != 1
                    or stage.get("status") not in {"running", "retry"}
                    or not str(stage.get("stage_key") or "").startswith("motion:")
                    or abs(float(stage.get("reserved_cost_usd") or 0) - reserved) > 0.0001
                    or reserved > float(current.get("max_inflight_call_usd") or 0)):
                raise DurableExecutionError(
                    f"Job {current['id']} has an ambiguous motion reservation; recovery stopped")
            cur.execute("""
                UPDATE generation_jobs SET status='queued',error=NULL,
                    max_attempts=GREATEST(max_attempts,attempts+2),
                    lease_owner=NULL,lease_expires_at=NULL,updated_at=now()
                WHERE id=%s RETURNING *
            """, (current["id"],))
            row = self._json_ready(self._row(cur, cur.fetchone())) or {}
            cur.execute("""
                INSERT INTO generation_events(job_id,event_type,data,details)
                VALUES (%s,'infrastructure_rearmed',
                        'Nature motion resumed after bounded local-disk cleanup',%s::jsonb)
            """, (row["id"], json.dumps({
                "prior_error": current.get("error"),
                "recovery_key": "nature_motion_disk_v1",
                "preserved_stage_key": stage.get("stage_key"),
                "preserved_reserved_cost_usd": reserved,
                "spent_cost_usd": row.get("spent_cost_usd"),
                "max_cost_usd": row.get("max_cost_usd"),
            })))
            return row

    def rearm_next_directed_parent_blob_failure(self) -> dict | None:
        """Rearm one checkpointed full film after its accepted-pilot pointer returns 404."""
        self.ensure_schema()
        with self._tx() as (_, cur):
            cur.execute("""
                SELECT j.* FROM generation_jobs j
                WHERE j.status='error'
                  AND j.error ILIKE '%Blob download failed%404 Client Error%Not Found%'
                  AND j.request->>'directed_full_film'='true'
                  AND j.reserved_cost_usd=0
                  AND j.spent_cost_usd < j.max_cost_usd
                  AND j.checkpoint <> '{}'::jsonb
                  AND EXISTS (
                      SELECT 1 FROM agent_actions a
                      WHERE a.job_id=j.id AND a.operation='directed_full_film'
                        AND a.status='queued'
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM generation_events e
                      WHERE e.job_id=j.id
                        AND e.event_type='directed_parent_blob_auto_rearmed'
                  )
                ORDER BY j.updated_at ASC
                FOR UPDATE SKIP LOCKED LIMIT 1
            """)
            current = self._json_ready(self._row(cur, cur.fetchone()))
            if not current:
                return None
            cur.execute("""
                UPDATE generation_jobs SET status='queued',error=NULL,
                    max_attempts=GREATEST(max_attempts,attempts+12),
                    lease_owner=NULL,lease_expires_at=NULL,updated_at=now()
                WHERE id=%s RETURNING *
            """, (current["id"],))
            row = self._json_ready(self._row(cur, cur.fetchone())) or {}
            cur.execute("""
                INSERT INTO generation_events(job_id,event_type,data,details)
                VALUES (%s,'directed_parent_blob_auto_rearmed',
                        'Directed film rearmed for exact-hash parent snapshot recovery',
                        %s::jsonb)
            """, (row["id"], json.dumps({
                "prior_error": current.get("error"),
                "spent_cost_usd": row.get("spent_cost_usd"),
                "max_cost_usd": row.get("max_cost_usd"),
            })))
            return row

    def rearm_next_directed_parent_archive_failure(self) -> dict | None:
        """Rearm one approved film for exact-hash recovery from parent checkpoints."""
        self.ensure_schema()
        with self._tx() as (_, cur):
            cur.execute("""
                SELECT j.* FROM generation_jobs j
                WHERE j.status='error'
                  AND j.error ILIKE '%Accepted pilot%missing%'
                  AND j.request->>'directed_full_film'='true'
                  AND j.reserved_cost_usd=0
                  AND j.spent_cost_usd < j.max_cost_usd
                  AND j.checkpoint <> '{}'::jsonb
                  AND EXISTS (
                      SELECT 1 FROM agent_actions a
                      WHERE a.job_id=j.id AND a.operation='directed_full_film'
                        AND a.status='queued'
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM generation_events e
                      WHERE e.job_id=j.id
                        AND e.event_type='directed_parent_archive_auto_rearmed'
                  )
                ORDER BY j.updated_at ASC
                FOR UPDATE SKIP LOCKED LIMIT 1
            """)
            current = self._json_ready(self._row(cur, cur.fetchone()))
            if not current:
                return None
            cur.execute("""
                UPDATE generation_jobs SET status='queued',error=NULL,
                    max_attempts=GREATEST(max_attempts,attempts+12),
                    lease_owner=NULL,lease_expires_at=NULL,updated_at=now()
                WHERE id=%s RETURNING *
            """, (current["id"],))
            row = self._json_ready(self._row(cur, cur.fetchone())) or {}
            cur.execute("""
                INSERT INTO generation_events(job_id,event_type,data,details)
                VALUES (%s,'directed_parent_archive_auto_rearmed',
                        'Directed film rearmed for exact-hash checkpoint archive recovery',
                        %s::jsonb)
            """, (row["id"], json.dumps({
                "prior_error": current.get("error"),
                "spent_cost_usd": row.get("spent_cost_usd"),
                "max_cost_usd": row.get("max_cost_usd"),
            })))
            return row

    def rearm_next_directed_remainder_salvage(self) -> dict | None:
        """Rearm one full-film job to persist its paid remainder when the opening is gone."""
        self.ensure_schema()
        with self._tx() as (_, cur):
            cur.execute("""
                SELECT j.* FROM generation_jobs j
                WHERE j.status='error'
                  AND j.error ILIKE '%Accepted pilot bytes are absent%'
                  AND j.request->>'directed_full_film'='true'
                  AND j.reserved_cost_usd=0
                  AND j.spent_cost_usd < j.max_cost_usd
                  AND j.checkpoint <> '{}'::jsonb
                  AND EXISTS (
                      SELECT 1 FROM agent_actions a
                      WHERE a.job_id=j.id AND a.operation='directed_full_film'
                        AND a.status='queued'
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM generation_events e
                      WHERE e.job_id=j.id
                        AND e.event_type='directed_remainder_salvage_auto_rearmed'
                  )
                ORDER BY j.updated_at ASC
                FOR UPDATE SKIP LOCKED LIMIT 1
            """)
            current = self._json_ready(self._row(cur, cur.fetchone()))
            if not current:
                return None
            cur.execute("""
                UPDATE generation_jobs SET status='queued',error=NULL,
                    max_attempts=GREATEST(max_attempts,attempts+12),
                    lease_owner=NULL,lease_expires_at=NULL,updated_at=now()
                WHERE id=%s RETURNING *
            """, (current["id"],))
            row = self._json_ready(self._row(cur, cur.fetchone())) or {}
            cur.execute("""
                INSERT INTO generation_events(job_id,event_type,data,details)
                VALUES (%s,'directed_remainder_salvage_auto_rearmed',
                        'Directed film rearmed to persist authorized remainder without lost opening',
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
        nature_disk_salvage = self.rearm_next_nature_motion_disk_failure()
        if nature_disk_salvage:
            return nature_disk_salvage
        nature_shot_salvage = self.rearm_next_nature_shot_timing_failure()
        if nature_shot_salvage:
            return nature_shot_salvage
        self.ensure_schema()
        with self._tx() as (_, cur):
            cur.execute("""
                SELECT j.*, (
                    EXISTS (
                        SELECT 1 FROM agent_actions a
                        WHERE a.job_id=j.id AND a.operation='directed_pilot'
                          AND a.payload #>> '{nature_short,version}' = 'nature_short_v2'
                    ) AND EXISTS (
                        SELECT 1 FROM generation_events e
                        WHERE e.job_id=j.id AND e.event_type='directed_audio_fit_rearmed'
                    )
                ) AS _nature_runtime_migration
                FROM generation_jobs j
                WHERE j.status='error'
                  AND j.error ILIKE '%measured pilot narration %visual spending stopped%'
                  AND j.reserved_cost_usd=0
                  AND j.spent_cost_usd < j.max_cost_usd
                  AND j.checkpoint <> '{}'::jsonb
                  AND EXISTS (
                      SELECT 1 FROM agent_actions a
                      WHERE a.job_id=j.id AND a.operation='directed_pilot'
                  )
                  AND (
                      NOT EXISTS (
                          SELECT 1 FROM generation_events e
                          WHERE e.job_id=j.id AND e.event_type='directed_audio_fit_rearmed'
                      ) OR (
                          EXISTS (
                              SELECT 1 FROM agent_actions a
                              WHERE a.job_id=j.id AND a.operation='directed_pilot'
                                AND a.payload #>> '{nature_short,version}' = 'nature_short_v2'
                          )
                          AND EXISTS (
                              SELECT 1 FROM generation_events e
                              WHERE e.job_id=j.id
                                AND e.event_type='directed_audio_fit_rearmed'
                          )
                          AND NOT EXISTS (
                              SELECT 1 FROM generation_events e
                              WHERE e.job_id=j.id AND e.event_type='infrastructure_rearmed'
                                AND e.details #>> '{recovery_key}' =
                                    'nature_measured_runtime_v1'
                          )
                      )
                  )
                ORDER BY j.updated_at ASC
                FOR UPDATE SKIP LOCKED LIMIT 1
            """)
            current = self._json_ready(self._row(cur, cur.fetchone()))
            if not current:
                return None
            nature_migration = bool(current.pop("_nature_runtime_migration", False))
            cur.execute("""
                UPDATE generation_jobs SET status='queued',error=NULL,
                    max_attempts=GREATEST(max_attempts,attempts+2),
                    lease_owner=NULL,lease_expires_at=NULL,updated_at=now()
                WHERE id=%s RETURNING *
            """, (current["id"],))
            row = self._json_ready(self._row(cur, cur.fetchone())) or {}
            recovery_key = "nature_measured_runtime_v1" if nature_migration else ""
            event_type = "infrastructure_rearmed" if nature_migration else "directed_audio_fit_rearmed"
            event_data = (
                "Nature pilot rearmed after measured-runtime gate removal" if nature_migration
                else "Approved directed pilot rearmed for bounded audio runtime fit")
            cur.execute("""
                INSERT INTO generation_events(job_id,event_type,data,details)
                VALUES (%s,%s,%s,%s::jsonb)
            """, (row["id"], event_type, event_data, json.dumps({
                "prior_error": current.get("error"),
                "spent_cost_usd": row.get("spent_cost_usd"),
                "max_cost_usd": row.get("max_cost_usd"),
                "recovery_key": recovery_key,
            })))
            return row

    def rearm_next_nature_shot_timing_failure(self) -> dict | None:
        """Continue a Nature v2 pilot once after removal of the measured-shot gate.

        Restrict recovery to its exact pre-visual error with an approved queued action,
        saved checkpoint, no live lease or reservation, and remaining budget.
        """
        self.ensure_schema()
        with self._tx() as (_, cur):
            cur.execute("""
                SELECT j.* FROM generation_jobs j
                WHERE j.status='error'
                  AND j.error ~ '^Nature shot [^ ]+ measures [0-9]+[.][0-9]+s; repartition this beat into [0-9.]+-[0-9.]+s shots before visuals$'
                  AND (j.lease_expires_at IS NULL OR j.lease_expires_at < now())
                  AND j.reserved_cost_usd=0
                  AND j.spent_cost_usd < j.max_cost_usd
                  AND j.checkpoint <> '{}'::jsonb
                  AND EXISTS (
                      SELECT 1 FROM agent_actions a
                      WHERE a.job_id=j.id AND a.operation='directed_pilot'
                        AND a.status='queued' AND a.approved_at IS NOT NULL
                        AND a.payload #>> '{nature_short,version}' = 'nature_short_v2'
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM generation_events e
                      WHERE e.job_id=j.id AND e.event_type='infrastructure_rearmed'
                        AND e.details #>> '{recovery_key}' = 'nature_measured_holds_v1'
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
                VALUES (%s,'infrastructure_rearmed',
                        'Nature pilot rearmed after measured-shot gate removal',%s::jsonb)
            """, (row["id"], json.dumps({
                "prior_error": current.get("error"),
                "spent_cost_usd": row.get("spent_cost_usd"),
                "max_cost_usd": row.get("max_cost_usd"),
                "recovery_key": "nature_measured_holds_v1",
            })))
            return row

    def rearm_next_portrait_audio_boundary_failure(self) -> dict | None:
        """Resume one approved portrait pilot after a sub-0.1s narration shortfall.

        This second recovery is only for a job that already consumed the normal
        audio-fit retry. It preserves the spec, completed TTS, and cost ceiling.
        """
        self.ensure_schema()
        with self._tx() as (_, cur):
            cur.execute("""
                SELECT j.* FROM generation_jobs j
                JOIN agent_actions a ON a.job_id=j.id
                WHERE j.status='error' AND a.operation='directed_pilot'
                  AND a.payload #>> '{target,format}' = 'portrait'
                  AND j.error ~ '^measured pilot narration [0-9]+[.][0-9]+s is outside '
                  AND j.reserved_cost_usd=0
                  AND j.spent_cost_usd < j.max_cost_usd
                  AND j.checkpoint <> '{}'::jsonb
                  AND ((a.payload #>> '{acceptance,pilot_runtime_min_sec}')::numeric
                       - substring(j.error from
                           '^measured pilot narration ([0-9]+[.][0-9]+)s')::numeric)
                      BETWEEN 0 AND 0.10
                  AND EXISTS (SELECT 1 FROM generation_events e WHERE e.job_id=j.id
                              AND e.event_type='directed_audio_fit_rearmed')
                  AND NOT EXISTS (SELECT 1 FROM generation_events e WHERE e.job_id=j.id
                                  AND e.event_type='portrait_audio_boundary_rearmed')
                ORDER BY j.updated_at ASC
                FOR UPDATE OF j SKIP LOCKED LIMIT 1
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
                VALUES (%s,'portrait_audio_boundary_rearmed',
                        'Approved portrait pilot rearmed after a frame-boundary audio miss',
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
