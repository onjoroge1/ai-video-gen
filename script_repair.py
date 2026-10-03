"""Conservative integrity checks at narration repair boundaries."""
from __future__ import annotations

from copy import deepcopy
import re


def broken_repair(text: str) -> bool:
    """Catch incomplete repair tails; this is not a general English grammar scorer.

    Arbitrary substring deletion is forbidden separately. These high-confidence checks also
    reject the same dangling constructions when a model returns them as a repair.
    """
    if not isinstance(text, str) or not text.strip():
        return True
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        tail = sentence.lower().rstrip(".!?\"' ”’")
        if re.search(r"\b(?:with|from|into|onto|because|although|and|or|the|a|an)"
                     r"(?:\s+(?:instead|now|still))?$", tail):
            return True
        # Location-only leftovers from removing the entire predicate (Studio 72d6e8da).
        place = r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*"
        if re.fullmatch(r"(?:(?:So|so)\s+)?(?:[Bb]ack\s+)?(?:[Aa]t|[Ii]n|[Nn]ear)\s+"
                        + place + r"(?:,\s*(?:in|near)\s+(?:southern |northern )?"
                        + place + r")?(?:,\s*(?:researchers|crews))?",
                        sentence.strip().rstrip(".!?")):
            return True
    return False


def reconcile_factcheck_events(script: dict, before: list[str], proposals: list,
                               dossier: dict, cost_sink: list) -> None:
    """Accept an event correction only through the existing evidence and fidelity cascade.

    Fact-check notes are not evidence. IDs, scope, role/kind, source entailment and narration
    fidelity must all pass. A rejected proposal leaves the old event for the final ledger to
    refuse; it never restores narration that the fact checker identified as false.
    """
    import longform_research as lr
    import story_fact_model as sfm

    scenes = script.get("scenes") or []
    if not isinstance(proposals, list):
        proposals = []
    claims = lr._claim_index(dossier or {})
    cache = script.setdefault("_entailment_cache", {})
    results = []
    seen = set()
    duplicate_indexes = {p.get("scene") for p in proposals if isinstance(p, dict)
                         and isinstance(p.get("scene"), int)
                         and sum(isinstance(q, dict) and q.get("scene") == p.get("scene")
                                 for q in proposals) > 1}
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        index = proposal.get("scene")
        if (type(index) is not int or not 1 <= index <= len(scenes)
                or index in seen or index in duplicate_indexes):
            continue
        seen.add(index)
        scene = scenes[index - 1]
        if index > len(before) or scene.get("narration") == before[index - 1]:
            continue
        event = proposal.get("event")
        refs = event.get("claim_refs") if isinstance(event, dict) else None
        if (not isinstance(event, dict) or not isinstance(event.get("text"), str)
                or not event["text"].strip() or not isinstance(refs, list) or not refs
                or any(not isinstance(ref, str) or ref not in claims for ref in refs)
                or scene.get("derivation")):
            results.append({"scene": index, "passed": False, "reason": "invalid_or_derived_event"})
            continue
        candidate = deepcopy(scene)
        candidate["event"] = {"text": event["text"].strip(), "claim_refs": list(dict.fromkeys(refs))}
        report = sfm.validate_cascade(
            [candidate], claims, lr._claims_by_parallel_case(dossier or {}),
            cache=cache, cost_sink=cost_sink, engine_id=script.get("_story_engine", ""))
        results.append({"scene": index, "passed": bool(report.get("passed")), "report": report})
        if report.get("passed"):
            scene["event"] = candidate["event"]
            eid = scene.get("evidence_id") or next(
                (r.get("evidence_id") for r in scene.get("claim_refs", [])
                 if isinstance(r, dict) and r.get("evidence_id")), "")
            scene["claim_refs"] = [{"claim_id": cid, "evidence_id": eid,
                                    "narration_phrase": scene["narration"]}
                                   for cid in candidate["event"]["claim_refs"]]
    script["_factcheck_reconciliation"] = results
    script.pop("_claim_validation", None)
