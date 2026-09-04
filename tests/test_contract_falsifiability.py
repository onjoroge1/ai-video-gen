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


def _codes(story):
    return {issue["code"] for issue in cs.validate_causal_story(story, ENGINE)["errors"]}


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
