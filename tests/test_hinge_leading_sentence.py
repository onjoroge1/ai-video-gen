"""When no model rewrite fits, a multi-sentence hinge keeps its leading sentences.

Job adb41d84 (2026-09-25): "There is no nest. Nothing to build one from, and the egg must stay
warm." was 15 words against a budget of 10, two asks came back over budget, and the storyboard
gate refused a draft whose research, script, fact-check and ledger were already bought.
"""
from types import SimpleNamespace

import causal_story as cs
import explainer_pipeline as ep


def _client(reply):
    def create(**kwargs):
        return SimpleNamespace(content=[SimpleNamespace(text=reply)],
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    return lambda: SimpleNamespace(messages=SimpleNamespace(create=create))


def test_the_first_sentence_survives_when_rewrites_stay_over_budget(monkeypatch):
    over = '{"hinge":"' + " ".join(["word"] * (cs.MAX_HINGE_WORDS + 3)) + '"}'
    monkeypatch.setattr(ep, "_claude", _client(over))
    monkeypatch.setattr(ep, "rederive_narration_bindings", lambda *a, **k: None)
    monkeypatch.setattr(ep, "validate_claim_joins", lambda *a, **k: {"passed": True})
    script = {"scenes": [{"causal_role": "setup", "narration": "x"},
                         {"causal_role": "hinge", "narration":
                          "There is no nest. Nothing to build one from, and the egg must stay warm."}]}
    out, _ = ep._ensure_hinge_fits_budget(script)
    assert out["scenes"][1]["narration"] == "There is no nest."


def test_a_single_long_sentence_is_left_for_the_gate(monkeypatch):
    over = '{"hinge":"' + " ".join(["word"] * (cs.MAX_HINGE_WORDS + 3)) + '"}'
    monkeypatch.setattr(ep, "_claude", _client(over))
    long_hinge = " ".join(["nest"] * (cs.MAX_HINGE_WORDS + 5)) + "."
    script = {"scenes": [{"causal_role": "hinge", "narration": long_hinge}]}
    out, _ = ep._ensure_hinge_fits_budget(script)
    assert out["scenes"][0]["narration"] == long_hinge
