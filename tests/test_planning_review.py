from pathlib import Path
from copy import deepcopy
import json
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
import durable_execution as durable
import explainer_pipeline as ep
import planning_evidence as pe
import planning_review_recovery as recovery
import script_stages
from test_durable_execution_phase6 import MemoryStore, MemoryBlob, runtime
from test_provider_blocks import transaction_store, CHECKPOINT


def claims(n=3):
    return [{"claim_id": f"c{i}", "claim": f"Fact {i}", "support_quote": f"Fact {i}"} for i in range(n)]


def row(cid, verdict="supported"):
    return {"claim_id": cid, "verdict": verdict, "reason": "passage comparison"}


def response(rows, stop="tool_use"):
    return NS(stop_reason=stop, content=[NS(type="tool_use", name="submit_claim_support", input={"claims": rows})],
              usage=NS(input_tokens=100, output_tokens=100))


def test_only_missing_and_ambiguous_decisions_are_retried(monkeypatch):
    create = Mock(side_effect=[response([row("c0", "unsupported"), row("c1"), row("c1"), row("unknown")]),
                               response([row("c1"), row("c2")])])
    monkeypatch.setattr(ep, "_claude", lambda: NS(messages=NS(create=create)))
    costs = []
    result = pe.prepare({"claims": claims()}, cost_sink=costs)
    asked = [json.loads(call.kwargs["messages"][0]["content"]) for call in create.call_args_list]
    assert [c["claim_id"] for c in asked[1]] == ["c1", "c2"]
    assert [c["claim_id"] for c in result["claims"]] == ["c1", "c2"]
    assert result["planning_excluded_claims"] == [claims()[0]]
    assert len(costs) == 2 and all(c > 0 for c in costs)
    assert create.call_args_list[0].kwargs["system"] != create.call_args_list[1].kwargs["system"]


@pytest.mark.parametrize("stop", ["max_tokens", "pause_turn"])
def test_truncated_response_cannot_be_salvaged(stop):
    accepted, diagnostic = pe._partial(response([row("c0")], stop), ["c0"])
    assert accepted == {} and diagnostic["code"] == "INCOMPLETE_RESPONSE"


def test_invalid_verdict_is_unresolved_not_unsupported():
    accepted, diagnostic = pe._partial(response([row("c0", []), row("c1")]), ["c0", "c1"])
    assert list(accepted) == ["c1"]
    assert diagnostic["invalid_ids"] == ["c0"]


def test_checkpoint_restores_decisions_and_retry_budget(tmp_path, monkeypatch):
    store, blob = MemoryStore(cap=10), MemoryBlob(tmp_path / "blob")
    first = runtime(tmp_path, store, blob, "first")
    original = first.checkpoint
    class Interrupted(BaseException): pass
    def checkpoint(label):
        original(label)
        raise Interrupted()
    first.checkpoint = checkpoint
    create = Mock(return_value=response([row("c0")]))
    monkeypatch.setattr(ep, "_claude", lambda: NS(messages=NS(create=create)))
    dossier = {"claims": claims(2)}
    with durable.activate(first), pytest.raises(Interrupted):
        pe.prepare(dossier)
    second = runtime(tmp_path, store, blob, "second")
    second.restore_checkpoint(store.job["checkpoint"])
    create.return_value = response([])
    with durable.activate(second), pytest.raises(ValueError, match="REVIEW_EXHAUSTED"):
        pe.prepare(dossier)
    assert len(create.call_args_list) == 2
    assert [c["claim_id"] for c in json.loads(create.call_args.kwargs["messages"][0]["content"])] == ["c1"]
    third = runtime(tmp_path, store, blob, "third")
    third.restore_checkpoint(store.job["checkpoint"])
    with durable.activate(third), pytest.raises(ValueError, match="REVIEW_EXHAUSTED"):
        pe.prepare(dossier)
    assert create.call_count == 2
    report = json.loads((Path(third.output_dir) / "planning_review.json").read_text())
    assert report["status"] == "exhausted" and report["unresolved_ids"] == ["c1"]


def test_batches_bound_response_size(monkeypatch):
    sizes = []
    def create(**kwargs):
        ids = [c["claim_id"] for c in json.loads(kwargs["messages"][0]["content"])]
        sizes.append(len(ids))
        return response([row(cid) for cid in ids])
    monkeypatch.setattr(ep, "_claude", lambda: NS(messages=NS(create=create)))
    assert len(pe.prepare({"claims": claims(19)})["claims"]) == 19
    assert sizes == [8, 8, 3]


def test_provider_unknown_outcome_is_not_semantic_retry(monkeypatch):
    create = Mock(side_effect=TimeoutError("unknown paid outcome"))
    monkeypatch.setattr(ep, "_claude", lambda: NS(messages=NS(create=create)))
    with pytest.raises(TimeoutError): pe.prepare({"claims": claims()})
    assert create.call_count == 1


def job():
    return {"id": "j", "kind": "explainer", "status": "error", "error": recovery.LEGACY_ERROR,
            "request": {"question": "stoats", "duration_sec": 180, "topic_channel": "world"},
            "checkpoint": {"sha256": CHECKPOINT}, "spent_cost_usd": 1, "max_cost_usd": 10,
            "reserved_cost_usd": 0}


def failed_stage():
    return {"status": "completed", "provider": "anthropic", "result": {"stop_reason": "tool_use", "content": [
        {"type": "tool_use", "name": "submit_claim_support", "input": {"claims": [row("c0")]}}]}}


def test_migration_reproduces_failure_and_preserves_limits():
    original = job()
    store, cur = transaction_store(original, [failed_stage()])
    evidence = {"claim_ids": ["c0", "c1"], "research_hash": "b" * 64}
    assert store.resume_planning_review("j", expected_checkpoint_sha256=CHECKPOINT, evidence=evidence)["status"] == "queued"
    sql = cur.execute.call_args[0][0]
    assert "max_cost_usd=" not in sql and "spent_cost_usd=" not in sql and "request=" not in sql
    marker = json.loads(cur.execute.call_args[0][1][0])
    assert marker[recovery.MARKER]["research_hash"] == evidence["research_hash"]


@pytest.mark.parametrize("patch", [
    {"status": "done"}, {"kind": "pilot"}, {"error": "Claim ledger failed"},
    {"error": "UNSCORED_JUDGE_UNAVAILABLE: planning claim support [REVIEW_EXHAUSTED]"},
    {"reserved_cost_usd": .1}, {"lease_owner": "worker"}, {"spent_cost_usd": 10},
    {"result": {recovery.MARKER: {"used": True}}}, {"request": {"controlled_pilot": True}},
])
def test_migration_rejects_unrelated_or_exhausted_jobs(patch):
    store, _ = transaction_store({**job(), **patch}, [failed_stage()])
    with pytest.raises(durable.DurableExecutionError):
        store.resume_planning_review("j", expected_checkpoint_sha256=CHECKPOINT,
                                     evidence={"claim_ids": ["c0", "c1"], "research_hash": "b"*64})


@pytest.mark.parametrize("stage", [{**failed_stage(), "status": "retry"}, {**failed_stage(), "provider": "tts"},
                                     {**failed_stage(), "result": {}}])
def test_migration_rejects_unresolved_stages_and_nonreproduced_failures(stage):
    store, _ = transaction_store(job(), [stage])
    with pytest.raises(durable.DurableExecutionError):
        store.resume_planning_review("j", expected_checkpoint_sha256=CHECKPOINT,
                                     evidence={"claim_ids": ["c0", "c1"], "research_hash": "b"*64})


def test_saved_research_must_replay_under_exact_request(tmp_path):
    store, blob = MemoryStore(), MemoryBlob(tmp_path / "blob")
    worker = runtime(tmp_path, store, blob, "writer")
    inputs = {"arguments": {"question": "stoats", "duration_sec": 180, "evidence_gaps": None},
              "context": {"channel": "world", "model": ep.ANTHROPIC_MODEL}}
    with durable.activate(worker):
        script_stages.save("research", inputs, {"result": {"claims": claims()}})
    saved = {**job(), "checkpoint": store.job["checkpoint"]}
    assert recovery.inspect_checkpoint(saved, store, blob)["claim_ids"] == ["c0", "c1", "c2"]
    saved["request"]["question"] = "different story"
    with pytest.raises(durable.DurableExecutionError, match="recipe/model"):
        recovery.inspect_checkpoint(saved, store, blob)


def test_duplicate_resume_is_idempotent_only_for_same_migration():
    saved = {**job(), "status": "processing", "result": {recovery.MARKER: {"checkpoint_sha256": CHECKPOINT}}}
    store, cur = transaction_store(saved, [])
    assert store.resume_planning_review("j", expected_checkpoint_sha256=CHECKPOINT, evidence={})["status"] == "processing"
    assert cur.execute.call_count == 1
    with pytest.raises(durable.DurableExecutionError):
        store, _ = transaction_store(saved, [])
        store.resume_planning_review("j", expected_checkpoint_sha256="f"*64, evidence={})


def test_saved_response_replay_after_checkpoint_write_interruption(tmp_path, monkeypatch):
    from test_durable_anthropic_response import Provider, payload
    raw = payload(stop_reason="tool_use")
    raw["content"] = [{"type":"tool_use", "name":"submit_claim_support", "input":{"claims":[row("c0")]}}]
    provider = Provider(raw)
    store, blob = MemoryStore(cap=10), MemoryBlob(tmp_path / "blob")
    first = runtime(tmp_path, store, blob, "first")
    original_publish = pe._publish
    monkeypatch.setattr(pe, "_publish", Mock(side_effect=OSError("checkpoint unavailable")))
    monkeypatch.setattr(ep, "_claude", lambda: first.wrap_anthropic(provider))
    with durable.activate(first), pytest.raises(OSError):
        pe.prepare({"claims":claims(1)})
    monkeypatch.setattr(pe, "_publish", original_publish)
    second = runtime(tmp_path, store, blob, "second")
    monkeypatch.setattr(ep, "_claude", lambda: second.wrap_anthropic(provider))
    with durable.activate(second):
        assert pe.prepare({"claims":claims(1)})["claims"]
    assert len(provider.calls) == 1


def test_authenticated_migration_route_checks_checkpoint_before_mutation(monkeypatch):
    import asyncio
    import httpx
    from fastapi import FastAPI
    import app as web
    import private_access
    import studio_jobs
    async def inline(fn, *args, **kwargs): return fn(*args, **kwargs)
    monkeypatch.setattr(web.asyncio, "to_thread", inline)
    monkeypatch.setenv("APP_USERNAME", "owner")
    monkeypatch.setenv("APP_PASSWORD", "test-password")
    monkeypatch.setenv("APP_SESSION_SECRET", "test-session-secret")
    saved = job()
    store = Mock(get_job=Mock(return_value=saved))
    inspect = Mock(return_value={"claim_ids":["c0"], "research_hash":"b"*64})
    monkeypatch.setattr(recovery, "inspect_checkpoint", inspect)
    monkeypatch.setattr(web, "_durable_execution_required", lambda:True)
    monkeypatch.setattr(web, "_durable_components", lambda:(store, Mock()))
    application=FastAPI()
    application.add_middleware(private_access.PrivateAccessMiddleware)
    application.add_api_route('/api/studio/jobs/{job_id}/resume-planning-review', web.studio_resume_planning_review, methods=['POST'])
    assert studio_jobs.snapshot(saved, [])['planning_review_resumable']
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),base_url='http://test') as c:
            url='/api/studio/jobs/j/resume-planning-review'
            assert (await c.post(url,json={'checkpoint_sha256':CHECKPOINT})).status_code==401
            c.cookies.set(private_access.COOKIE_NAME,private_access.create_session('owner'))
            assert (await c.post(url,json={'checkpoint_sha256':'f'*64})).status_code==409
            inspect.assert_not_called()
            assert (await c.post(url,json={'checkpoint_sha256':CHECKPOINT})).status_code==200
            store.resume_planning_review.assert_called_once()
            saved['error']='content failure'
            assert (await c.post(url,json={'checkpoint_sha256':CHECKPOINT})).status_code==409
            assert store.resume_planning_review.call_count==1
    asyncio.run(run())
