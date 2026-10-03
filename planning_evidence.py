"""Check claim paraphrases against their attached passages before planning prose."""
from copy import deepcopy
import json

import script_stages


def _verdicts(response, ids):
    """Normalize live and durable tool inputs before checking complete coverage."""
    def reject(code):
        # Keep diagnostics useful without exposing provider text in Studio errors.
        raise ValueError("UNSCORED_JUDGE_UNAVAILABLE: planning claim support [" + code + "]")

    if getattr(response, "stop_reason", None) in {"max_tokens", "pause_turn"}:
        reject("INCOMPLETE_RESPONSE")
    blocks = [b for b in response.content if getattr(b, "type", "") == "tool_use"]
    if len(blocks) != 1 or getattr(blocks[0], "name", "") != "submit_claim_support":
        reject("UNEXPECTED_TOOL")
    value = blocks[0].input
    # Durable execution wraps nested dictionaries on fresh calls as well as replay.
    # Its model_dump() returns the original nested JSON, like the SDK models.
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if not isinstance(value, dict) or not isinstance(value.get("claims"), list):
        reject("INVALID_PAYLOAD")
    rows = value["claims"]
    if any(not isinstance(r, dict)
           or not isinstance(r.get("claim_id"), str)
           or r.get("verdict") not in ("supported", "unsupported")
           or not isinstance(r.get("reason"), str) or not r["reason"].strip()
           for r in rows):
        reject("INVALID_VERDICT")
    by_id = {r["claim_id"]: r for r in rows}
    if len(rows) != len(ids) or len(by_id) != len(rows) or set(by_id) != set(ids):
        reject("INCOMPLETE_COVERAGE")
    return rows, by_id


@script_stages.cached("planning-evidence", context=lambda: {"contract": 2})
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
    rows, by_id = _verdicts(response, ids)
    result = deepcopy(dossier)
    result["claim_support_review"] = rows
    result["planning_excluded_claims"] = [c for c in result["claims"]
                                          if by_id[c["claim_id"]]["verdict"] != "supported"]
    result["claims"] = [dict(c, planning_support="supported") for c in result["claims"]
                        if by_id[c["claim_id"]]["verdict"] == "supported" and c.get("support_quote")]
    if not result["claims"]:
        raise ValueError("No source-supported claims remain for planning")
    return result
