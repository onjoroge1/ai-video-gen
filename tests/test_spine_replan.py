"""A CONTRADICTED required role re-asks the planner once, and nothing else does.

narrow_required_roles says "research or replan it" for REQUIRED_ROLE_CONTRADICTED and nothing
replanned. Measured 2026-09-22 on a 300s Four Pests sheet: eleven beats, ten supported, and the
reversal stated a crop-substitution claim backwards. Boundary A refused it correctly and the run
died with no path forward, on the planner's error rather than the evidence's.
"""
import inspect

import story_compiler as sc


def _spine(code, *, passed=False, reason="", beat_id="event_14", role="reversal"):
    return {"passed": passed,
            "unrepairable": [{"code": code, "beat_id": beat_id, "role": role,
                              "message": f"beat {beat_id} is the {role} ..."}] if code else [],
            "cascade": {"evidence": [{"beat_id": beat_id, "verdict": "contradicted",
                                      "reason": reason}] if reason else []}}


def test_a_contradicted_required_role_produces_a_correction_naming_the_beat_and_reason():
    reason = ("The claims say farmers substituted above-ground crops for below-ground sweet "
              "potatoes, but the statement reverses this.")
    correction = sc.contradiction_correction(_spine("REQUIRED_ROLE_CONTRADICTED", reason=reason))
    assert "event_14" in correction and "reversal" in correction and reason in correction
    assert "byte-identical" in correction


def test_only_a_contradiction_is_replanned():
    """Unsupported or missing evidence is not re-rolled until it passes."""
    assert sc.contradiction_correction(_spine("MISSING_REQUIRED_ROLE_SUPPORT")) == ""
    assert sc.contradiction_correction(_spine("ROLE_CONTRACT_FAILED")) == ""
    assert sc.contradiction_correction(_spine("")) == ""
    assert sc.contradiction_correction(_spine("REQUIRED_ROLE_CONTRADICTED", passed=True)) == ""
    assert sc.contradiction_correction({}) == "" and sc.contradiction_correction(None) == ""


def test_the_replan_is_wired_before_the_research_repair_and_keeps_only_a_passing_sheet():
    """Read the pipeline source: the re-ask must sit between the first spine summary and the
    research repair, and must adopt the retry only on `["passed"]`."""
    import explainer_pipeline as ep
    src = inspect.getsource(ep._generate_script_chunked)
    replan = src.index("contradiction_correction(_spine)")
    research = src.index("research_coverage.repair_sheet(")
    raise_at = src.index("raise _sfm.StorySpineUnsupported(_sfm.spine_summary(_sb, _spine)")
    assert replan < research < raise_at
    adopt = src.index('if _retry_prepared["compiled"]["passed"]:')
    assert replan < adopt < research
    assert "spine replan succeeded" in src and "failing on the original" in src
