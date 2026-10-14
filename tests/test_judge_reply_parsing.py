"""A judge that reasons before its verdict still returns a verdict (2026-10-14).

The Aral Sea dust beat came back "unusable judge verdict ''" on every attempt: the judge wrote
three paragraphs and then a correct partially_entailed JSON object, and only bare or fenced JSON
parsed. The planner's "parallel" scope read as the primary story for the same reason of spelling.
"""
import claim_entailment as ce
import story_fact_model as sfm

PROSE_THEN_JSON = (
    "Looking at the statement's three parts:\n\n1. c30 supports the pesticides {aldrin, lindane}.\n"
    "The main issue: DDT is not in the passage.\n\n"
    '{"verdict":"partially_entailed","supported_core":"aldrin and lindane",'
    '"unsupported_details":["DDT is not in c30"],"reason":"DDT unsupported"}')


def test_the_last_json_object_after_prose_is_the_verdict():
    assert ce.parse_verdict(PROSE_THEN_JSON)["verdict"] == "partially_entailed"


def test_bare_and_fenced_json_still_parse_and_nothing_parses_to_empty():
    assert ce.parse_verdict('{"verdict": "entailed"}')["verdict"] == "entailed"
    assert ce.parse_verdict('```json\n{"verdict": "contradicted"}\n```')["verdict"] == "contradicted"
    assert ce.parse_verdict("I cannot decide.") == {}
    assert ce.parse_verdict("") == {}


def test_parallel_is_read_as_the_comparison_scope():
    assert sfm.scope_of({"scope": "parallel"}) == sfm.PARALLEL_CASE
    assert sfm.scope_of({"scope": "parallel_case"}) == sfm.PARALLEL_CASE
    assert sfm.scope_of({"scope": "elsewhere"}) == sfm.PRIMARY_STORY
