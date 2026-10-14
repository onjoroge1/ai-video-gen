"""History's own story shape: a state programme and what it cost (2026-10-14).

Radium Girls was planned under accumulating_indictment and Salem under backfiring_solution. The
first had no event map, so it fell through to the Alex/Bolt investigation contract ("No visible
evidence changes Alex's belief", "Bolt useful measurement"); the second asked a court for an
exploited reward. state_programme is compiled like removed_keystone and closes on a verdict.
No provider is called here.
"""
import causal_story as cs
import event_functions as ef
import explainer_pipeline as ep
import illustrated_score
import story_compiler as sc
import story_engines as se
import story_fact_model as sfm
import story_template as st
import topic_fit as tf

ARAL = [
    {"beat_id": "a1", "event_function": ef.ESTABLISHES_PROBLEM,
     "event": {"text": "In the 1950s Soviet planners wanted far more cotton from Central Asia.",
               "claim_refs": ["c1"]},
     "changes_state": {"from": "a region growing limited cotton",
                       "to": "planners set out to irrigate the desert"}},
    {"beat_id": "a2", "event_function": ef.PROGRAMME_IMPOSED,
     "event": {"text": "The state diverted the Amu Darya and Syr Darya into irrigation canals.",
               "claim_refs": ["c2"]},
     "changes_state": {"from": "planners set out to irrigate the desert",
                       "to": "the rivers feed cotton fields"}},
    {"beat_id": "a3", "event_function": ef.APPARENT_SUCCESS,
     "event": {"text": "Cotton harvests in Uzbekistan rose for decades.", "claim_refs": ["c3"]},
     "changes_state": {"from": "the rivers feed cotton fields", "to": "the plan delivers cotton"}},
    {"beat_id": "a4", "event_function": ef.HARM_PATHWAY,
     "event": {"text": "The diverted rivers no longer reached the Aral Sea.", "claim_refs": ["c4"]},
     "changes_state": {"from": "the plan delivers cotton", "to": "the sea loses its inflow"}},
    {"beat_id": "a5", "event_function": ef.HARM_ACCUMULATES,
     "event": {"text": "The shoreline retreated and the fishing port of Muynak was left inland.",
               "claim_refs": ["c5"]},
     "changes_state": {"from": "the sea loses its inflow", "to": "the fishing towns lose the sea"}},
    {"beat_id": "a6", "event_function": ef.HARM_ACCUMULATES,
     "event": {"text": "Dust from the exposed seabed carried salt and pesticide residue.",
               "claim_refs": ["c6"]},
     "changes_state": {"from": "the fishing towns lose the sea", "to": "the seabed blows inland"}},
    {"beat_id": "a7", "event_function": ef.COST_RECKONED,
     "event": {"text": "By 2014 the sea's eastern basin had dried completely.", "claim_refs": ["c7"]},
     "changes_state": {"from": "the seabed blows inland", "to": "a sea turned into desert"}},
]


def test_a_state_programme_compiles_without_inventing_an_incentive_or_a_derivation():
    out = sc.compile_roles(ARAL, se.STATE_PROGRAMME)
    assert out["passed"], sc.summary(out)
    assert out["roles"] == {"a1": "setup", "a2": "intervention", "a3": "false_resolution",
                            "a4": "mechanism", "a5": "escalation", "a6": "escalation",
                            "a7": "reversal"}
    assert out["derived"] == [], "the harm pathway is a recorded fact, not a computed relationship"


def test_the_harm_pathway_and_the_reckoning_are_required():
    for missing in (ef.HARM_PATHWAY, ef.COST_RECKONED, ef.PROGRAMME_IMPOSED):
        sheet = [b for b in ARAL if b["event_function"] != missing]
        codes = [i["code"] for i in sc.compile_roles(sheet, se.STATE_PROGRAMME)["issues"]]
        assert "MISSING_EVENT_FUNCTION" in codes, missing
    # The apparent success is optional: some programmes never looked like they worked.
    without = [b for b in ARAL if b["event_function"] != ef.APPARENT_SUCCESS]
    assert sc.compile_roles(without, se.STATE_PROGRAMME)["passed"]


def test_the_compiler_adds_its_own_turn_and_a_verdict_close_in_engine_order():
    out = sc.compile_roles(ARAL, se.STATE_PROGRAMME)
    beats = sc.presentation_beats(sc.splice_derived(out["beats"], out), se.STATE_PROGRAMME,
                                  duration_sec=300)
    roles = [b["role"] for b in beats]
    assert roles.count("hinge") == 1 and roles[-1] == "verdict" and "tool" not in roles
    order = se.expected_order(se.STATE_PROGRAMME)
    assert [order.index(r) for r in roles] == sorted(order.index(r) for r in roles)
    hinge = next(b for b in beats if b["role"] == "hinge")
    assert "cost the programme carried" in str(hinge)


def test_the_engine_fits_a_five_minute_film_and_the_template_asks_for_one_of_each_singleton():
    assert ep._engine_runtime_fit(se.STATE_PROGRAMME, 300)["fits"]
    counts = st.role_counts(se.STATE_PROGRAMME, 300)
    for role in ("setup", "intervention", "false_resolution", "mechanism", "reversal"):
        assert counts[role] == 1, role
    assert counts["escalation"] >= cs.MIN_ESCALATIONS


def test_the_planner_is_shown_history_functions_not_a_bounty():
    prompt = sc.factual_plan_prompt("What did the Aral Sea diversions cost?", 300, 20,
                                    se.STATE_PROGRAMME)
    for function in (ef.PROGRAMME_IMPOSED, ef.HARM_PATHWAY, ef.HARM_ACCUMULATES, ef.COST_RECKONED):
        assert function in prompt
    assert ef.CHANGES_INCENTIVE not in prompt


def test_histories_written_as_processes_may_carry_the_cost():
    for role in ("setup", "escalation", "reversal"):
        assert "mechanism" in sfm.accepted_claim_kinds(role, se.STATE_PROGRAMME)
    assert "mechanism" not in sfm.accepted_claim_kinds("intervention", se.STATE_PROGRAMME)


def test_state_programme_is_history_only_and_history_uses_only_compiled_shapes():
    assert tf.engine_admitted(se.STATE_PROGRAMME, tf.HISTORY)
    for channel in (tf.WORLD, tf.NATURE, ""):
        assert not tf.engine_admitted(se.STATE_PROGRAMME, channel), channel
    assert tf.engine_admitted(se.BACKFIRING_SOLUTION, tf.WORLD)
    for engine in tf.engines_for_channel(tf.HISTORY):
        assert ef.map_for(engine) is not None, f"{engine} would fall through to the Alex/Bolt contract"


def test_the_score_has_a_mood_for_the_engine():
    assert se.STATE_PROGRAMME in illustrated_score._MOODS


def test_a_recorded_warning_is_the_turn_and_replaces_the_compilers_device():
    """The Aral sheet filed 'hydrologists understood before the canals were built' as context,
    which is never narrated; a History film without its warning is a natural disaster."""
    warning = {"beat_id": "a2w", "event_function": ef.WARNING_RECORDED,
               "event": {"text": "Soviet hydrologists understood before the main canals were built "
                                 "that the diversions would make the sea's level drop sharply.",
                         "claim_refs": ["c43"]},
               "changes_state": {"from": "the plan delivers cotton",
                                 "to": "the cost is known in advance"}}
    sheet = ARAL[:3] + [warning] + ARAL[3:]
    out = sc.compile_roles(sheet, se.STATE_PROGRAMME)
    assert out["passed"], sc.summary(out)
    assert out["roles"]["a2w"] == "hinge"
    beats = sc.presentation_beats(sc.splice_derived(out["beats"], out), se.STATE_PROGRAMME,
                                  duration_sec=300)
    hinges = [b for b in beats if b["role"] == "hinge"]
    assert [b["beat_id"] for b in hinges] == ["a2w"], "the warning is the hinge; no device is added"
    # A warning is recorded as an event or as context; the turn may cite either.
    assert {"event", "context"} <= set(sfm.accepted_claim_kinds("hinge", se.STATE_PROGRAMME))
