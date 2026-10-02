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
