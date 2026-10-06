"""Scene-level templates: the engine owns the skeleton, the fill is scored by the gates."""
import json

import story_template as st


def test_build_slots_has_the_engine_spine_and_a_flexible_escalation_band():
    slots = st.build_slots("removed_keystone", 300)
    assert 20 <= len(slots) <= 40
    roles = [s["role"] for s in slots]
    # The required spine appears in order; escalation is the biggest, repeatable band.
    for role in ("setup", "intervention", "mechanism", "escalation", "reversal"):
        assert role in roles
    first = {r: roles.index(r) for r in ("setup", "intervention", "mechanism", "escalation", "reversal")}
    assert first["setup"] < first["intervention"] < first["mechanism"] < first["escalation"] < first["reversal"]
    assert roles.count("escalation") >= st.MIN_ESCALATION_SCENES
    assert slots[0]["is_cold_open"] and slots[0]["words_min"] >= 6


def test_scene_count_scales_with_duration():
    assert len(st.build_slots("removed_keystone", 120)) < len(st.build_slots("removed_keystone", 300))
    assert st.target_scene_count(60) >= st.MIN_SCENES


# A pool of distinct nouns so each test sentence shares few content words with its neighbours
# and clears the repeat detector; the real writer achieves this with real facts.
_NOUNS = ("quoll goanna crocodile python bandicoot dingo kookaburra wallaby lizard snake gecko "
          "frog beetle cane sugar river gorge ridge valley savanna billabong mangrove eucalypt "
          "wetland floodplain escarpment bushland reef estuary lagoon").split()


def _good_fill(engine="removed_keystone", duration=300):
    slots = st.build_slots(engine, duration)
    scenes = []
    for i, s in enumerate(slots):
        refs = [] if not s["needs_claim"] else [{"claim_id": "c1", "narration_phrase": "x"}]
        # Coined tokens unique to each scene, so neighbouring sentences share no content words
        # and clear the repeat detector; the real writer achieves this with real distinct facts.
        target = max(s["words_min"], 12)

        def _alpha(x):
            out = ""
            x += 1
            while x:
                x, r = divmod(x - 1, 26)
                out = chr(97 + r) + out
            return out
        toks = " ".join(f"syn{_alpha(i)}{_alpha(k)}" for k in range(target - 4))
        scenes.append({"scene": s["scene"], "role": s["role"],
                       "narration": f"Here the {toks} changed the balance for good.",
                       "claim_refs": refs})
    return {"title": "T", "hook": "A fix to help one thing harmed another",
            "cold_open": {"text": "A dead predator lies beside the toad it tried to swallow", "claim_refs": ["c1"]},
            "opening_object": "the predator", "scenes": scenes}


def test_score_fill_passes_a_clean_distinct_fill():
    dossier = {"claims": [{"claim_id": "c1", "claim": "x", "source_url": "https://x"}]}
    report = st.score_fill(_good_fill(), "removed_keystone", dossier, 300)
    assert report["score"] >= 75 and report["repeats"] == 0


def test_score_fill_penalises_a_repeat_and_a_missing_cold_open():
    dossier = {"claims": [{"claim_id": "c1", "claim": "x", "source_url": "https://x"}]}
    fill = _good_fill()
    fill["scenes"][5]["narration"] = fill["scenes"][4]["narration"]   # verbatim repeat
    fill.pop("cold_open")
    report = st.score_fill(fill, "removed_keystone", dossier, 300)
    assert report["repeats"] >= 1
    assert any("repeat" in i for i in report["issues"])
    assert any("cold open" in i for i in report["issues"])
    assert report["score"] < st.score_fill(_good_fill(), "removed_keystone", dossier, 300)["score"]


def test_fill_prompt_names_every_slot_and_the_ledger():
    dossier = {"claims": [{"claim_id": "c1", "claim": "bees escaped", "source_url": "https://x"}]}
    prompt = st.fill_prompt("Killer bees", 300, "removed_keystone", dossier)
    n = len(st.build_slots("removed_keystone", 300))
    assert f"{n}. [takeaway]" in prompt or "[takeaway]" in prompt
    assert "1. [setup]" in prompt and "BINDING RESEARCH CLAIM LEDGER" in prompt
    assert "cold open" in prompt.lower()


def test_score_fill_catches_a_film_that_comes_in_short():
    """The first three template fills ran 196-222s for a 300s request and the gate passed them
    at 100/100 because it measured no runtime at all (2026-10-04)."""
    dossier = {"claims": [{"claim_id": "c1", "claim": "x", "source_url": "https://x"}]}
    fill = _good_fill()
    for scene in fill["scenes"]:                      # halve every scene: a short film
        scene["narration"] = " ".join(scene["narration"].split()[:8]) + "."
    report = st.score_fill(fill, "removed_keystone", dossier, 300)
    assert report["estimated_seconds"] < 255
    assert any("runtime" in i for i in report["issues"])
    assert report["score"] < 100


def test_the_slot_plan_is_a_role_budget_the_planner_can_be_asked_for():
    """One slot is one scene, so the plan is the film's structure, not a suggestion."""
    plan = st.role_counts("removed_keystone", 300)
    # The plan counts EVENTS the planner is asked for; the skeleton adds the compiler's hinge
    # and tool, which the planner must not supply. Asking for them produced DUPLICATE_ROLE
    # replans (three reversals asked, one allowed) and a tool beat written as a fact.
    assert sum(plan.values()) + 2 == len(st.build_slots("removed_keystone", 300))
    assert plan["escalation"] >= st.MIN_ESCALATION_SCENES
    for role in ("setup", "intervention", "mechanism", "escalation", "reversal"):
        assert plan.get(role, 0) >= 1
    # Legal for the compiler: nothing outside causal_story._REPEATABLE may be asked for twice.
    import causal_story as cs
    for role, count in plan.items():
        if role.casefold() not in {str(r).casefold() for r in cs._REPEATABLE}:
            assert count <= 1, f"{role} asked for {count} events; the compiler allows one"
    assert plan.get("takeaway", 0) == 0


def test_the_planner_prompt_asks_for_the_slot_plan_exactly():
    import story_compiler as sc
    plan = st.role_counts("removed_keystone", 300)
    prompt = sc.factual_plan_prompt("q", 300, 20, "removed_keystone", slot_plan=plan)
    assert f"Return EXACTLY {sum(plan.values())} factual events" in prompt
    # Rows name the event_function the schema accepts, not the role: asked for "escalation: 13"
    # the planner labelled the steps `context` and the film compiled to seven scenes.
    assert "population_responds: %d event(s)" % plan["escalation"] in prompt
    assert "these become the escalation" in prompt
    assert "DIFFERENT documented step" in prompt          # the anti-repetition rule
    # Without a slot plan the legacy ask is unchanged.
    legacy = sc.factual_plan_prompt("q", 300, 20, "removed_keystone")
    assert "Return about" in legacy and "Return EXACTLY" not in legacy


def test_the_beat_splitter_is_skipped_under_the_template(monkeypatch):
    """The split is what let one beat become two scenes the claim repair then merged."""
    import explainer_pipeline as ep
    monkeypatch.setenv("STORY_TEMPLATE", "1")
    assert ep._story_template_on()
    monkeypatch.setenv("STORY_TEMPLATE", "0")
    assert not ep._story_template_on()
