"""The hook contract: contradiction, specificity, timeframe, and an unanswered question."""
import hook_patterns as hp


def test_the_three_delivered_hooks_score_poorly_for_the_reasons_we_know():
    canetoad = hp.score_hook("Queensland's sugar bureau imported cane toads to kill beetles "
                             "— then native predators died from eating them.")
    wolves = hp.score_hook("Government hunters killed Yellowstone's last wolves.")
    bees = hp.score_hook("Brazil imported African bees to make more honey, and twenty-six "
                         "queens escaped.")
    # All three lack a clock, and the two that name a purpose also answer themselves.
    for r in (canetoad, wolves, bees):
        assert not r["patterns"]["timeframe"]
        assert r["score"] < 60
    assert not canetoad["patterns"]["open_question"]
    assert not bees["patterns"]["open_question"]
    assert not wolves["patterns"]["contradiction"]      # a bare fact, no tension at all


def test_a_hook_carrying_all_four_patterns_scores_full():
    r = hp.score_hook("Twenty-six queens escaped a Brazilian lab in 1957, and they never "
                      "stopped spreading.")
    assert r["score"] == 100
    assert all(r["patterns"].values())


def test_purpose_plus_outcome_is_marked_as_answering_itself():
    assert not hp.score_hook("They released toads to kill beetles, but the toads killed the "
                             "predators.")["patterns"]["open_question"]
    assert hp.score_hook("In 1935 Australia released 102 cane toads; they are still spreading "
                         "west.")["patterns"]["open_question"]


def test_clickbait_filler_is_penalised_not_rewarded():
    r = hp.score_hook("You won't believe what happened to some animals.")
    assert r["score"] <= 10
    assert any("vague" in n for n in r["notes"])


def test_persistence_counts_as_tension_without_a_pivot_word():
    assert hp.score_hook("The bees never stopped spreading.")["patterns"]["contradiction"]
    assert not hp.score_hook("The bees spread north.")["patterns"]["contradiction"]


def test_the_rules_reach_the_planner_prompt():
    import story_compiler as sc
    prompt = sc.factual_plan_prompt("Killer bees", 300, 20, "removed_keystone")
    for token in ("CONTRADICTION", "SPECIFICITY", "TIMEFRAME", "OPEN QUESTION"):
        assert token in prompt
