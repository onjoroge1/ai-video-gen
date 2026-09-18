"""Two defects measured on one delivered 268.5s film.

1. `longform_shots` carried its own weaker copy of the phrase search `audio_timing` already had.
   The copy had no joiner splitting, no number-word normalisation and no fuzzy fallback, so anchors
   that audio_timing resolved at confidence 1.0 failed there -- 19 of 43 delivered shots compiled as
   `timing_source: "repaired"`, pinned to `previous + MIN_SHOT_SECONDS`, which is what produced a row
   of 1.5s floor shots with the scene's whole remainder on the tail.

2. `verify_evidence_asset` turned EVERY exception into a rejection-shaped dict. 5 of the film's 6
   dropped states carry `evidence verifier unavailable: BadRequestError ... Your credit balance is
   too low` -- the judge never looked at them. They were treated as refused, which bought 10 extra
   images that could not be judged either and then deleted the states, handing their seconds to a
   surviving neighbour: [1.5, 1.5, 43.08].
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import audio_timing
import explainer_pipeline as ep
import longform_shots


TIMED = [
    ("Kudzu", 0.0, 0.5), ("spread", 0.5, 1.0), ("sixty", 1.0, 1.5), ("to", 1.5, 1.8),
    ("a", 1.8, 2.0), ("hundred", 2.0, 2.6), ("feet", 2.6, 3.0), ("of", 3.0, 3.2),
    ("new", 3.2, 3.5), ("growth", 3.5, 4.0), ("once-healthy", 4.0, 4.8), ("forest", 4.8, 5.4),
]


def test_the_two_matchers_are_now_one_function():
    """Not "they agree" -- they are the same callable. Agreement drifts; identity cannot."""
    from longform_shots import _find_phrase_span
    assert audio_timing.find_phrase_span is audio_timing._find_span
    # The wrapper delegates; it does not reimplement. Proven by behaviour on the cases below,
    # and by the module-level export existing at all.
    assert callable(audio_timing.find_phrase_span)
    assert _find_phrase_span(TIMED, "Kudzu spread") == (0.0, 1.0)


@pytest.mark.parametrize("phrase,expected,why", [
    ("sixty to a hundred feet", (1.0, 3.0), "exact match still works"),
    ("60 to a hundred feet", (1.0, 3.0), "number-word normalisation: the old copy had none"),
    ("once healthy forest", (4.0, 5.4), "joiner split: transcriber wrote 'once-healthy'"),
    ("nowhere in this narration", None, "genuinely absent still returns None"),
])
def test_anchors_the_weak_copy_could_not_resolve(phrase, expected, why):
    assert longform_shots._find_phrase_span(TIMED, phrase) == expected, why


def test_a_real_spelling_variant_resolves_fuzzily():
    """The substitution audio_timing's own docstring cites: smouldering vs smoldering.

    Whisper substitutes short tokens and expands contractions. The old copy was exact-match only,
    so every one of these became a repaired shot.
    """
    timed = [("the", 0.0, .2), ("vines", .2, .6), ("still", .6, 1.0),
             ("smoldering", 1.0, 1.8), ("underneath", 1.8, 2.4)]
    assert longform_shots._find_phrase_span(timed, "still smouldering underneath") == (0.6, 2.4)


def test_an_unavailable_verifier_is_distinguishable_from_a_refusal():
    """The whole defect in one assertion: these two outcomes used to be the same dict.

    A refusal carries reasons about the IMAGE and no verifier_available key. An outage carries
    verifier_available=False. Nothing downstream could previously tell them apart, so an outage was
    handled as bad artwork.
    """
    outage = ep.verify_evidence_asset("/nonexistent/none.png", {"state_id": "e01"}, {}, cost_sink=[])
    assert outage["verifier_available"] is False
    assert outage["passed"] is False
    assert "evidence verifier unavailable" in outage["reasons"][0]


def test_the_outage_reason_keeps_the_provider_message():
    """The operator must read the real cause, not "3 states rejected".

    The measured outage was a billing error. If the message is swallowed, the visible symptom is a
    43-second hold and the operator is sent to fix the artwork.
    """
    outage = ep.verify_evidence_asset("/nonexistent/none.png", {"state_id": "e01"}, {}, cost_sink=[])
    assert "FileNotFoundError" in outage["reasons"][0]


def test_a_genuine_refusal_does_not_claim_the_verifier_was_unavailable(monkeypatch):
    """The other direction, so the fix cannot be read as "treat every rejection as an outage".

    A judge that looked and said no must still reject, still carry its reasons, and must NOT set
    verifier_available=False -- otherwise every real visual failure would start aborting runs
    instead of costing a redraw, which is a far worse trade than the bug being fixed.

    Faked at the provider boundary (`_claude`), so the whole body of verify_evidence_asset runs.
    """
    # `passed` is computed from the STATE's own requirements against the model's per-object answers,
    # not from a `passed` field in the reply. So a genuine refusal needs a required object the model
    # reports absent -- an empty state requires nothing and vacuously passes.
    body = ('{"visible_information": true, "required_objects": {"a severed rat tail": false},'
            ' "reasons": ["the required severed tail is not visible"]}')

    class _Reply:
        content = [type("B", (), {"text": body})()]
        usage = type("U", (), {"input_tokens": 10, "output_tokens": 10})()

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {
        "messages": type("M", (), {"create": staticmethod(lambda **kw: _Reply())})()})())
    verdict = ep.verify_evidence_asset(
        __file__, {"state_id": "e01", "required_objects": ["a severed rat tail"]}, {}, cost_sink=[])
    assert verdict["passed"] is False, verdict
    assert verdict.get("verifier_available") is not False, \
        "a judged refusal must not be reported as an outage -- that would abort the run"
    assert "severed tail" in "; ".join(verdict["reasons"])
