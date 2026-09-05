"""Provider readiness must fail early without representing configuration as quota."""

import json

import anyio
import httpx
import pytest

import app as api
import explainer_pipeline as pipeline
import provider_readiness


@pytest.fixture
def configured_keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-credential")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-credential")
    monkeypatch.delenv("SCRIPT_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_SCRIPT_MODEL", raising=False)

    def no_provider_calls(*args, **kwargs):
        raise AssertionError("Readiness must not create a provider client")

    monkeypatch.setattr(pipeline, "_anthropic_native", no_provider_calls)
    monkeypatch.setattr(pipeline, "_claude", no_provider_calls)
    monkeypatch.setattr(pipeline, "_openai", no_provider_calls)


@pytest.mark.parametrize("provider,missing_key,unconfigured", [
    ("anthropic", "ANTHROPIC_API_KEY", {"research", "script", "visual_qa"}),
    ("anthropic", "OPENAI_API_KEY", {"images", "narration", "word_timing"}),
    ("openai", "ANTHROPIC_API_KEY", {"research"}),
    ("openai", "OPENAI_API_KEY", {"script", "visual_qa", "images", "narration", "word_timing"}),
])
def test_missing_credentials_block_actual_stages(
    monkeypatch, configured_keys, provider, missing_key, unconfigured,
):
    monkeypatch.setenv("SCRIPT_PROVIDER", provider)
    monkeypatch.setenv(missing_key, "   ")
    result = provider_readiness.illustrated_provider_readiness()

    assert not result["configured"]
    assert result["missing_configuration"] == [missing_key]
    assert {name for name, stage in result["stages"].items()
            if not stage["configured"]} == unconfigured


def test_present_keys_are_configuration_not_access_or_quota(configured_keys, monkeypatch):
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    result = provider_readiness.illustrated_provider_readiness()

    assert result["configured"]
    assert result["readiness_scope"] == "configuration_only"
    assert result["generation_verified"] is False
    assert result["model_access"] == result["quota"] == "not_checked"
    assert all(stage["model_access"] == stage["quota"] == "not_checked"
               for stage in result["stages"].values())
    serialized = json.dumps(result)
    assert "test-anthropic-credential" not in serialized
    assert "test-openai-credential" not in serialized


def test_manifest_tracks_actual_models_and_script_options(configured_keys, monkeypatch):
    monkeypatch.setenv("SCRIPT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_SCRIPT_MODEL", "selected-script-model")
    monkeypatch.setenv("OPENAI_SCRIPT_REASONING_EFFORT", "medium")
    monkeypatch.setenv("OPENAI_SCRIPT_REASONING_HEADROOM", "4321")
    monkeypatch.setattr(pipeline, "ANTHROPIC_MODEL", "selected-research-model")
    monkeypatch.setattr(pipeline, "IMAGE_MODEL", "selected-image-model")
    monkeypatch.setattr(pipeline, "TTS_MODEL", "selected-speech-model")
    monkeypatch.setattr(pipeline, "TRANSCRIPTION_MODEL", "selected-timing-model")

    manifest = provider_readiness.illustrated_provider_manifest()
    assert manifest["research"] == {"provider": "anthropic", "model": "selected-research-model"}
    assert manifest["script"] == manifest["visual_qa"] == {
        "provider": "openai", "model": "selected-script-model",
        "reasoning_effort": "medium", "reasoning_headroom": 4321,
    }
    assert manifest["images"]["model"] == "selected-image-model"
    assert manifest["narration"]["model"] == "selected-speech-model"
    assert manifest["word_timing"]["model"] == "selected-timing-model"
    assert "credential" not in json.dumps(manifest)


def test_empty_selected_model_blocks_configuration(configured_keys, monkeypatch):
    monkeypatch.setenv("SCRIPT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_SCRIPT_MODEL", "  ")
    result = provider_readiness.illustrated_provider_readiness()
    assert not result["configured"]
    assert result["missing_configuration"] == ["script.model", "visual_qa.model"]


def test_unknown_script_choice_reports_actual_fallback(configured_keys, monkeypatch):
    monkeypatch.setenv("SCRIPT_PROVIDER", "unrecognized-value")
    result = provider_readiness.illustrated_provider_readiness()
    assert result["stages"]["script"]["provider"] == "anthropic"
    assert result["warnings"]
    assert "unrecognized-value" not in json.dumps(result)


def test_renderer_import_failure_is_blocked_and_sanitized(monkeypatch):
    def invalid_config():
        raise ValueError("private deployment data")

    monkeypatch.setattr(provider_readiness, "illustrated_provider_manifest", invalid_config)
    result = provider_readiness.illustrated_provider_readiness()
    assert not result["configured"]
    assert result["missing_configuration"] == ["illustrated_pipeline"]
    assert result["pipeline_error"] == "ValueError"
    assert "private deployment data" not in json.dumps(result)


def test_readiness_endpoint_requires_providers_and_keeps_verification_honest(
    configured_keys, monkeypatch,
):
    monkeypatch.setattr(api.artifact_store, "readiness", lambda: {
        "ready": True, "blob": True, "database": True,
    })
    monkeypatch.setattr(api.media_binaries, "preflight", lambda: {"ready": True})
    monkeypatch.setattr(api.private_access, "auth_configured", lambda: True)
    monkeypatch.setattr(api.private_access, "auth_required", lambda: False)
    monkeypatch.setattr(api, "_durable_execution_required", lambda: False)
    monkeypatch.delenv("OPENAI_API_KEY")

    async def run():
        transport = httpx.ASGITransport(app=api.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            missing = await client.get("/api/production-readiness")
            assert missing.status_code == 200
            assert missing.json()["infrastructure_ready"] is True
            assert missing.json()["ready"] is False
            assert missing.json()["checks"]["illustrated_providers"] is False

            monkeypatch.setenv("OPENAI_API_KEY", "test-restored-credential")
            present = (await client.get("/api/production-readiness")).json()
            assert present["ready"] is True
            assert present["readiness_scope"] == "configuration_only"
            assert present["generation_verified"] is False
            assert present["providers"]["illustrated"]["quota"] == "not_checked"
            assert "test-restored-credential" not in json.dumps(present)

            monkeypatch.setattr(api.media_binaries, "preflight", lambda: {"ready": False})
            unavailable = (await client.get("/api/production-readiness")).json()
            assert unavailable["ready"] is False
            assert unavailable["infrastructure_ready"] is False

    anyio.run(run)
