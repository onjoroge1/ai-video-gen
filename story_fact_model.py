"""The factual layer between verified research and creative expression.

Narration used to be four things at once: the story, the evidence record, the source-binding key and
the instruction to the image model. Every pass that improved one damaged another — a fact-check
rewrite broke the claim bindings, a runtime refit broke the anchors, a hinge shortening dropped a
citation. And because the binding key WAS the prose, the sourcing check could only ask whether the
prose resembled the claim, which it answered by counting shared words. That rewarded narration
written in the ledger's vocabulary, which is where the lecture voice came from.

A beat now carries an EVENT: one plain factual statement, bound to the claims that support it. The
event is the canonical factual ceiling, and expression hangs off it:

    verified claims ──> EVENT ──┬──> narration   (creative prose)
                                └──> visual      (creative depiction)

Both branches may rephrase, dramatise and reorder freely. Neither may assert history the event does
not contain. Visual entailment is not judged here yet, but the ceiling is shared so it can be added
without moving anything: `visual_assertions_for` already collects the image side.

This module owns the DETERMINISTIC half — scope provenance and binding invariants that need no
model and cost nothing. `claim_entailment` owns the semantic half. Structure is checked first, so a
misplaced comparison or an unbound assertion fails before a single judge call is bought.
"""
from __future__ import annotations

import re
from typing import Any


SCHEMA_VERSION = "story_fact_model_v1"

PRIMARY_STORY = "primary_story"
PARALLEL_CASE = "parallel_case"
SCOPES = (PRIMARY_STORY, PARALLEL_CASE)

# The only role a comparison may occupy. An escalation is THIS story getting worse; a second country
# is a comparison, and a comparison offered before the first story resolves reads as the story
# changing subject. A measured draft put Hanoi in an escalation beat and every structural check
# passed, because a beat labelled escalation was present and in order.
COMPARISON_ROLE = "generalization"

# Narration that asserts nothing historical needs no event and no citation. Connectives, rhetorical
# questions and framing carry the story without carrying a claim, and demanding a binding for them
# produces the artificial citations that made every beat look sourced and none of them checkable.
# A hinge that announces a law instead of a turn. Deliberately narrow: explicit "this is an
# instance of a rule" phrasing, not any sentence containing an abstraction. "The reward depended on
# the dead body, not on any reduction of the wild population" is a turn and must not match.
_STATES_A_PRINCIPLE = re.compile(
    r"\b(demonstrat\w+|illustrat\w+|exemplif\w+|is an example of|is a case of|"
    r"shows that any|proves that any|known as \w+'s law|\w+'s law (?:holds|states)|"
    r"whenever (?:a|any) \w+|any \w+ is (?:only|always|by definition))\b", re.I)

_ASSERTION_SIGNALS = re.compile(
    r"\b(\d[\d,.]*|per cent|percent|%|million|thousand|hundreds?|dozens?|"
    r"in \d{3,4}|century|decade|years?|months?|weeks?|days?|overnight)\b", re.I)


# What KIND of thing a claim is, and which beats may cite it. A claim that explains WHY something
# happened does not evidence THAT it happened — and a measured sample bound one analytical claim
# ("the bounty rewarded the metric rather than the goal, and that gap is where the effect operates")
# to eight of ten beats, including the breeding, the release and the final outcome, none of which
# it states. The model was reading "explains the story" as "supports every event in the story".
#
# This is a cheap gate in front of the paid judge, not a replacement for it: it rejects bindings
# that are obviously the wrong shape before anyone pays to have their meaning weighed.
# INTRINSIC properties only: what kind of thing the claim is, independent of which story uses it.
#
# `parallel_case` was here and had to go. It is RELATIONAL -- it says whose story a claim belongs
# to, not what the claim is -- and mixing the two axes forced the classifier to choose between
# them. Measured on the golden control it labelled "COMPARABLE CASE (Hanoi rats): the community
# farmed rats, cut off their tails and released them" as `event`, which is correct, and scored as
# confidently wrong against a hand label of `parallel_case`, which was also correct. Two right
# answers to two different questions.
#
# The relational axis already exists and is better evidenced: `claims_by_case` maps each comparison
# to the claims that belong to it, and invariant 2 enforces it. Nothing was lost by deleting the
# redundant enum value except a classifier failure mode.
CLAIM_KINDS = ("event", "mechanism", "context", "outcome", "general_principle")
# Research owns this label and nothing downstream may rewrite it. Once a kind governs a cheap gate,
# a wrong label is a way to pass that gate: relabel "the bounty created a gap between metric and
# goal" as `event` and an escalation may cite it without complaint, even though it still does not
# entail that anyone bred a cobra. Boundary A catches that eventually — but the cheap layer must
# not become the thing a bad label games.
#
# `unknown` is therefore a first-class answer, and it SKIPS the compatibility check rather than
# guessing. A classifier that is unsure should say so, not pick whichever kind makes validation
# easiest.
UNKNOWN_KIND = "unknown"

# Structure has three outcomes, not two. An unknown or low-confidence kind must not read as a clean
# structural pass: the kind gate did not decide, it abstained, and the paid judge is now the only
# thing standing behind that binding. Collapsing "we checked and it is fine" into the same word as
# "we could not check" is how a classifier that quietly degrades makes CLAIM_KIND_MISMATCH vanish
# from the reports while the semantic layer silently carries more and more of the load.
STRUCTURE_PASS = "STRUCTURE_PASS"
STRUCTURE_PASS_WITH_UNKNOWN_KIND = "STRUCTURE_PASS_WITH_UNKNOWN_KIND"
STRUCTURE_FAIL = "STRUCTURE_FAIL"
# Below this, treat a stated kind as unknown. A label the classifier is unsure of is exactly the
# label that should not silently govern a gate.
MIN_KIND_CONFIDENCE = 0.6
# How far the chosen kind must beat its nearest alternative. Absolute confidence proved useless as
# an abstention signal: measured over two runs the classifier returned ZERO unknowns, with every
# confidence clustered between 0.65 and 0.85 and nothing below the 0.6 bar -- including on claims
# that were genuinely ambiguous and that it got wrong. It is not calibrated on "how sure am I",
# which is a hard question about itself.
#
# "Which of these two fits better, and by how much" is a comparative judgement about the material,
# and a much easier one. A claim whose top two kinds are neck and neck is exactly the claim that
# should abstain and let the paid judge decide.
MIN_KIND_MARGIN = 0.15


def resolved_claim_kind(claim: dict) -> tuple[str, str]:
    """The kind this claim may govern a gate with, and why it does or does not.

    Returns (kind, reason). `kind` is UNKNOWN_KIND whenever the classifier did not clearly decide,
    so callers never have to re-derive the abstention rules.
    """
    claim = claim if isinstance(claim, dict) else {}
    kind = _text(claim.get("claim_kind")).lower()
    if not kind:
        return UNKNOWN_KIND, "unlabelled"
    if kind == UNKNOWN_KIND:
        return UNKNOWN_KIND, "classifier_abstained"

    def _number(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    confidence = _number(claim.get("claim_kind_confidence"))
    if confidence is not None and confidence < MIN_KIND_CONFIDENCE:
        return UNKNOWN_KIND, "low_confidence"

    runner_up = _text(claim.get("runner_up_kind")).lower()
    runner_confidence = _number(claim.get("runner_up_confidence"))
    if (runner_up and runner_up not in ("", UNKNOWN_KIND) and confidence is not None
            and runner_confidence is not None
            and confidence - runner_confidence < MIN_KIND_MARGIN):
        return UNKNOWN_KIND, f"narrow_margin_over_{runner_up}"
    return kind, "decided"

_ROLE_ACCEPTS = {
    "setup": ("event", "context", "outcome"),
    "intervention": ("event", "context", "outcome"),
    "false_resolution": ("event", "context", "outcome"),
    "hinge": ("event", "context", "outcome", "mechanism"),
    "escalation": ("event", "context", "outcome"),
    "reversal": ("event", "context", "outcome"),
    "mechanism": ("mechanism", "general_principle"),
    # A comparison beat states what happened elsewhere, or the law it illustrates. That it is a
    # COMPARISON is carried by scope and claims_by_case, not by the claim's kind.
    "generalization": ("event", "outcome", "general_principle"),
    # The close is a rhetorical device built from the story, not a new historical assertion.
    "tool": (),
    "verdict": (),
}


def accepted_claim_kinds(role: str) -> tuple:
    """Claim kinds a beat in this role may cite. Empty means the beat should assert no history."""
    return _ROLE_ACCEPTS.get(_text(role).lower(), CLAIM_KINDS)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _issue(code: str, message: str, **fields) -> dict:
    return {"code": code, "message": message, **{k: v for k, v in fields.items() if v not in (None, "")}}


def scope_of(beat: dict) -> str:
    """A beat's declared provenance, defaulting to the primary story.

    Defaulting to primary_story rather than raising keeps an older script readable: a beat with no
    scope is a beat about the video's own subject, which is what every beat was before this field
    existed.
    """
    scope = _text((beat or {}).get("scope")).lower()
    return scope if scope in SCOPES else PRIMARY_STORY


def event_of(beat: dict) -> dict:
    """The beat's factual event as {text, claim_refs}, normalised.

    Accepts a bare string for `event` so a generator that writes the simple form still binds.
    """
    raw = (beat or {}).get("event")
    if isinstance(raw, str):
        return {"text": _text(raw), "claim_refs": []}
    raw = raw if isinstance(raw, dict) else {}
    refs = raw.get("claim_refs")
    refs = [_text(item) for item in refs if _text(item)] if isinstance(refs, list) else []
    return {"text": _text(raw.get("text")), "claim_refs": refs}


def asserts_history(text: str) -> bool:
    """Does this narration assert something historical, or is it discourse?

    Deliberately crude and deliberately narrow: it exists to decide whether an event is REQUIRED,
    not to judge the assertion. The semantic boundary does that. A false negative here costs a
    missing invariant; a false positive would demand citations for connectives, which is the
    artificial-binding problem this layer exists to end.
    """
    return bool(_ASSERTION_SIGNALS.search(_text(text)))


def visual_assertions_for(beat: dict) -> list[str]:
    """The image side of the ceiling, collected but not yet judged.

    Kept here so the third boundary (event -> visual) can be added without touching the schema. A
    supported event and faithful narration still permit "a vast underground breeding factory with
    hundreds of cages", which reintroduces invented history after the prose passed cleanly.
    """
    beat = beat or {}
    out = [_text(beat.get("visual")), _text(beat.get("image_prompt"))]
    for state in beat.get("visual_beats") or []:
        if isinstance(state, dict):
            out.append(_text(state.get("state_after")) or _text(state.get("visual")))
    return [item for item in out if item]


def indeterminate_kind_bindings(beats: list[dict], claims: dict | None = None) -> list[dict]:
    """Bindings the kind gate could not decide: unknown, unlabelled, or below MIN_KIND_CONFIDENCE.

    These are not failures and not passes. The gate abstained, so the paid entailment layer is the
    only thing standing behind them, and the report has to say so — otherwise a classifier that
    degrades over time makes CLAIM_KIND_MISMATCH disappear and looks like an improvement.
    """
    if claims is None:
        return []
    out = []
    for index, beat in enumerate(beats or []):
        beat = beat if isinstance(beat, dict) else {}
        beat_id = _text(beat.get("beat_id")) or f"beat_{index + 1:02d}"
        role = _text(beat.get("role") or beat.get("causal_role")).lower()
        if not role or not accepted_claim_kinds(role):
            continue
        for claim_id in event_of(beat)["claim_refs"]:
            claim = claims.get(claim_id) or {}
            kind, reason = resolved_claim_kind(claim)
            if kind == UNKNOWN_KIND:
                out.append({"beat_id": beat_id, "claim_id": claim_id,
                            "claim_kind": _text(claim.get("claim_kind")).lower() or UNKNOWN_KIND,
                            "claim_kind_confidence": claim.get("claim_kind_confidence"),
                            "runner_up_kind": _text(claim.get("runner_up_kind")).lower(),
                            "abstained_because": reason,
                            "kind_gate": "indeterminate",
                            "requires_semantic_validation": True})
    return out


def validate_structure(beats: list[dict], claims_by_case: dict | None = None,
                       claims: dict | None = None) -> list[dict]:
    """The invariants that need no model, run before any judge call is bought.

    1. parallel_case content cannot appear outside the generalization
    2. a primary_story event cannot source claims belonging exclusively to a parallel case
    3. narration that asserts history must have an event; discourse need not
    4. a beat may only cite claim KINDS its role can use
    5. one comparison per beat, and the close asserts no history

    `claims` maps claim_id -> claim record, used only for kind compatibility. Omit it and that
    check is skipped rather than guessed at.
    """
    issues: list[dict] = []
    case_only_claims = {}
    for case_id, claim_ids in (claims_by_case or {}).items():
        for claim_id in claim_ids or []:
            case_only_claims.setdefault(_text(claim_id), set()).add(_text(case_id))

    for index, beat in enumerate(beats or []):
        beat = beat if isinstance(beat, dict) else {}
        beat_id = _text(beat.get("beat_id")) or f"beat_{index + 1:02d}"
        role = _text(beat.get("role") or beat.get("causal_role")).lower()
        scope = scope_of(beat)
        event = event_of(beat)
        narration = _text(beat.get("narration"))

        # 1. A comparison may only occupy the generalization.
        if scope == PARALLEL_CASE and role and role != COMPARISON_ROLE:
            issues.append(_issue(
                "PARALLEL_CASE_OUT_OF_SCOPE",
                f"beat {beat_id} is declared {PARALLEL_CASE} but sits in the {role} role; a "
                f"comparison belongs in the {COMPARISON_ROLE}, after this story resolves",
                beat_id=beat_id, scope=scope, role=role))
        if scope == PARALLEL_CASE and not _text(beat.get("parallel_case_id")):
            issues.append(_issue(
                "PARALLEL_CASE_UNIDENTIFIED",
                f"beat {beat_id} is a {PARALLEL_CASE} with no parallel_case_id, so nothing "
                "downstream can tell which comparison it belongs to",
                beat_id=beat_id))

        # 2. The primary story may not quietly borrow a comparison's evidence.
        if scope == PRIMARY_STORY:
            for claim_id in event["claim_refs"]:
                owners = case_only_claims.get(claim_id)
                if owners:
                    issues.append(_issue(
                        "PRIMARY_SOURCED_FROM_PARALLEL_CASE",
                        f"beat {beat_id} tells the primary story but sources {claim_id}, which "
                        f"belongs to parallel case {', '.join(sorted(owners))}; evidence about "
                        "another case cannot support this one",
                        beat_id=beat_id, claim_id=claim_id))

        # 3. Historical assertion requires an event. Discourse does not.
        if asserts_history(narration) and not event["text"]:
            issues.append(_issue(
                "ASSERTION_WITHOUT_EVENT",
                f"beat {beat_id} narrates a historical specific with no event behind it; either "
                "give it an event bound to evidence or remove the specific",
                beat_id=beat_id))
        if event["text"] and not event["claim_refs"]:
            issues.append(_issue(
                "EVENT_WITHOUT_EVIDENCE",
                f"beat {beat_id} declares a factual event with no claim_refs",
                beat_id=beat_id))

        # 4. The claim must be the right KIND for this beat. A mechanism claim explains why
        #    something happened; it does not evidence that it happened.
        accepted = accepted_claim_kinds(role)
        if claims is not None and role:
            for claim_id in event["claim_refs"]:
                claim = claims.get(claim_id) or {}
                # No label, an explicit unknown, a doubted one, or one that barely beat its nearest
                # alternative: skip rather than enforce. The semantic boundary still has to agree,
                # so skipping loses a cheap rejection, not the contract.
                kind, _reason = resolved_claim_kind(claim)
                if kind == UNKNOWN_KIND:
                    continue
                if kind not in accepted:
                    issues.append(_issue(
                        "CLAIM_KIND_MISMATCH",
                        f"beat {beat_id} is a {role} beat citing {claim_id}, which is a {kind} "
                        f"claim; a {role} beat may cite "
                        + (", ".join(accepted) if accepted else "no factual claims at all"),
                        beat_id=beat_id, claim_id=claim_id))

        # 4b. A hinge may cite mechanism evidence, but it may not BE exposition. Allowing
        #     mechanism there lets the hinge name the flaw it just hit -- "the reward depended on
        #     the body, not on any fall in the wild population" -- and must not license "this
        #     demonstrates Goodhart's Law" as a beat.
        #
        #     This is a NARROW ANTI-PATTERN DETECTOR, not proof that the beat turns the story.
        #     It catches explicit "this is an instance of a rule" phrasing and nothing else -- a
        #     model can write "The lesson was suddenly obvious: incentives always beat intentions"
        #     and match none of it. Passing this proves only that the beat avoided the known
        #     wording. The real invariant is changes_state below: a hinge has to move the viewer's
        #     model of the situation, and a beat whose before and after are the same has not
        #     turned anything however it is worded.
        #
        #     Keyed on the event TEXT, not on which claim kinds it cites. A first version required
        #     the hinge to cite an event/context/outcome claim, and it rejected a perfectly good
        #     hinge whose only support was the analytical claim it was correctly naming.
        if role == "hinge" and event["text"] and _STATES_A_PRINCIPLE.search(event["text"]):
            issues.append(_issue(
                "HINGE_WITHOUT_TURN",
                f"beat {beat_id} is the hinge but its event states a general principle rather than "
                "a turn this story takes; name what the story just discovered, not the law it "
                "illustrates",
                beat_id=beat_id))

        # 4c. The stronger invariant: a hinge must CHANGE something. Wording rules catch a
        #     phrasing; this catches the beat that reads like a turn and moves nothing.
        if role == "hinge":
            transition = beat.get("changes_state")
            transition = transition if isinstance(transition, dict) else {}
            before, after = _text(transition.get("from")), _text(transition.get("to"))
            if before and after and before.casefold() == after.casefold():
                issues.append(_issue(
                    "HINGE_CHANGES_NOTHING",
                    f"beat {beat_id} is the hinge but its changes_state leaves the situation "
                    "exactly as it found it; the turn has to move the viewer's model, not restate "
                    "it",
                    beat_id=beat_id))

        # 5a. A role that asserts no history should not be carrying an event at all. The close is a
        #     rhetorical device built from the story, not a new historical assertion — a measured
        #     sample gave its tool beat an event about Goodhart's 1975 law and marked it
        #     primary_story, which is neither this story nor a fact the close needs.
        if role and not accepted and event["text"]:
            issues.append(_issue(
                "CLOSING_BEAT_ASSERTS_HISTORY",
                f"beat {beat_id} is a {role} beat carrying a factual event; the close is built "
                "from the story rather than adding to it. Move the assertion to a beat whose role "
                "can evidence it, or drop it and let the close be rhetoric",
                beat_id=beat_id, role=role))

        # 5b. One comparison per beat. A single event bundling two cases cannot be attributed,
        #     cited, illustrated or called back cleanly, and parallel_case_id can only name one of
        #     them. Splitting the beat is better than teaching the schema to hold a mess.
        if scope == PARALLEL_CASE:
            named = [case_id for case_id in (claims_by_case or {})
                     if _text(case_id) and _text(case_id) != _text(beat.get("parallel_case_id"))
                     and any(claim_id in (claims_by_case.get(case_id) or [])
                             for claim_id in event["claim_refs"])]
            if named:
                issues.append(_issue(
                    "MULTI_PARALLEL_CASE_EVENT",
                    f"beat {beat_id} is declared {beat.get('parallel_case_id')!r} but also sources "
                    f"{', '.join(sorted(named))}; one comparison per beat, so split it",
                    beat_id=beat_id))

    return issues


def validate_cascade(beats: list[dict], claims: dict | None = None,
                     claims_by_case: dict | None = None, *,
                     judge=None, cache: dict | None = None, cost_sink: list | None = None) -> dict:
    """Structure, then evidence, then fidelity — each stage seeing only what survived the last.

        1. schema, role, scope, kind, parallel-case integrity   free
        2. claims -> event entailment                           paid, cached
        3. event  -> narration fidelity                         paid, cached

    Nothing pays a judge to weigh a binding the type system has already rejected: there is no value
    in buying an opinion on whether a mechanism claim supports "residents bred cobras" once the
    cheap layer has said a mechanism claim cannot evidence an escalation at all. Likewise fidelity
    is not bought for an event whose own support failed — the ceiling has to exist before anything
    can be measured against it.

    A retryable verdict (provider unavailable, unreadable reply) stops the cascade for that beat
    rather than being reported as a content failure, and is never cached.
    """
    import claim_entailment as ce

    structural = validate_structure(beats, claims_by_case, claims)
    blocked = {issue.get("beat_id") for issue in structural if issue.get("beat_id")}
    indeterminate = indeterminate_kind_bindings(beats, claims)
    abstained = {row["beat_id"] for row in indeterminate}

    evidence, fidelity, skipped, unavailable = [], [], [], []
    for index, beat in enumerate(beats or []):
        beat = beat if isinstance(beat, dict) else {}
        beat_id = _text(beat.get("beat_id")) or f"beat_{index + 1:02d}"
        event = event_of(beat)
        if not event["text"]:
            continue                       # discourse: nothing to evidence, nothing to exceed
        if beat_id in blocked:
            skipped.append(beat_id)
            continue

        cited = [claims.get(ref) for ref in event["claim_refs"]] if claims else []
        cited = [claim for claim in cited if claim]
        verdict = ce.evidence_entailment(cited, event["text"], judge=judge, cache=cache,
                                         cost_sink=cost_sink)
        if ce.is_retryable(verdict):
            unavailable.append({"beat_id": beat_id, "stage": "evidence", **verdict})
            continue
        if not verdict["passed"]:
            evidence.append({"beat_id": beat_id, **verdict})
            continue

        narration = _text(beat.get("narration"))
        if not narration:
            continue
        told = ce.narration_fidelity(event["text"], narration, judge=judge, cache=cache,
                                     cost_sink=cost_sink)
        if ce.is_retryable(told):
            unavailable.append({"beat_id": beat_id, "stage": "fidelity", **told})
        elif not told["passed"]:
            fidelity.append({"beat_id": beat_id, **told})

    if structural:
        structure_status = STRUCTURE_FAIL
    elif indeterminate:
        structure_status = STRUCTURE_PASS_WITH_UNKNOWN_KIND
    else:
        structure_status = STRUCTURE_PASS

    return {
        "schema_version": SCHEMA_VERSION,
        "passed": not (structural or evidence or fidelity) and not unavailable,
        "structure_status": structure_status,
        # Bindings the kind gate abstained on. Not failures, not passes — the paid judge is the
        # only thing standing behind them, and a rising count here means the classifier is
        # degrading even while CLAIM_KIND_MISMATCH falls.
        "indeterminate_kinds": indeterminate,
        "beats_with_indeterminate_kinds": sorted(abstained),
        "structural": structural,
        "evidence": evidence,
        "fidelity": fidelity,
        # Judged nowhere, because the cheap layer already rejected them. Reported so the count is
        # never mistaken for a clean result.
        "skipped_for_structure": skipped,
        # Not a finding about the writing. Retry these; do not send a repair pass at them.
        "unavailable": unavailable,
    }


# The causal job each required role performs. Two beats doing the same job with the same state
# transition are one beat written twice, however differently they are worded -- and once a duplicate
# exists in the FACT model every layer below has to compensate for it, which is why this is caught
# here rather than left to narration dedupe.
CENTRAL_FUNCTIONS = {
    "setup": "establishes the state",
    "intervention": "changes the incentives",
    "false_resolution": "creates apparent success",
    "hinge": "reveals the flaw",
    # These three are routinely conflated, and conflating them is how a story ends up stating its
    # flaw twice and calling the second one a reversal:
    #   mechanism  WHY the incentive is broken      the bounty measures tails, not rats removed
    #   escalation HOW people exploit it            tails are cut from living rats, which are freed
    #   reversal   WHAT the system has now BECOME   rats are worth more alive than dead
    # A reversal restating the mechanism is not a reversal; it is the flaw said again.
    "mechanism": "names the rule — WHY the incentive is broken",
    "escalation": "HOW people exploit it, compounding",
    "reversal": "WHAT the system has become — the end state inverted",
    "tool": "hands back a reusable lens",
    "verdict": "states what the pattern proves",
}
# Roles whose duplicates may be collapsed into one beat. Everything else is a distinct causal job,
# and two beats performing the same transition under different required roles means one of those
# roles is missing rather than repeated.
COLLAPSIBLE_ROLES = ("escalation", "generalization")
# Roles a story can be told without. Context and comparison are enrichment: if the evidence does not
# carry them, they are pruned rather than sourced harder or invented.
OPTIONAL_ROLES = ("generalization",)
# What a complete causal story must actually evidence. Raw supported/total is poor telemetry -- five
# supported context beats with an unsupported reversal is a bad story, and five supported beats
# carrying the whole mechanism is a good one.
REQUIRED_SPINE_ROLES = ("setup", "intervention", "false_resolution", "mechanism",
                        "escalation", "reversal")


def _state_signature(beat: dict) -> str:
    """A beat's causal job, as the transition it performs rather than the words it uses."""
    transition = beat.get("changes_state")
    transition = transition if isinstance(transition, dict) else {}
    return f"{_text(transition.get('from')).casefold()}=>{_text(transition.get('to')).casefold()}"


# Words that carry no causal content, so two events sharing only these are not the same beat.
_FUNCTION_WORDS = frozenset((
    "that", "this", "these", "those", "with", "from", "into", "were", "have", "been", "they",
    "their", "them", "when", "then", "than", "also", "more", "most", "some", "such", "each",
    "which", "while", "after", "before", "about", "would", "could", "there", "where", "what",
    # Three-letter words matter once `_stems` drops the four-letter floor so that "rat" counts in a
    # story about rats. Without these, "and" alone was enough overlap to certify a China parallel
    # case as a Hanoi mechanism.
    "and", "the", "for", "was", "are", "but", "not", "its", "had", "has", "who", "one", "out",
    "any", "all", "can", "did", "own", "per", "via", "yet", "how", "why", "now", "way",
))


def _stems(text: str) -> set:
    """Content words reduced far enough that a plural cannot hide a match.

    Kept separate from `_content_words`, which the duplicate detector depends on: measured on the
    Hanoi spine, the role contract rejected a perfectly good mechanism because its event said
    "tail" and its declared state said "tails", and "rat" fell under the four-letter floor in a
    story about rats. Crude suffix stripping is enough -- this decides whether two phrases are
    about the same thing, not what either one means.
    """
    out = set()
    for word in re.findall(r"[a-z]+", _text(text).lower()):
        if len(word) < 3 or word in _FUNCTION_WORDS:
            continue
        for suffix in ("ies", "ing", "ed", "es", "s"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 3:
                word = word[:-len(suffix)] + ("y" if suffix == "ies" else "")
                break
        out.add(word)
    return out


def _content_words(text: str) -> set:
    return {word for word in re.findall(r"[a-z]+", _text(text).lower())
            if len(word) > 3 and word not in _FUNCTION_WORDS}


def duplicate_event_functions(beats: list[dict]) -> list[dict]:
    """Beats performing the same causal job twice.

    Compared on the state transition first and the event's content second, because two events can
    be worded quite differently and still move the story from and to the same place:

        beat 5  from: tail count appears successful    to: the rat population is not reduced
        beat 8  from: the bounty appears successful    to: the underlying problem persists

    Those are one beat. Wording similarity alone would miss it; the transition is the tell.
    """
    issues, seen = [], []
    for index, beat in enumerate(beats or []):
        beat = beat if isinstance(beat, dict) else {}
        role = _text(beat.get("role") or beat.get("causal_role")).lower()
        event = event_of(beat)["text"]
        if not event or role not in CENTRAL_FUNCTIONS:
            continue
        beat_id = _text(beat.get("beat_id")) or f"beat_{index + 1:02d}"
        signature, words = _state_signature(beat), _content_words(event)
        for prior_id, prior_role, prior_sig, prior_words in seen:
            same_transition = signature != "=>" and signature == prior_sig
            overlap = (len(words & prior_words) / max(1, min(len(words), len(prior_words)))
                       if words and prior_words else 0.0)
            if not (same_transition or overlap >= 0.6):
                continue
            # ACROSS REQUIRED ROLES, a duplicate is not redundancy — it is a missing beat.
            # Collapsing them deletes a causal function the story needs: a measured plan wrote the
            # same sentence for its mechanism and its reversal, and collapsing them silently
            # removed the reversal, so the compiler reported the story as unsupported when the
            # real defect was that the planner never wrote a reversal at all.
            if (prior_role != role and prior_role in REQUIRED_SPINE_ROLES
                    and role in REQUIRED_SPINE_ROLES):
                issues.append(_issue(
                    "DUPLICATE_ACROSS_REQUIRED_ROLES",
                    f"{prior_role} and {role} describe the same state change, so the {role} is not "
                    f"doing its job. {prior_role}: {CENTRAL_FUNCTIONS.get(prior_role, '')}. "
                    f"{role}: {CENTRAL_FUNCTIONS.get(role, '')}. Required repair: write a {role} "
                    "that is distinct from the " + prior_role,
                    beat_id=beat_id, duplicate_of=prior_id, collapsible=False))
                break
            if role in COLLAPSIBLE_ROLES and prior_role == role:
                issues.append(_issue(
                    "DUPLICATE_EVENT_FUNCTION",
                    f"beat {beat_id} performs the same causal job as {prior_id} "
                    f"({CENTRAL_FUNCTIONS.get(prior_role, prior_role)}); collapse them into one "
                    "beat rather than sourcing the same state change twice",
                    beat_id=beat_id, duplicate_of=prior_id, collapsible=True))
                break
        else:
            seen.append((beat_id, role, signature, words))
    return issues


def prune_unsupported_optional(beats: list[dict], failed_ids: set) -> tuple[list, list]:
    """Drop beats the evidence does not carry AND the story does not need.

    Returns (kept, pruned). Not every researched fact deserves a beat: a spine should contain only
    events that change the state of the story, so an unsupported comparison or a thin piece of
    context is removed rather than rewritten or sourced harder. A required role is never pruned --
    if the reversal is unsupported the story genuinely cannot be told.
    """
    kept, pruned = [], []
    for index, beat in enumerate(beats or []):
        beat = beat if isinstance(beat, dict) else {}
        beat_id = _text(beat.get("beat_id")) or f"beat_{index + 1:02d}"
        role = _text(beat.get("role") or beat.get("causal_role")).lower()
        optional = role in OPTIONAL_ROLES or scope_of(beat) == PARALLEL_CASE
        if beat_id in failed_ids and optional:
            pruned.append({"beat_id": beat_id, "role": role,
                           "event": event_of(beat)["text"],
                           "reason": "unsupported and not required by the causal chain"})
        else:
            kept.append(beat)
    return kept, pruned


def narrow_required_roles(beats: list[dict], verdicts: dict) -> tuple[list, list, list]:
    """Repair a required beat from its OWN evidence, and only when there is a core to keep.

    The free dossier search this replaces was unsound twice over. It picked the first verified claim
    of a compatible kind, which produced "Michael G. Vann published a peer-reviewed account" as a
    story's SETUP and a China comparable-case claim as its MECHANISM -- both perfectly sourced and
    both useless. And it then validated the substitution by asking whether the claim supported the
    event, which the claim it was copied from trivially does. A step that can only confirm itself.

    So: narrow, never search. `partially_entailed` means Boundary A found a factual nucleus worth
    keeping and named the unsupported specificity around it, so the beat can drop the specificity
    and keep the subject it always had:

        event           1890s sewer construction created Hanoi's rat problem
        supported_core  Hanoi had a serious rat problem
        narrowed to     Hanoi had a serious rat problem

    Any other verdict gets no repair. `unsupported` means there is no demonstrated nucleus to
    preserve, and inventing one from neighbouring evidence is how a compiler becomes a hallucination
    layer wearing a citation.

    Returns (beats, narrowed, blocked).
    """
    narrowed, blocked, out = [], [], []
    for index, beat in enumerate(beats or []):
        beat = dict(beat) if isinstance(beat, dict) else {}
        beat_id = _text(beat.get("beat_id")) or f"beat_{index + 1:02d}"
        role = _text(beat.get("role") or beat.get("causal_role")).lower()
        verdict = verdicts.get(beat_id) or {}
        if role not in REQUIRED_SPINE_ROLES or not verdict or verdict.get("passed"):
            out.append(beat)
            continue

        kind = _text(verdict.get("verdict"))
        core = _text(verdict.get("supported_core"))
        if kind == "partially_entailed" and core:
            candidate = dict(beat, event={"text": core,
                                          "claim_refs": event_of(beat)["claim_refs"]})
            holds, why = role_contract_holds(candidate)
            if holds:
                narrowed.append({"beat_id": beat_id, "role": role,
                                 "was": event_of(beat)["text"], "now": core,
                                 "dropped": verdict.get("unsupported_details") or []})
                out.append(candidate)
                continue
            # Sourced but no longer doing its job. "French authorities governed Hanoi in 1902" is
            # impeccable evidence and a useless setup for a story about rats.
            blocked.append(_issue("ROLE_CONTRACT_FAILED",
                                  f"beat {beat_id}: narrowing to the supported core left a {role} "
                                  f"that no longer performs its function — {why}. "
                                  f"{role}: {CENTRAL_FUNCTIONS.get(role, '')}",
                                  beat_id=beat_id, role=role))
            out.append(beat)
            continue

        code = {"contradicted": "REQUIRED_ROLE_CONTRADICTED"}.get(
            kind, "MISSING_REQUIRED_ROLE_SUPPORT")
        blocked.append(_issue(
            code,
            f"beat {beat_id} is the {role} and its evidence returned {kind or 'no verdict'}; "
            "there is no supported core to narrow to. The story needs this causal function, so "
            "research or replan it rather than softening it until it passes",
            beat_id=beat_id, role=role))
        out.append(beat)
    return out, narrowed, blocked


def role_contract_holds(beat: dict) -> tuple[bool, str]:
    """Does this beat's event still perform the role it claims, after being narrowed?

    Support and narrative function are separate contracts: evidence can prove a statement true
    without making it useful to the story. This asks the second question, keyed on the state
    transition the beat declared rather than on the kind of its citations.
    """
    beat = beat or {}
    role = _text(beat.get("role") or beat.get("causal_role")).lower()
    event = event_of(beat)["text"]
    if not event:
        return False, "the beat has no event"
    transition = beat.get("changes_state")
    transition = transition if isinstance(transition, dict) else {}
    before, after = _text(transition.get("from")), _text(transition.get("to"))

    if role in ("reversal", "hinge") and before and after and before.casefold() == after.casefold():
        return False, "its declared before and after states are identical"
    # Narrow anti-pattern, not a theory of narrative: an event that describes the SOURCE rather
    # than the world. "The article surveys the rat bounty" is true, cited, and about a document.
    # It overlaps its own state transition on the words "rat" and "bounty", so no overlap test
    # catches it -- which is exactly why the dossier-wide search produced three of them.
    if _META_EVIDENCE.search(event):
        return False, "its event describes the source material rather than anything that happened"
    # A comparison illustrates the rule after the story has earned it; it can never BE a step of
    # the story. This holds even when the beat calls itself primary_story -- which is precisely
    # what a mis-sourced beat does.
    if role in REQUIRED_SPINE_ROLES and (_text(beat.get("scope")) == PARALLEL_CASE
                                         or _PARALLEL_MARKER.search(event)):
        return False, "its event is a comparable case, which cannot be a step of the primary story"
    if not after:
        return True, ""
    # The narrowed event must still reach the state the beat exists to produce. Stripping the
    # unsupported specificity is fine; stripping the thing that made the transition happen is not.
    overlap = _stems(event) & _stems(after)
    if not overlap:
        return False, (f"the narrowed event shares nothing with the state it must produce "
                       f"({after[:60]!r})")
    return True, ""


_PARALLEL_MARKER = re.compile(r"\bCOMPARABLE\s+CASE\b", re.I)

_META_EVIDENCE = re.compile(
    r"\b(?:th(?:is|e)\s+(?:article|paper|stud(?:y|ies)|paper|paper)|"
    r"(?:article|paper|study|book|chapter|account|analysis|survey|dataset)\s+"
    r"(?:survey|describ|argu|note|record|document|examin|discuss|report|find)\w*|"
    r"(?:published|peer-reviewed|peer reviewed)\s|"
    r"\bin\s+(?:the\s+)?journal\b|"
    r"(?:historian|researcher|scholar|economist)s?\s+(?:have\s+)?"
    r"(?:publish|writ|argu|document|record|not)\w*)", re.I)


def spine_coverage(beats: list[dict], failed_ids: set) -> dict:
    """Which required causal functions the evidence actually supports.

    The gate that matters. A story whose setup, intervention, false resolution, mechanism,
    escalation and reversal are all evidenced can be told, even if the planner also proposed two
    expendable beats that did not survive.
    """
    supported, missing, why = {}, [], {}
    for role in REQUIRED_SPINE_ROLES:
        holders = [beat for beat in beats or []
                   if _text((beat or {}).get("role") or (beat or {}).get("causal_role")).lower() == role
                   and event_of(beat or {})["text"]]
        ok = [b for b in holders
              if (_text(b.get("beat_id")) or "") not in failed_ids]
        supported[role] = len(ok)
        if not ok:
            missing.append(role)
            # "Missing" hides two different problems with two different fixes: the planner never
            # wrote this beat (replan), or it wrote one the evidence does not carry (research).
            why[role] = ("no beat on the sheet performs this role"
                         if not holders else
                         "; ".join(f"{_text(b.get('beat_id'))} failed: "
                                   f"{event_of(b)['text'][:70]}" for b in holders))
    return {"required": list(REQUIRED_SPINE_ROLES), "supported_by_role": supported,
            "missing": missing, "missing_because": why, "covered": not missing}


class StorySpineUnsupported(ValueError):
    """The research does not evidence the sequence of events this story needs.

    Carries the sheet and the compile result. A refusal that discards what it refused cannot be
    measured across runs, and role assignment is exactly the thing that needs measuring across
    runs -- the events the planner proposes may be identical while the functions it assigns them
    move, and only the sheet shows that.
    """

    def __init__(self, message: str, *, spine: dict | None = None, beats: list | None = None):
        super().__init__(message)
        self.spine = spine or {}
        self.beats = beats or []


def spine_report(beats: list[dict], report: dict) -> str:
    """Say which central events the evidence supports and which it does not.

    Written to be actionable rather than merely refusing: an operator reading this should be able to
    tell instantly whether the topic is unsupportable or the beats are simply bound wrong.
    """
    by_id = {}
    for index, beat in enumerate(beats or []):
        beat = beat if isinstance(beat, dict) else {}
        by_id[_text(beat.get("beat_id")) or f"beat_{index + 1:02d}"] = beat

    failed = {}
    for issue in report.get("structural") or []:
        failed.setdefault(issue.get("beat_id"), []).append(issue["code"])
    for row in report.get("evidence") or []:
        failed.setdefault(row.get("beat_id"), []).append(row.get("verdict", "unsupported"))

    factual = [bid for bid, beat in by_id.items() if event_of(beat)["text"]]
    supported = [bid for bid in factual if bid not in failed]

    lines = ["STORY_SPINE_UNSUPPORTED", "",
             f"Central events supported: {len(supported)}/{len(factual)}", ""]
    if supported:
        lines.append("Supported:")
        lines += [f"  + {event_of(by_id[bid])['text']}" for bid in supported]
        lines.append("")
    lines.append("Unsupported:")
    for bid, reasons in failed.items():
        beat = by_id.get(bid) or {}
        text = event_of(beat)["text"] or _text(beat.get("beat")) or bid
        lines.append(f"  - {text}")
        lines.append(f"      {bid} [{', '.join(reasons)}]")
    return "\n".join(lines)


def compile_spine(beats: list[dict], claims: dict | None = None,
                  claims_by_case: dict | None = None, *,
                  judge=None, cache: dict | None = None,
                  cost_sink: list | None = None) -> dict:
    """Produce the smallest complete supported causal spine, or say which function is missing.

    The target is not "make every proposed beat pass". A planner asked for nine beats will propose
    nine whether or not the evidence carries nine, and rejecting the whole topic because two of
    them overreached throws away a story the archives genuinely support. So:

        1. collapse beats performing the same causal job          free
        2. structure + evidence on what remains                   paid, cached
        3. prune unsupported beats the chain does not require      free
        4. re-evaluate on REQUIRED-ROLE COVERAGE, not on a ratio

    Pruning removes; it never rewrites. An unsupported fact is dropped from the spine, not softened
    until it passes.
    """
    # A sheet carrying no events at all is not a supported spine and not an unsupported one -- the
    # fact model was handed nothing to weigh. Saying "passed" here would be the lying-PASS bug this
    # codebase has already paid for once, so the distinction is reported rather than flattened. But
    # a dossier means the planner was asked for events and returned none, and THAT is a failure:
    # the alternative is a gate that silently switches itself off the day the field stops arriving.
    if not any(event_of(beat or {})["text"] for beat in beats or []):
        missing_events = [_issue("SHEET_CARRIES_NO_EVENTS",
                                 "research was gathered and the beat sheet bound no events to it, "
                                 "so nothing about this story has been checked against evidence")
                          ] if claims else []
        return {"schema_version": SCHEMA_VERSION, "passed": not missing_events, "assessed": False,
                "coverage": {"required": list(REQUIRED_SPINE_ROLES), "supported_by_role": {},
                             "missing": [], "covered": False},
                "collapsed_duplicates": [], "duplicate_across_roles": [],
                "unrepairable": missing_events, "narrowed": [], "pruned": [],
                "kept_beats": [_text((b or {}).get("beat_id")) or f"beat_{i + 1:02d}"
                               for i, b in enumerate(beats or [])],
                "still_failing": [], "cascade": validate_cascade(beats, claims, claims_by_case,
                                                                 judge=judge, cache=cache,
                                                                 cost_sink=cost_sink)}

    duplicates = duplicate_event_functions(beats)
    dropped_ids = {issue["beat_id"] for issue in duplicates if issue.get("collapsible")}
    deduped = [beat for index, beat in enumerate(beats or [])
               if (_text((beat or {}).get("beat_id")) or f"beat_{index + 1:02d}") not in dropped_ids]

    report = validate_cascade(deduped, claims, claims_by_case,
                              judge=judge, cache=cache, cost_sink=cost_sink)
    failed = {issue.get("beat_id") for issue in report["structural"] if issue.get("beat_id")}
    failed |= {row["beat_id"] for row in report["evidence"]}
    failed |= {row["beat_id"] for row in report["fidelity"]}

    kept, pruned = prune_unsupported_optional(deduped, failed)
    # A required role cannot be pruned, so it is narrowed to whatever Boundary A actually supported
    # -- never re-sourced from elsewhere in the dossier.
    kept, narrowed, unrepairable = narrow_required_roles(
        kept, {row["beat_id"]: row for row in report["evidence"]})
    # No second entailment call: `supported_core` is Boundary A's own finding about these same
    # claims, so re-asking "do they support it" is a question whose answer we already bought. The
    # check worth running is the other contract -- whether the narrowed beat still does its job --
    # and `narrow_required_roles` has already run it, keeping only beats that passed.
    failed -= {row["beat_id"] for row in narrowed}
    still_failing = sorted({bid for bid in failed
                            if bid in {_text(b.get("beat_id")) for b in kept}})
    coverage = spine_coverage(kept, failed)
    blocking = [i for i in duplicates if not i.get("collapsible")] + unrepairable

    return {
        "schema_version": SCHEMA_VERSION,
        "assessed": True,
        # A spine is usable when every required causal function is evidenced and nothing that
        # survived pruning is still failing.
        "passed": (coverage["covered"] and not still_failing and not blocking
                   and not report["unavailable"]),
        "coverage": coverage,
        "collapsed_duplicates": [i for i in duplicates if i.get("collapsible")],
        "duplicate_across_roles": [i for i in duplicates if not i.get("collapsible")],
        "unrepairable": unrepairable,
        "narrowed": narrowed,
        "pruned": pruned,
        "kept_beats": [_text(b.get("beat_id")) for b in kept],
        "still_failing": still_failing,
        "cascade": report,
    }


def spine_summary(beats: list[dict], compiled: dict) -> str:
    """The compile result, written to be acted on."""
    by_id = {}
    for index, beat in enumerate(beats or []):
        by_id[_text((beat or {}).get("beat_id")) or f"beat_{index + 1:02d}"] = beat or {}
    coverage = compiled["coverage"]
    if not compiled.get("assessed", True):
        head = "SPINE NOT ASSESSED — the beat sheet bound no events"
        if compiled.get("unrepairable"):
            return f"STORY_SPINE_UNSUPPORTED\n\n  ! [SHEET_CARRIES_NO_EVENTS] " \
                   f"{compiled['unrepairable'][0]['message']}"
        return f"{head} (no research to check them against either)"
    lines = ["SUPPORTED_SPINE_COVERAGE" if coverage["covered"] else "STORY_SPINE_UNSUPPORTED", ""]
    lines.append("Required causal functions:")
    for role in coverage["required"]:
        mark = "+" if coverage["supported_by_role"].get(role) else "-"
        lines.append(f"  {mark} {role:18s} {CENTRAL_FUNCTIONS.get(role, '')}")
    if coverage["missing"]:
        lines += ["", "MISSING — the story cannot be told without these:"]
        for role in coverage["missing"]:
            lines.append(f"  - {role}: {coverage.get('missing_because', {}).get(role, '')}")
    if compiled.get("duplicate_across_roles"):
        lines += ["", "DUPLICATE_ACROSS_REQUIRED_ROLES — a role is missing, not repeated:"]
        for issue in compiled["duplicate_across_roles"]:
            lines.append(f"  ! {issue['message']}")
    if compiled.get("unrepairable"):
        lines += ["", "REQUIRED ROLES THAT CANNOT BE REPAIRED:"]
        for issue in compiled["unrepairable"]:
            lines.append(f"  ! [{issue['code']}] {issue['message']}")
    if compiled.get("narrowed"):
        lines += ["", "Required roles narrowed to their supported core:"]
        for row in compiled["narrowed"]:
            lines.append(f"  > {row['beat_id']} [{row['role']}]")
            lines.append(f"      was: {row['was'][:90]}")
            lines.append(f"      now: {row['now'][:90]}")
            for detail in row["dropped"][:3]:
                lines.append(f"      dropped: {detail[:80]}")
    if compiled["collapsed_duplicates"]:
        lines += ["", "Collapsed as duplicate causal functions:"]
        for issue in compiled["collapsed_duplicates"]:
            lines.append(f"  ~ {issue['beat_id']} == {issue.get('duplicate_of')}: "
                         f"{event_of(by_id.get(issue['beat_id'], {}))['text'][:90]}")
    if compiled["pruned"]:
        lines += ["", "Pruned — unsupported and not required:"]
        for row in compiled["pruned"]:
            lines.append(f"  x {row['beat_id']} [{row['role']}]: {row['event'][:90]}")
    if compiled["still_failing"]:
        # Every failure states its cause. A beat listed here with no reason sends an operator
        # hunting through three layers to find out whether the evidence or the schema rejected it.
        cascade = compiled.get("cascade") or {}
        reason = {row["beat_id"]: f"[{row.get('verdict', 'evidence')}] "
                                  f"{_text(row.get('reason') or row.get('message'))[:90]}"
                  for row in (cascade.get("evidence") or []) + (cascade.get("fidelity") or [])
                  if row.get("beat_id")}
        for issue in cascade.get("structural") or []:
            if issue.get("beat_id"):
                reason.setdefault(issue["beat_id"], f"[{issue['code']}] {issue['message'][:90]}")
        lines += ["", "Still failing after pruning:"]
        for bid in compiled["still_failing"]:
            lines.append(f"  ! {bid}: {event_of(by_id.get(bid, {}))['text'][:80]}")
            lines.append(f"      {reason.get(bid, '[no verdict recorded]')}")
    kept = set(compiled["kept_beats"])
    lines += ["", "Sheet as proposed:"]
    for index, beat in enumerate(beats or []):
        beat = beat or {}
        bid = _text(beat.get("beat_id")) or f"beat_{index + 1:02d}"
        role = _text(beat.get("role") or beat.get("causal_role")).lower() or "-"
        mark = "-" if bid not in kept else ("!" if bid in compiled["still_failing"] else "+")
        lines.append(f"  {mark} {bid} [{role:16s}] {event_of(beat)['text'][:74]}")
    lines += ["", f"Spine: {len(kept)} beats from {len(beats or [])} proposed."]
    return "\n".join(lines)
