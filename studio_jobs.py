"""Read-only, checkpoint-bound Studio diagnostics. Never dispatches provider work."""
import json
from pathlib import Path
import tempfile

from fastapi import HTTPException
import durable_execution

ACTIVE = {"queued", "processing", "rendering", "running", "retry"}
REPORTS = {
    "claim_failure": "semantic_failure_claim-ledger.json",
    "runtime_claim_failure": "semantic_failure_runtime-claim-ledger.json",
    "readiness": "retention_readiness.json",
    "claims": "claim_ledger_report.json",
    "storyboard": "illustrated_storyboard.json",
    "storyboard_failure": "semantic_failure_illustrated-storyboard.json",
    "planning_review": "planning_review.json",
    "manifest": "generation_manifest.json",
    "polish": "retention_polish_v1.json",
}


def snapshot(row, events):
    import provider_blocks
    import planning_review_recovery
    resumable = (row.get("kind") == "explainer"
                 and not (row.get("request") or {}).get("controlled_pilot")
                 and bool(provider_blocks.for_job(row))
                 and bool((row.get("checkpoint") or {}).get("sha256")))
    return {"id": row["id"], "status": row.get("status"),
            "provider_resumable": resumable,
            "planning_review_resumable": planning_review_recovery.eligible(row),
            "active": row.get("status") in ACTIVE, "error": row.get("error"),
            "question": (row.get("request") or {}).get("question", ""),
            "spent_cost_usd": row.get("spent_cost_usd"),
            "max_cost_usd": row.get("max_cost_usd"),
            "checkpoint_sha256": (row.get("checkpoint") or {}).get("sha256"),
            "events": [{"seq": e["seq"], "type": e["event_type"], "data": e["data"]}
                       for e in events]}


def artifacts(job_id, store, blob):
    row = store.get_job(job_id)
    if not row:
        raise HTTPException(404, "Job not found")
    checkpoint = row.get("checkpoint") or {}
    result = {"checkpoint_sha256": checkpoint.get("sha256"), "script": None,
              "reports": {}, "unavailable": []}
    if not checkpoint:
        return result
    # Always restore the requested snapshot, never an earlier process-local job cache.
    with tempfile.TemporaryDirectory(prefix="studio-read-") as directory:
        runtime = durable_execution.DurableRuntime(
            job_id=job_id, worker_id="read-only", output_dir=directory, store=store, blob=blob)
        runtime.restore_checkpoint(checkpoint)
        for key, filename in {"script": "_state.json", **REPORTS}.items():
            path = Path(directory) / filename
            if not path.exists():
                continue
            try:
                value = json.loads(path.read_text())
                if key == "script":
                    result["script"] = value.get("script")
                else:
                    result["reports"][key] = value
            except (OSError, ValueError, AttributeError):
                result["unavailable"].append(key)
        # Pre-spend refusals happen before _state.json is written. Keep their exact
        # narration available without labeling it approved or selecting an arbitrary file.
        failures = [v for k, v in result["reports"].items()
                    if k in {"claim_failure", "runtime_claim_failure", "storyboard_failure"}
                    and isinstance(v, dict) and isinstance(v.get("script"), dict)
                    and v["script"].get("scenes")]
        if row.get("status") == "error" and failures:
            failed = max(failures, key=lambda v: str(v.get("failed_at") or ""))
            result["script"] = failed["script"]
            result["script_source"] = "failed diagnostic: " + str(failed.get("stage") or "unknown")
        elif result["script"]:
            result["script_source"] = "saved state"
    return result
