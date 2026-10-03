"""The rendered gate counts a continuity field only where it was expected, and the measured cut
overrules a judge's slideshow call the same way it overrules a judge that missed one.

Yellowstone opening (2026-10-01, OpenAI judge): raw 83 capped to 49 by broken_continuity (18
honest Falses on 'is the lone wolf in this elk frame') and slideshow_behavior (judge said
slideshow on a 96% boundary-change, 74% source-change cut while also saying multi-shot=true).
"""
import longform_rendered_gate as g


def _det(**over):
    base = {"slideshow": False, "pixel_boundary_change_ratio": 0.957, "source_change_ratio": 0.739,
            "bolt_shot_ratio": 0.0, "verified_information_ratio": 1.0, "threshold_profile": {}}
    base.update(over)
    return base


def test_measured_cut_overrules_a_judge_slideshow_call():
    blind = {"slideshow": True, "multi_shot_storytelling": True, "evidence_accumulates": True}
    checked = g.cross_check_blind_observations(blind, _det())
    assert checked["slideshow"] is False
    assert any("slideshow" in c for c in checked["cross_check_contradictions"])


def test_judge_slideshow_stands_when_the_instrument_agrees_or_cannot_tell():
    blind = {"slideshow": True, "multi_shot_storytelling": False}
    assert g.cross_check_blind_observations(blind, _det(slideshow=True))["slideshow"] is True
    assert g.cross_check_blind_observations(blind, _det(source_change_ratio=0.2))["slideshow"] is True


def test_continuity_false_counts_only_where_expected():
    expected_no = {"opening_object_matches": False, "passed": True,
                   "expected": {"opening_object_matches": False, "location_matches": True}}
    expected_yes = {"opening_object_matches": False, "passed": False,
                    "expected": {"opening_object_matches": True, "location_matches": True}}
    legacy_passed = {"opening_object_matches": False, "passed": True}
    legacy_failed = {"opening_object_matches": False, "passed": False}
    assert g.continuity_failures_for({"state_id": "a", "verification": expected_no}, cast_free=True) == []
    assert g.continuity_failures_for({"state_id": "b", "verification": expected_yes}, cast_free=True) == [
        {"state_id": "b", "field": "opening_object_matches"}]
    assert g.continuity_failures_for({"state_id": "c", "verification": legacy_passed}, cast_free=True) == []
    assert g.continuity_failures_for({"state_id": "d", "verification": legacy_failed}, cast_free=True) == [
        {"state_id": "d", "field": "opening_object_matches"}]
