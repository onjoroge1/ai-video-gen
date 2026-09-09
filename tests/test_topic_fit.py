"""Does the question have a story in it, asked before any research is bought.

Measured cost of not asking: "Why don't Americans eat hippo meat?" spent $3.20 across four runs and
never produced a spine. Not the engine and not the budget -- the question names an ABSENCE with
parallel causes, so research returned 21 verified claims split across a 1910 congressional episode
and modern African conservation, and one spine cannot be built from two stories.
"""
import json

import pytest

import topic_fit as tf


def _judge(payload):
    """A judge that returns whatever the fixture decides, and records what it was asked."""
    seen = {}

    def judge(prompt, system=""):
        seen["prompt"], seen["system"] = prompt, system
        return json.dumps(payload)

    return judge, seen


def test_an_absence_question_is_refused_before_research_is_bought():
    judge, seen = _judge({
        "episode": "", "intent": "", "inversion": "", "verdict": "no_story",
        "reason": "an absence with parallel causes, not one episode that turned",
        "narrower_question": "Why did America nearly fill its rivers with hippos?"})
    result = tf.screen("Why don't Americans eat hippo meat?", judge=judge)
    assert result["verdict"] == tf.NO_STORY and tf.blocks(result)
    assert result["signals"]["absence_framing"] is True
    assert "hippos" in tf.report("q", result)


def test_the_hanoi_question_fits():
    judge, _ = _judge({"episode": "the 1902 Hanoi rat bounty", "intent": "fewer rats",
                       "inversion": "residents farmed rats to earn the bounty",
                       "verdict": "fits", "reason": "one episode, and the outcome turns",
                       "narrower_question": ""})
    result = tf.screen("Why did paying people to kill rats make Hanoi worse?", judge=judge)
    assert result["verdict"] == tf.FITS and not tf.blocks(result)


def test_needs_narrowing_does_not_block():
    """The episode is real and the operator may know exactly which one they mean."""
    judge, _ = _judge({"episode": "the 1910 American Hippo Bill", "intent": "cheap meat",
                       "inversion": "", "verdict": "needs_narrowing", "reason": "buried",
                       "narrower_question": "Why did America nearly import hippos?"})
    result = tf.screen("Why don't Americans eat hippo meat?", judge=judge)
    assert result["verdict"] == tf.NEEDS_NARROWING and not tf.blocks(result)
    assert 'try:' in tf.report("q", result)


def test_an_outage_is_not_a_verdict_about_a_question():
    """Confirmed live: with the provider returning 400, four questions screened UNKNOWN at $0.00.

    A screen that fails closed refuses good questions for reasons that have nothing to do with them.
    """
    def dead(prompt, system=""):
        raise RuntimeError("provider down")

    result = tf.screen("Why did the bounty backfire?", judge=dead)
    assert result["verdict"] == "unknown" and result["screened"] is False
    assert not tf.blocks(result)
    assert tf.screen("q", judge=None)["screened"] is False
    assert not tf.blocks(tf.screen("q", judge=None))


def test_unparseable_and_unrecognised_verdicts_do_not_block():
    junk, _ = _judge({"verdict": "maybe", "reason": "?"})
    assert tf.screen("q", judge=junk)["verdict"] == "unknown"

    def prose(prompt, system=""):
        return "I think this is a fine topic!"

    assert not tf.blocks(tf.screen("q", judge=prose))


def test_the_screen_can_be_observed_without_refusing(monkeypatch):
    judge, _ = _judge({"verdict": "no_story", "reason": "no turn", "episode": "",
                       "intent": "", "inversion": "", "narrower_question": ""})
    result = tf.screen("q", judge=judge)
    assert tf.blocks(result), "on by default; the point is to spend nothing"
    monkeypatch.setenv("TOPIC_FIT", "off")
    assert not tf.blocks(result) and not tf.enforced()


def test_the_judge_is_told_what_the_series_actually_is():
    """Read off the corpus, not invented: every reference is one episode whose outcome inverted."""
    judge, seen = _judge({"verdict": "fits", "reason": "", "episode": "", "intent": "",
                          "inversion": "", "narrower_question": ""})
    tf.screen("Why did the bounty backfire?", judge=judge)
    for reference in ("rat tail", "Washington DC", "Haiti"):
        assert reference in seen["system"], "the examples are the corpus's own"
    assert "Falling short is NOT an inversion" in seen["prompt"], \
        "the distinction that rejects most near-misses"


def test_deterministic_signals_are_advisory_only():
    """They have been wrong twice in this codebase. They inform the call; they never rule."""
    assert tf.signals("Why don't Americans eat hippo meat?")["absence_framing"]
    assert tf.signals("Why did the 1902 bounty backfire?")["time_anchor"]
    # An absence-framed question the judge likes is still allowed through.
    judge, _ = _judge({"verdict": "fits", "reason": "real episode", "episode": "x",
                       "intent": "y", "inversion": "z", "narrower_question": ""})
    assert not tf.blocks(tf.screen("Why don't we use nuclear ships?", judge=judge))
