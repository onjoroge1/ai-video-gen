"""The paid sampler must exercise the same script path before recommending a render."""
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "longform_script_check", Path(__file__).parents[1] / "scripts" / "longform_script_check.py")
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)


@pytest.fixture
def fake_pipeline(monkeypatch):
    events = []
    calls = []
    monkeypatch.setattr(harness.ep, "_runtime_is_enforced", lambda: False)
    monkeypatch.setattr(harness.ep, "_stable_standard_longform", lambda *a: True)
    monkeypatch.setattr(harness.ep, "_ordinary_research_mode", lambda *a: "required")
    monkeypatch.setattr(harness.ep, "_claim_ledger_hard", lambda: True)
    monkeypatch.setattr(harness.ep, "_illustrated_storyboard_hard", lambda: True)

    def research(*args, cost_sink, **kwargs):
        events.append("research")
        cost_sink.append(0.2)
        return {"claims": [{"claim_id": "c1"}]}

    def generate(*args, cost_sink, **kwargs):
        events.append("generate")
        calls.append(kwargs)
        cost_sink.append(0.05)  # judge cost; generation is recorded on the script
        return {"_story_engine": "backfiring_solution", "_script_cost_usd": 0.8,
                "scenes": [{"narration": "Before fact-check."}], "hook": "A plan backfired."}

    def factcheck(script, *args):
        events.append("factcheck")
        script["scenes"][0]["narration"] = "After fact-check."
        return script, ["corrected"], 0.1

    def bindings(script, *args):
        events.append("bindings")
        assert script["scenes"][0]["narration"] in {"After fact-check.", "After runtime fit."}

    def joins(script, *args):
        events.append("joins")
        return {"passed": True, "errors": []}

    def board(script, *args):
        events.append("board")
        return {"validation": {"passed": True, "errors": []}, "estimated_runtime_sec": 210,
                "chain": [{"role": "mechanism", "start_sec": 36}], "chapter_count": 4}

    monkeypatch.setattr(harness.ep, "generate_research_dossier", research)
    monkeypatch.setattr(harness.ep, "generate_graded_script", generate)
    monkeypatch.setattr(harness.ep, "factcheck_script", factcheck)
    monkeypatch.setattr(harness.ep, "rederive_narration_bindings", bindings)
    monkeypatch.setattr(harness.ep, "_review_story_structure", lambda *a: {"passed": False})
    monkeypatch.setattr(harness.ep, "_cached_graded_script", lambda *a: pytest.fail("must sample fresh"))
    monkeypatch.setattr(harness.ep, "_enforce_requested_runtime", lambda *a, **k: pytest.fail("no refit"))
    monkeypatch.setattr(harness.ep, "_ensure_hook_fits_budget", lambda script, *a: (script, 0))
    monkeypatch.setattr(harness, "validate_claim_joins", joins)
    monkeypatch.setattr(harness, "validate_research_dossier", lambda *a: {"passed": True})
    monkeypatch.setattr(harness, "validate_longform_story", lambda *a: {"passed": False})
    monkeypatch.setattr(harness, "plan_runtime", lambda *a: {"passed": False, "estimated_seconds": 210})
    monkeypatch.setattr(harness.illustrated, "build_storyboard", board)
    return events, calls


def test_illustrated_sampler_routes_and_checks_factchecked_final_story(fake_pipeline):
    args = harness.parse_args(["--visual-style", "illustrated_story", "--duration", "220", "Topic"])
    report = harness.run_sample(args, 1, log=lambda *a: None)
    events, calls = fake_pipeline
    assert calls[0]["causal_lane"] is True
    assert calls[0]["story_format"] == "standard_explainer"
    assert "ILLUSTRATED TREATMENT" in calls[0]["operator_direction"]
    assert events == ["research", "generate", "factcheck", "bindings", "joins", "bindings", "joins", "board"]
    assert report["passed"] and report["clean_script_checks"]
    assert report["checks"]["runtime"]["passed"] is False  # advisory, as in production
    assert report["checks"]["retention_review"]["passed"] is False  # not a new gate
    assert report["recorded_cost_usd"] == pytest.approx(1.15)
    assert report["cost_may_be_incomplete"] is True


def test_hard_runtime_uses_refit_and_refreshes_bindings(fake_pipeline, monkeypatch):
    events, _ = fake_pipeline
    monkeypatch.setattr(harness.ep, "_runtime_is_enforced", lambda: True)

    def fit(script, *args, cost_sink, **kwargs):
        events.append("refit")
        cost_sink.append(0.03)
        script["scenes"][0]["narration"] = "After runtime fit."
        script["_runtime_plan"] = {"passed": True}
        return script

    monkeypatch.setattr(harness.ep, "_enforce_requested_runtime", fit)
    args = harness.parse_args(["--visual-style", "illustrated_story", "Topic"])
    report = harness.run_sample(args, 1, log=lambda *a: None)
    assert report["passed"]
    assert events[events.index("refit") + 1:events.index("refit") + 3] == ["bindings", "joins"]
    assert report["recorded_cost_usd"] == pytest.approx(1.18)


def test_samples_keep_failed_observation_and_write_all_fresh_drafts(fake_pipeline, monkeypatch, tmp_path):
    calls = []

    def board(*args):
        calls.append(1)
        return {"validation": {"passed": len(calls) > 1,
                               "errors": ["ENGINE_ORDER: intervention after mechanism"] if len(calls) == 1 else []}}

    monkeypatch.setattr(harness.illustrated, "build_storyboard", board)
    output = tmp_path / "sampling.json"
    exit_code = harness.main(["--visual-style", "illustrated_story", "--samples", "2",
                              "--output", str(output), "Topic"])
    report = json.loads(output.read_text())
    assert exit_code == 1 and report["passed"] is False
    assert len(fake_pipeline[1]) == 2
    first, second = report["samples"]
    assert first["stage"] == "illustrated_storyboard" and not first["passed"]
    assert "ENGINE_ORDER" in first["error"]["message"]
    assert second["passed"]
    assert report["recorded_cost_usd"] == pytest.approx(2.3)
    assert "Blob publication" in report["excluded"]


def test_diagnostic_override_does_not_masquerade_as_clean_script(fake_pipeline, monkeypatch):
    monkeypatch.setattr(harness.ep, "_illustrated_storyboard_hard", lambda: False)
    monkeypatch.setattr(harness.illustrated, "build_storyboard", lambda *a: {
        "validation": {"passed": False, "errors": ["LATE_MECHANISM: too late"]}})
    args = harness.parse_args(["--visual-style", "illustrated_story", "Topic"])
    report = harness.run_sample(args, 1, log=lambda *a: None)
    assert report["passed"] is True  # would proceed under this environment
    assert report["clean_script_checks"] is False


@pytest.mark.parametrize("extra", [
    ["--visual-style", "illustrated_story", "--format", "evidence_led_mystery"],
    ["--video-format", "portrait"], ["--video-format", "social"],
    ["--samples", "0"], ["--duration", "0"],
])
def test_invalid_combinations_fail_before_any_provider_call(extra):
    with pytest.raises(SystemExit) as exc:
        harness.parse_args(extra + ["Topic"])
    assert exc.value.code == 2
