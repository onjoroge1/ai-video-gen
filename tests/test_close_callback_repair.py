"""The close must name the opening object, and the pipeline repairs it before the gate.

NO_CALLBACK is the third member of the LONG_HOOK / SOFT_HINGE family. Measured 2026-09-22 on a
300s Four Pests run: research, script, three claim-ledger repair passes and the runtime contract
all passed, and the storyboard gate killed the run because the closing lesson never said
sparrow, grain or field.
"""
import types

import causal_story as cs
import explainer_pipeline as ep


class _FakeClaude:
    def __init__(self, text):
        self._text = text

    @property
    def messages(self):
        def create(**kw):
            if self._text is None:
                raise RuntimeError("provider down")
            return types.SimpleNamespace(content=[types.SimpleNamespace(text=self._text)],
                                         usage=None)
        return types.SimpleNamespace(create=create)


OBJECT = "a single sparrow above a grain field"
LESSON = "Every fix touches a web you can't fully see. Count the friends of the thing you hate."


def _script(closing=LESSON, opening_object=OBJECT):
    return {"_story_contract": {"opening_object": opening_object},
            "scenes": [{"causal_role": "setup", "narration": "Sparrows ate the insects."},
                       {"causal_role": "reversal", "narration": "The locusts came."},
                       {"causal_role": "tool", "narration": closing}]}


def test_the_predicate_is_the_gates_own_rule():
    assert not cs.close_returns_to_object(OBJECT, LESSON)
    assert cs.close_returns_to_object(OBJECT, "So watch the sparrows over the field.")
    assert cs.close_returns_to_object("cobra farms everywhere", "Where are the cobra farms?")
    assert cs.close_returns_to_object("", LESSON), "no object means nothing to return to"


def test_a_close_that_already_returns_costs_nothing_and_changes_nothing():
    script = _script("So next time, picture that sparrow above the grain.")
    out, cost = ep._ensure_close_returns_to_object(script)
    assert cost == 0.0 and out["scenes"][-1]["narration"].endswith("above the grain.")


def test_the_writers_sentence_is_appended_and_the_original_kept(monkeypatch):
    monkeypatch.setattr(ep, "_claude", lambda: _FakeClaude(
        '{"callback":"Picture that single sparrow above the grain field again"}'))
    monkeypatch.setattr(ep, "_msg_cost", lambda usage: 0.01)
    out, cost = ep._ensure_close_returns_to_object(_script())
    narration = out["scenes"][-1]["narration"]
    assert narration.startswith(LESSON), "append-only: every original sentence survives"
    assert narration.endswith("above the grain field again.")
    assert cs.close_returns_to_object(OBJECT, narration)
    assert cost == 0.01


def test_a_sentence_that_still_misses_the_object_falls_back_to_the_plain_line(monkeypatch):
    monkeypatch.setattr(ep, "_claude", lambda: _FakeClaude('{"callback":"Think about it."}'))
    monkeypatch.setattr(ep, "_msg_cost", lambda usage: 0.01)
    out, _ = ep._ensure_close_returns_to_object(_script())
    narration = out["scenes"][-1]["narration"]
    assert narration == LESSON + " Remember that single sparrow above a grain field."
    assert cs.close_returns_to_object(OBJECT, narration)


def test_a_provider_failure_still_repairs_with_the_plain_line(monkeypatch):
    monkeypatch.setattr(ep, "_claude", lambda: _FakeClaude(None))
    out, cost = ep._ensure_close_returns_to_object(_script())
    assert out["scenes"][-1]["narration"].endswith(
        "Remember that single sparrow above a grain field.")
    assert cost == 0.0


def test_the_repair_touches_the_last_closing_scene_only():
    monkey = _script()
    monkey["scenes"].append({"causal_role": "verdict", "narration": "Then decide."})
    import types as _t
    ep_claude = ep._claude
    try:
        ep._claude = lambda: _FakeClaude(None)
        out, _ = ep._ensure_close_returns_to_object(monkey)
    finally:
        ep._claude = ep_claude
    assert out["scenes"][2]["narration"] == LESSON
    assert out["scenes"][3]["narration"].startswith("Then decide.")
    assert cs.close_returns_to_object(OBJECT, out["scenes"][3]["narration"])


def test_the_repair_is_wired_between_the_hinge_repair_and_the_storyboard_gate():
    import inspect
    src = inspect.getsource(ep.run_explainer_pipeline)
    hinge = src.index("_ensure_hinge_fits_budget(")
    callback = src.index("_ensure_close_returns_to_object(script, aux_costs, log)")
    gate = src.index("illustrated_story_lane.build_storyboard(script, question)")
    assert hinge < callback < gate


def test_the_callback_object_label_is_aligned_to_the_opening_object():
    """Measured on both surviving Four Pests drafts: one word of drift between the two labels,
    and validate_evidence_plan refuses the run for it after every earlier gate was bought."""
    logs = []
    script = {"_story_contract": {"opening_object": "a single sparrow above a grain field",
                                  "final_callback_object": "a single sparrow back above a grain field"}}
    assert ep._align_callback_object(script, logs.append)
    assert script["_story_contract"]["final_callback_object"] == "a single sparrow above a grain field"
    assert logs and "aligned" in logs[0]
    assert not ep._align_callback_object(script, logs.append), "idempotent"


def test_a_case_only_difference_or_a_missing_contract_is_left_alone():
    script = {"_story_contract": {"opening_object": "A Coin", "final_callback_object": "a coin"}}
    assert not ep._align_callback_object(script)
    assert not ep._align_callback_object({"scenes": []})
    assert not ep._align_callback_object({"_story_contract": {"final_callback_object": "x"}})


def test_the_aligned_contract_satisfies_the_evidence_plan_gate():
    from longform_evidence import build_continuity_pack
    script = {"_story_contract": {"opening_object": "a dead sparrow falling from an exhausted sky",
                                  "final_callback_object": "a living sparrow back on a rice stalk"},
              "scenes": [{"narration": "One.", "story_role": "setup", "continuity_anchor": "a field"},
                         {"narration": "Two.", "story_role": "final_payoff"}]}
    ep._align_callback_object(script)
    pack = build_continuity_pack(script)
    assert pack["callback"]["label"].casefold() == pack["opening_object"]["label"].casefold()


def test_alignment_is_wired_before_the_storyboard_gate_and_into_the_replan_repairs():
    import inspect
    src = inspect.getsource(ep.run_explainer_pipeline)
    assert src.index("_align_callback_object(script, log)") < src.index(
        "illustrated_story_lane.build_storyboard(script, question)")
    assert "_align_callback_object(script, log)" in inspect.getsource(ep._repair_presentation)
