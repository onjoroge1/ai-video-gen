"""Story roles compiled from factual functions, so the planner never picks one.

Five Hanoi sheets, cached research, real evidence judge: the same factual event landed in
`escalation`, `hinge` and `mechanism` on different runs. Every placement was defensible, which is
the problem -- the planner was answering an editorial question dressed as a factual one.
"""
import json
from pathlib import Path

import pytest

import event_functions as ef
import story_compiler as sc


def _beat(bid, function, text, frm="", to="", **extra):
    return {"beat_id": bid, "event_function": function,
            "event": {"text": text, "claim_refs": [f"c{bid[-2:]}"]},
            "changes_state": {"from": frm, "to": to}, **extra}


HANOI = [
    _beat("beat_01", ef.ESTABLISHES_PROBLEM, "Rats colonised Hanoi's new sewers.",
          "a new sewer network", "rats are an unwanted infestation in Hanoi"),
    _beat("beat_02", ef.CHANGES_INCENTIVE, "Authorities offered a bounty for every rat tail.",
          "rats are an unwanted infestation in Hanoi", "a rat tail is worth money",
          incentive={"rewarded_measure": "rat tails handed in",
                     "measure_claim_refs": ["c07"],
                     "actual_goal": "fewer living rats in the city",
                     "goal_claim_refs": ["c05"]}),
    _beat("beat_03", ef.APPARENT_SUCCESS, "Tail submissions climbed into the thousands.",
          "a rat tail is worth money", "the programme looks like it is working"),
    _beat("beat_04", ef.EXPLOIT_BEHAVIOR, "Residents cut tails from living rats and released them.",
          "the programme looks like it is working", "a rat is worth more alive than dead"),
    _beat("beat_05", ef.COMPOUNDS_EXPLOIT, "People bred rats on the outskirts to earn the bounty.",
          "a rat is worth more alive than dead", "rats in Hanoi are farmed as a paying crop"),
]


def test_the_planner_never_picks_mechanism_escalation_or_reversal():
    out = sc.compile_roles(HANOI, "backfiring_solution")
    assert out["passed"], sc.summary(out)
    assert out["roles"] == {"beat_01": "setup", "beat_02": "intervention",
                            "beat_03": "false_resolution", "beat_04": "escalation",
                            # the compounded exploit IS the inversion, so it holds the reversal
                            "beat_05": "reversal"}
    assert [d["role"] for d in out["derived"]] == ["mechanism", "reversal"]


def test_the_mechanism_is_the_gap_between_what_paid_and_what_was_wanted():
    derived = sc.derive_mechanism(HANOI[1])
    assert derived["ok"]
    # Two positive propositions. The negation form ("paid for tails, NOT for dead rats") asks the
    # evidence boundary to certify what no source states, and failed Boundary A when it did.
    assert derived["event"]["text"] == ("The reward was paid for rat tails handed in. "
                                        "The goal was fewer living rats in the city.")
    assert " not for " not in derived["event"]["text"]
    assert derived["event"]["claim_refs"] == ["c05", "c07"], \
        "each half brings its own evidence; the intervention's citations reach neither"


def test_an_unevidenced_goal_does_not_compile():
    """What a government wanted is an attribution of intent, not a free schema field."""
    beat = dict(HANOI[1], incentive={"rewarded_measure": "tails", "actual_goal": "fewer rats",
                                     "measure_claim_refs": ["c07"], "goal_claim_refs": []})
    assert sc.derive_mechanism(beat)["code"] == "GOAL_NOT_EVIDENCED"


def test_an_unevidenced_rewarded_measure_does_not_compile():
    """Measured: three sheets cited the announcement for what the clerk accepted. Different facts."""
    beat = dict(HANOI[1], incentive={"rewarded_measure": "a severed rat tail",
                                     "actual_goal": "fewer rats", "measure_claim_refs": [],
                                     "goal_claim_refs": ["c05"]})
    assert sc.derive_mechanism(beat)["code"] == "MEASURE_NOT_EVIDENCED"


def test_rewarding_exactly_what_you_want_is_no_mechanism():
    beat = dict(HANOI[1], incentive={"rewarded_measure": "dead rats delivered",
                                     "actual_goal": "rats delivered dead",
                                     "measure_claim_refs": ["c07"], "goal_claim_refs": ["c05"]})
    assert sc.derive_mechanism(beat)["code"] == "NO_PROXY_GAP"


def test_a_programme_that_merely_failed_is_not_a_reversal():
    """Every one of seven observed endings across five sheets was this sentence."""
    for ending in ("The bounty produced huge tail counts but made no dent in the rat population.",
                   "Despite the tails handed in, the rat population did not fall.",
                   "The scheme was abandoned after three months."):
        compounds = dict(HANOI[4], changes_state={"from": "x", "to": ending})
        result = sc.derive_reversal(HANOI[0], compounds)
        assert not result["ok"], f"accepted mere failure as a reversal: {ending}"
        assert result["code"] == "NO_INVERSION"


def test_a_reversal_must_be_about_the_setups_subject():
    compounds = dict(HANOI[4], changes_state={"from": "x", "to": "colonial budgets tightened"})
    assert sc.derive_reversal(HANOI[0], compounds)["code"] == "NO_INVERSION"


def test_the_reversal_is_computed_from_the_compounded_exploit_not_an_ending_event():
    result = sc.derive_reversal(HANOI[0], HANOI[4])
    assert result["ok"]
    assert result["event"]["text"].startswith("People bred rats")
    assert result["changes_state"]["to"] == "rats in Hanoi are farmed as a paying crop"


def test_hiring_crews_cannot_occupy_the_intervention_slot():
    """Both are government interventions in English; only one changes an incentive."""
    beats = list(HANOI)
    beats.insert(1, _beat("beat_1a", ef.CHANGES_INCENTIVE,
                          "Officials hired Vietnamese sewer crews to kill rats.",
                          "rats are an unwanted infestation", "crews are hunting rats"))
    codes = [i["code"] for i in sc.compile_roles(beats, "backfiring_solution")["issues"]]
    assert "MULTIPLE_INCENTIVE_CHANGES" in codes


def test_a_missing_function_names_what_it_was_for():
    beats = [b for b in HANOI if sc.function_of(b) != ef.COMPOUNDS_EXPLOIT]
    issues = sc.compile_roles(beats, "backfiring_solution")["issues"]
    assert any(i["code"] == "MISSING_EVENT_FUNCTION" and "compounds_exploit" in i["message"]
               for i in issues)


def test_outcome_state_is_never_load_bearing():
    """Measured: the archives record the failure, not the inversion. It must not be required."""
    assert ef.OUTCOME_STATE in ef.CONTEXTUAL_FUNCTIONS
    assert ef.OUTCOME_STATE not in ef.map_for("backfiring_solution").required
    assert ef.map_for("backfiring_solution").role_for(ef.OUTCOME_STATE) == "context", \
        "explicitly non-causal, so it cannot inherit a role from the pacing vocabulary"


def test_other_engines_do_not_inherit_the_bounty_contract():
    """An accidental invention has no incentive to change."""
    for engine in ("accidental_invention", "power_reversal", "almost_happened_plan",
                   "accumulating_indictment"):
        assert ef.map_for(engine) is None
        assert sc.compile_roles(HANOI, engine)["compiled"] is False


def test_hinge_is_not_a_factual_function():
    """It absorbed exploit_behavior twice and the ending once. It is a way of speaking."""
    assert "hinge" not in ef.EVENT_FUNCTIONS
    assert "hinge" not in ef.map_for("backfiring_solution").to_role.values()


def test_the_measured_endings_are_the_fixture_this_was_built_from():
    """Regression guard on the evidence, not just the rule."""
    sheets = json.loads((Path(__file__).parent.parent / "measurements" /
                         "hanoi_five_sheets.json").read_text())
    endings = [b for s in sheets["samples"]
               for b in ((s.get("spine") or {}).get("beats") or [])
               if (b.get("role") or "") == "reversal"]
    assert endings, "the five-sheet measurement must stay in the repo"
    failures = sum(1 for b in endings
                   if ef._MERE_FAILURE.search((b.get("event") or {}).get("text") or ""))
    assert failures, "every observed reversal reported failure rather than inversion"


def test_a_sheet_with_no_declared_functions_falls_back_rather_than_compiling_from_nothing():
    """Legacy sheets predate this contract. Compiling them would assign roles from nothing."""
    legacy = [{"beat_id": "beat_01", "role": "escalation", "beat": "something happened"}]
    out = sc.compile_roles(legacy, "backfiring_solution")
    assert out["compiled"] is False and "no beat declares an event_function" in out["reason"]
    assert out["beats"] == legacy, "the sheet is handed back untouched"


def test_the_derived_beats_are_spliced_into_causal_order():
    out = sc.compile_roles(HANOI, "backfiring_solution")
    spliced = sc.splice_derived(out["beats"], out)
    roles = [b.get("role") for b in spliced]
    assert roles == ["setup", "intervention", "mechanism", "false_resolution",
                     "escalation", "reversal"], "one event, one required role"
    assert [b["n"] for b in spliced] == list(range(1, 7)), "renumbered after the splice"
    derived = [b for b in spliced if b.get("derived") or b.get("derived_from")]
    assert all(b["event"]["claim_refs"] for b in derived), "a derived beat still cites evidence"
    reversal = next(b for b in spliced if b["role"] == "reversal")
    assert reversal["event"]["text"].startswith("People bred rats"), \
        "the reversal keeps the sourced event; only its declared state transition is computed"
    assert reversal["changes_state"] == {"from": "rats are an unwanted infestation in Hanoi",
                                         "to": "rats in Hanoi are farmed as a paying crop"}


def test_the_goal_is_normalised_into_the_derived_sentence():
    """Observed: 'The goal was Reduce Hanoi's rat population.' -- and the judge rejected it."""
    beat = dict(HANOI[1], incentive={"rewarded_measure": "A severed rat tail.",
                                     "actual_goal": "Reduce Hanoi's rat population.",
                                     "measure_claim_refs": ["c07"], "goal_claim_refs": ["c05"]})
    text = sc.derive_mechanism(beat)["event"]["text"]
    assert text == ("The reward was paid for a severed rat tail. "
                    "The goal was reduce Hanoi's rat population.")
    assert ".." not in text and " Reduce" not in text
    assert sc._phrase("US bounty payments") == "US bounty payments", "acronyms keep their case"


def test_the_prompt_asks_for_what_the_clerk_accepted_not_what_was_announced():
    """4 of 5 sheets filled rewarded_measure with 'every dead rat' -- the announcement, not the
    proof -- which erases the proxy gap the whole story turns on."""
    source = open(__import__("explainer_pipeline").__file__, encoding="utf-8").read()
    block = source[source.index('"rewarded_measure"'):]
    block = block[:block.index('"goal_claim_refs"')]
    assert "accepted as proof" in block and "not what the policy was announced as" in block
    assert "severed rat tail" in block and "never" in block


HANOI_CLAIMS = {
    "c08": {"claim": "In April 1902 the colonial authorities announced a bounty on every dead rat."},
    "c09": {"claim": "The bounty was extended to anyone in the city who brought a rat tail to the "
                     "authorities after civil servants declined to handle thousands of corpses."},
    "c10": {"claim": "The number of tails handed in climbed into the thousands within days."},
    "c05": {"claim": "French medical experts feared the plague reaching Hanoi and wanted the rat "
                     "population reduced."},
}


def test_a_suspect_citation_is_flagged_for_repair_and_does_not_block():
    """Five of five sheets cited the announcement while the right claim sat unused.

    Flagged, never refused. The check is a relevance heuristic: a claim saying "caudal appendage"
    would support "tail" while sharing no vocabulary with it, so a false positive here must not be
    able to kill a story whose citation is fine. Boundary A still rules.
    """
    beat = dict(HANOI[1], incentive={"rewarded_measure": "a severed rat tail",
                                     "measure_claim_refs": ["c08"],
                                     "actual_goal": "fewer rats in the city",
                                     "goal_claim_refs": ["c05"]})
    result = sc.derive_mechanism(beat, HANOI_CLAIMS)
    assert result["ok"], "a suspicion is not a verdict"
    assert result["suspect"]["code"] == "MEASURE_CITATION_SUSPECT"
    assert "c09" in result["suspect"]["message"], "candidates are surfaced, not certified"
    assert "not a ruling on support" in result["suspect"]["message"]


def test_a_flagged_sheet_still_compiles_so_the_judge_gets_the_last_word():
    beats = list(HANOI)
    beats[1] = dict(HANOI[1], incentive={"rewarded_measure": "a severed rat tail",
                                         "measure_claim_refs": ["c08"],
                                         "actual_goal": "fewer rats in the city",
                                         "goal_claim_refs": ["c05"]})
    out = sc.compile_roles(beats, "backfiring_solution", HANOI_CLAIMS)
    assert out["passed"] and len(out["suspicions"]) == 1
    assert "MEASURE_CITATION_SUSPECT" in sc.summary(out)


def test_citing_the_right_claim_compiles():
    beat = dict(HANOI[1], incentive={"rewarded_measure": "a severed rat tail",
                                     "measure_claim_refs": ["c09"],
                                     "actual_goal": "fewer rats in the city",
                                     "goal_claim_refs": ["c05"]})
    result = sc.derive_mechanism(beat, HANOI_CLAIMS)
    assert result["ok"] and result["suspect"] is None


def test_the_citation_check_is_a_pre_filter_not_a_verdict():
    """It asks whether a citation is on the subject. Only Boundary A says whether it supports."""
    assert sc._citations_mention(None, ["c08"], "a severed rat tail"), "no claims -> no opinion"
    assert sc._citations_mention(HANOI_CLAIMS, ["c09"], "")
    # "tail" is distinguishing and c10 has it, so this passes the pre-filter. Whether counting
    # tails proves a tail was ACCEPTED as proof is a question only the judge answers.
    assert sc._citations_mention(HANOI_CLAIMS, ["c10"], "a severed rat tail")
    # "rat" is in every claim in a dossier about rats, so it distinguishes nothing.
    assert sc._distinctive("a severed rat tail", HANOI_CLAIMS) == {"sever", "tail"}
