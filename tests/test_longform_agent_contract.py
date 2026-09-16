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
