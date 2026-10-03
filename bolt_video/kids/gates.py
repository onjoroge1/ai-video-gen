"""Fail-closed Kids gates. A plan is not evidence of pixels, action, or learning."""
from __future__ import annotations

import json
from pathlib import Path

from .models import POLICY_VERSION, canonical_hash


class KidsGateFailure(ValueError):
    """A content failure: retain reports and completed spend; do not blindly retry."""


class GateBook:
    def __init__(self, output, spec_hash):
        self.path = Path(output) / "kids_gates.json"
        self.spec_hash = spec_hash
        self.rows = []

    def record(self, name, checks, *, evidence=None, unavailable=False):
        # Explicit named non-empty booleans; neither {}, None, nor a truthy string can pass.
        good = bool(checks) and all(type(v) is bool and v for v in checks.values())
        status = "unscored_unavailable" if unavailable else "passed" if good else "needs_repair"
        row = {"gate": name, "status": status, "checks": checks,
               "evidence": evidence or {}, "policy_version": POLICY_VERSION,
               "spec_sha256": self.spec_hash}
        self.rows.append(row)
        self.path.write_text(json.dumps({"policy_version": POLICY_VERSION,
            "spec_sha256": self.spec_hash, "gates": self.rows,
            "publishable": False, "audience_engagement": "unmeasured"}, indent=2, allow_nan=False))
        if status != "passed":
            failed = [key for key, value in checks.items() if value is not True]
            raise KidsGateFailure(f"Kids {name}: {status}; {', '.join(failed) or 'assessment unavailable'}. See kids_gates.json")
        return row


def timing_checks(episode, timeline):
    assets = {asset.id: asset for asset in episode.assets}
    checks = {"approximately_two_minutes": 110 <= timeline["duration_sec"] <= 130,
              "no_audio_time_stretch": timeline["audio_time_stretch"] is False}
    for shot in timeline["shots"]:
        duration = shot["end_sec"]-shot["start_sec"]
        asset = assets[shot["asset_id"]]
        checks[f"{shot['id']}:minimum_hold"] = duration >= 1.25
        if asset.mode == "still":
            # A listening pause is intentional, not a missing visual/narration scene.
            checks[f"{shot['id']}:still_hold"] = duration <= (10 if shot["role"] == "question" else 7)
        elif not asset.reference_id and not asset.loopable:
            checks[f"{shot['id']}:action_fits"] = duration <= asset.motion_seconds + 1/24
    for cue in timeline["cues"]:
        if cue["kind"] == "pause":
            authored = next(c for b in episode.beats for c in b.audio if c.id == cue["id"])
            checks[f"{cue['id']}:pause_preserved"] = abs(cue["end_sec"]-cue["start_sec"]-authored.duration_sec) < .001
    return checks


def judge_checks(result, required):
    """Validate the independent critic schema, not author-provided declarations."""
    if not isinstance(result, dict) or set(result) != {"checks", "evidence"}:
        return {}, True
    checks = result.get("checks")
    if (not isinstance(checks, dict) or set(checks) != set(required)
            or any(type(v) is not bool for v in checks.values())
            or not isinstance(result.get("evidence"), str) or len(result["evidence"].strip()) < 10):
        return {}, True
    return checks, False


SCRIPT_CHECKS = ("one_clear_learning_goal", "age_appropriate_and_kind", "fair_identifiable_clues",
                 "correct_learning_claims", "no_franchise_imitation", "resolved_ending",
                 "actionable_original_lyrics", "no_unsafe_imitation")
IMAGE_CHECKS = ("robot_identity_matches_reference", "declared_cast_and_set_match", "clear_uncluttered_composition",
                "no_accidental_answer_leak", "first_state_matches", "age_appropriate")
ACTION_CHECKS = ("identity_stable", "action_occurs_in_order", "no_unplanned_events", "no_malformed_characters",
                 "last_state_matches", "loop_is_valid_when_requested")
FINAL_CHECKS = ("clear_story_progression", "correct_visible_answers", "consistent_robot", "no_disturbing_imagery",
                "recap_matches_reveals", "readable_composition")


def release_check(automatic, video_sha256, decision, checklist):
    required = {"watched_entire_video", "voices_and_lyrics_intelligible", "learning_content_correct",
                "actions_and_answers_match", "age_appropriate", "rights_and_disclosure_reviewed"}
    return bool(automatic.get("status") == "passed" and automatic.get("video_sha256") == video_sha256
                and decision == "approve" and isinstance(checklist, dict) and set(checklist) == required
                and all(value is True for value in checklist.values()))
