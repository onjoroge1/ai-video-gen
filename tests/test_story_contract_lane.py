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
]}


def _contract(**overrides):
    contract = {
        "topic": "Lionfish removal in Florida",
        "central_question": "What happens when you get good at catching the thing you're paid to catch?",
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
]


class FakeCaller:
    """Canned replies by stage; counts calls. `review_b` is a list consumed in order (last repeats)."""
    provider = "anthropic"

    def __init__(self, review_b=None, fail_on=None):
        self.calls = []
        self.review_b = list(review_b or [_clean_review()])
        self.fail_on = fail_on or set()

    def call(self, *, role, stage, system, user, max_tokens=8000):
        self.calls.append(stage)
        if stage in self.fail_on:
            raise RuntimeError(f"provider died during {stage}")
        if stage == "evidence":
            return {"claim_kinds": {"c1": "event", "c2": "event", "c3": "event", "c4": "model", "c5": "event"},
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
                    "partial removal", "ending_answer": "enough per reef"}, 0.005
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
    return sc.LaneRun(question="What Happens When Florida Gets Good at Catching Lionfish?",
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
    return {e["code"] for e in sc.validate_contract(contract, {"c1", "c2", "c3", "c4", "c5"})["errors"]}


def test_a_complete_contract_passes():
    report = sc.validate_contract(_contract(), {"c1", "c2", "c3", "c4", "c5"})
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
    codes = [w["code"] for w in sc.validate_narration(sents, {"c1"}, 60)["warnings"]]
    assert codes.count("PROMPT_LEAK") == 2
