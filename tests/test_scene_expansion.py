"""Structural recovery, not a claim of real-model creative or historical accuracy."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

import causal_story
import durable_execution as durable
import explainer_pipeline as ep
import scene_expansion as expansion
import script_integrity as integrity
import script_stages
import story_compiler
import story_fact_model as facts
from test_durable_execution_phase6 import MemoryStore, MemoryBlob, runtime
from test_durable_anthropic_response import Provider, payload


def row(ident):
    return {"scene_id": ident, "narration": "A complete sentence for " + ident + ".",
            "visual_beats": [{"shot": "A specific view."}]}


def response(rows):
    return NS(content=[NS(type="tool_use", name=expansion.TOOL, input={"scenes": rows})],
              stop_reason="tool_use")


def test_reordered_partial_batch_retains_valid_scenes_and_requests_only_missing():
    assigned = [{**row(ident), "n": i} for i, ident in enumerate(("a", "b", "c"), 1)]
    calls = []
    def request(prompt, tool):
        calls.append((prompt, tool))
        return (response([row("c"), row("a")]) if len(calls) == 1
                else response([row("b")])), .01
    scenes, cost = expansion.expand(assigned,
        "NOW WRITE scenes 1-3 ONLY\n<ASSIGNED_SCENES>old rows</ASSIGNED_SCENES>", request)
    assert scenes == [row(i) for i in ("a", "b", "c")] and cost == pytest.approx(.02)
    assert "NOW WRITE scenes 2-2 ONLY" in calls[1][0]
    rewritten = calls[1][0].split("<ASSIGNED_SCENES>\n")[1].split("\n</ASSIGNED_SCENES>")[0]
    assert json.loads(rewritten) == assigned[1]
    assert calls[1][1]["input_schema"]["properties"]["scenes"]["items"]["properties"][
        "scene_id"]["enum"] == ["b"]
    retry = json.loads(calls[1][0].split("identity.\n")[1])
    assert retry["read_only_completed_scenes"] == [row("a"), row("c")]


def test_duplicates_and_unknown_ids_cannot_shift_assignment():
    rows = [row("a"), row("b"), row("a"), row("a"), row("unknown"), {"narration": "Unidentified."}]
    accepted, errors = expansion.reconcile({"scenes": rows}, ["a", "b"])
    assert accepted == {"b": row("b")} and len(errors) == 4


def test_exhausted_scene_budget_remains_exhausted_on_resume(tmp_path, monkeypatch):
    worker = NS(output_dir=str(tmp_path), checkpoint=Mock())
    monkeypatch.setattr(durable, "current", lambda: worker)
    request = Mock(return_value=(response([row("a")]), .01))
    for _ in range(2):
        with pytest.raises(ValueError, match="two-attempt budget for: b"):
            expansion.expand([row("a"), row("b")], "prompt", request)
    assert request.call_count == 2
    record = json.loads(next((tmp_path / "script_stages" / "scene-expansion").glob("*.json")).read_text())
    assert record["output"]["accepted"] == {"a": row("a")}
    assert record["output"]["attempts"] == {"a": 1, "b": 2}
    assert record["output"]["cost"] == pytest.approx(.02)


def test_partial_scenes_resume_on_new_worker_and_tool_output_is_billed_once(tmp_path, monkeypatch):
    class Yield(BaseException):
        pass
    store, blob = MemoryStore(cap=10), MemoryBlob(tmp_path / "blob")
    first = runtime(tmp_path, store, blob, "first")
    second = runtime(tmp_path, store, blob, "second")
    raw_a, raw_b = payload(), payload()
    for raw, rows in ((raw_a, [row("a")]), (raw_b, [row("b")])):
        raw["stop_reason"] = "tool_use"
        raw["content"] = [{"type": "tool_use", "id": "fixture", "name": expansion.TOOL,
                           "input": {"scenes": rows}}]
    provider = Provider(raw_a, raw_b)
    saved = first.checkpoint
    def checkpoint(label):
        saved(label)
        if label == "script-stage-scene-expansion":
            raise Yield()
    monkeypatch.setattr(first, "checkpoint", checkpoint)
    def run(worker):
        client = worker.wrap_anthropic(provider)
        def request(prompt, tool):
            reply = client.messages.create(model="fixture", max_tokens=1000,
                messages=[{"role": "user", "content": prompt}], tools=[tool],
                tool_choice={"type": "tool", "name": expansion.TOOL})
            return reply, .01
        with durable.activate(worker):
            return expansion.expand([row("a"), row("b")], "prompt", request)
    with pytest.raises(Yield):
        run(first)
    second.restore_checkpoint(store.job["checkpoint"])
    scenes, cost = run(second)
    assert scenes == [row("a"), row("b")] and cost == pytest.approx(.02)
    assert run(second) == (scenes, cost) and len(provider.calls) == 2
    assert store.job["spent_cost_usd"] > 0 and store.job["reserved_cost_usd"] == 0


@pytest.mark.parametrize("failure", [durable.BudgetExceeded, durable.LeaseLost, durable.StorageUnavailable])
def test_operational_stop_does_not_turn_into_a_writer_retry(failure):
    request = Mock(side_effect=failure("stop"))
    with pytest.raises(failure):
        expansion.expand([row("a")], "prompt", request)
    assert request.call_count == 1


def observed():
    return json.loads((Path(__file__).parent / "fixtures" / "2bc5ef3a_scene_repair.json").read_text())


def test_observed_job_keeps_real_improvement_and_preserves_the_remaining_failures():
    data = observed()
    assert not integrity.improves(data["before"], data["after"])
    result = integrity.comparison(data["before"], data["after"],
        original=data["original"], candidate=data["candidate"])
    assert result["accepted"] and result["baseline_error_count"] == 11
    assert result["candidate_error_count"] == 8
    assert [e["code"] for e in result["preexisting_findings"]] == ["TIME_SCOPE_CHANGED"]
    assert not data["after"]["passed"]  # progress cannot certify delivery
    changed = deepcopy(data["candidate"])
    changed["scenes"][9]["narration"] += " This is still true today."
    assert not integrity.improves(data["before"], data["after"],
        original=data["original"], candidate=changed)


@pytest.mark.parametrize("mutation", ["context", "identity", "evidence", "global", "quote"])
def test_new_integrity_failure_exemption_requires_identical_local_inputs(mutation):
    d = observed()
    issue = next(e for e in d["after"]["errors"] if e["code"] == "TIME_SCOPE_CHANGED")
    if mutation == "context": d["candidate"]["scenes"][9]["context_refs"] = ["event_01"]
    if mutation == "identity": d["candidate"]["scenes"][9]["scene_id"] = "different"
    if mutation == "evidence": d["candidate"]["_research_dossier"] = {"claims": []}
    if mutation == "global": issue["code"] = "CAUSAL_DIRECTION_REVERSED"
    if mutation == "quote": issue["quote"] = "not an actual quotation"
    assert not integrity.improves(d["before"], d["after"], original=d["original"], candidate=d["candidate"])


def test_question_hook_finalization_is_idempotent_and_migrates_the_observed_bad_stop():
    scenes = [{"narration": "Why did kiwi pay the price?. The plan targeted rabbits.",
               "chapter": 0}]
    causal_story.finalize_narration(scenes, "Why did kiwi pay the price?")
    first = deepcopy(scenes)
    causal_story.finalize_narration(scenes, "Why did kiwi pay the price?")
    assert scenes == first and "?." not in scenes[0]["narration"]
    assert scenes[0]["narration"].count("Why did kiwi pay the price?") == 1


def test_title_only_failure_reaches_bounded_editor(monkeypatch):
    original = observed()["original"]
    create = Mock(return_value=NS(usage=NS(input_tokens=100, output_tokens=100),
        content=[NS(text=json.dumps({"title": "How a Rabbit Plan Put Kiwi at Risk", "scenes": []}))]))
    monkeypatch.setattr(ep, "_claude", lambda: NS(messages=NS(create=create)))
    candidate, cost = ep.repair_claim_join_failures(original, {"claims": []},
        {"errors": [{"code": "TITLE_EXCEEDS_STORY", "scene": "title"}]})
    assert cost > 0 and create.call_count == 1
    assert candidate["title"] == "How a Rabbit Plan Put Kiwi at Risk"
    assert candidate["scenes"] == original["scenes"]
    request = json.loads(create.call_args.kwargs["messages"][0]["content"])
    assert request["title_repair"]["events"] and request["scenes"] == []


def test_observed_double_reversal_fails_before_narration_expansion():
    rows = [s for s in observed()["original"]["scenes"]
            if not s.get("continues") and s.get("event_function")]
    result = story_compiler.compile_roles(rows, "removed_keystone")
    assert not result["passed"]
    assert any(e["code"] == "DUPLICATE_STORY_ROLE" for e in result["issues"])
    assert story_compiler.compile_correction(result)


def context_story():
    return [{"beat_id": "purpose", "role": "intervention", "scope": "primary_story",
             "event": {"text": "Stoats were released to hunt rabbits.", "claim_refs": ["c1"]}},
            {"beat_id": "close", "role": "tool", "scope": "primary_story",
             "presentation_device": "tool", "context_refs": ["purpose"],
             "event": {"text": "", "claim_refs": []},
             "narration": "The plan sent hunters after rabbits. What else would they hunt?"}]


def test_callback_uses_named_accepted_context_and_not_the_entire_ledger():
    calls = []
    def judge(payload):
        calls.append(deepcopy(payload))
        return {"verdict": "entailed"}
    claims = {"c1": {"claim_id": "c1", "claim": "Stoats were released to hunt rabbits."},
              "c2": {"claim_id": "c2", "claim": "Unrelated claim about a trap in Guam."}}
    result = facts.validate_cascade(context_story(), claims, judge=judge)
    assert result["passed"]
    fidelity = next(c for c in calls if c["kind"] == "fidelity")
    assert "Stoats were released to hunt rabbits." in fidelity["event"]
    assert "Guam" not in json.dumps(fidelity)
    calls.clear()
    def reject_source(payload):
        calls.append(payload)
        return {"verdict": "unsupported", "unsupported_details": ["release not evidenced"]}
    assert not facts.validate_cascade(context_story(), claims, judge=reject_source)["passed"]
    assert all(c["kind"] != "fidelity" for c in calls)


@pytest.mark.parametrize("mutation", ["unknown", "self", "parallel", "empty"])
def test_context_cannot_cross_cases_or_borrow_unchecked_discourse(mutation):
    beats = context_story()
    if mutation == "unknown": beats[1]["context_refs"] = ["missing"]
    if mutation == "self": beats[1]["context_refs"] = ["close"]
    if mutation == "parallel": beats[0].update(scope="parallel_case", parallel_case_id="Guam")
    if mutation == "empty": beats[0]["event"] = {"text": "", "claim_refs": []}
    issues = facts.validate_structure(beats)
    assert any(e["code"] == "INVALID_CONTEXT_REF" for e in issues)


def test_malformed_edit_is_one_billable_attempt_without_json_repair(monkeypatch):
    create = Mock(return_value=NS(usage=NS(input_tokens=100, output_tokens=100),
                                 content=[NS(text="not JSON")]))
    monkeypatch.setattr(ep, "_claude", lambda: NS(messages=NS(create=create)))
    script = observed()["original"]
    candidate, cost = ep.repair_claim_join_failures(script, {"claims": []},
        {"errors": [{"code": "TITLE_EXCEEDS_STORY", "scene": "title"}]})
    assert cost > 0 and candidate is script and create.call_count == 1
