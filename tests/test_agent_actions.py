import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anyio
import httpx
import pytest

import agent_actions
import app as studio
import db
import private_access


ROOT = Path(__file__).resolve().parents[1]
ACTION_ID = "act_" + "a" * 32


class FakeActionRepository:
    def __init__(self):
        self.action = None

    def create(self, **values):
        now = datetime.now(timezone.utc)
        self.action = {
            "action_id": ACTION_ID,
            "operation": agent_actions.OPERATION,
            "status": "pending",
            "created_at": now,
            "expires_at": now + timedelta(seconds=values.pop("ttl_seconds")),
            "approved_at": None,
            "approved_by": None,
            "job_id": None,
            "error": None,
            **copy.deepcopy(values),
        }
        return copy.deepcopy(self.action)

    def get(self, action_id):
        return copy.deepcopy(self.action) if self.action and action_id == ACTION_ID else None

    def pending(self):
        return [copy.deepcopy(self.action)] if self.action else []

    def reusable_for_spec(self, spec_sha256, cost_ceiling_usd,
                          operation=agent_actions.DIRECTED_PILOT_OPERATION):
        if (self.action and self.action.get("spec_sha256") == spec_sha256
                and self.action.get("operation") == operation
                and float(self.action.get("cost_ceiling_usd") or 0) == float(cost_ceiling_usd)
                and self.action.get("status") in {
                    "pending", "approved", "executing", "queued", "failed"}):
            return copy.deepcopy(self.action)
        return None

    def approve(self, action_id, *, spec_sha256, cost_ceiling_usd, approver):
        if not self.action or action_id != ACTION_ID:
            raise agent_actions.AgentActionConflict("Agent action not found")
        if self.action["status"] != "pending":
            raise agent_actions.AgentActionConflict("Agent action is not pending")
        if spec_sha256 != self.action["spec_sha256"]:
            raise agent_actions.AgentActionConflict("Specification hash changed")
        if float(cost_ceiling_usd) != float(self.action["cost_ceiling_usd"]):
            raise agent_actions.AgentActionConflict("Cost ceiling changed")
        self.action.update(status="approved", approved_at=datetime.now(timezone.utc),
                           approved_by=approver)
        return copy.deepcopy(self.action)

    def reject(self, action_id, *, approver):
        if not self.action or action_id != ACTION_ID or self.action["status"] != "pending":
            raise agent_actions.AgentActionConflict("Only a pending action can be rejected")
        self.action.update(status="rejected", approved_by=approver)
        return copy.deepcopy(self.action)

    def claim(self, action_id, *, claim_token):
        if (not self.action or action_id != ACTION_ID
                or not agent_actions.verify_claim_token(self.action, claim_token)):
            raise agent_actions.AgentActionForbidden("Invalid agent action claim token")
        if self.action["status"] != "approved":
            raise agent_actions.AgentActionConflict("Agent action has not been approved")
        self.action["status"] = "executing"
        return copy.deepcopy(self.action)

    def mark_queued(self, action_id, job_id):
        assert action_id == ACTION_ID
        self.action.update(status="queued", job_id=job_id)
        return copy.deepcopy(self.action)

    def mark_failed(self, action_id, error):
        assert action_id == ACTION_ID
        self.action.update(status="failed", error=error)
        return copy.deepcopy(self.action)


def _secure_environment(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("APP_USERNAME", "owner")
    monkeypatch.setenv("APP_PASSWORD", "studio-password")
    monkeypatch.setenv("APP_SESSION_SECRET", "independent-session-secret")
    monkeypatch.delenv("APP_SHARED_SECRET", raising=False)


def test_agent_action_lifecycle_requires_exact_operator_approval(monkeypatch):
    _secure_environment(monkeypatch)
    repository = FakeActionRepository()
    monkeypatch.setattr(agent_actions, "repository", lambda: repository)
    monkeypatch.setattr(studio, "_durable_execution_required", lambda: True)
    queued = []

    async def enqueue(request, background_tasks, *, max_cost_usd=None):
        queued.append({"request": request, "max_cost_usd": max_cost_usd})
        return {"job_id": "pilot001", "durable": True}

    monkeypatch.setattr(studio, "_enqueue_explainer_request", enqueue)

    async def run():
        transport = httpx.ASGITransport(app=studio.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Proposal is the only unauthenticated creation surface and cannot spend.
            created = await client.post("/api/agent/actions", json={
                "operation": "directed_pilot",
                "bundled_spec_id": "hippo_illustrated_story_v4",
                "cost_ceiling_usd": 1.60,
            })
            assert created.status_code == 200, created.text
            proposal = created.json()
            token = proposal.pop("claim_token")
            assert proposal["action_id"] == ACTION_ID
            assert proposal["scope"] == "first-45-pilot"
            assert proposal["estimated_cost_usd"] <= 1.60
            assert queued == []
            assert repository.action["claim_token_sha256"] == agent_actions.token_digest(token)
            assert token not in json.dumps(repository.action, default=str)

            duplicate = await client.post("/api/agent/actions", json={
                "operation": "directed_pilot",
                "bundled_spec_id": "hippo_illustrated_story_v4",
                "cost_ceiling_usd": 1.60,
            })
            assert duplicate.status_code == 200, duplicate.text
            assert duplicate.json()["action_id"] == ACTION_ID
            assert duplicate.json()["reused"] is True
            assert "claim_token" not in duplicate.json()

            assert (await client.get("/api/agent/actions/pending")).status_code == 401
            assert (await client.get(f"/api/agent/actions/{ACTION_ID}")).status_code == 403
            visible = await client.get(
                f"/api/agent/actions/{ACTION_ID}",
                headers={"Authorization": f"Bearer {token}"})
            assert visible.status_code == 200
            assert "payload" not in visible.json()
            assert (await client.post(
                f"/api/agent/actions/{ACTION_ID}/approve", json={
                    "spec_sha256": proposal["spec_sha256"], "cost_ceiling_usd": 1.60,
                })).status_code == 401

            before_approval = await client.post(
                f"/api/agent/actions/{ACTION_ID}/execute",
                headers={"Authorization": f"Bearer {token}"})
            assert before_approval.status_code == 409
            assert queued == []

            client.cookies.set(
                private_access.COOKIE_NAME, private_access.create_session("owner"))
            changed_hash = await client.post(
                f"/api/agent/actions/{ACTION_ID}/approve", json={
                    "spec_sha256": "0" * 64, "cost_ceiling_usd": 1.60,
                })
            assert changed_hash.status_code == 409
            approved = await client.post(
                f"/api/agent/actions/{ACTION_ID}/approve", json={
                    "spec_sha256": proposal["spec_sha256"], "cost_ceiling_usd": 1.60,
                })
            assert approved.status_code == 200, approved.text
            assert approved.json()["status"] == "approved"

            client.cookies.clear()
            wrong_token = await client.post(
                f"/api/agent/actions/{ACTION_ID}/execute",
                headers={"Authorization": "Bearer wrong"})
            assert wrong_token.status_code == 403
            executed = await client.post(
                f"/api/agent/actions/{ACTION_ID}/execute",
                headers={"Authorization": f"Bearer {token}"})
            assert executed.status_code == 200, executed.text
            assert executed.json()["status"] == "queued"
            assert len(queued) == 1
            assert queued[0]["request"].duration_sec == 45
            assert queued[0]["max_cost_usd"] == 1.60

            replay = await client.post(
                f"/api/agent/actions/{ACTION_ID}/execute",
                headers={"Authorization": f"Bearer {token}"})
            assert replay.status_code == 409
            assert len(queued) == 1

            queued_duplicate = await client.post("/api/agent/actions", json={
                "operation": "directed_pilot",
                "bundled_spec_id": "hippo_illustrated_story_v4",
                "cost_ceiling_usd": 1.60,
            })
            assert queued_duplicate.status_code == 200
            assert queued_duplicate.json()["action_id"] == ACTION_ID
            assert queued_duplicate.json()["status"] == "queued"
            assert queued_duplicate.json()["reused"] is True
            assert len(queued) == 1

    anyio.run(run)


def test_agent_action_public_surface_does_not_expand_authority(monkeypatch):
    _secure_environment(monkeypatch)

    async def run():
        transport = httpx.ASGITransport(app=studio.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/agent/actions/request")).status_code == 200
            assert (await client.get(
                "/agent/actions", headers={"Accept": "text/html"})).status_code == 303
            assert (await client.get("/api/agent/actions/pending")).status_code == 401
            assert (await client.post("/api/agent/actions", json={
                "operation": "full_film", "bundled_spec_id": "hippo_illustrated_story_v4",
                "cost_ceiling_usd": 1.60,
            })).status_code == 422
            # A near-match does not accidentally become a public route.
            assert (await client.get(
                "/api/agent/actions/act_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/approve"
            )).status_code == 401

    anyio.run(run)


def test_agent_dispatch_requeues_only_its_bound_storage_failure(monkeypatch):
    _secure_environment(monkeypatch)
    repository = FakeActionRepository()
    token = "one-action-token"
    now = datetime.now(timezone.utc)
    repository.action = {
        "action_id": ACTION_ID, "operation": "directed_pilot", "status": "queued",
        "title": "Pilot", "spec_sha256": "f" * 64, "estimated_cost_usd": 1.5,
        "cost_ceiling_usd": 1.6, "created_at": now,
        "expires_at": now + timedelta(minutes=5), "approved_at": now,
        "claim_token_sha256": agent_actions.token_digest(token), "job_id": "pilot001",
        "payload": {}, "error": None,
    }
    monkeypatch.setattr(agent_actions, "repository", lambda: repository)
    calls = []

    class Store:
        def get_job(self, job_id):
            assert job_id == "pilot001"
            return {"id": job_id, "status": "storage_error"}

        def requeue(self, job_id, *, allowed_statuses):
            calls.append((job_id, allowed_statuses))

    monkeypatch.setattr(studio, "_durable_components", lambda: (Store(), object()))

    async def worker(job_id):
        return {"claimed": True, "job": {"id": job_id, "status": "done"}}

    monkeypatch.setattr(studio, "_run_durable_explainer_worker", worker)

    async def run():
        transport = httpx.ASGITransport(app=studio.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/agent/actions/{ACTION_ID}/dispatch",
                headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 200, response.text
            assert response.json()["claimed"] is True

    anyio.run(run)
    assert calls == [("pilot001", ("storage_error",))]


def test_agent_dispatch_rearms_exact_repaired_ffprobe_failure(monkeypatch):
    _secure_environment(monkeypatch)
    repository = FakeActionRepository()
    token = "one-action-token"
    now = datetime.now(timezone.utc)
    repository.action = {
        "action_id": ACTION_ID, "operation": "directed_pilot", "status": "queued",
        "title": "Pilot", "spec_sha256": "f" * 64, "estimated_cost_usd": 1.5,
        "cost_ceiling_usd": 1.6, "created_at": now,
        "expires_at": now + timedelta(minutes=5), "approved_at": now,
        "claim_token_sha256": agent_actions.token_digest(token), "job_id": "pilot001",
        "payload": {}, "error": None,
    }
    monkeypatch.setattr(agent_actions, "repository", lambda: repository)
    calls = []

    class Store:
        def get_job(self, job_id):
            return {"id": job_id, "status": "error",
                    "error": "Required media binary 'ffprobe' was not found: install it"}

        def rearm_infrastructure_failure(self, job_id, **kwargs):
            calls.append((job_id, kwargs))

    monkeypatch.setattr(studio, "_durable_components", lambda: (Store(), object()))
    monkeypatch.setattr(studio.media_binaries, "preflight", lambda: {"ready": True})

    async def worker(job_id):
        return {"claimed": True, "job": {"id": job_id, "status": "done"}}

    monkeypatch.setattr(studio, "_run_durable_explainer_worker", worker)

    async def run():
        transport = httpx.ASGITransport(app=studio.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/agent/actions/{ACTION_ID}/dispatch",
                headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 200, response.text

    anyio.run(run)
    assert calls == [("pilot001", {
        "error_fragment": "Required media binary 'ffprobe' was not found",
        "extra_attempts": 3,
    })]


def test_agent_dispatch_rearms_exact_repaired_motion_manifest_failure(monkeypatch):
    _secure_environment(monkeypatch)
    repository = FakeActionRepository()
    token = "one-action-token"
    now = datetime.now(timezone.utc)
    repository.action = {
        "action_id": ACTION_ID, "operation": "directed_pilot", "status": "queued",
        "title": "Pilot", "spec_sha256": "f" * 64, "estimated_cost_usd": 1.5,
        "cost_ceiling_usd": 1.6, "created_at": now,
        "expires_at": now + timedelta(minutes=5), "approved_at": now,
        "claim_token_sha256": agent_actions.token_digest(token), "job_id": "pilot001",
        "payload": {}, "error": None,
    }
    monkeypatch.setattr(agent_actions, "repository", lambda: repository)
    calls = []

    class Store:
        def get_job(self, job_id):
            return {"id": job_id, "status": "error", "error": "'cache_path'"}

        def rearm_infrastructure_failure(self, job_id, **kwargs):
            calls.append((job_id, kwargs))

    monkeypatch.setattr(studio, "_durable_components", lambda: (Store(), object()))

    async def worker(job_id):
        return {"claimed": True, "job": {"id": job_id, "status": "done"}}

    monkeypatch.setattr(studio, "_run_durable_explainer_worker", worker)

    async def run():
        transport = httpx.ASGITransport(app=studio.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/agent/actions/{ACTION_ID}/dispatch",
                headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 200, response.text

    anyio.run(run)
    assert calls == [("pilot001", {"error_fragment": "'cache_path'", "extra_attempts": 3})]


@pytest.mark.parametrize("legacy,authorized", [(True, True), (False, True), (True, False)])
@pytest.mark.parametrize("failure_type", ["json", "sources", "claims"])
def test_research_parser_recovery_is_scoped_to_old_failure_and_action_token(
        monkeypatch, legacy, authorized, failure_type):
    from longform_research import LEGACY_DOSSIER_JSON_ERROR
    _secure_environment(monkeypatch)
    repository = FakeActionRepository()
    now = datetime.now(timezone.utc)
    token = "one-action-token"
    repository.action = {
        "action_id": ACTION_ID, "operation": "generic_illustrated", "status": "queued",
        "title": "Cobra", "spec_sha256": "f" * 64, "cost_ceiling_usd": 5,
        "created_at": now, "expires_at": now - timedelta(minutes=1), "approved_at": now,
        "claim_token_sha256": agent_actions.token_digest(token), "job_id": "cobra001",
        "payload": {},
    }
    monkeypatch.setattr(agent_actions, "repository", lambda: repository)
    calls = []
    old_error = LEGACY_DOSSIER_JSON_ERROR
    new_error = "Research provider returned malformed dossier JSON (incomplete object); no claims accepted."
    fragment = "Research provider returned malformed dossier JSON;"
    if failure_type == "sources":
        message = ("Social, community, encyclopedia, and generic blogging URLs are not "
                   "authoritative evidence.")
        old_error = ("Research dossier failed before scripting [23 quotable excerpts available; "
                     "weak_source_domainx7]: " + "; ".join([message] * 3))
        new_error = "Research dossier has no usable claims after excluding disallowed sources."
        fragment = "weak_source_domainx"
    elif failure_type == "claims":
        old_error = ("Claim ledger failed after script/fact-check before asset spend: "
                     "A speculative claim is narrated as certain. [scene 7]")
        new_error = ("Claim ledger failed after script/fact-check before asset spend: "
                     "The scene references a claim absent from the dossier. [scene 7]")
        fragment = "Claim ledger failed after script/fact-check before asset spend:"

    class Store:
        def get_job(self, job_id):
            return {"id": job_id, "status": "error", "error": (
                old_error if legacy else new_error)}

        def rearm_infrastructure_failure(self, job_id, **kwargs):
            calls.append((job_id, kwargs))

    monkeypatch.setattr(studio, "_durable_components", lambda: (Store(), object()))

    async def worker(job_id):
        return {"claimed": bool(calls), "job": {"id": job_id}}

    monkeypatch.setattr(studio, "_run_durable_explainer_worker", worker)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=studio.app),
                                     base_url="http://test") as client:
            response = await client.post(f"/api/agent/actions/{ACTION_ID}/dispatch",
                                        headers={"Authorization": f"Bearer {token if authorized else 'wrong'}"})
            assert response.status_code == (200 if authorized else 403)

    anyio.run(run)
    assert calls == ([("cobra001", {
        "error_fragment": fragment, "extra_attempts": 1,
    })] if authorized and legacy else [])


@pytest.mark.parametrize("error", [
    "Research dossier failed before scripting [23 quotable excerpts available; weak_source_domainx7, scope_inflationx1]: Bad evidence.",
    "Research dossier failed before scripting [23 quotable excerpts available; weak_source_domainx7]: Unexpected failure.",
    "Research dossier failed before scripting [0 quotable excerpts available; missing_claimsx1]: No claims.",
    "Other failure weak_source_domainx7",
])
def test_source_recovery_never_rearms_unrelated_evidence_failures(error):
    from longform_research import is_legacy_weak_source_failure
    assert not is_legacy_weak_source_failure(error)


def test_research_failure_is_not_reported_as_completed_or_graded(monkeypatch):
    _secure_environment(monkeypatch)
    monkeypatch.setattr(studio, "_durable_execution_required", lambda: True)
    repository = FakeActionRepository()
    repository.action = {
        "action_id": ACTION_ID, "operation": "generic_illustrated", "status": "queued",
        "payload": {}, "job_id": "cobra001", "cost_ceiling_usd": 5,
    }
    monkeypatch.setattr(agent_actions, "repository", lambda: repository)

    class Store:
        def get_job(self, job_id):
            return {"id": job_id, "status": "error", "spent_cost_usd": .711,
                    "result": {"rendered_contract": {}}}

        def events(self, *args):
            return []

    monkeypatch.setattr(studio, "_durable_components", lambda: (Store(), object()))
    monkeypatch.setattr(db, "finished_video_get", lambda job_id: None)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=studio.app),
                                     base_url="http://test") as client:
            response = await client.get(f"/api/agent/actions/{ACTION_ID}/public-status")
            assert response.status_code == 200
            status = response.json()
            assert status["status"] == "error"
            assert status["progress"]["percent"] == 0
            assert "grading" not in status["job"]["result"]
            assert "finished_video" not in status

    anyio.run(run)


def test_agent_dispatch_rearms_exact_disk_exhaustion_without_new_job(monkeypatch):
    _secure_environment(monkeypatch)
    repository = FakeActionRepository()
    token = "one-action-token"
    now = datetime.now(timezone.utc)
    repository.action = {
        "action_id": ACTION_ID, "operation": "directed_full_film", "status": "queued",
        "title": "Full film", "spec_sha256": "f" * 64, "estimated_cost_usd": 5.4,
        "cost_ceiling_usd": 6.0, "created_at": now,
        "expires_at": now + timedelta(minutes=5), "approved_at": now,
        "claim_token_sha256": agent_actions.token_digest(token), "job_id": "full001",
        "payload": {}, "error": None,
    }
    monkeypatch.setattr(agent_actions, "repository", lambda: repository)
    calls = []

    class Store:
        def get_job(self, job_id):
            return {"id": job_id, "status": "error",
                    "error": "Blob download failed: [Errno 28] No space left on device"}

        def rearm_disk_exhaustion(self, job_id, **kwargs):
            calls.append((job_id, kwargs))

    monkeypatch.setattr(studio, "_durable_components", lambda: (Store(), object()))

    async def worker(job_id):
        return {"claimed": True, "job": {"id": job_id, "status": "processing"}}

    monkeypatch.setattr(studio, "_run_durable_explainer_worker", worker)

    async def run():
        transport = httpx.ASGITransport(app=studio.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/agent/actions/{ACTION_ID}/dispatch",
                headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 200, response.text
            assert response.json()["job"]["id"] == "full001"

    anyio.run(run)
    assert calls == [("full001", {"extra_attempts": 3})]


def test_public_action_never_exposes_payload_token_or_operator():
    now = datetime.now(timezone.utc)
    action = {
        "action_id": ACTION_ID, "operation": "directed_pilot", "status": "queued",
        "title": "Pilot", "spec_sha256": "f" * 64, "estimated_cost_usd": 1.5,
        "cost_ceiling_usd": 1.6, "created_at": now, "expires_at": now + timedelta(minutes=5),
        "approved_at": now, "approved_by": "owner@example.com", "job_id": "secret-job",
        "error": "provider internals", "payload": {"secret": True},
        "claim_token_sha256": "digest",
    }
    public = agent_actions.public_action(action)
    serialized = json.dumps(public)
    for secret in ("owner@example.com", "secret-job", "provider internals", "digest", "secret"):
        assert secret not in serialized


def test_public_status_returns_sanitized_progress_and_finished_player(monkeypatch):
    _secure_environment(monkeypatch)
    monkeypatch.setattr(studio, "_durable_execution_required", lambda: True)
    repository = FakeActionRepository()
    payload = json.loads(
        (ROOT / "spec" / "hippo_illustrated_story_v4.json").read_text())
    now = datetime.now(timezone.utc)
    repository.action = {
        "action_id": ACTION_ID, "operation": "directed_pilot", "status": "queued",
        "title": payload["title"], "spec_sha256": "f" * 64,
        "estimated_cost_usd": 1.3934, "cost_ceiling_usd": 1.6,
        "created_at": now, "expires_at": now + timedelta(minutes=5),
        "approved_at": now, "claim_token_sha256": "digest", "job_id": "pilot001",
        "payload": payload, "error": None,
    }
    monkeypatch.setattr(agent_actions, "repository", lambda: repository)

    class Store:
        def get_job(self, job_id):
            assert job_id == "pilot001"
            return {
                "id": job_id, "status": "processing", "error": None,
                "spent_cost_usd": 0.42, "reserved_cost_usd": 0.28,
                "max_cost_usd": 1.6, "attempts": 1, "max_attempts": 3,
                "lease_expires_at": now, "updated_at": now, "checkpoint": {},
                "result": {"title": payload["title"], "script": {"secret": True},
                           "video_url": "https://private.example/video.mp4"},
            }

        def events(self, job_id, after, limit):
            assert job_id == "pilot001"
            assert (after, limit) in {(0, 1000), (1, 500)}
            events = [
                {"seq": 1, "event_type": "lease", "data": "Claimed by secret-worker",
                 "created_at": now.isoformat()},
                {"seq": 2, "event_type": "stage_completed", "data": "tts:hash-one",
                 "created_at": now.isoformat()},
                {"seq": 3, "event_type": "stage_completed", "data": "image:hash-two",
                 "created_at": now.isoformat()},
                {"seq": 4, "event_type": "stage_retry", "data": "motion:hash-three",
                 "details": {"error": "Bearer super-secret"},
                 "created_at": now.isoformat()},
                {"seq": 5, "event_type": "log",
                 "data": "Saved /tmp/private/file at https://provider.example/x token=secret",
                 "created_at": now.isoformat()},
            ]
            return [event for event in events if event["seq"] > after][:limit]

    monkeypatch.setattr(studio, "_durable_components", lambda: (Store(), object()))
    monkeypatch.setattr(db, "finished_video_get", lambda job_id: {
        "id": job_id, "title": payload["title"], "status": "degraded",
        "video_url": "https://private.example/video.mp4",
        "download_url": "https://private.example/download",
        "metadata": {"actual_cost": 1.39, "duration_sec": 45.2,
                     "rendered_contract_score": 91, "internal_path": "/tmp/secret"},
    })

    async def run():
        transport = httpx.ASGITransport(app=studio.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                f"/api/agent/actions/{ACTION_ID}/public-status?after=1")
            assert response.status_code == 200, response.text
            status = response.json()
            assert status["job"]["id"] == "pilot001"
            assert status["job"]["spent_cost_usd"] == 0.42
            assert status["job"]["result"] == {
                "title": payload["title"],
            }
            assert status["progress"]["narration_total"] == 5
            assert status["progress"]["images_total"] == 18
            assert status["progress"]["motion_total"] == 2
            assert status["progress"]["narration_completed"] == 1
            assert status["progress"]["images_completed"] == 1
            assert status["next_event_seq"] == 5
            assert [event["seq"] for event in status["events"]] == [2, 3, 4, 5]
            serialized = json.dumps(status)
            for secret in ("secret-worker", "super-secret", "/tmp/private/file",
                           "https://provider.example/x", "https://private.example/video.mp4",
                           "internal_path", "/tmp/secret"):
                assert secret not in serialized
            assert status["events"][-1]["data"] == "Render progress updated"
            assert status["finished_video"]["player_path"] == (
                "/api/finished/pilot001/artifact/video")
            assert status["finished_video"]["download_path"].endswith("?download=true")

    anyio.run(run)


def test_agent_action_pages_describe_the_narrow_confirmation_boundary():
    request_html = (ROOT / "static" / "agent_action_request.html").read_text()
    approval_html = (ROOT / "static" / "agent_actions.html").read_text()
    assert "Create non-spending request" in request_html
    assert "Execute approved pilot" in request_html
    assert "first-45" in request_html
    assert "A pilot and its remaining film are separate actions" in approval_html
    assert "Approve & render remaining film" in approval_html
    assert "Authorization SHA-256" in approval_html
    assert "Hard ceiling" in approval_html
    assert "Durable worker events will appear here" in approval_html
    assert "/public-status?after=" in approval_html
    assert "player_path" in approval_html
    assert "history.replaceState" in approval_html
