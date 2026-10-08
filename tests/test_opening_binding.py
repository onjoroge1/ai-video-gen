"""The ledger admits what the human-first opening's writer was told, row by row, claims only.

Killer bees V12 (2026-10-07): the planner put the excluder removal and the twenty-six queens in
opening.consequence; the writer was told to combine the opening beats; the ledger judged each
opening scene against its one-line event alone and refused three of them for facts the dossier
states, and refused the close's 'Twenty-six queens escaped' because no body event carries the
figure (the engine has no slot for the trigger; under the ladder the opening block is its home).
The callback contract was also inert on every ladder film because the frame plants no number.
"""
import copy
import causal_story as cs
import explainer_pipeline as ep
import story_fact_model as sfm

CLAIMS = {"c01": {"claim": "Kerr imported African honey bee queens to Brazil in 1956."},
          "c04": {"claim": "The queens were housed in hive boxes at a research station near Rio Claro."},
          "c07": {"claim": "The removal of the excluders released 26 queens with small swarms."},
          "c10": {"claim": "Escaped African queens hybridized with European honey bees."},
          "c39": {"claim": "European honey bees performed poorly in Brazil's tropics."}}
DOSSIER = {"claims": [{"claim_id": k, **v} for k, v in CLAIMS.items()]}
PLAN = {"hook": "Imagine you're a beekeeper in Brazil.",
        "opening": {"frame": "Imagine you're a beekeeper in Brazil.", "problem": "Bees did poorly.",
                    "solution": "Kerr imported queens.", "transition": "They sat in hive boxes near Rio Claro.",
                    "consequence": "In October 1957 a beekeeper lifted the excluders and 26 queens escaped.",
                    "claim_refs": {"problem": ["c39"], "solution": ["c01"], "transition": ["c04"],
                                   "consequence": ["c07", "cZZ"]}}}


def _beat(bid, text, refs, **extra):
    return {"beat_id": bid, "event": {"text": text, "claim_refs": refs}, **extra}


def _v12_shaped_scenes():
    return [{"beat_id": "event_01", "causal_role": "setup", "narration": "a"},
            {"beat_id": "event_02", "causal_role": "intervention", "narration": "b"},
            {"beat_id": "event_04:hinge", "causal_role": "hinge", "narration": "c"},
            {"beat_id": "event_04", "causal_role": "mechanism", "narration": "d"},
            {"beat_id": "event_05", "causal_role": "escalation", "narration": "e"},
            {"beat_id": "event_17", "causal_role": "reversal", "narration": "f"},
            {"beat_id": "event_17:synthesis", "causal_role": "synthesis", "narration": "g"},
            {"beat_id": "event_17:tool", "causal_role": "tool", "narration": "h"}]


def test_opening_rows_and_the_close_are_stamped_per_row_and_the_body_is_not():
    scenes = _v12_shaped_scenes()
    assert ep._attach_opening_ceiling(scenes, PLAN, DOSSIER) == [0, 1, 2, 7]
    assert scenes[0]["opening_ceiling"] == {"claim_refs": ["c39"]}
    assert scenes[1]["opening_ceiling"] == {"claim_refs": ["c01", "c04", "c07"]}   # cZZ unknown
    assert scenes[2]["opening_ceiling"] == {"claim_refs": ["c07"]}
    assert scenes[7]["opening_ceiling"] == {"claim_refs": ["c07"]}
    for i in (3, 4, 5, 6):
        assert "opening_ceiling" not in scenes[i], scenes[i]["causal_role"]
    # no hinge row: the mechanism still starts the body
    no_hinge = [s for s in _v12_shaped_scenes() if s["causal_role"] != "hinge"]
    ep._attach_opening_ceiling(no_hinge, PLAN, DOSSIER)
    assert "opening_ceiling" not in no_hinge[2] and "opening_ceiling" in no_hinge[-1]
    # dossier-less: nothing is admitted, so nothing is stamped
    assert ep._attach_opening_ceiling(_v12_shaped_scenes(), PLAN, None) == []
    assert ep._attach_opening_ceiling(_v12_shaped_scenes(), {"hook": "h"}, DOSSIER) == []


def test_the_ceiling_admits_the_stamped_claims_but_never_the_planner_prose():
    scene = _beat("event_02", "African bees were imported to Brazil in 1956.", ["c01"],
                  causal_role="intervention", opening_ceiling={"claim_refs": ["c04", "c07", "cZZ"]})
    ceiling = sfm.scene_ceiling(scene, {"event_02": scene}, CLAIMS)
    assert "hive boxes at a research station" in ceiling and "released 26 queens" in ceiling
    assert "lifted the excluders" not in ceiling          # prose from the plan is not a fact
    assert "cZZ" not in ceiling
    # the mechanism, unstamped, keeps its own ceiling
    body = _beat("event_04", "Hybrids formed.", ["c10"], causal_role="mechanism")
    assert "released 26 queens" not in sfm.scene_ceiling(body, {"event_04": body}, CLAIMS)


def test_the_close_gets_the_figure_through_the_opening_not_through_its_refs():
    """The close points at body beats whose events never say twenty-six; the stamp does."""
    reversal = _beat("event_17", "Beekeeping changed after 1957.", ["c43"])
    close = {"beat_id": "event_17:tool", "presentation_device": "tool", "causal_role": "tool",
             "context_refs": ["event_17"], "event": {"text": "", "claim_refs": []}}
    by_id = {"event_17": reversal, "event_17:tool": close}
    assert "released 26 queens" not in sfm.scene_ceiling(close, by_id, CLAIMS)
    ep._attach_opening_ceiling([reversal | {"causal_role": "reversal"}, close], PLAN, DOSSIER)
    assert "released 26 queens" in sfm.scene_ceiling(close, by_id, CLAIMS)


def test_the_opening_consequence_plants_the_callback_number_but_not_its_year():
    frame_only = {"line": "Imagine you're a beekeeper in Brazil."}
    assert cs.lead_numbers(frame_only) == set()
    with_consequence = dict(frame_only, consequence=PLAN["opening"]["consequence"])
    assert cs.lead_numbers(with_consequence) == {26}
    # a hook that states a year still plants it: only the consequence's dating is a setting
    assert cs.lead_numbers({"line": "In 1957 twenty-six queens escaped."}) == {1957, 26}
    assert "the opening planted" in cs.close_contract_text(["twenty-six"], "the jars")


def test_the_storyboard_validator_and_the_repair_read_the_same_lead(monkeypatch):
    import illustrated_story as lane
    import storyboard_repair as repair
    from test_illustrated_story import _script
    seen = {}
    real = cs.validate_causal_story
    def spy(payload, engine=None):
        seen["hook"] = payload.get("hook")
        return real(payload, engine)
    monkeypatch.setattr(cs, "validate_causal_story", spy)
    script = _script()
    script["_opening_contract"] = cs.OPENING_CONTRACT
    script["_opening"] = {"consequence": PLAN["opening"]["consequence"]}
    lane.build_storyboard(copy.deepcopy(script), "q")
    assert seen["hook"]["consequence"] == PLAN["opening"]["consequence"]
    assert cs.lead_numbers(seen["hook"]) == {26}
    lane.build_storyboard(copy.deepcopy(_script()), "q")
    assert seen["hook"]["consequence"] == ""
    # the repair plans the close against the same planted set
    script["_close_contract"] = cs.CLOSE_CONTRACT
    board = {"validation": {"errors": ["NO_NUMBER_CALLBACK: the hook planted [26] and the closing span re-speaks no number"]}}
    planned = repair.plan(script, board)
    assert planned and planned["planted_numbers"] == [26]


def test_the_ladder_schema_keeps_the_consequence_in_the_opening_block_only():
    import story_compiler as sc
    prompt = sc.factual_plan_prompt("q", 300, 20, "removed_keystone", opening_mode="ladder")
    assert '"opening": {' in prompt and "ALSO one of the `beats`" not in prompt
