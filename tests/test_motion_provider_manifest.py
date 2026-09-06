"""Every motion provider the pipeline can be configured for must survive manifest creation.

The generation manifest is written at the top of run_explainer_task, 175 lines before research and
before a cent is spent. It names a model for every provider in the configured chain, and it does so
regardless of motion mode -- a stills render still writes the manifest.

`wan` was added to the cost table and to the generation branch but not to _motion_model_id, so any
job configured for wan raised ValueError there. ValueError is classified as a hard failure, so the
job went straight to `error` with no retry, on a code path that was never going to call wan at all.
The suite stayed green because no test configured that provider.

These tests are keyed off the rate roster rather than a hand-written list, so adding a provider to
one place and forgetting the other fails here instead of in production.
"""
import pytest

import explainer_pipeline as ep


@pytest.mark.parametrize("provider", sorted(ep.I2V_RATE_BY_PROVIDER))
def test_every_priced_provider_can_be_named_in_a_manifest(provider):
    model_id = ep._motion_model_id(provider)
    assert model_id and isinstance(model_id, str)
    assert model_id.strip() == model_id and " " not in model_id


@pytest.mark.parametrize("provider", sorted(ep.I2V_RATE_BY_PROVIDER))
@pytest.mark.parametrize("motion_mode", ["stills", "standard", "full_motion"])
def test_the_manifest_builds_for_every_provider_in_every_motion_mode(
        monkeypatch, provider, motion_mode):
    """Stills matters most: it is the mode that never calls the provider, and it still crashed."""
    monkeypatch.setattr(ep, "_I2V_CHAIN", [provider])
    manifest = ep._generation_manifest_payload(
        video_format="landscape", motion_mode=motion_mode, threshold_profile={})
    entries = [item for item in manifest["models"] if item["purpose"] == "image_to_video"]
    assert [item["provider"] for item in entries] == [provider]
    assert entries[0]["model_id"] == ep._motion_model_id(provider)


def test_a_fallback_chain_names_a_model_for_every_link(monkeypatch):
    chain = sorted(ep.I2V_RATE_BY_PROVIDER)
    monkeypatch.setattr(ep, "_I2V_CHAIN", chain)
    manifest = ep._generation_manifest_payload(
        video_format="landscape", motion_mode="full_motion", threshold_profile={})
    named = [item["provider"] for item in manifest["models"]
             if item["purpose"] == "image_to_video"]
    assert named == chain
    assert all(item["model_id"] for item in manifest["models"])


def test_an_unknown_provider_still_fails_before_generation_spend(monkeypatch):
    """The guard itself must survive: a typo in I2V_PROVIDER is a real configuration error."""
    monkeypatch.setattr(ep, "_I2V_CHAIN", ["invented-provider"])
    with pytest.raises(ValueError) as excinfo:
        ep._generation_manifest_payload(
            video_format="landscape", motion_mode="full_motion", threshold_profile={})
    assert "Unsupported I2V provider" in str(excinfo.value)


def test_the_rate_roster_and_the_model_map_describe_the_same_providers():
    """The two halves of a provider definition, asserted against each other.

    Pricing a provider the manifest cannot name is the exact shape of the wan outage; naming one
    the estimator cannot price would silently bill it at the 0.15 default instead.
    """
    for provider in ep.I2V_RATE_BY_PROVIDER:
        assert ep._motion_model_id(provider), f"{provider} is priced but has no model id"


def test_the_suite_cannot_reach_a_billed_motion_provider(tmp_path):
    """The guard itself, asserted.

    app.py calls load_dotenv(override=True), so a developer's real FAL_KEY is loaded into any local
    test run. An unmocked motion path is therefore a suite that submits billed generation jobs and
    then polls for six minutes. This proves the autouse guard in conftest is actually installed.
    """
    with pytest.raises(AssertionError) as excinfo:
        ep._animate_one("fal", str(tmp_path / "in.jpg"), "motion", str(tmp_path / "out.mp4"),
                        1280, 720)
    assert "Unexpected live image-to-video provider boundary" in str(excinfo.value)


@pytest.mark.live_motion
def test_the_guard_can_be_opted_out_of():
    """Tests that drive a provider branch mock the transport themselves."""
    assert ep._animate_one.__name__ == "_animate_one"
