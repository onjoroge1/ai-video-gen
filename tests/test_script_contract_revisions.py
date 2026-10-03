"""Acceptance binds current prose; revisions never regenerate or mutate a parent job."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

import claim_entailment as ce
import durable_execution as durable
import explainer_pipeline as ep
import script_contracts
import script_finalizer
import script_integrity
import script_readiness
import script_revisions
import script_stages
import storyboard_repair


def draft():
    return {"title": "A plan backfires", "hook": "Why did the plan backfire?",
            "_factcheck_review": {"status": "incomplete"},
            "_research_dossier": {"claims": [{"claim_id": "c1", "claim": "The plan failed."}]},
            "scenes": [{"scene_id": "s1", "narration": "The plan failed.",
                        "event": {"text": "The plan failed.", "claim_refs": ["c1"]}}]}


def accept(monkeypatch, script):
    monkeypatch.setattr(ep, "_validate_claims", lambda *a, **k: {"passed": True, "errors": []})
    monkeypatch.setattr(ep, "validate_longform_story", lambda *a: {"passed": True})
    monkeypatch.setattr(ep, "duplicate_narration", lambda *a: [])
    import illustrated_story
    monkeypatch.setattr(illustrated_story, "build_storyboard", lambda *a: {"validation": {"passed": True}})
    script["_final_retention_review"] = {"passed": True,
        "narration_sha256": storyboard_repair.story_identity(script)}
    return script_finalizer.evaluate(script, script["_research_dossier"], "q", 180,
                                     factcheck_required=True)


def source(script, status="error"):
    row = {"id": "parent", "kind": "explainer", "status": status,
           "checkpoint": {"sha256": "a" * 64},
           "request": {"question": "q", "duration_sec": 180, "fact_check": True,
                       "visual_style": "illustrated_story", "video_format": "landscape"}}
    saved = {"script": script, "checkpoint_sha256": "a" * 64}
    args = {"checkpoint_sha256": "a" * 64, "content_sha256": script_readiness.content_hash(script),
            "cost_ceiling_usd": 3.0}
    return row, saved, args


def test_current_review_supersedes_incomplete_history_but_never_stale_words(monkeypatch):
    script = draft()
    assert accept(monkeypatch, script)["passed"]
    assert script["_factcheck_review"]["status"] == "incomplete"
    script_finalizer.verify_approved(script, script["_research_dossier"], "q", 180, factcheck_required=True)
    script["scenes"][0]["narration"] = "The plan worked."
    with pytest.raises(ValueError, match="APPROVED_SCRIPT_CHANGED"):
        script_finalizer.verify_approved(script, script["_research_dossier"], "q", 180, factcheck_required=True)


@pytest.mark.parametrize("mutation", ["evidence", "model", "runtime", "question", "duration", "factcheck"])
def test_approval_is_invalidated_by_its_other_dependencies(monkeypatch, mutation):
    script = draft(); accept(monkeypatch, script)
    question, duration, factcheck = "q", 180, True
    if mutation == "evidence": script["_research_dossier"]["claims"][0]["claim"] = "Another fact."
    if mutation == "model": monkeypatch.setenv("SCRIPT_PROVIDER", "openai")
    if mutation == "runtime": monkeypatch.setenv("RUNTIME_HARD", "1")
    if mutation == "question": question = "changed"
    if mutation == "duration": duration = 190
    if mutation == "factcheck": factcheck = False
    with pytest.raises(ValueError, match="APPROVED_SCRIPT_CHANGED"):
        script_finalizer.verify_approved(script, script["_research_dossier"], question, duration,
                                         factcheck_required=factcheck)


def test_child_identity_and_replay_preserve_parent(monkeypatch):
    row, saved, args = source(draft())
    original = deepcopy((row, saved))
    first_id, request = script_revisions.prepare(row, saved, mode="evaluate", **args)
    assert (first_id, request) == script_revisions.prepare(row, saved, mode="evaluate", **args)
    other_id, _ = script_revisions.prepare(row, saved, mode="evaluate", **{**args, "cost_ceiling_usd": 2})
    assert other_id != first_id
    out = script_revisions.restore(request["script_revision"], stop_after_script=True)
    out["scenes"][0]["narration"] = "An edit."
    assert (row, saved) == original and request["script_revision"]["script"] == original[1]["script"]
    request["script_revision"]["script"]["scenes"][0]["narration"] = "Tampered."
    with pytest.raises(ValueError, match="content changed"):
        script_revisions.restore(request["script_revision"], stop_after_script=True)


@pytest.mark.parametrize("change", ["active", "controlled", "directed", "agent", "checkpoint", "text", "failed_render"])
def test_revision_refuses_wrong_boundary(change):
    row, saved, args = source(draft())
    mode = "evaluate"
    if change == "active": row["status"] = "rendering"
    if change == "controlled": row["request"]["controlled_pilot"] = True
    if change == "directed": row["request"]["directed_spec"] = {"any": "value"}
    if change == "agent": row["request"]["illustrated_authorization"] = {"approved": True}
    if change == "checkpoint": args["checkpoint_sha256"] = "b" * 64
    if change == "text": args["content_sha256"] = "b" * 64
    if change == "failed_render": mode = "render"
    with pytest.raises(ValueError):
        script_revisions.prepare(row, saved, mode=mode, **args)


@pytest.mark.parametrize("failure", [durable.BudgetExceeded, durable.LeaseLost, durable.StorageUnavailable])
def test_operational_stops_escape_semantic_fallbacks(monkeypatch, failure):
    judge = Mock(side_effect=failure("stop"))
    with pytest.raises(failure):
        ce.narration_fidelity("A fact", "A line", judge=judge)
    assert judge.call_count == 1
    with pytest.raises(failure):
        script_integrity.review(draft(), draft()["_research_dossier"], judge=judge)
    monkeypatch.setattr(ep, "_claude", judge)
    with pytest.raises(failure):
        ep.factcheck_script({"scenes": [{"narration": "A line."}]}, "q")


def test_cache_depends_on_provenance_dates_metrics_and_real_model(monkeypatch):
    claim = {"claim": "Half survived.", "support_quote": "Half survived."}
    before = ce.cache_key([claim], "Half survived.")
    for field in ("support_provenance", "as_of", "source_published_at", "metric"):
        assert ce.cache_key([{**claim, field: "different"}], "Half survived.") != before
    monkeypatch.setenv("SCRIPT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_SCRIPT_MODEL", "different-model")
    assert ce.cache_key([claim], "Half survived.") != before


def test_expansion_cannot_restore_rejected_planner_success():
    from story_fact_model import expansion_input
    row = {"beat": "It worked.", "human_belief": "Rabbits were controlled.",
           "actual_outcome": "Rabbit numbers fell.", "changes_state": {"to": "success"},
           "event": {"text": "Stoats were introduced in the hope of controlling rabbits.", "claim_refs": ["c1"]}}
    out = expansion_input(row)
    assert out["beat"] == row["event"]["text"]
    assert not {"human_belief", "actual_outcome", "changes_state"} & out.keys()
    assert row["beat"] == "It worked."


def test_grammar_and_time_findings_are_addressable_and_block_edits():
    script = draft(); script["scenes"][0]["narration"] = "The chicks is safe today."
    report = script_integrity.review(script, script["_research_dossier"], judge=lambda _: {"issues": [
        {"scene": 1, "code": "BROKEN_GRAMMAR", "quote": "chicks is", "reason": "agreement", "repair": "Use are."},
        {"scene": 1, "code": "TIME_SCOPE_CHANGED", "quote": "today", "reason": "undated evidence", "repair": "Remove today."}]})
    assert not report["passed"] and not report["retryable"]
    assert not script_integrity.improves({"errors": []}, report)


@pytest.mark.parametrize("stop", [True, False])
def test_script_only_and_render_reach_the_same_final_gate(tmp_path, monkeypatch, stop):
    from test_script_flow_recovery import test_studio_script_only_checkpoints_ready_words_before_any_media
    # Build a saved checkpoint with the existing pipeline integration fixture.
    test_studio_script_only_checkpoints_ready_words_before_any_media(tmp_path, monkeypatch)
    state = json.loads((tmp_path / "_state.json").read_text())
    state["script"].pop("_script_readiness")
    # Empty evidence-plan fixture is compiled below; do not present it as a legacy saved plan.
    state["script"].pop("_evidence_plan", None)
    (tmp_path / "_state.json").write_text(json.dumps(state))
    final = Mock(return_value={"passed": False, "errors": ["claims"]})
    monkeypatch.setattr(script_finalizer, "evaluate", final)
    with pytest.raises(ValueError, match="SCRIPT_NOT_READY: claims"):
        ep.run_explainer_pipeline("Why did this happen?", str(tmp_path), duration_sec=300,
            visual_style="illustrated_story", resume=True, max_cost_usd=10, stop_after_script=stop)
    assert final.call_count == 1


def test_approved_render_reuses_frozen_words_without_any_writer(tmp_path, monkeypatch):
    from test_script_flow_recovery import test_studio_script_only_checkpoints_ready_words_before_any_media
    test_studio_script_only_checkpoints_ready_words_before_any_media(tmp_path, monkeypatch)
    script = json.loads((tmp_path / "_state.json").read_text())["script"]
    row, saved, args = source(script, "awaiting_script_approval")
    row["request"].update(question="Why did this happen?", duration_sec=300)
    _, request = script_revisions.prepare(row, saved, mode="render", **args)
    writer = Mock(side_effect=AssertionError("Approved render attempted text generation"))
    for name in ("generate_research_dossier", "generate_graded_script", "factcheck_script", "grade_script",
                 "_ensure_hook_fits_budget", "_ensure_hinge_fits_budget", "_enforce_requested_runtime"):
        monkeypatch.setattr(ep, name, writer)
    import retention_polish
    monkeypatch.setattr(retention_polish, "run", writer)
    class AtMedia(Exception): pass
    monkeypatch.setattr(ep, "compile_motion_plan", Mock(side_effect=AtMedia))
    child = tmp_path / "child"
    with pytest.raises(AtMedia):
        ep.run_explainer_pipeline(row["request"]["question"], str(child), duration_sec=300,
            visual_style="illustrated_story", max_cost_usd=10, script_revision=request["script_revision"])
    assert not writer.called
    result = json.loads((child / "_state.json").read_text())["script"]
    assert script_readiness.content_hash(result) == script_readiness.content_hash(script)


def test_saved_draft_evaluation_skips_research_planner_and_media(tmp_path, monkeypatch):
    from test_script_flow_recovery import test_studio_script_only_checkpoints_ready_words_before_any_media
    test_studio_script_only_checkpoints_ready_words_before_any_media(tmp_path, monkeypatch)
    script = json.loads((tmp_path / '_state.json').read_text())['script']
    row, saved, args = source(script)
    row['request'].update(question='Why did this happen?', duration_sec=300)
    _, request = script_revisions.prepare(row, saved, mode='evaluate', **args)
    forbidden = Mock(side_effect=AssertionError('Evaluation repeated an upstream or media stage'))
    for name in ('generate_research_dossier', 'generate_graded_script', '_cached_graded_script',
                 'generate_tts', 'compile_motion_plan'):
        monkeypatch.setattr(ep, name, forbidden)
    monkeypatch.setattr(ep, 'factcheck_script', lambda script, *a: (script, [], 0))
    child = tmp_path / 'evaluation'
    with pytest.raises(ep.ScriptApprovalRequired):
        ep.run_explainer_pipeline(row['request']['question'], str(child), duration_sec=300,
            visual_style='illustrated_story', stop_after_script=True, script_revision=request['script_revision'])
    assert not forbidden.called
    result = json.loads((child / 'script_revision.json').read_text())
    assert result['parent_job_id'] == 'parent' and result['result']['passed']
    assert row['status'] == 'error'


def test_revision_route_is_private_capped_idempotent_and_rejects_public_seeds(monkeypatch):
    import asyncio
    import httpx
    from fastapi import FastAPI
    import app as web
    import private_access
    import studio_jobs
    row, saved, args = source(draft())
    async def inline(fn, *args, **kwargs): return fn(*args, **kwargs)
    monkeypatch.setattr(web.asyncio, 'to_thread', inline)
    monkeypatch.setenv('APP_USERNAME', 'owner')
    monkeypatch.setenv('APP_PASSWORD', 'test-password')
    monkeypatch.setenv('APP_SESSION_SECRET', 'test-session-secret')
    monkeypatch.setenv('DURABLE_JOB_MAX_COST_USD', '3')
    store = Mock(get_job=Mock(return_value=row))
    monkeypatch.setattr(web, '_durable_execution_required', lambda: True)
    monkeypatch.setattr(web, '_durable_components', lambda: (store, Mock()))
    monkeypatch.setattr(studio_jobs, 'artifacts', lambda *a: saved)
    enqueued = []
    async def enqueue(request, tasks, **kwargs):
        enqueued.append((request.model_dump(), kwargs))
        return {'job_id': kwargs['job_id'], 'dispatch_url': '/dispatch'}
    monkeypatch.setattr(web, '_enqueue_explainer_request', enqueue)
    application = FastAPI()
    application.add_middleware(private_access.PrivateAccessMiddleware)
    application.add_api_route('/api/studio/jobs/{job_id}/script-revisions', web.studio_script_revision, methods=['POST'])
    application.add_api_route('/api/explainer/generate', web.explainer_generate, methods=['POST'])
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url='http://test') as client:
            url = '/api/studio/jobs/parent/script-revisions'
            body = {**args, 'mode': 'evaluate'}
            assert (await client.post(url, json=body)).status_code == 401
            client.cookies.set(private_access.COOKIE_NAME, private_access.create_session('owner'))
            assert (await client.post(url, json={**body, 'cost_ceiling_usd': 4})).status_code == 400
            first = await client.post(url, json=body)
            second = await client.post(url, json=body)
            assert first.status_code == 200 and first.json() == second.json()
            assert enqueued[0] == enqueued[1] and enqueued[0][1]['max_cost_usd'] == 3
            assert (await client.post(url, json={**body, 'mode': 'render'})).status_code == 409
            assert (await client.post('/api/explainer/generate', json={'question': 'q', 'script_revision': {}})).status_code == 403
            assert len(enqueued) == 2 and row['status'] == 'error'
    asyncio.run(run())


def test_function_review_outage_stays_operational_in_the_compiled_spine(monkeypatch):
    import story_fact_model as sfm
    monkeypatch.setattr(sfm, 'validate_cascade', lambda *a, **k: {
        'passed': False, 'structural': [], 'evidence': [], 'fidelity': [], 'unavailable': [],
        'judgments': [], 'assertion_judgments': []})
    monkeypatch.setattr(sfm, 'narrow_required_roles', lambda beats, *a, **k: (beats, [], [{
        'beat_id': 'b1', 'code': 'ROLE_CONTRACT_FAILED', 'function_verdict': 'unavailable'}]))
    result = sfm.compile_spine([{'beat_id': 'b1', 'role': 'setup',
        'event': {'text': 'The plan failed.', 'claim_refs': ['c1']}}],
        {'c1': {'claim': 'The plan failed.'}}, engine_id='removed_keystone')
    assert not result['passed']
    assert result['cascade']['unavailable'][0]['stage'] == 'function'


def test_editor_does_not_accept_detector_clean_but_semantically_broken_repair(monkeypatch):
    import script_editor
    script = {'scenes': [{'causal_role': 'hinge', 'narration': 'The original hinge has far too many words for this strict budget.'}]}
    defects = [{'scene': 1, 'code': script_editor.HINGE_TOO_LONG, 'note': 'over budget'}]
    response = NS(content=[NS(text=json.dumps({'scenes': [{'scene': 1, 'narration': 'The chicks is safe.'}]}))],
                  usage=NS(input_tokens=1, output_tokens=1))
    monkeypatch.setattr(ep, '_claude', lambda: NS(messages=NS(create=lambda **kw: response)))
    validate = Mock(return_value={'passed': False, 'errors': [{'code': 'BROKEN_GRAMMAR'}]})
    monkeypatch.setattr(ep, '_validate_claims', validate)
    result, _, remaining = script_editor.edit(script, {}, defects)
    assert result is script and remaining == defects and validate.call_count == 1
