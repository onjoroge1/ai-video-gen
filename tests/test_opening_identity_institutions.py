"""The opening identity check refuses invented PEOPLE, not states (2026-10-14).

The first History film (Aral Sea) stopped after its script was paid for: "scene 3 names 'Soviet
Union', and no claim in the dossier does; a person in the opening is a sourced fact". The Soviet
Union is not a person, and NASA's verified quote names it ("In the 1960s, the Soviet Union
undertook a major water diversion project") while the claim summary says "a Soviet project".
"""
import explainer_pipeline as ep

DOSSIER = {"claims": [
    {"claim_id": "c02", "claim": "NASA attributes the Aral Sea's decline to a major Soviet "
                                 "water-diversion project begun in the 1960s.",
     "support_quote": "In the 1960s, the Soviet Union undertook a major water diversion project "
                      "on the arid plains of Kazakhstan, Uzbekistan, and Turkmenistan."},
    {"claim_id": "c43", "claim": "Hydrologists understood the diversions would harm the sea.",
     "support_quote": "Soviet hydrologists understood even before the construction of the main "
                      "canals that diverting water would have serious consequences for the sea"},
]}


def _script(*narrations):
    roles = ["setup", "intervention", "mechanism", "escalation"]
    return {"scenes": [{"narration": n, "causal_role": roles[i]} for i, n in enumerate(narrations)]}


def test_a_state_named_by_the_sources_own_quote_is_not_an_unknown_person():
    script = _script("Imagine you fish the Aral Sea for a living.",
                     "In the 1960s the Soviet Union turned two rivers onto the desert.",
                     "The rivers stopped reaching the sea.", "The shoreline began to retreat.")
    assert ep._opening_identity_findings(script, DOSSIER) == []


def test_an_institution_is_not_a_person_even_when_no_claim_names_it():
    script = _script("Imagine you fish the Aral Sea for a living.",
                     "The Communist Party ordered the canals dug, and the State Planning "
                     "Committee set the cotton targets.",
                     "The rivers stopped reaching the sea.", "The shoreline began to retreat.")
    assert ep._opening_identity_findings(script, DOSSIER) == []


def test_an_invented_person_is_still_refused():
    script = _script("Imagine you fish the Aral Sea for a living.",
                     "The order to divert the rivers was signed by Elena Markova.",
                     "The rivers stopped reaching the sea.", "The shoreline began to retreat.")
    findings = ep._opening_identity_findings(script, DOSSIER)
    assert [f["code"] for f in findings] == ["OPENING_UNKNOWN_NAME"]
    assert "Elena Markova" in findings[0]["message"]
