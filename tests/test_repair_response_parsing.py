"""The storyboard repair reads the JSON object out of a response that carries prose around it.

V13 (2026-10-08): the model answered "Looking at the error, I only need to fix scene_026 ..."
and then the object; strict json.loads rejected a usable edit and spent the job's one attempt.
"""
import json

import pytest

import storyboard_repair as repair

OBJECT = {"scenes": [{"scene_id": "scene_026", "narration": "One choice, the whole length of it."}]}


def test_bare_json_still_parses():
    assert repair.extract_json_object(json.dumps(OBJECT)) == OBJECT


def test_prose_before_and_after_the_object_is_ignored():
    text = ("Looking at the error, I only need to fix scene_026 (the synthesis).\n\n"
            "Let me trace the beats {in order}: scene_006, scene_008.\n\n"
            + json.dumps(OBJECT) + "\n\nThat re-walks every beat.")
    assert repair.extract_json_object(text) == OBJECT
    assert repair.parse_response_text(text) == OBJECT


def test_a_fenced_block_parses():
    assert repair.extract_json_object("```json\n" + json.dumps(OBJECT) + "\n```") == OBJECT


def test_an_inner_object_without_scenes_is_not_mistaken_for_the_edit():
    text = '{"note": "x"} then ' + json.dumps(OBJECT)
    assert repair.extract_json_object(text) == OBJECT


def test_no_object_is_the_json_parse_rejection():
    assert repair.extract_json_object("I could not produce an edit.") is None
    assert repair.extract_json_object("") is None
    with pytest.raises(json.JSONDecodeError):
        repair.parse_response_text("I could not produce an edit.")
