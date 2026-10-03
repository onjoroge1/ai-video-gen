"""Check claim paraphrases against their attached passages before planning prose."""
from copy import deepcopy
import json

import script_stages


@script_stages.cached("planning-evidence", context=lambda: {"contract": 1})
def prepare(dossier, *, cost_sink=None):
    import explainer_pipeline as ep
    claims = dossier.get("claims") or []
    ids = [c["claim_id"] for c in claims]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Planning evidence requires unique claim IDs")
    response = ep._claude().messages.create(
        model=ep.ANTHROPIC_MODEL, max_tokens=6000,
        system="Check each factual claim against ONLY its attached exact source passage. "
            "A quote being on a page does not prove its paraphrase. Intended outcomes are not "
            "observed outcomes; association is not causation. Supported means every factual "
            "detail is entailed. Do not use background knowledge. Submit one verdict for every claim.",
        tools=[{"name": "submit_claim_support", "description": "Claim-to-passage decisions",
                "input_schema": {"type": "object", "properties": {"claims": {
                    "type": "array", "minItems": len(ids), "maxItems": len(ids),
                    "items": {"type": "object", "properties": {
                        "claim_id": {"type": "string", "enum": ids},
                        "verdict": {"type": "string", "enum": ["supported", "unsupported"]},
                        "reason": {"type": "string"}},
                        "required": ["claim_id", "verdict", "reason"], "additionalProperties": False}}},
                    "required": ["claims"], "additionalProperties": False}}],
        tool_choice={"type": "tool", "name": "submit_claim_support"},
        messages=[{"role": "user", "content": json.dumps([
            {k: c.get(k) for k in ("claim_id", "claim", "support_quote", "source_url",
                                   "quote_verified", "source_reachable", "support_provenance")}
            for c in claims], ensure_ascii=False)}])
    if cost_sink is not None:
        cost_sink.append(ep._msg_cost(response.usage))
    blocks = [b for b in response.content if getattr(b, "type", "") == "tool_use"
              and getattr(b, "name", "") == "submit_claim_support"]
    try:
        rows = blocks[0].input["claims"] if len(blocks) == 1 else []
        by_id = {r["claim_id"]: r for r in rows}
        if (len(rows) != len(ids) or set(by_id) != set(ids)
                or any(r["verdict"] not in {"supported", "unsupported"} for r in rows)):
            raise ValueError("Incomplete claim-support verdicts")
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ValueError("UNSCORED_JUDGE_UNAVAILABLE: planning claim support") from exc
    result = deepcopy(dossier)
    result["claim_support_review"] = rows
    result["planning_excluded_claims"] = [c for c in result["claims"]
                                          if by_id[c["claim_id"]]["verdict"] != "supported"]
    result["claims"] = [dict(c, planning_support="supported") for c in result["claims"]
                        if by_id[c["claim_id"]]["verdict"] == "supported" and c.get("support_quote")]
    if not result["claims"]:
        raise ValueError("No source-supported claims remain for planning")
    return result
