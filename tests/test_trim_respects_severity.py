"""A sentence is deleted only for a finding that would actually stop the run.

Lane C wrote 581 words, the top-up brought it to 608, the claim-ledger repair deleted 247 of
them, and the runtime contract then reported 133s against a 300s target. The trim was taking
every NARRATION_EXCEEDS_EVENT row, including the soft ones that do not block -- so the pipeline
was paying for length with one hand and throwing it away with the other, and every short film
this project has shipped was read as the writer's fault.
"""
from explainer_pipeline import _trim_unsupported_sentences


def _script():
    return {"scenes": [{"beat_id": "event_1", "narration":
                        "The swarm left the box. It moved across open ground. "
                        "The forest took it in."}]}


def test_a_soft_finding_never_costs_a_sentence():
    script = _script()
    before = script["scenes"][0]["narration"]
    report = {"errors": [{"code": "NARRATION_EXCEEDS_EVENT", "scene": "event_1",
                          "severity": "soft",
                          "unsupported_details": ["It moved across open ground."]}]}
    assert _trim_unsupported_sentences(script, report) == 0
    assert script["scenes"][0]["narration"] == before


def test_a_material_finding_still_costs_its_sentence():
    script = _script()
    report = {"errors": [{"code": "NARRATION_EXCEEDS_EVENT", "scene": "event_1",
                          "severity": "material",
                          "unsupported_details": ["It moved across open ground."]}]}
    dropped = _trim_unsupported_sentences(script, report)
    assert dropped == 1
    assert "across open ground" not in script["scenes"][0]["narration"]


def test_an_unscored_finding_is_still_trimmed():
    """Legacy reports carry no severity; absent is not soft, and must stay blocking."""
    script = _script()
    report = {"errors": [{"code": "NARRATION_EXCEEDS_EVENT", "scene": "event_1",
                          "unsupported_details": ["It moved across open ground."]}]}
    assert _trim_unsupported_sentences(script, report) == 1
