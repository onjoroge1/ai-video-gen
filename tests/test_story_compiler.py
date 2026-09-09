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
import story_fact_model as sfm


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
    # "handed in" is trimmed: no claim says who received the tail, and what pays is the object.
    assert derived["event"]["text"] == ("The reward was paid for rat tails. "
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
    beat = dict(HANOI[1], incentive={"rewarded_measure": "dead rats",
                                     "actual_goal": "rats, dead",
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


def test_a_reversal_candidate_requires_a_separate_relationship_judgment():
    compounds = dict(HANOI[4], changes_state={"from": "x", "to": "colonial budgets tightened"})
    candidate = sc.derive_reversal(HANOI[0], compounds)
    assert candidate["ok"]  # lexical differences cannot decide a semantic relationship
    assert candidate["derivation"]["kind"] == "behavior_inversion"
    assert "passed" not in candidate


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
    # almost_happened_plan has its own map now, and its own functions. The three still unmapped
    # keep the model-assigned path until each is measured the way these two were.
    for engine in ("accidental_invention", "power_reversal", "accumulating_indictment"):
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
    assert roles == ["setup", "intervention", "false_resolution", "mechanism",
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
    # Anchor on the SCHEMA, not the first mention: the repair prompt also names these fields.
    block = source[source.index('\'"incentive":{"rewarded_measure"'):]
    block = block[:block.index('"goal_claim_refs"')]
    assert "accepted as proof" in block and "not what the policy was announced as" in block
    assert "severed rat tail" in block and "never" in block


# Sized like a real dossier on purpose. The relevance ranking discounts stems that appear in more
# than half the ledger, which needs a ledger big enough for "half" to mean something: across four
# claims it means two, and "tail" -- the one word separating the claim about what was ACCEPTED
# from the one counting how many ARRIVED -- reads as ubiquitous and gets discarded.
HANOI_CLAIMS = {
    "c03": {"claim": "In the 1890s the French installed modern sewers throughout Hanoi."},
    "c04": {"claim": "Invasive brown rats colonised the new sewer network."},
    "c05": {"claim": "French medical experts feared the plague reaching Hanoi and wanted the rat "
                     "population reduced."},
    "c06": {"claim": "Researchers had linked plague transmission to fleas carried by rodents."},
    "c07": {"claim": "The administration first hired Vietnamese crews to hunt in the sewers."},
    "c08": {"claim": "In April 1902 the colonial authorities announced a bounty on every dead rat."},
    "c09": {"claim": "The bounty was extended to anyone in the city who brought a rat tail to the "
                     "authorities after civil servants declined to handle thousands of corpses."},
    "c10": {"claim": "The number of tails handed in climbed into the thousands within days."},
    "c14": {"claim": "Entrepreneurs on the outskirts bred rats to profit from the bounty."},
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
    assert sc._distinctive("a severed rat tail", HANOI_CLAIMS) == {"sever", "tail"}, \
        "\"rat\" is in most of the ledger and distinguishes nothing"
    # And the ranking that follows from it puts the claim about what was ACCEPTED first.
    assert sc.propose_measure_claims(HANOI_CLAIMS, "a severed rat tail")[0] == "c09"


def test_the_ranking_skips_claims_about_the_scholarship_and_other_cases():
    """A claim ABOUT the research is not evidence of the events it describes, and it scores well.

    Measured on the real dossier: ranking a goal about "Hanoi's rat population and the plague risk
    it carried" put "Vann's study is a scholarly work ... presenting the failure of the Hanoi rat
    bounty" FIRST, ahead of the claim recording the actual plague fear. Same bibliography trap the
    story spine already refuses, one layer down in the citation ranking.
    """
    claims = dict(HANOI_CLAIMS)
    claims["c02"] = {"claim": "Vann's study is a scholarly work published in the OUP Graphic "
                              "Histories series presenting the failed Hanoi rat bounty and the "
                              "plague context that produced it."}
    claims["c17"] = {"claim": "COMPARABLE CASE (USA): Fort Benning offered a bounty per pig tail "
                              "and the feral pig population rose."}
    ranked = sc.rank_claims_for(claims, "to reduce Hanoi's rat population and the plague risk")
    assert "c02" not in ranked, "a claim about the study is not evidence of the episode"
    assert "c17" not in ranked, "a comparable case can never source the primary story"
    assert ranked and ranked[0] == "c05", "the claim recording the plague fear ranks first"


def test_the_rewarded_measure_drops_the_hand_over_clause():
    """Three consecutive samples decorated the measure and failed the boundary on the decoration.

    The schema asks for the bare object -- "No rate, no date, no place -- just the object" -- and
    got "a severed rat tail handed to the authorities", "...presented to the bounty clerk", "one
    cent per rat tail handed in". No claim names who received it, so the derived mechanism failed
    on the clause rather than on anything the story needed. What pays is the object.
    """
    for decorated in ("a severed rat tail handed to the authorities",
                      "a severed rat tail presented to the bounty clerk",
                      "A rat tail brought to the clerk."):
        assert sc.normalise_measure(decorated).endswith("rat tail")
    assert sc.normalise_measure("a severed rat tail") == "a severed rat tail", "already bare"
    assert sc.normalise_measure("") == "", "nothing to trim"
    # It must never trim a measure down to nothing.
    assert sc.normalise_measure("handed to the clerk") == "handed to the clerk"


def test_the_measure_reaches_the_derived_sentence_already_trimmed():
    beat = dict(HANOI[1], incentive={"rewarded_measure": "a severed rat tail handed to the clerk",
                                     "measure_claim_refs": ["c09"],
                                     "actual_goal": "fewer rats in the city",
                                     "goal_claim_refs": ["c05"]})
    text = sc.derive_mechanism(beat, HANOI_CLAIMS)["event"]["text"]
    assert text.startswith("The reward was paid for a severed rat tail.")


# --- almost_happened_plan -----------------------------------------------------------------------

HIPPO = [
    {"beat_id": "e01", "event_function": ef.ESTABLISHES_PROBLEM,
     "event": {"text": "A 1910 meat shortage pushed Congress to look for new protein.",
               "claim_refs": ["h1"]},
     "changes_state": {"from": "cattle supply is falling", "to": "Congress wants new meat"}},
    {"beat_id": "e02", "event_function": ef.PLAN_PROPOSED,
     "event": {"text": "Robert Broussard introduced House Resolution 23261, the American Hippo "
                       "Bill.", "claim_refs": ["h2"]},
     "changes_state": {"from": "Congress wants new meat", "to": "a hippo bill is on the table"}},
    {"beat_id": "e03", "event_function": ef.GAINS_BACKING,
     "event": {"text": "A USDA researcher told the panel it could add a million tons of meat.",
               "claim_refs": ["h3"]},
     "changes_state": {"from": "a hippo bill is on the table", "to": "the bill looks credible"}},
    {"beat_id": "e04", "event_function": ef.COLLAPSE_CAUSE,
     "event": {"text": "The Lacey Act banned importing injurious wildlife.", "claim_refs": ["h4"]},
     "changes_state": {"from": "the bill looks credible", "to": "importing hippos is unlawful"}},
    {"beat_id": "e05", "event_function": ef.WORLD_WITHOUT_IT,
     "event": {"text": "The bill never passed and hippo meat never entered the U.S. diet.",
               "claim_refs": ["h5"]},
     "changes_state": {"from": "importing hippos is unlawful",
                       "to": "American meat stayed cattle, pigs and chickens"}},
]


def test_the_plan_engine_maps_its_own_functions_to_the_shared_roles():
    """Measured: the planner had all of these facts and filed them under the wrong roles.

    The Lacey Act -- what actually killed the 1910 bill -- arrived as an `escalation`, "the Bill
    never passed" arrived as the closing `tool`, and the `mechanism` slot got "U.S. wildlife policy
    distinguishes legal from unsustainable harvesting", a policy generality rather than an event.
    """
    out = sc.compile_roles(HIPPO, "almost_happened_plan")
    assert out["passed"], sc.summary(out)
    assert out["roles"] == {"e01": "setup", "e02": "intervention", "e03": "false_resolution",
                            "e04": "mechanism", "e05": "reversal"}


def test_this_engine_derives_nothing_because_its_mechanism_is_an_event():
    """backfiring_solution must COMPUTE its mechanism; nobody recorded "what pays is not what was
    wanted". Here the mechanism is a thing that happened, so deriving one would manufacture the
    problem the map exists to avoid."""
    assert ef.map_for("almost_happened_plan").derived == ()
    out = sc.compile_roles(HIPPO, "almost_happened_plan")
    assert out["derived"] == [] and not out["suspicions"]
    assert all(not b.get("derived_from") for b in out["beats"])


def test_a_plan_with_no_named_cause_of_death_does_not_compile():
    """"If you cannot name what happened, this is missing rather than abstract"."""
    without = [b for b in HIPPO if b["event_function"] != ef.COLLAPSE_CAUSE]
    issues = sc.compile_roles(without, "almost_happened_plan")["issues"]
    assert any(i["code"] == "MISSING_EVENT_FUNCTION" and "collapse_cause" in i["message"]
               for i in issues)


def test_the_two_engines_do_not_share_a_contract():
    """A bounty story's functions must not become the contract for a plan that never happened."""
    plan, bounty = ef.map_for("almost_happened_plan"), ef.map_for("backfiring_solution")
    assert ef.CHANGES_INCENTIVE not in plan.required, "a shelved plan changes no incentive"
    assert ef.COLLAPSE_CAUSE not in bounty.to_role, "a bounty that ran has no cause of death"
    assert set(plan.required) & set(bounty.required) == {ef.ESTABLISHES_PROBLEM}


def test_a_plan_engine_is_not_asked_for_a_bounty_incentive_block():
    """The incentive block belongs to an engine that DERIVES its mechanism from it.

    A plan that never happened has no rewarded measure, and asking for one is how a prompt teaches
    a model to invent a field to fill -- the same shape as asking for a chapter marker and then
    stripping it before it is spoken.
    """
    plan = sc.factual_plan_prompt("Why?", 90, 9, "almost_happened_plan")
    bounty = sc.factual_plan_prompt("Why?", 90, 9, "backfiring_solution")
    assert '"incentive":' in bounty and "rewarded_measure names" in bounty
    assert '"incentive":' not in plan and "rewarded_measure names" not in plan
    # It still gets everything it does need.
    for function in ef.map_for("almost_happened_plan").required:
        assert function in plan


def test_presentation_devices_attach_to_a_mechanism_nobody_derived():
    """almost_happened_plan maps collapse_cause straight onto the role, so its mechanism beat is
    planner-written and has no `derivation`. Subscripting it raised KeyError('derivation') one step
    after the first hippo sheet whose spine passed."""
    out = sc.compile_roles(HIPPO, "almost_happened_plan")
    sheet = sc.presentation_beats(sc.splice_derived(out["beats"], out), "almost_happened_plan")
    mechanism = next(b for b in sheet if b["role"] == "mechanism")
    assert "derivation" not in mechanism, "this engine derives nothing"
    devices = [b for b in sheet if b.get("presentation_device")]
    assert {b["presentation_device"] for b in devices} >= {"hinge", "tool"}
    for device in devices:
        assert mechanism["beat_id"] in device["context_refs"]
        assert sfm.event_of(device)["text"] == "", "a device asserts no history"


# --- removed_keystone ---------------------------------------------------------------------------

MACQUARIE = [
    {"beat_id": "k1", "event_function": ef.ESTABLISHES_BALANCE,
     "event": {"text": "Feral cats on Macquarie Island preyed on both seabirds and rabbits.",
               "claim_refs": ["m1"]},
     "changes_state": {"from": "an island with introduced cats and rabbits",
                       "to": "cats hold the rabbit population down while killing seabirds"}},
    {"beat_id": "k2", "event_function": ef.SPECIES_MOVED,
     "event": {"text": "From 1985 a programme shot the island's cats to protect the seabirds.",
               "claim_refs": ["m2"]},
     "changes_state": {"from": "cats hold the rabbit population down while killing seabirds",
                       "to": "the cats are being removed"}},
    {"beat_id": "k3", "event_function": ef.HIDDEN_LINK,
     "event": {"text": "The cats had also been the main predator keeping rabbit numbers low.",
               "claim_refs": ["m3"]},
     "changes_state": {"from": "the cats are being removed",
                       "to": "nothing is eating the rabbits"}},
    {"beat_id": "k4", "event_function": ef.POPULATION_RESPONDS,
     "event": {"text": "Rabbit numbers rose to roughly 100,000 after the last cat was killed.",
               "claim_refs": ["m4"]},
     "changes_state": {"from": "nothing is eating the rabbits",
                       "to": "rabbits graze the island unchecked"}},
    {"beat_id": "k5", "event_function": ef.SYSTEM_RESETTLES,
     "event": {"text": "Rabbit grazing stripped the island's tussock slopes bare.",
               "claim_refs": ["m5"]},
     "changes_state": {"from": "rabbits graze the island unchecked",
                       "to": "the island's vegetation is gone and the slopes are eroding"}},
]


def test_a_keystone_story_compiles_without_inventing_an_incentive():
    """Measured on Macquarie: backfiring_solution was selected because it was the only mapped
    engine, and its contract made the compiler write "the reward was paid for the count of cats
    killed" for a government eradication that paid no reward. The evidence boundary refused it,
    correctly -- nobody paid a reward for anything."""
    out = sc.compile_roles(MACQUARIE, "removed_keystone")
    assert out["passed"], sc.summary(out)
    assert out["roles"] == {"k1": "setup", "k2": "intervention", "k3": "mechanism",
                            "k4": "escalation", "k5": "reversal"}
    assert out["derived"] == [], "hidden_link is a fact, not a computed relationship"


def test_the_hidden_link_is_required_because_it_is_the_story():
    """Every story of this shape turns on what else the species was doing."""
    without = [b for b in MACQUARIE if b["event_function"] != ef.HIDDEN_LINK]
    codes = [i["code"] for i in sc.compile_roles(without, "removed_keystone")["issues"]]
    assert "MISSING_EVENT_FUNCTION" in codes
    assert ef.HIDDEN_LINK in ef.map_for("removed_keystone").required


def test_this_engine_is_not_asked_for_a_rewarded_measure():
    """No bounty, no proxy, no exploitation. Asking teaches a model to invent one."""
    prompt = sc.factual_plan_prompt("Why?", 90, 9, "removed_keystone")
    assert '"incentive":' not in prompt and "rewarded_measure names" not in prompt
    for function in ef.map_for("removed_keystone").required:
        assert function in prompt
    assert ef.CHANGES_INCENTIVE not in ef.map_for("removed_keystone").to_role
    assert ef.EXPLOIT_BEHAVIOR not in ef.map_for("removed_keystone").to_role


def test_its_roles_are_described_as_ecology_not_as_incentives():
    assert sfm.role_function("mechanism", "removed_keystone") == \
        "what else that species was doing that nobody counted"
    assert sfm.role_function("escalation", "removed_keystone") == \
        "the population no longer held down, surging"
    # And the bounty engine keeps its own.
    assert sfm.role_function("escalation", "backfiring_solution") == \
        "HOW people exploit it, compounding"


def test_the_two_backfire_engines_are_told_apart_by_who_acts():
    """Both answer to "a reasonable fix made things worse", so the premises must differ on the
    thing that actually separates them. Macquarie was selected as backfiring_solution on the old
    wording, and the compiler then invented a bounty for a government cull that paid nobody."""
    import story_engines as se

    bounty = se.ENGINES["backfiring_solution"]["premise"]
    keystone = se.ENGINES["removed_keystone"]["premise"]
    assert "PEOPLE respond" in bounty and "incentive somebody exploits" in bounty
    assert "ECOSYSTEM re-sorts" in keystone and "NOBODY exploits anything" in keystone
    assert "no reward is paid" in keystone
    # And neither premise can be read as the other's story.
    assert "incentive" not in keystone.replace("no reward is paid", "")


def test_a_hinge_never_inherits_an_empty_cause():
    """The hinge sits before its anchor so it inherits the anchor's cause rather than pointing at
    it -- but only if the anchor has one. On removed_keystone the mechanism can be the first beat
    with no antecedent, and the hinge then inherited nothing: ORPHAN_STEP refused a story whose
    spine had passed in full."""
    beats = [dict(b) for b in MACQUARIE]
    beats[2]["caused_by"] = ""            # mechanism with no antecedent
    out = sc.compile_roles(beats, "removed_keystone")
    sheet = sc.presentation_beats(sc.splice_derived(out["beats"], out), "removed_keystone")
    hinge = next(b for b in sheet if b.get("presentation_device") == "hinge")
    assert hinge["caused_by"], "a step after the setup must name the step it follows from"
    assert hinge["caused_by"] == "k2", "falls back along its chain to the intervention"
