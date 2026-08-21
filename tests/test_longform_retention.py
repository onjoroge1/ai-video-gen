from longform_retention import (
    build_story_contract,
    validate_longform_story,
    validation_rank,
    write_retention_report,
)
import copy


def _passing_script():
    n = 30
    roles = ["escalation"] * n
    roles[0] = "cold_consequence"
    roles[1] = "payoff"
    roles[2] = "promise"
    roles[3] = "prediction_gate"
    roles[4] = "payoff"
    roles[9] = "prediction_gate"
    roles[10] = "payoff"
    roles[14] = "rehook"
    roles[20] = "reversal"
    roles[24] = "false_relief"
    roles[26] = "final_escalation"
    roles[27] = "final_payoff"
    roles[29] = "resonant_end"

    beats = []
    scenes = []
    for i, role in enumerate(roles):
        opens = ""
        closes = ""
        question_opened = ""
        question_answered = ""
        if i == 0:
            opens, question_opened = "central", "What does a 500 metre sea-level drop really do?"
        elif i == 3:
            opens, question_opened = "first_failure", "Which system fails first?"
        elif i == 4:
            closes, question_answered = "first_failure", "Rainfall weakens before the apparent land gain helps."
        elif i == 9:
            opens, question_opened = "hidden_cost", "Where did all that water go?"
        elif i == 10:
            closes, question_answered = "hidden_cost", "The displaced water creates a larger global problem."
        elif i == 27:
            closes, question_answered = "central", "The new coastline destabilizes the whole water cycle."
        beat = {
            "n": i + 1,
            "pct": round(100 * i / (n - 1)),
            "beat": f"Distinct causal beat {i + 1}",
            "role": role,
            "question_opened": question_opened,
            "question_answered": question_answered,
            "new_complication": "The next consequence becomes harder to contain." if role in {"payoff", "reversal"} else "",
            "visible_consequence": f"Visible consequence {i + 1}",
            "opens_loop": opens,
            "closes_loop": closes,
        }
        beats.append(beat)
        scenes.append({
            "id": i + 1,
            "narration": "Sea level changes the coast and exposes another consequence right in front of Bolt.",
            "story_role": role,
            "question_opened": question_opened,
            "question_answered": question_answered,
            "new_complication": beat["new_complication"],
            "visible_consequence": beat["visible_consequence"],
            "opens_loop": opens,
            "closes_loop": closes,
        })

    plan = {
        "title": "What If Sea Level Dropped 500 Metres?",
        "hook": "The beach moves beyond the horizon.",
        "thumbnail_promise": "A ship stranded on a newly exposed ocean floor.",
        "throughline": "What does a 500 metre sea-level drop really do?",
        "false_model": "More land automatically helps humanity.",
        "replacement_model": "Moving ocean water destabilizes connected Earth systems.",
        "personal_stake": "Coasts, rainfall, food, and shipping all move with the water cycle.",
        "stages": ["THE COAST", "THE CLIMATE", "THE COST"],
    }
    contract = build_story_contract(plan["title"], plan, beats, scenes, 180)
    return {
        "title": plan["title"],
        "scenes": scenes,
        "_peak_scene": 21,
        "_story_contract": contract,
    }


def test_passing_story_contract_has_no_blocking_errors():
    report = validate_longform_story(_passing_script(), "What If Sea Level Dropped 500 Metres?")

    assert report["passed"] is True
    assert report["errors"] == []
    assert report["checks"]["prediction_scenes"] == [4, 10]
    assert report["checks"]["unresolved_loops"] == []
    assert report["checks"]["max_attention_gap_sec"] <= 55


def test_unresolved_narrative_debt_is_blocking():
    script = _passing_script()
    script["scenes"][27]["closes_loop"] = ""

    report = validate_longform_story(script)

    assert report["passed"] is False
    assert "unresolved_loops" in {item["code"] for item in report["errors"]}
    assert report["checks"]["unresolved_loops"] == ["central"]


def test_late_payoff_and_prediction_are_blocking():
    script = _passing_script()
    for scene in script["scenes"][:9]:
        if scene["story_role"] in {"payoff", "prediction_gate"}:
            scene["story_role"] = "escalation"
            scene["question_answered"] = ""
    script["scenes"][18]["story_role"] = "prediction_gate"

    report = validate_longform_story(script)
    codes = {item["code"] for item in report["errors"]}

    assert "late_first_prediction" in codes
    assert "late_first_payoff" in codes


def test_long_exposition_block_is_blocking():
    script = _passing_script()
    for scene in script["scenes"][5:10]:
        scene["story_role"] = "mechanism"

    report = validate_longform_story(script)

    assert "exposition_block" in {item["code"] for item in report["errors"]}


def test_missing_expanded_beat_is_blocking():
    script = _passing_script()
    script["_story_contract"]["beat_count"] += 1

    report = validate_longform_story(script)

    assert "beat_expansion_mismatch" in {item["code"] for item in report["errors"]}


def test_report_writer_emits_downloadable_text_and_json(tmp_path):
    script = _passing_script()
    report = validate_longform_story(script)

    path = write_retention_report(report, script["_story_contract"], str(tmp_path))

    assert path.endswith("retention_report.txt")
    assert (tmp_path / "retention_report.txt").exists()
    assert (tmp_path / "retention_report.json").exists()
    assert "LONG-FORM RETENTION CONTRACT — PASS" in (tmp_path / "retention_report.txt").read_text()


def test_validation_rank_prefers_fewer_blocking_errors():
    assert validation_rank({"errors": [], "warnings": [{}], "score": 97}) \
        < validation_rank({"errors": [{}], "warnings": [], "score": 88})


def test_pipeline_replans_a_failed_contract_before_subjective_grading(monkeypatch):
    import explainer_pipeline as pipeline

    bad = _passing_script()
    bad["scenes"][27]["closes_loop"] = ""
    bad["_script_cost_usd"] = 1.25
    good = _passing_script()
    good["_script_cost_usd"] = 1.5
    drafts = iter([bad, good])
    calls = []

    def fake_generate(*args, **kwargs):
        calls.append(kwargs.get("improve_note", ""))
        return copy.deepcopy(next(drafts))

    monkeypatch.setattr(pipeline, "generate_script", fake_generate)
    monkeypatch.setattr(pipeline, "grade_script", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline, "_ensure_hook_names_subject", lambda script, *args, **kwargs: (script, 0.0))
    monkeypatch.setattr(pipeline, "_LONGFORM_CONTRACT_RETRIES", 1)

    result = pipeline.generate_graded_script(
        "What If Sea Level Dropped 500 Metres?", 180, "scientific", "ocean", "landscape", ""
    )

    assert len(calls) == 2
    assert calls[0] == ""
    assert "DETERMINISTIC CONTRACT FAILURES" in calls[1]
    assert result["_retention_validation"]["passed"] is True
    assert result["_script_cost_usd"] == 2.75
