"""The judge says whether its finding is material; a regex no longer has to guess.

Which narration overshoots actually matter was inferred downstream from the judge's prose, and
every phrasing the regex had not met cost a render:

    "Across open ground."                 -> read as a proper noun
    "Brazilian"                           -> read as an invented place
    "A beekeeper opening a box"           -> read as an invented actor
    "the bees were specifically queens"   -> passed as harmless, and was the real fabrication

Each fix revealed the next phrasing. The judge has just read the event and the narration and
knows which kind it found, so it is asked. The regex stays for judges that do not answer, for
verdicts cached before the field existed, and for the tests that pin its behaviour.
"""
import claim_entailment as ce
from longform_research import fidelity_severity


def test_the_prompt_asks_for_a_severity_and_defines_it():
    shape = ce._FIDELITY_RETURN_SHAPE
    assert '"severity":"material|soft"' in shape
    assert "could repeat as a fact and be wrong" in shape
    assert "Paraphrase" in shape and "staging" in shape


def test_a_judge_rating_is_carried_through_normalisation():
    out = ce._normalise({"verdict": "partially_entailed", "severity": "soft",
                         "unsupported_details": ["Brazilian"], "reason": "x"}, "")
    assert out["severity"] == "soft"


def test_an_unrecognised_rating_is_dropped_so_the_regex_decides():
    out = ce._normalise({"verdict": "partially_entailed", "severity": "kind of bad",
                         "unsupported_details": ["Brazilian"], "reason": "x"}, "")
    assert "severity" not in out


def test_the_judges_rating_beats_the_regex():
    """"Twenty-six queens" would be read as a number; the judge says it is the event's own."""
    assert fidelity_severity(["Twenty-six queens escaped."], "", "partially_entailed",
                             "soft") == "soft"


def test_the_judge_can_also_make_something_blocking():
    assert fidelity_severity(["across open ground"], "", "partially_entailed",
                             "material") == "material"


def test_without_a_rating_the_regex_still_decides():
    assert fidelity_severity(["The year was 1962."], "", "partially_entailed", "") == "material"
    assert fidelity_severity(["Across open ground."], "", "partially_entailed", "") == "soft"


def test_an_unsupported_verdict_outranks_a_soft_rating():
    """No factual core was found at all; there is nothing left to be lenient about."""
    assert fidelity_severity([], "", "unsupported", "soft") == "material"
