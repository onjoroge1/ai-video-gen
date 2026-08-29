"""Build the production Hippo contract from the locked Markdown and shot-plan tables."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import user_directed  # noqa: E402


SOURCE = ROOT / "spec" / "hippo_bacon_video_generation_spec.md"
OUTPUT = ROOT / "spec" / "hippo_bacon_directed_v1.json"
BOLT_PATH = ROOT / "assets" / "mascot" / "bolt.png"

CLAIMS_BY_SCENE = {
    "scene_002": ["F01"],
    "scene_003": ["F01", "F04"],
    "scene_005": ["F04"],
    "scene_006": ["F04"],
    "scene_007": ["F01", "F04"],
    "scene_008": ["F01", "F02", "F03"],
    "scene_009": ["F05"],
    "scene_011": ["F05"],
    "scene_020": ["F06"],
    "scene_021": ["F07"],
    "scene_028": ["F08"],
    "scene_029": ["F08", "F09", "F10"],
    "scene_030": ["F09", "F10"],
    "scene_034": ["F11"],
    "scene_035": ["F11"],
    "scene_040": ["F05"],
}

OVERLAYS_BY_START = {
    3.0: "LAKE COW BACON",
    9.0: "HIPPO CROSSING",
    15.0: "ANIMAL LOOSE\nSCHOOL ROUTE CLOSED",
    24.0: "ROBERT F. BROUSSARD\nLOUISIANA · 1910",
    27.0: "H.R. 23261",
    36.0: "1910 · REAL BILL",
    242.0: "PROMISE → BIOLOGY",
}

# The opening keeps 15 unique masters. Later sequences deliberately reuse wide, layered masters
# through crops and camera paths; these group counts follow the continuity blocks in section 10.
GROUP_RANGES = (
    (45.0, 92.0, 4),
    (92.0, 155.0, 5),
    (155.0, 205.0, 4),
    (205.0, 260.0, 5),
    (260.0, 325.0, 5),
    (325.0, 415.0, 8),
    (415.0, 465.0, 4),
    (465.0, 515.1, 5),
)

BOLT_ACTIONS = {
    36.0: "Bolt pins a 1910 REAL BILL evidence card onto the congressional document",
    242.0: "Bolt rotates the bright promise diagram to reveal the red biology evidence side",
    498.0: "Bolt silently removes the counterfactual package as the ordinary shelf returns",
}


def _partition(items: list[dict], count: int) -> list[list[dict]]:
    groups = []
    for index in range(count):
        begin = round(index * len(items) / count)
        end = round((index + 1) * len(items) / count)
        if begin < end:
            groups.append(items[begin:end])
    return groups


def _shot_covering(shots: list[dict], second: float) -> dict:
    return next(
        shot for shot in shots
        if shot["start_sec"] <= second < shot["end_sec"] + 0.001
    )


def _master_prompt(group: list[dict]) -> str:
    zones = "; ".join(shot["visual"].split(";", 1)[0].strip() for shot in group)
    return (
        "One coherent wide documentary master composition with spatially separated foreground, "
        "middle-ground and background zones for later reframing. Include these connected visual "
        f"elements: {zones}. No generated letters or readable text; reserve clean surfaces for "
        "later exact typography overlays."
    )


def build() -> dict:
    payload = user_directed.compile_directed_spec(SOURCE)
    payload["target"]["max_cost_usd"] = 25.0
    payload["acceptance"]["planned_bolt_appearances"] = 3
    payload["acceptance"]["max_unique_master_assets"] = 60

    # The prior natural-voice pilot measured about four seconds short. Add one factual bridge to
    # the opening contract instead of time-stretching audio or weakening the 43–47 second gate.
    bridge = " That evidence exposes what the proposal's confident witnesses could not yet see."
    payload["narration"][3]["narration"] += bridge

    for scene in payload["narration"]:
        scene["claim_ids"] = CLAIMS_BY_SCENE.get(scene["scene_id"], [])
    scene_claims = {scene["scene_id"]: scene["claim_ids"] for scene in payload["narration"]}
    for evidence in payload["evidence"]:
        evidence["license"] = "citation-only factual source; no source media reused"

    for world in payload["worlds"]:
        world["on_screen_label"] = {
            "alternate_2026": "COUNTERFACTUAL — ALTERNATE 2026",
            "historical_1910": "GENERATED REENACTMENT / ILLUSTRATION — 1910",
            "modern_evidence": "GENERATED ILLUSTRATION — MODERN COLOMBIA EVIDENCE",
        }[world["world_id"]]

    payload["references"] = [{
        "reference_id": "BOLT",
        "uri": "asset://mascot/bolt.png",
        "sha256": hashlib.sha256(BOLT_PATH.read_bytes()).hexdigest(),
        "mime_type": "image/png",
        "license": "project-owned generated mascot asset",
        "origin": "ReelForge assets/mascot/bolt.png",
    }]

    shots = payload["shots"]
    bolt_shots = {_shot_covering(shots, second)["shot_id"]: action
                  for second, action in BOLT_ACTIONS.items()}
    for shot in shots:
        shot["claim_ids"] = list(scene_claims.get(shot["scene_id"], []))
        shot["overlay_text"] = OVERLAYS_BY_START.get(float(shot["start_sec"]), "")
        shot["reference_ids"] = []
        shot["labels"] = []
        shot["asset_key"] = ""
        shot["asset_prompt"] = ""
        shot["transformation"] = shot["mode"]

    master_number = 0

    def assign(group: list[dict], *, prompt: str | None = None) -> None:
        nonlocal master_number
        master_number += 1
        key = f"hippo_master_{master_number:03d}"
        master = prompt or _master_prompt(group)
        for shot in group:
            shot["asset_key"] = key
            shot["asset_prompt"] = master
            shot["transformation"] = (
                f"{shot['mode']}; reframe the master toward: {shot['visual']}"
            )

    for shot in [item for item in shots if item["start_sec"] < 45.0]:
        assign([shot], prompt=(
            f"A dedicated high-retention opening master for this exact composition: {shot['visual']}. "
            "Leave any sign, package, alert, name card or document lettering blank for exact "
            "typography composited after generation."
        ))

    for begin, end, count in GROUP_RANGES:
        candidates = [
            shot for shot in shots
            if begin <= shot["start_sec"] < end and shot["shot_id"] not in bolt_shots
        ]
        for group in _partition(candidates, count):
            assign(group)

    # Bolt actions get dedicated referenced masters so mascot pixels never leak into neighboring
    # reused shots and each appearance remains a useful, countable story action.
    for shot_id, action in bolt_shots.items():
        shot = next(item for item in shots if item["shot_id"] == shot_id)
        shot["visual"] = action
        shot["mode"] = "Useful mascot beat"
        shot["labels"] = ["useful_bolt"]
        shot["reference_ids"] = ["BOLT"]
        assign([shot], prompt=(
            f"Use the supplied Bolt reference exactly and preserve his identity. {action}. "
            "Documentary compositing, purposeful full-body action, no idle reaction pose, no text."
        ))

    if any(not shot["asset_key"] for shot in shots):
        missing = [shot["shot_id"] for shot in shots if not shot["asset_key"]]
        raise RuntimeError(f"Unassigned shots: {missing}")
    unique_masters = {shot["asset_key"] for shot in shots}
    if len(unique_masters) > payload["acceptance"]["max_unique_master_assets"]:
        raise RuntimeError(f"Master cap exceeded: {len(unique_masters)}")
    return payload


if __name__ == "__main__":
    contract = build()
    OUTPUT.write_text(json.dumps(contract, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)} with "
          f"{len(contract['shots'])} shots and "
          f"{len({shot['asset_key'] for shot in contract['shots']})} masters")
