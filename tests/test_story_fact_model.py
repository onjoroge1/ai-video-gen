"""The deterministic half of the fact model, which runs before any judge call is bought.

Structure is checked first on purpose. A misplaced comparison or an unbound assertion is decidable
by reading fields, and paying a model to notice it is both slower and less certain. The semantic
boundaries in claim_entailment only see beats that already have coherent provenance.
"""
import json
from pathlib import Path

import story_fact_model as sfm


def _beat(**over):
    beat = {
        "beat_id": "breed_rats", "role": "escalation", "scope": "primary_story",
        "event": {"text": "Residents began keeping rats alive to exploit the tail bounty.",
                  "claim_refs": ["c17", "c22"]},
        "narration": "Then somebody noticed: why kill the rat when the tail was the part that paid?",
        "caused_by": "tail_bounty",
        "changes_state": {"from": "rats are pests to be killed",
                          "to": "living rats can generate bounty value"},
    }
    beat.update(over)
    return beat


def _codes(beats, claims_by_case=None, claims=None):
    return {issue["code"] for issue in sfm.validate_structure(beats, claims_by_case, claims)}


# --- invariant 1: a comparison may only occupy the generalization --------------------------------

def test_a_parallel_case_outside_the_generalization_is_caught_structurally():
    """Sample 3's defect, now decidable by reading a field rather than matching text."""
    beat = _beat(scope="parallel_case", parallel_case_id="hanoi_rat_bounty", role="escalation")
    assert "PARALLEL_CASE_OUT_OF_SCOPE" in _codes([beat])


def test_the_same_beat_in_the_generalization_is_fine():
    beat = _beat(scope="parallel_case", parallel_case_id="hanoi_rat_bounty", role="generalization")
    assert "PARALLEL_CASE_OUT_OF_SCOPE" not in _codes([beat])


def test_a_parallel_case_must_say_which_case_it_is():
    beat = _beat(scope="parallel_case", role="generalization")
    assert "PARALLEL_CASE_UNIDENTIFIED" in _codes([beat])


def test_primary_story_beats_are_unaffected_by_the_role_rule():
    for role in ("setup", "intervention", "escalation", "reversal", "tool"):
        assert "PARALLEL_CASE_OUT_OF_SCOPE" not in _codes([_beat(role=role)])


# --- invariant 2: the primary story may not borrow a comparison's evidence -----------------------

def test_a_primary_beat_sourcing_a_parallel_case_claim_is_caught():
    """Evidence about Hanoi cannot support a sentence about Delhi.

    This is the failure that reads as well-sourced: the claim is real, verified and cited, and it is
    about a different country.
    """
    beat = _beat(event={"text": "Residents bred cobras for the bounty.", "claim_refs": ["c99"]})
    codes = _codes([beat], claims_by_case={"hanoi_rat_bounty": ["c99"]})
    assert "PRIMARY_SOURCED_FROM_PARALLEL_CASE" in codes


def test_a_parallel_beat_may_use_its_own_case_claims():
    beat = _beat(scope="parallel_case", parallel_case_id="hanoi_rat_bounty", role="generalization",
                 event={"text": "Hanoi paid a bounty per rat tail.", "claim_refs": ["c99"]})
    codes = _codes([beat], claims_by_case={"hanoi_rat_bounty": ["c99"]})
    assert "PRIMARY_SOURCED_FROM_PARALLEL_CASE" not in codes


def test_a_shared_claim_is_not_owned_by_the_case():
    """Only claims belonging EXCLUSIVELY to a case are restricted."""
    beat = _beat(event={"text": "A bounty was offered.", "claim_refs": ["c50"]})
    assert "PRIMARY_SOURCED_FROM_PARALLEL_CASE" not in _codes([beat], claims_by_case={})


# --- invariant 3: assertion needs an event, discourse does not -----------------------------------

def test_narration_asserting_a_specific_needs_an_event():
    beat = _beat(event={"text": "", "claim_refs": []},
                 narration="Within a year, hundreds of farms had appeared.")
    assert "ASSERTION_WITHOUT_EVENT" in _codes([beat])


def test_a_narrative_connective_needs_no_event_and_no_citation():
    """The artificial-binding problem this layer exists to end.

    "And that changed everything" carries the story without carrying a claim. Demanding a citation
    for it is how every beat came to look sourced while none of them were checkable.
    """
    beat = _beat(event={"text": "", "claim_refs": []},
                 narration="And that changed everything.")
    assert "ASSERTION_WITHOUT_EVENT" not in _codes([beat])


def test_a_rhetorical_question_needs_no_event():
    beat = _beat(event={"text": "", "claim_refs": []},
                 narration="Why kill the rat when the tail was the part that paid?")
    assert "ASSERTION_WITHOUT_EVENT" not in _codes([beat])


def test_an_event_without_evidence_is_caught():
    beat = _beat(event={"text": "Residents bred cobras.", "claim_refs": []})
    assert "EVENT_WITHOUT_EVIDENCE" in _codes([beat])


# --- schema tolerance ----------------------------------------------------------------------------

def test_a_beat_with_no_scope_is_read_as_the_primary_story():
    """An older script has no scope field, and every beat in it was about the video's subject."""
    beat = _beat()
    beat.pop("scope")
    assert sfm.scope_of(beat) == sfm.PRIMARY_STORY


def test_a_bare_string_event_still_binds():
    assert sfm.event_of({"event": "Residents bred cobras."})["text"] == "Residents bred cobras."


def test_the_visual_side_of_the_ceiling_is_collected():
    """Not judged yet, but reachable — so the third boundary needs no schema change.

    A supported event and faithful narration still permit "a vast underground breeding factory with
    hundreds of cages", which reintroduces invented history after the prose passed cleanly.
    """
    beat = _beat(visual="A resident places rats into wooden cages while coins accumulate.",
                 visual_beats=[{"state_after": "cages stacked three high"}])
    assertions = sfm.visual_assertions_for(beat)
    assert any("wooden cages" in item for item in assertions)
    assert any("stacked three high" in item for item in assertions)


def test_a_clean_beat_raises_nothing():
    assert _codes([_beat()]) == set()


# --- invariant 4: the claim must be the right KIND for the beat ----------------------------------

_KINDS = {"c_event": {"claim_kind": "event"}, "c_mech": {"claim_kind": "mechanism"},
          "c_gen": {"claim_kind": "general_principle"}, "c_case": {"claim_kind": "parallel_case"},
          "c_ctx": {"claim_kind": "context"}}


def test_an_escalation_citing_a_mechanism_claim_is_caught():
    """The c12 catch-all, measured: one analytical claim bound to eight of ten beats.

    "The bounty rewarded the metric rather than the goal, and that gap is where the effect
    operates" explains WHY the story happened. It does not evidence THAT residents bred cobras,
    released them, or that the city ended up worse. The model read "explains the story" as
    "supports every event in the story".
    """
    beat = _beat(role="escalation", event={"text": "Residents bred cobras.",
                                           "claim_refs": ["c_mech"]})
    assert "CLAIM_KIND_MISMATCH" in _codes([beat], claims=_KINDS)


def test_the_mechanism_beat_may_cite_the_mechanism_claim():
    """The same claim is correct on the beat whose job is to state the rule."""
    beat = _beat(role="mechanism", event={"text": "Paying for a proxy produces the proxy.",
                                          "claim_refs": ["c_mech", "c_gen"]})
    assert "CLAIM_KIND_MISMATCH" not in _codes([beat], claims=_KINDS)


def test_the_hinge_may_cite_either():
    """The turn can be the moment the mechanism becomes visible, so it accepts both."""
    for ref in ("c_event", "c_mech"):
        beat = _beat(role="hinge", event={"text": "The count never fell.", "claim_refs": [ref]})
        assert "CLAIM_KIND_MISMATCH" not in _codes([beat], claims=_KINDS)


def test_kind_checking_is_skipped_when_the_ledger_has_no_kinds():
    """An older dossier carries no claim_kind. Skip the check rather than guess at it."""
    beat = _beat(role="escalation", event={"text": "x", "claim_refs": ["c_mech"]})
    assert "CLAIM_KIND_MISMATCH" not in _codes([beat], claims=None)
    assert "CLAIM_KIND_MISMATCH" not in _codes([beat], claims={"c_mech": {}})


# --- invariant 5: one comparison per beat, and the close asserts nothing --------------------------

def test_a_tool_beat_carrying_a_factual_event_is_caught():
    """A measured sample gave its close an event about Goodhart's 1975 law, marked primary_story.

    That is neither this story nor a fact the close needs. "Pick up the coin and ask where the
    cobra farms are" is a rhetorical device built from the story, not an addition to it.
    """
    beat = _beat(role="tool", event={"text": "Goodhart's 1975 law holds that a measure under "
                                             "pressure collapses.", "claim_refs": ["c_gen"]})
    codes = _codes([beat], claims=_KINDS)
    assert "CLOSING_BEAT_ASSERTS_HISTORY" in codes
    assert "CLAIM_KIND_MISMATCH" in codes


def test_a_tool_beat_with_no_event_is_clean():
    beat = _beat(role="tool", event={"text": "", "claim_refs": []},
                 narration="So ask: where are the cobra farms?")
    assert _codes([beat], claims=_KINDS) == set()


def test_one_event_bundling_two_comparisons_is_caught():
    """Splitting the beat beats teaching the schema to hold a mess.

    A bundled event cannot be attributed, cited, illustrated or called back cleanly, and
    parallel_case_id can only name one of the two.
    """
    beat = _beat(scope="parallel_case", parallel_case_id="hanoi_rat_bounty", role="generalization",
                 event={"text": "Hanoi paid per rat tail, and fossil pay per fragment led to "
                                "smashed bones.", "claim_refs": ["c_case", "c_other"]})
    codes = _codes([beat], claims_by_case={"hanoi_rat_bounty": ["c_case"],
                                           "fossil_fragment_bounty": ["c_other"]})
    assert "MULTI_PARALLEL_CASE_EVENT" in codes


def test_one_comparison_per_beat_is_fine():
    beat = _beat(scope="parallel_case", parallel_case_id="hanoi_rat_bounty", role="generalization",
                 event={"text": "Hanoi paid a bounty per rat tail.", "claim_refs": ["c_case"]})
    codes = _codes([beat], claims_by_case={"hanoi_rat_bounty": ["c_case"],
                                           "fossil_fragment_bounty": ["c_other"]})
    assert "MULTI_PARALLEL_CASE_EVENT" not in codes


# --- claim_kind is research-owned, and a doubted label does not govern ----------------------------

def test_an_unknown_kind_skips_the_gate_rather_than_governing_it():
    """A classifier that is unsure must say so, not pick the kind that makes validation easiest."""
    beat = _beat(role="escalation", event={"text": "x", "claim_refs": ["c_unk"]})
    assert "CLAIM_KIND_MISMATCH" not in _codes(
        [beat], claims={"c_unk": {"claim_kind": "unknown"}})


def test_a_low_confidence_label_is_treated_as_unknown():
    """A label its own classifier doubts is exactly the label that should not gate anything."""
    beat = _beat(role="escalation", event={"text": "x", "claim_refs": ["c_mech"]})
    doubted = {"c_mech": {"claim_kind": "mechanism", "claim_kind_confidence": 0.3}}
    assert "CLAIM_KIND_MISMATCH" not in _codes([beat], claims=doubted)
    confident = {"c_mech": {"claim_kind": "mechanism", "claim_kind_confidence": 0.95}}
    assert "CLAIM_KIND_MISMATCH" in _codes([beat], claims=confident)


# --- the hinge accepts mechanism evidence without becoming exposition -----------------------------

def test_a_hinge_that_announces_a_law_is_caught():
    """Allowing mechanism on the hinge must not license "this demonstrates Goodhart's Law"."""
    for exposition in ("This demonstrates Goodhart's Law.",
                       "Goodhart's law holds that a measure under pressure collapses.",
                       "Any proxy is only a stand-in for the goal."):
        beat = _beat(role="hinge", event={"text": exposition, "claim_refs": ["c_mech"]})
        assert "HINGE_WITHOUT_TURN" in _codes([beat], claims=_KINDS), exposition


def test_a_hinge_naming_the_flaw_is_fine_on_mechanism_evidence_alone():
    """The case a first version of this rule got wrong.

    Requiring the hinge to cite an event/context/outcome claim rejected a real hinge whose only
    support was the analytical claim it was correctly naming. Whether a sentence is a turn or a law
    is a question about the sentence, not about its citations.
    """
    for turn in ("The reward depended on the dead body, not on any reduction of the wild population.",
                 "That was the flaw: the bounty paid for bodies, not fewer snakes."):
        beat = _beat(role="hinge", event={"text": turn, "claim_refs": ["c_mech"]})
        assert "HINGE_WITHOUT_TURN" not in _codes([beat], claims=_KINDS), turn


def test_other_roles_are_not_subject_to_the_turn_rule():
    """The mechanism beat's job IS to state the rule."""
    beat = _beat(role="mechanism", event={"text": "Any proxy is only a stand-in for the goal.",
                                          "claim_refs": ["c_mech"]})
    assert "HINGE_WITHOUT_TURN" not in _codes([beat], claims=_KINDS)


# --- abstention is a comparative judgement, not an introspective one -------------------------------

def test_a_clear_winner_decides():
    kind, reason = sfm.resolved_claim_kind(
        {"claim_kind": "mechanism", "claim_kind_confidence": 0.85,
         "runner_up_kind": "general_principle", "runner_up_confidence": 0.4})
    assert kind == "mechanism" and reason == "decided"


def test_a_near_tie_abstains_and_says_what_it_tied_with():
    """The fix for a classifier that never abstained.

    Two measured runs returned ZERO unknowns with every confidence between 0.65 and 0.85 —
    including on the claims it got wrong. Absolute confidence is introspection and it was not
    calibrated. "Which of these two fits better, and by how much" is about the material, and it
    caught both prior errors: c11 came back event 0.60 with context 0.50 as runner-up, which is
    exactly the disagreement, self-identified.
    """
    kind, reason = sfm.resolved_claim_kind(
        {"claim_kind": "event", "claim_kind_confidence": 0.6,
         "runner_up_kind": "context", "runner_up_confidence": 0.5})
    assert kind == sfm.UNKNOWN_KIND
    assert reason == "narrow_margin_over_context"


def test_low_absolute_confidence_still_abstains():
    """Both signals are kept. The margin is the useful one; the floor is the backstop."""
    kind, reason = sfm.resolved_claim_kind(
        {"claim_kind": "event", "claim_kind_confidence": 0.3,
         "runner_up_kind": "context", "runner_up_confidence": 0.05})
    assert kind == sfm.UNKNOWN_KIND and reason == "low_confidence"


def test_an_explicit_unknown_is_honoured():
    kind, reason = sfm.resolved_claim_kind({"claim_kind": "unknown"})
    assert kind == sfm.UNKNOWN_KIND and reason == "classifier_abstained"


def test_a_missing_label_abstains():
    assert sfm.resolved_claim_kind({})[0] == sfm.UNKNOWN_KIND
    assert sfm.resolved_claim_kind({})[1] == "unlabelled"


def test_no_runner_up_means_no_margin_test():
    """A claim with only one plausible kind should not be punished for having no rival."""
    kind, reason = sfm.resolved_claim_kind(
        {"claim_kind": "mechanism", "claim_kind_confidence": 0.7, "runner_up_kind": ""})
    assert kind == "mechanism" and reason == "decided"


def test_an_abstention_reason_reaches_the_report():
    beat = _beat(role="escalation", event={"text": "x", "claim_refs": ["c_tie"]})
    rows = sfm.indeterminate_kind_bindings(
        [beat], {"c_tie": {"claim_kind": "event", "claim_kind_confidence": 0.6,
                           "runner_up_kind": "context", "runner_up_confidence": 0.5}})
    assert rows and rows[0]["abstained_because"] == "narrow_margin_over_context"
    assert rows[0]["runner_up_kind"] == "context"


# --- required-role repair: narrow from own evidence, never search the dossier ----------------

def _required(beat_id="beat_05", role="mechanism", text="", to="an incentive to keep rats alive"):
    return {"beat_id": beat_id, "role": role, "scope": "primary_story",
            "changes_state": {"from": "a bounty paid per rat tail", "to": to},
            "event": {"text": text, "claim_refs": ["c01"]}}


def test_partially_entailed_required_beat_narrows_to_its_supported_core():
    beat = _required(text="The 1902 bounty paid 1 cent per tail and collectors farmed rats.")
    verdicts = {"beat_05": {"verdict": "partially_entailed", "passed": False,
                            "supported_core": "The bounty paid per rat tail, so collectors farmed rats.",
                            "unsupported_details": ["the 1 cent rate"]}}
    kept, narrowed, blocked = sfm.narrow_required_roles([beat], verdicts)
    assert not blocked
    assert len(narrowed) == 1 and narrowed[0]["beat_id"] == "beat_05"
    assert sfm.event_of(kept[0])["text"].startswith("The bounty paid per rat tail")
    assert kept[0]["event"]["claim_refs"] == ["c01"], "narrowing keeps the beat's own citations"


def test_unsupported_required_beat_is_never_re_sourced():
    """The whole point. `unsupported` means no demonstrated nucleus, so there is nothing to keep."""
    beat = _required(text="Colonial officials cancelled the bounty in 1903.")
    verdicts = {"beat_05": {"verdict": "unsupported", "passed": False,
                            "supported_core": "", "unsupported_details": ["the cancellation"]}}
    kept, narrowed, blocked = sfm.narrow_required_roles([beat], verdicts)
    assert not narrowed
    assert [i["code"] for i in blocked] == ["MISSING_REQUIRED_ROLE_SUPPORT"]
    assert sfm.event_of(kept[0])["text"] == "Colonial officials cancelled the bounty in 1903.", \
        "the beat is reported, not silently rewritten"


def test_a_contradicted_required_beat_is_reported_as_contradiction_not_absence():
    beat = _required(text="The bounty ended the rat population.")
    verdicts = {"beat_05": {"verdict": "contradicted", "passed": False, "supported_core": ""}}
    _, narrowed, blocked = sfm.narrow_required_roles([beat], verdicts)
    assert not narrowed and [i["code"] for i in blocked] == ["REQUIRED_ROLE_CONTRADICTED"]


def test_narrowing_that_destroys_the_role_is_blocked_not_accepted():
    """Support and narrative function are separate contracts."""
    beat = _required(text="French authorities in Hanoi paid a bounty per rat tail in 1902.")
    verdicts = {"beat_05": {"verdict": "partially_entailed", "passed": False,
                            "supported_core": "French authorities governed Hanoi in 1902.",
                            "unsupported_details": ["the bounty"]}}
    _, narrowed, blocked = sfm.narrow_required_roles([beat], verdicts)
    assert not narrowed, "sourced, and no longer a mechanism"
    assert [i["code"] for i in blocked] == ["ROLE_CONTRACT_FAILED"]


def test_optional_roles_are_pruned_not_narrowed():
    beat = _required(beat_id="beat_09", role="generalization", text="Everywhere, metrics corrupt.")
    verdicts = {"beat_09": {"verdict": "partially_entailed", "passed": False,
                            "supported_core": "Metrics corrupt."}}
    _, narrowed, blocked = sfm.narrow_required_roles([beat], verdicts)
    assert not narrowed and not blocked, "pruning already handles what the chain does not require"


def test_the_bibliography_run_can_never_pass_again():
    """The dossier-wide search's own output, kept as a fixture. Every event here is true."""
    fixture = json.loads((Path(__file__).parent.parent / "fixtures" / "fact_model" /
                          "bibliography_as_story.json").read_text())
    for beat in fixture["beats"]:
        holds, why = sfm.role_contract_holds(beat)
        assert not holds, (f"{beat['beat_id']} [{beat['role']}] was accepted: "
                           f"{sfm.event_of(beat)['text']}")
        assert why


def test_a_real_narrowed_event_still_passes_the_role_contract():
    """The guard has to let the good case through, or it is just a rejection machine."""
    beat = _required(text="Hanoi's 1890s sewers bred rats faster than the city could kill them.",
                     to="a city overrun by rats")
    assert sfm.role_contract_holds(beat)[0]


def test_a_dossier_with_no_bound_events_is_a_failure_not_a_pass():
    """The gate must not switch itself off the day the planner stops emitting the field."""
    beats = [{"beat_id": "beat_01", "role": "setup", "beat": "something happens"}]
    out = sfm.compile_spine(beats, {"c01": {"claim": "x", "verified": True}}, {})
    assert out["assessed"] is False and out["passed"] is False
    assert [i["code"] for i in out["unrepairable"]] == ["SHEET_CARRIES_NO_EVENTS"]
    assert "SHEET_CARRIES_NO_EVENTS" in sfm.spine_summary(beats, out)


def test_no_events_and_no_research_is_reported_as_unassessed_not_as_a_pass():
    beats = [{"beat_id": "beat_01", "role": "setup", "beat": "something happens"}]
    out = sfm.compile_spine(beats, {}, {})
    assert out["passed"] and out["assessed"] is False
    assert "NOT ASSESSED" in sfm.spine_summary(beats, out), "never printed as a clean pass"


def test_stemming_does_not_let_a_short_function_word_carry_a_match():
    """`and` was once enough overlap to certify a China parallel case as a Hanoi mechanism."""
    assert sfm._stems("and the for was per via") == set()
    assert "tail" in sfm._stems("tails") and "rat" in sfm._stems("rats")


def test_a_plural_does_not_hide_a_real_role_match():
    """Measured: this exact mechanism was rejected because it said 'tail' and its state 'tails'."""
    beat = {"role": "mechanism", "changes_state": {"from": "a bounty", "to": "Reward aimed at more tails"},
            "event": {"text": "Because the bounty paid per tail, a living rat was worth more alive."}}
    assert sfm.role_contract_holds(beat)[0]


def test_a_derived_beat_reaches_the_actual_judge_without_a_structural_collision():
    from test_story_planning_flow import factual_fixture, EvidenceFixture
    import story_compiler as compiler
    beats, claims = factual_fixture()
    roles = compiler.compile_roles(beats, "backfiring_solution", claims)
    sheet = compiler.splice_derived(roles["beats"], roles)
    judge = EvidenceFixture()
    result = sfm.validate_cascade(sheet, claims, judge=judge)
    assert not result["structural"] and not result["skipped_for_structure"]
    assert result["passed"]
    assert len(result["assertion_judgments"]) == 2
    assert any(c["event"].startswith("The reward was paid") for c in judge.calls)
    forged = {"beat_id": "fake", "role": "mechanism", "derived_from": ["fact_2"],
              "event": {"text": "The reward was paid for a tail.", "claim_refs": ["c7"]}}
    assert any(i["code"] == "CLAIM_KIND_MISMATCH" for i in sfm.validate_structure([forged], {}, claims))


def test_a_planner_written_beat_still_faces_the_kind_gate():
    """The exemption is for derived beats only, not a general loosening."""
    claims = {"c09": {"claim": "The bounty was extended to anyone who brought a rat tail.",
                      "claim_kind": "event", "claim_kind_confidence": 0.95}}
    beat = {"beat_id": "beat_06", "role": "mechanism", "scope": "primary_story",
            "changes_state": {"from": "a", "to": "b"},
            "event": {"text": "The reward was paid for a tail.", "claim_refs": ["c09"]}}
    assert [i["code"] for i in sfm.validate_structure([beat], {}, claims)
            if i["code"] == "CLAIM_KIND_MISMATCH"]


def test_each_engine_describes_its_roles_in_its_own_terms():
    """CENTRAL_FUNCTIONS describes a bounty that ran, which is where it came from.

    Applied to almost_happened_plan it told a story about a bill dying in committee that its
    escalation should show "HOW people exploit it, compounding" -- of an event where nobody
    exploits anything. The role names are shared; the jobs are not.
    """
    assert sfm.role_function("escalation", "backfiring_solution") == \
        "HOW people exploit it, compounding"
    assert sfm.role_function("escalation", "almost_happened_plan") == \
        "the opposition gathering against it"
    assert sfm.role_function("mechanism", "almost_happened_plan") == \
        "the specific thing that killed it"
    # An engine with no map keeps the shared defaults rather than losing its guidance.
    assert sfm.role_function("escalation", "power_reversal") == \
        "HOW people exploit it, compounding"
    assert sfm.role_function("escalation", "") == "HOW people exploit it, compounding"
    assert sfm.role_function("not_a_role", "almost_happened_plan") == ""


def test_the_engines_meaning_reaches_the_messages_an_operator_reads():
    """A refusal that explains the role in another engine's terms sends the repair the wrong way."""
    source = open(sfm.__file__, encoding="utf-8").read()
    # Skip role_function's own fallback, which is the one legitimate default lookup.
    body = source[source.index("def required_spine_roles"):]
    for site in ("ROLE_CONTRACT_FAILED", "Required repair: write a"):
        assert site in body
    assert "CENTRAL_FUNCTIONS.get(role, '')" not in body, \
        "every operator-facing message goes through role_function"
    out = sfm.compile_spine([], {}, {}, engine_id="almost_happened_plan")
    assert out["engine_id"] == "almost_happened_plan", "carried so the summary can use it"
