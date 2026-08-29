"""The runtime refit must not edit narration a source was verified against.

The refit compresses narration to hit a word budget and cut claim-carrying wording to do
it. _repair_claim_phrases can then only DROP a binding whose assertion is gone, which
leaves a factual scene unsourced, which is what validate_claim_joins rejects on the very
next line. Correcting words_per_second widened the budget from ~220 to ~321 words, so the
pass had more to cut and cut harder.
"""

import json

import explainer_pipeline as ep


def _script():
    return {"scenes": [
        {"narration": "Ulcers were blamed on stress for most of the twentieth century.",
         "claim_refs": [{"claim_id": "c01", "narration_phrase": "blamed on stress"}]},
        {"narration": "A doctor stared at the slide and refused to believe it. "
                      "He looked again and again and still it made no sense to him at all."},
        {"narration": "Over 90 percent of duodenal ulcers trace to one bacterium.",
         "claim_refs": [{"claim_id": "c12", "narration_phrase": "Over 90 percent"}]},
    ]}


def _stub_model(monkeypatch, payload):
    class _Resp:
        content = [type("C", (), {"text": payload})()]

    monkeypatch.setattr(ep, "_claude", lambda: type(
        "C", (), {"messages": type("M", (), {
            "create": staticmethod(lambda **kw: _Resp())})()})())


def test_a_scene_that_loses_its_sourced_sentence_is_reverted(monkeypatch):
    """Drive the real refit with a model that discards the sourced sentences."""
    original = _script()
    kept = [original["scenes"][0]["narration"], original["scenes"][2]["narration"]]

    _stub_model(monkeypatch, json.dumps({"scenes": [
        {"narration": "Compressed one."},
        {"narration": "Compressed two."},
        {"narration": "Compressed three."},
    ]}))

    scenes = ep._enforce_requested_runtime(_script(), 120, log=lambda _m: None)["scenes"]

    assert scenes[0]["narration"] == kept[0], "sourced scene 1 lost its claim sentence"
    assert scenes[2]["narration"] == kept[1], "sourced scene 3 lost its claim sentence"
    assert scenes[1]["narration"] == "Compressed two.", "unsourced scenes must stay editable"


def test_compression_is_kept_when_the_sourced_sentence_survives(monkeypatch):
    """The whole point of locking sentences instead of scenes.

    Scene-level locking immobilised 100% of a real script -- every scene in an evidence-led
    format carries a claim -- so the refit became a no-op and a 120s request measured 137.98s.
    A scene that keeps its sourced sentence must keep its compression.
    """
    sourced = _script()["scenes"][0]["narration"]
    trimmed = sourced + " Extra padding removed."

    _stub_model(monkeypatch, json.dumps({"scenes": [
        {"narration": sourced},              # locked sentence preserved, rest gone
        {"narration": "Compressed two."},
        {"narration": "Over 90 percent of duodenal ulcers trace to one bacterium."},
    ]}))

    script = _script()
    script["scenes"][0]["narration"] = trimmed
    scenes = ep._enforce_requested_runtime(script, 120, log=lambda _m: None)["scenes"]

    assert scenes[0]["narration"] == sourced, (
        "a scene that kept its sourced sentence must keep the compression of the rest")


def test_the_prompt_names_the_locked_scenes(monkeypatch):
    seen = {}

    class _Resp:
        content = [type("C", (), {"text": '{"scenes": []}'})()]

    def _capture(**kwargs):
        seen["prompt"] = kwargs["messages"][0]["content"]
        return _Resp()

    monkeypatch.setattr(ep, "_claude", lambda: type(
        "C", (), {"messages": type("M", (), {"create": staticmethod(_capture)})()})())

    ep._enforce_requested_runtime(_script(), 120, log=lambda _m: None)

    prompt = seen.get("prompt", "")
    assert "LOCKED" in prompt, "the model must be told which sentences it may not touch"
    # The sentences themselves, quoted, so the model can reproduce them character for character.
    assert "blamed on stress" in prompt, f"locked sentence not quoted, got: {prompt[:300]}"
    assert "Over 90 percent" in prompt, "second locked sentence not quoted"
    assert "scene 1:" in prompt and "scene 3:" in prompt, "locked sentences must name their scene"
