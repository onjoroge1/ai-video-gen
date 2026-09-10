"""One bounded evidence repair for a failed factual sheet, before narration or media.

The sheet supplies questions to investigate, never facts to assume. Existing verified source
pages are checked first; unresolved gaps may buy one focused search. New evidence must pass source
verification and entailment. Only citations change; the same events are judged again.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

import claim_verify
import claim_entailment as entailment
import cost_ledger
import event_functions
import longform_research as research
import story_fact_model as facts

REPAIR_VERSION = "evidence_coverage_v2"
LEGACY_REPAIR_VERSION = "evidence_coverage_v1"
MAX_GAPS = 4
MAX_NEW_CLAIMS = 8
MAX_REUSED_PASSAGES_PER_GAP = 3


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
        gaps.append({"beat_id": bid, "event_function": beat.get("event_function") or "",
                     "role": role,
                     "role_meaning": facts.role_function(role, compiled.get("engine_id", "")),
                     "assertion_to_verify": facts.event_of(beat)["text"],
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


def legacy_introduction_contract_failure(message: str) -> bool:
    """Recognize the one v1 sheet shaped by removal-only setup language."""
    return bool(message.startswith("STORY_SPINE_UNSUPPORTED\n")
                and "who was eating whom before anyone intervened" in message
                and "the species deliberately removed or introduced" in message
                and "[ROLE_CONTRACT_FAILED]" in message)


def legacy_introduction_dossier_repairable(dossier: dict, message: str) -> bool:
    """Allow one exact-checkpoint replan after v1 researched the impossible setup."""
    if (not isinstance(dossier, dict) or not legacy_introduction_contract_failure(message)
            or not research.validate_research_dossier(dossier)["passed"]):
        return False
    marker = dossier.get(LEGACY_REPAIR_VERSION)
    claim_ids = {claim.get("claim_id") for claim in dossier.get("claims") or []}
    return bool(isinstance(marker, dict) and marker.get("gaps")
                and marker.get("added_claim_ids")
                and set(marker["added_claim_ids"]) <= claim_ids
                and not dossier.get(REPAIR_VERSION))


def focused_provenance_failure(message: str) -> bool:
    """The focused search found URLs but exposed no readable provider excerpts."""
    match = re.fullmatch(
        r"Research dossier failed before scripting \[0 quotable excerpts available; "
        r"unverified_support_quotex([1-9]\d*)\]: (.+)", message or "")
    if not match:
        return False
    expected = "The claim support excerpt was not observed in a provider citation for its source URL."
    return match.group(2) == "; ".join([expected] * min(int(match.group(1)), 3))


def focused_provenance_dossier_repairable(dossier: dict, message: str) -> bool:
    """Permit one replay with citation extraction, from the validated pre-repair ledger."""
    return bool(focused_provenance_failure(message)
                and isinstance(dossier, dict)
                and research.validate_research_dossier(dossier)["passed"]
                and dossier.get(LEGACY_REPAIR_VERSION)
                and not dossier.get(REPAIR_VERSION))


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


def _reusable_source_claims(dossier: dict) -> list[dict]:
    """Use only retained primary-story sources from an already valid ledger."""
    if not research.validate_research_dossier(dossier)["passed"]:
        return []
    comparison_ids = {ref for refs in research._claims_by_parallel_case(dossier).values()
                      for ref in refs}
    seen, reusable = set(), []
    for claim in dossier.get("claims") or []:
        url = str((claim or {}).get("source_url") or "").strip()
        if (not url or claim.get("claim_id") in comparison_ids or url in seen
                or claim.get("quote_verified") is not True
                or claim.get("source_reachable") is not True):
            continue
        seen.add(url)
        reusable.append(deepcopy(claim))
    return reusable


def _checkpointed_entailment(claims, assertion, *, progress, save, accounted,
                             judge=None, cache=None, cost_sink=None):
    """Persist a decided result before the next call; never freeze an account outage.

    Provider responses are already durable. This also preserves their interpretation and
    usage subtotal, so a restart needs neither another judgment nor a reconstructed cache.
    """
    key = entailment.cache_key(claims, assertion,
                              contract_version=entailment.ENTAILMENT_CONTRACT_VERSION)
    decisions = progress.setdefault("decisions", {})
    if key in decisions:
        saved = decisions[key]
        if cost_sink is not None and key not in accounted:
            cost_sink.append(saved["cost_usd"])
        accounted.add(key)
        return deepcopy(saved["result"])
    before = sum(cost_sink) if cost_sink is not None else 0
    result = entailment.evidence_entailment(
        claims, assertion, judge=judge, cache=cache, cost_sink=cost_sink)
    accounted.add(key)
    if not entailment.is_retryable(result):
        decisions[key] = {"result": deepcopy(result),
                          "cost_usd": (sum(cost_sink) - before) if cost_sink is not None else 0}
        save()
    return result


def _reuse_existing_sources(dossier: dict, gaps: list[dict], *, judge=None, cache=None,
                            cost_sink=None, progress=None, save=lambda: None
                            ) -> tuple[list[dict], list[dict], set[str], dict]:
    """Mine exact passages from trusted ledger sources before purchasing another search.

    A retained source already passed source policy and provider-provenance validation. We fetch it
    once, freeze the ranked exact passages, then apply the unchanged Boundary A entailment judge.
    A lexical match alone can never create a claim. The enclosing repair identity binds this
    progress to the topic, base evidence, events and gaps.
    """
    sources = _reusable_source_claims(dossier)
    if not sources:
        return [], [], set(), {"sources": 0, "fetched": 0, "recovered_gaps": 0}
    progress = progress if progress is not None else {}
    if "candidates" not in progress:
        fetched = claim_verify.verify_claims(sources, repair=False)
        pages = fetched.get("pages") or {}
        candidates = {}
        for gap in gaps:
            assertion = str(gap.get("assertion_to_verify") or "").strip()
            query = " ".join([assertion, *[str(item) for item in gap.get("missing_details") or []]])
            ranked = []
            for url, page in pages.items():
                for passage in claim_verify.candidate_passages(
                        query, page, limit=MAX_REUSED_PASSAGES_PER_GAP):
                    overlap = len(claim_verify._content_words(query)
                                  & claim_verify._content_words(passage))
                    ranked.append((overlap, -len(passage), url, passage))
            ranked.sort(reverse=True)
            candidates[str(gap.get("beat_id") or "")] = [
                {"source_url": url, "support_quote": passage}
                for _, _, url, passage in ranked[:MAX_REUSED_PASSAGES_PER_GAP]]
        progress.update(candidates=candidates, fetched=fetched.get("fetched", 0))
        save()
    source_by_url = {str(claim.get("source_url") or "").strip(): claim for claim in sources}
    accepted, findings, recovered, accounted = [], [], set(), set()
    for gap in gaps:
        assertion = str(gap.get("assertion_to_verify") or "").strip()
        for candidate in progress["candidates"].get(str(gap.get("beat_id") or ""), []):
            url, passage = candidate["source_url"], candidate["support_quote"]
            result = _checkpointed_entailment(
                [{"claim_id": "source_excerpt", "claim": passage, "source_url": url}],
                assertion, progress=progress, save=save, accounted=accounted,
                judge=judge, cache=cache, cost_sink=cost_sink)
            findings.append({"gap_id": gap.get("beat_id"), "source_url": url,
                             "support_quote": passage, **result})
            if entailment.is_retryable(result):
                reason = str(result.get("reason") or "unknown provider failure")[:240]
                raise RuntimeError(
                    f"Evidence coverage judgment unavailable; no new claim accepted: {reason}")
            if not result["passed"]:
                continue
            origin = source_by_url[url]
            digest = hashlib.sha256(
                f"{gap.get('beat_id')}\n{url}\n{passage}".encode("utf-8")).hexdigest()[:12]
            accepted.append({
                "claim_id": f"reuse_{digest}", "claim": assertion, "source_url": url,
                "support_quote": passage, "source_type": origin.get("source_type"),
                "claim_kind": facts.UNKNOWN_KIND, "claim_kind_confidence": 0.0,
                "runner_up_kind": "", "runner_up_confidence": 0.0,
                "calculation": "", "assumptions": [],
                "geographic_scope": origin.get("geographic_scope") or "unspecified",
                "timescale": origin.get("timescale") or "unspecified",
                "confidence": origin.get("confidence") or "high",
                "allowed_exaggeration": False, "material": True,
                "quote_verified": True, "source_reachable": True,
                "reused_from_claim_id": origin.get("claim_id"),
            })
            recovered.add(str(gap.get("beat_id") or ""))
            break
    return accepted, findings, recovered, {
        "sources": len(sources), "fetched": progress.get("fetched", 0),
        "recovered_gaps": len(recovered),
    }


def _supplement_with_claims(question: str, claims: list[dict]) -> dict:
    return {"topic": question, "version": 1, "claims": claims,
            "citation_urls": sorted({claim["source_url"] for claim in claims}),
            "citation_records": [{"url": claim["source_url"],
                                  "cited_text": claim["support_quote"]}
                                 for claim in claims]}


def _state_path():
    from durable_execution import current
    runtime = current()
    return (Path(runtime.output_dir) / f"{REPAIR_VERSION}.json", runtime) if runtime else (None, None)


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
        save = lambda: _save(path, runtime, state)
        reused, reuse_findings, recovered, reuse_summary = _reuse_existing_sources(
            dossier, gaps, judge=judge, cache=cache, cost_sink=evidence_cost,
            progress=state.setdefault("source_progress", {}), save=save)
        # Keep the partial evidence and exact rejections even if focused research raises.
        state.update(reused_claims=deepcopy(reused), source_reuse=reuse_summary,
                     source_entailment=deepcopy(reuse_findings))
        save()
        remaining_gaps = [gap for gap in gaps
                          if str(gap.get("beat_id") or "") not in recovered]
        supplement = None
        try:
            if remaining_gaps:
                if "generated_supplement" in state:
                    supplement = deepcopy(state["generated_supplement"])
                    research_cost.append(state.get("research_cost_usd", 0))
                else:
                    supplement = generate(
                        question, evidence_gaps=remaining_gaps, cost_sink=research_cost)
                    state.update(generated_supplement=deepcopy(supplement),
                                 research_cost_usd=sum(research_cost))
                    save()
        finally:
            if isinstance(cost_sink, list):
                cost_sink.extend(research_cost)
        if supplement is not None and not research.validate_research_dossier(supplement)["passed"]:
            raise ValueError("Evidence supplement failed source validation")
        # A real quote can still be irrelevant to its attached claim. Check meaning as well
        # as presence before new claims are allowed into the story's factual ceiling.
        accepted, findings = list(reused), list(reuse_findings)
        accounted = set()
        for claim in (supplement or {}).get("claims", [])[:MAX_NEW_CLAIMS - len(accepted)]:
            result = _checkpointed_entailment(
                [{"claim_id": "source_excerpt", "claim": claim["support_quote"],
                  "source_url": claim["source_url"]}], claim["claim"],
                progress=state.setdefault("supplement_progress", {}), save=save,
                accounted=accounted,
                judge=judge, cache=cache, cost_sink=evidence_cost)
            findings.append({"claim_id": claim["claim_id"], **result})
            if entailment.is_retryable(result):
                reason = str(result.get("reason") or "unknown provider failure")[:240]
                raise RuntimeError(
                    f"Evidence coverage judgment unavailable; no new claim accepted: {reason}")
            if result["passed"]:
                accepted.append(claim)
        combined = _supplement_with_claims(question, accepted)
        state["supplement"] = deepcopy(combined)
        state["generated_supplement"] = (
            deepcopy(supplement) if supplement is not None else None)
        state["source_reuse"] = reuse_summary
        state["source_entailment"] = findings
        if not accepted:
            state["status"] = "unresolved"
            _save(path, runtime, state)
            return None
        merged, added = merge_supplement(dossier, combined)
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
