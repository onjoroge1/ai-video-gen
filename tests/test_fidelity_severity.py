"""A narration overshoot blocks only if a viewer could repeat it as a fact and be wrong.

Fifteen runs died on this gate. Every one of the phrases in the soft list below was refused as
invented history, and none of them can mislead anyone. Narrowing the judge's prose three times
produced a fresh crop each round, so the threshold was the thing that was wrong, not the wording.
"""
import pytest

from longform_research import fidelity_severity

SOFT = [
    "The bees were in a landscape.",             # setting the event already locates
    "across open ground",
    "The swarm is dark.",                        # staging in a cold open
    "became established",                        # the claim says "became established"
    "that the colony was not inside a crate",    # derived by NEGATION, never asserted
    "The hive boxes stood open.",
]

MATERIAL = [
    "Warwick Kerr brought them into Brazil.",    # a named person doing a thing
    "A beekeeper backs away.",                   # an invented actor and action
    "twenty-six swarms escaped",                 # a number in words, and the wrong noun
    "The colony was found in 1990",              # a date
    "hundreds of farms",                         # a quantity
    "behind mud-brick walls in Hanoi",           # a place
]


@pytest.mark.parametrize("detail", SOFT)
def test_soft_overshoot_does_not_block(detail):
    assert fidelity_severity([detail]) == "soft"


@pytest.mark.parametrize("detail", MATERIAL)
def test_material_overshoot_still_blocks(detail):
    assert fidelity_severity([detail]) == "material"


def test_one_material_detail_makes_the_whole_finding_blocking():
    assert fidelity_severity(["The swarm is dark.", "twenty-six queens escaped"]) == "material"


def test_no_details_is_soft():
    assert fidelity_severity([]) == "soft"


def _report(fidelity_details, **over):
    """A cascade report shaped like story_fact_model.validate_cascade returns."""
    import story_fact_model as sfm
    base = {"structural": [], "evidence": [], "unavailable": [], "passed": False,
            "structure_status": sfm.STRUCTURE_PASS, "indeterminate_kinds": [],
            "skipped_for_structure": [],
            "fidelity": [{"beat_id": f"b{i}", "passed": False, "verdict": "partially_entailed",
                          "unsupported_details": d}
                         for i, d in enumerate(fidelity_details)]}
    base.update(over)
    return base


def test_soft_only_fidelity_lets_the_ledger_pass(monkeypatch):
    """The cascade marks itself failed for ANY fidelity row, so filtering errors alone was never
    enough: the verdict has to be rebuilt from the parts. Fifteen runs died on exactly this."""
    import longform_research as lr
    import story_fact_model as sfm
    monkeypatch.setattr(sfm, "validate_cascade",
                        lambda *a, **k: _report([["The bees were in a landscape."],
                                                 ["across open ground"]]))
    monkeypatch.setattr(sfm, "_validate_relationships", lambda *a, **k: [])
    monkeypatch.setattr(lr, "script_has_events", lambda s: True, raising=False)
    out = lr.validate_story_fact_model(
        {"hook": "", "scenes": [{"beat_id": "b0", "causal_role": "setup",
                                 "event": {"text": "x", "claim_refs": []}, "narration": "y"}]},
        {"claims": []})
    assert out["passed"], out["errors"]
    assert len(out["soft_findings"]) == 2


def test_one_material_fidelity_row_still_blocks(monkeypatch):
    import longform_research as lr
    import story_fact_model as sfm
    monkeypatch.setattr(sfm, "validate_cascade",
                        lambda *a, **k: _report([["The bees were in a landscape."],
                                                 ["twenty-six swarms escaped"]]))
    monkeypatch.setattr(sfm, "_validate_relationships", lambda *a, **k: [])
    monkeypatch.setattr(lr, "script_has_events", lambda s: True, raising=False)
    out = lr.validate_story_fact_model(
        {"hook": "", "scenes": [{"beat_id": "b0", "causal_role": "setup",
                                 "event": {"text": "x", "claim_refs": []}, "narration": "y"}]},
        {"claims": []})
    assert not out["passed"]


def test_structural_and_evidence_failures_still_block_absolutely(monkeypatch):
    import longform_research as lr
    import story_fact_model as sfm
    monkeypatch.setattr(sfm, "validate_cascade",
                        lambda *a, **k: _report([], evidence=[{"beat_id": "b0", "verdict": "unsupported",
                                                               "reason": "no", "supported_core": "",
                                                               "unsupported_details": []}]))
    monkeypatch.setattr(sfm, "_validate_relationships", lambda *a, **k: [])
    monkeypatch.setattr(lr, "script_has_events", lambda s: True, raising=False)
    out = lr.validate_story_fact_model(
        {"hook": "", "scenes": [{"beat_id": "b0", "causal_role": "setup",
                                 "event": {"text": "x", "claim_refs": []}, "narration": "y"}]},
        {"claims": []})
    assert not out["passed"]
