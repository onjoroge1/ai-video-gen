"""The opening retry rule (2026-10-14): re-cut a below-B 45-second opening on paid pictures.

Every fixture here is synthetic and provider-free. The one language-model call (R2) is an injected
function; tests pass a stub and count its calls. Word timings are 0.4 s per word, so the instant
of every anchor is readable from its word index:

    alpha bravo charlie delta echo, foxtrot golf hotel india juliet. kilo lima mike november oscar papa
    0.0   0.4   0.8     1.2   1.6   2.0     2.4  2.8   3.2   3.6     4.0  4.4  4.8  5.2      5.6   6.0
"""
import copy
import inspect
import json

import pytest

import explainer_pipeline as ep
import opening_retry as retry

NARRATION = ("alpha bravo charlie delta echo, foxtrot golf hotel india juliet. "
             "kilo lima mike november oscar papa")
STEP = 0.4
DURATION = 6.4
ROLES = ("cold_consequence", "prediction_gate", "payoff")
SCRIPT = {"title": "A title", "hook": "A hook", "_story_contract": {"visual_promise": "a promise"}}
VALIDATION = {"checks": {"prediction_scenes": [2], "answer_scenes": [3],
                         "max_attention_gap_sec": 30.0, "max_exposition_block_sec": 10.0,
                         "unresolved_loops": []},
              "errors": [], "warnings": []}
# No packaging contract and whole-script narrative failures: Visual at 20/20 still leaves the
# opening under 80, which is a script shortfall rather than a cut-placement problem.
WEAK_SCRIPT = {"title": "A title", "hook": "A hook"}
WEAK_VALIDATION = {"checks": {"prediction_scenes": [2], "answer_scenes": [3],
                              "max_attention_gap_sec": 70.0, "max_exposition_block_sec": 50.0,
                              "unresolved_loops": ["an open question"]},
                   "errors": [], "warnings": []}


def _words(narration=NARRATION, step=STEP):
    return [[word, round(i * step, 3), round(i * step + step * 0.9, 3)]
            for i, word in enumerate(narration.split())]


def _state(scene, number, anchor, strategy="distinct", **extra):
    state = {"state_id": f"state:s{scene:03d}:e{number:02d}",
             "asset_id": f"asset:s{scene:03d}:e{number:02d}", "anchor_phrase": anchor,
             "asset_strategy": strategy, "asset_status": "accepted", "purpose": "evidence",
             "verified_visible_information": True}
    state.update(extra)
    return state


def _clean_scene(scene):
    return [_state(scene, 1, "alpha bravo", "master"), _state(scene, 2, "foxtrot golf"),
            _state(scene, 3, "kilo lima")]


def _ctx(middle, *, third=None, script=SCRIPT, validation=VALIDATION, **kwargs):
    states = [_clean_scene(1), middle, third if third is not None else _clean_scene(3)]
    return retry.OpeningContext(
        scenes=[{"narration": NARRATION, "story_role": role} for role in ROLES],
        durations=[DURATION] * 3, word_times=[_words() for _ in range(3)], states=states,
        script=script, validation=validation, **kwargs)


def _crowded_crop_scene():
    """Scene 2: a crop 0.8 s after the picture it crops; every cut of the scene is repaired."""
    return [_state(2, 1, "alpha bravo", "master"), _state(2, 2, "foxtrot golf"),
            _state(2, 3, "hotel india", "detail_reframe", source_asset_id="asset:s002:e02"),
            _state(2, 4, "kilo lima")]


def _crowded_anchor_scene(n=2):
    """'lima mike' 1.2 s after 'india juliet'; the clause starts at 'foxtrot'."""
    return [_state(n, 1, "alpha bravo", "master"), _state(n, 2, "india juliet"),
            _state(n, 3, "lima mike")]


def _duplicate_scene(n=2):
    """Two pictures on 'foxtrot golf'. Three planned, so the 70% floor allows no drop."""
    return [_state(n, 1, "alpha bravo", "master"), _state(n, 2, "foxtrot golf"),
            _state(n, 3, "foxtrot golf")]


def _duplicates():
    """Scenes 2 and 3 each carry one duplicate: 4 of 6 cuts aligned, under the 0.70 cap."""
    return _ctx(_duplicate_scene(2), third=_duplicate_scene(3))


REBIND_BOTH = {"anchors": [{"state_id": "state:s002:e03", "anchor_phrase": "kilo lima"},
                           {"state_id": "state:s003:e03", "anchor_phrase": "kilo lima"}]}


class _Rebind:
    def __init__(self, answer=None, cost=0.0123):
        self.calls = []
        self.answer = answer
        self.cost = cost

    def __call__(self, request):
        self.calls.append(request)
        return self.answer, self.cost


def _reasons(ctx):
    return {entry["state_id"]: entry["reason"]
            for entry in retry.diagnose_opening(ctx)["cuts"] if not entry["aligned"]}


# ── diagnosis ─────────────────────────────────────────────────────────────────────────────────


def _one_scene(states, narration=NARRATION, duration=DURATION, step=STEP):
    return retry.OpeningContext(
        scenes=[{"narration": narration, "story_role": "cold_consequence"}],
        durations=[duration], word_times=[_words(narration, step)], states=[states],
        script=SCRIPT, validation=VALIDATION)


def test_crowded_prev_and_crowded_next_are_told_apart():
    ctx = _one_scene([_state(1, 1, "alpha bravo", "master"), _state(1, 2, "juliet. kilo"),
                      _state(1, 3, "lima mike")])
    reasons = _reasons(ctx)
    # 'juliet' at 3.6 is pulled back because 'lima' (4.4) leaves no room after it; 'lima' itself
    # sits 0.8 s after its predecessor.
    assert reasons == {"state:s001:e02": "crowded_next", "state:s001:e03": "crowded_prev"}
    cuts = {c["state_id"]: c for c in retry.diagnose_opening(ctx)["cuts"]}
    assert cuts["state:s001:e02"]["conflicts_with"] == ["state:s001:e03"]
    assert cuts["state:s001:e03"]["conflicts_with"] == ["state:s001:e02"]


def test_duplicate_out_of_order_short_tail_and_unresolved_reasons():
    duplicate = _reasons(_one_scene(_duplicate_scene()[:1] + [
        _state(1, 2, "foxtrot golf"), _state(1, 3, "foxtrot golf")]))
    assert duplicate["state:s001:e03"] == "duplicate_anchor"
    order = _reasons(_one_scene([_state(1, 1, "alpha bravo", "master"),
                                 _state(1, 2, "kilo lima"), _state(1, 3, "foxtrot golf")]))
    assert order["state:s001:e03"] == "out_of_order"
    tail = _reasons(_one_scene([_state(1, 1, "alpha bravo", "master"),
                                _state(1, 2, "foxtrot golf"), _state(1, 3, "oscar papa")]))
    assert tail == {"state:s001:e03": "short_tail"}
    unresolved = _reasons(_one_scene([_state(1, 1, "alpha bravo", "master"),
                                      _state(1, 2, "zulu yankee whiskey"),
                                      _state(1, 3, "kilo lima")]))
    assert unresolved["state:s001:e02"] == "unresolved_anchor"


def test_a_cut_moved_only_by_its_neighbour_says_so():
    ctx = _one_scene([_state(1, 1, "alpha bravo", "master"), _state(1, 2, "zulu yankee whiskey"),
                      _state(1, 3, "foxtrot golf"), _state(1, 4, "kilo lima")])
    reasons = _reasons(ctx)
    assert reasons["state:s001:e02"] == "unresolved_anchor"
    assert reasons["state:s001:e03"] == "repaired_by_neighbour"
    assert reasons["state:s001:e04"] == "repaired_by_neighbour"


def test_a_whole_scene_respaced_evenly_says_so():
    narration = " ".join(f"word{i}" for i in range(40))
    ctx = _one_scene([_state(1, 1, "word0 word1", "master"), _state(1, 2, "word4 word5"),
                      _state(1, 3, "word8 word9")], narration=narration, duration=16.0)
    reasons = _reasons(ctx)
    assert set(reasons.values()) == {"even_spacing_fallback"}


def test_diagnosis_reports_counts_uncapped_literal_45_and_the_ceiling():
    diagnosis = retry.diagnose_opening(_ctx(_crowded_crop_scene()))
    assert (diagnosis["aligned"], diagnosis["total"]) == (4, 7)
    assert diagnosis["hard_failures"] == ["semantic_sync"]
    assert diagnosis["score"] == 69 and diagnosis["uncapped_score"] > 80
    # Every cut of this 19.2 s opening starts before 45 s.
    assert diagnosis["literal_45"] == {"aligned": 4, "cuts": 7, "ratio": round(4 / 7, 3)}
    assert diagnosis["ceiling"] >= diagnosis["uncapped_score"]
    assert diagnosis["reasons"] == {"crowded_next": 1, "crowded_prev": 2}


def test_literal_45_alignment_counts_only_cuts_that_start_before_45_seconds():
    plan = [[{"start_sec": 0.0}, {"start_sec": 20.0, "semantic_aligned": True}],
            [{"start_sec": 0.0}, {"start_sec": 4.0, "semantic_aligned": False},
             {"start_sec": 8.0, "semantic_aligned": False}]]
    assert retry.literal_45_alignment(plan, [40.0, 12.0]) == {"aligned": 1, "cuts": 2,
                                                              "ratio": 0.5}


# ── the ceiling ───────────────────────────────────────────────────────────────────────────────


def test_recut_ceiling_is_raw_minus_visual_plus_twenty_over_assessed():
    ctx = _ctx(_crowded_crop_scene())
    report = retry.score_opening(ctx, retry.compile_opening(ctx))["report"]
    visual = next(c for c in report["components"] if c["name"].startswith("Visual"))
    expected = round(100 * (report["raw_score"] - visual["score"] + 20) / report["assessed_max"])
    assert retry.recut_ceiling(report) == expected
    assert retry.uncapped_score(report) == round(100 * report["raw_score"]
                                                 / report["assessed_max"])


def test_recut_ceiling_on_known_numbers():
    report = {"raw_score": 78, "assessed_max": 95,
              "components": [{"name": "Visual continuity & semantic sync", "score": 16, "max": 20}]}
    assert retry.recut_ceiling(report) == 86        # aral-v2: round(100 * 82 / 95)
    report = {"raw_score": 69, "assessed_max": 95,
              "components": [{"name": "Visual continuity & semantic sync", "score": 18, "max": 20}]}
    assert retry.recut_ceiling(report) == 75        # bees_v9: the script shortfall


# ── R1 ────────────────────────────────────────────────────────────────────────────────────────


def test_r1_drops_a_crowded_crop_before_any_picture():
    ctx = _ctx(_crowded_crop_scene())
    decision = retry.decide_opening_retry(ctx)
    assert decision["outcome"] == "passed" and decision["rung"] == "R1"
    assert [(e["op"], e["state_id"]) for e in decision["edits"]] == [("drop", "state:s002:e03")]
    assert decision["after"]["score"] >= 80 and not decision["after"]["hard_failures"]
    assert decision["after"]["ratio"] >= 0.75
    # The planner never touches the shared lists; only the caller applies the chosen edits.
    assert len(ctx.states[1]) == 4


def test_r1_moves_a_crowded_anchor_to_the_start_of_its_own_clause():
    ctx = _ctx(_crowded_anchor_scene(2), third=_crowded_anchor_scene(3))
    decision = retry.decide_opening_retry(ctx)
    assert decision["before"]["hard_failures"] == ["semantic_sync"]
    assert decision["outcome"] == "passed"
    assert decision["edits"] == [{
        "op": "reanchor", "state_id": f"state:s00{n}:e02", "old": "india juliet",
        "new": "foxtrot golf hotel india juliet", "rung": "R1", "how": "clause start"}
        for n in (2, 3)]
    assert "foxtrot golf hotel india juliet" in NARRATION
    assert decision["after"]["aligned"] == decision["after"]["cuts"]


def test_clause_start_anchors_are_verbatim_and_never_the_old_anchor():
    options = retry.clause_start_anchors(NARRATION, "india juliet")
    assert options == [("clause start", "foxtrot golf hotel india juliet"),
                       ("sentence start", "alpha bravo charlie delta echo, foxtrot golf hotel "
                                          "india juliet")]
    assert all(phrase in NARRATION for _how, phrase in options)
    assert retry.clause_start_anchors(NARRATION, "alpha bravo") == []
    assert retry.clause_start_anchors(NARRATION, "kilo lima") == []


def test_r1_drops_a_distinct_picture_only_down_to_the_opening_floor():
    middle = [_state(2, 1, "alpha bravo", "master"), _state(2, 2, "foxtrot golf"),
              _state(2, 3, "hotel india"), _state(2, 4, "kilo lima")]
    decision = retry.decide_opening_retry(_ctx(middle))
    assert decision["outcome"] == "passed"
    drops = [e for e in decision["edits"] if e["op"] == "drop"]
    assert len(drops) == 1 and drops[0]["asset_strategy"] == "distinct"
    # Four planned: the floor max(2, ceil(2.8)) = 3 allows exactly one drop.
    assert retry.opening_floor(4) == 3 and retry.opening_floor(3) == 3
    assert retry.opening_floor(2) == 2 and retry.opening_floor(10) == 7


def test_the_floor_counts_states_already_rejected_by_the_asset_policy():
    middle = [_state(2, 1, "alpha bravo", "master"), _state(2, 2, "foxtrot golf"),
              _state(2, 3, "hotel india"), _state(2, 4, "kilo lima")]
    # Five planned, one already dropped as rejected: floor 4, so nothing more may go.
    ctx = _ctx(middle, planned_counts=[3, 5, 3])
    decision = retry.decide_opening_retry(ctx)
    assert not [e for e in decision["edits"] if e["op"] == "drop"]
    assert decision["outcome"] == "below_b_after_retry"


def test_r1_never_drops_a_paid_motion_clip():
    middle = [_state(2, 1, "alpha bravo", "master"), _state(2, 2, "foxtrot golf"),
              _state(2, 3, "hotel india"), _state(2, 4, "kilo lima")]
    ctx = _ctx(middle, motion_state_ids={"state:s002:e03"})
    assert retry.protected_state_ids(ctx)["state:s002:e03"] == "carries a paid motion clip"
    decision = retry.decide_opening_retry(ctx)
    assert "state:s002:e03" not in {e["state_id"] for e in decision["edits"]
                                    if e["op"] == "drop"}
    for row in decision["candidates"]:
        assert ("drop", "state:s002:e03") not in {(e["op"], e["state_id"]) for e in row["edits"]}


def test_r1_never_drops_the_callback_source_or_a_picture_another_state_crops():
    middle = [_state(2, 1, "alpha bravo", "master"), _state(2, 2, "foxtrot golf"),
              _state(2, 3, "hotel india"), _state(2, 4, "kilo lima")]
    plan = {"continuity_pack": {"callback": {"reuse_source_asset_id": "asset:s002:e03"},
                                "opening_object": {"opening_source_asset_id": "asset:s001:e01"}},
            "scenes": [{"scene_index": 9, "states": [
                _state(10, 1, "x", "detail_reframe", source_asset_id="asset:s002:e02")]}]}
    ctx = _ctx(middle, evidence_plan=plan, scene_indexes=[0, 1, 2])
    protected = retry.protected_state_ids(ctx)
    assert protected["state:s002:e03"] == "callback reuse source"
    assert protected["state:s002:e02"] == "source of state:s010:e01"
    assert protected["state:s001:e01"] == "scene master"
    decision = retry.decide_opening_retry(ctx)
    for row in decision["candidates"]:
        dropped = {e["state_id"] for e in row["edits"] if e["op"] == "drop"}
        assert not dropped & {"state:s002:e03", "state:s002:e02", "state:s002:e01"}


def _plan_for(states, *, extra_states=()):
    scenes = [{"scene_index": k, "opening": True, "state_capacity": 4, "states_requested": 3,
               "states": scene_states} for k, scene_states in enumerate(states)]
    if extra_states:
        scenes.append({"scene_index": len(states), "opening": False, "state_capacity": 4,
                       "states": list(extra_states)})
    return {"continuity_pack": {}, "scenes": scenes}


def test_a_drop_that_leaves_an_opening_beat_one_distinct_picture_is_rejected():
    # Master, a crowded distinct picture, and two crops of the master: dropping the distinct
    # picture leaves one generated asset -- insufficient_distinct_evidence_assets.
    middle = [_state(2, 1, "alpha bravo", "master"), _state(2, 2, "bravo charlie"),
              _state(2, 3, "foxtrot golf", "detail_reframe", source_asset_id="asset:s002:e01"),
              _state(2, 4, "kilo lima", "detail_reframe", source_asset_id="asset:s002:e01")]
    ctx = _ctx(middle)
    ctx.evidence_plan = _plan_for(ctx.states)
    baseline = retry.evaluate(ctx, [])
    compare = {"validation_errors": baseline["validation_errors"],
               "bolt_ratio": baseline["bolt_ratio"]}
    candidate = retry.evaluate(ctx, [retry.drop_edit(middle[1])], baseline=compare)
    assert not candidate["valid"]
    assert any("insufficient_distinct_evidence_assets" in reason
               for reason in candidate["rejected_because"])


def test_a_drop_that_pushes_bolt_past_35_percent_is_rejected():
    def bolt(state):
        return dict(state, include_bolt=True, purpose="action", bolt_action="Bolt lifts the gate")
    middle = [_state(2, 1, "alpha bravo", "master"), _state(2, 2, "foxtrot golf"),
              _state(2, 3, "hotel india"), _state(2, 4, "kilo lima")]
    ctx = _ctx(middle)
    later = [bolt(_state(4, n, "x")) for n in (1, 2, 3, 4, 5)]
    ctx.evidence_plan = _plan_for(ctx.states, extra_states=later)
    baseline = retry.evaluate(ctx, [])
    assert baseline["bolt_ratio"] <= 0.35
    compare = {"validation_errors": baseline["validation_errors"],
               "bolt_ratio": baseline["bolt_ratio"]}
    edits = [retry.drop_edit(ctx.states[0][2]), retry.drop_edit(ctx.states[1][2]),
             retry.drop_edit(ctx.states[2][2])]
    candidate = retry.evaluate(ctx, edits, baseline=compare)
    assert candidate["bolt_ratio"] > 0.35
    assert not candidate["valid"]
    assert any("Bolt" in reason or "bolt_state_budget" in reason
               for reason in candidate["rejected_because"])


def test_edits_never_reorder_states():
    states = [_crowded_crop_scene()]
    edited = retry.apply_edits(states, [retry.drop_edit(states[0][2]),
                                        retry.reanchor_edit(states[0][3], "lima mike", "R1")])
    assert [s["state_id"] for s in edited[0]] == ["state:s002:e01", "state:s002:e02",
                                                  "state:s002:e04"]
    assert edited[0][2]["anchor_phrase"] == "lima mike"
    assert states[0][3]["anchor_phrase"] == "kilo lima", "apply_edits must not mutate"


# ── acceptance ────────────────────────────────────────────────────────────────────────────────


def _shot(source, duration, kind="still"):
    return {"source": source, "duration": duration, "kind": kind}


def test_rendered_gate_checks_hold_margin_cadence_and_source_change():
    good = [[_shot("a", 2.0), _shot("b", 2.5), _shot("c", 3.0)]]
    assert retry.rendered_gate_checks(good, 0.45)["passed"]
    # 3.45 s passes the 3.5 s gate by rounding; the retry requires margin.
    on_the_line = [[_shot("a", 2.0), _shot("b", 3.45), _shot("c", 2.0)]]
    checks = retry.rendered_gate_checks(on_the_line, 0.45)
    assert not checks["passed"] and "holds 3.45s" in checks["failures"][0]
    slow = [[_shot("a", 3.3), _shot("b", 3.3), _shot("c", 3.3)]]
    assert "average state" in retry.rendered_gate_checks(slow, 0.45)["failures"][0]
    same = [[_shot("a", 2.0), _shot("a", 2.0), _shot("a", 2.0), _shot("b", 2.0)]]
    assert "source-change ratio" in retry.rendered_gate_checks(same, 0.45)["failures"][0]
    # A motion shot is judged against its clip allowance, not the still limit.
    motion = [[_shot("a", 2.0), _shot("b", 5.0, kind="i2v"), _shot("c", 2.0)]]
    assert retry.rendered_gate_checks(motion, 0.45)["passed"]


def test_acceptance_needs_b_no_hard_failure_and_75_percent_alignment():
    assert retry.acceptance_misses(86, "B", [], 0.80) == []
    assert retry.acceptance_misses(80, "B", [], 0.75) == []
    # wolves01's best single path: 91 A, but 8/11 = 73% aligned is under the margin.
    assert retry.acceptance_misses(91, "A", [], 0.727) == ["alignment 73% under 75%"]
    assert retry.acceptance_misses(79, "C", [], 0.9) == ["score 79 C under B"]
    assert retry.acceptance_misses(69, "D", ["semantic_sync"], 0.667) == [
        "score 69 D under B", "hard failure(s): semantic_sync", "alignment 67% under 75%"]
    assert retry.ACCEPT_ALIGNMENT == 0.75 and retry.TARGET_SCORE == 80
    assert retry.ACCEPT_MAX_HOLD_SECONDS == 3.4


def test_an_unaccepted_best_attempt_at_b_is_kept_without_a_below_b_label(monkeypatch):
    ctx = _ctx(_crowded_crop_scene())
    real = retry.acceptance_misses
    # Hold every candidate to an impossible margin: nothing is accepted, and the best attempt,
    # which clears B by grade, is kept and labelled as such.
    monkeypatch.setattr(retry, "acceptance_misses",
                        lambda score, grade, hard, ratio: real(score, grade, hard, ratio)
                        or ["margin"] if ratio < 1.01 else [])
    decision = retry.decide_opening_retry(ctx)
    assert decision["outcome"] == "passed_without_margin"
    assert decision["after"]["score"] >= 80 and decision["edits"]
    assert "B by grade" in retry.summary_line(decision)
    assert retry.degraded_reason(decision, {"score": decision["after"]["score"],
                                            "hard_failures": []}, None) == ""


def test_choose_prefers_fewest_distinct_pictures_then_highest_score():
    rows = [
        {"accepted": True, "distinct_dropped": 1, "score": 95, "ratio": 1.0, "edit_count": 1},
        {"accepted": True, "distinct_dropped": 0, "score": 84, "ratio": 0.8, "edit_count": 2},
        {"accepted": True, "distinct_dropped": 0, "score": 86, "ratio": 0.8, "edit_count": 3},
        {"accepted": False, "distinct_dropped": 0, "score": 99, "ratio": 1.0, "edit_count": 0},
    ]
    assert retry.choose(rows) is rows[2]


def test_a_below_b_opening_with_no_better_candidate_keeps_its_plan():
    ctx = _duplicates()
    decision = retry.decide_opening_retry(ctx, rebind=None)
    assert decision["outcome"] == "below_b_after_retry"
    assert decision["edits"] == []
    assert decision["llm_calls"] == 0


def test_an_opening_already_at_b_is_not_retried():
    decision = retry.decide_opening_retry(_ctx(_clean_scene(2)), rebind=_Rebind())
    assert decision["outcome"] == "not_needed" and decision["edits"] == []
    assert decision["llm_calls"] == 0


# ── R2 ────────────────────────────────────────────────────────────────────────────────────────


def test_r2_runs_once_only_when_r1_fails_and_its_anchor_is_validated():
    rebind = _Rebind(REBIND_BOTH)
    decision = retry.decide_opening_retry(_duplicates(), rebind=rebind)
    assert len(rebind.calls) == 1
    assert rebind.calls[0]["targets"] == ["state:s002:e03", "state:s003:e03"]
    assert decision["outcome"] == "passed" and decision["rung"] == "R2"
    assert decision["edits"] == [
        {"op": "reanchor", "state_id": f"state:s00{n}:e03", "old": "foxtrot golf",
         "new": "kilo lima", "rung": "R2", "how": "language-model re-bind"} for n in (2, 3)]
    assert decision["llm_calls"] == 1 and decision["cost_usd"] == pytest.approx(0.0123)


def test_r2_is_not_called_when_r1_succeeds_or_the_ceiling_is_under_b():
    rebind = _Rebind()
    retry.decide_opening_retry(_ctx(_crowded_crop_scene()), rebind=rebind)
    retry.decide_opening_retry(_ctx(_duplicate_scene(), third=_duplicate_scene(3),
                                    script=WEAK_SCRIPT, validation=WEAK_VALIDATION),
                               rebind=rebind)
    assert rebind.calls == []


def test_r2_unavailable_is_no_edit_and_no_crash():
    def broken(_request):
        raise RuntimeError("provider down")
    decision = retry.decide_opening_retry(_duplicates(), rebind=broken)
    assert decision["outcome"] == "below_b_after_retry"
    assert decision["r2"]["error"].startswith("RuntimeError")
    assert decision["llm_calls"] == 1


@pytest.mark.parametrize("phrase, why", [
    ("Kilo lima", "verbatim"),                # case changed: not the narration's words
    ("kilo lima mike zulu", "verbatim"),      # words the narration does not contain
    ("foxtrot golf", "duplicates"),           # the same words as another picture
    ("hotel india", "after its predecessor"),  # 0.8 s after 'foxtrot golf'
    ("bravo charlie", "out of order"),        # before its predecessor
    ("oscar papa", "before the scene ends"),  # 0.8 s left in the scene
])
def test_r2_rejects_non_verbatim_duplicate_crowded_out_of_order_and_short_tail(phrase, why):
    ctx = _ctx(_duplicate_scene())
    edits, rejections = retry.validate_rebind(
        ctx, ctx.states, ["state:s002:e03"],
        {"anchors": [{"state_id": "state:s002:e03", "anchor_phrase": phrase}]})
    assert edits == []
    assert len(rejections) == 1 and why in rejections[0]["reason"]


def test_r2_rejects_malformed_output_and_states_it_was_not_asked_about():
    ctx = _ctx(_duplicate_scene())
    assert retry.validate_rebind(ctx, ctx.states, ["state:s002:e03"], "kilo lima") == (
        [], [{"state_id": "", "reason": "malformed output"}])
    edits, rejections = retry.validate_rebind(
        ctx, ctx.states, ["state:s002:e03"],
        {"anchors": [{"state_id": "state:s001:e02", "anchor_phrase": "kilo lima"}]})
    assert edits == [] and "could not place" in rejections[0]["reason"]


def test_the_r2_request_carries_measured_words_and_marks_only_the_targets():
    ctx = _ctx(_duplicate_scene())
    request = retry.rebind_request(ctx, ctx.states, ["state:s002:e03"])
    payload = json.loads(request["user"][request["user"].index("{"):
                                         request["user"].rindex('\n\nReturn ONLY JSON')])
    (scene,) = payload["scenes"]
    assert scene["scene"] == 2 and scene["words"][5] == ["foxtrot", 2.0]
    assert [p["rebind"] for p in scene["pictures_in_order"]] == [False, False, True]


# ── script shortfall, the stop, and the degraded reason ───────────────────────────────────────


def test_a_script_shortfall_tries_no_plan_rung_and_reports_the_axes():
    ctx = _ctx(_crowded_crop_scene(), script=WEAK_SCRIPT, validation=WEAK_VALIDATION)
    decision = retry.decide_opening_retry(ctx, rebind=_Rebind())
    assert decision["outcome"] == "script_shortfall"
    assert decision["ceiling"] < 80
    assert decision["candidates"] == [] and decision["edits"] == []
    axes = {row["component"]: row for row in decision["below_b_axes"]}
    assert axes["Narrative propulsion"]["measured_over"] == "the whole script"
    assert axes["Narrative propulsion"]["points_lost"] == 18


def test_the_stop_raises_opening_below_b_with_its_report(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENING_RETRY_ALLOW_BELOW_B", raising=False)
    ctx = _ctx(_crowded_crop_scene(), script=WEAK_SCRIPT, validation=WEAK_VALIDATION)
    decision = retry.decide_opening_retry(ctx)
    with pytest.raises(ep.OpeningBelowB) as raised:
        ep._stop_if_opening_below_b(decision, str(tmp_path), log=lambda m: None)
    assert issubclass(ep.OpeningBelowB, ValueError)
    assert "OPENING_BELOW_B" in str(raised.value) and "Stopped before buying" in str(raised.value)
    text = (tmp_path / "opening_retry_report.txt").read_text()
    report = json.loads((tmp_path / "opening_retry_report.json").read_text())
    assert raised.value.report_path == str(tmp_path / "opening_retry_report.txt")
    assert report["stopped"] is True and report["recut_ceiling"] == decision["ceiling"]
    assert report["literal_45"] and report["diagnosis"]
    assert {o["option"] for o in report["paid_options"]} == {
        "re-voice the opening", "buy new opening images", "replan the opening beats"}
    for needle in ("re-cut ceiling", "Narrative propulsion", "re-voice", "0.75-1.20",
                   "new plan approval", "OPENING_RETRY_ALLOW_BELOW_B=1"):
        assert needle in text


def test_the_operator_override_continues_and_is_marked_degraded(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENING_RETRY_ALLOW_BELOW_B", "1")
    ctx = _ctx(_crowded_crop_scene(), script=WEAK_SCRIPT, validation=WEAK_VALIDATION)
    decision = retry.decide_opening_retry(ctx)
    logged = []
    ep._stop_if_opening_below_b(decision, str(tmp_path), log=logged.append)
    assert decision["continued_below_b"] is True and "OPENING_RETRY_ALLOW_BELOW_B=1" in logged[0]
    reason = retry.degraded_reason(decision, {"score": 69, "hard_failures": ["semantic_sync"]},
                                   None)
    assert reason.startswith("opening45 below B: script shortfall")


def test_only_a_script_shortfall_stops():
    for outcome in ("passed", "below_b_after_retry", "not_needed", "skipped",
                    "passed_without_margin", "error"):
        ep._stop_if_opening_below_b({"outcome": outcome}, "/nonexistent", log=lambda m: None)


def test_the_degraded_reason_names_aligned_cuts_and_score():
    ctx = _duplicates()
    decision = retry.decide_opening_retry(ctx)
    plan = retry.compile_opening(ctx)
    readiness = retry.score_opening(ctx, plan)["report"]
    aligned, cuts = retry.cut_alignment(plan)
    assert retry.degraded_reason(decision, readiness, plan) == (
        f"opening45 below B after retry ({aligned}/{cuts} cuts aligned, score 69)")
    assert retry.degraded_reason({"outcome": "passed"}, readiness, plan) == ""
    assert retry.degraded_reason(decision, {"score": 86, "hard_failures": []}, plan) == ""


def test_the_pipeline_adds_the_degraded_reason_and_the_run_result():
    source = inspect.getsource(ep.run_explainer_pipeline)
    assert "_opening_retry.degraded_reason(" in source
    assert "reasons.append(_opening_reason)" in source
    assert '"opening_retry": _opening_retry_result(opening_retry_record)' in source


# ── where it runs ─────────────────────────────────────────────────────────────────────────────


def test_the_retry_runs_after_the_image_preflight_and_before_the_gate_render():
    source = inspect.getsource(ep.run_explainer_pipeline)
    preflight = source.index("Opening images missing before the 45-second gate render")
    hook = source.index("_opening_retry_at_gate(")
    render = source.index("_render_first_minute_preview(\n")
    freeze = source.index("freeze_opening_manifest(")
    assert preflight < hook < render < freeze


def test_the_stop_comes_after_the_controlled_pilot_return_and_before_later_purchase():
    source = inspect.getsource(ep.run_explainer_pipeline)
    pilot_return = source.index('"controlled_pilot": True')
    stop = source.index("_stop_if_opening_below_b(opening_retry_record")
    later = source.index("later = []")
    assert pilot_return < stop < later


# ── the pipeline wrapper: apply, persist, replay, skip ────────────────────────────────────────


@pytest.fixture
def gate(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENING_RETRY", raising=False)
    monkeypatch.setattr(ep, "_audio_dur", lambda _path: DURATION)
    calls = []

    def rebind(request, cost_sink=None):
        calls.append(request)
        if cost_sink is not None:
            cost_sink.append(0.0123)
        return copy.deepcopy(REBIND_BOTH), 0.0123

    monkeypatch.setattr(ep, "_opening_anchor_rebind", rebind)
    audio = []
    for k in range(3):
        path = tmp_path / f"scene_{k:02d}.mp3"
        path.write_bytes(f"audio {k}".encode())
        audio.append(str(path))

    def launch(*, word_times=None, controlled_pilot=False):
        states = [_clean_scene(1), _duplicate_scene(2), _duplicate_scene(3)]
        plan = {"continuity_pack": {}, "scenes": [
            {"scene_index": k, "opening": True, "state_capacity": 4, "states": scene_states}
            for k, scene_states in enumerate(states)]}
        results = [{"i": k, "scene": {"narration": NARRATION, "story_role": ROLES[k]},
                    "aud": audio[k], "aud_ok": True, "evidence_states": states[k],
                    "word_times": (word_times or _words)() if k == 1 else _words()}
                   for k in range(3)]
        logged, sink = [], []
        record = ep._opening_retry_at_gate(
            opening_results=results, script=SCRIPT, retention_validation=VALIDATION,
            evidence_plan=plan, motion_state_ids=frozenset(), opening_stop=3,
            output_dir=str(tmp_path), controlled_pilot=controlled_pilot,
            human_review_path=str(tmp_path / "human_review.json"),
            rendered_contract_path=str(tmp_path / "rendered_contract.json"),
            threshold_profile={}, evidence_plan_path=str(tmp_path / "evidence_asset_plan.json"),
            cost_sink=sink, log=logged.append)
        return record, states, plan, logged, sink

    return {"launch": launch, "calls": calls, "dir": tmp_path}


def test_the_chosen_edits_land_on_the_shared_plan_lists_and_are_persisted(gate):
    record, states, plan, logged, sink = gate["launch"]()
    assert record["outcome"] == "passed" and record["rung"] == "R2"
    assert plan["scenes"][1]["states"] is states[1]
    assert states[1][2]["anchor_phrase"] == "kilo lima"
    assert states[1][2]["anchor_phrase_before_opening_retry"] == "foxtrot golf"
    saved = json.loads((gate["dir"] / "opening_retry.json").read_text())
    assert saved["key"] == record["key"] and saved["edits"] == record["edits"]
    assert saved["rung"] == "R2" and saved["dropped_state_ids"] == []
    assert [(r["state_id"], r["old"], r["new"]) for r in saved["reanchored"]] == [
        ("state:s002:e03", "foxtrot golf", "kilo lima"),
        ("state:s003:e03", "foxtrot golf", "kilo lima")]
    assert saved["before"]["score"] == 69 and saved["after"]["score"] >= 80
    assert saved["cost_usd"] == pytest.approx(0.0123) and sink == [0.0123]
    on_disk = json.loads((gate["dir"] / "evidence_asset_plan.json").read_text())
    assert on_disk["scenes"][1]["states"][2]["anchor_phrase"] == "kilo lima"
    assert any(line.startswith("Opening retry: 69 D -> ") for line in logged)


def test_a_resume_replays_the_saved_decision_without_a_second_model_call(gate):
    first, *_ = gate["launch"]()
    assert len(gate["calls"]) == 1
    # A resume recompiles the evidence plan from the script: fresh lists, original anchors.
    record, states, _plan, logged, sink = gate["launch"]()
    assert len(gate["calls"]) == 1, "the replay must not call the model again"
    assert record["replayed"] is True and record["key"] == first["key"]
    assert states[1][2]["anchor_phrase"] == "kilo lima"
    assert sink == []
    assert any("replayed from opening_retry.json" in line for line in logged)


def test_different_word_timings_decide_again(gate):
    gate["launch"]()
    shifted = lambda: [[w, round(a + 0.01, 3), round(b + 0.01, 3)] for w, a, b in _words()]
    record, *_ = gate["launch"](word_times=shifted)
    assert not record.get("replayed")
    assert len(gate["calls"]) == 2


def test_skips_controlled_pilots_and_opening_retry_off(gate, monkeypatch):
    record, states, *_ = gate["launch"](controlled_pilot=True)
    assert record["outcome"] == "skipped" and "controlled pilot" in record["skip_reason"]
    assert states[1][2]["anchor_phrase"] == "foxtrot golf"
    monkeypatch.setenv("OPENING_RETRY", "0")
    record, states, *_ = gate["launch"]()
    assert record["outcome"] == "skipped" and record["skip_reason"] == "OPENING_RETRY=0"
    assert states[1][2]["anchor_phrase"] == "foxtrot golf"
    assert gate["calls"] == []
    assert not (gate["dir"] / "opening_retry.json").exists()


def test_skips_an_opening_a_bound_human_review_approved(gate):
    preview = gate["dir"] / "first_minute_preview.mp4"
    contract = gate["dir"] / "rendered_contract.json"
    preview.write_bytes(b"approved preview")
    contract.write_text("{}")
    (gate["dir"] / "human_review.json").write_text(json.dumps({
        "decision": "approve", "preview_sha256": ep.sha256_file(str(preview)),
        "rendered_report_sha256": ep.sha256_file(str(contract))}))
    record, states, *_ = gate["launch"]()
    assert record["outcome"] == "skipped" and "human review" in record["skip_reason"]
    assert states[1][2]["anchor_phrase"] == "foxtrot golf" and gate["calls"] == []
    # An approval of a DIFFERENT preview is not an approval of this opening.
    preview.write_bytes(b"another preview")
    record, *_ = gate["launch"]()
    assert record["outcome"] == "passed"


def test_retry_key_moves_with_audio_words_states_and_motion():
    states = [_duplicate_scene()]
    base = dict(audio_sha256=["a"], word_times=[_words()], states=states)
    key = retry.retry_key(**base)
    assert key == retry.retry_key(**copy.deepcopy(base))
    assert key != retry.retry_key(**dict(base, audio_sha256=["b"]))
    assert key != retry.retry_key(**dict(base, word_times=[_words(step=0.41)]))
    moved = copy.deepcopy(states)
    moved[0][2]["anchor_phrase"] = "kilo lima"
    assert key != retry.retry_key(**dict(base, states=moved))
    assert key != retry.retry_key(**base, motion_state_ids={"state:s002:e02"})
    assert key == retry.retry_key(**base, motion_state_ids={"state:s999:e01"})


def test_a_replay_that_no_longer_matches_the_plan_applies_nothing():
    states = [_duplicate_scene()]
    edits = [retry.drop_edit(states[0][1]),
             {"op": "reanchor", "state_id": "state:s002:e03", "old": "not this", "new": "x"}]
    problems = retry.apply_edits_in_place(states, edits)
    assert problems and len(states[0]) == 3
