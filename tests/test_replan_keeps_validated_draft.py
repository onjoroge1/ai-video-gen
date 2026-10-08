"""A narration-timing miss is left to the storyboard repair; a failed replan keeps the draft.

Cane toad film, attempt 3 (2026-09-29): the first draft cleared research, spine and ledger with
its mechanism at 51s against a 51s deadline. The pre-render loop replanned it, the replacement
sheet failed the spine twice, and StorySpineUnsupported ended the run with a validated draft in
hand. Neither change lowers a gate: the storyboard gate still refuses a late mechanism, and its
repair is the one bounded edit already built for that code.
"""
import explainer_pipeline as ep


def test_only_timing_codes_skip_the_replan():
    passed = {"passed": True, "score": 80, "errors": []}
    late = ["LATE_MECHANISM: the mechanism lands at 51s, past the 51s mark"]
    callback = ["NO_CALLBACK: the closing step never returns to 'a cane toad'"]
    assert ep._only_repairable_timing_blocks(passed, late)
    assert ep._only_repairable_timing_blocks(passed, late + callback)
    # Any other causal failure, a failed contract, or nothing at all still takes the old path.
    assert not ep._only_repairable_timing_blocks(passed, late + ["DUPLICATE_ROLE: two reversals"])
    assert not ep._only_repairable_timing_blocks({"passed": False, "errors": []}, late)
    assert not ep._only_repairable_timing_blocks(passed, [])
    assert not ep._only_repairable_timing_blocks(passed, ["storyboard could not be built (X)"])


def test_word_budget_codes_are_bounded_edits_too():
    """Attempt 7: LONG_HOOK (19 vs 18 words) plus SOFT_HINGE (11 vs 10) replanned a draft whose
    spine had passed first time; both budgets are rewritten to fit before the storyboard gate."""
    passed = {"passed": True, "score": 80, "errors": []}
    budgets = ["LONG_HOOK: the hook is 19 words against a 18-word budget",
               "SOFT_HINGE: the hinge is 11 words"]
    assert ep._only_repairable_timing_blocks(passed, budgets)
    assert ep._only_repairable_timing_blocks(passed, budgets + ["LATE_MECHANISM: at 51s"])
    assert not ep._only_repairable_timing_blocks(passed, budgets + ["NO_HINGE: none found"])
