"""A fact-check corrects facts; it does not tighten prose.

The pass returned a 619-word script as 255 words and called them corrections, and the runtime
contract then reported a 93-second film against a 300-second target. Its prompt already said
"Preserve tone, length, and order", which is the third time today an instruction the model can
ignore was standing in for a guarantee.

Deleting an unsupported assertion is the claim ledger's job; it runs next, with the evidence in
front of it.
"""
import json
from types import SimpleNamespace

import explainer_pipeline as ep


def _script():
    return {"title": "T", "scenes": [
        {"narration": "The colonies sat in their hive boxes, twenty-nine of them, each one "
                      "fitted with a queen excluder that kept the larger queens below."},
        {"narration": "A local beekeeper lifted the grids away one October morning, and the "
                      "colonies behind them were suddenly free to leave whenever they chose."}]}


def _provider(monkeypatch, narration):
    def create(**kwargs):
        body = json.dumps({"title": "T", "narration": narration, "notes": []})
        return SimpleNamespace(content=[SimpleNamespace(text=body)],
                               usage=SimpleNamespace(input_tokens=10, output_tokens=10))
    monkeypatch.setattr(ep, "_claude",
                        lambda: SimpleNamespace(messages=SimpleNamespace(create=create)))


def test_a_compressed_rewrite_is_refused(monkeypatch):
    _provider(monkeypatch, ["Twenty-nine colonies sat in boxes.", "A beekeeper removed them."])
    script, notes, _ = ep.factcheck_script(_script(), "q", {})
    words = sum(len(s["narration"].split()) for s in script["scenes"])
    assert words > 40, f"the fact-check compressed the script to {words} words"
    assert any("compression" in n for n in notes), notes


def test_a_real_correction_of_similar_length_is_kept(monkeypatch):
    fixed = ["The colonies sat in their hive boxes, twenty-six of them, each one fitted with a "
             "queen excluder that kept the larger queens below.",
             "A local beekeeper lifted the grids away one October morning, and the colonies "
             "behind them were suddenly free to leave whenever they chose."]
    _provider(monkeypatch, fixed)
    script, _, _ = ep.factcheck_script(_script(), "q", {})
    assert "twenty-six" in script["scenes"][0]["narration"], "a genuine correction was discarded"


def test_a_short_line_is_left_alone(monkeypatch):
    """The rule needs a line long enough for a third of it to mean anything."""
    small = {"title": "T", "scenes": [{"narration": "It worked."}]}
    _provider(monkeypatch, ["It did not work."])
    script, _, _ = ep.factcheck_script(small, "q", {})
    assert script["scenes"][0]["narration"] == "It did not work."
