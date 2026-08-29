import copy
import inspect
from pathlib import Path

import anyio
import httpx
import pytest

import app as studio
import directed_longform as dl
import spec_pilot
import user_directed


ROOT = Path(__file__).resolve().parents[1]


def _valid_spec():
    shots = []
    for index in range(15):
        shots.append({
            "shot_id": f"shot_{index + 1:03d}",
            "start_sec": index * 3.0,
            "end_sec": (index + 1) * 3.0,
            "visual": f"Evidence-bearing visual {index + 1}",
            "mode": "Useful mascot beat" if index == 3 else "Still + camera path",
            "world_id": "history",
            "scene_id": "scene_001",
            "asset_key": f"master_{index + 1:03d}",
            "claim_ids": ["F01"] if index == 5 else [],
            "reference_ids": ["portrait"] if index == 5 else [],
            "overlay_text": "",
            "labels": ["useful_bolt"] if index == 3 else [],
        })
    return {
        "schema_version": dl.SCHEMA_VERSION,
        "project_id": "test-directed",
        "title": "A Directed Test",
        "negative_prompt": "no fake text",
        "target": {
            "duration_sec": 45.0,
            "pilot_end_sec": 45.0,
            "format": "landscape",
            "voice": "echo",
            "max_cost_usd": 5.0,
        },
        "acceptance": {
            "runtime_tolerance_sec": 2.0,
            "pilot_runtime_min_sec": 43.0,
            "pilot_runtime_max_sec": 47.0,
            "pilot_min_visual_states": 15,
            "min_shot_sec": 1.25,
            "max_unchanged_hold_sec": 5.0,
            "max_unique_master_assets": 60,
            "min_useful_bolt_appearances": 1,
            "max_bolt_appearances": 3,
            "evidence_coverage_pct": 100.0,
            "automatic_grade_min": 90.0,
            "editorial_grade_min": 85.0,
        },
        "worlds": [{
            "world_id": "history", "start_sec": 0.0, "end_sec": 45.0,
            "base_prompt": "restrained historical documentary", "on_screen_label": "REENACTMENT",
        }],
        "narration": [{
            "scene_id": "scene_001", "start_sec": 0.0, "end_sec": 45.0,
            "narration": "A complete operator-authored narration for the measured pilot.",
            "world_id": "history", "story_role": "hook", "claim_ids": ["F01"],
        }],
        "shots": shots,
        "evidence": [{
            "claim_id": "F01", "claim": "A sourced fact", "source_uri": "https://example.com/fact",
            "qualification": "Use only in this limited form", "license": "editorial citation",
        }],
        "references": [{
            "reference_id": "portrait", "uri": "https://example.com/portrait.jpg",
            "sha256": "a" * 64, "mime_type": "image/jpeg", "license": "public domain",
            "origin": "Example archive",
        }],
        "prohibited_claims": ["Do not invent a near-passage vote."],
    }


def test_valid_spec_returns_an_immutable_hash_and_cost_before_processing():
    report = dl.validate_directed_spec(_valid_spec())

    assert report["valid"] is True
    assert len(report["spec_sha256"]) == 64
    assert report["pilot_visual_states"] == 15
    assert report["cost_estimate"]["estimated_total_usd"] > 0
    assert report["cost_estimate"]["unique_master_assets"] == 15
    assert report["pilot_cost_estimate"]["shot_count"] == 15


def test_paid_processing_requires_the_exact_validated_hash_and_explicit_authorization():
    payload = _valid_spec()
    report = dl.validate_directed_spec(payload)

    with pytest.raises(dl.DirectedValidationError, match="authorization"):
        dl.authorize_processing(
            payload, expected_sha256=report["spec_sha256"], authorize_paid=False)
    with pytest.raises(dl.DirectedValidationError, match="hash"):
        dl.authorize_processing(payload, expected_sha256="0" * 64, authorize_paid=True)

    edited = copy.deepcopy(payload)
    edited["title"] = "Edited after validation"
    with pytest.raises(dl.DirectedValidationError, match="hash"):
        dl.authorize_processing(
            edited, expected_sha256=report["spec_sha256"], authorize_paid=True)


def test_timeline_evidence_license_and_asset_reuse_fail_closed():
    payload = _valid_spec()
    payload["shots"][1]["start_sec"] += 0.5
    payload["evidence"][0]["license"] = "unresolved"
    payload["acceptance"]["max_unique_master_assets"] = 3

    report = dl.validate_directed_spec(payload)
    codes = {issue["code"] for issue in report["issues"]}

    assert report["valid"] is False
    assert "shots_timeline_gap" in codes
    assert "unresolved_source_license" in codes
    assert "too_many_unique_master_assets" in codes


def test_one_asset_key_cannot_hide_different_prompts():
    payload = _valid_spec()
    payload["shots"][1]["asset_key"] = payload["shots"][0]["asset_key"]

    report = dl.validate_directed_spec(payload)

    assert "asset_key_conflict" in {issue["code"] for issue in report["issues"]}


def test_world_and_scene_must_match_their_timeline_positions():
    payload = _valid_spec()
    payload["worlds"][0]["end_sec"] = 42.0
    report = dl.validate_directed_spec(payload)
    assert "world_timeline_mismatch" in {issue["code"] for issue in report["issues"]}


def test_hippo_markdown_compiles_all_shots_and_routes_later_worlds_correctly():
    payload = user_directed.compile_directed_spec(
        ROOT / "spec" / "hippo_bacon_video_generation_spec.md")

    assert len(payload["narration"]) == 43
    assert len(payload["shots"]) == 181
    assert payload["target"]["duration_sec"] == 515
    by_start = {shot["start_sec"]: shot for shot in payload["shots"]}
    assert by_start[325]["world_id"] == "modern_evidence"
    assert by_start[465]["world_id"] == "alternate_2026"
    assert len(payload["evidence"]) == 11


def test_hippo_contract_reports_missing_editorial_work_instead_of_spending():
    payload = user_directed.compile_directed_spec(
        ROOT / "spec" / "hippo_bacon_video_generation_spec.md")
    report = dl.validate_directed_spec(payload)
    codes = {issue["code"] for issue in report["issues"]}

    assert report["valid"] is False
    assert "too_many_unique_master_assets" in codes
    assert "evidence_coverage" in codes
    assert "unresolved_source_license" in codes
    assert "bolt_appearance_plan" in codes


def test_motion_cache_identity_includes_image_bytes_prompt_and_provider(tmp_path):
    image = tmp_path / "source.jpg"
    image.write_bytes(b"one image")
    shot = {"visual": "camera crosses the plants", "mode": "Full motion"}

    first = spec_pilot._motion_cache_path(str(image), shot, 3.0, str(tmp_path / "shot.mp4"))
    changed_prompt = spec_pilot._motion_cache_path(
        str(image), {**shot, "visual": "camera pulls back"}, 3.0, str(tmp_path / "shot.mp4"))
    image.write_bytes(b"different image")
    changed_image = spec_pilot._motion_cache_path(
        str(image), shot, 3.0, str(tmp_path / "shot.mp4"))

    assert first != changed_prompt
    assert first != changed_image
    assert first.name.endswith(".src.mp4")


def test_identical_motion_requests_share_cache_across_shot_filenames(tmp_path):
    image = tmp_path / "source.jpg"
    image.write_bytes(b"one image")
    shot = {"visual": "camera crosses the plants", "mode": "Full motion"}

    first = spec_pilot._motion_cache_path(
        str(image), shot, 3.0, str(tmp_path / "shot_01.mp4"))
    second = spec_pilot._motion_cache_path(
        str(image), shot, 3.0, str(tmp_path / "shot_12.mp4"))

    assert first == second


def test_renderer_measures_audio_before_any_visual_generation():
    source = inspect.getsource(spec_pilot.render_pilot)

    assert source.index("measured pilot narration") < source.index("_generate_shot_image")
    assert 'world = shot["world_id"]' in source
    assert '"-movflags", "+faststart"' in source


def test_directed_modules_are_in_the_deployable_module_list():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for module in ("directed_longform", "spec_pilot", "user_directed"):
        assert f'"{module}"' in pyproject


def test_web_ui_exposes_free_validation_before_paid_processing():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

    assert "User-directed longform JSON" in html
    assert "/api/explainer/directed/validate" in html
    assert "/api/explainer/directed/process" in html
    assert "Validate JSON — free" in html
    assert "directed-paid-authorize" in html


def test_validate_route_is_free_and_process_requires_paid_authorization():
    payload = _valid_spec()

    async def run():
        transport = httpx.ASGITransport(app=studio.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            validated = await client.post(
                "/api/explainer/directed/validate", json={"spec": payload})
            assert validated.status_code == 200
            report = validated.json()
            assert report["valid"] is True

            refused = await client.post("/api/explainer/directed/process", json={
                "spec": payload, "spec_sha256": report["spec_sha256"],
                "authorize_paid": False,
            })
            assert refused.status_code == 409
            assert "authorization" in refused.text

    anyio.run(run)


def test_process_route_queues_only_the_hash_bound_directed_pilot(monkeypatch):
    payload = _valid_spec()
    report = dl.validate_directed_spec(payload)
    queued = []

    class Store:
        def enqueue(self, **kwargs):
            queued.append(kwargs)
            return {"id": kwargs["job_id"], "status": "queued", "result": {},
                    "spent_cost_usd": 0, "max_cost_usd": kwargs["max_cost_usd"],
                    "attempts": 0, "checkpoint": {}}

    monkeypatch.setenv("DURABLE_EXECUTION", "1")
    monkeypatch.setattr(studio, "_require_render_storage", lambda: None)
    monkeypatch.setattr(studio, "_sweep_old_temp", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(studio, "_durable_components", lambda: (Store(), object()))

    async def run():
        transport = httpx.ASGITransport(app=studio.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/explainer/directed/process", json={
                "spec": payload, "spec_sha256": report["spec_sha256"],
                "authorize_paid": True,
            })
            assert response.status_code == 200
            body = response.json()
            assert body["scope"] == "first-45-pilot"
            assert body["spec_sha256"] == report["spec_sha256"]
            assert body["estimated_cost"] == report["pilot_cost_estimate"]

    anyio.run(run)
    assert len(queued) == 1
    request = queued[0]["request"]
    assert request["directed_spec_sha256"] == report["spec_sha256"]
    assert request["directed_paid_authorized"] is True
    assert request["duration_sec"] == 45


def test_generic_generate_route_cannot_inject_directed_paid_fields():
    async def run():
        transport = httpx.ASGITransport(app=studio.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/explainer/generate", json={
                "question": "bypass", "directed_spec": _valid_spec(),
                "directed_paid_authorized": True,
            })
            assert response.status_code == 403

    anyio.run(run)
