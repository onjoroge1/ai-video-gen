"""The hook contract, derived from a corpus of seven winning first minutes rather than asserted.

The previous version scored four patterns from a practitioner write-up; our hooks scored 55-70
and the operator rejected them anyway, because the axes were wrong. These tests pin the axes to
the corpus: openings in the style we want must outscore the ones we shipped, by a wide margin.
"""
import statistics

import hook_patterns as hp

CORPUS = [
    "200 years ago, whale meat and whale oil were everywhere. Your lamp ran on it.",
    "Look at the back of your hand. Whatever shade your skin is, one thing is certain. It isn't green.",
    "All right, picture this. You're alone in the woods and 30 feet away there's a wolf.",
]
SHIPPED = [
    "Queensland's sugar bureau imported cane toads to kill beetles — then native predators died from eating them.",
    "Government hunters killed Yellowstone's last wolves.",
    "Brazil imported African bees to make more honey, and twenty-six queens escaped.",
    "Warwick Kerr imported African bees for honey—why did 26 escaped swarms spread across the Americas?",
]


def test_the_corpus_outscores_everything_we_shipped():
    corpus = statistics.mean(hp.score_hook(h)["score"] for h in CORPUS)
    shipped = statistics.mean(hp.score_hook(h)["score"] for h in SHIPPED)
    assert corpus >= 75, corpus
    assert shipped <= 35, shipped
    assert corpus - shipped >= 40


def test_the_listener_must_be_in_the_hook():
    """The pipeline measured second_person at 0.00 on every delivered film."""
    assert hp.score_hook("Your lamp ran on it.")["patterns"]["viewer_present"]
    r = hp.score_hook("Brazil imported African bees to make more honey.")
    assert not r["patterns"]["viewer_present"]
    assert any("listener is not in it" in n for n in r["notes"])


def test_an_institution_or_a_named_researcher_fails_the_subject_rule():
    assert not hp.score_hook("Queensland's sugar bureau imported cane toads.")["patterns"]["no_institution"]
    assert not hp.score_hook("In 1956 Warwick Kerr brought African queens to Brazil.")["patterns"]["no_institution"]
    assert hp.score_hook("You have never met the bee they were breeding for.")["patterns"]["no_institution"]


def test_stating_the_intervention_and_its_result_spoils_the_outcome():
    assert not hp.score_hook(
        "Brazil imported African bees, and twenty-six queens escaped.")["patterns"]["outcome_withheld"]
    assert hp.score_hook(
        "You have never met the bee Brazil was actually breeding for.")["patterns"]["outcome_withheld"]


def test_a_bare_number_needs_something_to_measure_it_against():
    assert not hp.score_hook("It can produce up to 860 volts.")["patterns"]["yardstick"]
    assert hp.score_hook("It makes 860 volts; your outlet runs at 240.")["patterns"]["yardstick"]


def test_a_reachable_hook_scores_well_inside_the_eighteen_word_budget():
    r = hp.score_hook("You would have asked whether a toad can climb a cane stalk, and nobody did.")
    assert r["words"] <= 18 and r["score"] >= 80


def test_clickbait_is_penalised():
    assert hp.score_hook("You won't believe what happened to your dinner.")["score"] <= 60


def test_the_rules_reach_the_planner_prompt():
    import story_compiler as sc
    prompt = sc.factual_plan_prompt("Killer bees", 300, 20, "removed_keystone")
    assert "PUT THE LISTENER IN IT" in prompt
    assert "NO INSTITUTION OR NAMED RESEARCHER" in prompt
