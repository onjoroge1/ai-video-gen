"""The story-contract lane (story_contract.py, story_contract_segment.py, story_contract_policy.py).

No provider is called: a fake caller returns canned JSON per stage, and the segmenter and gate
policy run on cached fixtures (the lionfish v2 dossier and narration in evals/promptfoo/fixtures).
"""
import json
import os
import re

import pytest

import story_contract as sc
import story_contract_policy as policy
import story_contract_segment as seg

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "evals", "promptfoo", "fixtures")


def _fixture_text(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return handle.read()


def _lionfish_dossier():
    return json.loads(_fixture_text("dossier_lionfish_v2.json"))


DOSSIER = {"claims": [
    {"claim_id": "c1", "claim": "Paul Carlson removed 1,542 lionfish over 73 dive trips.", "claim_kind": "event",
     "support_quote": "removing 1,542 lionfish over 73 dive trips", "source_url": "https://example.org/a"},
    {"claim_id": "c2", "claim": "Carlson said: 'My freezer is full.'", "claim_kind": "event",
     "support_quote": "\"My freezer is full.\"", "source_url": "https://example.org/a"},
    {"claim_id": "c3", "claim": "NOAA developed an 'Eat Lionfish' campaign.", "claim_kind": "event",
     "support_quote": "NOAA developed an 'Eat Lionfish' campaign", "source_url": "https://example.org/b"},
    {"claim_id": "c4", "claim": "Reducing an invasive population reduces catch rates.", "claim_kind": "mechanism",
     "support_quote": "will reduce their catch rates", "source_url": "https://example.org/c"},
    {"claim_id": "c5", "claim": "Partial removals produced similar gains in 30% less time.", "claim_kind": "outcome",
     "support_quote": "partial removals took 30% less time", "source_url": "https://example.org/d"},
    {"claim_id": "c6", "claim": "Florida divers removed a record 36,187 lionfish in the 2026 Lionfish Challenge.",
     "claim_kind": "event", "support_quote": "removed 36,187 invasive lionfish ... 2026", "source_url": "https://example.org/e"},
]}
KNOWN = {"c1", "c2", "c3", "c4", "c5", "c6"}


def _contract(**overrides):
    q = "Florida asked people to eat lionfish in 2010; why are divers still pulling record numbers out?"
    contract = {
        "topic": "Lionfish removal in Florida",
        "question_candidates": [
            {"question": "Why is Florida asking people to eat lionfish?", "claim_ids": ["c3"],
             "scores": {"curiosity": 1, "support": 3, "deliverable": 3}},
            {"question": q, "claim_ids": ["c4", "c5"], "scores": {"curiosity": 3, "support": 3, "deliverable": 3},
             "names_decision": True, "asks_consequence": True,
             "topic_fit": {"screened": True, "verdict": "fits", "channel": "world", "reason": "a deliberate campaign"}},
            {"question": "Can a freezer save a reef?", "claim_ids": ["c2"],
             "scores": {"curiosity": 2, "support": 1, "deliverable": 1}}],
        "chosen": 1, "chosen_reason": "the paradox the title does not give away",
        "central_question": q,
        "decision": {"what": "NOAA launched an 'Eat Lionfish' campaign", "who": "NOAA", "when": "2010",
                     "kind": "animal_targeted", "claim_ids": ["c3"]},
        "consequence": {"what": "divers remove lionfish by the thousand, and thinner reefs pay less",
                        "claim_ids": ["c1", "c4"]},
        "still_unfolding": {"what": "a record 36,187 removed in 2026", "as_of": "2026", "claim_ids": ["c6"]},
        "ending_answer": "The fishery can run out of profit before the reef runs out of lionfish, so "
                         "the target becomes enough removal per reef, not the last fish.",
        "human_perspective": {"person": "Paul Carlson", "want": "the hunt", "action": "73 dive trips",
                              "reward": "a full freezer",
                              "claim_ids": {"want": ["c1"], "action": ["c1"], "reward": ["c2"]}},
        "reasonable_attempt": {"what": "Eat the invader", "why_it_made_sense": "a market pays for removal",
                               "claim_ids": ["c3"]},
        "complication": {"what": "Success lowers catch rates", "mechanism": "fewer fish, longer searches",
                         "claim_ids": ["c4"]},
        "developments": [
            {"what_happens": "Removals work", "what_it_changes": "each trip brings back fewer fish",
             "why_next_matters": "so the profit thins", "claim_ids": ["c4"]},
            {"what_happens": "Researchers test partial removal", "what_it_changes": "the goal moves from "
             "the last fish to a per-reef threshold", "why_next_matters": "", "claim_ids": ["c5"]},
        ],
        "recurring_image": {"image": "a full freezer", "planted_in": "opening", "callback_in": "ending"},
        "forbidden_claims": ["Carlson lost commercial income"],
        "tangents_left_out": [{"tangent": "ciguatera", "why": "off the question"}],
        "evidence_gaps": [],
    }
    contract.update(overrides)
    return contract


SENTENCES = [
    {"text": "Paul Carlson made seventy-three dive trips.", "claim_ids": ["c1"], "kind": "event", "part": "opening"},
    {"text": "His report afterward?", "claim_ids": [], "kind": "framing", "part": "opening"},
    {"text": "\"My freezer is full.\"", "claim_ids": ["c2"], "kind": "event", "part": "opening"},
    {"text": "So NOAA put the invader on the menu.", "claim_ids": ["c3"], "kind": "event", "part": "attempt"},
    {"text": "But the better you get, the fewer fish each trip brings back.", "claim_ids": ["c4"],
     "kind": "interpretation", "part": "complication"},
    {"text": "Put yourself on a commercial boat.", "claim_ids": [], "kind": "illustration", "part": "development_1"},
    {"text": "Removing just enough lionfish gave similar gains in less time.", "claim_ids": ["c5"],
     "kind": "event", "part": "development_2"},
    {"text": "Seventy-three trips, and a full freezer.", "claim_ids": [], "kind": "framing", "part": "ending"},
    {"text": "And this year divers set a record anyway.", "claim_ids": ["c6"], "kind": "event", "part": "ending"},
]


class FakeCaller:
    """Canned replies by stage; counts calls. `review_b` is a list consumed in order (last repeats)."""
    provider = "anthropic"

    def text(self, *, role, stage, system, user, max_tokens=4000):
        self.calls.append(stage)
        return json.dumps({"episode": "Eat Lionfish campaign", "channel": "world", "verdict": "fits",
                           "reason": "a deliberate campaign with a documented aftermath"}), 0.001

    def __init__(self, review_b=None, fail_on=None):
        self.calls = []
        self.review_b = list(review_b or [_clean_review()])
        self.fail_on = fail_on or set()

    def call(self, *, role, stage, system, user, max_tokens=8000):
        self.calls.append(stage)
        if stage in self.fail_on:
            raise RuntimeError(f"provider died during {stage}")
        if stage == "evidence":
            return {"claim_kinds": {"c1": "event", "c2": "event", "c3": "event", "c4": "model", "c5": "event",
                                    "c6": "event"},
                    "human_material": [{"type": "object", "person": "Paul Carlson", "detail": "full freezer",
                                        "claim_ids": ["c2"], "serves_person": "his reward",
                                        "serves_problem": "the plan working", "does_both": True}]}, 0.01
        if stage == "contract":
            return _contract(), 0.02
        if stage == "openings":
            return {"openings": [{"id": f"O{i}", "text": f"Opening {i}.", "claim_ids": ["c1"]} for i in (1, 2, 3)],
                    "endings": [{"id": f"E{i}", "text": f"Ending {i}.", "claim_ids": []} for i in (1, 2)],
                    "selected": {"opening": "O2", "ending": "E1", "reason": "asks and answers"}}, 0.01
        if stage == "narration":
            return {"sentences": SENTENCES}, 0.05
        if stage.startswith("repair_"):
            n = int(stage.split("_")[1])
            revised = [dict(s) for s in SENTENCES]
            revised[1] = dict(revised[1], text=f"His report afterward, version {n}?")
            return {"sentences": revised}, 0.04
        if stage == "review_blind":
            return {"central_question": "what happens when you get good at it", "question_position": 0.1,
                    "main_idea": "success thins profit", "human": "Paul Carlson", "pivotal_discovery":
                    "partial removal", "ending_answer": "enough per reef", "decision": "NOAA's 2010 campaign",
                    "consequence": "divers remove thousands", "still_unfolding": "a 2026 record"}, 0.005
        if stage == "review_contract":
            reply = self.review_b.pop(0) if len(self.review_b) > 1 else self.review_b[0]
            return reply, 0.01
        if stage == "visual_plan":
            return {"scenes": []}, 0.0
        raise AssertionError(stage)


def _clean_review():
    return {"reconstruction_match": {"central_question": {"match": True}},
            "opening_ending": {"same_question": True},
            "rubric": [{"item": i, "score": 2, "quote": "full freezer"} for i in sc.RUBRIC_IDS],
            "factual_blockers": [], "editorial_objectives": []}


def _objection_review():
    review = _clean_review()
    review["editorial_objectives"] = [{"sentences": [6], "problem": "the boat is a cameo",
                                       "objective": "make the cost concrete", "preserve": "the freezer"}]
    return review


def _lane(tmp_path, caller):
    return sc.LaneRun(question="Lionfish Have No Predators in the Atlantic. Why Is Florida Asking People to Eat Them?",
                      output_dir=str(tmp_path), duration_sec=60, dossier=DOSSIER, caller=caller,
                      log=lambda m: None)


def _approve_contract(tmp_path):
    (tmp_path / sc.CONTRACT_APPROVED).write_text((tmp_path / sc.CONTRACT_FILE).read_text())


# ── repair budget ─────────────────────────────────────────────────────────────────────────────

def test_repair_budget_is_two_and_survives_a_new_instance(tmp_path):
    budget = sc.RepairBudget(str(tmp_path))
    assert budget.consume("first") == 1
    resumed = sc.RepairBudget(str(tmp_path))          # a resumed process reads the same file
    assert resumed.used() == 1 and resumed.remaining() == 1
    assert resumed.consume("second") == 2
    with pytest.raises(sc.RepairBudgetExhausted):
        sc.RepairBudget(str(tmp_path)).consume("third")


def test_an_unreadable_budget_line_still_counts_as_a_spent_pass(tmp_path):
    (tmp_path / sc.REPAIRS_FILE).write_text("{not json\n")
    assert sc.RepairBudget(str(tmp_path)).used() == 1


def test_the_lane_repairs_at_most_twice_and_resume_does_not_reset(tmp_path):
    caller = FakeCaller(review_b=[_objection_review()])     # every review asks for more
    with pytest.raises(sc.ContractApprovalRequired):
        _lane(tmp_path, caller).run()
    _approve_contract(tmp_path)
    with pytest.raises(sc.NarrationApprovalRequired) as stop:
        _lane(tmp_path, caller).run()
    assert [c for c in caller.calls if c.startswith("repair_")] == ["repair_1", "repair_2"]
    assert stop.value.details["status"] == "ready_with_open_objectives"
    # A resumed run (new process, new caller, a different reviewer) buys no third repair.
    again = FakeCaller(review_b=[_objection_review()])
    with pytest.raises(sc.NarrationApprovalRequired):
        _lane(tmp_path, again).run()
    assert not [c for c in again.calls if c.startswith("repair_")]
    assert sc.RepairBudget(str(tmp_path)).used() == 2
    record = json.loads((tmp_path / sc.NARRATION_FILE).read_text())
    assert record["repair_passes_used"] == 2 and len(json.loads(
        (tmp_path / sc.STATE_FILE).read_text())["candidates"]) == 3   # every candidate kept


def test_a_repair_that_dies_mid_call_is_still_counted(tmp_path):
    caller = FakeCaller(review_b=[_objection_review()], fail_on={"repair_1"})
    with pytest.raises(sc.ContractApprovalRequired):
        _lane(tmp_path, caller).run()
    _approve_contract(tmp_path)
    with pytest.raises(RuntimeError, match="provider died"):
        _lane(tmp_path, caller).run()
    assert sc.RepairBudget(str(tmp_path)).used() == 1
    resumed = FakeCaller(review_b=[_objection_review()])
    with pytest.raises(sc.NarrationApprovalRequired):
        _lane(tmp_path, resumed).run()
    assert [c for c in resumed.calls if c.startswith("repair_")] == ["repair_2"]
    # stages already bought were not bought again
    assert "evidence" not in resumed.calls and "contract" not in resumed.calls and "narration" not in resumed.calls


def test_a_clean_review_buys_no_repair_and_the_hash_approval_is_exact(tmp_path):
    caller = FakeCaller()
    with pytest.raises(sc.ContractApprovalRequired):
        _lane(tmp_path, caller).run()
    _approve_contract(tmp_path)
    with pytest.raises(sc.NarrationApprovalRequired) as stop:
        _lane(tmp_path, caller).run(stop_after="script")
    sha = stop.value.details["sha256"]
    assert sha == policy.narration_sha256(" ".join(s["text"] for s in SENTENCES))
    assert not [c for c in caller.calls if c.startswith("repair_")]
    with pytest.raises(sc.NarrationApprovalRequired, match="does not match"):
        _lane(tmp_path, caller).run(approve_narration="0" * 64)
    record = _lane(tmp_path, caller).run(approve_narration=sha)
    assert record["sha256"] == sha and json.loads((tmp_path / sc.NARRATION_APPROVED).read_text())["sha256"] == sha
    # --stop-after script stops even once approved
    with pytest.raises(sc.NarrationApprovalRequired):
        _lane(tmp_path, caller).run(stop_after="script")


def test_select_prefers_a_factually_clean_candidate_over_a_higher_rubric():
    dirty = {"version": 1, "review": dict(sc.normalize_review(_clean_review(), SENTENCES, {}),
                                          factual_blockers=[{"problem": "x"}], rubric_total=24)}
    clean = {"version": 2, "review": dict(sc.normalize_review(_objection_review(), SENTENCES, {}), rubric_total=10)}
    assert sc.select_candidate([dirty, clean])["version"] == 2


# ── contract validation ───────────────────────────────────────────────────────────────────────

def _codes(contract):
    return {e["code"] for e in sc.validate_contract(contract, KNOWN)["errors"]}


def test_a_complete_contract_passes():
    report = sc.validate_contract(_contract(), KNOWN)
    assert report["passed"], report["errors"]


def test_every_development_must_name_what_it_changes():
    devs = _contract()["developments"]
    assert "DEVELOPMENT_NO_CHANGE" in _codes(_contract(developments=[dict(devs[0], what_it_changes=""), devs[1]]))
    assert "DEVELOPMENT_NO_CHANGE" in _codes(_contract(developments=[
        dict(devs[0], what_it_changes="Removals work"), devs[1]]))       # restates what happens
    assert "DEVELOPMENT_REPEATS_CHANGE" in _codes(_contract(developments=[
        devs[0], dict(devs[1], what_it_changes=devs[0]["what_it_changes"])]))
    assert "DEVELOPMENT_NO_LINK" in _codes(_contract(developments=[dict(devs[0], why_next_matters=""), devs[1]]))
    assert "DEVELOPMENT_UNSUPPORTED" in _codes(_contract(developments=[dict(devs[0], claim_ids=[]), devs[1]]))
    assert "NO_DEVELOPMENTS" in _codes(_contract(developments=[]))


def test_contract_question_answer_human_image_and_claims_are_checked():
    assert {"MISSING_QUESTION", "MISSING_ANSWER"} <= _codes(_contract(central_question="", ending_answer=""))
    hp = dict(_contract()["human_perspective"], claim_ids={"want": [], "action": ["c1"], "reward": ["c2"]})
    assert "HUMAN_CLAIM_MISSING" in _codes(_contract(human_perspective=hp))
    assert "CALLBACK_BEFORE_PLANT" in _codes(_contract(recurring_image={
        "image": "freezer", "planted_in": "ending", "callback_in": "opening"}))
    assert "FORBIDDEN_CLAIMS_MISSING" in _codes(_contract(forbidden_claims=[]))
    comp = dict(_contract()["complication"], claim_ids=["c99"])
    assert "UNKNOWN_CLAIM" in _codes(_contract(complication=comp))


def test_an_invalid_contract_gets_one_corrected_attempt_then_stops(tmp_path):
    class Bad(FakeCaller):
        def call(self, **kw):
            if kw["stage"] == "contract":
                self.calls.append("contract")
                return _contract(developments=[{"what_happens": "x", "what_it_changes": "", "claim_ids": ["c4"]}]), 0.01
            return super().call(**kw)
    caller = Bad()
    with pytest.raises(sc.ContractInvalid):
        _lane(tmp_path, caller).run()
    assert caller.calls.count("contract") == 2
    assert "DEVELOPMENT_NO_CHANGE" in (tmp_path / sc.CONTRACT_MD).read_text()


def test_narration_validation_flags_unsourced_facts_and_unframed_illustrations():
    sents = [dict(SENTENCES[0], claim_ids=[]), {"text": "Carlson lost money.", "claim_ids": [],
                                                "kind": "illustration", "part": "development_1"}]
    report = sc.validate_narration(sents, {"c1"}, 60)
    assert {"UNSOURCED_FACT"} == {e["code"] for e in report["errors"]}
    assert "ILLUSTRATION_NOT_FRAMED" in {w["code"] for w in report["warnings"]}


def test_review_normalisation_verifies_quotes_caps_objectives_and_covers_low_scores():
    raw = _clean_review()
    raw["rubric"][0] = {"item": "human_entry", "score": 1, "quote": "not in the narration", "note": "cameo"}
    raw["editorial_objectives"] = [{"objective": f"o{i}", "problem": "p"} for i in range(3)]
    review = sc.normalize_review(raw, SENTENCES, {})
    assert len(review["editorial_objectives"]) == sc.MAX_EDITORIAL_OBJECTIVES
    assert review["deferred_objectives"] and review["deferred_objectives"][0]["from_rubric"] == "human_entry"
    assert review["rubric"][0]["quote_verified"] is False and review["rubric"][1]["quote_verified"] is True


def test_parse_json_reply_tolerates_fences_and_reports_truncation():
    assert sc.parse_json_reply('ok ```json\n{"a": "}"}\n``` done') == {"a": "}"}
    with pytest.raises(ValueError, match="unterminated"):
        sc.parse_json_reply('{"a": [1, 2')


# ── segmenter ─────────────────────────────────────────────────────────────────────────────────

def _v2_sentences():
    """The lionfish v2 narration as sentences, with parts by position and claims from its dossier."""
    text = policy.normalize_narration(_fixture_text("narration_lionfish_v2.txt"))
    parts = [p for p in re.split(r"(?<=[.!?\"])\s+(?=[A-Z\"])", text) if p]
    dossier = _lionfish_dossier()
    ids = [c["claim_id"] for c in dossier["claims"]]
    out = []
    for i, sentence in enumerate(parts):
        frac = i / len(parts)
        part = ("opening" if frac < 0.12 else "attempt" if frac < 0.3 else "complication" if frac < 0.45
                else "development_1" if frac < 0.75 else "ending")
        claims = [ids[i % len(ids)]] if i % 3 != 1 else []
        out.append({"text": sentence, "claim_ids": claims, "kind": "event" if claims else "framing", "part": part})
    return out, dossier, text


def test_segmenter_preserves_every_word_of_the_approved_narration():
    sentences, dossier, text = _v2_sentences()
    scenes = seg.build_scenes(sentences, dossier)
    assert policy.scenes_narration(scenes) == text
    assert len(scenes) > 10
    assert scenes[0]["claim_refs"], "the first scene carries a claim"
    assert all(len(s["narration"].split()) <= seg.MAX_SCENE_WORDS + 25 for s in scenes)
    for s in scenes:
        for ref in s["claim_refs"]:
            assert ref["narration_phrase"] in s["narration"]


def test_segmenter_refuses_a_changed_word():
    sentences, dossier, _ = _v2_sentences()
    scenes = seg.build_scenes(sentences, dossier)
    words = scenes[3]["narration"].split()
    scenes[3]["narration"] = " ".join(words[:2] + ["really"] + words[2:])
    with pytest.raises(seg.SegmentError, match="changed the narration"):
        seg.check_words_preserved(sentences, scenes)


def test_segmented_state_has_the_hand_build_shape_and_verbatim_anchors():
    sentences, dossier, text = _v2_sentences()
    record = {"sentences": sentences, "dossier": dossier, "sha256": policy.narration_sha256(text),
              "contract": _contract(), "question": "Q?", "version": 1, "contract_sha256": "x"}
    bad_plan = {"scenes": [{"image_prompt": "a reef", "visual_beats": [
        {"anchor_phrase": "words that are not there", "visual": "v"}]}]}
    state = seg.strip_private(seg.build_state(record, title="Q?", visual_plan=bad_plan))
    script = state["script"]
    assert policy.is_lane(script) and script["_story_contract_lane"]["approved_narration_sha256"] == record["sha256"]
    assert policy.scenes_narration(script["scenes"]) == text
    for scene in script["scenes"]:
        for key in ("scene_id", "beat_id", "role", "causal_role", "event", "claim_refs", "visual_beats",
                    "image_prompt", "event_function", "motion_anchor_phrase"):
            assert key in scene
        assert scene["visual_beats"], scene["n"]
        for beat in scene["visual_beats"]:
            assert beat["anchor_phrase"] in scene["narration"]
        assert scene["role"] in seg.EVENT_FUNCTION
        if scene["role"] != "tool" and not scene["continues"]:
            assert scene["event"]["claim_refs"]
    assert script["_story_contract"]["scene_count"] == len(script["scenes"])
    assert "_close_contract" not in script and "_sentence_mix_contract" not in script


def test_roles_follow_the_claim_kinds_the_ledger_accepts():
    import story_fact_model as sfm
    sentences, dossier, _ = _v2_sentences()
    claims = {c["claim_id"]: c for c in dossier["claims"]}
    for scene in seg.build_scenes(sentences, dossier):
        accepted = sfm.accepted_claim_kinds(scene["role"], seg.ENGINE)
        if scene["role"] == "tool" or not accepted:
            continue
        kinds = {str(claims[r["claim_id"]].get("claim_kind") or "").lower() for r in scene["claim_refs"]}
        if kinds <= set(accepted):
            continue
        # Only when no role in the fallback list could accept them all does the part's role stand.
        assert not any(kinds <= set(sfm.accepted_claim_kinds(r, seg.ENGINE) or kinds)
                       for r in seg.ROLE_FALLBACKS), (scene["n"], scene["role"], kinds)


# ── gate policy ───────────────────────────────────────────────────────────────────────────────

def test_policy_keys_on_the_lane_marker_only():
    assert policy.is_lane({"_lane": "story_contract"}) and not policy.is_lane({"_story_engine": "x"})
    assert policy.GATES["claim_ledger"] == "hard"
    assert policy.GATES["structural_turn"] == "report"
    assert policy.GATES["readiness_narrative_propulsion"] == "report"
    assert policy.GATES["engine_templates"] == "off" and policy.GATES["story_shape_writer_rules"] == "off"
    assert policy.opening_below_b_action({"_lane": "story_contract"}) == "degraded"
    assert policy.opening_below_b_action({}) == "stop"
    kept, demoted = policy.split_storyboard_issues([{"code": "THIN_CHAIN"}, {"code": "UNKNOWN_ROLE"},
                                                    {"code": "SOFT_HINGE"}, {"code": "ENGINE_ORDER"}])
    assert [i["code"] for i in kept] == ["UNKNOWN_ROLE"]
    assert {i["code"] for i in demoted} == {"THIN_CHAIN", "SOFT_HINGE", "ENGINE_ORDER"}


def test_readiness_reports_narrative_propulsion_without_grading_it_on_the_lane():
    from retention_readiness import score_retention_readiness
    script = {"title": "t", "hook": "h", "scenes": [{"story_role": "setup"}] * 6}
    validation = {"errors": [{"code": "misplaced_peak"}, {"code": "missing_final_payoff"}], "warnings": [],
                  "checks": {"max_attention_gap_sec": 80, "max_exposition_block_sec": 30,
                             "unresolved_loops": ["q"], "prediction_scenes": [], "answer_scenes": []}}
    metrics = {"semantic_sync_ratio": 0.95, "avg_still_seconds": 2.8, "min_shot_seconds": 1.8,
               "max_still_seconds": 3.0, "meaningful_cut_ratio": 0.9}
    base = score_retention_readiness(script, validation, metrics, [])
    lane = score_retention_readiness(dict(script, _lane="story_contract"), validation, metrics, [])
    prop = next(c for c in lane["components"] if c["name"] == "Narrative propulsion")
    assert prop["report_only"] and lane["report_only_components"] == ["Narrative propulsion"]
    assert base["report_only_components"] == []
    assert lane["assessed_max"] == base["assessed_max"] - next(
        c["assessed_max"] for c in base["components"] if c["name"] == "Narrative propulsion")
    assert lane["score"] > base["score"]           # the label axis no longer drags the grade


def test_below_b_opening_is_degraded_not_stopped_on_the_lane_only(tmp_path, monkeypatch):
    import explainer_pipeline as ep
    monkeypatch.delenv("OPENING_RETRY_ALLOW_BELOW_B", raising=False)
    record = {"outcome": "script_shortfall", "before": {"score": 74, "grade": "C"}, "ceiling": 74}
    logged = []
    ep._stop_if_opening_below_b(record, str(tmp_path), log=logged.append, script={"_lane": "story_contract"})
    assert record["continued_below_b"] is True and "degraded" in logged[0]
    with pytest.raises(ep.OpeningBelowB):
        ep._stop_if_opening_below_b({"outcome": "script_shortfall", "before": {}}, str(tmp_path),
                                    log=lambda m: None, script={"_story_engine": "unfolding_consequence"})


def test_media_is_bought_only_on_the_approved_narration(tmp_path):
    sentences, dossier, text = _v2_sentences()
    record = {"sentences": sentences, "dossier": dossier, "sha256": policy.narration_sha256(text),
              "contract": _contract(), "question": "Q?"}
    script = seg.strip_private(seg.build_state(record))["script"]
    policy.check_approved_narration(script, str(tmp_path))          # unchanged: passes
    script["scenes"][2]["narration"] += " Extra words."
    with pytest.raises(policy.NarrationChangedRequiresApproval) as raised:
        policy.check_approved_narration(script, str(tmp_path))
    assert raised.value.sha256 != record["sha256"]
    assert (tmp_path / "narration_changed_for_approval.md").read_text().count(raised.value.sha256) >= 1
    policy.check_approved_narration({"scenes": []}, str(tmp_path))  # other lanes: no-op


def test_lane_storyboard_reports_engine_templates_instead_of_blocking():
    import illustrated_story
    sentences, dossier, text = _v2_sentences()
    record = {"sentences": sentences, "dossier": dossier, "sha256": policy.narration_sha256(text),
              "contract": _contract(), "question": "Q?"}
    lane_script = seg.strip_private(seg.build_state(record))["script"]
    other = json.loads(json.dumps(lane_script))
    other.pop("_lane")
    plain = illustrated_story.build_storyboard(other, "Q?")
    board = illustrated_story.build_storyboard(lane_script, "Q?")
    def codes(rows):
        return {r.split(":")[0] for r in rows if re.fullmatch(r"[A-Z_]+", r.split(":")[0])}
    engine_codes = codes(plain["validation"]["errors"]) - policy.STORYBOARD_KEPT_CODES
    assert not (codes(board["validation"]["errors"]) & engine_codes)
    reported = codes(w[len(policy.REPORT_PREFIX):] for w in board["validation"]["warnings"]
                     if w.startswith(policy.REPORT_PREFIX))
    assert engine_codes <= reported


def test_narration_validation_flags_prompt_language_leaking_into_the_story():
    sents = [{"text": "The storm story is probably erroneous, according to the supplied record.",
              "claim_ids": ["c1"], "kind": "interpretation", "part": "opening"},
             {"text": "That is the title's problem in practical form.", "claim_ids": [], "kind": "framing",
              "part": "opening"}]
    codes = [e["code"] for e in sc.validate_narration(sents, {"c1"}, 60)["errors"]]
    assert codes.count("PROMPT_LEAK") == 2          # a blocker, not a warning


# ── question choice, length and spoken voice (operator fixes after the first dry run) ─────────

def test_the_contract_proposes_three_questions_and_may_not_restate_the_title():
    known = KNOWN
    title = "Lionfish Have No Predators in the Atlantic. Why Is Florida Asking People to Eat Them?"
    assert sc.validate_contract(_contract(), known, title)["passed"]
    two = _contract(question_candidates=_contract()["question_candidates"][:2])
    assert "QUESTION_CANDIDATES" in {e["code"] for e in sc.validate_contract(two, known, title)["errors"]}
    wrong = _contract(chosen=0)
    assert "QUESTION_NOT_CHOSEN" in {e["code"] for e in sc.validate_contract(wrong, known, title)["errors"]}
    cands = _contract()["question_candidates"]
    same = _contract(central_question="Why Is Florida Asking People to Eat Lionfish With No Predators?",
                     question_candidates=[cands[0], dict(cands[1], question="Why Is Florida Asking People "
                                          "to Eat Lionfish With No Predators?"), cands[2]])
    assert "QUESTION_IS_TITLE" in {e["code"] for e in sc.validate_contract(same, known, title)["errors"]}


def test_the_contract_markdown_shows_all_three_candidates_and_the_choice(tmp_path):
    md = sc.contract_markdown(_contract(), {"passed": True, "errors": [], "warnings": []}, {}, DOSSIER,
                              "Lionfish Have No Predators", "sha")
    assert md.count("total ") == 3 and "← chosen" in md and "record numbers" in md


def _metrics(name):
    return sc.voice_metrics(_fixture_text(name))


def test_voice_metrics_separate_the_reference_from_the_failures():
    v1, v2, v3 = (_metrics(f"narration_lionfish_{n}.txt") for n in ("v1", "v2", "contract_v3"))
    assert v2["mean_sentence_words"] < 10 < v1["mean_sentence_words"] < 15 < v3["mean_sentence_words"]
    assert v2["sentences_over_25"] == 2 and v1["sentences_over_25"] == 6 and v3["sentences_over_25"] == 17
    assert v2["attributions_per_minute"] <= sc.ATTRIBUTIONS_PER_MINUTE_MAX < v3["attributions_per_minute"]
    assert v3["words"] > 1300 and 800 < v2["words"] < 900


def _as_sentences(text, contract=None):
    return [{"text": x, "claim_ids": ["c1"], "kind": "event", "part": "opening"} for x in sc.spoken_sentences(text)]


def test_the_reference_narration_clears_every_voice_and_length_blocker():
    report = sc.validate_narration(_as_sentences(_fixture_text("narration_lionfish_v2.txt")), {"c1"}, 300)
    assert report["passed"], report["errors"]


def test_the_first_lane_narration_is_blocked_for_length_voice_and_leaks():
    report = sc.validate_narration(_as_sentences(_fixture_text("narration_lionfish_contract_v3.txt")), {"c1"}, 300)
    codes = {e["code"] for e in report["errors"]}
    assert {"LENGTH_OVER", "SENTENCE_MEAN_LONG", "ATTRIBUTION_DENSE", "PROMPT_LEAK"} <= codes
    assert "cut to about 776 words" in next(e["message"] for e in report["errors"] if e["code"] == "LENGTH_OVER")


def test_backstory_before_the_question_and_the_want_is_a_blocker():
    contract = _contract()
    early = [{"text": "Lionfish were first reported off Florida in 1985.", "claim_ids": ["c3"], "kind": "event", "part": "opening"}] + SENTENCES
    codes = {e["code"] for e in sc.validate_narration(early, KNOWN, 60, contract)["errors"]}
    assert "BACKSTORY_BEFORE_QUESTION" in codes
    late = SENTENCES[:2] + [dict(SENTENCES[1], text="Why?")] + [early[0]] + SENTENCES[2:]
    codes = {e["code"] for e in sc.validate_narration(late, KNOWN, 60, contract)["errors"]}
    assert "BACKSTORY_BEFORE_QUESTION" not in codes
    assert not sc.is_backstory("In the summer of 2025, he made seventy-three dive trips.", 2026)
    assert sc.is_backstory("The story has to go back to the reef.", 2026)


def test_an_overlong_narration_goes_back_for_cuts_within_the_shared_budget(tmp_path):
    long = [dict(SENTENCES[0], text=" ".join(["word"] * 12) + ".") for _ in range(20)] + SENTENCES

    class Long(FakeCaller):
        def call(self, **kw):
            if kw["stage"] == "narration" or kw["stage"].startswith("repair_"):
                self.calls.append(kw["stage"])
                assert kw["stage"] == "narration" or "the limit" in kw["user"]
                return {"sentences": [dict(x, text=x["text"].replace("word", kw["stage"][:6], 1)) for x in long]}, 0.0
            return super().call(**kw)
    caller = Long()
    with pytest.raises(sc.ContractApprovalRequired):
        _lane(tmp_path, caller).run()
    _approve_contract(tmp_path)
    with pytest.raises(sc.NarrationApprovalRequired) as stop:
        _lane(tmp_path, caller).run()
    assert [c for c in caller.calls if c.startswith("repair_")] == ["repair_1", "repair_2"]
    assert stop.value.details["status"] == "not_ready"
    record = json.loads((tmp_path / sc.NARRATION_FILE).read_text())
    assert any("over the ~155-word target" in r for r in record["not_ready_reasons"])
    md = (tmp_path / sc.NARRATION_MD).read_text()
    assert "LENGTH_OVER" in md and "mean sentence" in md and "attributions / spoken minute" in md


def test_the_rank_prompt_carries_every_narration_and_the_widened_scale():
    text = sc.rank_prompt("q", ["one.", "two.", "three."])
    assert "NARRATION C" in text and "distinctive" in text and '"ranking"' in text


def test_reply_text_skips_thinking_blocks():
    class B:
        def __init__(self, type, text=None):
            self.type = type
            if text is not None:
                self.text = text
    class R:
        content = [B("thinking"), B("text", '{"a": 1}')]
    assert sc.parse_json_reply(sc.reply_text(R())) == {"a": 1}


def test_quote_check_accepts_ellipsis_fragments_in_order():
    text = "Spread alone would just be a curiosity. What matters is what they do. Even the dinner plate has limits."
    assert sc.quote_in("Spread alone would just be a curiosity. ... Even the dinner plate has limits.", text)
    assert not sc.quote_in("Even the dinner plate has limits ... Spread alone", text)
    assert not sc.quote_in("", text)


# ── third round: numbers, side stories, list framing, question scoring, humour ────────────────

def test_numbers_are_capped_per_spoken_minute_and_the_reference_passes():
    for name, dense in (("v2", False), ("v1", True), ("contract_v3", True), ("contract_v4", True)):
        report = sc.validate_narration(_as_sentences(_fixture_text(f"narration_lionfish_{name}.txt")), {"c1"}, 300)
        assert ("NUMBER_DENSE" in {e["code"] for e in report["errors"]}) is dense, name


def test_counting_obstacles_is_a_parallel_list_blocker():
    for text, flagged in (("Then came a third limit: food safety.", True), ("The second wall is depth.", True),
                          ("Lionfish were first reported in 1985.", False), ("Another fish moved in.", False)):
        sents = [{"text": text, "claim_ids": ["c1"], "kind": "event", "part": "development_1"}]
        codes = {e["code"] for e in sc.validate_narration(sents, {"c1"}, 60)["errors"]}
        assert ("LIST_FRAMING" in codes) is flagged, text
    report = sc.validate_narration(_as_sentences(_fixture_text("narration_lionfish_v2.txt")), {"c1"}, 300)
    assert "LIST_FRAMING" not in {e["code"] for e in report["errors"]}


def test_side_stories_lists_and_purposeless_numbers_become_objectives_first():
    raw = _clean_review()
    raw["editorial_objectives"] = [{"objective": "tighten the close", "problem": "p"}]
    raw["development_removal"] = [{"development": 1, "changes_answer": True},
                                  {"development": 5, "sentences": [54, 58], "changes_answer": False,
                                   "note": "ciguatera does not change what the hunting is for"}]
    raw["parallel_obstacle_lists"] = [{"sentences": [54], "quote": "Then came a third limit"}]
    raw["numbers_without_purpose"] = [{"sentence": 55, "number": "194", "note": "sample size"}]
    review = sc.normalize_review(raw, SENTENCES, {})
    objectives = review["editorial_objectives"]
    assert len(objectives) == sc.MAX_EDITORIAL_OBJECTIVES
    assert "does not change the answer" in objectives[0]["problem"]
    assert "parallel-obstacle list" in objectives[1]["problem"] and "194" in objectives[2]["problem"]
    assert review["deferred_objectives"][0]["objective"] == "tighten the close"
    assert len(review["side_stories"]) == 1


def test_a_question_marked_down_for_an_honest_partial_answer_is_reported():
    cands = _contract()["question_candidates"]
    bad = dict(cands[2], reason="A strong paradox, but it ends on failure with no resolution.",
               scores={"curiosity": 3, "support": 3, "deliverable": 2})
    report = sc.validate_contract(_contract(question_candidates=[cands[0], cands[1], bad]),
                                  KNOWN, "Lionfish")
    assert "QUESTION_PENALISED_FOR_NO_FIX" in {e["code"] for e in report["errors"]}
    for reason in ("it ends on a constraint with little resolution", "an unresolved dispute rather than an answer"):
        c = dict(bad, reason=reason)
        r = sc.validate_contract(_contract(question_candidates=[cands[0], cands[1], c]), KNOWN, "x")
        assert "QUESTION_PENALISED_FOR_NO_FIX" in {e["code"] for e in r["errors"]}, reason
    prompt = sc.contract_prompt("q", DOSSIER, {}, 300)
    assert "honest partial answer" in prompt and "not a fix" in prompt


def test_the_reviewer_credits_situational_humour_but_never_requires_it():
    prompt = sc.review_b_prompt("q", _contract(), SENTENCES, DOSSIER, {})
    assert all(example in prompt for example in sc.HUMOR_EXAMPLES)
    assert "never ask for jokes" in prompt and "development_removal" in prompt
    assert "numbers_without_purpose" in prompt


def test_an_already_absent_development_is_reported_not_repaired_and_markers_are_ignored():
    raw = _clean_review()
    raw["development_removal"] = [{"development": 6, "sentences": [], "changes_answer": False, "note": "absent"}]
    review = sc.normalize_review(raw, SENTENCES, {})
    assert not review["side_stories"] and not review["editorial_objectives"]
    assert len(review["development_removal"]) == 1
    assert sc.quote_in("[1] Paul Carlson made seventy-three dive trips. ... [3] \"My freezer is full.\"",
                       " ".join(x["text"] for x in SENTENCES))


# ── the World consequence model (operator 2026-10-15; lane rule 2026-10-21) ──────────────────

def _claims_with_kinds(dossier, kinds):
    out = {}
    for c in dossier["claims"]:
        c = dict(c)
        c["story_kind"] = kinds.get(c["claim_id"], "event")
        out[c["claim_id"]] = c
    return out


def test_lionfish_v2_fails_the_consequence_rule():
    """The uploaded v2: a forward-hypothetical question and a MODEL result as its consequence."""
    claims = _claims_with_kinds(_lionfish_dossier(), json.loads(_fixture_text("lionfish_v2_story_kinds.json")))
    q = "What Happens When Florida Gets Good at Catching Lionfish?"
    v2 = _contract(central_question=q,
                   question_candidates=[dict(c, question=q if i == 1 else c["question"],
                                             claim_ids=["c77"], topic_fit=None) for i, c in enumerate(
                                                 _contract()["question_candidates"])],
                   decision={"what": "NOAA's 'Eat Lionfish' campaign", "when": "2010", "kind": "animal_targeted",
                             "claim_ids": ["c31"]},
                   consequence={"what": "the fishery can become less worth working as removals succeed",
                                "claim_ids": ["c77", "c78", "c80"]},
                   still_unfolding={"what": "a record 2026 Lionfish Challenge", "as_of": "2026", "claim_ids": ["c85"]})
    codes = {e["code"] for e in sc.validate_contract(v2, claims, q, consequence_rule=True)["errors"]}
    assert {"QUESTION_HYPOTHETICAL", "CONSEQUENCE_NOT_DOCUMENTED"} <= codes, codes
    assert sc.is_hypothetical_question(q)
    assert not sc.is_hypothetical_question("Why are Florida's divers still pulling record numbers of lionfish out?")


PYTHONS = {"claims": [
    {"claim_id": "p1", "claim_kind": "event", "source_url": "https://www.route-fifty.com/emerging-tech/2025/08/",
     "claim": "Burmese pythons were brought through the exotic pet trade and escaped their enclosures or were released.",
     "support_quote": "Burmese pythons are not native to Florida; they were brought through the exotic pet trade and "
                      "escaped their enclosures or were released"},
    {"claim_id": "p2", "claim_kind": "outcome", "source_url": "https://www.route-fifty.com/emerging-tech/2025/08/",
     "claim": "The pythons have reduced the population of fur-bearing animals by up to 95%.",
     "support_quote": "The pythons have reduced the population of fur-bearing animals by up to 95%"},
    {"claim_id": "p3", "claim_kind": "outcome", "source_url": "https://www.usgs.gov/publications/marsh-rabbit-mortalities",
     "claim": "Pythons accounted for 77% of rabbit mortalities within 11 months of translocation to Everglades National Park.",
     "support_quote": "Pythons accounted for 77% of rabbit mortalities within 11 months of their translocation to "
                      "Everglades National Park"},
    {"claim_id": "p4", "claim_kind": "event", "source_url": "https://myfwc.com/wildlifehabitats/nonnatives/python/",
     "claim": "As of April 2025, over 23,500 pythons have been removed from natural areas in Florida.",
     "support_quote": "As of April 2025, over 23,500 pythons have been removed from natural areas in the state of Florida"},
    {"claim_id": "p5", "claim_kind": "event", "source_url": "https://myfwc.com/wildlifehabitats/nonnatives/python/",
     "claim": "Florida began paying contracted hunters to remove pythons in spring 2017.",
     "support_quote": "After this program launched in spring 2017, the number and rate of Burmese pythons removed "
                      "from the wild increased"},
]}


def _pythons_contract():
    q = "Florida let pet pythons into the Everglades; why are hunters still pulling them out by the thousand?"
    return {
        "topic": "Burmese pythons in the Everglades",
        "question_candidates": [
            {"question": q, "claim_ids": ["p1", "p2"], "names_decision": True, "asks_consequence": True,
             "scores": {"curiosity": 3, "support": 3, "deliverable": 3},
             "topic_fit": {"screened": True, "verdict": "fits", "channel": "world", "reason": "introduced animal"}},
            {"question": "Why did Florida start paying python hunters in 2017?", "claim_ids": ["p5"],
             "names_decision": True, "asks_consequence": True, "scores": {"curiosity": 2, "support": 3, "deliverable": 2}},
            {"question": "Where did the Everglades' rabbits go?", "claim_ids": ["p3"], "names_decision": False,
             "asks_consequence": True, "scores": {"curiosity": 2, "support": 2, "deliverable": 2}}],
        "chosen": 0, "chosen_reason": "names the introduction and asks about what it still causes",
        "central_question": q,
        "ending_answer": "Because the pets that escaped are still eating the Everglades: hunters have taken "
                         "over 23,500 and the mammals have not come back.",
        "decision": {"what": "Burmese pythons imported through the exotic pet trade, released or escaped",
                     "who": "pet owners and the trade", "when": "1980s-1990s", "kind": "animal_introduced",
                     "claim_ids": ["p1"]},
        "consequence": {"what": "fur-bearing mammals down by up to 95%", "claim_ids": ["p2", "p3"]},
        "still_unfolding": {"what": "over 23,500 removed as of April 2025", "as_of": "2025", "claim_ids": ["p4"]},
        "human_perspective": {"person": "a contracted python hunter", "want": "paid removals", "action": "night hunts",
                              "reward": "", "claim_ids": {"want": ["p5"], "action": ["p4"]}},
        "reasonable_attempt": {"what": "pay hunters", "why_it_made_sense": "removals rose", "claim_ids": ["p5"]},
        "complication": {"what": "pythons are nearly invisible", "mechanism": "detection below 5%", "claim_ids": ["p4"]},
        "developments": [{"what_happens": "the mammals vanish", "what_it_changes": "the reef of the Everglades loses its prey base",
                          "why_next_matters": "so Florida pays hunters", "claim_ids": ["p2"]},
                         {"what_happens": "hunters are paid", "what_it_changes": "removals climb into the thousands",
                          "why_next_matters": "", "claim_ids": ["p4"]}],
        "recurring_image": None,
        "forbidden_claims": ["pythons can be eradicated"],
        "tangents_left_out": [{"tangent": "robot rabbits", "why": "no results yet"}],
    }


def test_a_pythons_style_introduction_still_eating_the_everglades_passes():
    claims = _claims_with_kinds(PYTHONS, {})
    report = sc.validate_contract(_pythons_contract(), claims, "Burmese pythons", consequence_rule=True)
    assert report["passed"], report["errors"]


def test_each_consequence_rule_failure_is_named():
    claims = _claims_with_kinds(PYTHONS, {"p2": "model", "p3": "interpretation"})
    base = _pythons_contract()

    def codes(**over):
        return {e["code"] for e in sc.validate_contract(dict(base, **over), claims, "x", consequence_rule=True)["errors"]}
    assert "CONSEQUENCE_NOT_DOCUMENTED" in codes()                       # only a model + an interpretation
    claims = _claims_with_kinds(PYTHONS, {})
    assert "DECISION_NOT_DELIBERATE" in codes(decision=dict(base["decision"], kind="accident"))
    assert "DECISION_UNDATED" in codes(decision=dict(base["decision"], when="", what="pets released"))
    assert "STILL_UNFOLDING_NOT_PRESENT" in codes(still_unfolding={"what": "the 2017 programme", "claim_ids": ["p5"]})
    assert "STILL_UNFOLDING_MISSING" in codes(still_unfolding={})
    cands = base["question_candidates"]
    off = dict(cands[0], topic_fit={"screened": True, "verdict": "no_story", "channel": "neither", "reason": "x"})
    assert "QUESTION_NOT_WORLD" in codes(question_candidates=[off] + cands[1:])
    assert "QUESTION_NOT_CONSEQUENCE" in codes(question_candidates=[dict(cands[0], asks_consequence=False)] + cands[1:])
    # History and Nature are not held to the World rule
    assert sc.validate_contract(dict(base, decision={}), claims, "x", consequence_rule=False)["passed"]
    assert sc.consequence_rule_applies("") and sc.consequence_rule_applies("world")
    assert not sc.consequence_rule_applies("history")


def test_the_blind_reader_must_recover_the_chain_and_the_ending_must_be_today():
    raw = _clean_review()
    raw["ending_from_today"] = False
    review = sc.normalize_review(raw, SENTENCES, {"decision": "NOAA's campaign", "consequence": "none",
                                                 "still_unfolding": ""}, consequence_rule=True)
    codes = [b["code"] for b in review["consequence_blockers"]]
    assert codes.count("CONSEQUENCE_CHAIN_MISSED") == 2 and "ENDING_NOT_FROM_TODAY" in codes
    assert sc.needs_repair(review)
    assert review["rubric_max"] == 3 * (len(sc.RUBRIC) + 1)
    status, reasons = sc.narration_status({"review": review, "validation": {"errors": []}})
    assert status == "not_ready" and any("could not recover" in r for r in reasons)
    early_end = [dict(x, claim_ids=[] if x["claim_ids"] == ["c6"] else x["claim_ids"]) for x in SENTENCES]
    report = sc.validate_narration(early_end, KNOWN, 60, _contract(), consequence_rule=True)
    assert "ENDING_NOT_FROM_TODAY" in {e["code"] for e in report["errors"]}


def test_the_contract_stage_screens_every_candidate_with_topic_fit(tmp_path):
    caller = FakeCaller()
    with pytest.raises(sc.ContractApprovalRequired):
        _lane(tmp_path, caller).run()
    assert caller.calls.count("topic_fit") == 3
    md = (tmp_path / sc.CONTRACT_MD).read_text()
    assert md.count("topic_fit: fits (world)") == 3 and "World consequence model" in md
