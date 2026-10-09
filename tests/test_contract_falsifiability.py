"""Every contract check must be reachable — a check that cannot fail is not evidence.

This project has shipped unfalsifiable checks twice. The four-location budget was fed from a
lookup table that only ever produced four values, so it could not exceed four. The story arc was
derived from scene position, so `payoff` needed 26 scenes to occur and a flat fact list scored a
clean "reversal". Both looked like working guards in the source and in the logs.

So this mutates a passing fixture once per error code and asserts the code actually fires. It is
deliberately exhaustive rather than representative: the failure mode is a check quietly becoming
decorative after an unrelated edit, and only enumerating all of them catches that.
"""
import copy
import json
import re
from pathlib import Path

import pytest

import causal_story as cs
import story_engines as se

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "causal" / "cobra_effect.json"
ENGINE = se.get(se.BACKFIRING_SOLUTION)


def _base():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["story"]


def _with_synthesis(s, text):
    """Insert a synthesis step before the close, as the compiler would."""
    close = s["steps"][-1]
    s["steps"].insert(len(s["steps"]) - 1, {
        "step_id": "syn", "role": "synthesis", "situation": text, "chapter": close["chapter"],
        "caused_by": s["steps"][-2]["step_id"], "start_sec": close["start_sec"] - 1.0})
    close["caused_by"] = "syn"


def _codes(story):
    engine = se.get(se.BACKFIRING_SOLUTION, compiled=bool(story.get("compiled")))
    report = cs.validate_causal_story(story, engine)
    # Warnings are declared with the same _issue(...) call and must be falsifiable too.
    return {issue["code"] for issue in report["errors"] + (report.get("warnings") or [])}


def _mutate(fn):
    story = copy.deepcopy(_base())
    fn(story)
    return story


def _declared_codes():
    source = (Path(cs.__file__)).read_text(encoding="utf-8")
    return set(re.findall(r'_issue\(\s*"([A-Z_]+)"', source))


# One mutation per error code. Each breaks exactly the property its check defends.
MUTATIONS = {
    "NO_STEPS":            lambda s: s.update(steps=[]),
    "UNKNOWN_ROLE":        lambda s: s["steps"][3].update(role="wat"),
    "DUPLICATE_ROLE":      lambda s: s["steps"][3].update(role="setup"),
    "MISSING_ROLE":        lambda s: s["steps"][0].update(role="escalation"),
    "THIN_CHAIN":          lambda s: s.update(
        steps=[x for x in s["steps"] if x["role"] != "escalation"]),
    "UNEARNED_HINGE":      lambda s: s["steps"][2].update(role="escalation"),
    "BAD_OPENING":         lambda s: s["steps"].insert(
        0, {**s["steps"][5], "step_id": "x0", "caused_by": ""}),
    "BAD_CLOSE":           lambda s: s["steps"][-1].update(role="escalation"),
    "HINGE_BEFORE_RESOLUTION": lambda s: (s["steps"][2].update(role="hinge"),
                                          s["steps"][3].update(role="false_resolution")),
    "ESCALATION_AFTER_REVERSAL": lambda s: s["steps"][-2].update(role="escalation"),
    "EARLY_GENERALIZATION": lambda s: s["steps"][1].update(role="generalization"),
    "CAUSED_SETUP":        lambda s: s["steps"][0].update(caused_by="bounty"),
    "ORPHAN_STEP":         lambda s: s["steps"][4].update(caused_by=""),
    "DANGLING_CAUSE":      lambda s: s["steps"][4].update(caused_by="nope"),
    "BACKWARD_CAUSE":      lambda s: s["steps"][2].update(caused_by="worse"),
    "NO_CHAPTERS":         lambda s: [x.pop("chapter", None) for x in s["steps"]],
    "STEP_OUTSIDE_CHAPTER": lambda s: s["steps"][4].pop("chapter", None),
    "CHAPTER_GAP":         lambda s: s["steps"][5].update(chapter=9),
    "CHAPTER_OUT_OF_ORDER": lambda s: (s["steps"][1].update(chapter=4),
                                       s["steps"][2].update(chapter=1)),
    "CHAPTER_COUNT":       lambda s: [x.update(chapter=1) for x in s["steps"]],
    "NO_RUNTIME":          lambda s: s.update(runtime_sec=0),
    "UNORDERED_TIMELINE":  lambda s: s["steps"][5].update(start_sec=1.0),
    "LATE_MECHANISM":      lambda s: s["steps"][4].update(start_sec=200.0),
    "NO_HOOK":             lambda s: s["hook"].update(line=""),
    "LONG_HOOK":           lambda s: s["hook"].update(line=" ".join(["word"] * 30)),
    "MULTI_SENTENCE_HOOK": lambda s: s["hook"].update(line="One thing. Two things."),
    "SUBJECT_NOT_WITHHELD": lambda s: s["hook"].update(line="How the cobras got much worse."),
    "SUBJECT_NEVER_PAID_OFF": lambda s: s["hook"].update(withheld_subject="zebras"),
    "SOFT_HINGE":          lambda s: s["steps"][3].update(situation=" ".join(["word"] * 25)),
    "HINGE_IS_A_QUESTION": lambda s: s["steps"][3].update(situation="So which one was it?"),
    "HINGE_IS_A_SIGNPOST": lambda s: s["steps"][3].update(situation="Here is the thing."),
    "NO_START_STATE":      lambda s: s.update(start_state=""),
    "NULL_REVERSAL":       lambda s: s["steps"][9].update(situation=s["start_state"]),
    "NO_OPENING_OBJECT":   lambda s: s.update(opening_object=""),
    "NO_CALLBACK":         lambda s: s["steps"][-1].update(situation="Nothing relevant at all."),
    # The sentence-mix bands fire only for scripts stamped with the joint contract; the cobra
    # reference opens 1 of 11 steps on a joint, so the stamp alone trips JOINT_BAND.
    # The planted-number close fires only under its contract; the cobra close is one sentence and
    # re-speaks nothing, so a numbered hook plus the stamp trips both blocking codes.
    "NO_NUMBER_CALLBACK":  lambda s: (s.update(close_contract="planted_callback_v1"),
                                      s["hook"].update(line="Twenty-six cobras left your street; "
                                                            "that is not the strangest part.")),
    "CLOSE_SENTENCE_COUNT": lambda s: s.update(close_contract="planted_callback_v1"),
    "NEGATION_LIST_UNRETURNED": lambda s: (s.update(close_contract="planted_callback_v1"),
                                           s["hook"].update(line="No fans, no ice, no electricity "
                                                                 "kept anyone cool.")),
    # The synthesis: demanded only on the compiled lane above its runtime floor (the cobra
    # reference has none and must keep validating); each shape defect is its own code.
    "SYNTHESIS_MISSING":   lambda s: s.update(compiled=True, runtime_sec=300.0),
    "SYNTHESIS_BEFORE_REVERSAL": lambda s: s["steps"][1].update(role="synthesis"),
    "SYNTHESIS_TOO_THIN":  lambda s: _with_synthesis(s, "Recap."),
    "SYNTHESIS_TOO_LONG":  lambda s: _with_synthesis(s, "The bounty paid. " * 6),
    "SYNTHESIS_SKIPS_A_BEAT": lambda s: _with_synthesis(
        s, "Nothing here touches the chain at all. Nor does this sentence, which only fills space."),
    "SYNTHESIS_ADDS_HISTORY": lambda s: _with_synthesis(
        s, "The bounty paid for tails, so farms bred cobras. Then Texas banned the trade in 1911."),
    # Under the ladder a body beat may not re-tell the opening: the last escalation repeats the setup.
    "OPENING_RESTATED":    lambda s: (s.update(opening_contract="ladder_v1"),
                                      next(x for x in reversed(s["steps"]) if x["role"] == "escalation")
                                      .update(situation=s["steps"][0]["situation"])),
    # Under the ladder the opening's consequence must be spoken before the mechanism: the
    # planner cites a claim no step binds (V14, 2026-10-08).
    "OPENING_CONSEQUENCE_UNSPOKEN": lambda s: s.update(opening_contract="ladder_v1",
                                                       opening_consequence_claims=["c_never"]),
    # A continuation part that re-tells its parent (V15, 2026-10-08: Florida twice).
    "CONTINUATION_REPEATS": lambda s: (s.update(opening_contract="ladder_v1"),
                                       (lambda esc: s["steps"].insert(s["steps"].index(esc) + 1, {
                                           **esc, "step_id": esc["step_id"] + "b",
                                           "continues": esc["step_id"],
                                           "start_sec": esc["start_sec"] + 0.5}))(
                                           next(x for x in s["steps"] if x["role"] == "escalation"))),
    # A scene opening on "That <noun>" that nothing named (V15: "That wall held for years").
    "DANGLING_REFERENCE": lambda s: (s.update(opening_contract="ladder_v1"),
                                     next(x for x in s["steps"] if x["role"] == "escalation")
                                     .update(situation="That zeppelin held for years. "
                                             + next(x for x in s["steps"] if x["role"] == "escalation")["situation"])),
    # A close assuming an outcome the reversal never told (V15: "if the fix filled the harvest").
    "CLOSE_PRESUPPOSES_OUTCOME": lambda s: (s.update(opening_contract="ladder_v1"),
                                            s["steps"][-1].update(situation=s["steps"][-1]["situation"]
                                                                  + " So the plan finally succeeded.")),
    # A second synthesis part re-walking the same beats as the first (V14, 2026-10-08).
    "SYNTHESIS_REPEATED":  lambda s: (_with_synthesis(s, "The bounty paid for tails, so farms bred "
                                                         "cobras and the trade ended."),
                                      s["steps"].insert(len(s["steps"]) - 1, {
                                          "step_id": "syn2", "role": "synthesis", "continues": "syn",
                                          "situation": "The bounty paid for tails, so farms bred cobras.",
                                          "chapter": s["steps"][-1]["chapter"], "caused_by": "syn",
                                          "start_sec": s["steps"][-1]["start_sec"] - 0.5}),
                                      s["steps"][-1].update(caused_by="syn2")),
    "JOINT_BAND":          lambda s: s.update(sentence_mix_contract="joints_v1"),
    "ADDRESS_BAND":        lambda s: (s.update(sentence_mix_contract="joints_v1"),
                                      [x.update(situation=re.sub(r"\b[Yy]ou(?:r)?\b", "they", x["situation"]))
                                       for x in s["steps"]]),
    "MIX_BAND":            lambda s: (s.update(sentence_mix_contract="joints_v1"),
                                      [x.update(situation="The bounty paid for every tail handed in.")
                                       for x in s["steps"]]),
    "FACT_RUN":            lambda s: (s.update(sentence_mix_contract="joints_v1"),
                                      [x.update(situation="The bounty paid for every tail handed in. "
                                                          "The count rose every month.")
                                       for x in s["steps"]]),
    "THIN_GENERALIZATION": lambda s: s.update(parallel_cases=[]),
    "UNPARALLEL_CASE":     lambda s: s.update(parallel_cases=[{"domain": "d"}, {"domain": "e"}]),
    "ENGINE_MISSING_ROLE": lambda s: s["steps"][1].update(role="escalation"),
    "ENGINE_ORDER":        lambda s: (s["steps"][1].update(role="mechanism"),
                                      s["steps"][4].update(role="intervention")),
    "ENGINE_CLOSE":        lambda s: s["steps"][-1].update(role="verdict"),
    "CHAPTER_MISNUMBERED": lambda s: s["steps"][0].update(
        situation="Step four. " + s["steps"][0]["situation"]),
    "CHAPTER_NOT_ANNOUNCED": lambda s: s["steps"][0].update(
        situation="Step one. " + s["steps"][0]["situation"]),
    # An escalation that leaves this story for the comparison it was saving for the generalization.
    # The word has to be one the story does not already use about itself, or the check correctly
    # reads it as the story's own vocabulary rather than an imported case.
    "PARALLEL_CASE_OUT_OF_PLACE": lambda s: (
        s.update(parallel_cases=[{"domain": "Hanoi", "problem": "rats", "solution": "tail bounty",
                                  "result": "farmed rats"}]),
        s["steps"][5].update(situation="The same trap sprang shut in Hanoi in 1902.")),
}


def test_the_reference_fixture_is_clean():
    """Every mutation below is measured against this, so it must start with zero errors."""
    assert _codes(_base()) == set()


@pytest.mark.parametrize("code", sorted(MUTATIONS))
def test_each_check_can_actually_fire(code):
    assert code in _codes(_mutate(MUTATIONS[code])), (
        f"{code} did not fire for a mutation that breaks exactly what it defends — "
        "it is unreachable and defends nothing")


def test_every_declared_code_has_a_mutation():
    """A new check without a mutation here is a check nobody has proven can fail."""
    missing = _declared_codes() - set(MUTATIONS)
    assert not missing, f"error codes with no falsifiability test: {sorted(missing)}"
