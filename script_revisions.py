"""Immutable Studio child jobs: evaluate saved prose or render accepted prose."""
from copy import deepcopy

import script_contracts
import script_finalizer
import script_readiness
from script_stages import digest

VERSION = "script_revision_v1"


def eligible(row):
    request = row.get("request") or {}
    return (row.get("kind") == "explainer" and row.get("status") in {"error", "awaiting_script_approval"}
            and request.get("visual_style") == "illustrated_story"
            and request.get("video_format", "landscape") == "landscape"
            and not any(request.get(k) for k in ("controlled_pilot", "controlled_production",
                "directed_spec", "illustrated_authorization", "pilot_batch_id", "production_batch_id")))


def prepare(row, saved, *, mode, checkpoint_sha256, content_sha256, cost_ceiling_usd):
    if not eligible(row):
        raise ValueError("This job must use its original approval or recovery workflow")
    if mode not in {"evaluate", "render"}:
        raise ValueError("Unknown script revision mode")
    if not checkpoint_sha256 or checkpoint_sha256 != (row.get("checkpoint") or {}).get("sha256") \
            or checkpoint_sha256 != saved.get("checkpoint_sha256"):
        raise ValueError("Saved checkpoint changed; refresh the script")
    script = deepcopy(saved.get("script"))
    if not script or not script.get("scenes") or content_sha256 != script_readiness.content_hash(script):
        raise ValueError("Saved script changed or is unavailable; refresh the script")
    dossier = script.get("_research_dossier") or {}
    if not dossier.get("claims"):
        raise ValueError("The saved script has no evidence ledger")
    request = deepcopy(row["request"])
    request.pop("script_revision", None)
    if mode == "render":
        if row.get("status") != "awaiting_script_approval":
            raise ValueError("Evaluate the saved draft before approving it for rendering")
        script_finalizer.verify_approved(script, dossier, request["question"], request["duration_sec"],
                                        factcheck_required=request.get("fact_check", True))
    revision = {"version": VERSION, "mode": mode, "parent_job_id": row["id"],
                "parent_checkpoint_sha256": checkpoint_sha256, "script": script,
                "source_sha256": digest(script), "content_sha256": content_sha256,
                "policy": script_contracts.acceptance_policy(), "cost_ceiling_usd": cost_ceiling_usd}
    request.update(stop_after_script=mode == "evaluate", revision_note="", script_revision=revision)
    # Same saved draft, settings, policy, operation and cap can buy only one child job.
    return "sr-" + digest(request)[:28], request


def restore(revision, *, stop_after_script):
    if (revision.get("version") != VERSION or revision.get("mode") not in {"evaluate", "render"}
            or revision.get("policy") != script_contracts.acceptance_policy()
            or (revision["mode"] == "evaluate") != stop_after_script):
        raise ValueError("Saved script revision policy or operation changed")
    script = deepcopy(revision.get("script"))
    if not script or digest(script) != revision.get("source_sha256") \
            or script_readiness.content_hash(script) != revision.get("content_sha256"):
        raise ValueError("Saved script revision content changed")
    # Parent usage remains on the parent job; a child reports its own work only.
    script["_script_cost_usd"] = 0.0
    if revision["mode"] == "evaluate":
        for key in ("_script_readiness", "_final_factcheck_review", "_final_retention_review"):
            script.pop(key, None)
    return script
