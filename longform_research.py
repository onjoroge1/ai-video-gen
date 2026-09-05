"""Fail-closed research and claim-ledger contracts for long-form explainers."""

from __future__ import annotations

import copy
import json
import re
from typing import Any
from urllib.parse import urlparse


LEGACY_DOSSIER_JSON_ERROR = (
    "Research provider returned malformed dossier JSON; source evidence was not "
    "passed to a paid JSON-repair model. No source claims were accepted."
)

LEGACY_ANAPHORIC_CLAIM_ERROR = (
    "Claim ledger failed after script/fact-check before asset spend: A factual or causal "
    "narration scene has no claim reference. [scene 3, role=payoff: It worked.]"
)


def parse_research_dossier_text(text_blocks: list[str]) -> dict:
    """Extract one complete ledger without rewriting any provider evidence.

    Search commentary and Markdown fences are not JSON. Walk complete top-level
    objects/arrays, respecting quoted braces and escapes, instead of parsing from
    the first opening brace through all remaining commentary. Never salvage a
    nested ledger from a truncated outer object or choose among multiple ledgers.
    Text blocks can split a JSON string at a citation boundary: preserve the bytes
    rather than inserting a newline into that string. The only syntax repair is
    removing trailing commas outside strings; incomplete values are never filled.
    """
    raw = "".join(text_blocks)
    candidates = []
    start = None
    stack = []
    quoted = escaped = False

    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("non-finite JSON number")

    def without_trailing_commas(fragment):
        # A punctuation-only repair. Never use a regex that could change a quote
        # such as "the result was ,}" or create a missing claim/value.
        output = []
        in_string = escape = False
        for position, character in enumerate(fragment):
            if in_string:
                if escape:
                    escape = False
                elif character == "\\":
                    escape = True
                elif character == '"':
                    in_string = False
            elif character == '"':
                in_string = True
            elif character == ",":
                following = fragment[position + 1:].lstrip()
                previous = fragment[:position].rstrip()
                if (following.startswith(("}", "]")) and previous
                        and previous[-1] not in "[{,:"):
                    continue
            output.append(character)
        return "".join(output)

    decoder = json.JSONDecoder(object_pairs_hook=unique_keys,
                               parse_constant=invalid_constant)
    for index, char in enumerate(raw):
        if start is None:
            if char in "{[":
                start = index
                stack = [char]
                quoted = escaped = False
            continue
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char in "{[":
            stack.append(char)
        elif char in "}]":
            if stack[-1] != ("{" if char == "}" else "["):
                raise ValueError("Research dossier JSON has mismatched delimiters; no claims accepted.")
            stack.pop()
            if not stack:
                fragment = raw[start:index + 1]
                start = None
                try:
                    value = decoder.decode(without_trailing_commas(fragment))
                except ValueError as exc:
                    if '"claims"' in fragment:
                        raise ValueError(
                            "Research provider returned malformed dossier JSON "
                            "(invalid complete object); no claims accepted.") from exc
                    continue  # e.g. a search explanation containing {query}
                if isinstance(value, dict) and "claims" in value:
                    candidates.append(value)
    if start is not None and '"claims"' in raw[start:]:
        raise ValueError("Research provider returned malformed dossier JSON "
                         "(incomplete object); no claims accepted.")
    if len(candidates) != 1:
        reason = "multiple candidate dossiers" if candidates else "no complete dossier object"
        raise ValueError(f"Research provider returned malformed dossier JSON ({reason}); "
                         "no claims accepted.")
    dossier = candidates[0]
    if not isinstance(dossier["claims"], list):
        raise ValueError("Research provider returned a dossier without a structured claims list.")
    return dossier


SOURCE_TYPES = {"primary", "authoritative_secondary"}
CONFIDENCE_LEVELS = {"high", "medium", "speculative"}
# Roles whose beats assert that something HAPPENED or IS TRUE, and therefore need a source even
# when the sentence carries no number or causal connective.
#
# "false_relief" was in this set and is not one of them. It is the "it looks like it is over"
# pause before the turn, and it asserts a feeling: a pilot was blocked because
# "For a moment, it all looks final. A sea erased, a desert that fights back." carries no
# checkable claim, and the only honest way to satisfy the rule would have been to staple a source
# to a line that claims nothing — citation theatre, which is worse than the gap.
#
# This narrows the ROLE trigger only. `_asserts_fact` still runs on every scene, so a false-relief
# beat that does state something ("the dam held for three years") is caught by its content exactly
# as before. Nothing that makes a claim becomes exempt.
FACT_ROLES = {
    "rules", "mechanism", "payoff", "escalation", "reversal", "branch",
    "final_escalation", "final_payoff",
}
_GLOBAL_WORDS = re.compile(r"\b(global(?:ly)?|worldwide|everywhere|all countries|the whole world)\b", re.I)
_HEDGE_WORDS = re.compile(r"\b(may|might|could|possibly|plausibly|in this scenario|model suggests)\b", re.I)
_INSTANT_WORDS = re.compile(r"\b(instant(?:ly)?|immediate(?:ly)?|at once|in seconds)\b", re.I)
_LONG_TIMESCALE_WORDS = re.compile(r"\b(years?|decades?|centuries|millennia|million|billion|geologic|evolutionary)\b", re.I)
_NEGATION_WORDS = re.compile(r"\b(?:no|not|never|neither|nor|without|cannot|can't|didn't|doesn't|isn't|wasn't|weren't)\b", re.I)
_NEGATION_CLAUSE_SPLIT = re.compile(
    r"(?<=[.!?;])\s+|,\s+(?=(?:but|yet|while|although|however)\b)", re.I)
_NUMERIC_OR_CAUSAL = re.compile(
    r"(?:\d|%|percent|kilomet|meter|mile|degree|because|causes?|therefore|leads? to|results? in)", re.I
)
_CONTENT_STOPWORDS = {
    "about", "after", "again", "also", "because", "before", "being", "between",
    "could", "does", "during", "from", "have", "into", "might", "more", "over",
    "said", "some", "than", "that", "their", "there", "these", "they", "this",
    "those", "through", "under", "very", "were", "what", "when", "where", "which",
    "while", "with", "would",
}
_WEAK_SOURCE_HOSTS = {
    "youtube.com", "www.youtube.com", "tiktok.com", "www.tiktok.com", "reddit.com",
    "www.reddit.com", "medium.com", "wikipedia.org", "en.wikipedia.org", "quora.com",
    "x.com", "twitter.com", "blogspot.com",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _semantic_words(value: str) -> set[str]:
    """Small deterministic entailment guard, not a substitute for fact checking.

    It prevents a valid claim ID from licensing wholly unrelated narration. Light suffix
    normalisation makes ordinary inflections comparable without pretending to understand prose.
    """
    words = set()
    for raw in re.findall(r"[a-z0-9]+", _text(value).casefold()):
        if len(raw) < 3 or raw in _CONTENT_STOPWORDS:
            continue
        word = raw
        for suffix in ("ingly", "edly", "ing", "ied", "ed", "es", "s"):
            if len(word) - len(suffix) >= 4 and word.endswith(suffix):
                word = word[:-len(suffix)] + ("y" if suffix == "ied" else "")
                break
        words.add(word)
    return words


def _assertion_for_phrase(narration: str, phrase: str) -> str:
    """Return the complete sentence containing a bound phrase."""
    needle = _text(phrase).casefold()
    if not needle:
        return ""
    for sentence in _SENTENCE_SPLIT.split(_text(narration)):
        if needle in sentence.casefold():
            return sentence.strip()
    return ""


def _claim_matches_assertion(claim: dict, assertion: str) -> bool:
    claim_words = _semantic_words(_text(claim.get("claim")))
    assertion_words = _semantic_words(assertion)
    if not claim_words or not assertion_words:
        return False
    shared = claim_words & assertion_words
    required = 1 if min(len(claim_words), len(assertion_words)) <= 3 else 2
    return len(shared) >= required and len(shared) / min(len(claim_words), len(assertion_words)) >= 0.25


def _support_contradicts_claim(claim_text: str, support_quote: str) -> bool:
    """Detect opposite polarity only when the negation governs the same proposition.

    A quote often contains an incidental negative clause (for example, "no archive proves the
    anecdote") beside a positive fact that supports the ledger claim. Merely comparing whether
    either *whole string* contains "not" rejects such evidence. Require the negated clause and
    the positive text to share most of the smaller proposition's content words.
    """
    claim_negative = bool(_NEGATION_WORDS.search(claim_text))
    quote_negative = bool(_NEGATION_WORDS.search(support_quote))
    if claim_negative == quote_negative:
        return False
    negative_text = claim_text if claim_negative else support_quote
    positive_text = support_quote if claim_negative else claim_text
    positive_words = _semantic_words(positive_text)
    if not positive_words:
        return False
    for clause in _NEGATION_CLAUSE_SPLIT.split(negative_text):
        if not _NEGATION_WORDS.search(clause):
            continue
        negative_words = _semantic_words(_NEGATION_WORDS.sub(" ", clause))
        if not negative_words:
            continue
        shared = negative_words & positive_words
        smaller = min(len(negative_words), len(positive_words))
        if len(shared) >= 2 and len(shared) / smaller >= 0.6:
            return True
    return False


def quarantine_contradicted_claims(dossier: dict) -> dict:
    """Keep directly contradicted candidates in audit data but out of writing context."""
    result = copy.deepcopy(dossier)
    retained, excluded = [], list(result.get("excluded_claims") or [])
    contradicted = 0
    for claim in result.get("claims") or []:
        if _support_contradicts_claim(
                _text(claim.get("claim")), _text(claim.get("support_quote"))):
            excluded.append({"claim": claim, "reason": "support_contradicts_claim"})
            contradicted += 1
        else:
            retained.append(claim)
    result["claims"] = retained
    result["excluded_claims"] = excluded
    result["semantic_source_filter"] = {
        "version": 1,
        "candidate_count": len(retained) + contradicted,
        "retained_count": len(retained),
        "excluded_count": contradicted,
    }
    return result


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


def _weak_source_domain(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").casefold().rstrip(".")
    except ValueError:
        return False  # The HTTPS URL validator reports malformed URLs separately.
    return any(host == blocked or host.endswith("." + blocked)
               for blocked in _WEAK_SOURCE_HOSTS)


def filter_disallowed_source_claims(dossier: dict) -> dict:
    """Quarantine disallowed source candidates before they can license narration.

    Source discovery returns candidates, and reading a real quote from a blog
    does not make it authoritative. Exclude those candidates just as the page
    verifier excludes quotes it cannot find. This is not a general error filter:
    surviving claims must pass the unchanged evidence, scope and story gates.
    Audit metadata is never included by claim_context_for_prompt.
    """
    if not isinstance(dossier, dict) or not isinstance(dossier.get("claims"), list):
        raise ValueError("Research candidates require a structured claims list.")
    report = validate_research_dossier(dossier)
    if any(item["code"] in {"invalid_claim", "invalid_claim_id"}
           for item in report["errors"]):
        raise ValueError("Research candidates have invalid or duplicate claim IDs/entries; "
                         "source filtering cannot repair an ambiguous ledger.")
    result = copy.deepcopy(dossier)
    retained, excluded = [], []
    for claim in result.get("claims") or []:
        if _weak_source_domain(_text(claim.get("source_url"))):
            excluded.append({"claim": claim, "reason": "weak_source_domain"})
        else:
            retained.append(claim)
    result["claims"] = retained
    # Discard provider-authored audit fields; only this code decides exclusions.
    result["excluded_claims"] = excluded
    result["source_filter"] = {"version": 1, "candidate_count": len(retained) + len(excluded),
                               "retained_count": len(retained), "excluded_count": len(excluded)}
    return result


def is_legacy_weak_source_failure(error: str) -> bool:
    """Recognize only the old all-or-nothing weak-domain gate, never other failures."""
    match = re.fullmatch(
        r"Research dossier failed before scripting \[\d+ quotable excerpts available; "
        r"weak_source_domainx([1-9]\d*)\]: (.+)", error or "")
    if not match:
        return False
    message = ("Social, community, encyclopedia, and generic blogging URLs are not "
               "authoritative evidence.")
    return match.group(2) == "; ".join([message] * min(int(match.group(1)), 3))


def is_legacy_negation_scope_failure(error: str) -> bool:
    """Recognize only PR81's whole-string negation error, never mixed evidence failures."""
    match = re.fullmatch(
        r"Research dossier failed before scripting \[\d+ quotable excerpts available; "
        r"support_contradicts_claimx([1-9]\d*)\]: (.+)", error or "")
    if not match:
        return False
    message = "The claim and its support excerpt disagree about negation."
    return match.group(2) == "; ".join([message] * min(int(match.group(1)), 3))


def is_legacy_anaphoric_claim_failure(error: str) -> bool:
    """Recognize only the observed Cobra payoff failure after PR82."""
    return (error or "") == LEGACY_ANAPHORIC_CLAIM_ERROR


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
        elif _weak_source_domain(source_url):
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
        claim_text = _text(claim.get("claim"))
        if support_quote and claim_text and _support_contradicts_claim(claim_text, support_quote):
            errors.append(_issue(
                "support_contradicts_claim",
                "The claim and its support excerpt disagree about negation.",
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


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _asserts_fact(narration: str) -> bool:
    """Does this narration ASSERT something a source must back?

    This used to search the whole scene at once, so a question counted as an assertion. The
    format instructs the writer to pose questions to the viewer -- "So what was actually eating
    the stomach lining?" -- and the word "eating" is innocent while "causes", "because" and
    "leads to" are exactly the vocabulary a question about causation uses. A scene whose only
    causal word sat inside a question was therefore required to cite a source for a sentence
    that claims nothing, and when the fact-check rewrote its narration and the binding was
    dropped, the run was rejected for an assertion it never made.

    A question is not a claim. Everything else is judged exactly as before.
    """
    for sentence in _SENTENCE_SPLIT.split(_text(narration)):
        sentence = sentence.strip()
        if not sentence or sentence.endswith("?"):
            continue
        if _NUMERIC_OR_CAUSAL.search(sentence):
            return True
    return False


def _claim_index(dossier: dict) -> dict[str, dict]:
    return {
        _text(claim.get("claim_id")): claim
        for claim in (dossier.get("claims") or [])
        if isinstance(claim, dict) and _text(claim.get("claim_id"))
    }


def validate_claim_joins(script: dict, dossier: dict) -> dict:
    """Verify source → claim → complete narrated assertion → visible evidence joins.

    A claim ID is only a pointer. It cannot license arbitrary narration, and a short substring
    cannot carry modality, scope, or timescale for a whole assertion. Resolve every binding to
    its complete sentence, then apply both lexical-relatedness and factual constraints there.
    """
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
        requires_claim = role in FACT_ROLES or _asserts_fact(narration)
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
            assertion = _assertion_for_phrase(narration, phrase)
            ref_evidence = _text(ref.get("evidence_id")) or evidence_id
            if not ref_evidence or ref_evidence != evidence_id:
                errors.append(_issue(
                    "claim_evidence_mismatch", "Claim reference and scene evidence IDs do not match.",
                    claim_id=claim_id, scene=index))
            claim = claims[claim_id]
            if assertion and not _claim_matches_assertion(claim, assertion):
                errors.append(_issue(
                    "claim_assertion_mismatch",
                    "The bound narrated assertion is not materially related to the referenced claim.",
                    claim_id=claim_id, scene=index))
            scope = _text(claim.get("geographic_scope")).casefold()
            if scope in {"local", "regional", "site-specific", "single site"} and _GLOBAL_WORDS.search(assertion):
                errors.append(_issue("scope_inflation", "Narration globalizes a local or regional claim.", claim_id=claim_id, scene=index))
            if _text(claim.get("confidence")) == "speculative" and assertion and not _HEDGE_WORDS.search(assertion):
                errors.append(_issue("unhedged_speculation", "A speculative claim is narrated as certain.", claim_id=claim_id, scene=index))
            timescale = _text(claim.get("timescale"))
            if _LONG_TIMESCALE_WORDS.search(timescale) and _INSTANT_WORDS.search(assertion):
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
