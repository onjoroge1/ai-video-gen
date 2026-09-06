"""The deterministic half of the fact model, which runs before any judge call is bought.

Structure is checked first on purpose. A misplaced comparison or an unbound assertion is decidable
by reading fields, and paying a model to notice it is both slower and less certain. The semantic
boundaries in claim_entailment only see beats that already have coherent provenance.
"""
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
