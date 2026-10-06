"""The length top-up may lengthen a line; it may not enlarge the claim.

Lanes B and C of the V4 run both died on the claim ledger after the top-up expanded short
scenes: the writer was told not to add facts and added "the introduced bees were specifically
queens" and "a breeding programme" anyway. The ledger refuses the WHOLE script for that, so a
300-second request produced a failed run instead of a short film -- strictly worse than not
expanding at all.

The guard asks the question with the ledger's own judge and the ledger's own severity threshold,
so the two cannot disagree. An earlier attempt guessed with a vocabulary list instead and held
back "slowly", "clear" and "thing"; a guard that strict starves every film.
"""
from explainer_pipeline import expansion_survives_the_ledger as survives


def _judge(verdict, details=()):
    """A stand-in for the entailment judge, so these tests need no provider."""
    def judge(payload):
        return {"verdict": verdict, "unsupported_details": list(details),
                "supported_core": payload.get("narration", ""), "reason": "test"}
    return judge


def test_a_faithful_expansion_is_kept():
    keep, _ = survives("The colonies sat in their hive boxes, twenty-nine of them.",
                       "Twenty-nine colonies were maintained in hive boxes.",
                       judge=_judge("entailed"))
    assert keep is True


def test_the_expansion_that_failed_the_ledger_is_held_back():
    """Lane B, event_02: queens and a breeding programme, neither in the event."""
    keep, why = survives(
        "Twenty-six queens escaped, brought there for a breeding programme.",
        "Twenty-six swarms escaped from the research station.",
        judge=_judge("partially_entailed",
                     ["The introduced bees were specifically queens.",
                      "The effort was a breeding programme."]))
    assert keep is False
    assert any("queens" in str(d) for d in why), why


def test_any_overshoot_holds_an_expansion_back():
    """Declining costs length; the ledger refusing costs the whole script.

    The gate tolerates soft overshoot because by then refusing is expensive. Here the draft line
    is always available, so the guard blocks a strict superset of what the gate blocks and the
    two can never disagree.
    """
    keep, _ = survives("The swarm moved across open ground in the afternoon light.",
                       "The swarm moved away from the station.",
                       judge=_judge("partially_entailed", ["Across open ground."]))
    assert keep is False


def test_an_invented_actor_is_material():
    keep, _ = survives("A visiting researcher lifted the barrier off.",
                       "In October 1957 the queen excluders were removed.",
                       judge=_judge("partially_entailed", ["A visiting researcher did it."]))
    assert keep is False


def test_an_invented_number_is_material():
    keep, _ = survives("Within four years they had crossed the border.",
                       "They later crossed the border.",
                       judge=_judge("partially_entailed", ["Within four years."]))
    assert keep is False
