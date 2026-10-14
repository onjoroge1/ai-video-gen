"""An operator-approved beat sheet is never replaced (2026-10-14).

Aral Sea: the approved sheet failed the spine check, the planner was re-asked, and its new sheet
replaced the approved one -- restoring the per-decade figures the operator removed and dropping
the warning and the Owens Lake comparison the operator kept. The report gave no reason: every
listed role passed, and the failure was evidence-judge calls that never got an answer.
"""
import inspect

import explainer_pipeline as ep
import story_fact_model as sfm

SOURCE = inspect.getsource(ep._generate_script_chunked)


def test_an_approved_sheet_that_does_not_compile_stops_instead_of_being_replanned():
    stop = SOURCE.index("APPROVED_PLAN_DOES_NOT_COMPILE")
    replan = SOURCE.index("Beat sheet did not compile — re-asking the planner once")
    assert stop < replan
    assert "if _correction and _approved:" in SOURCE


def test_the_cold_open_and_spine_replans_skip_an_approved_sheet():
    assert "if _cold_fix and _roles.get(\"compiled\") and not _approved:" in SOURCE
    spine_retry = SOURCE.index("ONE RE-ASK WITH THE VERDICT QUOTED BACK")
    assert "and not _approved" in SOURCE[spine_retry - 300:spine_retry]


def test_unanswered_judge_calls_are_asked_again_before_any_replan_or_candidate_sweep():
    retry = SOURCE.index("AN UNAVAILABLE JUDGE IS NOT A VERDICT")
    assert retry < SOURCE.index("THE OTHER CANDIDATES ARE ALREADY PAID FOR")
    assert retry < SOURCE.index("ONE RE-ASK WITH THE VERDICT QUOTED BACK")


def test_dropping_an_approved_beat_stops_the_run_unless_the_operator_accepts_it():
    assert "APPROVED_BEATS_PRUNED" in SOURCE and "APPROVED_PLAN_ALLOW_PRUNE" in SOURCE
    assert issubclass(ep.ApprovedPlanRefused, ValueError)


def _compiled(**overrides):
    compiled = {
        "assessed": True, "engine_id": "state_programme",
        "coverage": {"required": ["setup"], "supported_by_role": {"setup": 1}, "missing": [],
                     "missing_because": {}, "covered": True},
        "duplicate_across_roles": [], "unrepairable": [], "relationships": [], "narrowed": [],
        "collapsed_duplicates": [], "still_failing": [], "kept_beats": ["event_01"],
        "pruned": [{"beat_id": "event_15", "role": "generalization",
                    "event": "Officials drained Owens Lake to supply water for Los Angeles."},
                   {"beat_id": "event_13", "role": "escalation",
                    "event": "Dust from the exposed lakebed became a public health hazard."}],
        "cascade": {"judgments": [{"beat_id": "event_13", "passed": False,
                                   "verdict": "partially_entailed",
                                   "reason": "the quote does not give the 500 km figure",
                                   "unsupported_details": ["up to 500 km"]}],
                    "evidence": [],
                    "unavailable": [{"beat_id": "event_15", "stage": "evidence",
                                     "verdict": "unavailable",
                                     "reason": "provider_unavailable: OverloadedError: 529"}]},
    }
    compiled.update(overrides)
    return compiled


def test_the_report_says_why_each_beat_was_pruned_and_names_unanswered_judge_calls():
    text = sfm.spine_summary([{"beat_id": "event_01", "role": "setup",
                               "event": {"text": "The sea before 1960."}}], _compiled())
    assert "[partially_entailed] the quote does not give the 500 km figure" in text
    assert "[JUDGE UNAVAILABLE — not a verdict] provider_unavailable: OverloadedError" in text
    assert "EVIDENCE JUDGE UNAVAILABLE" in text and "? event_15 [evidence]" in text
