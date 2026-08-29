"""The cadence rule must actually be in the prompt the pipeline sends.

story_engine.cadence_block was written for the exact failure being measured, and its
docstring says it must be "injected into EVERY expansion batch". Nothing called it. The
pipeline imports get/resolve/check and no prompt text, and the only other 15-word rule
lives in the beat-sheet prompt, which does not write narration -- so the model producing
the narration was never told to write long sentences, and every run came back at 5-10%
against a 25% floor. Dead prompt text looks exactly like live prompt text in a diff.
"""

import explainer_pipeline as ep
import story_engine


def test_cadence_block_reaches_the_prompt_that_writes_narration():
    # The EXPANSION prompt, not the beat sheet. A sentence-length rule on the beat sheet is
    # inert -- the beat sheet plans beats, it does not write sentences.
    block = ep._cadence_rule_block("evidence_led_mystery")

    assert "15 WORDS OR MORE" in block
    assert "NOT YOUR CHOICE" in block, "the per-scene rule must survive in the sent prompt"


def test_the_spoken_cadence_rule_does_not_argue_against_the_gate():
    # This said "NEVER write every line at the same ~15-word length", naming 15 words as the
    # failure while the gate requires a quarter of sentences to reach it.
    rule = ep._NARRATION_CADENCE

    assert "same ~15-word length" not in rule
    assert "15 words or more" in rule


def test_the_rule_names_the_explaining_roles_it_keys_off():
    # The rule is per-scene and keyed on role, so the roles it names must exist in the
    # format. A renamed role would silently make the requirement unmatchable.
    fmt = story_engine.get("evidence_led_mystery")
    block = story_engine.cadence_block(fmt)

    for role in ("mechanism", "reversal", "consequence", "false_belief"):
        assert role in fmt.roles, f"{role} is named by the cadence rule but not in the format"
        assert role in block


def test_percent_signs_are_literal_in_the_sent_prompt():
    # The block was written with %%-escaping for a %-format that never happened, because
    # it was never sent anywhere. Concatenated directly, %% would reach the model verbatim.
    block = ep._cadence_rule_block("evidence_led_mystery")

    assert "%%" not in block


def test_a_format_without_bands_contributes_nothing():
    # The standard explainer has no bands and must not pick up mystery cadence rules.
    assert story_engine.cadence_block(story_engine.get("default_explainer")) == ""
