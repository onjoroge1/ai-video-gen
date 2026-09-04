"""The causal-story contract, graded against the two reference videos it was derived from.

`causal_cobra_effect.json` is the video the contract was built from, so it must validate — if a
change breaks it, the change has drifted from the reference. `causal_bengal_famine.json` was held
out: it is the same storytelling mode with a different close, and it caught the contract
overfitting the first video's ending.
"""
import json
from pathlib import Path

import pytest

import causal_story as cs
import story_engines as se

# Own directory: story_engine.selftest() globs every json under fixtures/story and
# grades it with its own gates, which do not apply to this contract.
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "causal"
REFERENCES = ("cobra_effect.json", "bengal_famine.json")


def _story(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["story"]


def _valid_story():
    return json.loads(json.dumps(_story("cobra_effect.json")))


@pytest.mark.parametrize("name", REFERENCES)
def test_both_reference_videos_validate(name):
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    report = cs.validate_causal_story(payload["story"])
    assert report["passed"] is payload["expect"]["pass"], report["errors"]


def test_the_held_out_video_uses_a_verdict_close_not_a_tool():
    """The generalization test that caught the overfit.

    The contract was derived from the cobra video, whose close hands the opening object back as a
    question. The famine video closes on a verdict instead. Requiring the first shape rejected a
    perfectly good reference, so both are contract-legal.
    """
    roles = {step["role"] for step in _story("bengal_famine.json")["steps"]}
    assert cs.VERDICT in roles and cs.TOOL not in roles
    assert cs.GENERALIZATION not in roles  # and generalization stays optional


def test_a_fact_list_fails_even_when_it_is_perfectly_spaced():
    """The defect the positional arc could not see.

    Six true, evenly distributed facts satisfy any position-derived arc. They have no causal
    edges to offer, so the chain check is what rejects them.
    """
    report = cs.validate_causal_story({
        "runtime_sec": 220.0,
        "hook": {"line": "Six things to know about the cobra effect."},
        "steps": [{"step_id": f"f{i}", "role": "escalation", "start_sec": i * 25.0,
                   "chapter": 1, "situation": f"Fact number {i}."} for i in range(6)],
    })
    assert report["passed"] is False
    assert "ORPHAN_STEP" in {error["code"] for error in report["errors"]}


def test_a_step_caused_by_a_later_step_is_rejected():
    story = _valid_story()
    story["steps"][1]["caused_by"] = "worse"      # caused by the reversal, ten steps later
    codes = {e["code"] for e in cs.validate_causal_story(story)["errors"]}
    assert "BACKWARD_CAUSE" in codes


def test_a_dangling_cause_is_rejected():
    story = _valid_story()
    story["steps"][2]["caused_by"] = "no_such_step"
    codes = {e["code"] for e in cs.validate_causal_story(story)["errors"]}
    assert "DANGLING_CAUSE" in codes


def test_the_mechanism_must_land_in_the_first_fifth():
    """Both references state their principle at 16.4% and 19.4% of runtime."""
    story = _valid_story()
    for step in story["steps"]:
        if step["role"] == cs.MECHANISM:
            step["start_sec"] = story["runtime_sec"] * 0.6
    codes = {e["code"] for e in cs.validate_causal_story(story)["errors"]}
    assert "LATE_MECHANISM" in codes


def test_a_long_hinge_is_not_a_hinge():
    story = _valid_story()
    for step in story["steps"]:
        if step["role"] == cs.HINGE:
            step["situation"] = " ".join(["word"] * (cs.MAX_HINGE_WORDS + 5))
    codes = {e["code"] for e in cs.validate_causal_story(story)["errors"]}
    assert "SOFT_HINGE" in codes


def test_a_hook_that_names_its_withheld_subject_has_no_gap():
    story = _valid_story()
    story["hook"]["line"] = "How the British made the cobras much worse."
    codes = {e["code"] for e in cs.validate_causal_story(story)["errors"]}
    assert "SUBJECT_NOT_WITHHELD" in codes


def test_callback_check_ignores_articles():
    """`opening_object.split()[0]` matched the stopword "the", so the check passed on any close."""
    story = _story("bengal_famine.json")
    assert story["opening_object"].startswith("the ")
    assert cs.validate_causal_story(story)["passed"] is True

    broken = json.loads(json.dumps(story))
    broken["steps"][-1]["situation"] = "The people responsible were never charged with anything."
    codes = {e["code"] for e in cs.validate_causal_story(broken)["errors"]}
    assert "NO_CALLBACK" in codes


def test_chapters_are_a_separate_layer_from_the_causal_chain():
    """12 causal steps across 6 spoken chapters in one reference, 11 across 4 in the other.

    Treating the two as one spine is what made the predicted step spine drift from the spoken
    markers by up to 31 seconds.
    """
    cobra = cs.validate_causal_story(_story("cobra_effect.json"))
    famine = cs.validate_causal_story(_story("bengal_famine.json"))
    assert (len(cobra["steps"]), cobra["chapter_count"]) == (12, 6)
    assert (len(famine["steps"]), famine["chapter_count"]) == (11, 4)


def test_chapter_numbering_cannot_skip_or_reverse():
    story = _valid_story()
    story["steps"][5]["chapter"] = 9
    codes = {e["code"] for e in cs.validate_causal_story(story)["errors"]}
    assert "CHAPTER_GAP" in codes


@pytest.mark.parametrize("name", REFERENCES)
def test_reference_transcripts_score_full_marks(name):
    """The bands are drawn from these two videos, so both must sit inside every one of them.

    This is calibration, not proof of quality: it fails loudly if a band is ever tightened past
    the material it was measured from.
    """
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    report = cs.grade(payload["story"])
    assert report["structure_passed"] is True
    assert report["metrics"], "grading produced no metrics"
    mechanism = next(m for m in report["metrics"] if m["metric"] == "mechanism_pct")
    assert mechanism["in_band"], mechanism


def test_grading_discriminates_against_the_answer_every_so_often_shape():
    """The shape being replaced: restate the answer at intervals instead of demonstrating it."""
    narration = (
        "The cobra effect is when a solution makes a problem worse. "
        "In colonial India the government wanted fewer cobras in the city of Delhi. "
        "The answer is that incentives can be gamed by the people they are offered to. "
        "Breeding cobras at home became widespread because it was inexpensive and reliable. "
        "The answer is that the measure replaced the goal it was intended to track. "
        "The administration understood what had happened and ended the bounty programme. "
        "The answer is that cancelling an incentive can be as damaging as creating one."
    )
    fair_runtime = len(narration.split()) / 180.0 * 60.0
    report = cs.grade({"runtime_sec": fair_runtime, "steps": [], "hook": {}},
                      narration=narration)
    assert report["structure_passed"] is False
    assert report["score"] < 70.0
    out = {m["metric"] for m in report["out_of_band"]}
    assert "step_markers" in out and "short_landing_pct" in out


def test_measure_narration_reads_the_reference_cadence():
    """Long sentence, then a short landing — the rhythm both references run on."""
    text = ("The colonial government believed the bounty would reduce the number of snakes in "
            "the city within a single season. It did not. The population grew instead.")
    report = cs.measure_narration(text, runtime_sec=text.count(" ") / 3.0)
    metrics = {m["metric"]: m["value"] for m in report["metrics"]}
    assert metrics["short_landing_pct"] > 0.5


def test_story_direction_states_what_the_validator_enforces():
    direction = cs.story_direction("Why did the bounty backfire?")
    assert "caused_by" in direction
    assert f"{cs.MIN_CHAPTERS}-{cs.MAX_CHAPTERS} spoken chapters" in direction
    assert "State the mechanism ONCE" in direction


def test_hook_is_measured_from_its_own_field_not_the_first_sentence():
    """Found by the live generation: a 12-word hook scored as two words.

    A transcript opens on its hook, so sentence one is the right fallback. A generated script
    keeps the hook in its own field and opens the narration on a chapter marker, so measuring
    sentence one read "Step one." and reported a two-word hook.
    """
    narration = "Step one. A long opening sentence that carries the story forward from here."
    assert next(m for m in cs.measure_narration(narration, 60.0)["metrics"]
                if m["metric"] == "hook_words")["value"] == 2.0
    measured = cs.measure_narration(
        narration, 60.0, hook="A city's proudest machine became the very thing it paid to destroy.")
    hook = next(m for m in measured["metrics"] if m["metric"] == "hook_words")
    assert hook["value"] == 12.0 and hook["in_band"]


def _roles(steps):
    return [step["role"] for step in steps]


def _bare(roles):
    """Steps with placeholder prose, except where a check actually reads the words.

    The hinge checks look at the sentence itself — a question or a bare signpost is not a turn —
    so a one-character placeholder there trips a real check with fake input.
    """
    return [{"step_id": f"s{i}", "role": role, "chapter": 0, "caused_by": "",
             "situation": ("The rivers never reached the sea again."
                           if role == cs.HINGE else "x")}
            for i, role in enumerate(roles)]


def test_repair_fixes_the_exact_shape_the_first_real_run_returned():
    """setup x2, false_resolution x3, verdict x2, escalations after the reversal.

    Every one of those is a label mistake on a sound beat order, so repair relabels rather than
    reorders — narration order is the planner's to own.
    """
    observed = ["setup", "escalation", "intervention", "setup", "mechanism", "escalation",
                "false_resolution", "false_resolution", "hinge", "escalation", "reversal",
                "generalization", "escalation", "verdict", "generalization", "verdict"]
    fixed, changes = cs.repair_chain(_bare(observed))
    roles = _roles(fixed)

    assert changes, "a broken chain must report what it changed"
    for role in (cs.SETUP, cs.INTERVENTION, cs.FALSE_RESOLUTION, cs.HINGE, cs.MECHANISM,
                 cs.REVERSAL):
        assert roles.count(role) == 1, f"{role} should be a singleton, got {roles.count(role)}"
    assert roles[0] == cs.SETUP and roles[-1] in cs.CLOSING_ROLES
    assert roles.index(cs.HINGE) > roles.index(cs.FALSE_RESOLUTION)
    # Nothing but generalization and the close may follow the reversal.
    assert set(roles[roles.index(cs.REVERSAL) + 1:]) <= {cs.GENERALIZATION} | set(cs.CLOSING_ROLES)


def test_repair_leaves_a_chain_that_validates():
    observed = ["setup", "escalation", "intervention", "setup", "mechanism", "escalation",
                "false_resolution", "hinge", "escalation", "reversal", "escalation", "verdict"]
    fixed, _ = cs.repair_chain(_bare(observed))
    report = cs.validate_causal_story({
        "runtime_sec": 200.0,
        "hook": {"line": "A sea the size of Ireland vanished in one lifetime."},
        "start_state": "the sea was there", "opening_object": "the trawler",
        # Keep the hinge's own prose: the hinge checks read the sentence, so overwriting it with
        # a placeholder would fail a real check on fake input.
        "steps": [{**step, "start_sec": index * 8.0,
                   "situation": ("the trawler" if index == len(fixed) - 1
                                 else step["situation"] if step["role"] == cs.HINGE else "x")}
                  for index, step in enumerate(fixed)],
    })
    assert report["passed"] is True, report["errors"]


def test_repair_never_reorders_the_beats():
    observed = ["setup", "reversal", "escalation", "mechanism", "verdict"]
    steps = _bare(observed)
    fixed, _ = cs.repair_chain(steps)
    assert [step["step_id"] for step in fixed] == [step["step_id"] for step in steps]


def test_repair_is_idempotent():
    """A second pass over an already-legal chain must change nothing."""
    once, _ = cs.repair_chain(_bare(
        ["setup", "intervention", "false_resolution", "hinge", "mechanism",
         "escalation", "escalation", "reversal", "tool"]))
    twice, changes = cs.repair_chain(once)
    assert _roles(twice) == _roles(once)
    assert not [c for c in changes if "role" in c]


def test_repair_demotes_a_generalization_that_precedes_the_reversal():
    fixed, _ = cs.repair_chain(_bare(
        ["setup", "escalation", "generalization", "escalation", "reversal", "verdict"]))
    roles = _roles(fixed)
    assert roles.index(cs.REVERSAL) < len(roles) - 1
    assert cs.GENERALIZATION not in roles[:roles.index(cs.REVERSAL)]


def test_repair_rebuilds_dangling_and_backward_causal_edges():
    steps = _bare(["setup", "escalation", "escalation", "reversal", "verdict"])
    steps[0]["caused_by"] = "s3"        # the setup cannot be caused by anything
    steps[2]["caused_by"] = "nope"      # dangling
    steps[3]["caused_by"] = "s4"        # backward: caused by a later beat
    fixed, changes = cs.repair_chain(steps)
    assert fixed[0]["caused_by"] == ""
    assert fixed[2]["caused_by"] == "s1"
    assert fixed[3]["caused_by"] == "s2"
    assert any("caused_by" in change for change in changes)


def test_finalize_normalizes_the_spine_without_editing_prose():
    """The spoken marker is mechanical, so it is done in code. The hinge is not.

    This test used to assert the opposite — that an over-long hinge was trimmed to its "turn"
    sentence. Two versions of that trim shipped and both damaged scripts: the first relocated
    sentences across scene boundaries, the second deleted them. The deletion picked by content-word
    count, which on a real example threw away "The plan failed completely" and kept a weaker line.

    Narration is now never edited for length. The marker is normalised; the hinge is reported by
    SOFT_HINGE and the run fails before any spend, which is free and reversible.
    """
    scenes = [
        {"chapter": 1, "causal_role": "setup", "narration": "A trawler sits on cracked desert."},
        {"chapter": 2, "causal_role": "hinge",
         "narration": ("Here is the strange part. Both rivers still flow today, full and strong. "
                       "They just stop short of the sea entirely, ending in dust.")},
        {"chapter": 3, "causal_role": "escalation", "narration": "Step nine. The canals leaked."},
    ]
    changes = cs.finalize_narration(scenes)
    assert changes

    # Every sentence of the hinge survives, including the one an earlier trim would have dropped.
    hinge = scenes[1]["narration"]
    for sentence in ("Here is the strange part", "Both rivers still flow today",
                     "They just stop short of the sea"):
        assert sentence in hinge
    assert any("left intact" in change for change in changes)

    # The spine is still normalised: markers added where missing, wrong numbers corrected.
    assert scenes[0]["narration"] == "Step one. A trawler sits on cracked desert."
    assert scenes[1]["narration"].startswith("Step two.")
    assert scenes[2]["narration"].startswith("Step three.")
    assert all(cs._MARKER.match(scene["narration"]) for scene in scenes)


def test_the_spoken_marker_does_not_spend_the_hinge_budget():
    report = cs.validate_causal_story({
        "runtime_sec": 100.0, "hook": {"line": "A short hook that promises the turn."},
        "start_state": "before", "opening_object": "the trawler",
        "steps": [
            {"step_id": "a", "role": "setup", "chapter": 1, "start_sec": 0, "situation": "x"},
            {"step_id": "b", "role": "intervention", "chapter": 1, "caused_by": "a",
             "start_sec": 5, "situation": "x"},
            {"step_id": "c", "role": "false_resolution", "chapter": 2, "caused_by": "b",
             "start_sec": 10, "situation": "x"},
            {"step_id": "d", "role": "hinge", "chapter": 3, "caused_by": "c", "start_sec": 15,
             "situation": "Step three. Both rivers still flow today, full and strong."},
            {"step_id": "e", "role": "mechanism", "chapter": 3, "caused_by": "d",
             "start_sec": 18, "situation": "x"},
            {"step_id": "f", "role": "escalation", "chapter": 4, "caused_by": "e",
             "start_sec": 25, "situation": "x"},
            {"step_id": "g", "role": "escalation", "chapter": 4, "caused_by": "f",
             "start_sec": 30, "situation": "x"},
            {"step_id": "h", "role": "reversal", "chapter": 4, "caused_by": "g",
             "start_sec": 40, "situation": "x"},
            {"step_id": "i", "role": "verdict", "chapter": 4, "caused_by": "h",
             "start_sec": 50, "situation": "the trawler"},
        ]})
    assert "SOFT_HINGE" not in {error["code"] for error in report["errors"]}


def test_a_marker_repeated_inside_a_chapter_is_removed():
    """A live run announced "Step one" again three scenes into chapter one.

    The spine is a reset device; repeating a number reads as the story restarting a chapter it is
    already inside, and it pushed the marker count past the reference band as well.
    """
    scenes = [
        {"chapter": 1, "causal_role": "setup", "narration": "Step one. A trawler on dry sand."},
        {"chapter": 1, "causal_role": "escalation",
         "narration": "Step one. The obvious suspect is drought."},
        {"chapter": 2, "causal_role": "escalation", "narration": "Engineers cut the canals."},
    ]
    changes = cs.finalize_narration(scenes)
    assert scenes[0]["narration"].startswith("Step one.")
    assert scenes[1]["narration"] == "The obvious suspect is drought."
    assert scenes[2]["narration"].startswith("Step two.")
    assert any("duplicate marker" in change for change in changes)
    assert sum(1 for scene in scenes if cs._MARKER.match(scene["narration"])) == 2


def test_a_hinge_before_the_false_resolution_is_relabelled():
    """The defect that failed the fourth live run; repair had no rule for this ordering."""
    observed = ["setup", "escalation", "hinge", "mechanism", "intervention", "escalation",
                "false_resolution", "escalation", "escalation", "reversal", "verdict"]
    fixed, _ = cs.repair_chain(_bare(observed))
    roles = _roles(fixed)
    assert roles.index(cs.HINGE) > roles.index(cs.FALSE_RESOLUTION)
    assert roles.count(cs.HINGE) == 1


def test_a_misnumbered_spoken_chapter_is_caught():
    """Chapters read one, one, two, three, five, six, four, five and still scored in band.

    The marker count was checked; the sequence was not. Reading the transcript showed it
    instantly, which is the gap this closes.
    """
    steps = [
        {"step_id": "a", "role": "setup", "chapter": 1, "start_sec": 0,
         "situation": "Step one. A trawler on dry sand."},
        {"step_id": "b", "role": "intervention", "chapter": 2, "caused_by": "a", "start_sec": 10,
         "situation": "Step one. Engineers cut the canals."},          # says one, opens two
        {"step_id": "c", "role": "false_resolution", "chapter": 3, "caused_by": "b",
         "start_sec": 20, "situation": "Step three. The cotton grew."},
        {"step_id": "d", "role": "hinge", "chapter": 4, "caused_by": "c", "start_sec": 30,
         "situation": "Step four. The rivers never arrived."},
        {"step_id": "e", "role": "mechanism", "chapter": 4, "caused_by": "d", "start_sec": 35,
         "situation": "x"},
        {"step_id": "f", "role": "escalation", "chapter": 4, "caused_by": "e", "start_sec": 40,
         "situation": "x"},
        {"step_id": "g", "role": "escalation", "chapter": 4, "caused_by": "f", "start_sec": 45,
         "situation": "x"},
        {"step_id": "h", "role": "reversal", "chapter": 4, "caused_by": "g", "start_sec": 50,
         "situation": "x"},
        {"step_id": "i", "role": "verdict", "chapter": 4, "caused_by": "h", "start_sec": 55,
         "situation": "the trawler"},
    ]
    codes = {e["code"] for e in cs.validate_causal_story({
        "runtime_sec": 100.0, "hook": {"line": "A short hook that promises the turn."},
        "start_state": "before", "opening_object": "the trawler", "steps": steps})["errors"]}
    assert "CHAPTER_MISNUMBERED" in codes


def test_finalize_never_reduces_a_hinge_to_its_marker():
    """A live run produced a hinge whose entire text was "Step one."

    Trimming ran before markers were settled, so the injected marker was the only sentence inside
    the cap and the trim selected it as the turn of the video.
    """
    scenes = [{"chapter": 1, "causal_role": "setup", "narration": "A trawler on dry sand."},
              {"chapter": 2, "causal_role": "hinge",
               "narration": ("Here is the strange part. Both rivers still flow today, full and "
                             "strong. They stop short of the sea entirely.")}]
    cs.finalize_narration(scenes)
    hinge = cs._MARKER.sub("", scenes[1]["narration"]).strip()
    assert hinge and len(hinge.split()) >= 4, hinge
    assert "rivers still flow" in hinge


# --- engines -----------------------------------------------------------------------------------

def test_each_reference_validates_under_its_own_engine():
    """The engines are read off the two reference videos, not invented.

    Writing the indictment sequence from memory put intervention before the false resolution; the
    reference states its profitability first and the fixture rejected the guess. That is what the
    held-out fixture is for, and the engine data was corrected rather than the fixture.
    """
    import story_engines as se
    for name, engine_id in (("cobra_effect.json", se.BACKFIRING_SOLUTION),
                            ("bengal_famine.json", se.ACCUMULATING_INDICTMENT)):
        report = cs.validate_causal_story(_story(name), se.get(engine_id))
        assert report["passed"] is True, (name, report["errors"])
        assert report["engine"] == se.get(engine_id)["name"]


def test_a_story_run_against_the_wrong_engine_is_rejected():
    import story_engines as se
    report = cs.validate_causal_story(_story("cobra_effect.json"),
                                      se.get(se.ACCUMULATING_INDICTMENT))
    assert report["passed"] is False
    codes = {error["code"] for error in report["errors"]}
    assert codes & {"ENGINE_MISSING_ROLE", "ENGINE_ORDER", "ENGINE_CLOSE"}


def test_engines_constrain_but_do_not_uniquely_classify():
    """An honest limitation, asserted so it cannot be mistaken for a guarantee.

    A backfiring-solution story also satisfies the accidental-invention engine, because that
    engine never names a false resolution and the order check ignores roles it does not name. The
    engine enforces a DECLARED intent; it does not reverse-engineer which shape a script is.
    """
    import story_engines as se
    passing = [engine_id for engine_id in se.ENGINES
               if cs.validate_causal_story(_story("cobra_effect.json"),
                                           se.get(engine_id))["passed"]]
    assert se.BACKFIRING_SOLUTION in passing
    assert len(passing) > 1


def test_repair_closes_on_the_engines_own_ending():
    """Repairing to a generic verdict would hand a lens story an indictment ending.

    The engine check would then reject exactly what repair had just produced.
    """
    import story_engines as se
    roles = ["setup", "intervention", "false_resolution", "hinge", "mechanism",
             "escalation", "escalation", "reversal", "escalation"]
    fixed, _ = cs.repair_chain(_bare(roles), se.get(se.BACKFIRING_SOLUTION))
    assert fixed[-1]["role"] == cs.TOOL
    fixed, _ = cs.repair_chain(_bare(roles), se.get(se.ACCUMULATING_INDICTMENT))
    assert fixed[-1]["role"] == cs.VERDICT


def test_an_unknown_engine_falls_back_rather_than_losing_the_script():
    import story_engines as se
    assert se.resolve_id("no_such_engine") == se.DEFAULT_ENGINE
    assert se.get("")["name"] == se.ENGINES[se.DEFAULT_ENGINE]["name"]


def test_the_catalogue_and_the_validator_cannot_disagree():
    """The prompt text is generated from the same data the validator checks."""
    import story_engines as se
    catalogue = se.catalogue()
    for engine_id, engine in se.ENGINES.items():
        assert engine_id in catalogue
        assert " -> ".join(engine["sequence"]) in catalogue


def test_order_is_checked_on_milestones_not_on_connective_tissue():
    """Escalation repeats and runs throughout, so it is not an ordered position.

    Including it required a story to place its first escalation after its mechanism, which no
    reference does. Both references still validate, so this loosens a modelling error rather than
    the contract: the milestone sequence is unchanged and still enforced.
    """
    import story_engines as se
    engine = se.get(se.BACKFIRING_SOLUTION)
    roles = ["setup", "escalation", "intervention", "false_resolution", "hinge", "mechanism",
             "escalation", "reversal", "tool"]
    steps = [{"step_id": f"s{i}", "role": r, "chapter": (i // 3) + 1, "caused_by": "",
              "start_sec": i * 5.0, "situation": "the trawler" if r == "tool" else "x"}
             for i, r in enumerate(roles)]
    steps, _ = cs.repair_chain(steps, engine)
    codes = {e["code"] for e in cs.validate_causal_story(
        {"runtime_sec": 200.0, "hook": {"line": "A short hook that promises the turn."},
         "start_state": "before", "opening_object": "the trawler", "steps": steps},
        engine)["errors"]}
    assert "ENGINE_ORDER" not in codes

    # A milestone genuinely out of order is still caught — mechanism before hinge is B's shape,
    # not A's, and this engine is A's.
    swapped = ["setup", "intervention", "false_resolution", "mechanism", "hinge",
               "escalation", "escalation", "reversal", "tool"]
    steps = [{"step_id": f"s{i}", "role": r, "chapter": (i // 3) + 1, "caused_by": "",
              "start_sec": i * 5.0, "situation": "the trawler" if r == "tool" else "x"}
             for i, r in enumerate(swapped)]
    assert "ENGINE_ORDER" in {e["code"] for e in cs.validate_causal_story(
        {"runtime_sec": 200.0, "hook": {"line": "A short hook that promises the turn."},
         "start_state": "before", "opening_object": "the trawler", "steps": steps},
        engine)["errors"]}


def test_a_question_is_not_a_hinge():
    """A live run labelled "So which drained it faster, hotter summers or the missing rivers?"

    That poses a choice; it breaks nothing, and the story carried on unturned. Both reference
    hinges are flat statements, so the distinction is checkable rather than a matter of taste.
    """
    def _hinge(text):
        steps = [
            {"step_id": "a", "role": "setup", "chapter": 1, "start_sec": 0, "situation": "x"},
            {"step_id": "b", "role": "intervention", "chapter": 1, "caused_by": "a",
             "start_sec": 5, "situation": "x"},
            {"step_id": "c", "role": "false_resolution", "chapter": 2, "caused_by": "b",
             "start_sec": 10, "situation": "x"},
            {"step_id": "d", "role": "hinge", "chapter": 2, "caused_by": "c", "start_sec": 15,
             "situation": text},
            {"step_id": "e", "role": "mechanism", "chapter": 3, "caused_by": "d",
             "start_sec": 20, "situation": "x"},
            {"step_id": "f", "role": "escalation", "chapter": 3, "caused_by": "e",
             "start_sec": 25, "situation": "x"},
            {"step_id": "g", "role": "escalation", "chapter": 3, "caused_by": "f",
             "start_sec": 30, "situation": "x"},
            {"step_id": "h", "role": "reversal", "chapter": 4, "caused_by": "g",
             "start_sec": 40, "situation": "x"},
            {"step_id": "i", "role": "verdict", "chapter": 4, "caused_by": "h",
             "start_sec": 50, "situation": "the trawler"},
        ]
        return {e["code"] for e in cs.validate_causal_story({
            "runtime_sec": 100.0, "hook": {"line": "A short hook that promises the turn."},
            "start_state": "before", "opening_object": "the trawler", "steps": steps})["errors"]}

    assert "HINGE_IS_A_QUESTION" in _hinge("So which drained it faster, rain or rivers?")
    assert "HINGE_IS_A_SIGNPOST" in _hinge("Here is the part that matters.")
    # Both references are flat statements and must stay legal.
    assert not _hinge("Except the problem is not solved.") & {
        "HINGE_IS_A_QUESTION", "HINGE_IS_A_SIGNPOST"}
    assert not _hinge("The system works perfectly until the rains stop.") & {
        "HINGE_IS_A_QUESTION", "HINGE_IS_A_SIGNPOST"}


def test_a_mood_beat_needs_no_citation_but_a_factual_one_still_does():
    """`false_relief` asserted a feeling and was required to cite a source for it.

    The role trigger was narrowed, not the content trigger. A false-relief beat that states
    something checkable is still caught, so nothing that makes a claim became exempt.
    """
    import longform_research as lr

    mood = "For a moment, it all looks final. A sea erased, a desert that fights back."
    factual = "For three years the dam held, and the water rose by 12 metres."

    assert "false_relief" not in lr.FACT_ROLES
    assert lr._asserts_fact(mood) is False
    assert lr._asserts_fact(factual) is True

    def unbound(role, narration):
        report = lr.validate_claim_joins(
            {"scenes": [{"narration": narration, "story_role": role, "claim_refs": []}]},
            {"claims": [{"claim_id": "c01", "claim": "x", "source_url": "https://example.org/a",
                         "support_quote": "q", "source_type": "primary", "confidence": "high"}],
             "citation_urls": ["https://example.org/a"],
             "citation_records": [{"url": "https://example.org/a", "cited_text": "q"}]})
        return any(e["code"] == "unbound_factual_scene" for e in report["errors"])

    assert unbound("false_relief", mood) is False        # a mood beat is not a claim
    assert unbound("false_relief", factual) is True      # a factual one still is
    assert unbound("mechanism", mood) is True            # other roles keep the role trigger


# --- the spoken hook, the reserved clock, and the per-engine deadline ---------------------------

def test_the_hook_is_spoken_before_the_chapter_marker():
    """The video used to open on the literal numeral "Step one."

    `script["hook"]` reached only the YouTube description. Both references open on a promise
    sentence and say the number second, which is why their first step starts at 5.0s and 3.0s
    rather than zero — that gap is the hook being spoken.
    """
    scenes = [{"chapter": 1, "causal_role": "setup", "narration": "A trawler sits on cracked sand."},
              {"chapter": 2, "causal_role": "escalation", "narration": "The canals leaked."}]
    cs.finalize_narration(scenes, hook="How one fix made the problem worse",
                          format_tag="explained like you are five")
    first = scenes[0]["narration"]
    assert first.startswith("How one fix made the problem worse.")
    assert "Explained like you are five." in first      # capitalised as its own sentence
    assert "Step one." in first
    assert first.index("Step one.") > first.index("worse.")
    # Later chapters get the marker alone — the hook is not repeated.
    assert scenes[1]["narration"] == "Step two. The canals leaked."


def test_without_a_hook_the_marker_still_leads():
    scenes = [{"chapter": 1, "causal_role": "setup", "narration": "A trawler on sand."}]
    cs.finalize_narration(scenes)
    assert scenes[0]["narration"] == "Step one. A trawler on sand."


def test_all_three_references_validate_under_their_declared_engine():
    """Two derived from videos, one written by an operator. The third caught two contract errors."""
    import story_engines as se
    for name, engine_id in (("cobra_effect.json", se.BACKFIRING_SOLUTION),
                            ("bengal_famine.json", se.ACCUMULATING_INDICTMENT),
                            ("hippo_weed.json", se.ALMOST_HAPPENED_PLAN)):
        payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        report = cs.validate_causal_story(payload["story"], se.get(engine_id))
        assert report["passed"] is payload["expect"]["pass"], (name, report["errors"])


def test_the_reveal_deadline_is_per_engine_not_a_global_loosening():
    """A reveal-structured story cannot state its principle first — the principle IS the ending.

    The hippo reveal lands at 55%. Engines built on the two reference videos keep the measured 20%
    deadline (16.4% and 19.4% observed), so the same story is still rejected by them. That is the
    difference between an engine-specific architecture and lowering the bar.
    """
    import story_engines as se
    story = json.loads((FIXTURES / "hippo_weed.json").read_text(encoding="utf-8"))["story"]

    assert cs.validate_causal_story(story, se.get(se.ALMOST_HAPPENED_PLAN))["passed"] is True
    late = {e["code"] for e in
            cs.validate_causal_story(story, se.get(se.BACKFIRING_SOLUTION))["errors"]}
    assert "LATE_MECHANISM" in late, "the measured 20% deadline must still bind its own engines"

    assert cs.MECHANISM_DEADLINE_PCT == 0.20, "the global default must not have been lowered"
    assert se.mechanism_deadline_pct(se.get(se.BACKFIRING_SOLUTION), 0.20) == 0.20
    assert se.mechanism_deadline_pct(se.get(se.ALMOST_HAPPENED_PLAN), 0.20) > 0.20


# --- PR1 correctness regressions ---------------------------------------------------------------
#
# Four bugs an external review found, all reproducible in one line each, none caught by the tests
# that existed. Two of them were introduced by the hook change in the same session that shipped it:
# the tests passed because they called finalize_narration once and never checked the arithmetic.

def test_finalize_narration_is_idempotent():
    """A second pass used to prepend another copy of hook + tag + marker.

    `_MARKER` strips only "Step one.", so the hook survived into `body` and was re-added. Nothing
    calls this twice today, but a retry or a second normalisation pass would have doubled the
    opening of every video.
    """
    lead = dict(hook="A simple plan made everything worse",
                format_tag="explained like you are five")
    scenes = [{"chapter": 1, "causal_role": "setup", "narration": "A problem begins."},
              {"chapter": 2, "causal_role": "escalation", "narration": "It gets worse."}]
    cs.finalize_narration(scenes, **lead)
    once = [scene["narration"] for scene in scenes]
    cs.finalize_narration(scenes, **lead)
    assert [scene["narration"] for scene in scenes] == once
    assert once[0].count("Step one.") == 1
    assert once[0].count("A simple plan made everything worse") == 1


def test_the_hinge_is_reported_never_trimmed():
    """The trim deleted the turn and kept a weaker sentence.

    Selecting by content-word count, "Important evidence was discovered later" (4) beat "The plan
    failed completely" (3), so the reversal was removed and the run reported success. There is no
    reliable way to find a story's turn by counting words, and a wrong guess is unrecoverable.
    """
    scenes = [{"chapter": 1, "causal_role": "hinge",
               "narration": ("Here is the strange part. The plan failed completely. "
                             "Important evidence was discovered later.")}]
    changes = cs.finalize_narration(scenes)

    assert "The plan failed completely." in scenes[0]["narration"]
    assert "Important evidence was discovered later." in scenes[0]["narration"]
    assert any("left intact" in change for change in changes)


def test_an_over_long_hinge_still_fails_validation():
    """Not trimming must not mean not noticing."""
    steps = [
        {"step_id": "a", "role": "setup", "chapter": 1, "start_sec": 0, "situation": "x"},
        {"step_id": "b", "role": "intervention", "chapter": 1, "caused_by": "a",
         "start_sec": 4, "situation": "x"},
        {"step_id": "c", "role": "false_resolution", "chapter": 2, "caused_by": "b",
         "start_sec": 8, "situation": "x"},
        {"step_id": "d", "role": "hinge", "chapter": 2, "caused_by": "c", "start_sec": 12,
         "situation": " ".join(["word"] * 25)},
        {"step_id": "e", "role": "mechanism", "chapter": 3, "caused_by": "d",
         "start_sec": 14, "situation": "x"},
        {"step_id": "f", "role": "escalation", "chapter": 3, "caused_by": "e",
         "start_sec": 20, "situation": "x"},
        {"step_id": "g", "role": "escalation", "chapter": 4, "caused_by": "f",
         "start_sec": 30, "situation": "x"},
        {"step_id": "h", "role": "reversal", "chapter": 4, "caused_by": "g",
         "start_sec": 40, "situation": "x"},
        {"step_id": "i", "role": "tool", "chapter": 4, "caused_by": "h",
         "start_sec": 50, "situation": "the trawler"},
    ]
    codes = {e["code"] for e in cs.validate_causal_story({
        "runtime_sec": 100.0, "hook": {"line": "A short hook that promises the turn."},
        "start_state": "before", "opening_object": "the trawler", "steps": steps})["errors"]}
    assert "SOFT_HINGE" in codes


def test_a_stray_closing_beat_is_demoted_to_a_role_the_engine_has():
    """Generalization was the unconditional demotion target. For an engine whose sequence has no
    generalization that invents a beat which can never pass — a generalization needs two parallel
    cases, and accumulating_indictment fetches none by design. A render died on
    THIN_GENERALIZATION for a beat the repair itself had created."""
    steps = [{"step_id": "s1", "role": "setup", "caused_by": "", "chapter": 1},
             {"step_id": "s2", "role": "escalation", "caused_by": "s1", "chapter": 1},
             {"step_id": "s3", "role": "verdict", "caused_by": "s2", "chapter": 2},
             {"step_id": "s4", "role": "verdict", "caused_by": "s3", "chapter": 2}]
    fixed, _ = cs.repair_chain(steps, se.get(se.ACCUMULATING_INDICTMENT))

    roles = [s["role"] for s in fixed]
    assert cs.GENERALIZATION not in roles, "this engine has no generalization in its sequence"
    assert all(role in se.get(se.ACCUMULATING_INDICTMENT)["sequence"] for role in roles), \
        "repair must only ever produce roles the declared engine actually runs"
    assert fixed[-1]["role"] == cs.VERDICT, "the real close survives"


def test_an_engine_that_has_generalization_still_gets_it():
    steps = [{"step_id": "s1", "role": "setup", "caused_by": "", "chapter": 1},
             {"step_id": "s2", "role": "tool", "caused_by": "s1", "chapter": 1},
             {"step_id": "s3", "role": "tool", "caused_by": "s2", "chapter": 2}]
    fixed, _ = cs.repair_chain(steps, se.get(se.BACKFIRING_SOLUTION))
    assert fixed[1]["role"] == cs.GENERALIZATION
