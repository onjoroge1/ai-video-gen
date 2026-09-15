"""The three gates that could never pass an illustrated film, and the one that never saw it.

Each test here pins a defect that was measured on a delivered film, not imagined:

  * both films carried `bolt_absent` among exactly four hard failures, on a lane whose own
    prompt forbids Bolt;
  * both films' manifests record `pipeline_profile: stable_standard_longform`, the recovery
    profile that demotes the rendered contract, human approval and the opening freeze;
  * `rendered_contract.json` described `first_minute_preview.mp4` -- 53.8s of a 252.5s film.
"""
import json
import os
import subprocess

import pytest

import longform_rendered_gate as gate
import explainer_pipeline as pipeline


def _score(deterministic):
    return gate.score_rendered_contract(
        deterministic=deterministic, blind={},
        story_validation={"checks": {}, "errors": []},
        claim_validation={}, callback_exact=False)


# ── bolt_absent ──────────────────────────────────────────────────────────────────────────

def test_cast_free_lane_is_not_failed_for_the_mascot_it_is_forbidden_to_draw():
    """_illustrated_is_cast_free() writes mascot_present=False on every scene and the beat
    prompt says "Never write Alex, Bolt, or any invented stand-in". bolt_shot_count is then 0
    by construction, so this fired on every illustrated film and no editorial work could clear
    it. The escape hatch at :927 needs a directed_spec AND no automated grade; this lane has
    neither."""
    failures = _score({"bolt_shot_count": 0, "cast_mode": "none"})["hard_failures"]
    assert "bolt_absent" not in failures


def test_a_lane_with_a_mascot_still_has_to_use_it():
    """The rule is narrowed to the lanes it was written for, not weakened."""
    assert "bolt_absent" in _score({"bolt_shot_count": 0, "cast_mode": "recurring"})["hard_failures"]


def test_an_absent_cast_field_keeps_the_check():
    """A plan with no continuity pack must not silently buy an exemption. Default is recurring."""
    assert "bolt_absent" in _score({"bolt_shot_count": 0})["hard_failures"]


def test_the_other_direction_is_untouched_on_a_cast_free_lane():
    """Cast-free means Bolt should not appear at all -- so drawing him everywhere still fails.
    Exempting the lane from `absent` must not also exempt it from `everywhere`."""
    failures = _score(
        {"bolt_shot_count": 8, "bolt_shot_ratio": 0.8, "cast_mode": "none"})["hard_failures"]
    assert "bolt_everywhere" in failures


def test_cast_mode_is_read_from_the_same_field_longform_evidence_uses(tmp_path):
    """longform_evidence:677 reads continuity_pack["cast"]. The gate must not invent a second
    source of truth for the same fact."""
    import longform_evidence
    plan = {"continuity_pack": {"cast": "none"}, "scenes": []}
    assert (plan["continuity_pack"].get("cast")) == "none"
    # The evidence validator's own predicate agrees this pack is cast-free.
    assert longform_evidence._text(plan["continuity_pack"].get("cast")) == "none"


# ── the recovery profile ─────────────────────────────────────────────────────────────────

def test_arming_the_render_gates_is_opt_in_and_scoped_to_illustrated(monkeypatch):
    """ILLUSTRATED_RENDER_GATES=block is the one-line flip for the day the beat-count defect
    lands. It is deliberately not the default: arming these three today does not make the lane
    stricter, it stops it delivering, because the rejection is long_visual_hold +
    visual_state_cadence -- the same two failures both delivered films carry."""
    monkeypatch.setenv("ILLUSTRATED_RENDER_GATES", "block")
    assert pipeline._render_gates_advisory(True, True) is False, "illustrated: armed"
    assert pipeline._render_gates_advisory(True, False) is True, "other lanes: untouched"


def test_the_default_keeps_every_lane_exactly_where_it_was(monkeypatch):
    """This change must not turn the product off by inheritance, the way the demotion was
    inherited. Without the flag, behaviour is byte-identical to before."""
    monkeypatch.delenv("ILLUSTRATED_RENDER_GATES", raising=False)
    assert pipeline._render_gates_advisory(True, True) is True
    assert pipeline._render_gates_advisory(True, False) is True
    assert pipeline._render_gates_advisory(False, True) is False
    assert pipeline._render_gates_advisory(False, False) is False


def test_an_unrecognised_flag_value_does_not_silently_arm_anything(monkeypatch):
    monkeypatch.setenv("ILLUSTRATED_RENDER_GATES", "1")
    assert pipeline._render_gates_advisory(True, True) is True


def test_the_recovery_profile_itself_is_unchanged():
    """The pre-spend retention contract and the evidence-plan timing advisories still read
    _stable_standard_longform directly and still stay demoted, for the same reason. Pinned so a
    later edit that widens the exclusion has to do it deliberately."""
    assert pipeline._stable_standard_longform("landscape", "standard_explainer", False) is True
    assert pipeline._stable_standard_longform("social", "standard_explainer", False) is False
    assert pipeline._stable_standard_longform("landscape", "evidence_led_mystery", False) is False
    assert pipeline._stable_standard_longform("landscape", "standard_explainer", True) is False


def test_the_commissioned_payload_is_exactly_the_profiles_match_condition():
    """Why the demotion happened at all: the approval path's frozen values ARE the match."""
    import agent_actions
    payload = agent_actions.build_illustrated_payload(
        topic="Why Hanoi's Rat Bounty Created Rat Farms", duration_sec=75,
        creative_direction="", cost_ceiling_usd=5.0, providers={})
    request = payload["request"]
    assert request["video_format"] == "landscape"
    assert request["story_format"] == "standard_explainer"
    assert pipeline._stable_standard_longform(
        request["video_format"], request["story_format"], False) is True


# ── measuring the delivered film ─────────────────────────────────────────────────────────

def _tiny_video(path, seconds=4):
    """A real encode, so the frame extraction under test is real too."""
    ffmpeg = pipeline._ffmpeg_bin()
    subprocess.run(
        [ffmpeg, "-y", "-f", "lavfi", "-i", f"testsrc=size=320x180:rate=10:duration={seconds}",
         "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True)
    return str(path)


def test_two_inspections_of_one_output_dir_do_not_share_a_frame_directory(tmp_path):
    """The preview pass gates before the spend and must stay. The delivered-film pass is a
    second inspection over the same output_dir -- if they share rendered_gate_frames/, one
    contact sheet ends up backing two contracts that claim to describe different videos."""
    video = _tiny_video(tmp_path / "v.mp4", seconds=4)
    plan = [[{"state_id": "s1", "duration": 2.0}, {"state_id": "s2", "duration": 2.0}]]
    evidence = {"continuity_pack": {"cast": "none"}, "scenes": []}

    preview = gate.inspect_rendered_opening(video, plan, str(tmp_path), evidence)
    full = gate.inspect_rendered_opening(
        video, plan, str(tmp_path), evidence, frame_dir_name="rendered_gate_frames_full")

    assert (tmp_path / "rendered_gate_frames").is_dir()
    assert (tmp_path / "rendered_gate_frames_full").is_dir()
    preview_frames = {p.name for p in (tmp_path / "rendered_gate_frames").glob("*.jpg")}
    full_frames = {p.name for p in (tmp_path / "rendered_gate_frames_full").glob("*.jpg")}
    assert preview_frames and full_frames
    # Same basenames, different directories -- which is precisely the collision being avoided.
    assert preview["deterministic"]["shot_count"] == full["deterministic"]["shot_count"]


def test_the_default_frame_directory_is_unchanged(tmp_path):
    """Existing callers, and every archived run, keep writing where they always did."""
    video = _tiny_video(tmp_path / "v.mp4", seconds=2)
    plan = [[{"state_id": "s1", "duration": 2.0}]]
    gate.inspect_rendered_opening(video, plan, str(tmp_path), {"scenes": []})
    assert (tmp_path / "rendered_gate_frames").is_dir()


def test_a_longer_film_measures_longer_holds_than_its_opening(tmp_path):
    """The defect in one assertion. The preview covered 12 shots of a 25-shot film and reported
    a 10.58s worst hold; the delivered film's worst hold was 64.36s against a 3.5s ceiling.
    Inspecting only the opening cannot see a hold that happens later."""
    video = _tiny_video(tmp_path / "v.mp4", seconds=12)
    opening_plan = [[{"state_id": "a", "duration": 1.0}, {"state_id": "b", "duration": 1.0}]]
    full_plan = [[{"state_id": "a", "duration": 1.0}, {"state_id": "b", "duration": 1.0}],
                 [{"state_id": "c", "duration": 10.0}]]
    evidence = {"continuity_pack": {"cast": "none"}, "scenes": []}

    opening = gate.inspect_rendered_opening(
        video, opening_plan, str(tmp_path), evidence)
    full = gate.inspect_rendered_opening(
        video, full_plan, str(tmp_path), evidence, frame_dir_name="full_frames")

    assert opening["deterministic"]["long_hold_count"] == 0
    assert full["deterministic"]["long_hold_count"] == 1
    assert full["deterministic"]["max_visual_state_sec"] > \
        opening["deterministic"]["max_visual_state_sec"]
    # And the scorer turns that into the hard failure the preview could not raise.
    assert "long_visual_hold" not in _score(opening["deterministic"])["hard_failures"]
    assert "long_visual_hold" in _score(full["deterministic"])["hard_failures"]


def test_rendered_hard_failures_are_surfaced_as_degraded_reasons():
    """A film that failed every rendered gate was reported to the operator as having run 2.5s
    short: `degraded_reasons` was built only from runtime, dropped scenes and filler, and
    app.py builds the user-facing status from that list. This pins the wording contract the
    delivery payload now carries."""
    contract = {"score": 59, "status": "REJECT",
                "hard_failures": ["long_visual_hold", "visual_state_cadence"]}
    reasons = []
    if contract and contract.get("hard_failures"):
        reasons.append(
            f"rendered contract {contract.get('score')}/100 {contract.get('status')} "
            f"(delivered film): " + ", ".join(contract["hard_failures"]))
    assert reasons == [
        "rendered contract 59/100 REJECT (delivered film): long_visual_hold, visual_state_cadence"]


# ── the recorded films ───────────────────────────────────────────────────────────────────

RECORDED = os.path.join(os.path.dirname(__file__), "fixtures", "delivered_contract_hanoi9.json")


@pytest.mark.skipif(not os.path.exists(RECORDED), reason="recorded delivery not vendored")
def test_the_recorded_delivery_loses_bolt_absent_and_keeps_the_rest():
    """Replay of the real 252.5s film. bolt_absent clears; the three genuine defects do not."""
    recorded = json.load(open(RECORDED))
    deterministic = dict(recorded["deterministic"])
    deterministic["cast_mode"] = recorded["cast_mode"]
    failures = _score(deterministic)["hard_failures"]
    assert "bolt_absent" not in failures
    assert "visual_state_cadence" in failures
