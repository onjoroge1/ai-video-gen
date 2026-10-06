"""Fail-closed research and claim-ledger contracts for long-form explainers."""

from __future__ import annotations

import copy
import json
import math
import re
from typing import Any
from urllib.parse import urlparse


# ── How much research a runtime needs ────────────────────────────────────────────────────────
#
# The chain that sets visual density runs: claims -> events -> scenes -> scene length -> states
# -> holds. The last link was fixed by sizing states from the hold ceiling, and that turned out
# not to be enough -- asked for 26 states in one scene the model returns 8, because a 228-word
# scene does not contain 26 distinct visible changes. Scene LENGTH is the binding constraint,
# and scene length is set here, at the top of the chain.
#
# MEASURED on the recorded 252.5s film: a 22-28 claim request returned 19 verified claims, which
# supported 8 factual events, which became 7 scenes of ~43s each. Nothing downstream can rescue a
# 43-second scene. The request was a flat literal regardless of runtime, so a 300s film and a 60s
# film asked for exactly the same research and got the same ~8 events.
#
# The three ratios below are measured from that run, not chosen:

# A scene the writer can actually illustrate -- DERIVED, not chosen.
#
# This was 25.0, reasoned as "6-8 states per scene at the 3.5s ceiling buys 21-28 seconds". Both
# halves of that were wrong in the same direction. The cadence TARGET is 2.75s, not the 3.5s
# rejection line, and the state ceiling is a measured 7, so the real figure is 7 x 2.75 = 19.25s.
# Planning 25-second scenes asked for ~9 states from a writer that returns 7, and the 5.75-second
# shortfall per scene is what the rendered gate reports as long_visual_hold.
#
# longform_evidence owns both numbers because it owns the state contract. Importing them is what
# keeps this from becoming a third independent copy of the same arithmetic -- there were already
# two, disagreeing by 6 seconds a scene.
from longform_evidence import illustratable_scene_seconds as _illustratable_scene_seconds

SECONDS_PER_SCENE_TARGET = _illustratable_scene_seconds()

# 19 verified claims supported 8 events on the recorded run. Events need corroboration and some
# claims are context that never becomes an event, so this is well above 1.
CLAIMS_PER_EVENT = 2.4

# 19 verified from a 22-28 ask. Claims die on paywalls, 403s and quotes that are not on the page,
# and that attrition is already why the prompt asks for more than the video needs.
VERIFIED_CLAIM_YIELD = 0.76

# The tuned floor. 22-28 is what the 60-90s lane was calibrated on and it works there; this must
# scale UP with runtime and never below the numbers short films were validated against.
MIN_CLAIM_REQUEST = 22


def events_for_runtime(duration_sec: float) -> int:
    """How many factual events a runtime needs to keep scenes short enough to illustrate."""
    return max(1, math.ceil(max(0.0, float(duration_sec or 0)) / SECONDS_PER_SCENE_TARGET))


def illustratable_beat_words() -> int:
    """The most spoken words one beat may carry and still be fillable with distinct visuals.

    A beat becomes exactly one scene, and a scene is held together by its evidence states. Past
    MAX_STATES_PER_SCENE the states stop being distinct visible changes and the scene holds one
    picture instead -- which is the 45-second scene the delivered films kept producing.

    The SLOWEST measured rate, not the average. A scene written to 2.86 w/s and then read at 2.588
    overruns by 10%, and the overrun does not spread: it lands on whichever picture was already
    holding longest. Budgeting at the slow end costs a few words and removes that failure.
    """
    from longform_evidence import SLOWEST_MEASURED_WORDS_PER_SECOND
    return max(1, int(SECONDS_PER_SCENE_TARGET * SLOWEST_MEASURED_WORDS_PER_SECOND))


def beats_required_for_words(total_words: int) -> int:
    """How many beats a word budget needs so no single scene exceeds the illustratable cap."""
    return max(1, math.ceil(max(0, int(total_words or 0)) / illustratable_beat_words()))


def cadence_feasibility(beat_count: int, duration_sec: float, total_words: int) -> dict:
    """Can this many beats carry this runtime at target cadence? Answered BEFORE any image spend.

    Every number here already existed and nothing read them together. The result was that a run
    learned its cadence was impossible only from the rendered gate, after the images were bought:
    `long_visual_hold` on a 300s film built from 8 beats, about $5 in, when the arithmetic was
    decidable at plan time.

    A beat becomes one scene, a scene holds at most MAX_STATES_PER_SCENE distinct states, and each
    state should hold TARGET_VISUAL_STATE_SECONDS. So `beats x 7 x 2.75` is the longest runtime the
    plan can cut to cadence, and anything past it is a hold nobody can remove downstream.

    Reported, not enforced. Whether to shorten the film, demand more beats, or accept the holds is
    an editorial call, and the caller that has to make it is the only one that can. What this
    removes is the surprise.
    """
    from longform_evidence import (MAX_STATES_PER_SCENE, TARGET_VISUAL_STATE_SECONDS,
                                   cadence_feasible_seconds)
    beats = max(0, int(beat_count or 0))
    requested = max(0.0, float(duration_sec or 0))
    feasible = cadence_feasible_seconds(beats)
    needed = beats_required_for_words(total_words)
    return {
        "beat_count": beats,
        "requested_seconds": round(requested, 1),
        "cadence_feasible_seconds": round(feasible, 1),
        "shortfall_seconds": round(max(0.0, requested - feasible), 1),
        "beats_needed_for_requested_runtime": max(
            beats, math.ceil(requested / (MAX_STATES_PER_SCENE * TARGET_VISUAL_STATE_SECONDS))),
        "beats_needed_for_word_budget": needed,
        "states_needed": math.ceil(requested / TARGET_VISUAL_STATE_SECONDS) if requested else 0,
        "states_available": beats * MAX_STATES_PER_SCENE,
        "feasible": feasible + 1e-9 >= requested,
    }


def research_claim_target(duration_sec: float) -> tuple[int, int]:
    """The (low, high) claim request for this runtime.

    Returns (22, 28) at 90s -- exactly the hand-tuned pair it replaces, because the floor binds
    there -- and scales above it: (27, 33) at 180s, (39, 45) at 300s.

    Research is the cheap end of this pipeline. The recorded 252.5s film spent $3.59, of which
    research was $0.0096; asking for twice the claims is the least expensive intervention
    available and it is the only one at the top of the chain.
    """
    needed = math.ceil(events_for_runtime(duration_sec) * CLAIMS_PER_EVENT)
    requested = math.ceil(needed / VERIFIED_CLAIM_YIELD)
    low = max(MIN_CLAIM_REQUEST, requested)
    return low, low + 6


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


def _claim_contradicts_itself(claim: dict) -> str:
    """A claim whose own flags cannot both be true, named by the rule it breaks.

    `material: true` with `allowed_exaggeration: true` says "this is a load-bearing scientific
    claim" and "this may overstate" at once. validate_research_dossier rejects it -- correctly --
    but rejected the WHOLE DOSSIER for it, and the claim is one self-contradictory row the writer
    was never going to be allowed to use.

    Measured: one such claim out of fifty killed a 300s run after the research was paid for. It
    gets likelier as the claim target scales -- one bad row in 22 is unlucky, one in 53 is
    ordinary -- so the failure mode arrived with the larger ask rather than existing before it.
    """
    if claim.get("material", True) and claim.get("allowed_exaggeration") is True:
        return "material_claim_permits_exaggeration"
    return ""


def quarantine_contradicted_claims(dossier: dict) -> dict:
    """Keep directly contradicted candidates in audit data but out of writing context.

    Two kinds of contradiction, both quarantined rather than fatal: a support quote that refutes
    its own claim, and a claim whose flags contradict each other. Neither can license narration, so
    dropping one costs a fact; failing the dossier costs the run and every claim in it.

    THE GATE IS NOT WEAKENED. validate_research_dossier still rejects `material_exaggeration` -- it
    simply no longer sees a row that was removed for exactly that reason. Everything downstream is
    unchanged, including the count-based gates that decide whether enough evidence survived, so a
    dossier gutted by quarantine still fails on the numbers.
    """
    result = copy.deepcopy(dossier)
    retained, excluded = [], list(result.get("excluded_claims") or [])
    contradicted = 0
    for claim in result.get("claims") or []:
        self_contradiction = _claim_contradicts_itself(claim)
        if _support_contradicts_claim(
                _text(claim.get("claim")), _text(claim.get("support_quote"))):
            excluded.append({"claim": claim, "reason": "support_contradicts_claim"})
            contradicted += 1
        elif self_contradiction:
            excluded.append({"claim": claim, "reason": self_contradiction})
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
        # A page nobody could open is a THIRD state, and conflating it with "the page does not say
        # this" cost this lane its best sources. nma.gov.au, dcceew.gov.au, wiley and britannica all
        # return 403 or refuse the connection to any non-browser client; measured on one topic, 13
        # of 16 rejected claims were transport failures, and they were the spine of the story.
        #
        # Such a claim is carried, not promoted. It is exempt from the excerpt check ONLY because
        # the check asks a question that cannot be answered for it — nobody, provider or client,
        # read text at that URL. Every other guard still applies: the URL must still appear in the
        # provider's own citations (`unverified_source` above), the domain must still not be weak,
        # the quote must still exist, and negation must still agree. The exemption is granted by an
        # explicit provenance tag that only `_verify_claims_against_sources` sets, never by an
        # absent field, so a claim cannot acquire it by omission.
        attested_unfetchable = (
            _text(claim.get("support_provenance")) == "provider_attested_unfetchable")
        if not support_quote:
            errors.append(_issue(
                "missing_support_quote", "The claim has no exact provider-observed support excerpt.",
                claim_id=claim_id))
        elif attested_unfetchable:
            pass
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
        # The research prompt's comparison label identifies a case, not the assertion's
        # geographic reach. The cane-toad canary returned "COMPARABLE CASE (worldwide):"
        # before a claim explicitly limited to the American West. Check the assertion
        # after that complete label; genuine global wording in the body still fails.
        scoped_assertion = re.sub(
            r"^\s*COMPARABLE CASE\s*\([^\n)]+\)\s*:\s*", "", claim_text,
            count=1, flags=re.I)
        if scope in {"local", "regional", "site-specific", "single site"} and _GLOBAL_WORDS.search(scoped_assertion):
            errors.append(_issue("scope_inflation", "A local or regional source is stated as a global claim.", claim_id=claim_id))
        if claim.get("material", True) and claim.get("allowed_exaggeration") is True:
            errors.append(_issue("material_exaggeration", "A material scientific claim cannot permit exaggeration.", claim_id=claim_id))

    # The exemption above must not be able to carry a whole dossier. Zero is the only threshold
    # here that is not arbitrary: if NOT ONE claim survived with text somebody actually read at its
    # URL, this is a network outage wearing a ledger's clothes, and the exemption would launder it
    # into a sourced story. A partial outage is reported, not blocked — this build already fails
    # too much on uncalibrated thresholds, and picking a ratio out of the air would add another.
    attested_only = [claim for claim in claims if isinstance(claim, dict)
                     and _text(claim.get("support_provenance")) == "provider_attested_unfetchable"]
    if attested_only and len(attested_only) == len([c for c in claims if isinstance(c, dict)]):
        errors.append(_issue(
            "no_fetched_evidence",
            "Every claim rests on a source that could not be retrieved; nothing in this ledger "
            "was read at its cited URL."))

    blocking = [e for e in errors if e.get("severity") != "soft"]
    return {
        "version": 1,
        # A soft fidelity overshoot does not block. The judge flags any phrase it cannot derive
        # from the event, which over fifteen runs meant "the bees were in a landscape", "across
        # open ground", "a natural colony" (refused for implying the colony was not in a crate)
        # and "across the Southwest" for three named states. None of those can mislead anyone.
        # What CAN is an invented number, date, named person or place, so those stay blocking and
        # everything else is reported. Three rounds of narrowing the judge's prose produced a new
        # crop of over-reaches each time; the threshold was the thing that was wrong.
        "passed": not blocking,
        "soft_findings": [e for e in errors if e.get("severity") == "soft"],
        "claim_count": len(claims),
        "citation_count": len(citation_urls),
        "attested_unfetchable_count": len(attested_only),
        "errors": errors,
    }


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def is_legacy_scope_label_failure(message: str) -> bool:
    """Only the single research-scope error repaired by the comparison-label fix."""
    return bool(re.fullmatch(
        r"Research dossier failed before scripting \[\d+ quotable excerpts available; "
        r"scope_inflationx1\]: A local or regional source is stated as a global claim\.",
        _text(message)))


def scope_label_dossier_repaired(dossier: dict) -> bool:
    """Recheck saved evidence without editing its original failed validation report."""
    if not isinstance(dossier, dict):
        return False
    prior = dossier.get("validation") or {}
    errors = prior.get("errors") or []
    if prior.get("passed") is not False or len(errors) != 1:
        return False
    if not isinstance(errors[0], dict) or errors[0].get("code") != "scope_inflation":
        return False
    claim = next((item for item in dossier.get("claims") or []
                  if isinstance(item, dict)
                  and item.get("claim_id") == errors[0].get("claim_id")), {})
    label = re.match(r"^\s*COMPARABLE CASE\s*\(([^\n)]+)\)\s*:",
                     _text(claim.get("claim")), re.I)
    return bool(label and _GLOBAL_WORDS.search(label.group(1))
                and validate_research_dossier(dossier)["passed"])


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


def _claims_by_parallel_case(dossier: dict) -> dict:
    """Which claims belong to which comparison, read off the ledger's own convention.

    The research prompt asks for comparable cases and the model prefixes them
    "COMPARABLE CASE (Hanoi rats): ...". That is a convention rather than a field, so this is a
    best-effort read: when no prefix is present the mapping is empty and the two parallel-case
    invariants simply do not fire. Better an invariant that abstains than one keyed on a heuristic
    that quietly mis-attributes evidence.
    """
    out: dict[str, list] = {}
    for claim in (dossier or {}).get("claims") or []:
        if not isinstance(claim, dict):
            continue
        declared = _text(claim.get("parallel_case_id"))
        if not declared:
            match = re.match(r"\s*COMPARABLE CASE\s*\(([^)]+)\)", _text(claim.get("claim")), re.I)
            declared = re.sub(r"[^a-z0-9]+", "_", match.group(1).lower()).strip("_") if match else ""
        if declared:
            out.setdefault(declared, []).append(_text(claim.get("claim_id")))
    return out


def validate_story_fact_model(script: dict, dossier: dict, *, judge=None, cache=None,
                              cost_sink: list | None = None) -> dict:
    """The cascade, in the shape `validate_claim_joins` callers already expect.

    Structure free, then evidence entailment, then narration fidelity — each seeing only what
    survived. Returns `passed` and `errors[].message` like its predecessor, so nothing downstream
    has to change to stop trusting word overlap.
    """
    import story_fact_model as sfm

    scenes = script.get("scenes") or []
    # THE HOOK IS NOT AN ASSERTION ABOUT BEAT ONE.
    #
    # finalize_narration prepends the spoken hook to the first scene, so the fidelity boundary was
    # measuring a promise about the WHOLE video against the single event that scene happens to
    # carry. Measured on the Hanoi render: "French officials paid a bounty for every dead rat, then
    # watched Hanoi breed more rats" came back `unsupported` against an event about sewers. Both
    # halves of that sentence are sourced -- the bounty and the breeding are separate verified
    # claims -- and neither is in the beat it was glued to. A true, cited hook was being reported
    # as an unsupported claim, which is the kind of false failure that teaches people to disable a
    # gate.
    #
    # So the hook is lifted out and judged against the story it promises: the union of the events
    # the spine actually establishes. It may say anything those events support, and nothing more.
    hook = _text(script.get("hook"))
    beats = [dict(scene, beat_id=_text(scene.get("beat_id")) or _text(scene.get("scene_id")) or f"scene_{index:03d}",
                  role=_text(scene.get("causal_role")) or _text(scene.get("story_role")))
             for index, scene in enumerate(scenes, 1)]
    if hook and beats:
        lead = _text(beats[0].get("narration"))
        if lead.casefold().startswith(hook.casefold()):
            # Strip the separator too. A hook already ending in "?" leaves ". Explained like you
            # are five..." behind, and a narration opening on a bare full stop is both a worse
            # sentence for the judge to read and a worse one for the narrator to say.
            beats[0] = dict(beats[0], narration=lead[len(hook):].lstrip(" .,;:—-").strip())
    # THE COLD OPEN IS NOT AN ASSERTION ABOUT BEAT ONE EITHER. It is the aftermath sentence
    # spoken after the hook (2026-10-02), cited to its own claims; judged against beat one's
    # setup event it was refused on the first killer bees resume ("an escaped swarm ... a
    # beekeeper backed away" against "European bees were introduced in the 1600s"). Lifted out
    # here and judged below against the claims it cites.
    cold_open = _text(script.get("_cold_open")).strip()
    cold_spoken = (cold_open.rstrip(".!?") + ".") if cold_open else ""
    if cold_spoken:
        cold_spoken = cold_spoken[0].upper() + cold_spoken[1:]
    if cold_spoken and beats:
        lead = _text(beats[0].get("narration"))
        if lead.casefold().startswith(cold_spoken.casefold()):
            beats[0] = dict(beats[0], narration=lead[len(cold_spoken):].lstrip(" .,;:—-").strip())
    # A QUESTION IN THE OPENING IS A PROMISE, NOT AN ASSERTION ABOUT BEAT ONE. A question-first
    # opening ends on the problem the video resolves ("But if the chick hatches before she
    # returns, how does a father who hasn't been fishing feed it?"), which is answered by later
    # beats. Judged against beat one alone it was refused every time (job 2e2c7498). Questions
    # in the opening scene are lifted out and judged with the hook against the whole story.
    #
    # NOT nested under the cold open. Adding the cold-open lift above put this inside its guard
    # (2026-10-02), so a film without a cold open -- every film written before the contract, and
    # the penguin fixture -- silently stopped lifting its opening questions and judged them
    # against beat one again, which is the exact failure this block exists to prevent.
    if beats:
        opening_sentences = [s for s in re.split(r"(?<=[.!?])\s+", _text(beats[0].get("narration")))
                             if s]
        questions = [s for s in opening_sentences if s.rstrip().endswith("?")]
        if questions:
            beats[0] = dict(beats[0], narration=" ".join(
                s for s in opening_sentences if not s.rstrip().endswith("?")))
            hook = " ".join([hook] + questions).strip()
    # The engine travels with the script, and it has to reach the cascade here as well as at the
    # spine gate. Without it this path fell back to backfiring_solution's contract and raised
    # CLAIM_KIND_MISMATCH on a removed_keystone mechanism citing a context claim -- which is what
    # that engine's mechanism IS. Worse, the code is not in the repairable set, so the whole claim
    # repair bailed and seven ordinary narration overshoots went unrepaired behind it.
    report = sfm.validate_cascade(
        beats, _claim_index(dossier), _claims_by_parallel_case(dossier),
        judge=judge, cache=cache, cost_sink=cost_sink,
        engine_id=_text(script.get("_story_engine")))

    relationships = sfm._validate_relationships(beats, report, judge=judge,
                                                cache=cache, cost_sink=cost_sink)

    errors = []
    for row in relationships:
        if not row["passed"]:
            errors.append({"code": "RELATIONSHIP_NOT_ENTAILED", "scene": row["beat_id"],
                           "message": row.get("reason", "unsupported derived relationship"),
                           "retryable": row.get("verdict") in ("unavailable", "invalid_response")})
    for issue in report["structural"]:
        errors.append({"code": issue["code"], "scene": issue.get("beat_id"),
                       "message": issue["message"]})
    for row in report["evidence"]:
        errors.append({"code": "EVENT_NOT_ENTAILED", "scene": row["beat_id"],
                       "message": f"{row['beat_id']}: the cited claims do not support the event "
                                  f"({row['verdict']}). " + (row.get("reason") or ""),
                       "supported_core": row.get("supported_core"),
                       "unsupported_details": row.get("unsupported_details")})
    for row in report["fidelity"]:
        errors.append({"code": "NARRATION_EXCEEDS_EVENT", "scene": row["beat_id"],
                       "severity": fidelity_severity(row.get("unsupported_details") or [],
                                                     _known_evidence_text(dossier),
                                                     row.get("verdict") or ""),
                       "message": f"{row['beat_id']}: the narration asserts more than its event "
                                  f"({row['verdict']}): "
                                  + ", ".join(row.get("unsupported_details") or []),
                       "supported_core": row.get("supported_core"),
                       "unsupported_details": row.get("unsupported_details")})
    if hook:
        import claim_entailment as ce
        import story_fact_model as _sfm
        # The ceiling is the events AND the claims behind them. The events deliberately state the
        # PROXY -- "the reward was paid for a severed rat tail" -- while the story a viewer is
        # being promised starts with the announcement, "a bounty on every dead rat", which is a
        # separate verified claim. Judged against the events alone, a hook saying officials "paid
        # residents for rats" was flagged for implying whole rats, and the judge's own supported
        # core said the same thing back. The hook promises the story; the story starts with the
        # announcement, so the announcement belongs in what the hook may draw on.
        #
        # Still bounded by the spine: only claims cited by events that PASSED, so nothing the
        # evidence boundary rejected can raise the ceiling.
        index = _claim_index(dossier)
        supported = [beat for beat in beats
                     if _sfm.event_of(beat)["text"]
                     and _text(beat.get("beat_id")) not in
                     {row["beat_id"] for row in report["evidence"]}]
        cited = []
        for beat in supported:
            for ref in _sfm.event_of(beat)["claim_refs"]:
                claim = _text((index.get(ref) or {}).get("claim"))
                if claim and claim not in cited:
                    cited.append(claim)
        story = " ".join([_sfm.event_of(beat)["text"] for beat in supported] + cited)
        if not story:
            # Nothing survived, so there is no ceiling to measure against. Reported as the hook
            # exceeding the story rather than skipped: a promise with no supported events behind
            # it is the strongest version of this failure, not an exemption from it.
            errors.append({"code": "HOOK_EXCEEDS_STORY", "scene": "hook",
                           "message": "no event survived the evidence boundary, so nothing "
                                      "supports the hook's promise"})
            verdict = None
        else:
            # THE HOOK ADDRESSES THE VIEWER, and that address is rhetoric, not history. The
            # opening contract requires a literal "you" or "your" -- it is the single device the
            # corpus never omits and our films never had -- and the ledger was refusing exactly
            # that: "Your honey jar could trace back to Warwick Kerr's African bees" was flagged
            # as an unsupported claim because no document records the viewer's honey jar. Two
            # requirements in one pipeline cannot disagree about the same sentence; the cold open
            # already carries this kind of ceiling, and the hook now does too. Its FACTS are
            # still bound: a name, a number, a date or a place in the hook must be supported.
            hook_ceiling = (story + "\n\nThis sentence is the film's FIRST LINE, spoken TO THE "
                            "VIEWER. Second-person framing is a rhetorical address, not a factual "
                            "assertion: 'your kitchen', 'your honey jar', 'your hive', 'you are "
                            "standing there' are never flagged, and neither is a hypothetical "
                            "('could', 'might') built on one. Flag ONLY an invented actor, an "
                            "invented action, a number, a date or a named place.")
            verdict = ce.narration_fidelity(hook_ceiling, hook, judge=judge, cache=cache,
                                            cost_sink=cost_sink)
        if verdict is None:
            pass
        elif ce.is_retryable(verdict):
            errors.append({"code": "ENTAILMENT_UNAVAILABLE", "scene": "hook",
                           "message": f"hook: {verdict.get('reason') or verdict['verdict']}",
                           "retryable": True})
        elif not verdict["passed"]:
            errors.append({"code": "HOOK_EXCEEDS_STORY", "scene": "hook",
                           # Scored like every other overshoot. Without a severity these blocked
                           # unconditionally, so a cold open whose SOLE objection was the word
                           # "Brazilian" -- on a film about Brazil -- killed the run, while six
                           # genuinely soft findings beside it were correctly waved through.
                           "severity": fidelity_severity(
                               verdict.get("unsupported_details") or [],
                               _known_evidence_text(dossier), verdict.get("verdict") or ""),
                           "message": "the hook promises more than the supported events deliver ("
                                      f"{verdict['verdict']}): "
                                      + ", ".join(verdict.get("unsupported_details") or []),
                           "supported_core": verdict.get("supported_core"),
                           "unsupported_details": verdict.get("unsupported_details")})

    if cold_open:
        import claim_entailment as ce
        index = _claim_index(dossier)
        cited = [_text((index.get(ref) or {}).get("claim"))
                 for ref in (script.get("_cold_open_claim_refs") or [])]
        cited = [c for c in cited if c]
        if not cited:
            errors.append({"code": "COLD_OPEN_EXCEEDS_CLAIM", "scene": "cold_open",
                           "message": "the cold open cites no claim from the ledger"})
        else:
            # The cold open is an IMAGE DESCRIPTION by contract -- it exists to say what the
            # first frame shows -- so its visual staging is not a historical assertion. It was
            # refused for "the swarm is dark" and "the setting is a grove" (2026-10-05). What it
            # still may not do is invent an ACTOR or an ACTION: "a beekeeper backs away" is a
            # person doing a thing, and that is a claim.
            cold_ceiling = ("\n".join(cited) + "\nThis sentence describes the film's FIRST IMAGE. "
                            "Colour, light, weather, vegetation and framing are staging, not "
                            "history: never flag them. Flag only an invented actor, an invented "
                            "action, a number, a date or a named place.")
            verdict = ce.narration_fidelity(cold_ceiling, cold_open, judge=judge, cache=cache,
                                            cost_sink=cost_sink)
            if ce.is_retryable(verdict):
                errors.append({"code": "ENTAILMENT_UNAVAILABLE", "scene": "cold_open",
                               "message": f"cold open: {verdict.get('reason') or verdict['verdict']}",
                               "retryable": True})
            elif not verdict["passed"]:
                errors.append({"code": "COLD_OPEN_EXCEEDS_CLAIM", "scene": "cold_open",
                               "severity": fidelity_severity(
                                   verdict.get("unsupported_details") or [],
                                   _known_evidence_text(dossier), verdict.get("verdict") or ""),
                               "message": "the cold open shows more than its cited claims support ("
                                          f"{verdict['verdict']}): "
                                          + ", ".join(verdict.get("unsupported_details") or []),
                               "supported_core": verdict.get("supported_core"),
                               "unsupported_details": verdict.get("unsupported_details")})

    # An outage is not a content failure, but it is not a pass either. It blocks and says why.
    for row in report["unavailable"]:
        errors.append({"code": "ENTAILMENT_UNAVAILABLE", "scene": row["beat_id"],
                       "message": f"{row['beat_id']}: {row['stage']} entailment could not be "
                                  f"judged — {row.get('reason')}", "retryable": True})
    # SOFT OVERSHOOT DOES NOT BLOCK. `report["passed"]` is False whenever the cascade recorded
    # any fidelity row, so filtering `errors` alone never reached the decision -- which is why
    # fifteen runs still died after the severity classifier landed. The verdict is rebuilt here
    # from the parts: structure, evidence and relationships still block absolutely, and of the
    # fidelity rows only the MATERIAL ones do (a number, a date, a named person or place, an
    # invented actor). Everything else is carried in soft_findings and reported.
    soft_fidelity, material_fidelity = [], []
    for row in report["fidelity"]:
        bucket = (soft_fidelity
                  if fidelity_severity(row.get("unsupported_details") or [],
                                       _known_evidence_text(dossier),
                                       row.get("verdict") or "") == "soft"
                  else material_fidelity)
        bucket.append(row)
    blocking_errors = [e for e in errors
                       if not e.get("retryable") and e.get("severity") != "soft"]
    return {
        "version": 2,
        "passed": (report["structure_status"] != sfm.STRUCTURE_FAIL
                   and not report["structural"] and not report["evidence"]
                   and not material_fidelity
                   and all(r["passed"] for r in relationships)
                   and not blocking_errors),
        "soft_findings": [{"scene": r.get("beat_id"),
                           "details": r.get("unsupported_details") or []} for r in soft_fidelity],
        "structure_status": report["structure_status"],
        "claim_count": len(_claim_index(dossier)),
        "errors": errors,
        "indeterminate_kinds": report["indeterminate_kinds"],
        "skipped_for_structure": report["skipped_for_structure"],
        "retryable": bool(report["unavailable"]) or any(e.get("retryable") for e in errors),
    }


def script_has_events(script: dict) -> bool:
    """Does this script carry the fact model, or is it an older one bound phrase-by-phrase?"""
    for scene in (script or {}).get("scenes") or []:
        event = scene.get("event")
        if isinstance(event, dict) and _text(event.get("text")):
            return True
        if isinstance(event, str) and _text(event):
            return True
    return False


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


_ACTOR_NOUN = re.compile(
    r"\b(farmer|worker|hunter|beekeeper|official|scientist|researcher|rancher|trapper|settler|"
    r"keeper|breeder|geneticist|entomologist|man|woman|crowd|people|villager|child)s?\b", re.I)


def _known_evidence_text(dossier: dict) -> str:
    """Everything the evidence actually says, as one lowercase blob, cached on the dossier.

    Used to tell an invented name from the film's own subject.
    """
    if not isinstance(dossier, dict):
        return ""
    cached = dossier.get("_known_text")
    if isinstance(cached, str):
        return cached
    parts = []
    for claim in (dossier.get("claims") or []):
        if isinstance(claim, dict):
            parts.append(_text(claim.get("claim")))
            parts.append(_text(claim.get("support_quote")))
    blob = " ".join(parts).casefold()
    try:
        dossier["_known_text"] = blob
    except Exception:
        pass
    return blob


_MATERIAL_DETAIL = re.compile(
    r"\d+"                                  # a count or a year, whole so it can be matched in evidence
    # Spelled-out numbers and quantities. "twenty-six swarms escaped" is the measured case: the
    # evidence says twenty-six QUEENS escaped with swarms of European workers, and the wrong
    # noun rode the number through five runs. A number in words is still a number.
    r"|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|"
    r"fifty|sixty|seventy|eighty|ninety|hundreds?|thousands?|millions?|billions?|dozens?|"
    r"scores?|half|double|triple)\b"
    r"|\b(?:[A-Z][a-z]{2,})\b"              # a proper noun: a person or a place
    r"|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|"
    r"forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion|dozens?|"
    r"decades?|centur(?:y|ies))\b"        # an invented quantity or duration, spelled out
    r"|\b(?:farmer|worker|hunter|beekeeper|official|scientist|researcher|rancher|trapper|"
    r"settler|keeper|breeder|geneticist|entomologist)s?\b",  # an invented actor
    re.I if False else 0)


# Ordinary English carries no claim, so it cannot be an invented action. Only consulted when an
# actor the evidence names is already established -- a narrower question than "is this word in
# the dossier", which refused "Brazilian beekeepers LEARNED what the escaped queens COULD do".
_ORDINARY_ENGLISH = frozenset("""
about above after again against along among around because become became before began begin
being below between beyond could would should might must still their there these those through
under until where which while whose after where learned learning seemed seeming started starting
continued continuing moved moving turned turning looked looking found finding known taken given
going coming every other another something nothing anything everything people place thing things
time times years year later early often never always really simply almost nearly enough across
within without toward towards itself himself herself themselves ourselves yourself first second
third final later little large small great whole close closer early earlier quickly slowly
""".split())


_NUMBER_WORD = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
_SPELLED = re.compile(
    r"\b(twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)[\s-](one|two|three|four|five|six|"
    r"seven|eight|nine)\b|\b(" + "|".join(_NUMBER_WORD) + r")\b", re.I)


def _digits_for_words(text: str) -> str:
    """Spell numbers the way the evidence does, so a figure it states is not called invented.

    The dossier says "26" and the narration says "Twenty-six", and the exemption is a substring
    test -- so the film's own headline number read as a fabrication and blocked the run. Both
    forms mean the same fact; only the spelling differs.
    """
    def swap(match):
        tens, units, single = match.group(1), match.group(2), match.group(3)
        if tens and units:
            return str(_NUMBER_WORD[tens.lower()] + _NUMBER_WORD[units.lower()])
        return str(_NUMBER_WORD[single.lower()]) if single else match.group(0)

    return _SPELLED.sub(swap, text or "")


def fidelity_severity(details: list, known_text: str = "", verdict: str = "") -> str:
    """Is this narration overshoot material enough to stop a render?

    MATERIAL: the detail carries a number, a date, a named person or place, or an actor doing
    something. Those are the things a viewer could repeat as fact and be wrong about, and they
    are exactly what the repair prompt has always told the writer not to invent.

    SOFT: everything else -- setting, paraphrase, the ordinary word for a state the event already
    asserts. Reported, never blocking.

    Only `partially_entailed` can ever be soft. A judge that says `unsupported` has found no
    factual core at all, and one that lists nothing has told us nothing to weigh -- both fail
    closed. Without that, "Hundreds of secret overnight rat farms appeared" passed the gate
    because the judge rejected it without itemising why, which is a fail-open hole in the one
    boundary that stops invented narration.
    """
    if verdict and verdict != "partially_entailed":
        return "material"
    # A NAME THE EVIDENCE ALREADY CONTAINS IS NOT AN INVENTED NAME. Without this the film's own
    # subject trips the rule: "Brazil's European bees" and "The forest gained African honey bee
    # colonies" were both classed material because "Brazil" and "African" are capitalised, while
    # every claim in the dossier says them. Only a name the evidence does NOT carry can mislead.
    # BOTH SIDES SPELLED THE SAME WAY. The evidence writes "26" in one dossier and "twenty-six"
    # in another, and the narration picks whichever it likes; normalising only one side simply
    # moves the false positive to the other dossier.
    known = _digits_for_words((known_text or "").casefold())
    for detail in details or []:
        text = detail if isinstance(detail, str) else str(detail)
        # THE JUDGE'S OWN PROSE IS NOT THE NARRATION'S CLAIM. Findings arrive phrased as
        # commentary -- "Calling it a defensive response", "Saying the queens escaped rather
        # than..." -- and the capitalised framing verb was being read as a proper noun, so a
        # dispute about WORD CHOICE blocked renders as if a name had been invented.
        # A complaint about what something is CALLED is soft: the viewer is not misled about a
        # fact by "defensive response" instead of "defensive behaviour".
        if re.match(r"^(calling|saying|describing|characteri[sz]ing|labell?ing|terming|"
                    r"referring to|treating|framing|implying|suggesting|asserting that it is)\b",
                    text.strip(), re.I):
            continue
        # SENTENCE CASE IS NOT A PROPER NOUN. Stripping a fixed list of leading articles left
        # every other opening word capitalised, so "Across open ground", "Dividing into new
        # colonies" and "More occupied branches appearing" were all read as names and blocked
        # renders. A finding always starts capitalised; that position carries no information.
        # A real name survives because a name is rarely alone -- "Warwick Kerr" keeps its Kerr --
        # and a lone sentence-initial place is covered by the evidence exemption below.
        stripped = text.strip()
        # ...but only when the SECOND word is not capitalised too. "Warwick Kerr" is a real name
        # and must keep its Warwick: the evidence carries "kerr" and not "warwick", so dropping
        # the first word's case let the exemption match Kerr and wave the invented first name
        # through. Two capitals in a row is a name; one at the start is just a sentence.
        probe = stripped
        if stripped and not re.match(r"^\S+\s+[A-Z]", stripped):
            probe = stripped[0].lower() + stripped[1:]
        # "Twenty-six" and "26" are the same figure; the evidence writes one of them.
        probe = _digits_for_words(probe)
        # AN ACTOR THE EVIDENCE PUTS THERE IS NOT AN INVENTED ACTOR. This rule used to be
        # absolute -- a person doing a thing is a claim, whatever the dossier says -- and that is
        # right for "a beekeeper backs away" invented out of nothing. It is wrong for the bee
        # dossier's own sentence: "in October 1957, a local beekeeper noticed the queen excluders
        # and removed them". That is the documented turning point of the film, the hook rules
        # tell the planner to open on exactly that gesture, and this classifier was refusing
        # every script that obeyed them. Two requirements cannot disagree about one sentence.
        #
        # So the actor gets the same exemption names and numbers get, and no more: an actor the
        # evidence does not mention is still material, and whatever that actor is said to DO is
        # still measured by the rules below and by the judge that produced this finding.
        actor = _ACTOR_NOUN.search(probe)
        if actor:
            noun = actor.group(0).strip().casefold().rstrip("s")
            if not (known and noun in known):
                return "material"
            # The actor is documented, so what remains is whether the ACTION is. Every
            # substantial word has to be one the evidence already uses: "a local beekeeper
            # removed the queen excluders" is the dossier's own sentence, while "a beekeeper
            # backs away through the grove" borrows a real person for an invented moment.
            for word in re.findall(r"[a-z]{5,}", probe.casefold()):
                if word == noun or word in known or word in _ORDINARY_ENGLISH:
                    continue
                if not any(word[:n] in known for n in range(len(word), 4, -1)):
                    return "material"
        for match in _MATERIAL_DETAIL.finditer(probe):
            token = match.group(0).strip()
            # A figure the evidence states is not invented either: "October 1957" and "26
            # queens" are both in the dossier verbatim, and were blocking because the match was
            # a single digit too short to look up.
            if known and len(token) >= 2 and token.casefold() in known:
                continue              # the evidence says it; it is not an invention
            # A MORPHOLOGICAL VARIANT OF A NAME THE EVIDENCE CARRIES IS NOT A NEW NAME. The
            # exemption was a literal substring test, so a dossier full of "Brazil" and "African"
            # still classed "Brazilian" and "Africanized" as invented, and those two words
            # blocked run after run on a film whose subject is Africanized bees in Brazil.
            # WORDS ONLY: a token with a digit in it must match exactly, because "1957" and
            # "1958" are different facts and no amount of shared prefix makes them the same one.
            folded = token.casefold()
            if (known and len(folded) >= 5 and folded.isalpha()
                    and any(folded[:n] in known for n in range(len(folded), 4, -1))):
                continue
            return "material"
    return "soft"


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


# --- dossier scope ------------------------------------------------------------------------------
# A question can quietly ask for two stories, and research will answer both. "Why don't Americans
# eat hippo meat?" returned 21 verified claims -- MORE than the Hanoi dossier that works -- split
# between a 1910 congressional episode and modern African conservation. The planner then built one
# spine from both: `world_without_it` came back as a 2006 IUCN listing and `outcome_state` as Congo
# poaching figures, neither of which is about the American bill that the story is supposedly about.
#
# Nothing noticed. The dossier validated, the beat sheet was paid for, and the spine failed three
# runs later for reasons that took a $2 render each to read. This is decidable by looking at the
# dates, so it is decided here, before anything downstream is bought.
ERA_GAP_YEARS = 50


def era_split(dossier: dict) -> dict:
    """Do the verified claims describe one period, or two separated by a lifetime?

    Reports; never refuses. A story CAN legitimately span eras -- a 1910 plan and the world it
    failed to produce -- so this names what it found and leaves the judgement to the spine gate,
    which reasons about the events rather than counting years. Blocking on a date histogram is
    exactly the kind of confident heuristic that has been wrong twice already here.

    Two kinds of claim are excluded, and both matter. A comparable case is SUPPOSED to come from
    another time and place, so counting it would flag every story that generalises. And a claim
    ABOUT THE SCHOLARSHIP carries the publication's date, not the episode's: the Hanoi dossier --
    the one that works -- cites Vann's 2003 history of a 1902 bounty, and reading that as a
    century of drift flagged the story this check exists to leave alone.
    """
    import story_fact_model as _sfm

    # The causal lane can reach here with research off, and a check that crashes on the absence of
    # a dossier is a check that turns "no research" into a failed run.
    if not isinstance(dossier, dict):
        return {"spans_eras": False, "clusters": [], "dated": 0, "undated": 0, "largest": None}
    dated: list[tuple[int, str]] = []
    for ref, claim in (_claim_index(dossier) or {}).items():
        text = " ".join(_text(claim.get(field)) for field in ("claim", "support_quote"))
        if _sfm._PARALLEL_MARKER.search(text) or _sfm._META_EVIDENCE.search(text):
            continue
        import re as _re
        years = [int(y) for y in _re.findall(r"\b(1[5-9]\d\d|20\d\d)\b", text)]
        if years:
            dated.append((min(years), ref))
    dated.sort()
    if len(dated) < 2:
        return {"spans_eras": False, "clusters": [], "dated": len(dated),
                "undated": len(_claim_index(dossier) or {}) - len(dated)}

    clusters: list[list[tuple[int, str]]] = [[dated[0]]]
    for entry in dated[1:]:
        (clusters[-1] if entry[0] - clusters[-1][-1][0] <= ERA_GAP_YEARS
         else clusters.append([]) or clusters[-1]).append(entry)
    described = [{"from": group[0][0], "to": group[-1][0],
                  "claim_ids": [ref for _, ref in group]} for group in clusters]
    return {"spans_eras": len(clusters) > 1, "clusters": described, "dated": len(dated),
            "undated": len(_claim_index(dossier) or {}) - len(dated),
            "largest": max(described, key=lambda c: len(c["claim_ids"])) if described else None}


def era_split_report(split: dict) -> str:
    if not split.get("spans_eras"):
        return ""
    periods = ", ".join(
        f"{c['from']}" + (f"-{c['to']}" if c["to"] != c["from"] else "")
        + f" ({len(c['claim_ids'])} claim{'s' if len(c['claim_ids']) != 1 else ''})"
        for c in split["clusters"])
    return (f"Dossier spans {len(split['clusters'])} periods more than {ERA_GAP_YEARS} years "
            f"apart: {periods}. {split['undated']} claims carry no date. A question that asks "
            "about a present-day absence AND a historical episode returns both, and one spine "
            "cannot be built from two stories — say which period the video is about.")
