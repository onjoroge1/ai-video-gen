"""A lone surname is still a named researcher (killer bees 2026-10-06, attempt 3).

"You watch Kerr import African bees for Brazilian honey" scored 68 with no_institution passing:
the scorer's personal-name regex wants two capitalised tokens. Surnames come from the dossier,
so this is a per-run registry, and a country's possessive must not read as a person.
"""
import hook_patterns as hp

DOSSIER = {"claims": [
    {"claim_id": "c01", "claim": "In 1956 Brazilian geneticist Warwick Kerr imported African queens."},
    {"claim_id": "c02", "claim": "The Africanized bees spread from Rio Claro across South America."},
    {"claim_id": "c03", "claim": "Feral Africanized colonies were studied at the Carl Hayden Bee Research Center."},
    {"claim_id": "c04", "claim": "In October 1957 a local beekeeper removed the queen excluders."},
]}


def test_registry_keeps_surnames_and_drops_places_and_adjectives():
    people = hp.register_people(DOSSIER)
    assert "Kerr" in people and "Hayden" in people
    for not_a_person in ("Africanized", "Claro", "America", "October", "Research", "Bee"):
        assert not_a_person not in people


def test_a_lone_surname_fails_no_institution_and_a_country_does_not():
    hp.register_people(DOSSIER)
    kerr = hp.score_hook("You watch Kerr import African bees for Brazilian honey—then his queens escape.")
    assert not kerr["patterns"]["no_institution"]
    poss = hp.score_hook("You watch Kerr's African bees leave their boxes; nobody checked the gate.")
    assert not poss["patterns"]["no_institution"]
    country = hp.score_hook("Your country receives 26 escaped queens; Africanized bees are not the strangest part.")
    assert country["patterns"]["no_institution"]
    # Without a registry the old behaviour stands: the regex alone cannot know a surname.
    hp.register_people({"claims": []})
    assert hp.score_hook("You watch Kerr import African bees for honey.")["patterns"]["no_institution"]
