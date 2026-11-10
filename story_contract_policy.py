"""Gate policy for the story-contract lane (docs/STORY_CONTRACT_LANE.md, operator 2026-10-21).

The lane writes one continuous narration from an approved story contract, and the operator then
approves that exact narration by its hash. The compiled lane's gates read role labels and
structure, and they ranked the lionfish catalogue (91 A) above the better story (74 C), so this
lane keeps only the gates about facts and delivery:

    claim ledger, quotation binding, source fetch   hard (facts)
    storyboard integrity, delivery, loudness        kept
    structural late_turn / 116-word turn budget     report only
    readiness "Narrative propulsion"                report only
    engine role order / min escalation / templates  not applied
    story_shape writer rules                        not applied
    opening_retry below B                           degraded, not stopped
    any narration rewrite after approval            stops for a new approval

Everything here keys on `script["_lane"] == LANE`, which only the lane's segmenter writes, so a
script from any other lane gets exactly the behaviour it had before this module existed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

LANE = "story_contract"

GATES = {
    "claim_ledger": "hard",
    "storyboard_integrity": "hard",
    "technical_delivery": "hard",
    "structural_turn": "report",
    "readiness_narrative_propulsion": "report",
    "engine_templates": "off",
    "story_shape_writer_rules": "off",
    "opening_retry_below_b": "degraded",
    "narration_rewrite_after_approval": "approval",
}

# Storyboard (causal_story) findings that stay blocking in this lane. They are integrity checks on
# what the segmenter produced, not on the story's shape: a scene list with no steps, no runtime, a
# role the renderer cannot draw, or a cause pointing at a scene that does not exist or comes later.
# Every other causal_story code is an engine template (role order, escalation count, hinge length,
# hook/close/synthesis templates, sentence-mix bands) and is reported, never blocking.
STORYBOARD_KEPT_CODES = frozenset({
    "NO_STEPS", "NO_RUNTIME", "UNKNOWN_ROLE", "DANGLING_CAUSE", "BACKWARD_CAUSE",
})

# Retention-readiness components scored and printed but left out of the grade.
READINESS_REPORT_ONLY = ("Narrative propulsion",)

REPORT_PREFIX = "[report only, story_contract lane] "


def is_lane(script) -> bool:
    return isinstance(script, dict) and str(script.get("_lane") or "") == LANE


def readiness_report_only(script) -> tuple:
    return READINESS_REPORT_ONLY if is_lane(script) else ()


def engine_templates_applied(script) -> bool:
    return not is_lane(script)


def turn_report_only(script) -> bool:
    return is_lane(script)


def opening_below_b_action(script) -> str:
    """'stop' (the compiled lane's OpeningBelowB) or 'degraded' (this lane)."""
    return "degraded" if is_lane(script) else "stop"


def split_storyboard_issues(issues: list) -> tuple[list, list]:
    """(kept, demoted) causal_story issues for this lane. Issues are {'code', 'message', ...}."""
    kept, demoted = [], []
    for issue in issues or []:
        code = str((issue or {}).get("code") or "")
        (kept if code in STORYBOARD_KEPT_CODES else demoted).append(issue)
    return kept, demoted


# ── the approved narration ────────────────────────────────────────────────────────────────────

def normalize_narration(text: str) -> str:
    """Whitespace-normalised narration: the form the hash binds. Words and punctuation untouched."""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def narration_sha256(text: str) -> str:
    return hashlib.sha256(normalize_narration(text).encode("utf-8")).hexdigest()


def scenes_narration(scenes: list) -> str:
    return normalize_narration(" ".join(str((s or {}).get("narration") or "") for s in scenes or []))


class NarrationChangedRequiresApproval(RuntimeError):
    """Production changed the approved words. The new version is written for review; nothing paid
    for media has been bought on it."""

    def __init__(self, message: str, *, path: str = "", sha256: str = ""):
        super().__init__(message)
        self.path = path
        self.sha256 = sha256


def check_approved_narration(script: dict, output_dir: str = "") -> None:
    """Raise unless the script's narration is the one the operator approved (by hash).

    Called before the first media purchase. Any stage between approval and here that rewrote a
    word (a claim-ledger repair, a refit, a lead re-insertion) produces a new narration version
    that goes back to the operator instead of into TTS.
    """
    if not is_lane(script):
        return
    meta = script.get("_story_contract_lane") or {}
    approved = str(meta.get("approved_narration_sha256") or "")
    text = scenes_narration(script.get("scenes") or [])
    current = narration_sha256(text)
    if approved and approved == current:
        return
    path = ""
    if output_dir:
        path = os.path.join(output_dir, "narration_changed_for_approval.md")
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("# Narration changed after approval\n\n")
                handle.write(f"Approved sha256: `{approved or '(none)'}`\n\n")
                handle.write(f"Current sha256: `{current}`\n\n")
                handle.write("Production rewrote words in the approved narration. Review this "
                             "version; approve it with `--approve-narration " + current + "`.\n\n")
                handle.write(text + "\n")
        except OSError:
            path = ""
    raise NarrationChangedRequiresApproval(
        "STORY_CONTRACT_NARRATION_CHANGED: the narration about to be voiced is not the approved "
        f"one (approved {approved[:12] or 'none'}, now {current[:12]}). No media was bought; the "
        "new version is written for review" + (f" at {path}" if path else "") + ".",
        path=path, sha256=current)


def describe() -> str:
    return json.dumps(GATES, indent=2)
