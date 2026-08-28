"""An operator-supplied script skips the planner and the research dossier.

Two Opus calls disappear when the operator writes the script: the beat sheet is already
written, and they own the facts, so the dossier has nothing to verify that they have not
already asserted. Sourcing stays mandatory when the PIPELINE writes the script, because there
it is asserting claims nobody has checked.
"""

import explainer_pipeline as ep


def test_a_note_is_not_a_script():
    # The common case: creative direction, which must keep working exactly as before.
    assert ep.parse_provided_script("Make it punchy and cinematic.") is None
    assert ep.parse_provided_script("") is None
    assert ep.parse_provided_script(None) is None


def test_the_marker_must_open_the_field():
    # A brief that merely mentions the word is direction, not a script. Treating it as one
    # would silently throw away the operator's actual note and render their brief as narration.
    assert ep.parse_provided_script("Use a SCRIPT: style tone") is None


def test_blank_line_separated_scenes():
    scenes = ep.parse_provided_script(
        "SCRIPT:\nA doctor drinks the broth.\n\nRewind to 1982.\n\nThe bacteria survive.")

    assert scenes == ["A doctor drinks the broth.", "Rewind to 1982.",
                      "The bacteria survive."]


def test_numbered_scenes_on_their_own_lines():
    scenes = ep.parse_provided_script(
        "script:\nScene 1: One line here.\nScene 2: Two line here.")

    assert scenes == ["One line here.", "Two line here."]


def test_a_year_does_not_split_a_scene():
    """The reason numbering must be line-anchored.

    Splitting on any digits followed by a period would cut "In 1982. Stress was blamed" into
    two scenes at the year. Real narration is full of dates and figures, so a mid-line rule
    would quietly shred exactly the scripts this feature exists to accept.
    """
    scenes = ep.parse_provided_script(
        "SCRIPT:\nIn 1982. Stress was blamed for 90. percent of cases.")

    assert scenes == ["In 1982. Stress was blamed for 90. percent of cases."]


def test_research_is_required_only_when_the_pipeline_writes():
    assert ep.research_is_required("punchy and cinematic") is True
    assert ep.research_is_required("") is True
    assert ep.research_is_required("SCRIPT:\nOne.\n\nTwo.") is False
