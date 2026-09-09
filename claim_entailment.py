"""Semantic entailment across the two boundaries between research and prose.

The sourcing check this replaces was a word-set intersection: a narrated sentence passed if it
shared 25% of its content words with the claim it cited. Measured on a real draft, that rejected
"But it paid per corpse, not per empty field." (0 shared words) while accepting "But the street
cobras never thinned." on the strength of "cobra" and "the". It was not merely strict — it rewarded
narration that copied the ledger's vocabulary, which is where the lecture voice came from.

A factual EVENT now sits between the research and the prose, and two different questions are asked:

    RESEARCH CLAIMS  --(A: evidence entailment)-->  EVENT  --(B: narrative fidelity)-->  NARRATION

A: do the cited claims, TOGETHER, support the event? The unit is the claim set, not one claim at a
time — "paid per tail" and "living rats seen without tails" each entail only part of "people cut
tails off and kept the animals alive", and judged separately both come back unsupported.

B: does the narration stay inside the event? This is the boundary A cannot see. A perfectly
evidenced event still permits "hundreds of secret farms sprang up behind mud-brick homes overnight",
which invents the number, the secrecy, the material and the timescale. The event is the factual
ceiling for the prose.

Both return `unsupported_details`, because the repair pass needs to know WHICH detail is
unsupported. The code this replaces raised claim_assertion_mismatch and told the revision system
nothing it could act on.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Callable


# Bump when the MEANING of entailment changes — a reworded prompt, a different verdict vocabulary,
# a changed pass rule. It is part of the cache key, so every stored verdict from the old meaning is
# invalidated rather than silently reused under the new one.
ENTAILMENT_CONTRACT_VERSION = "entailment_v2"

# Judgements the model can return about the content.
SEMANTIC_VERDICTS = ("entailed", "partially_entailed", "unsupported", "contradicted")
# States the system reports about ITSELF, never about the content. A provider outage is not a
# sourcing failure, and collapsing the two produced ten identical "unsupported" rows that read
# exactly like a substantive result -- they were the fail-closed default, and they were nearly
# reported as evidence that the citations were bad.
OPERATIONAL_VERDICTS = ("unavailable", "invalid_response")
VERDICTS = SEMANTIC_VERDICTS + OPERATIONAL_VERDICTS

# Only full entailment passes. `partially_entailed` is a fail: half a fact is an unsourced fact,
# and the half that is missing is the half nobody checked.
PASSING_VERDICTS = ("entailed",)
# These mean "ask again", not "repair the content". Sending a rewrite pass at an unavailable judge
# edits a sentence nobody found fault with.
RETRYABLE_VERDICTS = OPERATIONAL_VERDICTS


def is_retryable(verdict: dict) -> bool:
    """Did this fail because of the system rather than because of the writing?"""
    return _text((verdict or {}).get("verdict")) in RETRYABLE_VERDICTS

# Fields that can change a verdict. `claim_id` is deliberately NOT among them — a repaired dossier
# rewrites a claim and keeps its id, and keying on the id would inherit a verdict for text nobody
# has judged. Under durable resume that is a stale PASS on a checkpoint, not just a stale value.
_CLAIM_KEY_FIELDS = ("claim", "support_quote", "source_url", "geographic_scope",
                     "timescale", "confidence")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _canonical_claim(claim: dict) -> str:
    parts = [f"{field}={_text((claim or {}).get(field))}" for field in _CLAIM_KEY_FIELDS]
    return "|".join(parts)


def cache_key(claims: list[dict], event_text: str, *,
              kind: str = "evidence",
              contract_version: str = ENTAILMENT_CONTRACT_VERSION) -> str:
    """Content-addressed, so nothing survives an edit to what it was judged against.

    Claims are sorted, because the judgement is about the SET: a reorder must not re-buy the call.
    """
    canonical = sorted(_canonical_claim(claim) for claim in (claims or []))
    payload = "\n".join([kind, contract_version, _text(event_text), *canonical])
    return f"{contract_version}:{kind}:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalise(reply: Any, fallback_reason: str) -> dict:
    """Coerce a judge reply into a verdict, failing closed on anything unusable.

    A malformed reply is not a pass. Sourcing fails closed or it is not a contract.
    """
    reply = reply if isinstance(reply, dict) else {}
    verdict = _text(reply.get("verdict")).lower().replace(" ", "_")
    if verdict not in SEMANTIC_VERDICTS:
        # An unreadable reply is an operational fault, not a finding about the evidence.
        return {"verdict": "invalid_response", "passed": False, "supported_core": "",
                "unsupported_details": [],
                "reason": fallback_reason or f"unusable judge verdict {verdict!r}"}
    details = [_text(item) for item in (reply.get("unsupported_details") or []) if _text(item)]
    # `partially_entailed` is the most useful state in the system, and reducing it to passed=False
    # throws away what makes it useful. "Unsupported" says remove the assertion; "partially" says
    # there is a valid factual core worth keeping and these specific inventions to strip. The
    # repair instruction is deterministic only if both halves survive.
    return {"verdict": verdict, "passed": verdict in PASSING_VERDICTS,
            "supported_core": _text(reply.get("supported_core")),
            "unsupported_details": details, "reason": _text(reply.get("reason"))}


_EVIDENCE_SYSTEM = (
    "You decide whether a set of researched claims, taken TOGETHER, supports one factual statement "
    "from a documentary script. Judge meaning, not wording: a faithful paraphrase that shares no "
    "vocabulary with the claims is still entailed, and a sentence that merely shares subject matter "
    "with them is not. Return ONLY JSON."
)

_FIDELITY_SYSTEM = (
    "You decide whether a line of documentary narration stays inside one factual event. The event "
    "is the factual ceiling: the narration may rephrase it, dramatise it, reorder it and choose its "
    "own words, but it may not assert history the event does not contain.\n"
    "\nALLOWED — never flag these:\n"
    "- rhetorical questions ('why kill the rat when the tail was the part that paid?')\n"
    "- transitions and framing ('then', 'but', 'so', 'here is the problem', 'somebody noticed')\n"
    "- figurative language and non-factual emphasis\n"
    "- causal connectives already entailed by the event sequence\n"
    "- restating the event as a scene rather than a summary\n"
    "A rhetorical question does not assert that its premise happened. Framing that moves the story "
    "along is not a new fact.\n"
    "\nFLAG — these are historical assertions and need the event behind them:\n"
    "- quantities and scale ('hundreds of farms')\n"
    "- dates and timescales ('overnight', 'within a year', 'in 1902')\n"
    "- locations and physical settings ('behind mud-brick walls', 'in the poorest districts')\n"
    "- named actors\n"
    "- motivations presented as historical fact\n"
    "- secrecy, or any characterisation of how something was done\n"
    "- direct quotes\n"
    "- causal mechanisms the event does not contain\n"
    "\nFlag a detail only if a viewer would come away believing a specific thing about the world "
    "that the event does not support. Return ONLY JSON."
)


_RETURN_SHAPE = (
    'Return ONLY JSON: {"verdict":"entailed|partially_entailed|unsupported|contradicted",'
    '"supported_core":"the part that IS supported, stated plainly, or \'\' if none",'
    '"unsupported_details":["the specific detail that is not supported", "..."],'
    '"reason":"one sentence"}.\n'
    'Use "entailed" only when EVERY factual element is supported. Use "partially_entailed" when '
    'some are and some are not, and list the ones that are not. Use "contradicted" when something '
    'asserted is incompatible with the source material.'
)


def _default_judge(payload: dict) -> dict:
    """The real call. Imported lazily so the module is testable without a provider configured."""
    import explainer_pipeline as ep

    if payload.get("kind") == "function":
        system = _EVIDENCE_SYSTEM
        body = ("SUPPORTED STATEMENT:\n" + payload["claims"][0]["claim"]
                + "\nREQUIRED FACTUAL FUNCTION:\n" + payload["event"]
                + "\nDoes this statement actually supply every required part of this function? "
                  "Judge only the statement, not a planner's label or your background knowledge. "
                  "Shared subjects are insufficient. A lack of impact studies does not establish "
                  "which intervention was implemented or its purpose. Omitting a date is fine "
                  "when the function does not require one. Return entailed only if the function "
                  "remains complete.\n" + _RETURN_SHAPE)
    elif payload.get("kind") == "relationship":
        system = _EVIDENCE_SYSTEM
        body = ("SUPPORTED FACTS:\n" + json.dumps(payload["claims"], ensure_ascii=False)
                + "\nPROPOSED RELATIONSHIP:\n" + payload["event"]
                + "\nDecide from these facts alone. Shared vocabulary, different wording, or a "
                  "planner's role label proves nothing. Both sides must concern the same target "
                  "and policy. Do not infer motives, aggregate population changes, or an economic "
                  "valuation absent from the facts.\n" + _RETURN_SHAPE)
    elif payload.get("kind") == "fidelity":
        system = _FIDELITY_SYSTEM
        body = (f"EVENT (the factual ceiling):\n{payload['event']}\n\n"
                f"NARRATION:\n{payload['narration']}\n\n"
                "Does the narration introduce any factual detail the event does not contain?\n"
                + _RETURN_SHAPE)
    else:
        claims = "\n".join(f"- [{c.get('claim_id') or '?'}] {c.get('claim')}"
                           for c in payload["claims"])
        system = _EVIDENCE_SYSTEM
        body = (f"CLAIMS:\n{claims}\n\nFACTUAL STATEMENT:\n{payload['event']}\n\n"
                "Taken together, do the claims support the statement?\n" + _RETURN_SHAPE)

    response = ep._claude().messages.create(
        model=ep.ANTHROPIC_MODEL, max_tokens=600, system=system,
        messages=[{"role": "user", "content": body}])
    if payload.get("cost_sink") is not None:
        payload["cost_sink"].append(ep._msg_cost(response.usage))
    # A malformed 600-token verdict is an unavailable judgment. Never launch an unaccounted
    # 16k-token script-JSON repair from this small, bounded provider call.
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw[raw.find("{"):raw.rfind("}") + 1]
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


def _judged(payload: dict, key: str, judge: Callable[[dict], Any] | None,
            cache: dict | None, fallback_reason: str) -> dict:
    if cache is not None and key in cache and not is_retryable(cache[key]):
        return dict(cache[key])
    try:
        reply = (judge or _default_judge)(payload)
    except Exception as exc:                       # noqa: BLE001 - any provider failure fails closed
        result = {"verdict": "unavailable", "passed": False, "supported_core": "",
                  "unsupported_details": [],
                  "reason": f"provider_unavailable: {type(exc).__name__}: {str(exc)[:120]}"}
        # Deliberately NOT cached. A credit outage must not freeze into a stored verdict that a
        # later resume reads as a decided result.
        return result
    result = _normalise(reply, fallback_reason)
    if cache is not None and not is_retryable(result):
        cache[key] = dict(result)
    return result


def function_fulfillment(statement: str, function: str, *, judge=None,
                         cache=None, cost_sink=None) -> dict:
    """Check a narrowed, already-supported fact still supplies its compiled story function."""
    facts = [{"claim_id": "supported_core", "claim": statement}]
    payload = {"kind": "function", "claims": facts, "event": function, "cost_sink": cost_sink}
    return _judged(payload, cache_key(facts, function, kind="function"), judge, cache, "")


def relationship_entailment(facts: list[dict], statement: str, *, judge=None,
                           cache=None, cost_sink=None) -> dict:
    """Validate a proposed relationship over already-supported facts using Boundary A."""
    if not facts:
        return _normalise({"verdict": "unsupported", "reason": "no supported inputs"}, "")
    payload = {"kind": "relationship", "claims": facts, "event": statement,
               "cost_sink": cost_sink}
    return _judged(payload, cache_key(facts, statement, kind="relationship"),
                   judge, cache, "")


def evidence_entailment(claims: list[dict], event_text: str, *,
                        judge: Callable[[dict], Any] | None = None,
                        cache: dict | None = None,
                        cost_sink: list | None = None) -> dict:
    """Boundary A. Do the cited claims, together, support this factual event?

    One call per EVENT, never one per claim.
    """
    claims = [claim for claim in (claims or []) if isinstance(claim, dict)]
    if not claims:
        return {"verdict": "unsupported", "passed": False, "supported_core": "",
                "unsupported_details": [], "reason": "the event cites no claims"}
    if not _text(event_text):
        return {"verdict": "unsupported", "passed": False, "supported_core": "",
                "unsupported_details": [], "reason": "the event has no text"}
    payload = {"kind": "evidence", "claims": claims, "event": _text(event_text),
               "cost_sink": cost_sink}
    return _judged(payload, cache_key(claims, event_text, kind="evidence"),
                   judge, cache, "")


def narration_fidelity(event_text: str, narration: str, *,
                       judge: Callable[[dict], Any] | None = None,
                       cache: dict | None = None,
                       cost_sink: list | None = None) -> dict:
    """Boundary B. Does the narration stay inside the event it expresses?

    The event is the factual ceiling. Rephrasing is free; new facts are not.
    """
    if not _text(narration):
        return {"verdict": "entailed", "passed": True, "supported_core": "",
                "unsupported_details": [], "reason": "no narration to check"}
    if not _text(event_text):
        return {"verdict": "unsupported", "passed": False, "supported_core": "",
                "unsupported_details": [],
                "reason": "narration asserts something with no event behind it"}
    payload = {"kind": "fidelity", "event": _text(event_text), "narration": _text(narration),
               "cost_sink": cost_sink}
    key = cache_key([{"claim": _text(event_text)}], _text(narration), kind="fidelity")
    return _judged(payload, key, judge, cache, "")


def repair_instruction(verdict: dict) -> str:
    """Turn a failing verdict into an instruction narrow enough to be safe.

    "Fix the sourcing" hands a general revision model the whole sentence and hopes. A partial
    verdict already names the supported core and every unsupported detail, so the instruction can
    say exactly what to keep and exactly what to remove — and nothing about inventing a
    replacement, which is how a sourcing repair becomes a new sourcing failure.

    Returns "" when there is nothing to repair.
    """
    verdict = verdict if isinstance(verdict, dict) else {}
    if verdict.get("passed"):
        return ""
    details = [item for item in (verdict.get("unsupported_details") or []) if _text(item)]
    core = _text(verdict.get("supported_core"))
    if not details:
        return ("Nothing here is supported by the cited evidence. Remove the assertion, or replace "
                "it with one the evidence does support. Do not add new factual detail.")
    lines = []
    if core:
        lines.append(f"PRESERVE this supported core, in your own words if you prefer: {core}")
    lines.append("REMOVE or replace ONLY these unsupported factual details:")
    lines += [f"  - {item}" for item in details]
    lines.append("Do not add any new factual detail. Do not restate the evidence in its own "
                 "vocabulary; ordinary language that means the same thing is correct.")
    return "\n".join(lines)
