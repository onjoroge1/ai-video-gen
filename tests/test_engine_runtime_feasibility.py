"""Engine/runtime feasibility, decided before the first paid call.

An engine's required roles each need a beat, and the beat-sheet planner will not write below a
25-word floor, so every engine has a hard minimum word count. The runtime contract has a hard
maximum. When the minimum exceeds the maximum the plan is over budget before a word is written and
nothing downstream recovers it -- the beats cannot be dropped (the engine requires them) and they
cannot be shortened (the planner overshoots the ask rather than obeying it).

Job act_de546a5c is the case these tests exist for: a 60-second request planned as
backfiring_solution, which needs 225 words against a 176-word ceiling. It was unrenderable when it
was proposed, and the pipeline bought research, a script and a fact-check pass before the storyboard
reported ENGINE_MISSING_ROLE and LATE_MECHANISM. 77% of the job's ceiling went on proving the story
could not be told.
"""
import pytest

import causal_story as cs
import explainer_pipeline as ep
import story_engines as se


def test_the_production_pairing_is_rejected_before_any_call():
    """60s of backfiring_solution is arithmetic, not taste."""
    fit = ep._engine_runtime_fit(se.BACKFIRING_SOLUTION, 60)
    assert not fit["fits"]
    assert fit["minimum_beats"] == 8  # the compounded exploit also supplies the reversal
    assert fit["words_demanded"] == 8 * ep._WORD_FLOOR
    assert fit["words_demanded"] > fit["word_ceiling"]


def test_the_same_engine_fits_once_the_runtime_pays_for_its_beats():
    assert ep._engine_runtime_fit(se.BACKFIRING_SOLUTION, 90)["fits"]
    assert ep._minimum_feasible_runtime(se.BACKFIRING_SOLUTION, 1) == 67


@pytest.mark.parametrize("engine_id", sorted(se.ENGINES))
def test_every_engine_states_a_minimum_workable_runtime(engine_id):
    """A feasibility gate that cannot say what to change is a gate that only blocks."""
    shortest = ep._minimum_feasible_runtime(engine_id, 1)
    assert shortest > 0, f"{engine_id} never fits any runtime"
    assert ep._engine_runtime_fit(engine_id, shortest)["fits"]
    assert not ep._engine_runtime_fit(engine_id, shortest - 1)["fits"]


def test_minimum_beats_matches_what_the_planner_actually_reserves():
    """The gate and the planner must agree, or the gate passes plans the planner then breaks.

    Escalation is the one required role the contract expects to repeat, so it costs
    MIN_ESCALATIONS beats rather than one.
    """
    for engine_id, engine in se.ENGINES.items():
        expected = len(set(engine["required"]) - {cs.ESCALATION}) + cs.MIN_ESCALATIONS
        assert se.minimum_beats(engine) == expected, engine_id


def test_sixty_seconds_narrows_the_menu_and_ninety_restores_it():
    short = ep._feasible_engines(60)
    assert se.BACKFIRING_SOLUTION not in short
    assert se.ACCUMULATING_INDICTMENT in short
    assert set(ep._feasible_engines(90)) == set(se.ENGINES)


def test_the_selector_never_offers_an_engine_that_cannot_fit(monkeypatch):
    """Runtime fit reaches the model as prose that calls itself 'not a gate or an engine ban'.

    A preference expressed in prose loses to the model's read of which shape the topic has, so the
    impossible engines are removed from the menu instead of argued against.
    """
    seen = {}

    class _Messages:
        def create(self, **call):
            seen["prompt"] = call["messages"][0]["content"]
            raise RuntimeError("no network in tests")

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    chosen = ep._select_story_engine("Why did the fix backfire?", 60)

    assert se.BACKFIRING_SOLUTION not in seen["prompt"]
    assert se.ACCUMULATING_INDICTMENT in seen["prompt"]
    # And the fallback obeys the same gate. The default engine is the longest of the five and the
    # first to fall out of a short runtime, so falling back to it blindly would reintroduce exactly
    # the pairing this gate exists to prevent.
    assert chosen in ep._feasible_engines(60)
    assert chosen != se.DEFAULT_ENGINE


def test_a_model_choice_outside_the_offered_set_is_not_honoured(monkeypatch):
    class _Messages:
        def create(self, **call):
            return type("R", (), {
                "content": [type("C", (), {"text": '{"engine":"backfiring_solution","why":"x"}'})()],
                "usage": type("U", (), {"input_tokens": 1, "output_tokens": 1})()})()

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    monkeypatch.setattr(ep, "_msg_cost", lambda usage: 0.0)
    assert ep._select_story_engine("Why?", 60) != se.BACKFIRING_SOLUTION


def test_a_replan_pinning_an_impossible_engine_fails_before_the_sheet_is_bought(monkeypatch):
    """A pin skips selection, so it is the one path that can still reach an infeasible pairing."""
    calls = []

    class _Messages:
        def create(self, **call):
            calls.append(call)
            raise AssertionError("the sheet must not be purchased for an impossible plan")

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    with pytest.raises(ValueError) as excinfo:
        ep._generate_script_chunked("Why?", 60, "s", "", 12, causal_lane=True,
                                    pinned_engine=se.BACKFIRING_SOLUTION)
    message = str(excinfo.value)
    assert "8 beats" in message and "200 words" in message
    assert "67s" in message, "the operator must be told what to change, not only that it failed"
    assert not calls


def test_no_engine_fits_a_very_short_runtime_and_the_error_says_the_shortest():
    with pytest.raises(ValueError) as excinfo:
        ep._select_story_engine("Why?", 20)
    assert "No narrative engine fits" in str(excinfo.value)
    assert "59s" in str(excinfo.value)
