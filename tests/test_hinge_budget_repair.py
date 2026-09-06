"""The hinge word budget, repaired before the gate that measures it.

SOFT_HINGE killed a live 90-second pilot at 13 words against a budget of 10, after research,
script, fact-check and grading were all paid for. LONG_HOOK is the same class of failure and has
had _ensure_hook_fits_budget sitting on the line above the storyboard call for some time; the hinge
reached the gate with nothing.

The hinge differs from the hook in one way that matters: it IS scene narration, so its claim refs
and anchor phrases are bound to the exact wording. A rewrite that shortens the sentence and loses
its source has traded a word budget for an unsourced claim, which is a worse draft that reads
greener. These tests pin both halves.
"""
import causal_story as cs
import explainer_pipeline as ep


def _script(hinge_narration):
    return {
        "hook": "A fix that made it worse.",
        "scenes": [
            {"narration": "Step one. A city has a snake problem.", "causal_role": "setup"},
            {"narration": "Officials post a bounty on every dead cobra.",
             "causal_role": "intervention"},
            {"narration": "Cobras pour in and the count climbs.",
             "causal_role": "false_resolution"},
            {"narration": hinge_narration, "causal_role": "hinge"},
            {"narration": "Reward a number and people chase the number.",
             "causal_role": "mechanism"},
        ],
    }


def _fake_claude(monkeypatch, returned):
    class _Messages:
        def create(self, **call):
            return type("R", (), {
                "content": [type("C", (), {"text": returned})()],
                "usage": type("U", (), {"input_tokens": 10, "output_tokens": 10})()})()

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    monkeypatch.setattr(ep, "_msg_cost", lambda usage: 0.001)


def test_a_hinge_inside_its_budget_costs_nothing_and_is_untouched(monkeypatch):
    def _unexpected():
        raise AssertionError("a hinge within budget must not buy a rewrite")

    monkeypatch.setattr(ep, "_claude", _unexpected)
    script = _script("Except the problem is not solved.")
    result, cost = ep._ensure_hinge_fits_budget(dict(script))
    assert cost == 0.0
    assert result["scenes"][3]["narration"] == "Except the problem is not solved."


def test_an_over_long_hinge_is_rewritten_into_budget(monkeypatch):
    _fake_claude(monkeypatch, '{"hinge":"It rewarded dead cobras, not fewer wild ones."}')
    monkeypatch.setattr(ep, "rederive_narration_bindings", lambda *a, **k: None)
    monkeypatch.setattr(ep, "validate_claim_joins", lambda *a, **k: {"passed": True})

    long_hinge = "It rewarded dead cobras, the metric, not a shrinking wild population, the goal."
    assert len(long_hinge.split()) > cs.MAX_HINGE_WORDS
    result, cost = ep._ensure_hinge_fits_budget(_script(long_hinge))

    rewritten = result["scenes"][3]["narration"]
    assert rewritten != long_hinge
    assert len(rewritten.split()) <= cs.MAX_HINGE_WORDS
    assert cost > 0


def test_a_rewrite_that_is_still_over_budget_is_discarded(monkeypatch):
    """Half a repair is worse than none: the gate would fail either way, on different text."""
    _fake_claude(monkeypatch, '{"hinge":"' + " ".join(["word"] * 20) + '"}')
    long_hinge = "It rewarded dead cobras, the metric, not a shrinking wild population, the goal."
    result, _ = ep._ensure_hinge_fits_budget(_script(long_hinge))
    assert result["scenes"][3]["narration"] == long_hinge


def test_a_rewrite_that_loses_the_source_is_reverted(monkeypatch):
    """A sourced claim is a harder contract than a word budget."""
    _fake_claude(monkeypatch, '{"hinge":"It rewarded dead cobras, not fewer wild ones."}')
    monkeypatch.setattr(ep, "rederive_narration_bindings", lambda *a, **k: None)
    verdicts = iter([{"passed": True}, {"passed": False}])
    monkeypatch.setattr(ep, "validate_claim_joins", lambda *a, **k: next(verdicts))

    long_hinge = "It rewarded dead cobras, the metric, not a shrinking wild population, the goal."
    result, _ = ep._ensure_hinge_fits_budget(_script(long_hinge))
    assert result["scenes"][3]["narration"] == long_hinge


def test_a_provider_failure_leaves_the_script_alone(monkeypatch):
    def _boom():
        raise RuntimeError("provider down")

    monkeypatch.setattr(ep, "_claude", _boom)
    long_hinge = "It rewarded dead cobras, the metric, not a shrinking wild population, the goal."
    result, _ = ep._ensure_hinge_fits_budget(_script(long_hinge))
    assert result["scenes"][3]["narration"] == long_hinge


def test_a_script_with_no_hinge_is_not_a_failure(monkeypatch):
    def _unexpected():
        raise AssertionError("no hinge means nothing to repair")

    monkeypatch.setattr(ep, "_claude", _unexpected)
    script = _script("x")
    script["scenes"][3]["causal_role"] = "escalation"
    result, cost = ep._ensure_hinge_fits_budget(script)
    assert cost == 0.0
    assert result["scenes"][3]["narration"] == "x"
