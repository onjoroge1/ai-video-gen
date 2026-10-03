"""One final decision over the exact words shown in Studio, independent of render estimates."""
import script_stages
import storyboard_repair

VERSION = "script_readiness_v1"


def evaluate(script, dossier, *, claims, structure, storyboard, runtime,
             duplicates, review, runtime_hard=False, factcheck_required=False):
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
        gates["factcheck"] = (script.get("_factcheck_review") or {}).get("status") == "complete"
    warnings = []
    if runtime_hard:
        gates["runtime"] = bool(runtime and runtime.get("passed"))
    elif runtime and not runtime.get("passed"):
        warnings.append("Requested runtime is advisory and was not met")
    errors = [name for name, passed in gates.items() if not passed]
    return {"version": VERSION, "passed": not errors, "errors": errors,
            "warnings": warnings, "gates": gates, "narration_sha256": narration_hash,
            "script_sha256": script_stages.digest({k: v for k, v in script.items()
                                                   if k != "_script_readiness"}),
            "evidence_sha256": script_stages.digest(dossier),
            "policy": {"runtime_hard": runtime_hard, "factcheck_required": factcheck_required, "required": list(gates)}}
