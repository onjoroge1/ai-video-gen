"""The spine re-ask names the acceptable-kind claims nearest a beat refused for its claim kind.

Cane toad film, 2026-09-29: the reversal cited c49 (mechanism: selection favours larger snakes)
while c48 (outcome: two snake species have evolved larger gapes) sat unused, and the generic
re-ask returned the same citation. The suggestion block is text for the planner; it changes no
gate, cites nothing itself, and is empty when no kind mismatch was reported.
"""
import story_fact_model as sfm

CLAIMS = {
    "c48": {"claim_id": "c48", "claim_kind": "outcome", "claim_kind_confidence": 0.78,
            "runner_up_kind": "mechanism", "runner_up_confidence": 0.55,
            "claim": "Two Australian snake species with long associations with cane toads have "
                     "evolved rapidly in gape size and body length."},
    "c49": {"claim_id": "c49", "claim_kind": "mechanism", "claim_kind_confidence": 0.82,
            "runner_up_kind": "general_principle", "runner_up_confidence": 0.5,
            "claim": "Because snakes are gape-limited predators, the arrival of toads exerts "
                     "selection favouring an increase in mean snake body size."},
    "c10": {"claim_id": "c10", "claim_kind": "outcome", "claim_kind_confidence": 0.9,
            "claim": "Northern quolls declined quickly after long toad exposure."},
    "c30": {"claim_id": "c30", "claim_kind": "outcome", "claim_kind_confidence": 0.5,
            "claim": "Snake species with toad exposure changed body length."},
}
BEATS = [
    {"beat_id": "event_14", "role": "reversal",
     "event": {"text": "Snake species with long toad exposure have shifted in gape size and "
                       "body length, an evolving new normal.", "claim_refs": ["c49"]}},
]


def _compiled(code="CLAIM_KIND_MISMATCH"):
    return {"cascade": {"structural": [
        {"code": code, "beat_id": "event_14", "claim_id": "c49",
         "message": "beat event_14 is a reversal beat citing c49, which is a mechanism claim"}]}}


def test_names_the_overlapping_acceptable_claims_best_first():
    text = sfm.citation_suggestions(BEATS, _compiled(), CLAIMS, "backfiring_solution")
    assert "event_14 [reversal] may cite event, context, outcome" in text
    assert text.index("c48 (outcome)") < text.index("c10 (outcome)")
    # The refused mechanism claim is never offered back, and a low-confidence label is unknown,
    # not acceptable, so it is not offered either.
    assert "c49" not in text.split("may cite", 1)[1]
    assert "c30" not in text


def test_silent_without_a_kind_mismatch_and_honest_without_a_candidate():
    assert sfm.citation_suggestions(BEATS, _compiled("DUPLICATE_ROLE"), CLAIMS) == ""
    assert sfm.citation_suggestions(BEATS, {"cascade": {}}, CLAIMS) == ""
    only_mechanism = {"c49": CLAIMS["c49"]}
    text = sfm.citation_suggestions(BEATS, _compiled(), only_mechanism, "backfiring_solution")
    assert "no such claim overlaps" in text


def test_role_contract_failure_searches_for_the_dropped_detail():
    """Attempt 2 (2026-09-29): the intervention cited Mungomery's travel and release claims, so
    Boundary A dropped 'the purpose was to control cane beetles' and the role failed its contract
    while c01 ('introduced in 1935 to control cane beetles') sat unused."""
    claims = dict(CLAIMS)
    claims["c01"] = {"claim_id": "c01", "claim_kind": "event", "claim_kind_confidence": 0.9,
                     "claim": "Cane toads were introduced to Queensland in 1935 to control the "
                              "greyback cane beetle and French's cane beetle."}
    beats = [{"beat_id": "event_03", "role": "intervention",
              "event": {"text": "In June 1935 Mungomery returned from Hawaii with a breeding "
                                "sample of toads.", "claim_refs": ["c07"]}}]
    compiled = {"cascade": {"structural": []}, "unrepairable": [
        {"code": "ROLE_CONTRACT_FAILED", "beat_id": "event_03", "role": "intervention",
         "message": "narrowing left an intervention that no longer performs its function",
         "dropped": ["that the purpose of the release was to control cane beetles"]}]}
    text = sfm.citation_suggestions(beats, compiled, claims, "removed_keystone")
    assert "event_03 [intervention] may cite" in text
    assert "c01 (event)" in text
    # Overlap ranks: the purpose claim beats a claim that merely shares "cane toads".
    assert text.index("c01 (event)") < text.index("c48 (outcome)")
