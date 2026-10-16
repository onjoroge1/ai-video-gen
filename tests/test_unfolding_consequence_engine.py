"""World's present-consequence shape: a fix and what it released, still unfolding (2026-10-15).

Chernobyl's first planned sheet was handed backfiring_solution, filed the evacuation as
`changes_incentive`, and its mechanism would have compiled as "The reward was paid for ..." for a
safety test that paid no reward. removed_keystone needs a moved species and state_programme is
History's. unfolding_consequence is compiled like state_programme and closes on World's tool.
No provider is called here.
"""
import causal_story as cs
import backfire_packaging
import event_functions as ef
import explainer_pipeline as ep
import illustrated_score
import opening_turn
import story_compiler as sc
import story_engines as se
import story_fact_model as sfm
import story_template as st
import topic_fit as tf

CHERNOBYL = [
    {"beat_id": "u1", "event_function": ef.ESTABLISHES_PROBLEM,
     "event": {"text": "The test was designed to show a coasting turbine could power the coolant "
                       "pumps until the backup generators started.", "claim_refs": ["c02"]},
     "changes_state": {"from": "a reactor with a gap in a blackout",
                       "to": "a test planned to close the gap"}},
    {"beat_id": "u2", "event_function": ef.FIX_ADOPTED,
     "event": {"text": "To run the test, operators lowered the power and switched off several "
                       "safety systems.", "claim_refs": ["c04"]},
     "changes_state": {"from": "a test planned to close the gap",
                       "to": "the reactor at low power with safety systems off"}},
    {"beat_id": "u3", "event_function": ef.APPARENT_SUCCESS,
     "event": {"text": "They pressed AZ-5, the emergency shutdown button.", "claim_refs": ["c04"]},
     "changes_state": {"from": "the reactor at low power with safety systems off",
                       "to": "the shutdown button pressed"}},
    {"beat_id": "u4", "event_function": ef.CONSEQUENCE_PATHWAY,
     "event": {"text": "The core surged out of control and exploded.", "claim_refs": ["c04"]},
     "changes_state": {"from": "the shutdown button pressed",
                       "to": "radioactive material scattered"}},
    {"beat_id": "u5", "event_function": ef.CONSEQUENCE_SPREADS,
     "event": {"text": "Some 350,000 people were evacuated from around the plant.",
               "claim_refs": ["c24"]},
     "changes_state": {"from": "radioactive material scattered", "to": "the land emptied"}},
    {"beat_id": "u6", "event_function": ef.CONSEQUENCE_SPREADS,
     "event": {"text": "Caesium-137 has a half-life of 30 years.", "claim_refs": ["c34"]},
     "changes_state": {"from": "the land emptied", "to": "the contamination persists"}},
    {"beat_id": "u7", "event_function": ef.STILL_UNFOLDING,
     "event": {"text": "Repairs to the breached shelter could cost at least 500 million euros.",
               "claim_refs": ["c51"]},
     "changes_state": {"from": "the contamination persists",
                       "to": "a breached shelter and a closed zone forty years on"}},
]


def test_a_fix_compiles_without_inventing_an_incentive_or_a_derivation():
    out = sc.compile_roles(CHERNOBYL, se.UNFOLDING_CONSEQUENCE)
    assert out["passed"], sc.summary(out)
    assert out["roles"] == {"u1": "setup", "u2": "intervention", "u3": "false_resolution",
                            "u4": "mechanism", "u5": "escalation", "u6": "escalation",
                            "u7": "reversal"}
    assert out["derived"] == [], "the pathway is a recorded fact, not a reward-versus-goal gap"


def test_the_pathway_and_the_present_state_are_required_the_apparent_success_is_not():
    for missing in (ef.CONSEQUENCE_PATHWAY, ef.STILL_UNFOLDING, ef.FIX_ADOPTED):
        sheet = [b for b in CHERNOBYL if b["event_function"] != missing]
        codes = [i["code"] for i in sc.compile_roles(sheet, se.UNFOLDING_CONSEQUENCE)["issues"]]
        assert "MISSING_EVENT_FUNCTION" in codes, missing
    without = [b for b in CHERNOBYL if b["event_function"] != ef.APPARENT_SUCCESS]
    assert sc.compile_roles(without, se.UNFOLDING_CONSEQUENCE)["passed"]


def test_the_compiler_adds_its_own_turn_and_a_tool_close_in_engine_order():
    out = sc.compile_roles(CHERNOBYL, se.UNFOLDING_CONSEQUENCE)
    beats = sc.presentation_beats(sc.splice_derived(out["beats"], out), se.UNFOLDING_CONSEQUENCE,
                                  duration_sec=300)
    roles = [b["role"] for b in beats]
    assert roles.count("hinge") == 1 and roles[-1] == "tool" and "verdict" not in roles
    order = se.expected_order(se.UNFOLDING_CONSEQUENCE)
    assert [order.index(r) for r in roles] == sorted(order.index(r) for r in roles)
    hinge = next(b for b in beats if b["role"] == "hinge")
    assert "what the fix set loose" in str(hinge)
    assert "reward" not in str(hinge).lower()


def test_a_recorded_warning_is_the_turn():
    warning = {"beat_id": "u3w", "event_function": ef.WARNING_RECORDED,
               "event": {"text": "The reactor's positive void coefficient was a known feature "
                                 "of its design.", "claim_refs": ["c07"]},
               "changes_state": {"from": "the shutdown button pressed",
                                 "to": "the danger on record"}}
    sheet = CHERNOBYL[:3] + [warning] + CHERNOBYL[3:]
    out = sc.compile_roles(sheet, se.UNFOLDING_CONSEQUENCE)
    assert out["passed"], sc.summary(out)
    assert out["roles"]["u3w"] == "hinge"


def test_the_engine_fits_a_five_minute_film_and_the_template_asks_for_one_of_each_singleton():
    assert ep._engine_runtime_fit(se.UNFOLDING_CONSEQUENCE, 300)["fits"]
    counts = st.role_counts(se.UNFOLDING_CONSEQUENCE, 300)
    for role in ("setup", "intervention", "false_resolution", "mechanism", "reversal"):
        assert counts[role] == 1, role
    assert counts["escalation"] >= cs.MIN_ESCALATIONS


def test_the_planner_is_shown_fix_functions_not_a_bounty_or_a_species():
    prompt = sc.factual_plan_prompt("Why can't anyone live at Chernobyl, 40 years later?", 300, 16,
                                    se.UNFOLDING_CONSEQUENCE)
    for function in (ef.FIX_ADOPTED, ef.CONSEQUENCE_PATHWAY, ef.CONSEQUENCE_SPREADS,
                     ef.STILL_UNFOLDING):
        assert function in prompt
    for absent in (ef.CHANGES_INCENTIVE, ef.SPECIES_MOVED, ef.PROGRAMME_IMPOSED):
        assert absent not in prompt


def test_physical_processes_may_carry_the_consequence():
    for role in ("setup", "escalation", "reversal"):
        assert "mechanism" in sfm.accepted_claim_kinds(role, se.UNFOLDING_CONSEQUENCE)
    assert "mechanism" not in sfm.accepted_claim_kinds("intervention", se.UNFOLDING_CONSEQUENCE)


def test_it_is_a_world_shape_offered_to_world_and_kept_off_history():
    assert tf.engine_admitted(se.UNFOLDING_CONSEQUENCE, tf.WORLD)
    assert tf.engine_admitted(se.UNFOLDING_CONSEQUENCE, "")
    assert not tf.engine_admitted(se.UNFOLDING_CONSEQUENCE, tf.HISTORY)
    assert not tf.engine_admitted(se.UNFOLDING_CONSEQUENCE, tf.NATURE)
    assert se.UNFOLDING_CONSEQUENCE in ep._feasible_engines(300, tf.WORLD)


def test_world_packaging_score_and_turn_know_the_engine():
    assert se.UNFOLDING_CONSEQUENCE in backfire_packaging.ENGINES
    assert se.UNFOLDING_CONSEQUENCE in illustrated_score._MOODS
    assert se.UNFOLDING_CONSEQUENCE in opening_turn.TURN_ENGINES
    assert opening_turn.consequence_shape(se.UNFOLDING_CONSEQUENCE, ["c04"], ["c99"]) == "B"
