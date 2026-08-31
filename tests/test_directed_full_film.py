import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anyio
import httpx
import pytest

import agent_actions
import app as studio
import directed_full_film as dff
import directed_longform as dl


ROOT = Path(__file__).resolve().parents[1]
PILOT = json.loads((ROOT / "spec" / "hippo_illustrated_story_v4.json").read_text())
FULL = json.loads((ROOT / "spec" / "hippo_illustrated_story_v4_full_5m.json").read_text())


def _envelope():
    return dff.build_envelope(
        full_spec=FULL,
        parent_spec=PILOT,
        parent_action_id="act_" + "1" * 32,
        parent_job_id="51f926ab",
        parent_video_sha256="a" * 64,
    )


def test_five_minute_bundle_preserves_v4_and_prices_only_the_remaining_window():
    envelope, report = _envelope()
    assert report["valid"] is True
    assert report["duration_sec"] == 300.0
    assert report["shot_count"] == 117
    assert report["remaining_cost_estimate"]["estimated_total_usd"] == 5.4183
    assert envelope["promotion"]["scope"] == "remaining-45-to-300"
    assert envelope["promotion"]["pilot_reuse_required"] is True
    dff.validate_opening_identity(PILOT, FULL)


def test_opening_or_parent_hash_mutation_cannot_cross_the_paid_boundary():
    changed = copy.deepcopy(FULL)
    changed["shots"][0]["visual"] = "different opening"
    with pytest.raises(dff.DirectedFullFilmError, match="accepted opening shots"):
        dff.build_envelope(
            full_spec=changed, parent_spec=PILOT,
            parent_action_id="act_" + "1" * 32, parent_job_id="51f926ab",
            parent_video_sha256="a" * 64)

    envelope, report = _envelope()
    envelope["promotion"]["parent_video_sha256"] = "b" * 64
    with pytest.raises(dff.DirectedFullFilmError, match="authorization hash changed"):
        dff.validate_envelope(envelope, expected_sha256=report["authorization_sha256"])


def test_remaining_renderer_never_requests_the_pilot_window(monkeypatch, tmp_path):
    parent = tmp_path / "pilot.mp4"
    parent.write_bytes(b"accepted-pilot")
    envelope, report = dff.build_envelope(
        full_spec=FULL, parent_spec=PILOT,
        parent_action_id="act_" + "1" * 32, parent_job_id="51f926ab",
        parent_video_sha256=dff.file_sha256(parent))
    called = {}

    def render(spec, out_dir, **kwargs):
        called["window"] = kwargs["window"]
        segment = Path(out_dir) / "segment.mp4"
        segment.write_bytes(b"remaining")
        for name in ("generation_manifest.json", "directed_spec.json", "validation_report.json"):
            (Path(out_dir) / name).write_text("{}")
        return {
            "preview_path": str(segment), "total_cost_usd": 5.0, "shots": 99,
            "animated_shots": 3,
            "generation_manifest_path": str(Path(out_dir) / "generation_manifest.json"),
            "directed_spec_path": str(Path(out_dir) / "directed_spec.json"),
            "validation_report_path": str(Path(out_dir) / "validation_report.json"),
        }

    def ffmpeg(args, **_kwargs):
        Path(args[-1]).write_bytes(b"accepted-pilot+remaining")

    monkeypatch.setattr(dff.spec_pilot, "render_pilot", render)
    monkeypatch.setattr(dff.ep, "_run_ffmpeg", ffmpeg)
    monkeypatch.setattr(dff.ep, "_audio_dur", lambda _path: 300.0)
    result = dff.render_remaining(
        envelope=envelope, authorization_hash=report["authorization_sha256"],
        parent_video_path=str(parent), out_dir=str(tmp_path), authorize_paid=True)
    assert called["window"] == (45.0, 300.0)
    assert result["pilot_reused"] is True
    assert result["actual_cost"] == 5.0
    assert result["technical_status"] == "completed"


class _CreateOnlyRepository:
    def __init__(self):
        self.action = None

    def get(self, _action_id):
        return None

    def reusable_for_spec(self, *_args):
        return None

    def create(self, **values):
        now = datetime.now(timezone.utc)
        self.action = {
            "action_id": "act_" + "9" * 32,
            "status": "pending", "created_at": now,
            "expires_at": now + timedelta(minutes=15), "approved_at": None,
            "job_id": "", "error": "", **values,
        }
        return copy.deepcopy(self.action)


def test_full_action_creation_is_nonspending_and_displays_parent_boundary(monkeypatch):
    repository = _CreateOnlyRepository()
    monkeypatch.setattr(agent_actions, "repository", lambda: repository)
    monkeypatch.setattr(studio, "_directed_parent_pilot_context", lambda *_args: {
        "spec": PILOT,
        "video_artifact": {"sha256": "a" * 64},
        "grading": {"hard_failures": [], "automated_status": "UNSCORED_JUDGE_UNAVAILABLE"},
    })

    async def run():
        transport = httpx.ASGITransport(app=studio.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/agent/actions", json={
                "operation": "directed_full_film",
                "bundled_spec_id": "hippo_illustrated_story_v4_full_5m",
                "parent_action_id": "act_" + "1" * 32,
                "parent_job_id": "51f926ab",
                "cost_ceiling_usd": 6.0,
            })
            assert response.status_code == 200, response.text
            proposal = response.json()
            assert proposal["scope"] == "remaining-45-to-300"
            assert proposal["parent_job_id"] == "51f926ab"
            assert proposal["pilot_reused"] is True
            assert proposal["estimated_cost_usd"] == 5.4183
            assert proposal["cost_ceiling_usd"] == 6.0
            assert repository.action["job_id"] == ""
            assert repository.action["operation"] == "directed_full_film"

    anyio.run(run)


def test_full_action_surfaces_parent_storage_failure_as_structured_503(monkeypatch):
    def unavailable(*_args):
        raise agent_actions.AgentActionStorageError("Postgres unavailable")

    monkeypatch.setattr(studio, "_directed_parent_pilot_context", unavailable)

    async def run():
        transport = httpx.ASGITransport(app=studio.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/agent/actions", json={
                "operation": "directed_full_film",
                "bundled_spec_id": "hippo_illustrated_story_v4_full_5m",
                "parent_action_id": "act_" + "1" * 32,
                "parent_job_id": "51f926ab",
                "cost_ceiling_usd": 6.0,
            })
            assert response.status_code == 503
            assert response.json()["detail"]["code"] == "AGENT_ACTION_STORAGE_UNAVAILABLE"

    anyio.run(run)


def test_window_estimate_rejects_invalid_boundaries():
    with pytest.raises(dl.DirectedValidationError):
        dl.window_cost_estimate(FULL, 300.0, 45.0)
