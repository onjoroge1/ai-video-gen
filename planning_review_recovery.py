"""Explicit migration of an exhausted legacy review, never a content-gate bypass."""
import json
import re
import tempfile
from pathlib import Path

import script_stages

MARKER = "planning_review_v3_migration"
LEGACY_ERROR = "UNSCORED_JUDGE_UNAVAILABLE: planning claim support [INCOMPLETE_COVERAGE]"


def eligible(job):
    return bool(job.get("kind") == "explainer" and job.get("status") == "error"
        and job.get("error") == LEGACY_ERROR
        and not (job.get("request") or {}).get("controlled_pilot")
        and not (job.get("result") or {}).get(MARKER)
        and not job.get("lease_owner") and not job.get("lease_expires_at")
        and float(job.get("reserved_cost_usd") or 0) == 0
        and float(job.get("spent_cost_usd") or 0) < float(job.get("max_cost_usd") or 0)
        and re.fullmatch(r"[0-9a-f]{64}", str((job.get("checkpoint") or {}).get("sha256") or "")))


def inspect_checkpoint(job, store, blob):
    """Validate the retained research and absence of downstream work without spending."""
    from durable_execution import DurableRuntime, DurableExecutionError
    import explainer_pipeline as ep
    with tempfile.TemporaryDirectory(prefix="planning-review-read-") as directory:
        runtime = DurableRuntime(job_id=job["id"], worker_id="read-only",
                                 output_dir=directory, store=store, blob=blob)
        runtime.restore_checkpoint(job["checkpoint"])
        root = Path(directory)
        if (root.joinpath("planning_review.json").exists() or root.joinpath("_state.json").exists()
                or list(root.glob("script_stages/accepted-plan/*.json"))):
            raise DurableExecutionError("Review migration cannot reset existing v3 or downstream work")
        records = list(root.glob("script_stages/research/*.json"))
        if len(records) != 1:
            raise DurableExecutionError("Expected one exact saved research stage")
        record = json.loads(records[0].read_text())
        if (record.get("stage") != "research" or record.get("input_hash") != records[0].stem
                or record.get("output_hash") != script_stages.digest(record.get("output"))):
            raise DurableExecutionError("Saved research integrity check failed")
        request = job.get("request") or {}
        inputs = {"arguments": {"question": request.get("question"), "evidence_gaps": None,
                                 "duration_sec": request.get("duration_sec", 90)},
                  "context": {"channel": request.get("topic_channel", ""), "model": ep.ANTHROPIC_MODEL}}
        expected = script_stages.digest({"version": script_stages.VERSION, "stage": "research", "inputs": inputs})
        if record["input_hash"] != expected:
            raise DurableExecutionError("Saved research cannot replay under this recipe/model")
        claims = record["output"]["result"].get("claims") or []
        ids = [c["claim_id"] for c in claims]
        if not ids or len(ids) != len(set(ids)):
            raise DurableExecutionError("Saved research has invalid claim identities")
        return {"research_hash": record["output_hash"], "claim_ids": ids}
