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
    """A judge that kept a factual core and itemised nothing has flagged nothing to strip."""
    assert fidelity_severity([]) == "soft"
    assert fidelity_severity([], "", "partially_entailed") == "soft"


def test_an_unsupported_verdict_blocks_even_with_nothing_itemised():
    """Severity softens `partially_entailed` and nothing else.

    "Hundreds of secret overnight rat farms appeared" was rejected by the judge as unsupported
    with no itemised details, and the severity filter read the empty list as soft and let it
    through -- a fail-open hole in the one boundary that stops invented narration. Unsupported
    means no factual core was found at all; there is nothing left to be lenient about.
    """
    assert fidelity_severity([], "", "unsupported") == "material"
    assert fidelity_severity(["across open ground"], "", "unsupported") == "material"
    assert fidelity_severity([], "", "unavailable") == "material"


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


KNOWN = ("african honey bees were imported into brazil in 1956 by kerr. european honey bees were "
         "already present. twenty-six queens escaped with small swarms. a local beekeeper removed "
         "the queen excluders in october 1957.")


def test_a_name_the_evidence_already_carries_is_not_an_invention():
    """The film's own subject was tripping the rule: "Brazil's European bees" and "the forest
    gained African honey bee colonies" were classed material because the words are capitalised,
    while every claim in the dossier says them."""
    for detail in ("Brazil's European bees",
                   "The forest gained African honey bee colonies.",
                   "Twenty-six African queens with small swarms later escaped."):
        assert fidelity_severity([detail], KNOWN) == "soft", detail


def test_a_name_the_evidence_does_not_carry_still_blocks():
    assert fidelity_severity(["Warwick Kerr personally carried them"], KNOWN) == "material"
    assert fidelity_severity(["The colony was found in 1990"], KNOWN) == "material"


def test_an_actor_is_material_even_when_the_evidence_mentions_that_role():
    """The risk is the ACTION, not the noun: the dossier mentions a beekeeper, which does not
    license "a beekeeper backs away through the grove"."""
    assert fidelity_severity(["A beekeeper backs away through the grove."], KNOWN) == "material"


def test_without_a_known_blob_the_old_strictness_holds():
    assert fidelity_severity(["Brazil's European bees"]) == "material"


def test_a_dispute_about_word_choice_is_soft():
    """The judge phrases findings as commentary -- "Calling it a defensive response" -- and the
    capitalised framing verb was read as a proper noun, so word-choice disputes blocked renders.
    A viewer is not misled about a fact by "defensive response" instead of "defensive behaviour".
    """
    for detail in ('Calling it a defensive response',
                   'Calling them "African honey-bee" queens rather than Africanized queens',
                   'Saying the queens escaped rather than were released',
                   'Describing the spread as continuous'):
        assert fidelity_severity([detail], KNOWN) == "soft", detail


def test_word_choice_exemption_does_not_swallow_an_invented_actor():
    assert fidelity_severity(["A beekeeper backs away through the grove"], KNOWN) == "material"


def test_a_spelled_number_the_evidence_writes_in_digits_is_not_invented():
    """The dossier says "26"; the narration says "Twenty-six". Same fact, different spelling.

    The exemption is a substring test, so the film's own headline number read as a fabrication
    and blocked the run -- on a video titled for those twenty-six queens.
    """
    known = ("african honey bees were imported into brazil in 1956. 26 queens escaped with small "
             "swarms. 29 colonies were kept in hive boxes.")
    assert fidelity_severity(["Twenty-six African queens, small swarms"], known,
                             "partially_entailed") == "soft"
    assert fidelity_severity(["Twenty-nine colonies remained."], known,
                             "partially_entailed") == "soft"


def test_a_figure_the_evidence_does_not_carry_is_still_invented():
    """A duration COMPUTED from two sourced dates is exactly what the hook rules call invented."""
    known = "african honey bees were imported into brazil in 1956. 26 queens escaped."
    assert fidelity_severity(["Thirty-three years later."], known, "partially_entailed") == "material"
    assert fidelity_severity(["The year was 1962."], known, "partially_entailed") == "material"


def test_an_actor_the_evidence_puts_there_is_not_invented():
    """The bee dossier's own sentence was blocking every script that used it.

    "In October 1957, a local beekeeper noticed the queen excluders and removed them" is the
    documented turning point of the film, and the hook rules tell the planner to open on exactly
    that gesture. The actor rule was absolute -- a person doing a thing is a claim, whatever the
    dossier says -- so the classifier refused every script that obeyed those rules.
    """
    known = ("in october 1957 a local beekeeper noticed the queen excluders and removed them. "
             "26 queens escaped.")
    assert fidelity_severity(["A local beekeeper removed the queen excluders."], known,
                             "partially_entailed") == "soft"


def test_an_actor_the_evidence_never_mentions_still_blocks():
    """The exemption is for the documented actor, not for actors in general."""
    known = ("in october 1957 a local beekeeper noticed the queen excluders and removed them.")
    assert fidelity_severity(["A rancher burned the hives."], known,
                             "partially_entailed") == "material"
    assert fidelity_severity(["A geneticist redesigned them."], known,
                             "partially_entailed") == "material"
