"""The cold open: the aftermath sentence spoken right after the hook (2026-10-02).

The cane toad film opened on a summary hook, the spoken format tag, then 48 s of setup; its
first visible consequence landed at 52.9 s and browse viewers left at 41 s on average.
"""
import causal_story as cs
import explainer_pipeline as ep


def test_finalize_speaks_hook_then_cold_open_and_is_idempotent():
    scenes = [{"narration": "Two beetles were pests in the cane.", "chapter": 1},
              {"narration": "In 1935 toads arrived.", "chapter": 1}]
    cs.finalize_narration(scenes, hook="Australia imported a toad to save its sugar",
                          cold_open="a crocodile lies dead with the toad still in its jaws")
    first = scenes[0]["narration"]
    assert first.startswith("Australia imported a toad to save its sugar. A crocodile lies dead "
                            "with the toad still in its jaws. Two beetles")
    cs.finalize_narration(scenes, hook="Australia imported a toad to save its sugar",
                          cold_open="a crocodile lies dead with the toad still in its jaws")
    assert scenes[0]["narration"] == first
    assert scenes[1]["narration"] == "In 1935 toads arrived."


def test_cold_open_shape_rules():
    assert cs.check_cold_open("", "") and cs.check_cold_open("", "")[0]["code"] == "COLD_OPEN_MISSING"
    codes = {i["code"] for i in cs.check_cold_open(
        "Explained like you are five, here is the story of the toads and why they came", "")}
    assert "COLD_OPEN_META" in codes
    long = " ".join(["word"] * 23)
    assert {i["code"] for i in cs.check_cold_open(long, "")} == {"LONG_COLD_OPEN"}
    hook = "Queensland imported cane toads to kill beetles"
    assert "COLD_OPEN_RESTATES_HOOK" in {i["code"] for i in cs.check_cold_open(
        "Queensland imported the cane toads to kill the beetles", hook)}
    assert cs.check_cold_open("A crocodile lies dead with a toad in its jaws", hook) == []


def test_validator_holds_cold_open_only_when_required():
    steps = [{"step_id": "s1", "role": "setup", "start_sec": 0, "situation": "x", "chapter": 1}]
    issues = []
    cs._check_hook({"line": "A hook", "require_cold_open": True}, steps, issues, short_form=False)
    assert "COLD_OPEN_MISSING" in {i["code"] for i in issues}
    issues = []
    cs._check_hook({"line": "A hook"}, steps, issues, short_form=False)
    assert "COLD_OPEN_MISSING" not in {i["code"] for i in issues}


def test_plan_cold_open_and_correction():
    plan = {"hook": "Brazil imported African bees to make more honey",
            "cold_open": {"text": "Twenty-six swarms escaped and their descendants now defend hives across the Americas",
                          "claim_refs": ["c03"]}}
    dossier = {"claims": [{"claim_id": "c03", "source_url": "https://x"}]}
    assert ep._plan_cold_open(plan) == (plan["cold_open"]["text"], ["c03"])
    assert ep._cold_open_correction(plan, dossier) == ""
    plan["cold_open"]["claim_refs"] = ["c99"]
    assert "COLD_OPEN_UNCITED" in ep._cold_open_correction(plan, dossier)
    assert "COLD_OPEN_MISSING" in ep._cold_open_correction({"hook": "h"}, dossier)


def test_description_meta_scrub_and_sources():
    raw = ("To give viewers clear context, rank for key search terms, and drive viewer engagement, "
           "use this optimized layout:\n\nIn 1958, China ordered the eradication of sparrows.\n\n"
           "Here is the optimized description:\nThe film follows the campaign.")
    out = ep._scrub_description_meta(raw)
    assert out.startswith("In 1958, China ordered")
    assert "optimized" not in out and "The film follows the campaign." in out
    script = {"_research_dossier": {"claims": [
                  {"claim_id": "c1", "source_url": "https://www.nps.gov/yell/a"},
                  {"claim_id": "c2", "source_url": "https://doi.org/10.1/b"},
                  {"claim_id": "c3", "source_url": "https://unused.example/c"}]},
              "scenes": [{"claim_refs": [{"claim_id": "c1"}, {"claim_id": "c2"}]},
                         {"claim_refs": [{"claim_id": "c1"}]}]}
    assert ep.description_sources(script) == [("nps.gov", "https://www.nps.gov/yell/a"),
                                              ("doi.org", "https://doi.org/10.1/b")]


def test_lead_is_restored_after_a_pass_dropped_it():
    script = {"hook": "Brazil imported African bees to make more honey, and twenty-six queens escaped",
              "_cold_open": "An escaped swarm boils from a hive box as a beekeeper backs away",
              "_cold_open_claim_refs": ["c14"], "_compiled_story": True,
              "scenes": [{"narration": "European honey bees had been introduced in the 1600s. Brazil wanted more.",
                          "claim_refs": [{"claim_id": "c01", "evidence_id": "e01", "narration_phrase": "Brazil wanted more."}]},
                         {"narration": "In 1956 African queens arrived."}]}
    assert ep._ensure_lead_spoken(script)
    first = script["scenes"][0]["narration"]
    assert first.startswith("Brazil imported African bees to make more honey, and twenty-six queens escaped. "
                            "An escaped swarm boils from a hive box as a beekeeper backs away. European honey bees")
    assert any(r["claim_id"] == "c14" for r in script["scenes"][0]["claim_refs"])
    assert not ep._ensure_lead_spoken(script)          # idempotent: nothing to change the second time
    assert script["scenes"][0]["narration"] == first


def test_hook_that_opens_the_first_sentence_is_not_spoken_twice():
    """Wild pigs (2026-10-23): hook "On a Monday" before "On a Monday in July 2026, ..." was
    prepended as its own sentence and the film opened "On a Monday. On a Monday in July..."."""
    scenes = [{"narration": "On a Monday in July 2026, a hog crossed an office-park lawn.",
               "chapter": 1},
              {"narration": "In 1769 the first pigs arrived.", "chapter": 1}]
    cs.finalize_narration(scenes, hook="On a Monday")
    first = scenes[0]["narration"]
    assert first == "On a Monday in July 2026, a hog crossed an office-park lawn."
    cs.finalize_narration(scenes, hook="On a Monday")
    assert scenes[0]["narration"] == first, "a second pass changes nothing"

    with_cold_open = [{"narration": "On a Monday in July 2026, a hog crossed a lawn.",
                       "chapter": 1}]
    cs.finalize_narration(with_cold_open, hook="On a Monday.",
                          cold_open="the sprinklers came up full of mud")
    first = with_cold_open[0]["narration"]
    assert first == ("The sprinklers came up full of mud. "
                     "On a Monday in July 2026, a hog crossed a lawn.")
    assert first.casefold().count("on a monday") == 1
    cs.finalize_narration(with_cold_open, hook="On a Monday.",
                          cold_open="the sprinklers came up full of mud")
    assert with_cold_open[0]["narration"] == first


def test_hook_matching_only_part_of_a_word_is_still_spoken():
    scenes = [{"narration": "On a Mondayish afternoon a hog crossed the lawn.", "chapter": 1}]
    cs.finalize_narration(scenes, hook="On a Monday")
    assert scenes[0]["narration"].startswith("On a Monday. On a Mondayish")
