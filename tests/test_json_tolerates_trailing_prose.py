"""A complete JSON object followed by prose is an answer, not a failure.

"JSONDecodeError: Extra data: line 1 column 12464" killed two lanes mid-run -- once inside the
repair call that exists to rescue the first parse failure, so the run paid for a fix and threw
the result away. The model had answered correctly and then kept talking.
"""
import json

import pytest

from explainer_pipeline import _first_json_value


def test_an_object_followed_by_prose_parses():
    assert _first_json_value('{"scenes": [1, 2]} Hope that helps!') == {"scenes": [1, 2]}


def test_a_leading_sentence_is_skipped():
    assert _first_json_value('Sure thing.\n\n{"a": 1}') == {"a": 1}


def test_a_bare_array_parses():
    assert _first_json_value('[{"id": 1}] and that is all') == [{"id": 1}]


def test_nested_braces_are_not_truncated():
    payload = {"scenes": [{"narration": "a {brace} inside"}, {"narration": "another"}]}
    assert _first_json_value(json.dumps(payload) + "\n\nLet me know!") == payload


def test_text_with_no_json_still_raises():
    with pytest.raises(json.JSONDecodeError):
        _first_json_value("there is no object here")
