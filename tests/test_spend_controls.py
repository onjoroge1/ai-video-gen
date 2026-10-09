"""Spend controls added 2026-10-08, after a day in which the Anthropic credit ran out three times.

The image checker was the largest Claude line (about 390 Opus vision calls), about 80 of them
re-checks of images already accepted; nothing recorded per-call spend; and the writer resent its
beat sheet at full price on every batch.
"""
import base64
import io
import json

from PIL import Image

import explainer_pipeline as ep
import usage_ledger


# ── usage ledger ───────────────────────────────────────────────────────────

def test_cost_uses_the_model_rate_and_prices_cache_tokens():
    usage = {"input_tokens": 1_000_000, "output_tokens": 0}
    assert usage_ledger.anthropic_cost("claude-opus-4-8", usage) == 5.0
    assert usage_ledger.anthropic_cost("claude-sonnet-5-5", usage) == 2.0
    assert abs(usage_ledger.anthropic_cost("claude-haiku-5-5", usage) - 0.10) < 1e-9
    cached = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 1_000_000,
              "cache_creation_input_tokens": 1_000_000}
    assert abs(usage_ledger.anthropic_cost("claude-opus-4-8", cached) - (0.5 + 6.25)) < 1e-9
    assert usage_ledger.anthropic_cost("unknown-model", usage) == 5.0, "unpriced counts as Opus"


def test_the_ledger_sums_every_launch(tmp_path):
    usage_ledger.set_job_dir(str(tmp_path))
    usage_ledger.record("anthropic", "message", 0.5, model="claude-opus-4-8", caller="a.f")
    usage_ledger.set_job_dir(str(tmp_path))                     # a resume is a new launch
    usage_ledger.record("openai", "image", 0.04, model="gpt-image-2", caller="b.g")
    summary = usage_ledger.summarize(str(tmp_path / usage_ledger.LEDGER_FILENAME))
    assert summary["calls"] == 2 and abs(summary["total_usd"] - 0.54) < 1e-9
    assert summary["by_provider"] == {"anthropic": 0.5, "openai": 0.04}
    usage_ledger.set_job_dir("")


def test_meter_records_each_message_and_splits_the_cache_marker(tmp_path):
    usage_ledger.set_job_dir(str(tmp_path))
    seen = {}

    class _Inner:
        def create(self, **kwargs):
            seen.update(kwargs)
            return type("R", (), {"model": kwargs["model"], "usage": type("U", (), {
                "input_tokens": 100, "output_tokens": 10, "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0})()})()

    client = usage_ledger.meter(type("C", (), {"messages": _Inner()})())
    text = "PREFIX" + usage_ledger.CACHE_SPLIT + "REST"
    client.messages.create(model="claude-opus-4-8", max_tokens=5,
                           messages=[{"role": "user", "content": text}])
    blocks = seen["messages"][0]["content"]
    assert blocks[0] == {"type": "text", "text": "PREFIX", "cache_control": {"type": "ephemeral"}}
    assert blocks[1] == {"type": "text", "text": "REST"}
    rows = usage_ledger.read(str(tmp_path / usage_ledger.LEDGER_FILENAME))
    assert len(rows) == 1 and rows[0]["input_tokens"] == 100 and rows[0]["model"] == "claude-opus-4-8"
    usage_ledger.set_job_dir("")


def test_the_writer_prefix_is_marked_for_the_cache_but_reads_as_one_string(monkeypatch):
    monkeypatch.setattr(ep.script_provider, "active_provider", lambda: "anthropic")
    joined = ep._cached_prefix_content("SHEET", "NOW WRITE")
    assert isinstance(joined, str) and joined.replace(usage_ledger.CACHE_SPLIT, "") == "SHEETNOW WRITE"
    monkeypatch.setattr(ep.script_provider, "active_provider", lambda: ep.script_provider.OPENAI)
    assert ep._cached_prefix_content("SHEET", "NOW WRITE") == "SHEETNOW WRITE"


# ── image checker ──────────────────────────────────────────────────────────

def _png(path, size=(1536, 1024), colour=(200, 120, 90)):
    Image.new("RGB", size, colour).save(path, format="PNG")
    return str(path)


STATE = {"required_objects": ["wooden hive box"], "forbidden_objects": [], "state_before": "a",
         "state_after": "b", "include_human": False, "pure_evidence": True}
PACK = {"opening_object": {"label": "a hive box"}, "first_act_location": {}}


class _Judge:
    def __init__(self):
        self.calls, self.requests = 0, []
        outer = self

        class _M:
            def create(self, **kwargs):
                outer.calls += 1
                outer.requests.append(kwargs)
                text = json.dumps({"required_objects": {"wooden hive box": True},
                                   "forbidden_objects_absent": {}, "visible_information": True,
                                   "bolt_present": False, "reasons": []})
                return type("R", (), {"content": [type("T", (), {"text": text})()],
                                      "usage": {"input_tokens": 900, "output_tokens": 40}})()
        self.messages = _M()


def test_a_verdict_is_reused_for_the_same_image_and_bought_again_for_new_bytes(tmp_path, monkeypatch):
    judge = _Judge()
    monkeypatch.setattr(ep, "_claude", lambda: judge)
    image = _png(tmp_path / "scene.jpg")
    first = ep.verify_evidence_asset(image, STATE, PACK, cost_sink=[])
    second = ep.verify_evidence_asset(image, STATE, PACK, cost_sink=[])
    assert first["passed"] and second["passed"] and second.get("verdict_cached") is True
    assert judge.calls == 1, "a resume does not re-buy an accepted verdict"
    _png(tmp_path / "scene.jpg", colour=(10, 200, 10))          # a redraw: new bytes
    ep.verify_evidence_asset(image, STATE, PACK, cost_sink=[])
    assert judge.calls == 2
    changed_state = dict(STATE, required_objects=["hollow tree nest"])
    ep.verify_evidence_asset(image, changed_state, PACK, cost_sink=[])
    assert judge.calls == 3, "a different question is a different verdict"


def test_the_checker_sees_a_downscaled_image_on_its_own_model(tmp_path, monkeypatch):
    judge = _Judge()
    monkeypatch.setattr(ep, "_claude", lambda: judge)
    monkeypatch.setattr(ep, "VERIFY_IMAGE_MAX_EDGE", 768)
    monkeypatch.setattr(ep, "EVIDENCE_VERIFY_MODEL", "claude-haiku-5-5")
    ep.verify_evidence_asset(_png(tmp_path / "big.jpg"), STATE, PACK, cost_sink=[])
    request = judge.requests[0]
    assert request["model"] == "claude-haiku-5-5"
    image_block = request["messages"][0]["content"][0]
    assert image_block["source"]["media_type"] == "image/jpeg"
    sent = Image.open(io.BytesIO(base64.b64decode(image_block["source"]["data"])))
    assert max(sent.size) == 768


def test_colour_is_style_not_evidence():
    assert "COLOUR IS STYLE, NOT EVIDENCE" in ep._EVIDENCE_VERIFY_SYSTEM
    assert "colour that IS the state" in ep._EVIDENCE_VERIFY_SYSTEM


def test_a_refused_image_is_kept_with_its_verdict(tmp_path):
    image = _png(tmp_path / "scene_05_e02.jpg")
    ep._keep_rejected_image(image, {"passed": False, "reasons": ["no swarm"]}, 1)
    assert (tmp_path / "scene_05_e02.jpg.rejected-1.jpg").exists()
    kept = json.loads((tmp_path / "scene_05_e02.jpg.rejected-1.json").read_text())
    assert kept["reasons"] == ["no swarm"]


def test_the_checker_turns_thinking_off_per_model_and_reads_the_text_block():
    assert ep._checker_thinking_options("claude-haiku-5-5") == {"thinking": {"type": "disabled"}}
    assert ep._checker_thinking_options("claude-sonnet-5-5") == {"thinking": {"type": "between_tools"}}
    assert ep._checker_thinking_options("claude-opus-4-8") == {}
    reply = type("R", (), {"content": [type("B", (), {"type": "thinking", "thinking": ""})(),
                                        type("B", (), {"type": "text", "text": "{}"})()]})()
    assert ep._first_text(reply) == "{}"
