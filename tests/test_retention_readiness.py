from retention_readiness import (
    build_audio_cues,
    grade_observed_retention,
    score_retention_readiness,
    write_readiness_report,
)


def _fixture():
    roles = ["cold_consequence", "payoff", "promise", "prediction_gate", "payoff",
             "escalation", "rehook", "mechanism", "reversal", "final_payoff", "resonant_end"]
    scenes = [{"story_role": role} for role in roles]
    script = {
        "title": "What If Sea Level Dropped?", "hook": "The beach vanishes.",
        "scenes": scenes,
        "_story_contract": {"visual_promise": "A ship stranded on exposed ocean floor"},
    }
    validation = {"errors": [], "warnings": [], "checks": {
        "prediction_scenes": [4], "answer_scenes": [2, 5, 9, 10],
        "max_attention_gap_sec": 32, "max_exposition_block_sec": 8,
        "unresolved_loops": [],
    }}
    metrics = {"shot_count": 24, "avg_still_seconds": 2.8, "max_still_seconds": 3.4,
               "alternate_shot_count": 5, "i2v_shot_count": 2}
    return script, validation, metrics


def test_retention_readiness_is_a_grade_not_a_fake_retention_prediction():
    script, validation, metrics = _fixture()
    cues = build_audio_cues(script["scenes"], [6.0] * len(script["scenes"]))
    report = score_retention_readiness(
        script, validation, metrics, cues,
        preview={"decodable": True, "duration_sec": 60, "target_sec": 60},
    )

    assert report["score"] >= 80
    assert report["passed"] is True
    assert "not a prediction" in report["disclaimer"]
    assert sum(c["max"] for c in report["components"]) == 100


def test_weak_opening_and_slow_visuals_fail_the_gate():
    script, validation, metrics = _fixture()
    script["scenes"][0]["story_role"] = "mechanism"
    validation["errors"] = [{"code": "late_first_prediction"}, {"code": "late_first_payoff"},
                            {"code": "misplaced_peak"}, {"code": "missing_final_payoff"}]
    validation["warnings"] = [{"code": "subject_unclear_by_5s"}]
    validation["checks"].update({"prediction_scenes": [], "answer_scenes": [],
                                  "max_attention_gap_sec": 70, "max_exposition_block_sec": 25})
    metrics.update({"shot_count": 8, "avg_still_seconds": 5.5,
                    "max_still_seconds": 8, "alternate_shot_count": 0})

    report = score_retention_readiness(script, validation, metrics, [], preview={})

    assert report["score"] < 60
    assert report["grade"] == "F"
    assert report["passed"] is False


def test_audio_cues_are_story_driven_and_spaced():
    scenes = [{"story_role": r} for r in
              ["prediction_gate", "payoff", "reversal", "rehook", "final_payoff"]]
    cues = build_audio_cues(scenes, [3, 3, 3, 3, 3])

    sounded = [c for c in cues if c["type"] != "music_drop"]
    assert {c["type"] for c in cues} == {"prediction_tick", "impact", "music_drop"}
    assert all(b["time_sec"] - a["time_sec"] >= 6 for a, b in zip(sounded, sounded[1:]))


def test_report_writer_emits_downloadable_text_and_json(tmp_path):
    script, validation, metrics = _fixture()
    report = score_retention_readiness(
        script, validation, metrics, build_audio_cues(script["scenes"], [6] * 11),
        preview={"decodable": True, "duration_sec": 60, "target_sec": 60},
    )
    text_path, json_path = write_readiness_report(report, str(tmp_path))

    assert text_path.endswith("retention_readiness.txt")
    assert json_path.endswith("retention_readiness.json")
    assert "RETENTION READINESS SCORE" in (tmp_path / "retention_readiness.txt").read_text()


def test_old_sea_level_result_is_critical_but_low_confidence():
    observed = grade_observed_retention(7 * 60 + 14, 19.5, views=16)

    assert observed["grade"] == "F"
    assert observed["label"] == "Critical collapse"
    assert observed["confidence"] == "low"
