"""Oversized research is resized before spend; manual recovery cannot bypass any limit."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
from contextlib import contextmanager
from unittest.mock import Mock

import anyio
import httpx
import pytest

import _durable_execution_legacy as engine
import agent_actions
import app as studio
import db
import durable_execution as durable
import explainer_pipeline as pipeline
from test_agent_actions import ACTION_ID, FakeActionRepository, _secure_environment
from test_durable_anthropic_response import Provider, payload
from test_durable_execution_phase6 import MemoryBlob, MemoryStore, runtime
from test_longform_research_phase2 import SOURCE, QUOTE, _dossier
from test_research_continuation import _mock_sources


TITLE = "Introducing Cane Toads to Eat Beetles Made Australia Toxic to Predators"
CHECKPOINT = "a" * 64
STAGE = "anthropic:" + "b" * 32
ERROR = f"Stage {STAGE} reserves $1.0049; the single-call ceiling is $1.0000"


class LimitedStore(MemoryStore):
    def __init__(self, cap=10):
        super().__init__(cap)
        self.job["max_inflight_call_usd"] = 1
        self.denied = []

    def prepare_stage(self, job_id, key, provider, request_hash, estimate):
        if key not in self.stages:
            try:
                durable.enforce_budget(self.job, estimate, key)
            except durable.SingleCallReservationExceeded:
                self.denied.append((key, estimate))
                raise
        return super().prepare_stage(job_id, key, provider, request_hash, estimate)


def research_provider():
    data = payload(text=json.dumps(_dossier()))
    data["content"][0]["citations"] = [{"url": SOURCE, "cited_text": QUOTE}]
    return Provider(data)


def test_five_minute_research_fits_real_search_permissions_and_replays(tmp_path, monkeypatch):
    _mock_sources(monkeypatch)
    store, blob = LimitedStore(), MemoryBlob(tmp_path / "blob")
    provider = research_provider()
    results = []
    for name in ("first", "replacement"):
        worker = runtime(tmp_path, store, blob, name)
        monkeypatch.setattr(pipeline, "_anthropic_native", lambda: worker.wrap_anthropic(provider))
        results.append(pipeline.generate_research_dossier(TITLE, duration_sec=300))
    assert results[0] == results[1]
    assert results[0]["validation"]["passed"]
    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call["max_tokens"] == pipeline._research_token_budget(pipeline.research_claim_target(300)[1])
    assert call["tools"][0]["max_uses"] == 4
    assert results[0]["web_search_max_uses"] == 4
    assert len(store.denied) == 2 and store.denied[0][1] > 1
    assert store.denied[0][0] not in store.stages  # rejected before the provider/stage reservation
    assert len(store.stages) == 1 and store.job["reserved_cost_usd"] == pytest.approx(0)
    assert store.job["max_inflight_call_usd"] == 1 and store.job["max_cost_usd"] == 10
    assert next(iter(store.stages.values()))["reserved_cost_usd"] <= 1


def test_already_paid_large_request_replays_without_changing_searches(tmp_path, monkeypatch):
    _mock_sources(monkeypatch)
    store, blob = LimitedStore(), MemoryBlob(tmp_path / "blob")
    store.job["max_inflight_call_usd"] = 2
    provider = research_provider()
    for name in ("old", "new"):
        worker = runtime(tmp_path, store, blob, name)
        monkeypatch.setattr(pipeline, "_anthropic_native", lambda: worker.wrap_anthropic(provider))
        pipeline.generate_research_dossier(TITLE, duration_sec=300)
        store.job["max_inflight_call_usd"] = 1
    assert len(provider.calls) == 1 and not store.denied
    assert provider.calls[0]["tools"][0]["max_uses"] == 5


def test_total_budget_exhaustion_does_not_purchase_a_smaller_request(tmp_path, monkeypatch):
    _mock_sources(monkeypatch)
    store, blob = LimitedStore(cap=.1), MemoryBlob(tmp_path / "blob")
    provider = research_provider()
    worker = runtime(tmp_path, store, blob, "first")
    monkeypatch.setattr(pipeline, "_anthropic_native", lambda: worker.wrap_anthropic(provider))
    with pytest.raises(durable.BudgetExceeded):
        pipeline.generate_research_dossier(TITLE, duration_sec=300)
    assert not provider.calls and not store.stages


def test_search_fitting_never_clips_estimates_or_tokens_or_mutates_original():
    request = {"max_tokens": 28000, "messages": [],
               "tools": [{"type": "web_search_20260318", "max_uses": 5}]}
    original = copy.deepcopy(request)
    fitted = durable.fit_anthropic_search_request(request, 1)
    assert request == original and fitted["max_tokens"] == 28000
    assert fitted["tools"][0]["max_uses"] == 4
    assert engine._anthropic_reserved_cost(fitted) <= 1
    assert durable.fit_anthropic_search_request(request, .5) is None
    assert durable.fit_anthropic_search_request({"max_tokens": 60000, "messages": []}, 1) is None


def failed_job():
    return {"id": "job-1", "status": "error", "error": ERROR, "result": {},
            "checkpoint": {"sha256": CHECKPOINT}, "attempts": 1, "max_attempts": 5,
            "max_cost_usd": 10, "spent_cost_usd": .0141, "reserved_cost_usd": 0,
            "max_inflight_call_usd": 1, "request": {"immutable": "same spec"}}


def transaction_store(job, stages=()):
    cursor = Mock()
    cursor.fetchone.side_effect = [copy.deepcopy(job), {**job, "status": "queued"}]
    cursor.fetchall.return_value = list(stages)
    store = object.__new__(durable.PostgresStore)
    @contextmanager
    def tx():
        yield None, cursor
    store._tx = tx
    store._row = lambda _, value: value
    store.append_event = Mock()
    return store, cursor


def test_recovery_reconciles_ledger_and_preserves_spend_spec_and_limits():
    store, cursor = transaction_store(failed_job())
    assert store.resume_research_budget_block("job-1", expected_checkpoint_sha256=CHECKPOINT)["status"] == "queued"
    mutations = [call.args for call in cursor.execute.call_args_list
                 if call.args[0].lstrip().startswith("UPDATE")]
    assert len(mutations) == 1
    sql, params = mutations[0]
    assert "cost_usd=" not in sql and "request=" not in sql and "generation_stages" not in sql
    marker = json.loads(params[0])[durable.RESEARCH_BUDGET_RECOVERY]
    assert marker["checkpoint_sha256"] == CHECKPOINT and marker["stage_key"] == STAGE


@pytest.mark.parametrize("change", ["lease", "reservation", "budget", "checkpoint", "used",
                                    "content", "settlement", "large", "other_stage", "paid_stage"])
def test_unsafe_or_duplicate_recovery_is_rejected_without_writes(change):
    job, stages = failed_job(), []
    if change == "lease": job["lease_owner"] = "active-worker"
    elif change == "reservation": job["reserved_cost_usd"] = .2
    elif change == "budget": job["spent_cost_usd"] = 9.5
    elif change == "checkpoint": job["checkpoint"]["sha256"] = "c" * 64
    elif change == "used": job["result"][durable.RESEARCH_BUDGET_RECOVERY] = {"used": True}
    elif change == "content": job["error"] = "STORY_SPINE_UNSUPPORTED"
    elif change == "settlement": job["error"] = "Provider settlement exceeded the single-call liability ceiling"
    elif change == "large": job["error"] = ERROR.replace("1.0049", "2.0049")
    elif change == "other_stage": stages = [{"stage_key": "other", "status": "retry"}]
    elif change == "paid_stage": stages = [{"stage_key": STAGE, "status": "completed"}]
    store, cursor = transaction_store(job, stages)
    with pytest.raises(durable.DurableExecutionError):
        store.resume_research_budget_block("job-1", expected_checkpoint_sha256=CHECKPOINT)
    assert not any(call.args[0].lstrip().startswith("UPDATE") for call in cursor.execute.call_args_list)


def test_concurrent_restart_does_not_extend_attempts_twice():
    job = failed_job()
    job["status"] = "processing"
    store, cursor = transaction_store(job)
    assert store.resume_research_budget_block("job-1", expected_checkpoint_sha256=CHECKPOINT) == job
    assert not any(call.args[0].lstrip().startswith("UPDATE") for call in cursor.execute.call_args_list)


def test_status_and_dispatch_bind_restart_to_the_same_approved_job(monkeypatch):
    _secure_environment(monkeypatch)
    repository = FakeActionRepository()
    repository.action = {"action_id": ACTION_ID, "operation": "generic_illustrated",
                         "status": "queued", "job_id": "job-1", "cost_ceiling_usd": 10,
                         "claim_token_sha256": agent_actions.token_digest(ACTION_ID),
                         "spec_sha256": "d" * 64}
    job = failed_job()
    store = Mock()
    store.get_job.return_value = job
    store.events.return_value = []
    monkeypatch.setattr(agent_actions, "repository", lambda: repository)
    monkeypatch.setattr(studio, "_durable_execution_required", lambda: True)
    monkeypatch.setattr(studio, "_durable_components", lambda: (store, Mock()))
    monkeypatch.setattr(db, "finished_video_get", lambda _: None)
    dispatched = []
    async def worker(job_id):
        dispatched.append(job_id)
        return {"claimed": True}
    monkeypatch.setattr(studio, "_run_durable_explainer_worker", worker)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=studio.app), base_url="https://test") as client:
            status = (await client.get(f"/api/agent/actions/{ACTION_ID}/public-status")).json()
            assert status["job"]["restart"]["eligible"]
            assert status["job"]["restart"]["kind"] == "research_budget"
            assert CHECKPOINT not in json.dumps(status)
            denied = await client.post(f"/api/agent/actions/{ACTION_ID}/dispatch")
            assert denied.status_code == 403
            response = await client.post(f"/api/agent/actions/{ACTION_ID}/dispatch",
                                         headers={"Authorization": f"Bearer {ACTION_ID}"})
            assert response.status_code == 200, response.text
    anyio.run(run)
    store.resume_research_budget_block.assert_called_once_with("job-1", expected_checkpoint_sha256=CHECKPOINT)
    assert dispatched == ["job-1"]
    job["error"] = "Nature source-image review needs repair"
    assert not studio._agent_restart_state(repository.action, job)["eligible"]


@pytest.mark.skipif(not shutil.which("node"), reason="Node is required for browser-script behavior")
def test_restart_button_survives_redraw_and_ignores_double_clicks():
    page = (Path(__file__).resolve().parents[1] / "static/agent_actions.html").read_text()
    script = page.split("<script>", 1)[1].split("</script>", 1)[0].replace("\nload();", "")
    check = r"""
const vm=require('node:vm'),assert=require('node:assert/strict');
const root={innerHTML:'',querySelector:()=>null};
const ctx=vm.createContext({URLSearchParams,console,Set,setTimeout,clearTimeout,
  document:{getElementById:()=>root},location:{search:''},
  history:{replaceState:()=>{}},alert:()=>assert.fail('Unexpected alert')});
vm.runInContext(SCRIPT,ctx);
vm.runInContext(`(async()=>{
  const status={action_id:'act_test',title:'Example',job:{id:'job-1',status:'error',
    restart:{eligible:true,message:'Reuse saved work'}}};
  if(!restartHtml(status).includes('Restart from saved progress'))throw Error('Button missing');
  const failed={...status,job:{...status.job,restart:{eligible:false,message:'Repair first'}}};
  if(!restartHtml(failed).includes('disabled>Restart unavailable'))throw Error('Unsafe button');
  if(restartHtml({...status,finished_video:{}})!=='')throw Error('Finished video offered restart');
  let calls=0,complete;
  api=(path,options)=>{calls++;if(!path.endsWith('/dispatch')||options.method!=='POST')throw Error('Wrong request');return new Promise(resolve=>complete=resolve)};
  watchAction=async()=>{draw(status)};
  const first=resumeProvider(status);
  await resumeProvider(status);
  if(calls!==1||!restartHtml(status).includes('disabled'))throw Error('Duplicate restart');
  complete({claimed:true});await first;
  if(restarting.size!==0)throw Error('Button stayed busy');
})()`,ctx).catch(error=>{console.error(error);process.exitCode=1});
""".replace("SCRIPT", json.dumps(script))
    result = subprocess.run([shutil.which("node"), "-e", check], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
