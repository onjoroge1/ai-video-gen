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
CLAIM_KINDS = ("event", "mechanism", "context", "outcome", "general_principle", "parallel_case")
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

_ROLE_ACCEPTS = {
    "setup": ("event", "context", "outcome"),
    "intervention": ("event", "context", "outcome"),
    "false_resolution": ("event", "context", "outcome"),
    "hinge": ("event", "context", "outcome", "mechanism"),
    "escalation": ("event", "context", "outcome"),
    "reversal": ("event", "context", "outcome"),
    "mechanism": ("mechanism", "general_principle"),
    "generalization": ("parallel_case", "general_principle"),
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
            kind = _text(claim.get("claim_kind")).lower()
            confidence = claim.get("claim_kind_confidence")
            try:
                unsure = confidence is not None and float(confidence) < MIN_KIND_CONFIDENCE
            except (TypeError, ValueError):
                unsure = False
            if not kind or kind == UNKNOWN_KIND or unsure:
                out.append({"beat_id": beat_id, "claim_id": claim_id,
                            "claim_kind": kind or UNKNOWN_KIND,
                            "claim_kind_confidence": confidence,
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
                kind = _text(claim.get("claim_kind")).lower()
                confidence = claim.get("claim_kind_confidence")
                try:
                    unsure = confidence is not None and float(confidence) < MIN_KIND_CONFIDENCE
                except (TypeError, ValueError):
                    unsure = False
                # No label, an explicit unknown, or a label its own classifier doubts: skip rather
                # than enforce. The semantic boundary still has to agree, so skipping loses a cheap
                # rejection, not the contract.
                if not kind or kind == UNKNOWN_KIND or unsure:
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
