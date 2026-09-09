"""Story roles derived from factual functions, so the planner never picks one.

The measured failure this replaces: across five Hanoi sheets the same factual event landed in
`escalation`, `hinge` and `mechanism` on different runs, and each placement was defensible. The
planner was being asked an editorial question dressed as a factual one.

Here it answers only the factual question -- what is this fact -- and the roles fall out. Two of
them are not assignments at all but computations over the facts, because neither is a thing that
happened: the mechanism is the gap between what a policy paid for and what it wanted, and the
reversal is a comparison between the world before and the world the exploit produced.
"""
from __future__ import annotations

from copy import deepcopy
import re
import json
import event_functions as ef
import story_fact_model as sfm

COMPILER_VERSION = "story_compiler_v2"


def factual_plan_prompt(question, duration, count, engine_id, cast_rules=""):
    """The factual planner never receives the narration layer's competing role slots."""
    mapping = ef.map_for(engine_id)
    functions = tuple(mapping.to_role)
    import causal_story
    schema = {
        "title": "", "hook": f"at most {causal_story.MAX_HOOK_WORDS} words, with a named actor "
                               "and the concrete title subject",
        "throughline": "", "opening_object": "", "final_callback_object": "",
        "recurring_location": "the primary case's documented setting, reused in the opening",
        "style_mode": "educational", "stages": [], "parallel_cases": [],
        "beats": [{"n": 1, "beat_id": "event_01", "beat": "the factual event text",
                   "event_function": "one of: " + " | ".join(functions),
                   "caused_by": "earlier beat_id, or empty for the initial problem",
                   "scope": "primary_story", "parallel_case_id": "",
                   "event": {"text": "one historical assertion", "claim_refs": ["claim_id"]},
                   "changes_state": {"from": "evidence-backed starting state",
                                     "to": "evidence-backed resulting state"},
                   "incentive": {"rewarded_measure": "proof accepted for payment",
                                 "measure_claim_refs": ["claim_id"],
                                 "stated_policy_goal": "the documented intended outcome",
                                 "goal_claim_refs": ["claim_id"]}}]}
    # The incentive block belongs to an engine that DERIVES its mechanism from it. A plan that
    # never happened has no rewarded measure, and asking for one is how a prompt teaches a model to
    # invent a field to fill -- the same shape as asking for a chapter marker and then stripping it.
    if "mechanism" not in mapping.derived:
        schema["beats"][0].pop("incentive", None)
    return (
        f'Plan the sourced factual events for a {duration}-second illustrated video: "{question}".\n'
        f'Engine: {engine_id}. Return about {max(len(mapping.required), count - 3)} distinct factual '
        'events, including each required function exactly once; add only distinct supported '
        'consequences or optional context. Do not pad the list.\n'
        'Required functions: ' + ', '.join(mapping.required) + '.\n'
        + '\n'.join(f'{name}: {ef.WHAT_EACH_FUNCTION_IS[name]}'
                    for name in functions)
        + '\nThe compiler assigns story roles, derives the mechanism and reversal, and adds '
        'presentation transitions and the closing question. Every event you supply needs a '
        'nonempty factual text and its own supporting claim_refs. State changes must follow '
        'from those same facts; an intended reduction followed by unchanged numbers is failure, '
        'not an inversion. Do not supply a hinge, mechanism, tool, or editorial role field.\n'
        + ('On changes_incentive only, supply incentive. rewarded_measure names what was '
           'accepted as proof, not what the policy was announced as. Bind it to the claim '
           'about accepted proof. stated_policy_goal needs separate evidence of the policy '
           'purpose; never infer intent. Both citation lists are required.\n'
           if "mechanism" in mapping.derived else "")
        + 'Keep every primary event about this policy and subject. A parallel_case event contains '
        'one comparison only, with its own id and citations; do not merge countries. If you add '
        f'comparisons, supply at least {causal_story.MIN_PARALLEL_CASES} distinct cases and fill '
        'parallel_cases with domain, problem, solution, and result for each. Otherwise leave it [].\n'
        'Preserve uncertainty and timescales. Use stable beat IDs for causal links. The opening '
        'and final callback refer to the same concrete object.\n'
        + cast_rules + '\nReturn ONLY JSON matching this shape:\n' + json.dumps(schema))


def canonical_beats(beats: list[dict]) -> list[dict]:
    """Stable identities and parent references, independent of subsequent display order."""
    out = deepcopy(beats)
    for i, beat in enumerate(out):
        beat["beat_id"] = sfm._text(beat.get("beat_id")) or f"beat_{i + 1:02d}"
    by_number = {int(b.get("n") or i + 1): b["beat_id"] for i, b in enumerate(out)}
    for beat in out:
        parent = beat.get("caused_by")
        if isinstance(parent, int) or (isinstance(parent, str) and parent.isdigit()):
            beat["caused_by"] = by_number.get(int(parent), "")
    return out


def refresh_story_positions(scenes):
    """Presentation positions follow the finished words, never absent planner percentages."""
    lengths = [len(str(s.get("narration") or "").split()) for s in scenes]
    total, elapsed = sum(lengths) or 1, 0
    for scene, length in zip(scenes, lengths):
        scene["story_pct"] = round(100 * elapsed / total, 2)
        elapsed += length

def function_of(beat: dict) -> str:
    return (sfm._text((beat or {}).get("event_function"))).strip().lower()


def _phrase(value) -> str:
    """A noun phrase fit to drop into a sentence.

    Measured: a planner returned "Reduce Hanoi's rat population" and the derived mechanism read
    "The goal was Reduce Hanoi's rat population." An evidence judge reading ungrammatical text has
    been handed a second reason to reject a claim that may be perfectly true.
    """
    text = sfm._text(value).strip().rstrip(".").strip()
    head = text.split(" ")[0]
    # Acronyms keep their case ("US bounty payments"); a lone capital "A" is not an acronym.
    if text[:1].isupper() and not (len(head) > 1 and head.isupper()):
        text = text[:1].lower() + text[1:]
    return text


# The schema asks for the bare object -- "No rate, no date, no place -- just the object" -- and
# three consecutive samples returned "a severed rat tail handed to the authorities", "...presented
# to the bounty clerk", "one cent per rat tail handed in". Each addition is a detail no claim
# carries, so the derived mechanism failed the evidence boundary on the decoration rather than on
# anything the story needed. Asking again has not worked; the clause is simply not part of the
# measure, and dropping it is loss-free because what pays is the object, not who received it.
_MEASURE_TAIL = re.compile(
    r"\s+(?:handed|presented|brought|delivered|turned|submitted|given|surrendered)\b.*$", re.I)


def normalise_measure(value) -> str:
    """The object a person had to produce, without the hand-over clause wrapped around it."""
    text = _phrase(value)
    trimmed = _MEASURE_TAIL.sub("", text).strip().rstrip(",;")
    return trimmed or text


def incentive_of(beat: dict) -> dict:
    block = (beat or {}).get("incentive")
    block = block if isinstance(block, dict) else {}
    return {"rewarded_measure": normalise_measure(block.get("rewarded_measure")),
            "actual_goal": _phrase(block.get("stated_policy_goal") or block.get("actual_goal")),
            "measure_claim_refs": [sfm._text(r) for r in (block.get("measure_claim_refs") or [])
                                   if sfm._text(r)],
            "goal_claim_refs": [sfm._text(r) for r in (block.get("goal_claim_refs") or [])
                                if sfm._text(r)]}


def _state(beat: dict, side: str) -> str:
    block = (beat or {}).get("changes_state")
    block = block if isinstance(block, dict) else {}
    return sfm._text(block.get(side)).strip()


def _claim_text(claims: dict, ref: str) -> str:
    claim = (claims or {}).get(ref) or {}
    return " ".join(sfm._text(claim.get(field)) for field in ("claim", "support_quote"))


def _citations_mention(claims: dict, refs: list, phrase: str) -> bool:
    """Do the cited claims talk about this at all?

    A relevance heuristic and nothing more. It cannot establish support and it cannot establish
    its absence, in either direction:

        a claim saying "caudal appendage" shares no stem with "tail" and may support it exactly
        a claim saying "tails were counted but not accepted for payment" shares the distinguishing
        word and contradicts the assertion outright

    So its output is a SUSPICION that drives a repair, never a verdict. Only Boundary A rules on
    entailment. It is worth asking first because the answer was no in five of five sampled sheets
    while the claim that fit sat unused in the same dossier -- a cheap prompt for a second look,
    not a gate.
    """
    wanted = _distinctive(phrase, claims)
    if not wanted or not claims:
        return True
    cited = set()
    for ref in refs or []:
        cited |= sfm._stems(_claim_text(claims, ref))
    return bool(wanted & cited)


def _distinctive(phrase: str, claims: dict) -> set:
    """The stems in this phrase that are not the whole dossier's subject.

    "a severed rat tail" shares "rat" with nearly every claim in a dossier about rats, and one
    ubiquitous token was enough to pass the announcement off as evidence for what the clerk
    accepted. The same shape as "and" certifying a China parallel case as a Hanoi mechanism, and
    the same fix: a token that appears everywhere distinguishes nothing.
    """
    stems = sfm._stems(phrase)
    # "Appears in more than half" needs a ledger big enough for half to mean anything. Across
    # three claims it means two, which discarded "tail" from "a severed rat tail" -- the one word
    # that separates the claim about what was accepted from the one counting how many arrived.
    if not stems or len(claims or {}) < _UBIQUITY_FLOOR:
        return stems
    everywhere = {stem for stem in stems
                  if sum(1 for ref in claims if stem in sfm._stems(_claim_text(claims, ref)))
                  > len(claims) / 2}
    # Never everything. A phrase built entirely from the dossier's common vocabulary still has to
    # rank against something, and an empty set silently turns the check into "no opinion".
    return (stems - everywhere) or stems


_UBIQUITY_FLOOR = 6


def rank_claims_for(claims: dict, phrase: str) -> list:
    """Claims ordered by how much of what makes this phrase SPECIFIC they contain.

    Distinctive stems, not raw overlap: in a dossier about rats, "rat" appears nearly everywhere
    and ranking on it puts the announcement level with the claim that actually describes what was
    accepted. Scoring "a severed rat tail" on {sever, tail} separates them.

    Ordering only. Whether the top claim SUPPORTS the sentence is Boundary A's question and this
    cannot answer it -- "caudal appendage" would support "tail" and score zero here.
    """
    wanted = _distinctive(phrase, claims)
    if not wanted:
        return []
    scored = []
    for ref in claims or {}:
        text = _claim_text(claims, ref)
        # A claim ABOUT the scholarship is not evidence of the events it describes, and it scores
        # dangerously well: "Vann's study presents the failure of the Hanoi rat bounty and the
        # plague context" shares almost every word with a goal about Hanoi's rats and plague, and
        # ranked first for it. Same detector that keeps a bibliography out of the story spine.
        if sfm._META_EVIDENCE.search(text) or sfm._PARALLEL_MARKER.search(text):
            continue
        overlap = len(wanted & sfm._stems(text))
        if overlap:
            scored.append((overlap, ref))
    return [ref for _, ref in sorted(scored, key=lambda row: (-row[0], row[1]))]


def propose_measure_claims(claims: dict, phrase: str, limit: int = 2) -> list:
    """The citations a mechanism's `rewarded_measure` should probably carry.

    A PROPOSAL, made because asking a model to choose has now failed three times against a prompt
    that names the exact trap it keeps falling into. Measured on Hanoi: it cited the announcement
    ("a bounty on every dead rat") and then the tail COUNTS, while the claim saying a tail was
    accepted -- "the bounty was extended to anyone in the city who brought a rat tail" -- sat
    unused in the same ledger every time.

    Nothing here certifies anything. The proposal is written into the beat and the evidence
    boundary judges it exactly as it would judge a citation a model picked; a wrong proposal fails
    there and the run fails with it.
    """
    return rank_claims_for(claims, phrase)[:max(1, limit)]


def _claims_that_mention(claims: dict, phrase: str, limit: int = 3) -> list:
    return [f"{ref}: {sfm._text((claims.get(ref) or {}).get('claim'))[:90]}"
            for ref in rank_claims_for(claims, phrase)[:limit]]


def derive_mechanism(intervention: dict, claims: dict | None = None) -> dict:
    """The mechanism is `rewarded_measure != actual_goal`, and both halves must be sourced.

    `rewarded_measure` is a fact about the policy and 4 of 5 measured sheets already stated it
    correctly. `actual_goal` is an attribution of intent to whoever wrote the policy -- the exact
    category the fidelity boundary flags in narration -- so putting it in a schema field does not
    make it true. It carries its own claim_refs or the mechanism does not compile.
    """
    incentive = incentive_of(intervention)
    beat_id = sfm._text((intervention or {}).get("beat_id"))
    suspect = None
    if not incentive["rewarded_measure"] or not incentive["actual_goal"]:
        return {"ok": False, "code": "INTERVENTION_STATES_NO_INCENTIVE",
                "message": f"beat {beat_id} changes the incentive but does not say what the rule "
                           "rewarded and what it was for, so the mechanism cannot be derived "
                           "rather than invented"}
    if not incentive["goal_claim_refs"]:
        return {"ok": False, "code": "GOAL_NOT_EVIDENCED",
                "message": f"beat {beat_id} states the policy's goal as "
                           f"{incentive['actual_goal']!r} with no claim behind it. What a "
                           "government wanted is an attribution of intent, not a free field"}
    if not incentive["measure_claim_refs"]:
        # Measured: with the measure riding on the intervention's own citations, three sheets
        # produced "The reward was paid for a severed rat tail" cited to claims about a bounty
        # being announced on dead rats -- true, correctly derived, and not entailed by what it
        # cited. The proof the clerk accepted is nearly always a different source from the
        # announcement, and it is usually sitting on some other beat.
        return {"ok": False, "code": "MEASURE_NOT_EVIDENCED",
                "message": f"beat {beat_id} says the reward was paid for "
                           f"{incentive['rewarded_measure']!r} with no claim behind it. The "
                           "announcement and the proof actually accepted are different facts "
                           "from different sources, and the gap between them is the story"}
    # NOT a failure. A false positive here would kill a story whose citation is fine, so the
    # suspicion travels with the compiled mechanism and Boundary A still rules on it.
    if not _citations_mention(claims, incentive["measure_claim_refs"],
                              incentive["rewarded_measure"]):
        # Measured on five sheets: the mechanism cited the announcement ("a bounty on every dead
        # rat") and the tail COUNTS, while the claim saying a tail was accepted as proof sat
        # unused in the same dossier. The evidence boundary refused it five times out of five and
        # was right to. This says so before the judge is paid, and names the claim that fits.
        nearest = _claims_that_mention(claims, incentive["rewarded_measure"])
        suspect = {
            "code": "MEASURE_CITATION_SUSPECT", "beat_id": beat_id,
            "field": "measure_claim_refs", "cited": list(incentive["measure_claim_refs"]),
            "phrase": incentive["rewarded_measure"], "candidates": nearest,
            "message": f"beat {beat_id} says the reward was paid for "
                       f"{incentive['rewarded_measure']!r} and cites "
                       f"{', '.join(incentive['measure_claim_refs'])}, which do not appear to "
                       "mention it. What a policy was announced as and what was accepted as "
                       "proof are usually different claims. This is a relevance check, not a "
                       "ruling on support -- only the evidence boundary decides that"
                       + (f". Candidates worth checking: {'; '.join(nearest)}" if nearest else "")}
    if sfm._stems(incentive["rewarded_measure"]) == sfm._stems(incentive["actual_goal"]):
        return {"ok": False, "code": "NO_PROXY_GAP",
                "message": f"beat {beat_id} rewards the same thing it wants, so there is no "
                           "mechanism for the story to turn on"}
    assertions = {
        "measure": {"text": f"The reward was paid for {incentive['rewarded_measure']}.",
                    "claim_refs": incentive["measure_claim_refs"]},
        "goal": {"text": f"The goal was {incentive['actual_goal']}.",
                 "claim_refs": incentive["goal_claim_refs"]},
    }
    return {"ok": True, "role": "mechanism", "suspect": suspect,
            "derivation": {"version": COMPILER_VERSION, "kind": "proxy_gap",
                           "source_ids": [beat_id], "assertions": assertions},
            # Two positive propositions, not one negation. "Paid for tails, NOT for dead rats"
            # asks the evidence boundary to certify something no source states -- the archives
            # record what the bounty paid for, not what it declined to pay for -- and the derived
            # mechanism failed Boundary A on exactly that. Each half now stands on its own claims
            # and the GAP between them is structural, which needs no judge at all.
            "event": {"text": f"The reward was paid for {incentive['rewarded_measure']}. "
                              f"The goal was {incentive['actual_goal']}.",
                      # Each half brings its own evidence. The intervention's citations describe
                      # the announcement and do not reach either proposition on their own.
                      "claim_refs": sorted(set(incentive["measure_claim_refs"])
                                           | set(incentive["goal_claim_refs"]))},
            "changes_state": {"from": _state(intervention, "to"),
                              "to": f"what pays and what was wanted have come apart"},
            "derived_from": [beat_id]}


def derive_reversal(setup: dict, compounds: dict) -> dict:
    """The reversal compares the setup's world with the world the exploit industrialised into.

    Not sourced from an ending event, on measured grounds: five sheets produced seven phrasings of
    the ending and every one said the bounty produced tails without reducing rats. That is the
    programme failing, which the story already implies. What inverted is the subject's standing --
    an unwanted animal became a cultivated one -- and farming is the documented form of that.
    """
    # The setup's `to`, not its `from`: `establishes_problem` ends with the problem in place, and
    # the problem state is what the reversal has to invert. Keyed on `from` it compared the world
    # before anyone noticed rats ("a new sewer network") against the world after they were farmed,
    # which share nothing and rejected a correct reversal.
    before = _state(setup, "to") or _state(setup, "from")
    after = _state(compounds, "to")
    # This constructs a candidate. Only a relationship judgment over supported events can
    # establish an inversion; token overlap cannot prove it (or disprove a paraphrase).
    if not before or not after or before.casefold() == after.casefold():
        return {"ok": False, "code": "NO_INVERSION",
                "message": "the reversal needs distinct, nonempty proposed states"}
    if ef._MERE_FAILURE.search(after):
        return {"ok": False, "code": "NO_INVERSION",
                "message": "the proposed state only reports that the programme failed"}
    sources = [sfm._text(setup.get("beat_id")), sfm._text(compounds.get("beat_id"))]
    return {"ok": True, "role": "reversal",
            "derivation": {"version": COMPILER_VERSION, "kind": "behavior_inversion",
                           "source_ids": sources},
            "event": {"text": sfm.event_of(compounds)["text"],
                      "claim_refs": sfm.event_of(compounds)["claim_refs"]},
            "changes_state": {"from": before, "to": after},
            "derived_from": sources}


def compile_roles(beats: list[dict], engine_id: str, claims: dict | None = None) -> dict:
    """Assign every story role from the beats' factual functions. Nothing here asks a model."""
    mapping = ef.map_for(engine_id)
    if mapping is None:
        return {"compiled": False, "reason": f"{engine_id or 'engine'} still assigns roles itself",
                "beats": list(beats or []), "issues": []}

    # Recompilation always starts from factual nodes. Remove prior synthetic output; retain the
    # compound event that was re-roled as the reversal, but discard its old computed annotation.
    beats = canonical_beats([b for b in beats or [] if not b.get("derived")])
    for beat in beats:
        beat.pop("derivation", None)
        beat.pop("derived_from", None)

    declared = [b for b in beats or []
                if isinstance(b, dict) and function_of(b)]
    if not declared:
        # A sheet from before this contract, or one whose planner returned no functions at all.
        # Compiling it would assign every role from nothing; the older labelling pass and the
        # spine gate behind it still apply. Reported rather than silently taken.
        return {"compiled": False,
                "reason": f"{mapping.engine_id} maps functions to roles, but no beat declares an "
                          "event_function -- falling back to the labelling pass",
                "beats": list(beats or []), "issues": []}

    issues, by_function = [], {}
    out = []
    for index, beat in enumerate(beats or []):
        beat = dict(beat) if isinstance(beat, dict) else {}
        beat.setdefault("beat_id", f"beat_{index + 1:02d}")
        function = function_of(beat)
        if function and function not in ef.EVENT_FUNCTIONS:
            issues.append(sfm._issue("UNKNOWN_EVENT_FUNCTION",
                                     f"beat {beat['beat_id']} declares event_function "
                                     f"{function!r}, which is not one of "
                                     f"{', '.join(ef.EVENT_FUNCTIONS)}",
                                     beat_id=beat["beat_id"]))
            function = ""
        # Always set, never left to inherit. The two role vocabularies share three words.
        beat["role"] = mapping.role_for(function) or "context"
        beat["causal_role"] = beat["role"]
        beat["_story_engine"] = engine_id
        beat["_story_compiler_version"] = COMPILER_VERSION
        beat["event_function"] = function
        by_function.setdefault(function, []).append(beat)
        out.append(beat)

    for function in mapping.missing(by_function):
        issues.append(sfm._issue(
            "MISSING_EVENT_FUNCTION",
            f"no beat is the {function}: {ef.WHAT_EACH_FUNCTION_IS[function]}"))

    # One incentive change, or the story has two interventions and no single thing to exploit.
    interventions = by_function.get(ef.CHANGES_INCENTIVE) or []
    if len(interventions) > 1:
        issues.append(sfm._issue(
            "MULTIPLE_INCENTIVE_CHANGES",
            "more than one beat claims to change the incentive: "
            + ", ".join(b["beat_id"] for b in interventions)
            + ". Only the rule the story goes on to exploit belongs here; an earlier attempt to "
              "solve the problem directly is context"))

    derived, suspicions = [], []
    if len(interventions) == 1:
        mechanism = derive_mechanism(interventions[0], claims)
        if mechanism["ok"]:
            mechanism["derivation"]["witness_ids"] = [
                b["beat_id"] for b in by_function.get(ef.EXPLOIT_BEHAVIOR, [])]
            derived.append(mechanism)
            if mechanism.get("suspect"):
                suspicions.append(mechanism["suspect"])
        else:
            issues.append(sfm._issue(mechanism["code"], mechanism["message"]))
    setups = by_function.get(ef.ESTABLISHES_PROBLEM) or []
    compounds = by_function.get(ef.COMPOUNDS_EXPLOIT) or []
    if setups and compounds:
        reversal = derive_reversal(setups[0], compounds[-1])
        if reversal["ok"] and len(interventions) == 1:
            reversal["derivation"]["goal_source_id"] = interventions[0]["beat_id"]
        (derived.append(reversal) if reversal["ok"]
         else issues.append(sfm._issue(reversal["code"], reversal["message"])))

    return {"compiled": True, "engine": mapping.engine_id, "beats": out,
            "derived": derived, "issues": issues, "suspicions": suspicions,
            "roles": {b["beat_id"]: b.get("role", "") for b in out},
            "passed": not issues}


def summary(result: dict) -> str:
    if not result.get("compiled"):
        return f"Roles not compiled: {result.get('reason', '')}"
    lines = [f"STORY ROLES COMPILED FROM EVENT FUNCTIONS ({result['engine']})", ""]
    for beat in result["beats"]:
        function = beat.get("event_function") or "-"
        lines.append(f"  {function:<20s} -> {(beat.get('role') or '-'):<16s} "
                     f"{sfm.event_of(beat)['text'][:60]}")
    for entry in result["derived"]:
        lines += ["", f"  DERIVED {entry['role']}: {entry['event']['text'][:80]}",
                  f"      from {', '.join(entry['derived_from'])}  "
                  f"cites {', '.join(entry['event']['claim_refs']) or '-'}"]
    for suspect in result.get("suspicions") or []:
        lines += ["", f"  ? [{suspect['code']}] {suspect['message']}"]
    if result["issues"]:
        lines += ["", "Cannot compile:"]
        lines += [f"  ! [{i['code']}] {i['message']}" for i in result["issues"]]
    return "\n".join(lines)


def splice_derived(beats: list[dict], result: dict) -> list[dict]:
    """Place the derived mechanism and reversal into the beat list, in causal order.

    The mechanism follows the intervention it is computed from -- it explains the rule that was
    just introduced, and the engine's deadline wants it early. The reversal goes last among the
    primary-story beats, before any generalization or closing tool, because it is the end state
    those comment on.
    """
    derived = {entry["role"]: entry for entry in result.get("derived") or [] if entry.get("ok")}
    if not derived:
        return list(beats)

    def _made(entry, number):
        source = entry["derived_from"][0] if entry["derived_from"] else ""
        return {"beat_id": f"{source}:mechanism", "n": number, "role": entry["role"],
                "causal_role": entry["role"], "derivation": deepcopy(entry["derivation"]),
                "_story_compiler_version": COMPILER_VERSION,
                "_story_engine": result.get("engine", ""),
                "event_function": "", "derived": True, "derived_from": entry["derived_from"],
                "beat": entry["event"]["text"], "event": entry["event"],
                "changes_state": entry["changes_state"], "scope": sfm.PRIMARY_STORY,
                "claim_refs": [{"claim_id": ref} for ref in entry["event"]["claim_refs"]],
                "caused_by": source, "chapter": 1}

    out: list[dict] = []
    for beat in beats:
        out.append(deepcopy(beat))
        if "mechanism" in derived and function_of(beat) == ef.APPARENT_SUCCESS:
            node = _made(derived.pop("mechanism"), 0)
            node["chapter"] = beat.get("chapter") or 1
            out.append(node)
    if "reversal" in derived:
        # The compounded exploit IS the inversion; it is re-roled, not copied. Inserting a second
        # beat carrying the same event put one fact in two required roles, and the duplicate
        # detector correctly reported the reversal as missing rather than repeated.
        entry = derived.pop("reversal")
        for beat in out:
            if sfm._text(beat.get("beat_id")) == (entry["derived_from"] or [""])[-1]:
                beat["role"], beat["changes_state"] = "reversal", entry["changes_state"]
                beat["causal_role"] = "reversal"
                beat["derivation"] = deepcopy(entry["derivation"])
                beat["derived_from"] = entry["derived_from"]
    for index, beat in enumerate(out):
        beat["n"] = index + 1
        beat.setdefault("beat_id", f"beat_{index + 1:02d}")
    return out


def presentation_beats(beats: list[dict], engine_id: str) -> list[dict]:
    """Add narration devices after factual acceptance, without relabeling factual nodes."""
    if ef.map_for(engine_id):
        import story_engines
        order = story_engines.expected_order(engine_id)
        # Context supports planning but is not an additional step in the narrative contract.
        # Sort before prose exists; identities and factual events remain unchanged.
        out = deepcopy([b for b in beats if b.get("role") in order])
        out.sort(key=lambda b: order.index(b["role"]))
        mechanism = next(b for b in out if b["role"] == "mechanism")
        reversal = next(b for b in out if b["role"] == "reversal")
        # The hinge instruction is the engine's, not one sentence for all of them. "Break the
        # apparent success ... using the supported mechanism and exploit" describes a bounty: it
        # presumes a moment where the fix looked like it worked, and people exploiting it.
        # removed_keystone requires neither, so the expansion was told to break a success that was
        # never claimed and to lean on an exploit nobody committed -- and the narration it wrote
        # came back CONTRADICTED against the events, which is the boundary's strongest verdict.
        hinge_text = {
            "removed_keystone":
                "Name the thing nobody counted, in one short sentence: what the removed species "
                "had also been doing. Do not claim the programme looked successful and do not "
                "say anyone exploited anything. No new historical detail.",
            "almost_happened_plan":
                "Name what stopped the plan, in one short sentence. Do not claim it had already "
                "succeeded. No new historical detail.",
        }.get(engine_id,
              "Break the apparent success in one short sentence, using only the supported "
              "mechanism and exploit. No new historical detail.")
        for role, anchor, text in (
            ("hinge", mechanism, hinge_text),
            ("tool", reversal, "Close with one useful question the viewer can reuse; no new facts."),
        ):
            if any(b.get("causal_role") == role for b in out):
                continue
            # `.get`, because a mechanism is not always derived. almost_happened_plan maps
            # collapse_cause straight onto the role -- what killed the plan is an event somebody
            # recorded -- so its mechanism beat is planner-written and carries no derivation.
            # Subscripting raised KeyError('derivation') on the first hippo sheet whose spine
            # passed, one step after the gate it had just cleared.
            refs = [mechanism["beat_id"]] + (
                (mechanism.get("derivation") or {}).get("witness_ids") or [])
            if role == "tool":
                refs.append(reversal["beat_id"])
            device = {"beat_id": f"{anchor['beat_id']}:{role}", "role": role,
                      "causal_role": role, "presentation_device": role, "context_refs": refs,
                      "event": {"text": "", "claim_refs": []}, "beat": text,
                      # The hinge sits BEFORE its anchor, so it inherits the anchor's cause
                      # rather than pointing at it -- but only if the anchor has one. On
                      # removed_keystone the mechanism is the first beat the planner writes with
                      # no antecedent, so the hinge inherited an empty cause and ORPHAN_STEP
                      # refused a story whose spine had passed in full.
                      "caused_by": ((anchor.get("caused_by") or anchor["beat_id"])
                                    if role == "hinge" else anchor["beat_id"]),
                      "chapter": anchor.get("chapter") or 1, "scope": sfm.PRIMARY_STORY,
                      "_story_engine": engine_id, "_story_compiler_version": COMPILER_VERSION}
            out.insert(out.index(anchor), device) if role == "hinge" else out.append(device)
        for i, beat in enumerate(out):
            beat["n"] = i + 1
            beat["chapter"] = min(4, i * 4 // len(out) + 1)
            derivation = beat.get("derivation") or {}
            if derivation:
                refs = derivation.get("source_ids", []) + derivation.get("witness_ids", [])
                if derivation.get("kind") == "behavior_inversion":
                    refs = refs + [mechanism["beat_id"]]
                beat["context_refs"] = list(dict.fromkeys(r for r in refs if r != beat["beat_id"]))
            refs = sfm.event_of(beat)["claim_refs"]
            if beat.get("context_refs"):
                refs = sorted(set(refs) | {ref for parent in out
                               if parent["beat_id"] in beat["context_refs"]
                               for ref in sfm.event_of(parent)["claim_refs"]})
            beat["claim_refs"] = [{"claim_id": ref} for ref in refs]
            beat["evidence_id"] = f"e{i + 1:02d}" if refs else ""
        # These are engine-owned narrative dependencies. Semantic support for the policy,
        # exploit and inversion was checked on the factual sheet before this adapter is called.
        previous = {}
        # CANDIDATES, not one parent. A single parent orphans any step whose ancestor is optional
        # for this engine and absent from this story: removed_keystone does not require a false
        # resolution, so the hinge pointed at a beat that was never written and ORPHAN_STEP
        # refused a story whose spine had passed in full. Each role now falls back along its own
        # chain to the nearest ancestor that exists.
        parent_roles = {"intervention": ("setup",),
                        "false_resolution": ("intervention", "setup"),
                        "hinge": ("false_resolution", "intervention", "setup"),
                        "mechanism": ("intervention", "setup"),
                        "escalation": ("mechanism", "false_resolution", "intervention"),
                        "reversal": ("escalation", "mechanism", "intervention"),
                        "generalization": ("reversal", "escalation"),
                        "tool": ("reversal", "escalation", "mechanism")}
        for beat in out:
            role = beat["causal_role"]
            inherited = previous.get(role) if role in ("escalation", "generalization") else None
            beat["caused_by"] = inherited or next(
                (previous[name] for name in parent_roles.get(role, ()) if previous.get(name)), "")
            previous[role] = beat["beat_id"]
        return out
    return deepcopy(beats)
