"""One final decision over the exact words shown in Studio, independent of render estimates."""
import script_stages
import storyboard_repair

VERSION = "script_readiness_v2"


def content_hash(script):
    """Approved words and their factual meaning; excludes mutable render/cache bookkeeping."""
    return script_stages.digest({
        "title": script.get("title"), "hook": script.get("hook"),
        "engine": script.get("_story_engine"), "contract": script.get("_story_contract"),
        "cold_open": script.get("_cold_open"), "cold_open_claim_refs": script.get("_cold_open_claim_refs"),
        "narrative_mode": script.get("_narrative_mode"),
        "narrative_document": script.get("_narrative_document"),
        "production_status": script.get("_production_status"),
        "scenes": [{k: scene.get(k) for k in ("scene_id", "narration", "event", "causal_role",
                    "caused_by", "derivation", "scope", "chapter", "continues", "_story_compiler_version",
                    "beat_id", "context_refs", "parallel_case_id", "paragraph_id", "narrative_section", "narration_span")}
                   for scene in script.get("scenes") or []]})


def evaluate(script, dossier, *, claims, structure, storyboard, runtime,
             duplicates, review, runtime_hard=False, factcheck_required=False, factual_review=None):
    narration_hash = storyboard_repair.story_identity(script)
    gates = {
        "claims": bool(claims and claims.get("passed")),
        "structure": bool(structure and structure.get("passed")),
        "storyboard": bool(storyboard and storyboard.get("passed")),
        "duplicates": not duplicates,
        "editorial": bool(review and review.get("passed")
                          and review.get("narration_sha256") == narration_hash),
    }
    if factcheck_required:
        factual_review = factual_review or {}
        gates["factcheck"] = bool(factual_review.get("passed")
            and factual_review.get("content_sha256") == content_hash(script)
            and factual_review.get("evidence_sha256") == script_stages.digest(dossier))
    warnings = []
    if runtime_hard:
        gates["runtime"] = bool(runtime and runtime.get("passed"))
    elif runtime and not runtime.get("passed"):
        warnings.append("Requested runtime is advisory and was not met")
    errors = [name for name, passed in gates.items() if not passed]
    return {"version": VERSION, "passed": not errors, "errors": errors,
            "warnings": warnings, "gates": gates, "narration_sha256": narration_hash,
            "content_sha256": content_hash(script),
            "script_sha256": script_stages.digest({k: v for k, v in script.items()
                                                   if k != "_script_readiness"}),
            "evidence_sha256": script_stages.digest(dossier),
            "policy": {"runtime_hard": runtime_hard, "factcheck_required": factcheck_required, "required": list(gates)}}
