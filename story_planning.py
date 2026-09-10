"""Compile, judge, and (once) repair one factual sheet before narration can be purchased."""
from copy import deepcopy

import cost_ledger
import research_handoff as handoff
import story_compiler as compiler
import story_fact_model as facts


def prepare(beats, engine_id, claims, claims_by_case=None, *, question="", judge=None,
            repair=None, cost_sink=None, cache=None):
    """Return the actual accepted objects and explicit results, not only kept IDs.

    Repair changes citations on the same factual sheet. It cannot generate replacement events,
    switch engines, add a second mechanism, or buy another full plan.
    """
    cache = {} if cache is None else cache
    evidence_cost = cost_ledger.StageCostSink(cost_sink, cost_ledger.BOUNDARY_A)
    repair_cost = cost_ledger.StageCostSink(cost_sink, cost_ledger.CAUSAL_SPINE)
    key = handoff.identity(beats, engine_id, claims, claims_by_case, question, repair is not None)
    saved = handoff.load(key)
    if saved:
        evidence_cost.append(saved["costs"].get("evidence", 0))
        repair_cost.append(saved["costs"].get("repair", 0))
        result = deepcopy(saved["prepared"])
        cache.update(result.get("cache") or {})
        result["cache"] = cache
        return result
    handoff.save(handoff.record(key, beats, claims))
    working = compiler.canonical_beats(beats)
    repairs = []
    for attempt in range(2):
        roles = compiler.compile_roles(working, engine_id, claims)
        if not roles.get("compiled") or not roles.get("passed"):
            failure = handoff.record(key, working, claims)
            failure.update(status="blocked", failure=compiler.summary(roles))
            handoff.save(failure)
            raise facts.StorySpineUnsupported(compiler.summary(roles), beats=working)
        sheet = compiler.splice_derived(roles["beats"], roles)
        compiled = facts.compile_spine(sheet, claims, claims_by_case, judge=judge, cache=cache,
                                      cost_sink=evidence_cost, engine_id=engine_id)
        effective = compiled["effective_beats"]
        if compiled["passed"] or attempt or repair is None:
            break
        mechanism = next((b for b in effective if facts.compiled_mechanism(b)), None)
        failures = [row for row in compiled["cascade"]["assertion_judgments"]
                    if mechanism and row["beat_id"] == mechanism["beat_id"]
                    and row.get("verdict") in {"unsupported", "partially_entailed"}]
        if any(row.get("verdict") == "contradicted"
               for row in compiled["cascade"]["assertion_judgments"]):
            break
        if not failures:
            break
        source = mechanism["derivation"]["source_ids"][0]
        # Keep narrowed factual events and pruning; never feed old synthetic nodes into repair.
        working = [deepcopy(b) for b in effective if not b.get("derived")]
        original = deepcopy(working)
        concerns = [{"beat_id": source, "why": "; ".join(
            f"{r['field']} {r['verdict']}: {r.get('reason', '')} "
            + "; ".join(r.get("unsupported_details") or []) for r in failures)}]
        case_claims = {ref for refs in (claims_by_case or {}).values() for ref in refs}
        eligible = {ref: claim for ref, claim in claims.items() if ref not in case_claims}
        before_charge = len(repair_cost)
        repaired, subtotal = repair(working, concerns, eligible, question, cost_sink=repair_cost)
        if len(repair_cost) == before_charge and subtotal:
            repair_cost.append(subtotal)
        # Only the two citation lists may change. Treat all other provider edits as unusable.
        new_by_id = {b["beat_id"]: b for b in repaired}
        working = original
        changed = False
        for beat in working:
            if beat["beat_id"] != source:
                continue
            update = (new_by_id.get(source) or {}).get("incentive") or {}
            for field in ("measure_claim_refs", "goal_claim_refs"):
                refs = update.get(field)
                if (isinstance(refs, list) and refs and all(isinstance(r, str) for r in refs)
                        and set(refs) <= set(eligible)
                        and refs != beat["incentive"].get(field)):
                    beat["incentive"][field] = list(dict.fromkeys(refs))
                    changed = True
        repairs.append({"beat_id": source, "attempted": True, "changed": changed,
                        "reason": concerns[0]["why"]})
        if not changed:
            break
    compiled["citation_repairs"] = repairs
    result = {"beats": compiled["effective_beats"], "compiled": compiled,
              "cache": cache, "cost_usd": sum(evidence_cost) + sum(repair_cost)}
    handoff.save(handoff.record(key, beats, claims, result,
                               {"evidence": sum(evidence_cost), "repair": sum(repair_cost)}))
    return result
