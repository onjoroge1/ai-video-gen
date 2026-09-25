"""Generate the start/end stills for spec/four_pests_sparrows_short_beat_sheet.md.

Ten images: a start frame per clip (text-to-image, portrait), then an end frame per clip drawn in
image-edit mode with that clip's start frame as the reference so framing, palette and figure
placement carry across. Clip 5's end frame references clip 1's START frame instead, because the
Short loops: the closing sky must be the opening sky rendered again, not a copy.

Outputs land in renders/four_pests/stills/ (gitignored) with a manifest of prompts, sizes and the
actual USD each call billed. Re-running skips images that already exist, so a partial run is
never paid for twice.

    python3 scripts/four_pests_stills.py            # generate what is missing
    python3 scripts/four_pests_stills.py --dry-run  # print prompts and the estimate only
"""
from __future__ import annotations
import concurrent.futures
import json
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(usecwd=True))          # the worktree has no .env; the parent repo does

import explainer_pipeline as ep                # noqa: E402

OUT = os.path.join(ROOT, "renders", "four_pests", "stills")
SIZE = "1024x1536"                             # gpt-image-2 portrait; fitted to 1080x1920 at clip time

STYLE = ("Painted documentary illustration, vertical 9:16 composition, rural northern China 1958, "
         "muted earth palette with one warm accent, film grain, natural light, no text, no lettering, "
         "no logos, no modern objects, faces small or turned away. ")

END_RULE = (" Keep the exact same camera position, framing, lens, lighting, palette and figure "
            "placement as the reference image; change only what is described.")

BEATS = [
    {"id": "b1", "caption": "1958 · WAR ON THE SPARROW",
     "start": "Low-angle view up past clay rooftops at dusk. The whole sky is dense with small brown "
              "sparrows in flight, thousands of them, filling the upper two thirds of the frame. On "
              "the rooftops, villagers in 1950s cotton jackets stand with pots, gongs and bamboo poles "
              "raised overhead, faces turned up to the sky.",
     "end": "The same rooftops and the same villagers with pots still raised overhead. The sky is "
            "now almost empty: only three sparrows remain, one of them mid-fall with wings folded."},
    {"id": "b2", "caption": "NO PLACE TO LAND",
     "start": "A walled courtyard of packed earth at midday. A boy of about ten, seen from the side, "
              "beats a dented tin pot with a stick, mouth open in a shout. One sparrow circles low "
              "above him, wings ragged.",
     "end": "The same courtyard and the same boy with his arm still raised. The sparrow now lies on "
            "the packed earth at his feet. Against the wall behind him is a heap of small brown "
            "birds."},
    {"id": "b3", "caption": "WHAT THE SPARROW ATE",
     "start": "Macro close-up of a single ripe wheat stalk, sharp, against a soft green field bokeh. "
              "A sparrow grips the stalk and holds a green locust nymph in its beak.",
     "end": "The same wheat stalk, same light and bokeh, with no sparrow. The stalk is crowded with "
            "a dozen locusts climbing it, and the blurred field behind is speckled with more."},
    {"id": "b4", "caption": "THE FIELDS",
     "start": "Wide view of a green millet field at morning under a clear pale sky. At the field "
              "edge in the lower third, a farmer in a conical straw hat stands with his back to the "
              "camera, a hoe over his shoulder.",
     "end": "The same field and the same farmer, now holding his straw hat against his chest. The "
            "crop is stripped to brown stubble and the sky is a dark moving cloud of locusts."},
    {"id": "b5", "caption": "1960 · REPLACED BY THE BED BUG",
     "start": "A weathered wooden notice board in a village square at dusk, sky visible above it. On "
              "the board, four painted pest icons in a vertical column: a rat, a fly, a mosquito, a "
              "sparrow. A hand holding a paintbrush enters from the right edge of the frame.",
     "end": "The same notice board in the same square, same camera, same dusk light. The sparrow "
            "icon now has a wet red cross painted through it and a small bed bug icon is painted "
            "beneath it, and the hand with the brush has pulled back to the frame edge. The band of "
            "dusk sky visible above the board is now filled with hundreds of small brown sparrows "
            "in flight."},
    # The loop is closed by a cross-dissolve from this end frame to clip 1's start frame. A first
    # attempt referenced b1_start here so the closing sky would be the opening sky; the edit model
    # kept b1's rooftops and dropped the board, leaving Kling nothing to morph between. Kept as
    # b5_end_v1_rejected.png for provenance.
]


def _path(beat_id, which):
    return os.path.join(OUT, f"{beat_id}_{which}.png")


def _gen(prompt, out, refs, costs, label):
    if os.path.exists(out) and os.path.getsize(out) > 0:
        print(f"  skip  {label} (exists)", flush=True)
        return None
    t = time.time()
    ep.generate_image(prompt, out, reference_paths=refs, cost_sink=costs, size=SIZE)
    print(f"  done  {label}  ${costs[-1]:.3f}  {time.time() - t:.0f}s", flush=True)
    return costs[-1]


def main(dry_run=False):
    os.makedirs(OUT, exist_ok=True)
    manifest = {"size": SIZE, "style": STYLE, "beats": [], "usd_total": 0.0}
    est = len(BEATS) * (ep._COST_IMG_BASE + ep._COST_IMG_HOST)
    print(f"{len(BEATS) * 2} stills at {SIZE}; estimate ${est:.2f}; output {OUT}")
    if dry_run:
        for b in BEATS:
            print(f"\n[{b['id']}] START: {STYLE}{b['start']}\n[{b['id']}] END:   {STYLE}{b['end']}{END_RULE}"
                  f"  (ref: {b.get('end_reference', b['id'])}_start)")
        return

    # Start frames first, in parallel: the end frames depend on them.
    costs = {b["id"]: [] for b in BEATS}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda b: _gen(STYLE + b["start"], _path(b["id"], "start"), None,
                                     costs[b["id"]], f"{b['id']} start"), BEATS))
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda b: _gen(STYLE + b["end"] + END_RULE, _path(b["id"], "end"),
                                     [_path(b.get("end_reference", b["id"]), "start")],
                                     costs[b["id"]], f"{b['id']} end"), BEATS))

    for b in BEATS:
        manifest["beats"].append({
            "id": b["id"], "caption": b["caption"],
            "start": {"path": _path(b["id"], "start"), "prompt": STYLE + b["start"]},
            "end": {"path": _path(b["id"], "end"), "prompt": STYLE + b["end"] + END_RULE,
                    "reference": _path(b.get("end_reference", b["id"]), "start")},
            "usd": round(sum(costs[b["id"]]), 4)})
        manifest["usd_total"] = round(manifest["usd_total"] + sum(costs[b["id"]]), 4)
    with open(os.path.join(OUT, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nthis run billed ${manifest['usd_total']:.2f}; manifest at {OUT}/manifest.json")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
