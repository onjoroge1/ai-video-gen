"""LATE_MECHANISM by a few words is repaired by tightening the scenes before it.

The line stays where the corpus put it and the beat stays where the sheet put it. Measured
2026-09-22 on two consecutive 300s Four Pests runs: 55s past a 53s mark, then 48s past a 46s
mark, both after research, script, three claim-ledger passes and the runtime contract had passed.
"""
import types

import explainer_pipeline as ep


def _fake(text_for_words):
    """A model that returns narration cut to the requested word count, or a fixed text."""
    def create(**kw):
        content = kw["messages"][0]["content"]
        if callable(text_for_words):
            reply = text_for_words(content)
        else:
            reply = text_for_words
        return types.SimpleNamespace(content=[types.SimpleNamespace(text=reply)], usage=None)
    return lambda: types.SimpleNamespace(messages=types.SimpleNamespace(create=create))


def _cut_to_request(content):
    import json, re
    limit = int(re.search(r"at most (\d+) words", content).group(1))
    original = re.search(r'\n\n"(.+?)"\n\n', content, re.S).group(1)
    words = original.split()
    return json.dumps({"narration": " ".join(words[:limit])})


def _script(pre_words=(20, 40, 30), mech_words=20, post_words=(100, 100, 60)):
    def scene(role, n, phrase=""):
        text = " ".join(["word"] * n)
        if phrase:
            text = phrase + " " + " ".join(["word"] * max(0, n - len(phrase.split())))
        return {"causal_role": role, "narration": text,
                "claim_refs": [{"narration_phrase": phrase}] if phrase else []}
    scenes = [scene("setup", pre_words[0])]
    scenes += [scene("context" if i else "intervention", n, phrase="sourced fact here")
               for i, n in enumerate(pre_words[1:])]
    scenes.append(scene("mechanism", mech_words))
    scenes += [scene("escalation", n) for n in post_words]
    return {"scenes": scenes}


def test_a_mechanism_inside_the_line_costs_nothing_and_changes_nothing():
    script = _script(pre_words=(10, 10, 10), post_words=(100, 100, 100))
    out, cost = ep._ensure_mechanism_meets_deadline(script)
    assert cost == 0.0 and out is script


def test_a_small_miss_is_repaired_by_tightening_and_keeps_the_sourced_phrase(monkeypatch):
    script = _script()                      # 90 of 370 words before the mechanism = 24.3%
    assert ep._mechanism_position(script["scenes"])["late"]
    monkeypatch.setattr(ep, "_claude", _fake(_cut_to_request))
    monkeypatch.setattr(ep, "_msg_cost", lambda usage: 0.01)
    monkeypatch.setattr(ep, "rederive_narration_bindings", lambda *a, **k: None)
    monkeypatch.setattr(ep, "validate_claim_joins", lambda *a, **k: {"passed": True})
    out, cost = ep._ensure_mechanism_meets_deadline(script)
    position = ep._mechanism_position(out["scenes"])
    assert not position["late"], position
    assert out["scenes"][0]["narration"].split().__len__() == 20, "the opener is never trimmed"
    assert all("sourced fact here" in s["narration"] for s in out["scenes"][1:3])
    assert cost > 0


def test_a_large_miss_is_left_for_the_gate(monkeypatch):
    script = _script(pre_words=(40, 80, 80), post_words=(60, 60, 60))   # 200 of 420 = 48%
    called = []
    monkeypatch.setattr(ep, "_claude", lambda: called.append(1))
    out, cost = ep._ensure_mechanism_meets_deadline(script)
    assert cost == 0.0 and not called and out is script


def test_a_rewrite_that_drops_the_sourced_phrase_is_not_used(monkeypatch):
    script = _script()
    monkeypatch.setattr(ep, "_claude", _fake('{"narration":"short but unsourced"}'))
    monkeypatch.setattr(ep, "_msg_cost", lambda usage: 0.01)
    before = [s["narration"] for s in script["scenes"]]
    out, _ = ep._ensure_mechanism_meets_deadline(script)
    assert [s["narration"] for s in out["scenes"]] == before


def test_tightened_scenes_that_lose_their_evidence_are_all_put_back(monkeypatch):
    script = _script()
    monkeypatch.setattr(ep, "_claude", _fake(_cut_to_request))
    monkeypatch.setattr(ep, "_msg_cost", lambda usage: 0.01)
    monkeypatch.setattr(ep, "rederive_narration_bindings", lambda *a, **k: None)
    verdicts = iter([{"passed": True}, {"passed": False}])
    monkeypatch.setattr(ep, "validate_claim_joins", lambda *a, **k: next(verdicts))
    before = [s["narration"] for s in script["scenes"]]
    out, _ = ep._ensure_mechanism_meets_deadline(script)
    assert [s["narration"] for s in out["scenes"]] == before


def test_the_repair_is_wired_after_the_callback_and_before_the_storyboard_gate():
    import inspect
    src = inspect.getsource(ep.run_explainer_pipeline)
    callback = src.index("_ensure_close_returns_to_object(script, aux_costs, log)")
    deadline = src.index("_ensure_mechanism_meets_deadline(")
    gate = src.index("illustrated_story_lane.build_storyboard(script, question)")
    assert callback < deadline < gate
