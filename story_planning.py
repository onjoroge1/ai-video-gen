"""Compile, judge, and (once) repair one factual sheet before narration can be purchased."""
from copy import deepcopy

import cost_ledger
import research_handoff as handoff
import story_compiler as compiler
import story_fact_model as facts


def prepare(beats, engine_id, claims, claims_by_case=None, *, question="", judge=None,
            repair=None, repair_event=None, cost_sink=None, cache=None):
    """Return the actual accepted objects and explicit results, not only kept IDs.

    TWO REPAIRS, ONE SHEET. `repair` changes citations; `repair_event` rewrites a beat's factual
    sentence inside the citations it already has. Neither may generate replacement events, switch
    engines, add a second mechanism, or buy another full plan.

    They are separate because the complaints are. The role contract says things like "bundles in
    an unrelated peak-population figure not needed for the function" and "does not specify the new
    ecological state" -- the first needs the sentence trimmed, the second extended, and neither is
    a question about which claim was cited. Sending those to the citation repair buys a call that
    cannot answer them.
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
            # A ROLE CONTRACT FAILURE IS A SENTENCE PROBLEM, so it gets the sentence repair --
            # but only once the evidence has nothing left to fix. A wrong citation is the more
            # fundamental fault and the round belongs to it; polishing prose that rests on the
            # wrong claim is work thrown away. It used to block outright, which refused stories
            # whose evidence was sound because a beat carried one figure too many or
            # under-specified an end state.
            # A beat research can still help is NOT a sentence problem. evidence_gaps decides
            # when a missing fact justifies a supplement, and rewording inside the claims a beat
            # already cites can never add one -- so firing here would spend a call that cannot
            # help AND consume the round that would have bought the research that could. The
            # cane-toad fixture is exactly this: its intervention beat cites a claim about the
            # ABSENCE of studies, and what it needs is the claim saying the toads were introduced.
            import research_coverage as _coverage

            gapped = {gap.get("beat_id") for gap in _coverage.evidence_gaps(compiled, effective)}
            role_issues = [issue for issue in (compiled.get("unrepairable") or [])
                           if issue.get("code") == "ROLE_CONTRACT_FAILED"
                           and issue.get("beat_id") and issue["beat_id"] not in gapped]
            if role_issues and repair_event is not None:
                working = [deepcopy(b) for b in effective if not b.get("derived")]
                original = deepcopy(working)
                before_charge = len(repair_cost)
                working, subtotal = repair_event(
                    working,
                    [{"beat_id": i["beat_id"], "role": i.get("role", ""), "why": i.get("message", "")}
                     for i in role_issues],
                    claims, question, cost_sink=repair_cost)
                if len(repair_cost) == before_charge and subtotal:
                    repair_cost.append(subtotal)
                # Only event TEXT may change. Everything else on the beat is restored, so a provider
                # that edits a role, a citation or a state transition cannot smuggle it through here.
                rewritten = {b["beat_id"]: facts.event_of(b)["text"] for b in working}
                working = original
                changed = False
                for beat in working:
                    text = rewritten.get(beat["beat_id"])
                    if text and text != facts.event_of(beat)["text"]:
                        beat["event"] = dict(beat.get("event") or {}, text=text)
                        changed = True
                repairs.append({"beat_id": role_issues[0]["beat_id"], "kind": "event_text",
                                "attempted": True, "changed": changed})
                if changed:
                    continue
                break
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
