"""The turn by 45 seconds, PLANNED (opening_turn): the aral-v2 claim_refs layout, the approval
page, the feasibility flags, the planner and writer text, the promptfoo assert. $0."""
import copy
import json
import os
import sys

import hook_patterns as hp
import explainer_pipeline as ep
import opening_turn as ot
import story_compiler as sc
import story_planner as sp
from turn_fixture import ROOT, SAVED, dossier_for as _dossier



# ── 5. the plan, before any spend ───────────────────────────────────────────────────────────

def test_plan_opening_reads_the_top_level_claim_refs_of_aral_v2():
    plan = SAVED["history-aral-sea-v2"]["approved_plan"]
    assert "claim_refs" not in plan["opening"] and plan["claim_refs"]["consequence"] == ["c05", "c06"]
    opening = ep._plan_opening(plan)
    assert opening["claim_refs"]["consequence"] == ["c05", "c06"]
    assert opening["missing_claims"] and "decree" in opening["missing_claims"][0]
    scenes = [{k: v for k, v in s.items() if k != "opening_ceiling"}
              for s in copy.deepcopy(SAVED["history-aral-sea-v2"]["scenes"])]
    stamped = ep._attach_opening_ceiling(scenes, plan, _dossier("history-aral-sea-v2"))
    assert stamped == [0, 1, 2, 3]
    for row in scenes[1:4]:
        assert {"c05", "c06"} <= set(row["opening_ceiling"]["claim_refs"])
    # A sheet that nests its refs inside `opening` is read as before.
    nested = dict(plan, opening=dict(plan["opening"], claim_refs={"consequence": ["c99"]}))
    assert ep._plan_opening(nested)["claim_refs"] == {"consequence": ["c99"]}


def _report(job, myth=False):
    entry = SAVED[job]
    plan = entry.get("approved_plan") or entry["plan"]
    return plan, {"score": 90.0, "issues": [], "turn": ot.plan_feasibility(
        plan, entry["engine"], _dossier(job), 300, myth=myth)}


def test_the_approval_page_prints_the_opening_order_shape_and_budget():
    plan, report = _report("history-aral-sea-v2")
    page = sp.plan_markdown(plan, report)
    assert "Opening:" in page and "consequence: In 1961 the sea begins to fall" in page and "[c05, c06]" in page
    assert "Turn: 103 target / 116 limit" in page and "shape B" in page
    order = page[page.index("Compiled order:"):].split("\n")[0]
    assert order.index("false_resolution (event_05)") < order.index("hinge (event_04)") < order.index("mechanism")
    assert "Turn feasible as planned." in page


def test_feasibility_flags_myth_openings_crowded_sheets_and_uncited_consequences():
    _, escobar = _report("escobar-hippos", myth=True)
    assert not escobar["turn"]["feasible"]
    assert any(i.startswith("TURN_OPENING_TOO_LONG") and "myth" in i for i in escobar["turn"]["issues"])
    plan, bees = _report("bees_v16")
    assert bees["turn"]["feasible"] and bees["turn"]["shape"] == "A" and bees["turn"]["rows_before_mechanism"] == 3
    crowded = copy.deepcopy(plan)
    extra = copy.deepcopy(next(b for b in crowded["beats"] if b["event_function"] == "intended_effect"))
    extra["beat_id"] = "event_03x"
    crowded["beats"].insert(2, extra)
    flagged = ot.plan_feasibility(crowded, "removed_keystone", _dossier("bees_v16"), 300)
    assert any(i.startswith("TURN_TOO_MANY_ROWS") for i in flagged["issues"])
    uncited = copy.deepcopy(plan)
    uncited["opening"]["claim_refs"].pop("consequence")
    assert any(i.startswith("TURN_CONSEQUENCE_UNCITED")
               for i in ot.plan_feasibility(uncited, "removed_keystone", _dossier("bees_v16"), 300)["issues"])
    unknown = copy.deepcopy(plan)
    unknown["opening"]["claim_refs"]["consequence"] = ["c999"]
    assert any(i.startswith("TURN_CONSEQUENCE_UNKNOWN_CLAIM")
               for i in ot.plan_feasibility(unknown, "removed_keystone", _dossier("bees_v16"), 300)["issues"])
    assert not ot.plan_feasibility(plan, "removed_keystone", _dossier("bees_v16"), 300,
                                   opening_mode="hook")["applies"]


def test_score_plan_reports_the_turn_without_scoring_it():
    plan, _ = _report("escobar-hippos")
    report = sp.score_plan(plan, "removed_keystone", _dossier("escobar-hippos"), 300)
    assert report["turn"]["applies"] and report["engine"] == "removed_keystone"



# ── the planner and writer text ─────────────────────────────────────────────────────────────

def test_the_rules_carry_the_turn_only_in_scope(monkeypatch):
    monkeypatch.delenv("OPENING_HOOK", raising=False)
    assert hp.opening_rules() == hp.OPENING_RULES and "no fixed length" in hp.opening_rules()
    assert hp.opening_writer_rules() == hp.OPENING_WRITER_RULES
    assert hp.opening_body_rule() == hp.OPENING_BODY_RULE
    ruled = hp.opening_rules(turn_rule=True, engine_id="removed_keystone")
    assert "no fixed length" not in ruled and "forty seconds" in ruled and "FIRST HARM" not in ruled
    assert "FIRST HARM" in hp.opening_rules(turn_rule=True, engine_id="state_programme")
    writer = hp.opening_writer_rules(turn_rule=True, shape="B", engine_id="state_programme")
    assert "103 spoken words" in writer and "WITHOUT its year" in writer and "recorded warning" in writer
    assert "WITHOUT its year" not in hp.opening_writer_rules(turn_rule=True, shape="A")
    monkeypatch.setenv("OPENING_HOOK", "myth")
    assert "INSIDE the first row's" in hp.opening_writer_rules(turn_rule=True, shape="B")


def test_the_planner_prompt_is_the_ladder_and_states_the_turn(monkeypatch):
    monkeypatch.delenv("OPENING_MODE", raising=False)
    monkeypatch.delenv("OPENING_HOOK", raising=False)
    ladder = sc.factual_plan_prompt("q", 300, 60, "removed_keystone", opening_mode="ladder")
    assert "forty seconds" in ladder and "no fixed length" not in ladder
    assert "FIRST, spend" not in ladder, "intended_effect is no longer pushed first under the turn rule"
    assert "FIRST, spend" in sc.factual_plan_prompt("q", 300, 60, "removed_keystone", opening_mode="hook")
    assert "no fixed length" in sc.factual_plan_prompt("q", 200, 60, "removed_keystone", opening_mode="ladder")
    history = sc.factual_plan_prompt("q", 300, 60, "state_programme", opening_mode="ladder")
    assert "FIRST, spend" in history and "warning_recorded" in history and "FIRST HARM" in history
    prompt = sp.planner_prompt("q", 300, "removed_keystone", {"claims": []})
    assert "THE OPENING." in prompt and "COLD OPEN:" not in prompt


def test_the_eval_assert_judges_turn_feasibility():
    sys.path.insert(0, os.path.join(ROOT, "evals", "promptfoo"))
    import asserts
    plan = SAVED["bees_v16"]["plan"]
    ok = asserts.plan_turn_feasible(json.dumps(plan), {"vars": {
        "engine": "removed_keystone", "dossier": "dossier_killerbees.json", "duration": 300}})
    assert "shape A" in ok["reason"]
    bad = copy.deepcopy(plan)
    bad["opening"]["claim_refs"]["consequence"] = []
    out = asserts.plan_turn_feasible(json.dumps(bad), {"vars": {
        "engine": "removed_keystone", "dossier": "dossier_killerbees.json", "duration": 300}})
    assert not out["pass"] and "TURN_CONSEQUENCE_UNCITED" in out["reason"]

