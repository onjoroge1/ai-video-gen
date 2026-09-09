"""One focused evidence repair for a failed factual sheet, before narration or media.

The sheet supplies questions to investigate, never facts to assume. New evidence must pass
source verification and entailment. Only citations change; the same events are judged again.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

import claim_entailment as entailment
import cost_ledger
import event_functions
import longform_research as research
import story_fact_model as facts

REPAIR_VERSION = "evidence_coverage_v1"
MAX_GAPS = 4
MAX_NEW_CLAIMS = 8


def evidence_gaps(compiled: dict, beats: list) -> list[dict]:
    """Only substantive gaps in required primary-story events justify new research."""
    cascade = compiled.get("cascade") or {}
    judgments = cascade.get("judgments") or []
    if (not event_functions.map_for(compiled.get("engine_id", ""))
            or compiled.get("passed") or cascade.get("unavailable")
            or any(row.get("verdict") == "contradicted" for row in judgments)
            or any(row.get("function_verdict") in entailment.OPERATIONAL_VERDICTS
                   for row in compiled.get("unrepairable") or [])):
        return []
    required = set(facts.required_spine_roles(compiled.get("engine_id", "")))
    failed = set(compiled.get("still_failing") or [])
    reasons = {row["beat_id"]: row for row in cascade.get("evidence") or []}
    gaps = []
    for beat in beats:
        bid = beat.get("beat_id")
        role = beat.get("causal_role") or beat.get("role")
        result = reasons.get(bid) or {}
        if (bid not in failed or role not in required or facts.compiled_mechanism(beat)
                or facts.scope_of(beat) != facts.PRIMARY_STORY
                or result.get("verdict") not in {"unsupported", "partially_entailed"}):
            continue
        gaps.append({"beat_id": bid, "assertion_to_verify": facts.event_of(beat)["text"],
                     "missing_details": result.get("unsupported_details") or [],
                     "reason": result.get("reason", "")})
    # A broadly unsupported sheet needs a new editorial decision, not unlimited gap filling.
    return gaps if 0 < len(gaps) <= MAX_GAPS else []


def legacy_setup_failure(message: str) -> bool:
    """Recognize only the pre-narration ecosystem setup classification defect."""
    return bool(message.startswith("STORY_SPINE_UNSUPPORTED\n")
                and "who was eating whom before anyone intervened" in message
                and re.search(r"\[CLAIM_KIND_MISMATCH\] beat [\w-]+ is a setup beat "
                              r"citing [\w-]+, which is a mechanism claim;", message))


def legacy_setup_dossier_repairable(dossier: dict, message: str) -> bool:
    if (not isinstance(dossier, dict) or not legacy_setup_failure(message)
            or not research.validate_research_dossier(dossier)["passed"]):
        return False
    refs = re.findall(r"setup beat citing ([\w-]+), which is a mechanism claim;", message)
    claims = research._claim_index(dossier)
    return bool(refs and all(facts.resolved_claim_kind(claims.get(ref) or {})[0] == "mechanism"
                             for ref in refs)
                and "mechanism" in facts.accepted_claim_kinds("setup", "removed_keystone"))


def merge_supplement(original: dict, supplement: dict) -> tuple[dict, list[str]]:
    """Keep original IDs/evidence intact and append independently validated primary claims."""
    if not research.validate_research_dossier(supplement)["passed"]:
        raise ValueError("Evidence supplement failed source validation")
    merged = deepcopy(original)
    used = {c["claim_id"] for c in merged["claims"]}
    existing = {(c.get("claim"), c.get("source_url")) for c in merged["claims"]}
    comparisons = {ref for refs in research._claims_by_parallel_case(supplement).values()
                   for ref in refs}
    added = []
    for claim in supplement["claims"][:MAX_NEW_CLAIMS]:
        if (claim["claim_id"] in comparisons
                or (claim.get("claim"), claim.get("source_url")) in existing):
            continue
        item = deepcopy(claim)
        identifier = "repair_" + claim["claim_id"]
        while identifier in used:
            identifier = "repair_" + identifier
        item["claim_id"] = identifier
        used.add(identifier)
        existing.add((item.get("claim"), item.get("source_url")))
        merged["claims"].append(item)
        added.append(identifier)
    merged["citation_urls"] = sorted(set(original.get("citation_urls") or [])
                                     | set(supplement.get("citation_urls") or []))
    merged["citation_records"] = (deepcopy(original.get("citation_records") or [])
                                  + deepcopy(supplement.get("citation_records") or []))
    merged["validation"] = research.validate_research_dossier(merged)
    if not merged["validation"]["passed"]:
        raise ValueError("Merged evidence failed validation")
    return merged, added


def _state_path():
    from durable_execution import current
    runtime = current()
    return (Path(runtime.output_dir) / "evidence_coverage_repair.json", runtime) if runtime else (None, None)


def _save(path, runtime, state):
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        runtime.checkpoint("evidence-coverage-repair")


def repair_sheet(question, beats, compiled, dossier, *, generate, judge=None,
                 cache=None, cost_sink=None):
    """Research missing facts once; retain the same sheet and extend failed beats' citations."""
    gaps = evidence_gaps(compiled, beats)
    if not gaps or dossier.get(REPAIR_VERSION):
        return None
    path, runtime = _state_path()
    identity = {"version": REPAIR_VERSION, "engine": compiled.get("engine_id"),
                "question": question, "gaps": gaps,
                "base_evidence_sha256": hashlib.sha256(json.dumps(
                    dossier.get("claims"), sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
    state = {"identity": identity, "status": "started"}
    if path and path.exists():
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("identity") != identity:
            raise ValueError("This job already attempted evidence repair for a different gap set")
        if state.get("status") == "unresolved":
            return None
    else:
        _save(path, runtime, state)
    research_cost = cost_ledger.StageCostSink(cost_sink, cost_ledger.RESEARCH)
    evidence_cost = cost_ledger.StageCostSink(cost_sink, cost_ledger.BOUNDARY_A)
    if state.get("status") == "completed":
        # Report the reused work once in this run's accounting, just as durable provider
        # responses do. Research remains outside the separately reported script subtotal.
        research_cost.append(state.get("research_cost_usd", 0))
        evidence_cost.append(state.get("script_cost_usd", 0))
        if isinstance(cost_sink, list):
            cost_sink.extend(research_cost)
    else:
        try:
            supplement = generate(question, evidence_gaps=gaps, cost_sink=research_cost)
        finally:
            if isinstance(cost_sink, list):
                cost_sink.extend(research_cost)
        if not research.validate_research_dossier(supplement)["passed"]:
            raise ValueError("Evidence supplement failed source validation")
        # A real quote can still be irrelevant to its attached claim. Check meaning as well
        # as presence before new claims are allowed into the story's factual ceiling.
        accepted, findings = [], []
        for claim in supplement["claims"][:MAX_NEW_CLAIMS]:
            result = entailment.evidence_entailment(
                [{"claim_id": "source_excerpt", "claim": claim["support_quote"],
                  "source_url": claim["source_url"]}], claim["claim"],
                judge=judge, cache=cache, cost_sink=evidence_cost)
            findings.append({"claim_id": claim["claim_id"], **result})
            if entailment.is_retryable(result):
                raise RuntimeError("Evidence coverage judgment unavailable; no new claim accepted")
            if result["passed"]:
                accepted.append(claim)
        state["supplement"] = deepcopy(supplement)
        state["source_entailment"] = findings
        supplement = dict(supplement, claims=accepted)
        if not accepted:
            state["status"] = "unresolved"
            _save(path, runtime, state)
            return None
        merged, added = merge_supplement(dossier, supplement)
        if not added:
            state["status"] = "unresolved"
            _save(path, runtime, state)
            return None
        merged[REPAIR_VERSION] = {"gaps": gaps, "added_claim_ids": added}
        state.update(status="completed", dossier=merged, added_claim_ids=added,
                     research_cost_usd=sum(research_cost), script_cost_usd=sum(evidence_cost))
        _save(path, runtime, state)
    merged, added = deepcopy(state["dossier"]), state["added_claim_ids"]
    if not research.validate_research_dossier(merged)["passed"]:
        raise ValueError("Saved repaired evidence no longer validates")
    if path:
        original_path = path.parent / "research_dossier.initial.json"
        if not original_path.exists():
            original_path.write_text(json.dumps(dossier, ensure_ascii=False, indent=2), encoding="utf-8")
        (path.parent / "research_dossier.json").write_text(
            json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        runtime.checkpoint("evidence-coverage-accepted")
    repaired = deepcopy(beats)
    failed_ids = {gap["beat_id"] for gap in gaps}
    claims = research._claim_index(merged)
    for beat in repaired:
        if beat.get("beat_id") in failed_ids:
            event = facts.event_of(beat)
            kinds = facts.accepted_claim_kinds(
                beat.get("causal_role") or beat.get("role"), compiled.get("engine_id", ""))
            eligible = [ref for ref in added if facts.resolved_claim_kind(claims[ref])[0]
                        in (*kinds, facts.UNKNOWN_KIND)]
            event["claim_refs"] = list(dict.fromkeys(event["claim_refs"] + eligible))
            beat["event"] = event
    return {"beats": repaired, "dossier": merged,
            "cost_usd": sum(evidence_cost), "research_cost_usd": sum(research_cost)}
