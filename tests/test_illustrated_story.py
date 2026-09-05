from pathlib import Path

import pytest

import illustrated_story as ils

ROOT = Path(__file__).resolve().parent.parent
from pydantic import ValidationError

from app import ExplainerRequest
from illustrated_story import (
    CINEMATIC,
    ILLUSTRATED_STORY,
    LOCATION_BUDGET,
    build_storyboard,
    is_enabled,
    story_direction,
    negative_prompt,
    validate_request,
    visual_style_suffix,
)


# Role, spoken chapter, and narration length in words. The lengths are not decoration: the
# contract places the mechanism as a fraction of estimated runtime, so a fixture that gives every
# beat the same size pushes the principle past the first fifth and fails — exactly as a real
# script would. Shaped like the references: a brisk opening, a six-word hinge, long escalations.
_CHAIN = [
    ("setup", 1, 14), ("intervention", 1, 12), ("false_resolution", 1, 8),
    ("hinge", 1, 6), ("mechanism", 1, 20),
    ("escalation", 2, 55), ("escalation", 2, 55), ("escalation", 3, 55),
    ("reversal", 3, 25), ("tool", 4, 25),
]
# The opening budget has headroom on purpose. The first version sat one second inside the
# mechanism deadline, so when the spoken hook began consuming its own seconds — which is the
# correct behaviour, and what both reference fixtures show — the fixture tipped over and failed
# a check it was written to satisfy. A fixture that only just passes tests the arithmetic, not
# the rule.
_CLOSING_LINE = ("So the next time this happens look back at the workshop table and ask what "
                 "the plan was really rewarding all along in the end")


def _narration(index, role, words):
    if role == "hinge":
        return "Except the problem is not solved."
    body = (f"Move {index + 1} follows directly from the step before it and changes the "
            "situation again for everyone involved in the story ")
    return " ".join((body * 6).split()[:words])


def _script(count=len(_CHAIN), environments=None):
    """A script that declares its causal chain, as the rejoined lane now requires.

    The old helper produced narration and let the module invent roles from scene position. Roles,
    causal links and spoken chapters are the script's job now, so the fixture states them.
    """
    scenes = []
    for index in range(count):
        role, chapter, words = _CHAIN[index % len(_CHAIN)]
        scene = {
            "scene_id": f"scene_{index + 1:03d}",
            "causal_role": role,
            "chapter": chapter,
            "caused_by": "" if index == 0 else f"scene_{index:03d}",
            "narration": _narration(index, role, words),
            "human_intention": "solve the visible problem",
            "human_belief": "the simple plan should work",
            "expected_outcome": "the problem gets smaller",
            "actual_outcome": f"consequence {index + 1} appears",
            "continuity_anchor": "the workshop table",
            "visual_beats": [{"state_after": f"state {index + 1}"}],
        }
        if environments:
            scene["environment_type"] = environments[index % len(environments)]
        scenes.append(scene)
    scenes[-1]["narration"] = _CLOSING_LINE       # the close returns to the opening object
    return {
        "title": "The Plan That Backfired",
        "hook": "How one simple fix quietly made the whole problem worse.",
        "_story_contract": {
            "human_subject": "Alex",
            "subject_goal": "solve the visible problem",
            "accepted_belief": "the simple plan should work",
            "replacement_model": "each reaction changes the system",
            "opening_object": "the workshop table",
        },
        "scenes": scenes,
    }


def test_request_defaults_to_existing_visual_lane_and_accepts_illustrated():
    assert ExplainerRequest(question="x").visual_style == CINEMATIC
    assert ExplainerRequest(
        question="x", visual_style=ILLUSTRATED_STORY).visual_style == ILLUSTRATED_STORY
    with pytest.raises(ValidationError):
        ExplainerRequest(question="x", visual_style="watercolor")


def test_illustrated_lane_isolated_to_ordinary_standard_landscape():
    assert is_enabled(
        visual_style=ILLUSTRATED_STORY,
        video_format="landscape",
        story_format="standard_explainer",
        controlled_pilot=False,
    )
    validate_request(
        visual_style=CINEMATIC,
        video_format="social",
        story_format="evidence_led_mystery",
        controlled_pilot=True,
    )
    with pytest.raises(ValueError, match="landscape"):
        validate_request(
            visual_style=ILLUSTRATED_STORY,
            video_format="social",
            story_format="standard_explainer",
            controlled_pilot=False,
        )
    with pytest.raises(ValueError, match="Standard"):
        validate_request(
            visual_style=ILLUSTRATED_STORY,
            video_format="landscape",
            story_format="evidence_led_mystery",
            controlled_pilot=False,
        )
    with pytest.raises(ValueError, match="pilots"):
        validate_request(
            visual_style=ILLUSTRATED_STORY,
            video_format="landscape",
            story_format="standard_explainer",
            controlled_pilot=True,
        )


def test_story_direction_keeps_operator_input_and_forbids_fact_lists():
    direction = story_direction("Why did the plan fail?", "Keep the narration dry and funny.")
    assert "caused_by" in direction                      # the causal spine is carried through
    assert "hand-drawn editorial storybook" in direction  # and the illustrated bible with it
    assert "Keep the narration dry and funny." in direction
    # The forced protagonist is gone: neither reference video has a named one.
    assert "Follow Alex" not in direction


def test_storyboard_is_deterministic_intent_led_and_returns_to_opening():
    script = _script()
    board = build_storyboard(script, "Why did the plan fail?")

    assert board["schema_version"] == "illustrated_story_v1"
    assert board["validation"]["passed"] is True
    assert board["story"]["goal"] == "solve the visible problem"
    assert board["beats"][0]["role"] == "setup"
    assert board["beats"][-1]["role"] == "tool"
    assert board["beats"][-1]["return_object"] == "the workshop table"
    assert len(board["visual_bible"]["locations"]) <= 4
    assert all(beat["intent"] for beat in board["beats"])
    assert all(scene["_illustrated_beat"]["scene_index"] == index
               for index, scene in enumerate(script["scenes"]))
    assert script["_illustrated_story"] == board


def test_storyboard_refuses_a_scene_without_narration():
    script = _script()
    script["scenes"][3]["narration"] = ""
    with pytest.raises(ValueError, match="scene 4 has no narration"):
        build_storyboard(script, "Why did the plan fail?")


def test_visual_style_is_consistent_and_keeps_generated_text_out():
    suffix = visual_style_suffix(" Keep the top edge clear.")
    assert "hand-drawn editorial history illustration" in suffix
    # "Not photorealistic" moved to the negative prompt, which is where a generator reads it.
    assert "photorealism" in negative_prompt()
    # Identity is no longer pinned to a named character: neither reference has one, and the
    # anchors that actually survive regeneration are clothing, silhouette and props.
    assert "clothing colour, silhouette, headwear and props" in suffix
    assert "No text" in suffix
    assert "Keep the top edge clear" in suffix


def test_storyboard_now_carries_the_declared_chain_not_a_derived_arc():
    """The rejoin: roles come from the script and the chain is verified, not invented.

    `_role_for` used to assign a role from scene position, which is why a flat fact list could
    satisfy the arc. Replaced by the causal contract, so this asserts the links survive into the
    storyboard rather than that a band was computed.
    """
    board = build_storyboard(_script(), "Why did the plan fail?")
    assert board["validation"]["passed"] is True, board["validation"]["errors"]
    assert [link["role"] for link in board["chain"]] == [row[0] for row in _CHAIN]
    assert board["chapter_count"] == 4
    assert all(link["caused_by"] for link in board["chain"][1:])


def test_a_scene_that_does_not_say_what_caused_it_fails_before_asset_spend():
    script = _script()
    script["scenes"][4]["caused_by"] = ""
    board = build_storyboard(script, "Why did the plan fail?")
    assert board["validation"]["passed"] is False
    assert any("ORPHAN_STEP" in error for error in board["validation"]["errors"])


def test_location_budget_is_measured_against_the_scripted_environments():
    """The budget check must read the script, not this module's role->location table.

    Fed from the role mapping alone it could only ever see four values, so the four-location
    continuity promise was unenforceable and the check could not fail.
    """
    script = _script(environments=[f"world_{i}" for i in range(7)])
    board = build_storyboard(script, "Why did the plan fail?")

    # Seven scripted worlds are now COLLAPSED to the budget rather than failing the run: the count
    # is mechanically decidable, and this codebase already fixes that class for free instead of
    # re-buying it (see repair_chain on the causal spine). The moves are the proof the SCRIPT was
    # read — fed from the role table's four values there would have been nothing to collapse.
    assert board["visual_bible"]["location_moves"], "7 scripted worlds must produce moves"
    assert len(board["visual_bible"]["locations"]) <= LOCATION_BUDGET
    assert board["visual_bible"]["location_budget"] == LOCATION_BUDGET
    assert not any("against a budget of 4" in error
                   for error in board["validation"]["errors"])


def test_scripted_environments_within_budget_pass_and_are_recorded():
    script = _script(environments=["home", "city", "Science Lab"])
    board = build_storyboard(script, "Why did the plan fail?")

    assert board["validation"]["passed"] is True
    assert board["visual_bible"]["locations"] == ["city", "home", "science_lab"]


def test_scenes_without_a_declared_environment_fall_back_to_story_position():
    board = build_storyboard(_script(), "Why did the plan fail?")
    assert board["validation"]["passed"] is True
    assert board["visual_bible"]["locations"] == [
        "action_location", "consequence_location", "opening_location", "planning_location"]


def test_story_direction_states_the_budget_the_validator_enforces():
    """The script prompt and the validator must name the same number.

    The base script schema tells the model to VARY environment_type, so without this override
    the now-enforceable budget would reject nearly every illustrated script.
    """
    direction = story_direction("Why did the plan fail?")
    assert f"at most {LOCATION_BUDGET} distinct environment_type" in direction
    assert "overrides that instruction" in direction


def test_parallel_cases_reach_the_validator_from_the_script():
    """They were fetched by the spine pass and then dropped before the check that needs them.

    A generalization beat with real cases attached failed THIN_GENERALIZATION because
    build_storyboard never passed them on.
    """
    script = _script()
    script["scenes"][-2]["causal_role"] = "generalization"
    assert any("THIN_GENERALIZATION" in error for error in
               build_storyboard(script, "q")["validation"]["errors"])

    script["_parallel_cases"] = [
        {"domain": "d1", "problem": "p", "solution": "s", "result": "r"},
        {"domain": "d2", "problem": "p", "solution": "s", "result": "r"},
    ]
    assert not any("THIN_GENERALIZATION" in error for error in
                   build_storyboard(script, "q")["validation"]["errors"])


def test_the_style_asks_for_round_white_heads_not_detailed_faces():
    """The consistency lever, and the one spec change made before the first pilot.

    Fifty to ninety images of the same people cannot hold a detailed face across independent
    generations. Both references carry identity in clothing and silhouette instead, so the style
    must ask for that explicitly rather than hope for it.
    """
    suffix = visual_style_suffix()
    assert "round white heads" in suffix
    assert "never by facial detail" in suffix
    assert "detailed rendered faces" in negative_prompt()


def test_the_lane_now_has_a_negative_prompt():
    negative = negative_prompt()
    for banned in ("photorealism", "3D render", "inconsistent characters", "watermarks"):
        assert banned in negative


def test_an_unknown_role_is_reported_not_raised():
    """`_LOCATION_BY_ROLE[role]` raised KeyError before the validator could speak.

    A single mislabelled scene killed the run with a bare exception instead of the readable list of
    everything wrong with the script — and a blank role is exactly what a replan that dropped the
    causal lane produces.
    """
    board = build_storyboard(
        {"title": "T", "hook": "h",
         "scenes": [{"narration": "something happens here", "causal_role": "bogus",
                     "human_intention": "q"}]},
        "why?")
    assert board["validation"]["passed"] is False
    assert any("UNKNOWN_ROLE" in error for error in board["validation"]["errors"])


def test_the_spoken_hook_is_counted_once_in_the_runtime_estimate():
    """The clock added the hook's seconds AND counted them inside scene 1's narration.

    Measured 6.3s of phantom runtime, which moves the mechanism's position against its deadline.
    """
    import causal_story as cs
    script = _script()
    cs.finalize_narration(script["scenes"], hook=script["hook"],
                          format_tag="explained like you are five")
    board = build_storyboard(script, "Why did the plan fail?")

    words = sum(len(scene["narration"].split()) for scene in script["scenes"])
    from illustrated_story import REFERENCE_WPM
    assert board["estimated_runtime_sec"] == pytest.approx(words / REFERENCE_WPM * 60.0, abs=0.2)


def test_the_causal_engine_id_survives_the_structure_review():
    """`_story_engine` holds an engine id; the story-structure review returns a report dict from a
    different module whose name differs by one letter. Writing the report to that key destroyed the
    engine identity mid-run and cost three renders — the storyboard then judged an
    accumulating-indictment story against The Backfiring Solution and failed it for missing a
    `tool` beat that only that engine requires."""
    source = (ROOT / "explainer_pipeline.py").read_text(encoding="utf-8")
    assert 'script["_story_engine"] = _review_story_structure(' not in source
    assert 'script["_story_structure_review"] = _review_story_structure(' in source


def test_an_unreadable_engine_falls_back_to_the_generic_contract():
    """Not to the default engine. resolve_id is lenient by design, so a non-string silently
    validates against whatever DEFAULT_ENGINE happens to be rather than failing visibly."""
    source = (ROOT / "illustrated_story.py").read_text(encoding="utf-8")
    assert 'isinstance(declared, str)' in source
    assert 'se.get(script["_story_engine"])' not in source


def _beats(*locations):
    return [{"location_id": loc} for loc in locations]


def test_collapse_is_a_no_op_inside_the_budget():
    beats = _beats("a", "b", "a", "c")
    assert ils.collapse_locations(beats) == []
    assert [b["location_id"] for b in beats] == ["a", "b", "a", "c"]


def test_collapse_brings_the_count_to_the_budget():
    """The budget was enforced by asking for it and failing the run when the script said no."""
    beats = _beats("a", "b", "c", "d", "e", "f", "a", "b", "c", "d")
    ils.collapse_locations(beats, budget=4)
    assert len({b["location_id"] for b in beats}) <= 4


def test_the_least_used_locations_are_the_ones_folded_away():
    beats = _beats("lab", "lab", "lab", "city", "city", "home", "rare")
    ils.collapse_locations(beats, budget=2)
    kept = {b["location_id"] for b in beats}
    assert kept == {"lab", "city"}, "frequency decides which places survive"


def test_an_orphaned_scene_adopts_the_place_the_story_is_already_in():
    """Nearest, not most-common. The budget exists to make the video feel continuous, so sending a
    stranded beat somewhere the story is not currently would satisfy the count and break its point."""
    beats = _beats("lab", "lab", "lab", "lab", "orphan", "city", "city")
    ils.collapse_locations(beats, budget=2)
    assert beats[4]["location_id"] == "lab", "should continue the place it just came from"


def test_collapse_is_deterministic_across_equal_counts():
    first = _beats("a", "b", "c", "d")
    second = _beats("a", "b", "c", "d")
    ils.collapse_locations(first, budget=2)
    ils.collapse_locations(second, budget=2)
    assert [b["location_id"] for b in first] == [b["location_id"] for b in second]


def test_location_repair_updates_the_scene_consumed_by_rendering():
    script = _script()
    locations = ["market", "office", "sewer", "farm", "laboratory"]
    for index, scene in enumerate(script["scenes"]):
        scene["environment_type"] = locations[index % len(locations)]

    board = build_storyboard(script, "Why did the plan fail?")

    assert len(set(board["visual_bible"]["locations"])) <= ils.LOCATION_BUDGET
    assert [scene["environment_type"] for scene in script["scenes"]] == [
        beat["location_id"] for beat in board["beats"]]
    assert "laboratory" not in {scene["environment_type"] for scene in script["scenes"]}


def test_repair_chain_runs_before_the_storyboard_validates():
    """_assign_causal_spine has always repaired its output; the storyboard re-derived steps from
    the scenes and validated them raw, so an order mistake repair had already fixed came back as a
    hard ENGINE_ORDER failure. The repair existed — it was not wired into this path."""
    source = (ROOT / "illustrated_story.py").read_text(encoding="utf-8")
    repair = source.index("cs.repair_chain(steps, engine)")
    validate = source.index("causal = cs.validate_causal_story(")
    assert repair < validate, "repair must run before validation, not after"


def test_the_repair_is_written_back_to_the_scene():
    """A repair that satisfies the validator without changing the story is a green metric over
    wrong output — the exact failure mode this build has been bitten by repeatedly."""
    source = (ROOT / "illustrated_story.py").read_text(encoding="utf-8")
    assert 'scene["causal_role"] = step["role"]' in source


def test_a_chapter_that_does_not_announce_itself_gets_the_marker():
    scenes = [{"narration": "It begins here."}, {"narration": "And continues."},
              {"narration": "A new chapter opens."}]
    scenes[0]["chapter"], scenes[1]["chapter"], scenes[2]["chapter"] = 1, 1, 2
    added = ils.announce_chapters(scenes)

    assert added == ["Step one.", "Step two."]
    assert scenes[0]["narration"] == "Step one. It begins here."
    assert scenes[2]["narration"] == "Step two. A new chapter opens."
    assert scenes[1]["narration"] == "And continues.", "only the opening scene announces"


def test_the_marker_is_prepended_never_substituted():
    """Claim bindings and anchor phrases are bound to exact narration substrings, so the original
    wording has to survive intact inside the new line."""
    scenes = [{"narration": "Lead was known to be poison.", "chapter": 1}]
    ils.announce_chapters(scenes)
    assert "Lead was known to be poison." in scenes[0]["narration"]


def test_an_already_announced_chapter_is_left_alone():
    scenes = [{"narration": "Step one. It begins.", "chapter": 1}]
    assert ils.announce_chapters(scenes) == []
    assert scenes[0]["narration"] == "Step one. It begins."


def test_the_marker_reaches_the_scene_the_narrator_actually_reads():
    """Announcing into a copy the validator sees would clear the gate without changing the video.
    Because the announcer now runs before the step list is built, the marker reaches the script's
    own scene and every downstream consumer — narration, TTS and the clock — sees the same words."""
    script = _script(environments=["home", "city"])
    for index, scene in enumerate(script["scenes"]):
        scene["chapter"] = 1 if index == 0 else 2
        scene["narration"] = f"Plain line {index}."
    build_storyboard(script, "Why did the plan fail?")

    assert script["scenes"][0]["narration"].startswith("Step one.")
    assert "Plain line 0." in script["scenes"][0]["narration"], "prepend, never substitute"
