"""removed_keystone's escalation and reversal may cite mechanism-kind claims.

Cane toads (2026-09-29): three consecutive beat sheets put the reversal, "what the place became",
on a claim the research classifier filed as mechanism ("smaller predators survive and learn to
avoid toads", runner-up kind outcome), and each run died at the spine with every other required
beat standing. The nature engines were widened for the same reason on 2026-09-24. The paid
Boundary A judgement is unchanged; the intervention keeps its historical-event rule.
"""
import story_fact_model as sfm


def test_removed_keystone_outcome_roles_accept_mechanism_claims():
    for role in ("escalation", "reversal"):
        assert "mechanism" in sfm.accepted_claim_kinds(role, "removed_keystone")
        assert "event" in sfm.accepted_claim_kinds(role, "removed_keystone")
    assert "mechanism" not in sfm.accepted_claim_kinds("intervention", "removed_keystone")
    # The bounty engine derives its mechanism; its escalations stay events, as before.
    assert "mechanism" not in sfm.accepted_claim_kinds("escalation", "backfiring_solution")
    assert "mechanism" not in sfm.accepted_claim_kinds("reversal", "backfiring_solution")


def test_a_mechanism_labelled_reversal_no_longer_fails_the_kind_gate():
    claims = {"c27": {"claim_id": "c27", "claim_kind": "mechanism", "claim_kind_confidence": 0.8,
                      "runner_up_kind": "outcome", "runner_up_confidence": 0.55,
                      "claim": "Smaller predators survive and learn to avoid toads thereafter."}}
    beat = {"beat_id": "event_16", "role": "reversal", "event_function": "system_resettles",
            "event": {"text": "Smaller predators survive and learn to avoid toads.",
                      "claim_refs": ["c27"]}}
    issues = sfm.validate_structure([beat], {}, claims=claims, engine_id="removed_keystone")
    assert not [issue for issue in issues if issue.get("code") == "CLAIM_KIND_MISMATCH"]
    # The same binding on the bounty engine is still refused: only removed_keystone widened.
    issues = sfm.validate_structure([beat], {}, claims=claims, engine_id="backfiring_solution")
    assert [issue for issue in issues if issue.get("code") == "CLAIM_KIND_MISMATCH"]


def test_system_resettles_is_defined_for_animals_as_well_as_plants():
    """The fulfillment judge reads the definition literally; a plant-only wording refused every
    animal reversal on the cane toad film (2026-09-29)."""
    import event_functions as ef
    text = ef.WHAT_EACH_FUNCTION_IS[ef.SYSTEM_RESETTLES].lower()
    assert "animals" in text and "plants" in text
    assert "species" in text and "cost" in text
