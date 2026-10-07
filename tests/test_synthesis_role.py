"""A synthesis beat re-walks the chain before the close (change #1, 2026-10-06).

The 552 s reference spends ~14% of its runtime re-speaking every mechanism as a cause -> cost
pair ("each one solving a problem the last one had created") before it closes; our films jump
from the reversal to a one-line takeaway, which is what the judge's story 41 / ending 29 and
'a list of facts' describe. The role exists in the contract, is sized by the template, added by
the compiler, exempted from STATE-ONCE for exactly one beat, and measured for free.
"""
import causal_story as cs
import story_compiler as sc
import story_engines as se
import story_template as st
from test_story_compiler import MACQUARIE

CHAIN = [
    ("setup", "European honey bees struggled in Brazil."),
    ("intervention", "Kerr brought African queens to Brazil for honey."),
    ("hinge", "Except the queens did not stay in their boxes."),
    ("mechanism", "Queens and drones escaped and hybridized with the local population."),
    ("escalation", "A beekeeper removed the excluders and twenty-six queens left with swarms."),
    ("escalation", "Colonies grew and swarmed more often than European colonies."),
    ("escalation", "Disturbed, a greater proportion of the colony responded with stings."),
    ("escalation", "Africanized bees were detected in Arizona in 1993."),
    ("reversal", "Brazilian beekeeping shifted to Africanized bees."),
]
GOOD = ("The excluders came away, so twenty-six queens left for the forest. Escaped queens "
        "hybridized and the colonies swarmed. Disturbed, more of the colony stung; Arizona "
        "followed, and beekeeping shifted.")


def _steps(synthesis=GOOD, close="Ask what else escaped your plan besides the bees."):
    rows = CHAIN + ([("synthesis", synthesis)] if synthesis is not None else []) + [("tool", close)]
    return [{"step_id": f"s{i}", "role": r, "situation": t, "chapter": 1 + i // 4,
             "caused_by": f"s{i - 1}" if i else "", "start_sec": i * 28.0}
            for i, (r, t) in enumerate(rows)]


def _codes(steps, runtime=300.0, compiled=True):
    engine = se.get("removed_keystone", compiled=compiled)
    report = cs.validate_causal_story({"runtime_sec": runtime, "steps": steps,
                                       "opening_object": "the bees", "start_state": "low honey",
                                       "hook": {"line": "Your hive could face twenty-six queens."}},
                                      engine)
    return {i["code"] for i in report["errors"] if i["code"].startswith("SYNTHESIS")}


def test_a_synthesis_built_from_the_chains_own_words_passes():
    assert _codes(_steps()) == set()


def test_it_is_demanded_only_on_the_compiled_lane_above_the_floor():
    assert _codes(_steps(synthesis=None)) == {"SYNTHESIS_MISSING"}
    assert _codes(_steps(synthesis=None), compiled=False) == set()
    assert _codes(_steps(synthesis=None), runtime=120.0) == set()


def test_each_shape_defect_has_its_own_code():
    assert "SYNTHESIS_TOO_THIN" in _codes(_steps("The chain again, briefly."))
    assert "SYNTHESIS_TOO_LONG" in _codes(_steps("The queens left. " * 6))
    skipped = _codes(_steps("The excluders came away, so twenty-six queens left. Beekeeping shifted "
                            "to the new bees at last."))
    assert "SYNTHESIS_SKIPS_A_BEAT" in skipped
    history = _codes(_steps(GOOD + " Then Texas banned the trade in 1911."))
    assert "SYNTHESIS_ADDS_HISTORY" in history
    # A number an earlier step spoke may be re-spoken: that is the point of the beat.
    assert "SYNTHESIS_ADDS_HISTORY" not in _codes(_steps())
    before = _steps()
    before.insert(1, {"step_id": "early", "role": "synthesis", "situation": GOOD, "chapter": 1,
                      "caused_by": "s0", "start_sec": 10.0})
    assert "SYNTHESIS_BEFORE_REVERSAL" in _codes(before)


def test_repair_leaves_a_compiler_placed_synthesis_alone():
    steps = cs._normalize_steps(_steps())
    repaired, changes = cs.repair_chain(steps, se.get("removed_keystone", compiled=True))
    assert [s["role"] for s in repaired] == [s["role"] for s in steps]
    assert not any("synthesis" in c for c in changes)


def test_the_template_reserves_the_slot_only_above_the_floor():
    assert cs.synthesis_planned(se.get("removed_keystone"), 300) is True
    assert cs.synthesis_planned(se.get("removed_keystone"), 120) is False
    assert cs.synthesis_planned(se.get("removed_keystone"), 0) is False
    assert cs.synthesis_planned(se.get("accumulating_indictment"), 300) is False
    slots = st.build_slots("removed_keystone", 300)
    roles = [s["role"] for s in slots]
    assert roles[-3:] == ["reversal", "synthesis", "takeaway"]
    syn = slots[-2]
    assert syn["needs_claim"] is False and syn["words_min"] == cs.SYNTHESIS_MIN_WORDS
    assert syn["words_max"] <= 49
    assert "synthesis" not in [s["role"] for s in st.build_slots("removed_keystone", 120)]
    assert se.minimum_beats(se.get("removed_keystone")) == se.minimum_beats(
        se.get("removed_keystone", compiled=True)) + 0  # sequence, not required


def test_the_compiler_adds_the_device_between_reversal_and_close():
    out = sc.compile_roles(MACQUARIE, "removed_keystone")
    beats = sc.splice_derived(out["beats"], out)
    long = sc.presentation_beats(beats, "removed_keystone", duration_sec=300)
    roles = [b["role"] for b in long]
    assert roles.index("synthesis") == roles.index("tool") - 1
    assert roles.index("synthesis") > roles.index("reversal")
    syn = next(b for b in long if b["role"] == "synthesis")
    assert syn["event"] == {"text": "", "claim_refs": []}
    chain = [b["beat_id"] for b in long if b["role"] in ("mechanism", "escalation", "reversal")]
    assert syn["context_refs"] == chain
    assert syn["claim_refs"], "inherits the chain's claims through context_refs"
    assert "re-walk EVERY mechanism and escalation" in syn["beat"]
    short = sc.presentation_beats(beats, "removed_keystone", duration_sec=120)
    assert "synthesis" not in [b["role"] for b in short]
    unknown = sc.presentation_beats(beats, "removed_keystone")
    assert "synthesis" not in [b["role"] for b in unknown]
