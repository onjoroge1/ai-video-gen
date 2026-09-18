"""An axis nobody measured must not be scored, in either direction.

`score_retention_readiness` reads six keys out of `validation["checks"]`. The compiled-factual
(illustrated/causal) validator returned before computing any of them, and the scorer read them with
`or` defaults — which are not neutral:

    max_attention_gap_sec     absent -> 999   -8   (a 999-second gap on a 75-second video)
    prediction_scenes         absent -> falsy -5
    answer_scenes             absent -> falsy -5
    max_exposition_block_sec  absent -> 0     +5   (a flawless reading, for nothing)
    unresolved_loops          absent -> falsy +5

Plus `scenes[0]["story_role"] == "cold_consequence"`, which every causal engine makes impossible:
they all open on `setup`, and `cold_consequence` is not one of that lane's roles at all.

Measured before this change: a PERFECT illustrated video scored 77/100 — a C — with Opening
contract and Narrative propulsion structurally capped. The number was not measuring the video.
"""
import longform_retention as lr
from retention_readiness import score_retention_readiness


PERFECT_SHOTS = {
    "avg_still_seconds": 2.75, "min_shot_seconds": 2.0, "max_still_seconds": 3.0,
    "over_ceiling_still_count": 0, "visual_state_ceiling_seconds": 3.5,
    "sub_min_shot_count": 0,
    "semantic_sync_ratio": 1.0, "meaningful_cut_ratio": 1.0, "motion_sync_ratio": 1.0,
    "same_source_hard_cut_count": 0, "broll_clause_count": 5,
}
PERFECT_AUDIO = [{"type": "sting", "time_sec": 5}, {"type": "whoosh", "time_sec": 20},
                 {"type": "sting", "time_sec": 40}, {"type": "whoosh", "time_sec": 60}]
PREVIEW = {"decodable": True, "duration_sec": 60.0, "target_sec": 60.0}
CAUSAL_ROLES = ("setup", "intervention", "mechanism", "escalation", "reversal")


def _script(roles=CAUSAL_ROLES):
    return {"title": "T", "hook": "H", "_story_contract": {"visual_promise": "p"},
            "scenes": [{"story_role": r, "causal_role": r} for r in roles]}


def _score(checks, script=None, shots=None, audio=None):
    return score_retention_readiness(
        script or _script(), {"checks": checks, "errors": [], "warnings": []},
        shots or PERFECT_SHOTS, audio if audio is not None else PERFECT_AUDIO, preview=PREVIEW)


def test_a_perfect_causal_video_can_reach_an_A():
    """The regression. Before this, the ceiling on this lane was 77 and an A was unreachable."""
    checks = {"contract": "compiled_factual", "retention_role_vocabulary": "causal",
              "prediction_scenes": [2], "answer_scenes": [5], "attention_scenes": [4, 5],
              "max_attention_gap_sec": 30.0, "max_exposition_block_sec": 12.0,
              "unresolved_loops": []}
    report = _score(checks)
    assert report["grade"] == "A", report["components"]
    assert report["score"] == 100
    assert report["hard_failures"] == []


def test_an_absent_metric_is_neither_penalty_nor_gift():
    """Absent earns nothing, costs nothing, and is named."""
    report = _score({"contract": "compiled_factual"})

    assert "max_attention_gap_sec" in report["unmeasured"]
    assert "max_exposition_block_sec" in report["unmeasured"]
    # No fabricated reading anywhere in the notes.
    notes = [n for c in report["components"] for n in c["notes"]]
    assert not any("999" in n for n in notes), notes
    assert any("not measured" in n for n in notes)
    # The denominator shrinks instead of the score.
    assert report["assessed_max"] < report["nominal_max"]
    assert report["score"] == round(100 * report["raw_score"] / report["assessed_max"])


def test_zero_is_a_measurement_and_999_is_not():
    """`or` could not tell a measured 0.0 from a missing key. Both readings were wrong."""
    measured_zero = _score({"contract": "compiled_factual", "retention_role_vocabulary": "causal",
                            "prediction_scenes": [1], "answer_scenes": [2], "unresolved_loops": [],
                            "max_attention_gap_sec": 0.0, "max_exposition_block_sec": 0.0})
    assert "max_attention_gap_sec" not in measured_zero["unmeasured"]
    # A measured zero-second gap is perfect, and must be scored as such.
    propulsion = next(c for c in measured_zero["components"] if c["name"].startswith("Narrative"))
    assert propulsion["score"] == propulsion["assessed_max"] == 25


def test_the_causal_opening_is_not_graded_against_mystery_grammar():
    """Every causal engine opens on `setup`; `cold_consequence` is not one of its roles."""
    causal = _score({"contract": "compiled_factual", "retention_role_vocabulary": "causal",
                     "prediction_scenes": [2], "answer_scenes": [5], "unresolved_loops": [],
                     "max_attention_gap_sec": 30.0, "max_exposition_block_sec": 12.0})
    assert "opening_is_cold_consequence" in causal["unmeasured"]
    opening = next(c for c in causal["components"] if c["name"] == "Opening contract")
    assert opening["score"] == opening["assessed_max"] == 20

    # The mystery lane is untouched: there the check is real and still bites.
    mystery = _score({"prediction_scenes": [1], "answer_scenes": [2], "unresolved_loops": [],
                      "max_attention_gap_sec": 30.0, "max_exposition_block_sec": 12.0})
    assert "opening_is_cold_consequence" not in mystery["unmeasured"]
    mystery_opening = next(c for c in mystery["components"] if c["name"] == "Opening contract")
    assert mystery_opening["assessed_max"] == 25
    assert "first beat is not a visible consequence" in mystery_opening["notes"]


def test_hard_failures_still_cap_the_grade():
    """Widening the denominator must not let a real defect through."""
    checks = {"contract": "compiled_factual", "retention_role_vocabulary": "causal",
              "prediction_scenes": [2], "answer_scenes": [5], "unresolved_loops": [],
              "max_attention_gap_sec": 30.0, "max_exposition_block_sec": 12.0}
    bad = dict(PERFECT_SHOTS, semantic_sync_ratio=0.27, same_source_hard_cut_count=4)
    report = _score(checks, shots=bad)
    assert set(report["hard_failures"]) == {"semantic_sync", "same_source_jump_cuts"}
    assert report["score"] <= 69 and report["grade"] == "D"
    assert report["passed"] is False


def test_the_compiled_factual_validator_now_emits_what_the_scorer_reads():
    """The wiring itself: every key the scorer looks for must exist on this lane."""
    scenes = [{"causal_role": r, "narration": "word " * 30} for r in CAUSAL_ROLES]
    starts, _durations, runtime = lr._timeline(scenes)
    checks = lr._causal_retention_checks(scenes, starts, runtime)

    for key in ("prediction_scenes", "answer_scenes", "max_attention_gap_sec",
                "max_exposition_block_sec", "unresolved_loops"):
        assert key in checks, f"{key} is what score_retention_readiness reads"
    assert checks["retention_role_vocabulary"] == "causal"
    # Roles map to the causal vocabulary, not the mystery one.
    assert checks["answer_scenes"] == [5], "reversal repays the question"
    assert checks["prediction_scenes"] == [2], "intervention is where a viewer predicts"
    assert 0 < checks["max_attention_gap_sec"] <= runtime, "a gap cannot exceed the video"


def test_the_gap_can_never_exceed_the_runtime():
    """The sentinel's real tell: a 75-second video reported a 999-second attention gap."""
    scenes = [{"causal_role": r, "narration": "word " * 30} for r in CAUSAL_ROLES]
    starts, _durations, runtime = lr._timeline(scenes)
    checks = lr._causal_retention_checks(scenes, starts, runtime)
    assert checks["max_attention_gap_sec"] <= runtime + 0.05

    # And with no attention beat at all it is the whole runtime, not a magic number.
    flat = [{"causal_role": "setup", "narration": "word " * 30} for _ in range(3)]
    fstarts, _fd, fruntime = lr._timeline(flat)
    assert lr._causal_retention_checks(flat, fstarts, fruntime
                                       )["max_attention_gap_sec"] <= fruntime + 0.05


def test_audio_cues_speak_the_causal_vocabulary():
    """The third instance of the lane-vocabulary bug, in the same file as the first two.

    `build_audio_cues` matched story_role against prediction_gate / payoff / reversal /
    final_payoff / false_relief / rehook. Those intersect causal_story.STEP_ROLES at exactly one
    word — `reversal` — so a causal story produced one cue of one type, and the palette check
    (which wants two) scored 2/4 on every illustrated video ever rendered. Measured on a real
    render: a single `impact` at 53.05s, note "audio cue palette lacks contrast".
    """
    from retention_readiness import build_audio_cues

    scenes = [{"story_role": r, "causal_role": r} for r in CAUSAL_ROLES]
    durations = [7.0, 7.2, 19.9, 18.7, 22.2]          # the real run's scene lengths
    cues = build_audio_cues(scenes, durations)

    assert len({c["type"] for c in cues}) >= 2, cues
    assert [c["story_role"] for c in cues] == ["intervention", "mechanism", "reversal"]

    # Only cues the mixer can actually render. A fourth name would be counted by the palette
    # check and then silently dropped by _make_audio_cue_track / music_mix_filter.
    assert {c["type"] for c in cues} <= {"prediction_tick", "impact", "music_drop"}

    # The scorer's own spacing rule still holds for non-music cues.
    times = [c["time_sec"] for c in cues if c["type"] != "music_drop"]
    assert all(b - a >= 6 for a, b in zip(times, times[1:])), times


def test_the_mystery_lane_keeps_its_own_cue_table():
    """Fixing one lane must not silently re-map the other."""
    from retention_readiness import build_audio_cues

    mystery = [{"story_role": r} for r in
               ("cold_consequence", "prediction_gate", "rules", "payoff", "rehook")]
    types = [c["type"] for c in build_audio_cues(mystery, [8, 8, 8, 8, 8])]
    assert types == ["prediction_tick", "impact", "music_drop"]


def test_a_repeatable_role_is_never_cued():
    """escalation and generalization repeat by contract; cueing them is cue-on-every-cut."""
    from retention_readiness import build_audio_cues

    roles = ["setup", "escalation", "escalation", "escalation", "generalization", "reversal"]
    cues = build_audio_cues([{"story_role": r, "causal_role": r} for r in roles], [12] * 6)
    assert [c["story_role"] for c in cues] == ["reversal"]


def _shot(**kw):
    base = dict(kind="still", duration=4.0, transition="hard_cut", source="asset:x")
    base.update(kw)
    return base


def test_clause_broll_is_counted_on_the_evidence_lane():
    """`broll_clause_count` was structurally zero wherever evidence_states are used.

    It counted only shots whose literal `source` is the string "alternate", which the two
    pre-evidence paths emit and the evidence lane never does. A real illustrated render scored 0
    with 17 planned states, 12 of them separately generated assets — not "no B-roll" but "this
    metric cannot see this lane".
    """
    from longform_shots import shot_plan_metrics

    plan = [[
        _shot(source="a1", asset_strategy="master"),
        _shot(source="a2", asset_strategy="distinct",
              verified_visible_information=True, semantic_aligned=True),
        _shot(source="a3", asset_strategy="distinct",
              verified_visible_information=True, semantic_aligned=True),
    ]]
    assert shot_plan_metrics(plan)["broll_clause_count"] == 2


def test_only_a_cut_that_earns_it_counts_as_clause_broll():
    """All three conjuncts are load-bearing; each exclusion here is a different way to not earn it."""
    from longform_shots import shot_plan_metrics

    plan = [[
        _shot(source="a1", asset_strategy="master"),
        _shot(source="a2", asset_strategy="distinct",           # earns it
              verified_visible_information=True, semantic_aligned=True),
        _shot(source="a3", asset_strategy="distinct",           # missed its clause
              verified_visible_information=True, semantic_aligned=False),
        _shot(source="a1", asset_strategy="detail_reframe",     # a crop, not new picture
              verified_visible_information=True, semantic_aligned=True),
        _shot(source="a4", asset_strategy="distinct",           # verifier rejected the asset
              verified_visible_information=False, semantic_aligned=True),
    ]]
    assert shot_plan_metrics(plan)["broll_clause_count"] == 1


def test_an_all_even_spaced_cut_scores_zero_broll():
    """The metric must degrade honestly rather than reward placement it did not achieve."""
    from longform_shots import shot_plan_metrics

    plan = [[_shot(source=f"a{i}", asset_strategy="distinct",
                   verified_visible_information=True, semantic_aligned=False)
             for i in range(5)]]
    assert shot_plan_metrics(plan)["broll_clause_count"] == 0


def test_the_legacy_alternate_source_still_counts():
    """Widening the predicate must not drop the pre-evidence lanes it was written for."""
    from longform_shots import shot_plan_metrics

    plan = [[_shot(source="alternate"), _shot(source="alternate")]]
    assert shot_plan_metrics(plan)["broll_clause_count"] == 2
    assert shot_plan_metrics(plan)["alternate_shot_count"] == 2
