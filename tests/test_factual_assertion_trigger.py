"""Only an ASSERTION needs a source. A question asserts nothing.

The claim ledger required a citation from any scene containing a digit or a causal word,
searched across the whole scene at once. The format instructs the writer to pose questions
to the viewer, and a question about causation uses exactly that vocabulary -- so a scene
whose only causal word sat inside a question had to cite a source for a sentence making no
claim. Roughly one run in six died here, after the script was paid for.
"""

from longform_research import _asserts_fact


def test_a_causal_question_is_not_an_assertion():
    assert _asserts_fact("So what actually causes an ulcer?") is False


def test_a_causal_statement_still_is():
    assert _asserts_fact("Bacteria cause the ulcer.") is True


def test_a_question_next_to_a_statement_does_not_hide_the_statement():
    # The question is ignored; the assertion beside it still requires a source.
    narration = "So what causes it? The infection causes the ulcer."
    assert _asserts_fact(narration) is True

    # ...and a bare question alongside a neutral line still asserts nothing.
    assert _asserts_fact("So what causes it? He stared at the slide.") is False


def test_numbers_still_require_a_source():
    assert _asserts_fact("In 1982 he swallowed the culture.") is True


def test_a_number_inside_a_question_does_not():
    assert _asserts_fact("Would you drink it to prove a 1982 hunch?") is False


def test_plain_narration_needs_nothing():
    assert _asserts_fact("He lifted the beaker and drank.") is False
    assert _asserts_fact("") is False
