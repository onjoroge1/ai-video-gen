import copy
import json
from pathlib import Path

import nature_channel as nc
import nature_story_flow as ns


def _episode():
    return {
        "flow_id": ns.FLOW_ID,
        "channel": "nature",
        "series_id": "terrible_parents",
        "episode_id": "harp_seal_mother",
        "species": "harp seal",
        "parent_role": "mother",
        "title": "Why is this harp seal the worst mother?",
        "central_question": "Why is this harp seal the worst mother?",
        "observed_behavior": "She stops nursing before the pup can forage independently.",
        "practical_problem": "The pup still needs energy while it waits before independent feeding.",
        "engine": "strange_behaviour",
        "mechanism": {
            "resource_or_origin": "energy stored from the nursing period",
            "process": "the pup uses those reserves during the post-weaning fast",
            "offspring_benefit": "the reserves bridge the food gap",
        },
        "supported_limitation": "Stored energy does not remove every environmental dependency.",
        "ending": "End on the remaining dependency, not a fabricated reunion.",
        "word_cap": 150,
        "target_duration_sec": 40,
        "runtime_tolerance_sec": 4,
        "estimated_words_per_sec": 2.6,
        "voice": "onyx",
        "motion_model": "kling-v3-pro",
        "hard_cap_usd": 12,
        "claims": [
            {"id": "c1", "status": "verified", "passage": "verified behavior passage"},
            {"id": "c2", "status": "verified", "passage": "verified reserve passage"},
            {"id": "c3", "status": "verified", "passage": "verified limitation passage"},
        ],
        "promises": [
            {"id": "food_gap", "question": "what bridges the food gap?", "answer_beat_id": "b3"}
        ],
        "review": {"contradictions_reviewed": True, "contradictions": []},
        "visual": {
            "location": "pack ice and open water",
            "opening_object": "mother and nursing pup",
            "final_object": "weaned pup at the ice edge",
            "subject_sheet": "Adult harp seal and white-coated pup remain anatomically consistent.",
            "continuity_loop_safe": False,
            "style": "Painterly natural-history illustration, no people, vertical for the Short.",
            "negative": "people, text, logos, duplicate animals, deformed anatomy",
        },
        "beats": [
            {
                "id": "b1",
                "role": "setup",
                "development": "action",
                "new_information": "The mother ends nursing while the pup still depends on stored energy.",
                "critical_visual": True,
                "caption": "THEN SHE LEAVES",
                "claim_ids": ["c1"],
                "vo": "Why is this harp seal the worst mother? She nurses her pup, then leaves before it can forage on its own.",
                "visual_beats": [
                    {
                        "id": "b1s1", "anchor_phrase": "She nurses her pup", "purpose": "action",
                        "state_before": "mother harp seal beside her nursing pup on pack ice",
                        "state_after": "the pup finishes nursing beside the mother on pack ice",
                        "visual_proof": True,
                        "motion": "Locked camera. The pup finishes nursing; the mother remains beside it."
                    },
                    {
                        "id": "b1s2", "anchor_phrase": "then leaves", "purpose": "consequence",
                        "state_before": "mother and pup together on the ice",
                        "state_after": "mother moving toward open water while the pup remains on the ice",
                        "visual_proof": True,
                    },
                ],
            },
            {
                "id": "b2",
                "role": "hinge",
                "development": "constraint",
                "new_information": "The pup is not yet independently feeding.",
                "critical_visual": True,
                "caption": "NO MORE MILK",
                "claim_ids": ["c1"],
                "vo": "Now the milk stops, but the pup is not yet feeding for itself.",
                "visual_beats": [
                    {
                        "id": "b2s1", "anchor_phrase": "milk stops", "purpose": "consequence",
                        "state_before": "pup alone where it had been nursing",
                        "state_after": "pup resting alone on the ice with no adult feeding it",
                        "visual_proof": True,
                    }
                ],
            },
            {
                "id": "b3",
                "role": "mechanism",
                "development": "mechanism",
                "new_information": "Stored energy from nursing bridges the food gap.",
                "critical_visual": True,
                "caption": "STORED ENERGY",
                "claim_ids": ["c2"],
                "vo": "The bridge is energy it stored while nursing. During the wait, its body uses those reserves.",
                "visual_beats": [
                    {
                        "id": "b3s1", "anchor_phrase": "energy it stored", "purpose": "mechanism",
                        "state_before": "well-fed pup resting after the nursing period",
                        "state_after": "same pup resting while a simple body-reserve diagram indicates stored energy",
                        "visual_proof": True,
                    }
                ],
            },
            {
                "id": "b4",
                "role": "verdict",
                "development": "limitation",
                "new_information": "The reserve solves the food gap but not every environmental dependency.",
                "critical_visual": True,
                "caption": "IT DOESN'T SOLVE EVERYTHING",
                "claim_ids": ["c3"],
                "vo": "That reserve explains the food gap. It does not solve everything the pup still depends on. That is the trade-off.",
                "visual_beats": [
                    {
                        "id": "b4s1", "anchor_phrase": "does not solve everything", "purpose": "consequence",
                        "state_before": "weaned pup resting on stable ice",
                        "state_after": "same pup at the ice edge, with the remaining environmental dependency visible",
                        "visual_proof": True,
                    }
                ],
            },
        ],
    }


def test_shared_nature_episode_passes_pre_render_kpis():
    report = ns.validate_episode(_episode())
    assert report["passed_pre_render"] is True
    assert report["hard_failures"] == []
    statuses = {check["check_id"]: check["status"] for check in report["checks"]}
    for check in (
        "INPUTS_READY", "WORD_CAP", "HOOK_ONCE", "CLAIM_SUPPORT", "PROMISE_CLOSED",
        "MECHANISM_COMPLETE", "PARENT_SUBJECT_MATCH", "NO_CONTRADICTION", "VISUAL_PROOF",
    ):
        assert statuses[check] == "PASS"
    # Production-only facts are never laundered into green checks.
    assert statuses["TIMING_MEASURED"] == "UNKNOWN"
    assert statuses["SCRIPT_GRADE_ACTUAL"] == "UNKNOWN"
    assert statuses["RENDER_GATE_ACTUAL"] == "UNKNOWN"


def test_duplicate_hook_and_unanswered_promise_block_before_render():
    episode = _episode()
    episode["beats"][1]["vo"] = episode["central_question"] + " " + episode["beats"][1]["vo"]
    episode["promises"][0]["answer_beat_id"] = "missing"
    report = ns.validate_episode(episode)
    assert report["passed_pre_render"] is False
    assert "HOOK_ONCE" in report["hard_failures"]
    assert "PROMISE_CLOSED" in report["hard_failures"]


def test_storyboard_reuses_existing_nature_aware_evidence_planner():
    built = ns.compile_storyboard(_episode())
    assert built["script"]["_topic_channel"] == "nature"
    states = [state for scene in built["plan"]["scenes"] for state in scene["states"]]
    assert states
    assert all(state["include_human"] is False for state in states)
    assert all(state["anonymous_people_required"] is False for state in states)
    assert all(nc.FORBIDDEN_PEOPLE in state["forbidden_objects"] for state in states)


def test_short_and_long_share_identity_but_keep_profile_specific_rendering():
    episode = _episode()
    short_spec = ns.compile_keyframe_spec(episode)
    assert short_spec["flow_id"] == ns.FLOW_ID
    assert short_spec["channel"] == "nature"
    assert short_spec["engine"] == episode["engine"]
    assert short_spec["loop"] is False
    assert short_spec["beats"][0]["vo"].startswith(episode["central_question"])

    episode["target_duration_sec"] = 180
    episode["word_cap"] = 800
    kwargs = ns.longform_pipeline_kwargs(episode)
    assert kwargs["topic_channel"] == "nature"
    assert kwargs["visual_style"] == "illustrated_story"
    assert kwargs["video_format"] == "landscape"
    assert kwargs["motion_mode"] == "standard"
    assert ns.FLOW_ID in kwargs["operator_direction"]
    assert episode["central_question"] == kwargs["question"]


def test_shared_writing_contract_is_nature_only():
    assert nc.WRITING_RULES == ns.NATURE_WRITING_CONTRACT
    assert "Do not force every species into a feeding" in nc.WRITING_RULES
    assert nc.writing_rules_block("history") == ""
    assert "NATURE CHANNEL WRITING CONTRACT" in nc.writing_rules_block("nature")


def test_harp_seal_pilot_spec_passes_shared_pre_render_gate():
    path = Path(__file__).resolve().parents[1] / "spec" / "harp_seal_nature_story.json"
    episode = json.loads(path.read_text(encoding="utf-8"))
    report = ns.validate_episode(episode, profile=ns.PROFILE_SHORT)
    assert report["passed_pre_render"] is True
    assert report["metrics"]["word_count"] == 110
    storyboard = ns.compile_storyboard(episode)
    assert storyboard["validation"]["passed"] is True
    keyframe = ns.compile_keyframe_spec(episode)
    assert keyframe["loop"] is False
    assert keyframe["beats"][-1]["caption"] == "HER MILK BUYS TIME"
