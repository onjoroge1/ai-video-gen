"""The prediction requirement must be satisfiable by the format being judged.

The evidence-led mystery's beat-sheet spec says "At most ONE prediction/guess prompt to
the viewer, and never before the reversal". The retention contract asked a 120s video for
two, with the first inside 30 seconds. The model obeyed the prompt and the gate rejected
the result -- 4 of 6 measured runs, the single most common blocker.
"""

from longform_retention import validate_longform_story

# The requirement only rises to two at >=120s of runtime, so the fixtures must actually
# reach that. With short narration every scene set runs under 120s, needed_predictions is
# 1 for both formats, and the tests pass without exercising the policy at all.
_LONG = " ".join(["the researcher watched the culture change colour again and again"] * 6) + "."


def _scene(index, role, mystery_role="", narration=_LONG):
    # story_role is the field the validator reads; mystery_role/_role identify the format.
    return {
        "narration": narration, "story_role": role, "role": role,
        "mystery_role": mystery_role, "_role": mystery_role, "scene_index": index,
    }


def _mystery(prediction_count):
    # A mystery is identified by roles that exist only in its vocabulary.
    roles = ["anomaly", "false_belief", "seal", "reversal", "mechanism",
             "second_revelation", "scope_shift", "resolution"]
    scenes = [_scene(i, "escalation", role) for i, role in enumerate(roles)]
    for i in range(prediction_count):
        scenes[3 + i]["story_role"] = "prediction_gate"
    return {"scenes": scenes, "title": "Why doctors were wrong about ulcers"}


def _standard(prediction_count):
    scenes = [_scene(i, "escalation") for i in range(8)]
    for i in range(prediction_count):
        scenes[3 + i]["story_role"] = "prediction_gate"
    return {"scenes": scenes, "title": "How a jet engine works"}


def _codes(report):
    return {issue["code"] for issue in report.get("errors", [])}


def test_one_prediction_satisfies_a_mystery():
    # What the format's own spec permits must be enough to pass.
    report = validate_longform_story(_mystery(1), "why were doctors wrong about ulcers")

    assert "too_few_predictions" not in _codes(report)


def test_zero_predictions_still_fails_a_mystery():
    # The requirement is relaxed to one, not removed.
    report = validate_longform_story(_mystery(0), "why were doctors wrong about ulcers")

    assert "too_few_predictions" in _codes(report)


def test_a_standard_explainer_still_needs_two_at_long_runtime():
    # The relaxation is specific to the format whose spec contradicts it.
    report = validate_longform_story(_standard(1), "how a jet engine works")

    assert "too_few_predictions" in _codes(report)


def test_the_stamped_format_survives_a_replan_that_drops_mystery_roles():
    """A replan can leave every scene carrying a standard role name.

    `_role` falls back to `story_role` when a beat has no mystery_role, so inference from
    role names alone reports "standard explainer" and applies rules the mystery prompt
    forbids. Run 9f8a6cd1 was asked for one prediction on its first pass and then failed
    the 30-second rule on its second, for exactly this reason.
    """
    script = _mystery(1)
    for scene in script["scenes"]:
        scene["_role"] = scene["story_role"]        # what a replan leaves behind
        scene["mystery_role"] = ""
        scene["_story_format"] = "evidence_led_mystery"

    report = validate_longform_story(script, "why were doctors wrong about ulcers")

    # The COUNT relaxation is what this test guards -- one prediction satisfies a mystery where
    # a standard explainer needs two. The 30-second deadline applies to both again.
    assert "too_few_predictions" not in _codes(report)


def test_a_late_prediction_fails_a_mystery_too():
    """The 30-second deadline applies to a mystery again.

    It was exempted because "never before the reversal" puts the earliest legal prediction at
    22-35% of runtime, past 30s in a 120s video. An editorial review of the first finished video
    found what that exemption cost: "the first real prediction gate arrives after 34 seconds.
    This interaction should appear around 10-15 seconds and then be answered later."

    The band conflict is real. The answer is to place the reversal earlier, not to stop
    measuring -- an unmeasurable requirement is not a relaxed one, it is an absent one.
    """
    report = validate_longform_story(_mystery(1), "why were doctors wrong about ulcers")

    assert "late_first_prediction" in _codes(report)
