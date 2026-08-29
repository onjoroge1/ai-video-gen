"""A shape wobble in visual_beats must cost the extra fields, not the whole beat.

The planner returns visual_beats as an array of objects. A prompt edit shifted it to an array
of plain phrases, and _visual_beats dropped every one of them silently because they were not
dicts. The scene compiled to ZERO states, and the opening gate then reported "every opening
beat requires two to six evidence states" about a scene whose beats were all present and
perfectly readable -- run 72c7a9ca, which had already paid for its first image.
"""

from longform_evidence import _visual_beats


def test_bare_string_beats_are_coerced_not_discarded():
    scene = {"visual_beats": ["Alex leans into the microscope", "curved shapes swarm the mucosa"]}

    beats = _visual_beats(scene)

    assert len(beats) == 2, "string beats were dropped instead of coerced"
    assert beats[0]["anchor_phrase"] == "Alex leans into the microscope"


def test_object_beats_are_unchanged():
    scene = {"visual_beats": [
        {"anchor_phrase": "a b c", "purpose": "evidence", "visual": "slide"},
        {"anchor_phrase": "d e f", "purpose": "action"},
    ]}

    beats = _visual_beats(scene)

    assert len(beats) == 2
    assert beats[0]["purpose"] == "evidence", "object fields must survive"


def test_unusable_entries_are_still_dropped():
    # Coercion is not credulity: nothing here carries an anchor phrase.
    scene = {"visual_beats": [None, "", "   ", {"purpose": "evidence"}, 42]}

    assert _visual_beats(scene) == []


def test_a_mixed_list_keeps_everything_usable():
    scene = {"visual_beats": ["a phrase", {"anchor_phrase": "another phrase"}, None]}

    assert len(_visual_beats(scene)) == 2
