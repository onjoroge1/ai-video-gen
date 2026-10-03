"""The last text boundary shared by Studio, the production render and the CLI."""
from copy import deepcopy

import script_contracts
import script_readiness
from script_stages import digest


def evaluate(script, dossier, question, duration, *, factcheck_required, cost_sink=None):
    import explainer_pipeline as ep
    import illustrated_story
    claims = ep._validate_claims(script, dossier, cost_sink)
    factual_review = {"passed": bool(claims.get("passed")) and not claims.get("retryable"),
                      "content_sha256": script_readiness.content_hash(script),
                      "evidence_sha256": digest(dossier), "report": claims}
    # Keep the original fact-check attempt as history. It cannot veto a later,
    # complete review or certify different words after a repair.
    script["_final_factcheck_review"] = factual_review
    script["_claim_validation"] = claims
    report = script_readiness.evaluate(script, dossier, claims=claims,
        structure=ep.validate_longform_story(script, question),
        storyboard=illustrated_story.build_storyboard(deepcopy(script), question)["validation"],
        runtime=ep.plan_runtime(script.get("scenes") or [], duration),
        duplicates=ep.duplicate_narration(script.get("scenes") or []),
        review=script.get("_final_retention_review"), runtime_hard=ep._runtime_is_enforced(),
        factcheck_required=factcheck_required, factual_review=factual_review)
    report["acceptance_policy"] = script_contracts.acceptance_policy()
    from story_fact_model import event_of
    cited = set(script.get("_cold_open_claim_refs") or [])
    for scene in script.get("scenes") or []:
        cited.update(event_of(scene)["claim_refs"])
        cited.update(r.get("claim_id") for r in scene.get("claim_refs") or [] if isinstance(r, dict))
    claims_used = [c for c in dossier.get("claims") or [] if c.get("claim_id") in cited]
    report["evidence_provenance"] = {
        "cited_claims": len(claims_used),
        "page_verified_quotes": sum(c.get("quote_verified") is True for c in claims_used),
        "other_quote_provenance": sum(c.get("quote_verified") is not True for c in claims_used),
        "meaning": "Semantic acceptance does not establish independent page retrieval or currentness"}
    report["question"] = question
    report["duration_sec"] = duration
    script["_script_readiness"] = report
    return report


def verify_approved(script, dossier, question, duration, *, factcheck_required):
    """Restore a decision only for identical words, evidence and policy. No paid work."""
    report = script.get("_script_readiness") or {}
    if not (report.get("version") == script_readiness.VERSION and report.get("passed")
            and report.get("content_sha256") == script_readiness.content_hash(script)
            and report.get("evidence_sha256") == digest(dossier)
            and report.get("acceptance_policy") == script_contracts.acceptance_policy()
            and report.get("question") == question and report.get("duration_sec") == duration
            and (report.get("policy") or {}).get("factcheck_required") == factcheck_required):
        raise ValueError("APPROVED_SCRIPT_CHANGED: evaluate this saved draft under the current policy first")
    return deepcopy(report)
