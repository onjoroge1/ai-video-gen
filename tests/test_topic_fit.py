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
        "episode": "", "intent": "", "aftermath": "", "channel": "neither",
        "verdict": "no_story",
        "reason": "an absence with parallel causes, not one episode that turned",
        "narrower_question": "Why did America nearly fill its rivers with hippos?"})
    result = tf.screen("Why don't Americans eat hippo meat?", judge=judge)
    assert result["verdict"] == tf.NO_STORY and tf.blocks(result)
    assert result["signals"]["absence_framing"] is True
    assert "hippos" in tf.report("q", result)


def test_the_hanoi_question_fits():
    judge, _ = _judge({"episode": "the 1902 Hanoi rat bounty", "intent": "fewer rats",
                       "aftermath": "residents farmed rats to earn the bounty",
                       "channel": "world", "verdict": "fits",
                       "reason": "one intervention on an animal population, and its aftermath",
                       "narrower_question": ""})
    result = tf.screen("Why did paying people to kill rats make Hanoi worse?", judge=judge)
    assert result["verdict"] == tf.FITS and not tf.blocks(result)


def test_needs_narrowing_does_not_block():
    """The episode is real and the operator may know exactly which one they mean."""
    judge, _ = _judge({"episode": "the 1910 American Hippo Bill", "intent": "cheap meat",
                       "aftermath": "", "channel": "history",
                       "verdict": "needs_narrowing", "reason": "buried",
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
    judge, _ = _judge({"verdict": "no_story", "reason": "no intervention", "episode": "",
                       "intent": "", "aftermath": "", "channel": "neither",
                       "narrower_question": ""})
    result = tf.screen("q", judge=judge)
    assert tf.blocks(result), "on by default; the point is to spend nothing"
    monkeypatch.setenv("TOPIC_FIT", "off")
    assert not tf.blocks(result) and not tf.enforced()


def test_the_judge_is_told_what_the_series_actually_is():
    """Read off the corpus, not invented: every reference is one episode whose outcome inverted."""
    judge, seen = _judge({"verdict": "fits", "reason": "", "episode": "", "intent": "",
                          "aftermath": "", "channel": "world", "narrower_question": ""})
    tf.screen("Why did the bounty backfire?", judge=judge)
    assert "Bolt Explains the World" in seen["system"] and "Bolt Explains History" in seen["system"]
    assert "ANIMALS WIN TIES" in seen["system"], \
        "otherwise HISTORY absorbs a state-run animal campaign and the split collapses"
    # The inversion LAW is gone. It was derived from a corpus that is mostly backfires and would
    # have refused the Aral Sea, where the diversion did exactly what it was designed to do.
    assert "need NOT be the opposite" in seen["prompt"]


def test_deterministic_signals_are_advisory_only():
    """They have been wrong twice in this codebase. They inform the call; they never rule."""
    assert tf.signals("Why don't Americans eat hippo meat?")["absence_framing"]
    assert tf.signals("Why did the 1902 bounty backfire?")["time_anchor"]
    # An absence-framed question the judge likes is still allowed through.
    judge, _ = _judge({"verdict": "fits", "reason": "real episode", "episode": "x",
                       "intent": "y", "aftermath": "z", "channel": "history",
                       "narrower_question": ""})
    assert not tf.blocks(tf.screen("Why don't we use nuclear ships?", judge=judge))


# --- the topic generator for this lane ----------------------------------------------------------

def test_the_causal_topic_prompt_states_the_series_not_just_history():
    """The existing generator serves the simulation shorts; this lane had none, so topics arrived
    by hand and one of them cost $3.20 before anything noticed it had no story in it."""
    import explainer_pipeline as ep

    world, history = ep._causal_topic_system("world"), ep._causal_topic_system("history")
    assert "Hanoi" in world and "cane toads" in world
    assert "Aral Sea" in history and "Decree 770" in history
    for system in (world, history):
        assert "hippo meat" in system, "the measured failure is named so it is not repeated"
        assert "names the SUBJECT, not the shape" in system
        assert "DOCUMENTED AFTERMATH" in system
        assert "INVERT" not in system, "the inversion law is gone; it would refuse the Aral Sea"
    assert "belongs to the OTHER channel" in history, "animals win ties"
    assert "must TARGET the animal population" in world


def test_a_proposed_topic_is_screened_before_it_reaches_an_operator(monkeypatch):
    """A topic must not reach an operator and then be refused by the pipeline that proposed it."""
    import explainer_pipeline as ep

    proposals = {"questions": [
        {"question": "Why did DC pay slave owners to free the people they enslaved?",
         "curiosity_gap": 9},
        {"question": "Why don't Americans eat hippo meat?", "curiosity_gap": 9},
        {"question": "Too dull", "curiosity_gap": 3}]}
    verdicts = {"Why don't Americans eat hippo meat?": "no_story"}

    class _Messages:
        def create(self, **call):
            body = call["messages"][0]["content"]
            if "Propose" in body:
                text = json.dumps(proposals)
            else:
                asked = body.split('"')[1]
                text = json.dumps({"verdict": verdicts.get(asked, "fits"), "reason": "r",
                                   "episode": "e", "intent": "i", "aftermath": "a",
                                   "channel": "history", "narrower_question": ""})
            return type("R", (), {
                "usage": type("U", (), {"input_tokens": 200, "output_tokens": 50})(),
                "content": [type("C", (), {"text": text})()]})()

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    out = ep.generate_causal_topics(channel="history", n=5, min_score=8)
    questions = [item["question"] for item in out]
    assert "Why did DC pay slave owners to free the people they enslaved?" in questions
    assert "Why don't Americans eat hippo meat?" not in questions, "screened out, not shipped"
    assert "Too dull" not in questions, "below the curiosity floor"
    assert out[0]["topic_fit"]["verdict"] == "fits", "the verdict travels with the topic"


def test_a_programme_that_worked_and_cost_everything_is_not_refused():
    """The rule this replaces would have refused the history channel's first episode.

    "Inversion" was derived from a corpus that is mostly backfires, and turned a pattern into a
    law. The Aral Sea diversion did exactly what it was designed to do -- cotton grew. The lake was
    the price, not a reversal, and foreseen harm still counts: the hydrologists knew.
    """
    judge, seen = _judge({"episode": "the Soviet diversion of the Amu Darya and Syr Darya",
                          "intent": "irrigate cotton", "channel": "history",
                          "aftermath": "the Aral Sea lost most of its volume and the fishery died",
                          "verdict": "fits", "reason": "one programme, documented cost",
                          "narrower_question": ""})
    result = tf.screen("Why did diverting two rivers destroy the Aral Sea?", judge=judge)
    assert result["verdict"] == tf.FITS and not tf.blocks(result)
    assert result["channel"] == tf.HISTORY
    assert "foreseen" in seen["system"], "the harm need not have been a surprise"
    assert "succeeded at" in seen["system"].lower() or "SUCCEEDED" in seen["system"]


def test_a_river_diversion_is_not_the_animal_channel():
    """The intervention has to TARGET the animals. Nobody was intervening on the fish."""
    assert "nobody was intervening on the fish" in tf.CHANNELS[tf.WORLD]["requires"]


def test_the_channel_can_be_asserted_and_still_challenged():
    judge, seen = _judge({"verdict": "fits", "channel": "history", "episode": "e", "intent": "i",
                          "aftermath": "a", "reason": "r", "narrower_question": ""})
    tf.screen("Why did Decree 770 fill Romania's orphanages?", channel=tf.HISTORY, judge=judge)
    assert "HISTORY channel" in seen["prompt"] and "belongs to the other one" in seen["prompt"]


def test_the_ui_channels_and_the_screen_share_one_definition():
    """A topic suggested in the UI and refused by the pipeline is the UI arguing with its back end.

    The three science channels this replaces (Earth, Physics, Space) were one channel's breadth
    wearing three labels, and the lane that actually renders fitted none of them.
    """
    import re
    import app

    labels = [c["label"] for c in app.CHANNELS]
    assert labels == ["Bolt Explains the World", "Bolt Explains History"]
    assert [c["topic_channel"] for c in app.CHANNELS] == [tf.WORLD, tf.HISTORY]

    world, history = (c["niche"] for c in app.CHANNELS)
    assert "TARGET the animals" in world, "the World/History boundary, stated to the operator"
    assert "TARGET the animals" in tf.CHANNELS[tf.WORLD]["requires"]
    assert "ANIMALS WIN TIES" in tf._SYSTEM
    # The rule that would otherwise refuse the history channel's own first episode.
    assert "SUCCEEDED at its stated aim" in history
    assert "no requirement that the outcome invert" in history

    source = re.sub(r"\s+", " ", open(app.__file__, encoding="utf-8").read())
    assert 'if channel.get("topic_channel"): topics = ep.generate_causal_topics(' in source, \
        "a causal channel must propose through the screened generator"


def test_the_generator_is_told_to_name_the_right_actor():
    """Measured: "Britain's bounty on the last thylacines". It was the TASMANIAN government's.

    The screen asks whether a topic has a story in it, not whether its framing is true, so a
    confidently misattributed topic sails through and the error lands in the title.
    """
    import explainer_pipeline as ep

    for channel in ("world", "history"):
        system = ep._causal_topic_system(channel)
        assert "NAME THE RIGHT ACTOR" in system
        assert "colonial administration rather than the imperial capital" in system
        assert "an omission costs a rewrite, a wrong attribution costs a video" in system


def test_the_ui_fallback_chips_are_on_brand():
    """These are what an operator sees when the trending research returns nothing.

    The pool was generic science -- "What is gravity?", "Why do cats purr?" -- which offered topics
    the illustrated lane refuses at its own topic screen, so the UI's first suggestion was a
    question its back end would not build.
    """
    import re
    from pathlib import Path

    page = Path("static/index.html").read_text(encoding="utf-8")
    catalogue = tf.editorial_catalogue()
    world, history = catalogue['channels']
    assert len(world['topics']) == 4 and len(history['topics']) == 3
    assert all(t['topic_channel'] == 'world' for t in world['topics'])
    assert all(t['topic_channel'] == 'history' for t in history['topics'])
    assert all(t['status'] == 'research_candidate' for c in catalogue['channels'] for t in c['topics'])
    assert 'Hanoi' in world['topics'][0]['question']
    assert 'Aral Sea' in history['topics'][0]['question']
    assert not any('sparrow' in t['question'].lower() for t in history['topics'])
    assert world['topics'][1]['reference_count'] == 0
    assert '/api/explainer/channels' in page
    for retired in ('What is gravity?', 'Why do cats purr?', 'What is dark matter?'):
        assert retired not in page
