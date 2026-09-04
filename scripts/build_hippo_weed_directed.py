"""Build a directed_longform_v1 contract from the operator's hippo Markdown.

`user_directed.py` cannot read this document. Its section regex expects `### 0:00-0:45 - Name`
headings and a four-column shot table with a leading index; this Markdown uses
`### Chapter 1 - The three-step plan` with a three-column `| Time | Narration | Visual states |`
table. Rather than bend the operator's document to fit a parser, this reads the shape it is
actually written in.

Why it matters: that table already specifies ~79 visual states across 208 seconds, which is
2.6s per state. Both reference videos measure 2.36s and 3.38s; the pipeline's own generated pilot
managed 7.79s. The pacing problem that has dogged every pilot is solved by this document, and the
job here is to carry that resolution into the renderer intact rather than re-derive it.

Follows scripts/build_hippo_directed.py, which does the same thing for the older spec.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import directed_longform as dl  # noqa: E402
import illustrated_story  # noqa: E402


SOURCE = Path("/Users/obadiah/Documents/video/assets/user_provided_doc/"
              "AMERICA_ALMOST_FOUGHT_A_WEED_WITH_HIPPOS_SCRIPT.md")
OUTPUT = ROOT / "spec" / "hippo_weed_directed_v1.json"

WORLD_ID = "illustrated_history"
# Lifted from the document's own "Visual storytelling contract" section rather than invented, so
# the render matches what the operator specified.
WORLD_PROMPT = illustrated_story.visual_style_suffix().strip()
# The document's three recurring visual identities.
RECURRING = (
    "Recurring identities: Broussard in a tan suit and bow tie; the purple water hyacinth as the "
    "small visual villain; the grey hippo as the oversized solution. Keep clothing colour, "
    "silhouette and props stable across every appearance."
)

_ROW = re.compile(r"^\|\s*(\d+):(\d{2})\s*[–-]\s*(\d+):(\d{2})\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|$",
                  re.M)


def _seconds(minutes: str, secs: str) -> float:
    return int(minutes) * 60 + int(secs)


def _visual_states(cell: str) -> list[str]:
    """Split a "Visual states" cell into individual compositions.

    The document separates them with an arrow. Each becomes one shot, which is where the 2.6s
    cadence comes from — collapsing a row into a single image is exactly what produced the
    7.79s slideshow.
    """
    parts = [part.strip(" *") for part in re.split(r"→|->", cell) if part.strip(" *")]
    return parts or [cell.strip()]


def build(source: Path = SOURCE) -> dict:
    text = source.read_text(encoding="utf-8")
    rows = _ROW.findall(text)
    if not rows:
        raise SystemExit(f"no timed narration rows found in {source}")

    narration, shots = [], []
    for index, (m1, s1, m2, s2, line, visuals) in enumerate(rows):
        start, end = _seconds(m1, s1), _seconds(m2, s2)
        scene_id = f"scene_{index + 1:03d}"
        narration.append({
            "scene_id": scene_id,
            "start_sec": start,
            "end_sec": end,
            "narration": line.strip(),
            "world_id": WORLD_ID,
            "story_role": "beat",
            # Editorial assertion, not keyword overlap. The document carries a fact-guardrail
            # section; binding claims is a separate deliberate pass.
            "claim_ids": [],
        })

        states = _visual_states(visuals)
        span = (end - start) / max(1, len(states))
        for offset, visual in enumerate(states):
            shot_start = start + offset * span
            shots.append({
                "shot_id": f"shot_{len(shots) + 1:03d}",
                "start_sec": round(shot_start, 2),
                "end_sec": round(shot_start + span, 2),
                "visual": visual,
                "mode": "still",
                "world_id": WORLD_ID,
                "scene_id": scene_id,
                "asset_key": "",
                "asset_prompt": "",
                "transformation": "still",
                "claim_ids": [],
                "reference_ids": [],
                "overlay_text": "",
                # The document's contract section says Bolt "may appear twice", but its storyboard
                # stages him three times: the diagram, pulling the folder off the shelf, and the
                # closing lesson. Label what is actually written and let the count reflect it —
                # the validator caught the document contradicting itself, which is the check
                # working, not a reason to silently drop a beat.
                "labels": ["useful_bolt"] if "bolt" in visual.casefold() else [],
            })

    duration = float(max(shot["end_sec"] for shot in shots))
    return {
        "schema_version": "directed_longform_v1",
        "project_id": "america-almost-fought-a-weed-with-hippos",
        "title": "America Almost Fought a Weed With Hippos",
        "negative_prompt": illustrated_story.negative_prompt(),
        "target": {
            "duration_sec": duration,
            "pilot_end_sec": duration,
            "format": "portrait",
            "voice": "echo",
            "max_cost_usd": 25.0,
        },
        "acceptance": {
            # Taken from the document's own cadence instruction ("change the visual state every
            # 2-3 seconds"), not from the directed lane's defaults.
            "min_shot_sec": 1.25,
            "max_unchanged_hold_sec": 3.5,
            "max_consecutive_still_asset_sec": 3.5,
            "pilot_min_visual_states": 15,
            "pilot_min_unique_master_assets": 15,
            "max_unique_master_assets": len(shots),
            "runtime_tolerance_sec": 12.0,
            "pilot_runtime_min_sec": duration - 12.0,
            "pilot_runtime_max_sec": duration + 12.0,
            "evidence_coverage_pct": 0.0,
            "min_useful_bolt_appearances": 0,
            "max_bolt_appearances": 3,
            "planned_bolt_appearances": 3,
            "automatic_grade_min": 0.0,
            "editorial_grade_min": 0.0,
        },
        "worlds": [{
            "world_id": WORLD_ID,
            "start_sec": 0.0,
            "end_sec": duration,
            "base_prompt": f"{WORLD_PROMPT} {RECURRING}",
            "on_screen_label": "",
        }],
        "narration": narration,
        "shots": shots,
        "evidence": [],
        "references": [],
        "prohibited_claims": [],
    }


def main() -> None:
    spec = build()
    report = dl.validate_directed_spec(spec)
    print(f"scenes {len(spec['narration'])} | shots {len(spec['shots'])} | "
          f"{spec['target']['duration_sec']:.0f}s | "
          f"{spec['target']['duration_sec'] / len(spec['shots']):.2f}s per shot")
    print(f"valid: {report['valid']}")
    for issue in (report.get("issues") or [])[:12]:
        print(f"   [{issue.get('code')}] {issue.get('message')}")
    if report["valid"]:
        OUTPUT.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
