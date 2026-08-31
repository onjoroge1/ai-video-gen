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
from PIL import Image


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
            "asset_prompt": f"Evidence-bearing master {index + 1}",
            "transformation": "slow push",
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
            "pilot_min_unique_master_assets": 15,
            "min_shot_sec": 1.25,
            "max_unchanged_hold_sec": 3.0,
            "max_consecutive_still_asset_sec": 3.0,
            "full_motion_duration_sec": 5.0,
            "full_motion_duration_tolerance_sec": 0.25,
            "frontloaded_motion_count": 0,
            "frontloaded_motion_window_sec": 15.0,
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
    assert report["pilot_unique_master_assets"] == 15
    assert report["max_consecutive_still_asset_sec"] == 3.0


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
    payload["acceptance"]["pilot_min_unique_master_assets"] = 1
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


def test_reused_master_requires_explicit_per_shot_transformations():
    payload = _valid_spec()
    payload["shots"][1]["asset_key"] = payload["shots"][0]["asset_key"]
    payload["shots"][1]["asset_prompt"] = payload["shots"][0]["asset_prompt"]
    payload["shots"][1]["transformation"] = ""

    report = dl.validate_directed_spec(payload)
    assert "asset_reuse_transformation_missing" in {
        issue["code"] for issue in report["issues"]}


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


def test_authored_hippo_v4_is_valid_fast_varied_and_inside_the_pilot_cap():
    import json

    with open(ROOT / "spec" / "hippo_illustrated_story_v4.json", encoding="utf-8") as handle:
        payload = json.load(handle)
    report = dl.validate_directed_spec(payload)

    assert report["valid"] is True
    assert report["shot_count"] == 18
    assert report["pilot_unique_master_assets"] == 18
    assert report["max_consecutive_still_asset_sec"] <= 3.0
    assert report["frontloaded_motion_assets"] == 2
    motion = [shot for shot in payload["shots"] if shot["mode"] == "Full motion"]
    assert [shot["end_sec"] - shot["start_sec"] for shot in motion] == [5.0, 5.0]
    assert report["evidence_coverage_pct"] == 100.0
    assert report["planned_bolt_appearances"] == 2
    assert report["pilot_cost_estimate"]["estimated_total_usd"] < 2.0


def test_source_image_cadence_counts_reframes_as_one_long_hold():
    payload = _valid_spec()
    for index in range(3):
        payload["shots"][index]["asset_key"] = "same-opening-master"
        payload["shots"][index]["asset_prompt"] = "One unchanged opening composition"
        payload["shots"][index]["transformation"] = f"reframe {index + 1}"
    payload["acceptance"]["pilot_min_unique_master_assets"] = 1

    report = dl.validate_directed_spec(payload)
    codes = {issue["code"] for issue in report["issues"]}

    assert report["max_consecutive_still_asset_sec"] == 9.0
    assert "consecutive_still_asset_too_long" in codes


def test_new_asset_keys_cannot_disguise_duplicate_compositions():
    payload = _valid_spec()
    payload["shots"][1]["asset_prompt"] = payload["shots"][0]["asset_prompt"]

    report = dl.validate_directed_spec(payload)

    assert "duplicate_master_composition" in {
        issue["code"] for issue in report["issues"]}


def test_declared_motion_is_five_seconds_and_frontloaded():
    payload = _valid_spec()
    payload["shots"][10]["mode"] = "Full motion"
    payload["acceptance"]["frontloaded_motion_count"] = 1

    report = dl.validate_directed_spec(payload)
    codes = {issue["code"] for issue in report["issues"]}

    assert "full_motion_duration_mismatch" in codes
    assert "frontloaded_motion_missing" in codes


def test_rendered_cadence_uses_actual_holds_and_breaks_runs_on_motion():
    shots = [
        {"shot_id": "a", "asset_key": "same", "mode": "Still"},
        {"shot_id": "b", "asset_key": "same", "mode": "Still"},
        {"shot_id": "c", "asset_key": "same", "mode": "Full motion"},
        {"shot_id": "d", "asset_key": "same", "mode": "Still"},
    ]

    cadence = spec_pilot._actual_source_cadence(shots, [2.0, 2.0, 5.0, 2.5])

    assert cadence["max_consecutive_still_asset_sec"] == 4.0
    assert cadence["motion_starts_sec"] == [4.0]
    assert cadence["motion_durations_sec"] == [5.0]
    assert [run["duration_sec"] for run in cadence["still_asset_runs"]] == [4.0, 2.5]


def test_pre_v4_hippo_specs_fail_the_new_source_cadence_contract():
    import json

    for filename in ("hippo_bacon_directed_v1.json", "hippo_illustrated_story_v3.json"):
        with open(ROOT / "spec" / filename, encoding="utf-8") as handle:
            report = dl.validate_directed_spec(json.load(handle))
        codes = {issue["code"] for issue in report["issues"]}
        assert report["valid"] is False
        assert "consecutive_still_asset_too_long" in codes
        assert "full_motion_duration_mismatch" in codes


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


def test_exact_directed_text_is_composited_after_image_generation(tmp_path):
    source = tmp_path / "master.jpg"
    output = tmp_path / "shot.jpg"
    Image.new("RGB", (960, 540), (80, 100, 120)).save(source)

    spec_pilot._compose_directed_overlays(
        str(source), str(output), overlay_text="LAKE COW BACON",
        world_label="COUNTERFACTUAL — ALTERNATE 2026")

    assert output.is_file()
    assert output.read_bytes() != source.read_bytes()


def test_project_asset_reference_is_verified_before_paid_calls(tmp_path):
    payload = _valid_spec()
    bolt = ROOT / "assets" / "mascot" / "bolt.png"
    import hashlib
    payload["references"] = [{
        "reference_id": "portrait", "uri": "asset://mascot/bolt.png",
        "sha256": hashlib.sha256(bolt.read_bytes()).hexdigest(),
        "mime_type": "image/png", "license": "project-owned",
        "origin": "ReelForge mascot",
    }]
    spec = dl.DirectedLongformSpec.model_validate(payload)

    resolved = spec_pilot._materialize_references(spec, tmp_path)

    assert Path(resolved["portrait"]).read_bytes() == bolt.read_bytes()


def test_renderer_measures_audio_before_any_visual_generation():
    source = inspect.getsource(spec_pilot.render_pilot)

    assert source.index("measured pilot narration") < source.index("_generate_shot_image")
    assert 'world = shot["world_id"]' in source
    assert '"-movflags", "+faststart"' in source
    assert '"-f", "concat", "-safe", "0", "-i", str(concat_list)' in source
    assert "silent_video" not in source
    assert "for clip in clips" in source


def test_remaining_film_streams_and_releases_source_images():
    source = inspect.getsource(spec_pilot.render_pilot)

    assert "streaming_render" in source
    assert "flush_stream()" in source
    assert "Path(path).unlink(missing_ok=True)" in source
    assert '_render_shot(path, hold, motion, clip, preset="veryfast", crf=23)' in source
    assert "compact_stream_clips(force=True)" in source
    assert "clips[:] = stream_segments" in source
    assert source.index("flush_stream()", source.index("for order, shot in enumerate(shots)")) \
        < source.index("pending_stream = {", source.index("for order, shot in enumerate(shots)"))


def test_generated_jpg_payload_is_normalized_to_jpeg(tmp_path):
    from explainer_pipeline import _normalize_generated_image

    path = tmp_path / "provider-output.jpg"
    Image.new("RGBA", (320, 180), (20, 40, 60, 128)).save(path, "PNG")

    _normalize_generated_image(str(path))

    assert path.read_bytes().startswith(bytes((0xFF, 0xD8, 0xFF)))
    with Image.open(path) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"


def test_generated_jpg_is_compacted_for_bounded_serverless_workspace(tmp_path):
    from explainer_pipeline import _normalize_generated_image

    path = tmp_path / "long-film-master.jpg"
    Image.effect_noise((1536, 1024), 80).convert("RGB").save(path, "PNG")
    provider_size = path.stat().st_size

    _normalize_generated_image(str(path))

    assert path.stat().st_size < provider_size * 0.45
    source = inspect.getsource(__import__("explainer_pipeline").generate_image)
    assert source.index("_normalize_generated_image(output_path)") < source.index(
        "runtime.paid_file")


def test_failed_optional_motion_event_needs_no_cache_path():
    source = inspect.getsource(spec_pilot.render_pilot)

    assert 'if event.get("cache_path")' in source


def test_directed_modules_are_in_the_deployable_module_list():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for module in ("directed_longform", "spec_pilot", "user_directed"):
        assert f'"{module}"' in pyproject


def test_web_ui_exposes_free_validation_before_paid_processing():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    approvals = (ROOT / "static" / "agent_actions.html").read_text(encoding="utf-8")

    assert "User-directed longform JSON" in html
    assert "/api/explainer/directed/validate" in html
    assert "/api/explainer/directed/process" in html
    assert "/api/explainer/directed/template" in html
    assert "Download fillable JSON" in html
    assert "Validate JSON — free" in html
    assert "directed-paid-authorize" in html
    assert "hippo-v4" in approvals
    assert "hippo_illustrated_story_v4" in approvals


def test_downloadable_template_is_complete_but_fail_closed_until_filled():
    template = dl.starter_template()
    report = dl.validate_directed_spec(template)

    assert len(template["shots"]) == 15
    assert [shot["end_sec"] - shot["start_sec"] for shot in template["shots"][:2]] == [5.0, 5.0]
    assert template["acceptance"]["pilot_min_unique_master_assets"] == 15
    assert template["acceptance"]["frontloaded_motion_count"] == 2
    assert report["valid"] is False
    assert "unresolved_source_license" in {issue["code"] for issue in report["issues"]}

    async def run():
        transport = httpx.ASGITransport(app=studio.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/explainer/directed/template")
            assert response.status_code == 200
            assert "attachment" in response.headers["content-disposition"]
            assert response.json()["schema_version"] == dl.SCHEMA_VERSION

    anyio.run(run)


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
