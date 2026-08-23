"""Fail-closed research and claim-ledger contracts for long-form explainers."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


SOURCE_TYPES = {"primary", "authoritative_secondary"}
CONFIDENCE_LEVELS = {"high", "medium", "speculative"}
FACT_ROLES = {
    "rules", "mechanism", "payoff", "escalation", "reversal", "branch",
    "false_relief", "final_escalation", "final_payoff",
}
_GLOBAL_WORDS = re.compile(r"\b(global(?:ly)?|worldwide|everywhere|all countries|the whole world)\b", re.I)
_HEDGE_WORDS = re.compile(r"\b(may|might|could|possibly|plausibly|in this scenario|model suggests)\b", re.I)
_INSTANT_WORDS = re.compile(r"\b(instant(?:ly)?|immediate(?:ly)?|at once|in seconds)\b", re.I)
_LONG_TIMESCALE_WORDS = re.compile(r"\b(years?|decades?|centuries|millennia|million|billion|geologic|evolutionary)\b", re.I)
_NUMERIC_OR_CAUSAL = re.compile(
    r"(?:\d|%|percent|kilomet|meter|mile|degree|because|causes?|therefore|leads? to|results? in)", re.I
)
_WEAK_SOURCE_HOSTS = {
    "youtube.com", "www.youtube.com", "tiktok.com", "www.tiktok.com", "reddit.com",
    "www.reddit.com", "medium.com", "wikipedia.org", "en.wikipedia.org", "quora.com",
    "x.com", "twitter.com", "blogspot.com",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _issue(code: str, message: str, *, claim_id: str = "", scene: int | None = None) -> dict:
    item = {"code": code, "message": message}
    if claim_id:
        item["claim_id"] = claim_id
    if scene is not None:
        item["scene"] = scene
    return item


def _valid_https(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme == "https" and bool(parsed.netloc) and "." in parsed.netloc
    except Exception:
        return False


def _canonical_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}"
    except Exception:
        return _text(url)


def validate_research_dossier(dossier: dict) -> dict:
    """Validate provider output without trusting its self-reported source quality."""
    errors: list[dict] = []
    claims = dossier.get("claims") if isinstance(dossier, dict) else None
    citation_urls = {_canonical_url(_text(url)) for url in (dossier.get("citation_urls") or []) if _text(url)}
    citation_records: dict[str, list[str]] = {}
    for record in dossier.get("citation_records") or []:
        if not isinstance(record, dict):
            continue
        citation_records.setdefault(_canonical_url(_text(record.get("url"))), []).append(
            _text(record.get("cited_text")))
    if not isinstance(claims, list) or not claims:
        errors.append(_issue("missing_claims", "The research dossier contains no claims."))
        claims = []

    seen: set[str] = set()
    for claim in claims:
        if not isinstance(claim, dict):
            errors.append(_issue("invalid_claim", "A claim entry is not an object."))
            continue
        claim_id = _text(claim.get("claim_id"))
        if not claim_id or claim_id in seen:
            errors.append(_issue("invalid_claim_id", "Claim IDs must be present and unique.", claim_id=claim_id))
        seen.add(claim_id)
        if not _text(claim.get("claim")):
            errors.append(_issue("missing_claim_text", "A ledger claim has no claim text.", claim_id=claim_id))
        source_url = _text(claim.get("source_url"))
        if not _valid_https(source_url):
            errors.append(_issue("invalid_source_url", "The claim does not have a valid HTTPS source.", claim_id=claim_id))
        elif _canonical_url(source_url) not in citation_urls:
            errors.append(_issue(
                "unverified_source", "The source URL was not observed in the provider's web-search citations.",
                claim_id=claim_id))
        elif urlparse(source_url).netloc.casefold() in _WEAK_SOURCE_HOSTS:
            errors.append(_issue(
                "weak_source_domain", "Social, community, encyclopedia, and generic blogging URLs are not authoritative evidence.",
                claim_id=claim_id))
        support_quote = _text(claim.get("support_quote"))
        excerpts = citation_records.get(_canonical_url(source_url), [])
        if not support_quote:
            errors.append(_issue(
                "missing_support_quote", "The claim has no exact provider-observed support excerpt.",
                claim_id=claim_id))
        elif not any(support_quote.casefold() in excerpt.casefold() for excerpt in excerpts if excerpt):
            errors.append(_issue(
                "unverified_support_quote",
                "The claim support excerpt was not observed in a provider citation for its source URL.",
                claim_id=claim_id))
        if _text(claim.get("source_type")) not in SOURCE_TYPES:
            errors.append(_issue("invalid_source_type", "Source type must be primary or authoritative_secondary.", claim_id=claim_id))
        if _text(claim.get("confidence")) not in CONFIDENCE_LEVELS:
            errors.append(_issue("invalid_confidence", "Claim confidence is missing or invalid.", claim_id=claim_id))
        if not _text(claim.get("geographic_scope")):
            errors.append(_issue("missing_scope", "Claim geographic scope is required.", claim_id=claim_id))
        if not _text(claim.get("timescale")):
            errors.append(_issue("missing_timescale", "Claim timescale is required.", claim_id=claim_id))
        scope = _text(claim.get("geographic_scope")).casefold()
        if scope in {"local", "regional", "site-specific", "single site"} and _GLOBAL_WORDS.search(_text(claim.get("claim"))):
            errors.append(_issue("scope_inflation", "A local or regional source is stated as a global claim.", claim_id=claim_id))
        if claim.get("material", True) and claim.get("allowed_exaggeration") is True:
            errors.append(_issue("material_exaggeration", "A material scientific claim cannot permit exaggeration.", claim_id=claim_id))

    return {
        "version": 1,
        "passed": not errors,
        "claim_count": len(claims),
        "citation_count": len(citation_urls),
        "errors": errors,
    }


def _claim_index(dossier: dict) -> dict[str, dict]:
    return {
        _text(claim.get("claim_id")): claim
        for claim in (dossier.get("claims") or [])
        if isinstance(claim, dict) and _text(claim.get("claim_id"))
    }


def validate_claim_joins(script: dict, dossier: dict) -> dict:
    """Verify source → claim → exact narration phrase → visible evidence joins."""
    errors = list(validate_research_dossier(dossier)["errors"])
    claims = _claim_index(dossier)
    used: set[str] = set()
    scenes = script.get("scenes") or []

    for index, scene in enumerate(scenes, 1):
        narration = _text(scene.get("narration"))
        role = _text(scene.get("story_role")).casefold()
        refs = scene.get("claim_refs")
        if not isinstance(refs, list):
            refs = []
        requires_claim = role in FACT_ROLES or bool(_NUMERIC_OR_CAUSAL.search(narration))
        if requires_claim and not refs:
            errors.append(_issue(
                "unbound_factual_scene", "A factual or causal narration scene has no claim reference.",
                scene=index))
        evidence_id = _text(scene.get("evidence_id"))
        if refs and not evidence_id:
            errors.append(_issue("missing_evidence_join", "A claimed scene has no evidence_id.", scene=index))

        for ref in refs:
            if not isinstance(ref, dict):
                errors.append(_issue("invalid_claim_reference", "A scene claim reference is not an object.", scene=index))
                continue
            claim_id = _text(ref.get("claim_id"))
            phrase = _text(ref.get("narration_phrase"))
            if claim_id not in claims:
                errors.append(_issue("unknown_claim", "The scene references a claim absent from the dossier.", claim_id=claim_id, scene=index))
                continue
            used.add(claim_id)
            if not phrase or phrase.casefold() not in narration.casefold():
                errors.append(_issue(
                    "claim_phrase_not_in_narration",
                    "The bound narration phrase is not an exact substring of the final narration.",
                    claim_id=claim_id, scene=index))
            ref_evidence = _text(ref.get("evidence_id")) or evidence_id
            if not ref_evidence or ref_evidence != evidence_id:
                errors.append(_issue(
                    "claim_evidence_mismatch", "Claim reference and scene evidence IDs do not match.",
                    claim_id=claim_id, scene=index))
            claim = claims[claim_id]
            scope = _text(claim.get("geographic_scope")).casefold()
            if scope in {"local", "regional", "site-specific", "single site"} and _GLOBAL_WORDS.search(phrase):
                errors.append(_issue("scope_inflation", "Narration globalizes a local or regional claim.", claim_id=claim_id, scene=index))
            if _text(claim.get("confidence")) == "speculative" and phrase and not _HEDGE_WORDS.search(phrase):
                errors.append(_issue("unhedged_speculation", "A speculative claim is narrated as certain.", claim_id=claim_id, scene=index))
            timescale = _text(claim.get("timescale"))
            if _LONG_TIMESCALE_WORDS.search(timescale) and _INSTANT_WORDS.search(phrase):
                errors.append(_issue("timescale_contradiction", "Narration presents a long-timescale claim as immediate.", claim_id=claim_id, scene=index))

    return {
        "version": 1,
        "passed": not errors,
        "claim_count": len(claims),
        "used_claim_ids": sorted(used),
        "joined_reference_count": sum(
            len(scene.get("claim_refs") or []) for scene in scenes if isinstance(scene, dict)),
        "errors": errors,
    }


def claim_context_for_prompt(dossier: dict) -> list[dict]:
    """Return only the fields the story planner needs; provider metadata stays out of prompts."""
    keys = (
        "claim_id", "claim", "source_url", "support_quote", "source_type", "calculation", "assumptions",
        "geographic_scope", "timescale", "confidence", "allowed_exaggeration",
    )
    return [
        {key: claim.get(key) for key in keys}
        for claim in (dossier.get("claims") or [])
        if isinstance(claim, dict)
    ]
