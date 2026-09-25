"""The fal.ai endpoint registry: one table, two callers, no Kling body sent to a non-Kling model.

Before fal_models.py, `_animate_one` and the directed-motion adapter each carried Kling's field
names inline. Pointing FAL_MODEL at Seedance or Wan would have submitted `image_url` + `duration`
and nothing else: Seedance would then have billed for the audio track it generates by default, Wan
2.2 would have rejected the missing frame count, and the cost guard would have priced every clip
at Kling's $0.056/s. These tests pin the request body per family, the rate per model, and the
wiring in both callers.
"""
import json

import pytest

import fal_models
import explainer_pipeline as ep
from bolt_seq.providers import directed_video as dv


START, END = "data:image/jpeg;base64,START", "data:image/jpeg;base64,END"


def _body(model, **kw):
    args = dict(prompt="Bolt wobbles and rights himself", image_url=START, seconds=5,
                aspect_ratio="9:16", audio=False)
    args.update(kw)
    return fal_models.build_i2v_body(model, **args)


# ── request families ───────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("endpoint", sorted(fal_models.MODELS))
def test_every_registered_model_builds_a_json_body_with_its_own_start_frame_field(endpoint):
    body = _body(endpoint, end_image_url=END)
    json.dumps(body)                                   # nothing un-serialisable leaks in
    fam = fal_models.MODELS[endpoint]["family"]
    start_field = "start_image_url" if fam == fal_models.KLING_V3 else "image_url"
    assert body[start_field] == START
    assert body["prompt"].startswith("Bolt wobbles")


def test_kling_v3_speaks_start_and_end_image_url_and_forces_audio_off():
    body = _body("kling-3-pro", end_image_url=END, negative_prompt="legs")
    assert body["start_image_url"] == START and body["end_image_url"] == END
    assert body["generate_audio"] is False and body["negative_prompt"] == "legs"
    assert body["duration"] == "5" and "image_url" not in body


def test_kling_v2_speaks_image_url_and_tail_image_url():
    body = _body("kling-2.1-pro", end_image_url=END)
    assert body["image_url"] == START and body["tail_image_url"] == END
    assert "generate_audio" not in body and "resolution" not in body


def test_seedance_two_sends_resolution_aspect_and_audio_off_and_folds_the_negative_prompt():
    body = _body("seedance-2.0", end_image_url=END, negative_prompt="no legs, no feet")
    assert body["image_url"] == START and body["end_image_url"] == END
    assert body["resolution"] == "720p" and body["aspect_ratio"] == "9:16"
    assert body["generate_audio"] is False              # schema default is True and bills
    assert "negative_prompt" not in body                # no such field on Seedance
    assert body["prompt"].endswith("Avoid: no legs, no feet.")


def test_seedance_two_five_never_sends_an_aspect_ratio_because_its_schema_only_takes_auto():
    body = _body("seedance-2.5", aspect_ratio="9:16")
    assert "aspect_ratio" not in body
    assert body["duration"] == "5" and body["resolution"] == "720p"


def test_seedance_one_pro_pins_the_camera_and_has_no_audio_flag():
    body = _body("seedance-1-pro")
    assert body["camera_fixed"] is False and "generate_audio" not in body


def test_wan_two_six_takes_a_start_frame_only_and_keeps_the_prompt_literal():
    body = _body("wan-2.6", end_image_url=END, negative_prompt="text")
    assert body["image_url"] == START and "end_image_url" not in body
    assert body["enable_prompt_expansion"] is False and body["multi_shots"] is False
    assert body["negative_prompt"] == "text" and body["resolution"] == "720p"


def test_wan_two_two_counts_frames_at_sixteen_fps_instead_of_seconds():
    body = _body("wan-2.2-a14b", seconds=5, end_image_url=END)
    assert body["num_frames"] == 81 and body["frames_per_second"] == 16
    assert body["end_image_url"] == END and body["aspect_ratio"] == "9:16"
    assert "duration" not in body
    assert _body("wan-2.2-a14b", seconds=30)["num_frames"] == 161        # schema ceiling


def test_an_unregistered_endpoint_gets_the_legacy_kling_body_and_the_legacy_rate():
    """Any FAL_MODEL string a deployment already has keeps working exactly as before."""
    body = _body("fal-ai/some/new/image-to-video", end_image_url=END)
    assert body == {"prompt": "Bolt wobbles and rights himself", "image_url": START,
                    "duration": "5", "tail_image_url": END}
    assert fal_models.rate_usd_per_sec("fal-ai/some/new/image-to-video") == 0.056


# ── durations snap to what each endpoint accepts ───────────────────────────────────────────────

@pytest.mark.parametrize("model, seconds, expected", [
    ("kling-2.1-standard", 5.3, 10),     # Kling: 5 or 10, never shorter than asked
    ("wan-2.6", 6, 10),                  # Wan 2.6: 5 / 10 / 15
    ("wan-2.6", 16, 15),                 # ...capped at the schema maximum
    ("seedance-2.0", 5.3, 6),            # Seedance: integer seconds 4-15
    ("seedance-2.0", 2, 4),
    ("seedance-2.5", 24, 24),            # 4-30
    ("seedance-1-pro", 3, 3),            # 2-12
])
def test_durations_snap_up_to_the_nearest_value_the_endpoint_accepts(model, seconds, expected):
    assert fal_models.snap_duration(model, seconds) == expected


# ── rates ──────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("endpoint", sorted(fal_models.MODELS))
def test_every_registered_model_has_a_positive_rate_at_every_resolution_it_offers(endpoint):
    m = fal_models.MODELS[endpoint]
    for res in (m["resolutions"] or (None,)):
        assert fal_models.rate_usd_per_sec(endpoint, res) > 0, (endpoint, res)


def test_seedance_is_priced_by_resolution_and_an_unknown_resolution_never_under_reserves():
    assert fal_models.rate_usd_per_sec("seedance-2.0", "480p") < fal_models.rate_usd_per_sec("seedance-2.0", "720p")
    assert fal_models.rate_usd_per_sec("seedance-2.0", "8k") == max(
        fal_models.MODELS[fal_models.resolve("seedance-2.0")]["usd_per_sec"].values())


def test_a_clip_estimate_uses_the_snapped_duration_not_the_requested_one():
    assert fal_models.estimate_clip_usd("wan-2.6", 6) == pytest.approx(10 * 0.10)


# ── explainer pipeline wiring ──────────────────────────────────────────────────────────────────

def test_the_pipeline_prices_provider_fal_from_the_configured_model():
    assert ep.I2V_RATE_BY_PROVIDER["fal"] == fal_models.rate_usd_per_sec(ep._FAL_MODEL, ep._FAL_I2V_RESOLUTION)
    assert fal_models.is_registered(ep._FAL_MODEL) and fal_models.is_registered(ep._FAL_MODEL_HERO)


def test_a_blank_fal_model_line_in_dotenv_means_the_default_not_an_empty_endpoint(monkeypatch):
    """.env.example now lists FAL_MODEL=; a copied blank line must not post to queue.fal.run/."""
    monkeypatch.setenv("FAL_MODEL", "")
    assert ep._fal_model_from_env("FAL_MODEL", "kling-2.1-standard") == fal_models.resolve("kling-2.1-standard")
    monkeypatch.setenv("FAL_MODEL", "  seedance-2.0  ")
    assert ep._fal_model_from_env("FAL_MODEL", "kling-2.1-standard") == "bytedance/seedance-2.0/image-to-video"


@pytest.mark.parametrize("short_name", sorted(dv._FAL_ENDPOINTS))
def test_directed_short_names_price_the_same_through_the_registry_as_through_the_adapter(short_name):
    """A script pricing "kling-v3-pro" straight through fal_models must not get the fallback rate."""
    assert fal_models.resolve(short_name) == dv._FAL_ENDPOINTS[short_name]
    assert fal_models.estimate_clip_usd(short_name, 5) == dv.budget_for(short_name)["candidate_cost_usd"]


def test_short_labels_resolve_to_full_endpoint_ids_for_the_manifest():
    assert fal_models.resolve("seedance-2.0") == "bytedance/seedance-2.0/image-to-video"
    assert fal_models.resolve("wan-2.6") == "wan/v2.6/image-to-video"
    assert ep._motion_model_id("fal", fal_model=fal_models.resolve("wan-2.6")) == "wan/v2.6/image-to-video"


class _Resp:
    def __init__(self, status=200, payload=None, content=b""):
        self.status_code, self._payload, self.content, self.text = status, payload or {}, content, ""

    def json(self):
        return self._payload


@pytest.mark.live_motion
def test_animate_one_submits_the_registry_body_for_a_seedance_model(tmp_path, monkeypatch):
    """The transport is mocked; what matters is the JSON that would have gone to fal."""
    from PIL import Image
    src = tmp_path / "in.jpg"
    Image.new("RGB", (64, 64), "white").save(src)
    monkeypatch.setenv("FAL_KEY", "test-key")
    sent = {}

    def fake_post(url, headers=None, timeout=None, json=None):
        sent["url"], sent["body"] = url, json
        return _Resp(200, {"status_url": "s", "response_url": "r", "request_id": "id"})

    def fake_get(url, headers=None, timeout=None):
        if url == "s":
            return _Resp(200, {"status": "COMPLETED"})
        if url == "r":
            return _Resp(200, {"video": {"url": "v"}})
        return _Resp(200, {}, content=b"mp4")

    import requests
    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(ep.time, "sleep", lambda s: None)
    monkeypatch.setattr(ep, "_clip_is_real", lambda path, **kw: True)   # the bytes are fake
    ok, quota, err = ep._animate_one("fal", str(src), "a wobble", str(tmp_path / "out.mp4"),
                                     1080, 1920, 5, fal_model="seedance-2.0")
    assert ok, err
    assert sent["url"] == "https://queue.fal.run/bytedance/seedance-2.0/image-to-video"
    body = sent["body"]
    assert body["image_url"].startswith("data:image/jpeg;base64,")
    assert body["duration"] == "5" and body["resolution"] == "720p"
    assert body["aspect_ratio"] == "9:16" and body["generate_audio"] is False
    assert "tail_image_url" not in body and "start_image_url" not in body


# ── directed-motion wiring ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("short_name", sorted(dv._FAL_ENDPOINTS))
def test_every_directed_short_name_builds_a_payload_and_is_priced(short_name):
    endpoint = dv._FAL_ENDPOINTS[short_name]
    spec = {"prompt": "p", "duration": 5, "seed_image": "seed.png", "end_image": "end.png",
            "negative_prompt": "legs"}
    body = dv.build_fal_payload(spec, endpoint, lambda p: f"<{p}>")
    assert body["prompt"].startswith("p")
    assert dv.budget_for(short_name)["candidate_cost_usd"] > 0


def test_directed_seedance_conditions_on_the_end_frame_and_kling_v3_extras_stay_on_kling():
    spec = {"prompt": "p", "duration": 5, "seed_image": "seed.png", "end_image": "end.png",
            "cfg_scale": 0.5, "use_elements": True, "identity_reference": "bolt.png"}
    seedance = dv.build_fal_payload(spec, dv._FAL_ENDPOINTS["seedance-2.0"], lambda p: f"<{p}>")
    assert seedance["image_url"] == "<seed.png>" and seedance["end_image_url"] == "<end.png>"
    assert "cfg_scale" not in seedance and "elements" not in seedance
    kling = dv.build_fal_payload(spec, dv._FAL_ENDPOINTS["kling-v3-pro"], lambda p: f"<{p}>")
    assert kling["start_image_url"] == "<seed.png>" and kling["end_image_url"] == "<end.png>"
    assert kling["cfg_scale"] == 0.5 and kling["elements"] == [{"frontal_image_url": "<bolt.png>"}]


def test_directed_wan_two_six_drops_the_end_frame_rather_than_inventing_a_field():
    spec = {"prompt": "p", "duration": 5, "seed_image": "seed.png", "end_image": "end.png"}
    body = dv.build_fal_payload(spec, dv._FAL_ENDPOINTS["wan-2.6"], lambda p: f"<{p}>")
    assert body["image_url"] == "<seed.png>"
    assert not any(k.endswith("image_url") and k != "image_url" for k in body)
    assert not fal_models.supports_end_frame(dv._FAL_ENDPOINTS["wan-2.6"])


def test_the_directed_budget_follows_the_model_instead_of_klings_historical_figure():
    kling = dv.budget_for("kling-v3-pro")["candidate_cost_usd"]
    seedance = dv.budget_for("seedance-2.0")["candidate_cost_usd"]
    assert kling == pytest.approx(0.56)
    assert seedance == pytest.approx(5 * 0.3024)
    assert dv.budget_for("seedance-2.0", resolution="480p")["candidate_cost_usd"] < seedance
    assert dv.budget_for("seedance-2.0", max_candidates=1)["max_candidates"] == 1
