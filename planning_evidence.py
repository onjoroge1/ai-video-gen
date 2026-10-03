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


VERSION = "planning_review_v3"
BATCH_SIZE = 8
MAX_ATTEMPTS = 2


def _partial(response, ids):
    """Accept only unique, well-formed decisions; ambiguity stays unresolved."""
    try:
        rows, by_id = _verdicts(response, ids)
        return by_id, {"code": "COMPLETE", "missing_ids": [], "duplicate_ids": [],
                       "unknown_ids": [], "invalid_ids": []}
    except ValueError as exc:
        code = str(exc).rsplit("[", 1)[-1].rstrip("]")
    diagnostic = {"code": code, "missing_ids": list(ids), "duplicate_ids": [],
                  "unknown_ids": [], "invalid_ids": []}
    # Never salvage a truncated response or an unexpected tool envelope.
    if code in {"INCOMPLETE_RESPONSE", "UNEXPECTED_TOOL", "INVALID_PAYLOAD"}:
        return {}, diagnostic
    value = next(b for b in response.content if getattr(b, "type", "") == "tool_use").input
    value = value.model_dump() if hasattr(value, "model_dump") else value
    groups = {}
    for row in value["claims"]:
        if isinstance(row, dict) and isinstance(row.get("claim_id"), str):
            groups.setdefault(row["claim_id"], []).append(row)
    accepted = {}
    for cid, rows in groups.items():
        if cid not in ids:
            diagnostic["unknown_ids"].append(cid)
        elif len(rows) != 1:
            diagnostic["duplicate_ids"].append(cid)
        elif (rows[0].get("verdict") not in ("supported", "unsupported")
              or not isinstance(rows[0].get("reason"), str) or not rows[0]["reason"].strip()):
            diagnostic["invalid_ids"].append(cid)
        else:
            accepted[cid] = rows[0]
    diagnostic["missing_ids"] = [cid for cid in ids if cid not in accepted]
    return accepted, diagnostic


def _request(claims, attempt, cost_sink):
    import explainer_pipeline as ep
    ids = [c["claim_id"] for c in claims]
    response = ep._claude().messages.create(
        model=ep.ANTHROPIC_MODEL, max_tokens=2400,
        system="Check each factual claim against ONLY its attached exact source passage. "
            "A quote being on a page does not prove its paraphrase. Intended outcomes are not "
            "observed outcomes; association is not causation. Supported means every factual "
            "detail is entailed. Do not use background knowledge. Submit one verdict for every claim. Keep each reason concise. "
            + f"Review contract {VERSION}; bounded attempt {attempt}.",
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
    return response


def _publish(inputs, state):
    # Exact input-bound progress includes rejected attempt counts, so a worker
    # restart cannot reset the retry budget. The flat report is for Studio only.
    from durable_execution import current
    from pathlib import Path
    runtime = current()
    if runtime:
        Path(runtime.output_dir, "planning_review.json").write_text(
            json.dumps(state, ensure_ascii=False))
    script_stages.save("planning-review-progress", inputs, state)


def _context():
    import explainer_pipeline as ep
    return {"contract": VERSION, "model": ep.ANTHROPIC_MODEL}


@script_stages.cached("planning-evidence", context=_context)
def prepare(dossier, *, cost_sink=None):
    import explainer_pipeline as ep
    claims = dossier.get("claims") or []
    ids = [c["claim_id"] for c in claims]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Planning evidence requires unique claim IDs")
    inputs = {"version": VERSION, "model": ep.ANTHROPIC_MODEL, "dossier": deepcopy(dossier)}
    state = script_stages.load("planning-review-progress", inputs) or {
        "version": VERSION, "input_hash": script_stages.digest(inputs),
        "status": "reviewing", "decisions": {}, "batches": {}, "attempts": []}
    for offset in range(0, len(claims), BATCH_SIZE):
        batch = claims[offset:offset + BATCH_SIZE]
        key = str(offset // BATCH_SIZE)
        attempt = state["batches"].get(key, 0)
        pending = [c for c in batch if c["claim_id"] not in state["decisions"]]
        while pending and attempt < MAX_ATTEMPTS:
            # Provider exceptions propagate through durable execution. Unknown paid
            # outcomes are never interpreted as an invitation to buy a second call.
            response = _request(pending, attempt + 1, cost_sink)
            accepted, diagnostic = _partial(response, [c["claim_id"] for c in pending])
            state["decisions"].update(accepted)
            attempt += 1
            state["batches"][key] = attempt
            state["attempts"].append({"batch": int(key), "attempt": attempt,
                                      "requested_ids": [c["claim_id"] for c in pending],
                                      **diagnostic})
            pending = [c for c in batch if c["claim_id"] not in state["decisions"]]
            state["unresolved_ids"] = [cid for cid in ids if cid not in state["decisions"]]
            state["status"] = "exhausted" if pending and attempt == MAX_ATTEMPTS else "reviewing"
            _publish(inputs, state)
        if pending:
            raise ValueError("UNSCORED_JUDGE_UNAVAILABLE: planning claim support "
                             "[REVIEW_EXHAUSTED]; unresolved=" + ",".join(c["claim_id"] for c in pending))
    by_id = state["decisions"]
    result = deepcopy(dossier)
    result["claim_support_review"] = [by_id[cid] for cid in ids]
    result["planning_excluded_claims"] = [c for c in result["claims"]
                                          if by_id[c["claim_id"]]["verdict"] != "supported"
                                          or not c.get("support_quote")]
    result["claims"] = [dict(c, planning_support="supported") for c in result["claims"]
                        if by_id[c["claim_id"]]["verdict"] == "supported" and c.get("support_quote")]
    state["status"] = "complete" if result["claims"] else "no_supported_claims"
    _publish(inputs, state)
    if not result["claims"]:
        raise ValueError("No source-supported claims remain for planning")
    return result
