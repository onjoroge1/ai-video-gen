"""Production orchestration regressions from the ad241e26 audit; no network."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
import durable_execution as durable
import explainer_pipeline as ep
import research_handoff as handoff
import script_readiness
import script_stages
import story_planner
import story_planning
import story_fact_model as facts
import storyboard_repair
from test_durable_execution_phase6 import MemoryStore, MemoryBlob, runtime
from test_durable_anthropic_response import Provider, payload
from test_story_planning_flow import factual_fixture, EvidenceFixture, expanded_fixture


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket, "connect", Mock(side_effect=AssertionError("network forbidden")))
    monkeypatch.setattr(socket.socket, "connect_ex", Mock(side_effect=AssertionError("network forbidden")))


def test_completed_research_restores_on_new_worker_without_refetch(tmp_path):
    store, blob = MemoryStore(), MemoryBlob(tmp_path / "blob")
    first = runtime(tmp_path, store, blob, "first")
    fetch = Mock(return_value={"claims": [{"claim_id": "c1", "source_reachable": False}]})
    @script_stages.cached("research-test")
    def research(question, cost_sink=None):
        return fetch(question)
    with durable.activate(first):
        expected = research("same topic")
    second = runtime(tmp_path, store, blob, "second")
    second.restore_checkpoint(store.job["checkpoint"])
    fetch.side_effect = AssertionError("must not refetch a completed dossier")
    with durable.activate(second):
        assert research("same topic") == expected
    assert fetch.call_count == 1


def test_corrupt_stage_blocks_without_repurchase(tmp_path, monkeypatch):
    worker = NS(output_dir=str(tmp_path), checkpoint=Mock())
    monkeypatch.setattr(durable, "current", lambda: worker)
    script_stages.save("stage", {"q": "x"}, {"ok": True})
    path, _, _ = script_stages.location("stage", {"q": "x"})
    record = json.loads(path.read_text()); record["output"]["ok"] = False
    path.write_text(json.dumps(record))
    with pytest.raises(script_stages.RecoveryError):
        script_stages.load("stage", {"q": "x"})


def test_candidates_are_distinct_and_each_slot_replays(tmp_path):
    store, blob = MemoryStore(cap=10), MemoryBlob(tmp_path / "blob")
    worker = runtime(tmp_path, store, blob, "worker")
    provider = Provider(*(payload(text=json.dumps({"candidate": i})) for i in range(3)))
    client = worker.wrap_anthropic(provider)
    def run():
        return [client.messages.create(model="fixture", max_tokens=12000,
            messages=[{"role": "user", "content": "plan" + story_planner.candidate_brief(i)}]
        ).content[0].text for i in range(3)]
    a, b = run(), run()
    assert a == b and len(set(a)) == 3 and len(provider.calls) == 3


def test_rejected_retry_cannot_replace_selected_studio_attempt(tmp_path, monkeypatch):
    import app
    monkeypatch.setattr(handoff, "_location", lambda: (tmp_path / handoff.FILENAME, Mock()))
    beats, claims = factual_fixture()
    a = story_planning.prepare(beats, "backfiring_solution", claims, judge=EvidenceFixture())
    handoff.select(a)
    changed = deepcopy(beats); changed[0]["event"]["text"] = "In 1902, " + changed[0]["event"]["text"]
    b = story_planning.prepare(changed, "backfiring_solution", claims,
        judge=EvidenceFixture(reject_relationship="material property"))
    assert not b["compiled"]["passed"]
    result = app._read_research_handoff(lambda kind: str(tmp_path / handoff.FILENAME)
                                       if kind == "research-handoff" else None)
    assert result["identity"] == a["handoff_identity"] and result["status"] == "ready"
    assert handoff.load(a["handoff_identity"]) and handoff.load(b["handoff_identity"])


def test_production_plan_and_expansion_resume_without_language_calls(tmp_path, monkeypatch):
    worker = NS(output_dir=str(tmp_path), checkpoint=Mock())
    monkeypatch.setattr(durable, "current", lambda: worker)
    monkeypatch.setattr(ep, "_dedupe_narration", lambda scenes, beats, throughline: (scenes, 0.0))
    script, dossier, judge, prompts, _ = expanded_fixture(monkeypatch)
    monkeypatch.setattr(ep, "_claude", Mock(side_effect=AssertionError("completed planning/expansion replayed")))
    again = ep._generate_script_chunked("Hanoi rat bounty", 90, "engaging", "", 8,
        causal_lane=True, pinned_engine="backfiring_solution", research_dossier=dossier)
    assert again["scenes"] == script["scenes"]
    assert len(list((tmp_path / "script_stages" / "accepted-plan").glob("*.json"))) == 1
    assert len(list((tmp_path / "script_stages" / "expansion-progress").glob("*.json"))) == 1


def test_event_citation_repair_changes_only_refs_and_rejudges(monkeypatch):
    beats, claims = factual_fixture()
    for c in claims.values():
        c.update(quote_verified=True, source_reachable=True)
    beats[0]["event"]["claim_refs"] = ["c2"]
    base = EvidenceFixture()
    def judge(p):
        if p.get("kind") == "evidence" and p.get("event") == claims["c1"]["claim"]:
            return {"verdict": "entailed" if [c["claim_id"] for c in p["claims"]] == ["c1"]
                    else "unsupported", "reason": "wrong source"}
        return base(p)
    calls = []
    def repair(rows, concerns, eligible, question, cost_sink):
        calls.append(concerns)
        rows[0]["event"] = {"text": "INVENTED", "claim_refs": ["c1"]}
        rows[0]["event_function"] = "INVENTED"
        return rows, 0
    result = story_planning.prepare(beats, "backfiring_solution", claims,
        judge=judge, event_repair=repair)
    assert calls and result["compiled"]["passed"]
    fixed = next(b for b in result["beats"] if b["beat_id"] == "fact_1")
    assert fixed["event"]["text"] == beats[0]["event"]["text"]
    assert fixed["event"]["claim_refs"] == ["c1"]


@pytest.mark.parametrize("failed", ["claims", "structure", "storyboard", "editorial", "stale_grade"])
def test_readiness_cannot_hide_failed_gate_or_stale_grade(failed):
    script = {"scenes": [{"scene_id": "s1", "narration": "A complete statement."}]}
    review = {"passed": True, "narration_sha256": storyboard_repair.story_identity(script)}
    args = dict(claims={"passed": True}, structure={"passed": True},
        storyboard={"passed": True}, runtime={"passed": True}, duplicates=[], review=review)
    if failed == "stale_grade": script["scenes"][0]["narration"] = "Different words."
    elif failed == "editorial": review["passed"] = False
    else: args[failed]["passed"] = False
    assert not script_readiness.evaluate(script, {}, **args)["passed"]


def test_final_baseline_is_checked_even_when_editorial_grade_is_high(tmp_path, monkeypatch):
    import retention_polish
    from test_retention_polish import setup, grade
    script, create, _, _ = setup(monkeypatch, [grade(80)], structure=False)
    _, report = retention_polish.run(script, "q", {}, tmp_path, [], lambda _: None)
    assert not report["passed"] and not create.called


def test_unavailable_judge_is_named_even_when_roles_are_covered():
    beats, claims = factual_fixture()
    result = story_planning.prepare(beats, "backfiring_solution", claims, judge=EvidenceFixture())
    compiled = result["compiled"]
    compiled["passed"] = False
    compiled["cascade"]["unavailable"] = [{"beat_id": "optional", "reason": "outage"}]
    summary = facts.spine_summary(result["beats"], compiled)
    assert summary.startswith("STORY_SPINE_UNSUPPORTED")
    assert "UNSCORED_JUDGE_UNAVAILABLE" in summary and "outage" in summary


def test_planning_evidence_quarantines_claim_quote_mismatch(monkeypatch):
    import planning_evidence
    claims = [{"claim_id": "c1", "claim": "Stoats controlled rabbits.",
               "support_quote": "Stoats were intended to control rabbits."},
              {"claim_id": "c2", "claim": "Stoats were introduced.",
               "support_quote": "Stoats were introduced."}]
    response = NS(content=[NS(type="tool_use", name="submit_claim_support", input={"claims": [
        {"claim_id": "c1", "verdict": "unsupported", "reason": "intention only"},
        {"claim_id": "c2", "verdict": "supported", "reason": "exact"}]})],
        usage=NS(input_tokens=100, output_tokens=100))
    monkeypatch.setattr(ep, "_claude", lambda: NS(messages=NS(create=Mock(return_value=response))))
    result = planning_evidence.prepare({"claims": claims})
    assert [c["claim_id"] for c in result["claims"]] == ["c2"]
    assert result["planning_excluded_claims"][0]["claim_id"] == "c1"
    assert len(claims) == 2


@pytest.mark.parametrize("boundary", ["script-stage-accepted-plan", "script-stage-expansion-progress"])
def test_yield_after_checkpoint_resumes_on_another_worker(tmp_path, monkeypatch, boundary):
    class Yield(BaseException):
        pass
    store, blob = MemoryStore(cap=10), MemoryBlob(tmp_path / "blob")
    first = runtime(tmp_path, store, blob, "first")
    original_checkpoint = first.checkpoint
    def checkpoint(label):
        result = original_checkpoint(label)
        if label == boundary:
            raise Yield()
        return result
    monkeypatch.setattr(first, "checkpoint", checkpoint)
    monkeypatch.setattr(ep, "_dedupe_narration", lambda scenes, beats, throughline: (scenes, 0))
    with durable.activate(first), pytest.raises(Yield):
        expanded_fixture(monkeypatch)
    second = runtime(tmp_path, store, blob, "second")
    second.restore_checkpoint(store.job["checkpoint"])
    with durable.activate(second):
        script, _, judge, prompts, _ = expanded_fixture(monkeypatch)
    assert script["scenes"] and not judge.calls
    assert not any("Plan the sourced factual events" in p for p in prompts)
    if boundary == "script-stage-expansion-progress":
        assert not prompts


def test_cadence_reports_rhythm_without_turning_preferences_into_gates():
    import script_cadence
    from script_repair import broken_repair
    varied = {"scenes": [{"narration": "Friday night. You stand beside the counter. "
        "The familiar meal arrives, but its ordinary appearance conceals a detail you have never thought to question."}]}
    report = script_cadence.measure(varied)
    assert report["sentence_count"] == 3 and report["min_words"] == 2
    assert report["long_sentences"] == 1 and report["status"] == "advisory"
    assert "passed" not in report
    assert not broken_repair("Friday night.")
    assert broken_repair("The animal was introduced because.")


def test_unavailable_factcheck_is_reported_and_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(durable, "current", lambda: NS(output_dir=str(tmp_path), checkpoint=Mock()))
    monkeypatch.setattr(ep, "_claude", Mock(side_effect=RuntimeError("provider unavailable")))
    script, notes, _ = ep.factcheck_script({"scenes": [{"narration": "A statement."}]}, "q", {})
    assert notes[0].startswith("Fact-check unavailable")
    assert not (tmp_path / "script_stages" / "factcheck").exists()
    review = {"passed": True, "narration_sha256": storyboard_repair.story_identity(script)}
    report = script_readiness.evaluate(script, {}, claims={"passed": True},
        structure={"passed": True}, storyboard={"passed": True}, runtime={"passed": True},
        duplicates=[], review=review, factcheck_required=True)
    assert report["errors"] == ["factcheck"]


def test_promptfoo_uses_production_adapter_only_when_explicitly_enabled(monkeypatch):
    import importlib.util
    path = Path(__file__).resolve().parents[1] / "evals/promptfoo/production_provider.py"
    spec = importlib.util.spec_from_file_location("production_eval", path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    create = Mock(return_value=NS(content=[NS(text='{"ok":true}')],
                                  usage=NS(input_tokens=10, output_tokens=5)))
    monkeypatch.setattr(ep, "_claude", lambda: NS(messages=NS(create=create)))
    prompt = json.dumps([{"role": "system", "content": "system"}, {"role": "user", "content": "q"}])
    monkeypatch.delenv("REELFORGE_PAID_EVAL", raising=False)
    assert "error" in module.call_api(prompt, {}, {}) and not create.called
    monkeypatch.setenv("REELFORGE_PAID_EVAL", "1")
    assert module.call_api(prompt, {}, {})["output"] == '{"ok":true}'
    assert create.call_args.kwargs["model"] == ep.ANTHROPIC_MODEL
    assert create.call_args.kwargs["system"] == "system"


def test_readiness_pass_preserves_advisory_runtime_warning():
    script = {"scenes": [{"scene_id": "s1", "narration": "A complete statement."}],
              "_factcheck_review": {"status": "complete"}}
    review = {"passed": True, "narration_sha256": storyboard_repair.story_identity(script)}
    args = dict(claims={"passed": True}, structure={"passed": True},
                storyboard={"passed": True}, runtime={"passed": False}, duplicates=[],
                review=review, factcheck_required=True)
    report = script_readiness.evaluate(script, {}, **args)
    assert report["passed"] and report["warnings"]
    assert not script_readiness.evaluate(script, {}, **args, runtime_hard=True)["passed"]


def test_studio_script_only_checkpoints_ready_words_before_any_media(tmp_path, monkeypatch):
    from test_storyboard_repair import failed_script, write_failure, writer, response_for
    script = failed_script()
    script["_factcheck_review"] = {"status": "complete"}
    write_failure(tmp_path, script)
    writer(monkeypatch, response_for(script))
    monkeypatch.setattr(ep, "grade_script", lambda *a, **k: {"overall": 80,
        "scores": dict.fromkeys(("hook", "story", "ending", "repetition", "cadence"), 80)})
    monkeypatch.setattr(ep, "validate_longform_story", lambda *a, **k:
                        {"passed": True, "score": 100, "errors": [], "warnings": []})
    monkeypatch.setattr(ep, "duplicate_narration", lambda *a, **k: [])
    monkeypatch.setattr(ep, "compile_evidence_plan", lambda *a, **k:
                        {"validation": {"passed": True}, "continuity_pack": {}, "scenes": []})
    monkeypatch.setattr(ep, "evidence_asset_counts", lambda *a: dict.fromkeys(
        ("planned_state_count", "distinct_source_count", "reframe_count", "exact_reuse_count"), 0))
    media = Mock(side_effect=AssertionError("Script Only reached media work"))
    monkeypatch.setattr(ep, "_preflight_verifier_credit", media)
    monkeypatch.setattr(ep, "compile_motion_plan", media)
    monkeypatch.setenv("RUNTIME_HARD", "0")
    with pytest.raises(ep.ScriptApprovalRequired):
        ep.run_explainer_pipeline("Why did this happen?", str(tmp_path), duration_sec=300,
            visual_style="illustrated_story", resume=True, max_cost_usd=10, stop_after_script=True)
    saved = json.loads((tmp_path / "_state.json").read_text())["script"]
    assert saved["_script_readiness"]["passed"]
    assert saved["_script_readiness"]["narration_sha256"] == storyboard_repair.story_identity(saved)
    assert (tmp_path / "script_for_approval.md").exists() and not media.called
