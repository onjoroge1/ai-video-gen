import copy
import json
from pathlib import Path

import anyio
import httpx
import pytest

import agent_actions
import app as studio
import finished_api
import private_access
from test_agent_actions import ACTION_ID, FakeActionRepository, _secure_environment


@pytest.mark.parametrize("duration", [60, 90, 180, 240, 300])
def test_duration_recipe_roundtrip_and_mutation(duration, monkeypatch):
    monkeypatch.delenv("I2V_PROVIDER", raising=False)
    providers = {"script": {"provider": "fixture"}}
    payload = agent_actions.build_illustrated_payload(topic="Stoats", duration_sec=duration,
        creative_direction="One researched story", cost_ceiling_usd=10, providers=providers)
    sha = agent_actions.illustrated_payload_hash(payload)
    assert agent_actions.validate_illustrated_payload(payload, expected_sha256=sha,
        providers=providers, cost_ceiling_usd=10)["duration_sec"] == duration
    assert payload["schema"] == ("illustrated_topic_v2" if duration <= 90 else "illustrated_topic_v3")
    if duration <= 90:
        assert payload["estimated_cost_usd"] == round(3.5 + duration / 5 * .055 + duration * .00045, 4)
    else:
        assert "50%" in payload["estimate_basis"]
    changed = copy.deepcopy(payload)
    changed["request"]["duration_sec"] = 299
    with pytest.raises(agent_actions.AgentActionConflict):
        agent_actions.validate_illustrated_payload(changed, expected_sha256=sha,
            providers=providers, cost_ceiling_usd=10)
    with pytest.raises(agent_actions.AgentActionConflict):
        agent_actions.validate_illustrated_payload(payload, expected_sha256=sha,
            providers=providers, cost_ceiling_usd=11)


def test_five_minute_proposal_approval_queue_and_duplicate(monkeypatch):
    _secure_environment(monkeypatch)
    monkeypatch.setenv("DURABLE_EXECUTION", "1")
    monkeypatch.setenv("DURABLE_JOB_MAX_COST_USD", "10")
    monkeypatch.setenv("AGENT_ACTION_LONGFORM_MAX_COST_USD", "10")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture")
    repo = FakeActionRepository()
    monkeypatch.setattr(agent_actions, "repository", lambda: repo)
    queued = []
    async def enqueue(request, background_tasks, **kwargs):
        queued.append((request, kwargs))
        return {"job_id": "five-minute-fixture", "durable": True}
    monkeypatch.setattr(studio, "_enqueue_explainer_request", enqueue)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=studio.app), base_url="http://test") as c:
            caps = (await c.get("/api/agent/capabilities")).json()
            assert caps["duration_sec"]["max"] == 300
            body = {"operation": "generic_illustrated", "topic": "New Zealand stoats",
                    "duration_sec": 300, "cost_ceiling_usd": 10}
            for duration in [59, 301, 300.5, True]:
                assert (await c.post("/api/agent/actions", json={**body, "duration_sec": duration})).status_code == 422
            for cost in [1, 11]:
                assert (await c.post("/api/agent/actions", json={**body, "cost_ceiling_usd": cost})).status_code == 409
            response = await c.post("/api/agent/actions", json=body)
            assert response.status_code == 200, response.text
            proposal = response.json()
            assert proposal["duration_sec"] == 300
            assert not queued
            duplicate = (await c.post("/api/agent/actions", json=body)).json()
            assert duplicate["reused"] and duplicate["action_id"] == proposal["action_id"]
            headers = {"Authorization": "Bearer " + proposal["claim_token"]}
            execute = f"/api/agent/actions/{ACTION_ID}/execute"
            assert (await c.post(execute, headers=headers)).status_code == 409
            approval = {"spec_sha256": proposal["spec_sha256"], "cost_ceiling_usd": 10}
            approve = f"/api/agent/actions/{ACTION_ID}/approve"
            assert (await c.post(approve, json=approval)).status_code == 401
            c.cookies.set(private_access.COOKIE_NAME, private_access.create_session("owner"))
            assert (await c.post(approve, json={**approval, "cost_ceiling_usd": 9})).status_code == 409
            assert (await c.post(approve, json=approval)).status_code == 200
            c.cookies.clear()
            response = await c.post(execute, headers=headers)
            assert response.status_code == 200, response.text
            assert queued[0][0].duration_sec == 300
            assert queued[0][0].visual_style == "illustrated_story"
            assert queued[0][1]["max_cost_usd"] == 10
            assert (await c.post(execute, headers=headers)).status_code == 200
            assert len(queued) == 1
    anyio.run(run)


def test_read_credential_is_scoped_and_saved_diagnostics_are_paginated(monkeypatch, tmp_path):
    _secure_environment(monkeypatch)
    token = "r" * 48
    monkeypatch.setenv("REELFORGE_AGENT_READ_TOKEN", token)
    repo = FakeActionRepository()
    repo.action = {"action_id": ACTION_ID, "job_id": "saved-job"}
    monkeypatch.setattr(agent_actions, "repository", lambda: repo)
    monkeypatch.setattr(studio, "_durable_execution_required", lambda: False)
    saved = tmp_path / "script.json"
    saved.write_text("x" * 24001)
    monkeypatch.setattr(studio, "_explainer_text_artifact", lambda *args: (str(saved), "story"))
    monkeypatch.setattr(finished_api, "_get", lambda *args: {"artifacts": {
        "video": {"url": "https://private.example/secret"}, "srt": {}, "internal": {}}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=studio.app), base_url="http://test") as c:
            path = f"/api/agent/actions/{ACTION_ID}/diagnostics?artifact=script"
            assert (await c.get(path)).status_code == 401
            assert (await c.get(path, headers={"Authorization": "Bearer bad"})).status_code == 401
            headers = {"Authorization": "Bearer " + token}
            first = (await c.get(path, headers=headers)).json()
            assert len(first["content"]) == 24000 and first["next_offset"] == 24000
            last = (await c.get(path + "&offset=24000", headers=headers)).json()
            assert last["content"] == "x" and last["next_offset"] is None
            assert (await c.get(path + "&offset=-1", headers=headers)).status_code == 422
            assert (await c.get(path.replace("script", "../../.env"), headers=headers)).status_code == 422
            for url in ["/api/finished", "/api/production-readiness", "/api/agent/actions/pending"]:
                assert (await c.get(url, headers=headers)).status_code == 401
            assert (await c.post(f"/api/agent/actions/{ACTION_ID}/approve", json={}, headers=headers)).status_code == 401
            manifest = (await c.get(f"/api/agent/actions/{ACTION_ID}/artifacts", headers=headers)).json()
            assert [x["kind"] for x in manifest["artifacts"]] == ["srt", "video"]
            assert "secret" not in json.dumps(manifest)
    anyio.run(run)


def test_durable_diagnostics_restore_current_checkpoint_and_cleanup(monkeypatch):
    repo = FakeActionRepository()
    repo.action = {"action_id": ACTION_ID, "job_id": "saved-job"}
    monkeypatch.setattr(agent_actions, "repository", lambda: repo)
    monkeypatch.setattr(studio, "_durable_execution_required", lambda: True)
    class Store:
        def get_job(self, job):
            return {"checkpoint": {"sha256": "latest"}}
    monkeypatch.setattr(studio, "_durable_components", lambda: (Store(), object()))
    roots = []
    class Runtime:
        def __init__(self, **kwargs):
            self.root = Path(kwargs["output_dir"])
            roots.append(self.root)
        def restore_checkpoint(self, checkpoint):
            assert checkpoint["sha256"] == "latest"
            (self.root / "_state.json").write_text('{"script": {"title": "latest"}}')
    monkeypatch.setattr(studio.durable_execution, "DurableRuntime", Runtime)
    async def run():
        result = await studio.agent_diagnostics(ACTION_ID, "script", 0)
        assert json.loads(result["content"])["script"]["title"] == "latest"
        with pytest.raises(studio.HTTPException) as exc:
            await studio.agent_diagnostics(ACTION_ID, "grade", 0)
        assert exc.value.status_code == 404
    anyio.run(run)
    assert all(not root.exists() for root in roots)


def test_nature_failure_diagnostics_read_original_checkpoint_privately_without_retry(monkeypatch):
    _secure_environment(monkeypatch)
    token = "r" * 48
    monkeypatch.setenv("REELFORGE_AGENT_READ_TOKEN", token)
    repo = FakeActionRepository()
    repo.action = {"action_id": ACTION_ID, "job_id": "saved-job"}
    monkeypatch.setattr(agent_actions, "repository", lambda: repo)
    monkeypatch.setattr(studio, "_durable_execution_required", lambda: True)
    saved = json.dumps({"available": False, "error": "invalid_review_json",
                        "evidence": "<script>alert(1)</script>"})
    job = {"status": "error", "spent_cost_usd": .9184, "checkpoint": {"sha256": "latest"}}
    original = copy.deepcopy(job)
    class Store:
        def get_job(self, job_id):
            assert job_id == "saved-job"
            return job
    monkeypatch.setattr(studio, "_durable_components", lambda: (Store(), object()))
    roots = []
    class Runtime:
        def __init__(self, **kwargs):
            assert kwargs["worker_id"] == "read-only"
            self.root = Path(kwargs["output_dir"])
            roots.append(self.root)
        def restore_checkpoint(self, checkpoint):
            assert checkpoint == original["checkpoint"]
            (self.root / "nature_visual_review.json").write_text(saved)
            (self.root / "nature_semantic_review.json").write_text('{"passed": true}')
    monkeypatch.setattr(studio.durable_execution, "DurableRuntime", Runtime)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=studio.app), base_url="http://test") as c:
            api = f"/api/agent/actions/{ACTION_ID}/diagnostics"
            page = f"/agent/actions/{ACTION_ID}/nature-review"
            assert (await c.get(api + "?artifact=nature-visual-review")).status_code == 401
            assert (await c.get(page)).status_code != 200
            assert not roots
            headers = {"Authorization": "Bearer " + token}
            result = await c.get(api + "?artifact=nature-visual-review", headers=headers)
            assert result.status_code == 200
            assert result.json()["content"] == saved
            assert result.json()["source"] == "saved_artifact"
            result = await c.get(api + "?artifact=nature-semantic-review", headers=headers)
            assert json.loads(result.json()["content"])["passed"] is True
            assert (await c.get(page, headers=headers)).status_code != 200
            c.cookies.set(private_access.COOKIE_NAME, private_access.create_session("owner"))
            result = await c.get(page)
            assert result.status_code == 200
            assert "&lt;script&gt;" in result.text and "<script>" not in result.text
            assert "Download nature_visual_review.json" in result.text
            result = await c.get(page + "?download=true")
            assert result.text == saved
            assert result.headers["content-disposition"] == 'attachment; filename="nature_visual_review.json"'
            assert result.headers["cache-control"] == "no-store"
    anyio.run(run)
    assert job == original
    assert len(roots) == 4 and all(not root.exists() for root in roots)


def test_storyboard_repair_diagnostics_reveal_legacy_reason_without_retry(monkeypatch):
    _secure_environment(monkeypatch)
    token = 'r' * 48
    monkeypatch.setenv('REELFORGE_AGENT_READ_TOKEN', token)
    repo = FakeActionRepository()
    repo.action = {'action_id': ACTION_ID, 'job_id': 'saved-job'}
    monkeypatch.setattr(agent_actions, 'repository', lambda: repo)
    monkeypatch.setattr(studio, '_durable_execution_required', lambda: True)
    # Legacy PR141 shape: neither rejection_code nor provider_response_text existed.
    saved = json.dumps({'status': 'rejected', 'reason': 'Repair still exceeds the opening word budget',
                        'input_script': {'title': '<script>alert(1)</script>'}})
    failure = '{"stage":"illustrated-storyboard","report":{"passed":false}}'
    job = {'status': 'error', 'spent_cost_usd': 3.299, 'checkpoint': {'sha256': 'latest'}}
    original = copy.deepcopy(job)
    class Store:
        def get_job(self, job_id):
            assert job_id == 'saved-job'
            return job
    monkeypatch.setattr(studio, '_durable_components', lambda: (Store(), object()))
    roots = []
    class Runtime:
        def __init__(self, **kwargs):
            assert kwargs['worker_id'] == 'read-only'
            self.root = Path(kwargs['output_dir'])
            roots.append(self.root)
        def restore_checkpoint(self, checkpoint):
            assert checkpoint == original['checkpoint']
            (self.root / 'illustrated_storyboard_repair_v1.json').write_text(saved)
            (self.root / 'semantic_failure_illustrated-storyboard.json').write_text(failure)
    monkeypatch.setattr(studio.durable_execution, 'DurableRuntime', Runtime)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=studio.app), base_url='http://test') as c:
            api = f'/api/agent/actions/{ACTION_ID}/diagnostics'
            page = f'/agent/actions/{ACTION_ID}/storyboard-repair'
            assert (await c.get(api + '?artifact=storyboard-repair')).status_code == 401
            assert (await c.get(page)).status_code != 200
            assert not roots
            headers = {'Authorization': 'Bearer ' + token}
            response = await c.get(api + '?artifact=storyboard-repair', headers=headers)
            assert response.status_code == 200 and response.json()['content'] == saved
            response = await c.get(api + '?artifact=storyboard-failure', headers=headers)
            assert response.json()['content'] == failure
            assert (await c.get(page, headers=headers)).status_code != 200
            assert (await c.post(f'/api/agent/actions/{ACTION_ID}/dispatch', headers=headers)).status_code == 403
            c.cookies.set(private_access.COOKIE_NAME, private_access.create_session('owner'))
            response = await c.get(page)
            assert response.status_code == 200
            assert 'Repair still exceeds the opening word budget' in response.text
            assert '&lt;script&gt;' in response.text and '<script>' not in response.text
            assert response.headers['cache-control'] == 'no-store'
            response = await c.get(page + '?download=true')
            assert response.text == saved
            assert response.headers['content-disposition'] == 'attachment; filename="illustrated_storyboard_repair_v1.json"'
            assert response.headers['cache-control'] == 'no-store'
    anyio.run(run)
    assert job == original and len(roots) == 4 and all(not root.exists() for root in roots)


def test_storyboard_repair_diagnostics_prefer_latest_budget_repair(monkeypatch):
    _secure_environment(monkeypatch)
    token = 'r' * 48
    monkeypatch.setenv('REELFORGE_AGENT_READ_TOKEN', token)
    repo = FakeActionRepository()
    repo.action = {'action_id': ACTION_ID, 'job_id': 'saved-job'}
    monkeypatch.setattr(agent_actions, 'repository', lambda: repo)
    monkeypatch.setattr(studio, '_durable_execution_required', lambda: True)
    legacy = json.dumps({'version': 'illustrated_storyboard_repair_v1',
                         'status': 'rejected', 'reason': 'legacy reason'})
    latest = json.dumps({'version': 'illustrated_storyboard_opening_budget_repair_v2',
                         'status': 'rejected',
                         'reason': 'Repair exceeds a scene opening word limit'})
    job = {'status': 'error', 'spent_cost_usd': 3.4736,
           'checkpoint': {'sha256': 'latest'}}
    original = copy.deepcopy(job)
    class Store:
        def get_job(self, job_id):
            assert job_id == 'saved-job'
            return job
    monkeypatch.setattr(studio, '_durable_components', lambda: (Store(), object()))
    roots = []
    class Runtime:
        def __init__(self, **kwargs):
            assert kwargs['worker_id'] == 'read-only'
            self.root = Path(kwargs['output_dir'])
            roots.append(self.root)
        def restore_checkpoint(self, checkpoint):
            assert checkpoint == original['checkpoint']
            (self.root / 'illustrated_storyboard_repair_v1.json').write_text(legacy)
            (self.root / 'illustrated_storyboard_opening_budget_repair_v2.json').write_text(latest)
    monkeypatch.setattr(studio.durable_execution, 'DurableRuntime', Runtime)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=studio.app), base_url='http://test') as c:
            api = f'/api/agent/actions/{ACTION_ID}/diagnostics?artifact=storyboard-repair'
            response = await c.get(api, headers={'Authorization': 'Bearer ' + token})
            assert response.status_code == 200
            assert response.json()['content'] == latest
            c.cookies.set(private_access.COOKIE_NAME, private_access.create_session('owner'))
            page = f'/agent/actions/{ACTION_ID}/storyboard-repair'
            response = await c.get(page)
            assert response.status_code == 200
            assert 'Repair exceeds a scene opening word limit' in response.text
            assert 'legacy reason' not in response.text
            assert 'Download illustrated_storyboard_opening_budget_repair_v2.json' in response.text
            response = await c.get(page + '?download=true')
            assert response.text == latest
            assert response.headers['content-disposition'] == (
                'attachment; filename="illustrated_storyboard_opening_budget_repair_v2.json"')
            assert response.headers['cache-control'] == 'no-store'
    anyio.run(run)
    assert job == original and len(roots) == 3 and all(not root.exists() for root in roots)
