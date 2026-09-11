"""Voice is checked after expansion, because stating it in the prompt did not work.

narration_tense and sentence_length reached every blueprint and five consecutive Macquarie drafts
came back past tense at a 9-word median, against a corpus that is present tense at 6. That is the
fourth property in this work that a prompt failed to move and a check moved -- citations, actor
attribution, word budget, and now voice.
"""
import json

import pytest

import explainer_pipeline as ep
import reference_corpus as rc


def _scenes(lines):
    return [{"narration": line, "id": i + 1} for i, line in enumerate(lines)]


PAST_AND_LONG = [
    "Cats were eradicated on the island to protect the seabirds that nested on its slopes.",
    "The programme removed every last cat over a period of fifteen years of sustained effort.",
    "Rabbit numbers rose sharply afterwards because nothing remained that would prey upon them.",
    "The vegetation was stripped back to bare ground across a substantial share of the island.",
]


def test_the_target_is_derived_from_the_corpus_not_declared():
    """The numbers move when the corpus does, and an engine is judged against its own references."""
    house = rc.voice_target()
    assert house["tense"] == "present", "five of five measured references are present tense"
    assert 4 <= house["median_words"] <= 9
    assert house["references"] >= 5
    # An engine with no references of its own falls back to the house voice rather than to nothing.
    assert rc.voice_target("removed_keystone")["median_words"] == house["median_words"]


def test_a_draft_already_in_voice_is_not_rewritten(monkeypatch):
    """Rewriting a draft inside the corpus band buys a call to move it sideways."""
    monkeypatch.setattr(ep, "_claude", lambda: pytest.fail("no provider call expected"))
    scenes = _scenes(["Cats hunt the seabirds.", "So the cats are shot.", "Rabbits breed.",
                      "The island goes bare."])
    out, cost = ep._enforce_voice(scenes, "removed_keystone")
    assert out == scenes and cost == 0.0


def test_a_past_tense_draft_is_sent_back_with_the_numbers(monkeypatch):
    seen = {}

    class _Messages:
        def create(self, **call):
            seen["prompt"], seen["system"] = call["messages"][0]["content"], call["system"]
            return type("R", (), {
                "usage": type("U", (), {"input_tokens": 400, "output_tokens": 120})(),
                "content": [type("C", (), {"text": json.dumps({"narration": [
                    "Cats are eradicated to protect the seabirds.",
                    "Every last cat goes. It takes fifteen years.",
                    "Rabbit numbers rise. Nothing preys on them now.",
                    "The vegetation strips back. Bare ground spreads."]})})()]})()

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    out, cost = ep._enforce_voice(_scenes(PAST_AND_LONG), "removed_keystone")
    assert cost > 0
    assert rc.measure_voice(" ".join(s["narration"] for s in out))["narration_tense"].startswith("present")
    # The draft's own measurements and the corpus target both reach the editor.
    assert "median 15 words" in seen["prompt"] or "median 1" in seen["prompt"]
    assert "reference videos" in seen["prompt"] and "present tense" in seen["prompt"]
    assert "may NOT add a fact" in seen["prompt"]
    assert "HOW something is said and never WHAT it says" in seen["system"]


def test_a_mismatched_reply_leaves_the_draft_alone(monkeypatch):
    """Same count, same order, or the rewrite is unusable."""
    class _Messages:
        def create(self, **call):
            return type("R", (), {
                "usage": type("U", (), {"input_tokens": 100, "output_tokens": 20})(),
                "content": [type("C", (), {"text": '{"narration":["only one line"]}'})()]})()

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    scenes = _scenes(PAST_AND_LONG)
    out, cost = ep._enforce_voice(scenes, "removed_keystone")
    assert [s["narration"] for s in out] == PAST_AND_LONG
    assert cost > 0, "the call was still paid for and is recorded"


def test_an_outage_leaves_the_draft_standing(monkeypatch):
    class _Messages:
        def create(self, **call):
            raise RuntimeError("provider down")

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    out, cost = ep._enforce_voice(_scenes(PAST_AND_LONG), "removed_keystone")
    assert [s["narration"] for s in out] == PAST_AND_LONG and cost == 0.0


def test_it_runs_on_the_causal_lane_after_expansion():
    source = open(ep.__file__, encoding="utf-8").read()
    block = source[source.index("if causal_lane:\n        all_scenes, vc = _enforce_voice"):]
    block = block[:block.index('s["id"] = i + 1')]
    assert "_ledger.EXPANSION" in block, "charged like the expansion it follows"
