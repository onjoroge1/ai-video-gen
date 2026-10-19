"""Rescue by revision (operator rule, 2026-10-19): exact-text edits that fail loudly, a sentence diff
that flags a rewrite, a three-round log, and an install that sets the failure file aside so resume
cannot restore it. No paid calls.
"""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import rescue_script as rs  # noqa: E402


def _script():
    return {"title": "Why Is Florida Building Robot Rabbits to Catch Its Pythons?", "style_mode": "educational",
            "scenes": [
                {"beat_id": "event_01", "scene_id": "scene_001", "_role": "setup",
                 "narration": "Florida's newest weapon is a toy rabbit. Yet the snakes stay hidden.",
                 "event": {"text": "setup", "claim_refs": ["c01"]}},
                {"beat_id": "event_02", "scene_id": "scene_002", "_role": "mechanism",
                 "narration": "They released 95 rabbits and fitted them with trackers.",
                 "event": {"text": "rabbits", "claim_refs": ["c06"]}},
                {"beat_id": "event_02b", "scene_id": "scene_003", "_role": "mechanism",
                 "narration": "The answer came fast. Within 11 months, pythons caused 77 percent of the deaths.",
                 "event": {"text": "control sites", "claim_refs": ["c08"]}}],
            "_grade": {"overall": 68}}


def test_edits_are_exact_and_minimal():
    out, notes = rs.apply_edits(_script(), [
        {"scene": "event_02", "replace": [" and fitted them with trackers", ""]},
        {"scene": "event_02b", "move": "Within 11 months, pythons caused 77 percent of the deaths.", "to": "event_02"},
        {"scene": 0, "delete": "Yet the snakes stay hidden."},
        {"scene": "scene_003", "event_text": "new event", "event_claims": ["c06"]}])
    s = out["scenes"]
    assert s[1]["narration"] == "They released 95 rabbits. Within 11 months, pythons caused 77 percent of the deaths."
    assert s[2]["narration"] == "The answer came fast."
    assert s[0]["narration"] == "Florida's newest weapon is a toy rabbit."
    assert s[2]["event"] == {"text": "new event", "claim_refs": ["c06"]}
    assert "_grade" not in out, "a revised script must be graded again"
    assert len(notes) == 4 and _script()["scenes"][1]["narration"].endswith("trackers."), "the input is not mutated"


def test_an_edit_that_misses_fails_loudly():
    with pytest.raises(ValueError, match="not found"):
        rs.apply_edits(_script(), [{"scene": "event_02", "replace": ["fitted them with collars", "x"]}])
    with pytest.raises(KeyError):
        rs.apply_edits(_script(), [{"scene": "event_99", "delete": "x"}])
    with pytest.raises(ValueError, match="empty narration"):
        rs.apply_edits(_script(), [{"scene": "event_02", "delete": "They released 95 rabbits and fitted them with trackers."}])


def test_diff_counts_sentences_and_flags_a_rewrite():
    small, _ = rs.apply_edits(_script(), [{"scene": "event_02", "replace": [" and fitted them with trackers", ""]}])
    d = rs.narration_diff(_script(), small)
    assert d["scenes_changed"] == 1 and d["sentences_changed"] == 1 and d["sentences_before"] == 5
    assert "rewrite, not a revision" not in rs.diff_text(d)
    big, _ = rs.apply_edits(_script(), [{"scene": i, "narration": f"All new words {i}."} for i in range(3)])
    assert "rewrite, not a revision" in rs.diff_text(rs.narration_diff(_script(), big))


def test_rounds_are_logged_and_counted(tmp_path):
    assert rs.record_round(str(tmp_path), ["a"], "r1.json") == 1
    assert rs.record_round(str(tmp_path), ["b"], "r2.json") == 2
    assert len(json.load(open(tmp_path / rs.LOG_NAME))["rounds"]) == 2


def test_load_failed_takes_the_newest_failure_and_install_sets_it_aside(tmp_path, monkeypatch):
    old = tmp_path / "semantic_failure_illustrated-storyboard.json"
    old.write_text(json.dumps({"stage": "storyboard", "script": {"scenes": []}, "report": {}}))
    time.sleep(0.01)
    new = tmp_path / "semantic_failure_claim-ledger.json"
    new.write_text(json.dumps({"stage": "claim-ledger", "script": _script(), "report": {"errors": []}}))
    os.utime(old, (1, 1))
    failed = rs.load_failed(str(tmp_path))
    assert failed["stage"] == "claim-ledger" and failed["script"]["title"].startswith("Why")

    monkeypatch.setattr(rs, "stamp_opening", lambda script: script.setdefault("_opening_turn", {"digest": "x"}))
    path = rs.install(str(tmp_path), {"script": _script(), "style_mode": "educational"})
    state = json.load(open(path))
    assert state["script"]["_opening_turn"] == {"digest": "x"} and state["video_format"] == "landscape"
    assert not new.exists() and (tmp_path / "semantic_failure_claim-ledger.json.rescued.bak").exists()
    assert list(tmp_path.glob("_state.rescue_*.json")), "a dated copy is kept"


def test_launch_flags_and_resume_command_come_from_the_recorded_command(tmp_path):
    (tmp_path / "run_command.txt").write_text(
        "/opt/homebrew/bin/python3 scripts/run_illustrated_local.py --question 'Q?' --out jobs/x "
        "--engine unfolding_consequence --opening witness --no-synthesis --music\n")
    assert rs.launch_flags(str(tmp_path)) == {"SYNTHESIS_DEVICE": "off", "STORY_ENGINE": "unfolding_consequence",
                                              "OPENING_HOOK": "witness"}
    assert rs.resume_command(str(tmp_path)).endswith("--music --resume")


def test_report_marks_the_scenes_with_errors():
    failed = {"script": _script(), "stage": "claim-ledger", "source": "semantic_failure_claim-ledger.json",
              "report": {"errors": [{"code": "NARRATION_EXCEEDS_EVENT", "scene": "event_02b", "severity": "material",
                                     "message": "unsupported: Within 11 months", "supported_core": "rabbits died"}]}}
    text = rs.report_text(failed)
    assert "!02 event_02b" in text and " 00 event_01" in text and "supported core: rabbits died" in text
    assert "Revise, don't rewrite" in text


def test_a_judge_outage_is_not_a_pass(monkeypatch):
    import types
    fake_ist = types.SimpleNamespace(build_storyboard=lambda sc, q: {"validation": {"passed": True, "errors": [], "warnings": []}})
    fake_lr = types.SimpleNamespace(validate_research_dossier=lambda d: {"passed": True, "errors": []})
    fake_lrt = types.SimpleNamespace(validate_longform_story=lambda s, q: {"passed": False, "errors": [{"code": "SCENE_COUNT_MISMATCH"}]})
    monkeypatch.setitem(sys.modules, "illustrated_story", fake_ist)
    monkeypatch.setitem(sys.modules, "longform_research", fake_lr)
    monkeypatch.setitem(sys.modules, "longform_retention", fake_lrt)
    outage = {"passed": True, "errors": [{"code": "ENTAILMENT_UNAVAILABLE", "scene": "event_01", "severity": "material",
                                          "message": "provider_unavailable: KeyError"}]}
    res = rs.run_gates(_script(), "Q?", grades=2, judge_claims=lambda s: outage, grader=lambda s: {"overall": 80, "notes": ""})
    assert not res["claims"]["passed"] and "judge unavailable" in res["claims"]["errors"][0]
    assert res["retention"]["errors"] == ["SCENE_COUNT_MISMATCH"] and res["grade_mean"] == 80 and not res["passed"]
