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


def test_locked_scenes_survive_a_model_that_rewrites_them(monkeypatch):
    """Drive the real refit with a model that ignores the lock and compresses everything."""
    original = _script()
    kept = [original["scenes"][0]["narration"], original["scenes"][2]["narration"]]

    _stub_model(monkeypatch, json.dumps({"scenes": [
        {"narration": "Compressed one."},
        {"narration": "Compressed two."},
        {"narration": "Compressed three."},
    ]}))

    result = ep._enforce_requested_runtime(_script(), 120, log=lambda _m: None)
    scenes = result["scenes"]

    assert scenes[0]["narration"] == kept[0], "sourced scene 1 was edited"
    assert scenes[2]["narration"] == kept[1], "sourced scene 3 was edited"
    assert scenes[1]["narration"] == "Compressed two.", "unsourced scenes must stay editable"


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
    assert "LOCKED" in prompt, "the model must be told which scenes it may not touch"
    assert "SCENES 1, 3" in prompt, f"locked scene numbers must be named, got: {prompt[:200]}"
