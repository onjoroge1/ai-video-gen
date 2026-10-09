"""Presentation-only failures repair the draft; they never buy a new beat sheet.

Measured 2026-09-22 across three consecutive 300s renders: a replan bought for LATE_MECHANISM
returned a sheet whose reversal was contradicted (run 5), one whose mechanism was still late by
a smaller margin (run 7), and one that added NO_CALLBACK (run 6). Every one of those drafts had
a supported spine before the replan threw it away.
"""
import explainer_pipeline as ep


def _validation(*codes):
    return {"passed": not codes, "score": 60,
            "errors": [{"code": c, "message": c.lower()} for c in codes]}


def test_every_presentation_code_alone_or_together_is_repairable():
    assert ep._only_presentation_blocks(_validation("LONG_HOOK"), [])
    assert ep._only_presentation_blocks(_validation(), ["LATE_MECHANISM: lands at 55s"])
    assert ep._only_presentation_blocks(
        _validation("LONG_HOOK"), ["NO_CALLBACK: never returns", "SOFT_HINGE: 13 words"])


def test_a_story_defect_still_replans():
    assert not ep._only_presentation_blocks(_validation(), ["ENGINE_ORDER: mechanism first"])
    assert not ep._only_presentation_blocks(
        _validation("LONG_HOOK"), ["LATE_MECHANISM: x", "THIN_GENERALIZATION: y"])
    assert not ep._only_presentation_blocks(_validation(), [])


def test_storyboard_error_strings_are_read_by_their_code():
    assert ep._blocking_codes({}, ["NO_CALLBACK: the closing step never returns to 'x'"]) == [
        "NO_CALLBACK"]
    assert ep._blocking_codes(_validation("LONG_HOOK"), [{"code": "SOFT_HINGE"}]) == [
        "LONG_HOOK", "SOFT_HINGE"]


def test_the_hook_only_shortcut_is_unchanged():
    assert ep._only_hook_length_blocks(_validation("LONG_HOOK"), [])
    assert not ep._only_hook_length_blocks(_validation("LONG_HOOK"), ["NO_CALLBACK: x"])


def test_repair_presentation_runs_all_four_repairs_in_gate_order(monkeypatch):
    calls = []
    for name in ("_ensure_hook_fits_budget", "_ensure_hinge_fits_budget",
                 "_ensure_close_returns_to_object", "_ensure_mechanism_meets_deadline"):
        monkeypatch.setattr(ep, name, (lambda n: lambda script, *a, **k:
                                       (calls.append(n), (script, 0.25))[1])(name))
    script = {"scenes": []}
    out, cost = ep._repair_presentation(script, [], lambda m: None, {})
    assert out is script and cost == 1.0
    assert calls == ["_ensure_hook_fits_budget", "_ensure_hinge_fits_budget",
                     "_ensure_close_returns_to_object", "_ensure_mechanism_meets_deadline"]


def test_the_replan_loop_repairs_before_it_replans():
    import inspect
    src = inspect.getsource(ep.generate_graded_script)
    repair = src.index("_only_presentation_blocks(best_validation, best_causal_errors)")
    replan = src.index("improve_note=\"DETERMINISTIC CONTRACT FAILURES: \"")
    assert repair < replan
    assert "_only_hook_length_blocks(best_validation" not in src, \
        "the narrow hook-only shortcut was replaced, not duplicated"
