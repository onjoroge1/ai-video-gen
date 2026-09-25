"""The hook trimmer must not give up silently on a hook the gates will refuse.

Measured on the first emperor penguin long-form (2026-09-24): a 23-word hook against an 18-word
budget passed research, engine, spine, script, fact-check, ledger and runtime, then the single
model ask returned 21 words, the helper kept the original, and the storyboard gate refused the
run on that one line.
"""
from types import SimpleNamespace

import causal_story as cs
import explainer_pipeline as ep

HOOK = ("The emperor mother hands over her only egg and vanishes for two months — and that "
        "leaving is how the chick gets fed.")


def _script():
    return {"title": "Why the Emperor Penguin Mother Leaves Her Only Egg for Two Months",
            "hook": HOOK, "scenes": [{"narration": HOOK + " A female emperor penguin lays a single egg."}]}


def _client(replies):
    it = iter(replies)

    def create(**kwargs):
        text = next(it)
        return SimpleNamespace(content=[SimpleNamespace(text=text)],
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    return lambda: SimpleNamespace(messages=SimpleNamespace(create=create))


def test_a_compliant_rewrite_on_a_later_ask_is_taken(monkeypatch):
    long = '{"hook":"The emperor penguin mother hands over her only egg and vanishes for two whole months of winter."}'
    short = '{"hook":"The emperor mother hands over her only egg and vanishes for two months."}'
    monkeypatch.setattr(ep, "_claude", _client([long, short, short]))
    script, _ = ep._ensure_hook_fits_budget(_script())
    assert len(script["hook"].split()) <= cs.MAX_HOOK_WORDS
    assert script["scenes"][0]["narration"].startswith(script["hook"])
    assert HOOK not in script["scenes"][0]["narration"]


def test_when_every_ask_is_over_budget_the_pre_dash_promise_is_kept(monkeypatch):
    over = ('{"hook":"The emperor penguin mother hands over her only egg and then vanishes into '
            'the frozen sea for two whole dark months."}')
    assert len(over.split()) > cs.MAX_HOOK_WORDS
    monkeypatch.setattr(ep, "_claude", _client([over, over, over]))
    script, _ = ep._ensure_hook_fits_budget(_script())
    assert script["hook"] == "The emperor mother hands over her only egg and vanishes for two months."
    assert script["scenes"][0]["narration"].startswith(script["hook"])
    assert "how the chick gets fed" not in script["scenes"][0]["narration"].split(".")[0]


def test_a_hook_with_no_safe_cut_is_left_for_the_gate(monkeypatch):
    over = '{"hook":"' + " ".join(["word"] * 25) + '"}'
    monkeypatch.setattr(ep, "_claude", _client([over, over, over]))
    script = {"title": "Sparrows", "hook": " ".join(["sparrow"] * 23), "scenes": [{"narration": "x"}]}
    out, _ = ep._ensure_hook_fits_budget(script)
    assert out["hook"] == " ".join(["sparrow"] * 23)


def test_a_hook_already_inside_the_budget_costs_nothing(monkeypatch):
    monkeypatch.setattr(ep, "_claude", lambda: (_ for _ in ()).throw(AssertionError("no call")))
    script = {"title": "t", "hook": "Short hook.", "scenes": []}
    assert ep._ensure_hook_fits_budget(script) == (script, 0.0)
