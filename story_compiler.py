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

import event_functions as ef
import story_fact_model as sfm


def function_of(beat: dict) -> str:
    return (sfm._text((beat or {}).get("event_function"))).strip().lower()


def incentive_of(beat: dict) -> dict:
    block = (beat or {}).get("incentive")
    block = block if isinstance(block, dict) else {}
    return {"rewarded_measure": sfm._text(block.get("rewarded_measure")).strip(),
            "actual_goal": sfm._text(block.get("actual_goal")).strip(),
            "goal_claim_refs": [sfm._text(r) for r in (block.get("goal_claim_refs") or [])
                                if sfm._text(r)]}


def _state(beat: dict, side: str) -> str:
    block = (beat or {}).get("changes_state")
    block = block if isinstance(block, dict) else {}
    return sfm._text(block.get(side)).strip()


def derive_mechanism(intervention: dict) -> dict:
    """The mechanism is `rewarded_measure != actual_goal`, and both halves must be sourced.

    `rewarded_measure` is a fact about the policy and 4 of 5 measured sheets already stated it
    correctly. `actual_goal` is an attribution of intent to whoever wrote the policy -- the exact
    category the fidelity boundary flags in narration -- so putting it in a schema field does not
    make it true. It carries its own claim_refs or the mechanism does not compile.
    """
    incentive = incentive_of(intervention)
    beat_id = sfm._text((intervention or {}).get("beat_id"))
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
    if sfm._stems(incentive["rewarded_measure"]) == sfm._stems(incentive["actual_goal"]):
        return {"ok": False, "code": "NO_PROXY_GAP",
                "message": f"beat {beat_id} rewards the same thing it wants, so there is no "
                           "mechanism for the story to turn on"}
    return {"ok": True, "role": "mechanism",
            "event": {"text": f"The reward was paid for {incentive['rewarded_measure']}, "
                              f"not for {incentive['actual_goal']}.",
                      "claim_refs": sorted(set(sfm.event_of(intervention)["claim_refs"])
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
    ok, why = ef.inverts_setup_property(before, after, sfm._stems)
    if not ok:
        return {"ok": False, "code": "NO_INVERSION",
                "message": f"the end state {after[:70]!r} does not invert a property of the setup: "
                           f"{why}"}
    return {"ok": True, "role": "reversal",
            "event": {"text": sfm.event_of(compounds)["text"],
                      "claim_refs": sfm.event_of(compounds)["claim_refs"]},
            "changes_state": {"from": before, "to": after},
            "derived_from": [sfm._text(setup.get("beat_id")), sfm._text(compounds.get("beat_id"))]}


def compile_roles(beats: list[dict], engine_id: str) -> dict:
    """Assign every story role from the beats' factual functions. Nothing here asks a model."""
    mapping = ef.map_for(engine_id)
    if mapping is None:
        return {"compiled": False, "reason": f"{engine_id or 'engine'} still assigns roles itself",
                "beats": list(beats or []), "issues": []}

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
        role = mapping.role_for(function)
        if role:
            beat["role"] = role
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

    derived = []
    if len(interventions) == 1:
        mechanism = derive_mechanism(interventions[0])
        (derived.append(mechanism) if mechanism["ok"]
         else issues.append(sfm._issue(mechanism["code"], mechanism["message"])))
    setups = by_function.get(ef.ESTABLISHES_PROBLEM) or []
    compounds = by_function.get(ef.COMPOUNDS_EXPLOIT) or []
    if setups and compounds:
        reversal = derive_reversal(setups[0], compounds[-1])
        (derived.append(reversal) if reversal["ok"]
         else issues.append(sfm._issue(reversal["code"], reversal["message"])))

    return {"compiled": True, "engine": mapping.engine_id, "beats": out,
            "derived": derived, "issues": issues,
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
        return {"beat_id": f"{entry['role']}_derived", "n": number, "role": entry["role"],
                "event_function": "", "derived": True, "derived_from": entry["derived_from"],
                "beat": entry["event"]["text"], "event": entry["event"],
                "changes_state": entry["changes_state"], "scope": sfm.PRIMARY_STORY,
                "claim_refs": [{"claim_id": ref} for ref in entry["event"]["claim_refs"]],
                "caused_by": source, "chapter": 0}

    out: list[dict] = []
    for beat in beats:
        out.append(beat)
        if "mechanism" in derived and function_of(beat) == ef.CHANGES_INCENTIVE:
            out.append(_made(derived.pop("mechanism"), 0))
    if "reversal" in derived:
        tail = next((index for index, beat in enumerate(out)
                     if function_of(beat) in (ef.PARALLEL_CASE,)), len(out))
        out.insert(tail, _made(derived.pop("reversal"), 0))
    for index, beat in enumerate(out):
        beat["n"] = index + 1
        beat.setdefault("beat_id", f"beat_{index + 1:02d}")
    return out
