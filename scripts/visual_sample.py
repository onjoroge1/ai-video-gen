"""Render a side-by-side sample of a proposed visual system against delivered frames.

The illustrated films measured flat: one amber/ivory palette across every role (hue SD 8-26),
frame-to-frame RGB change of 17-21 out of 255, and close-ups at 3-4 scenes out of 25. This
renders the SAME story beats under a proposed palette arc and shot grammar so the difference
can be looked at before any gate is wired into the pipeline.

    python3 scripts/visual_sample.py --spec sample_spec.json --out <dir>

Spec: {"style_base": "...", "scenes": [{"scene", "role", "framing", "palette", "subject"}]}
Writes <out>/after/sceneNN.jpg and prints the measured palette stats for each.
"""
from __future__ import annotations

import argparse
import colorsys
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def measure(path: str) -> dict:
    from PIL import Image
    im = Image.open(path).convert("RGB").resize((48, 27))
    px = list(im.getdata())
    n = len(px)
    r = sum(p[0] for p in px) / n
    g = sum(p[1] for p in px) / n
    b = sum(p[2] for p in px) / n
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return {"hue": round(h * 360, 1), "sat": round(s, 3), "lum": round(l, 3), "rgb": (r, g, b)}


def spread(paths: list[str]) -> dict:
    """Palette spread and frame-to-frame change across a set of frames, in order."""
    stats = [measure(p) for p in paths]
    hues = [s["hue"] for s in stats]
    deltas = [sum(abs(a - b) for a, b in zip(stats[i]["rgb"], stats[i + 1]["rgb"])) / 3
              for i in range(len(stats) - 1)]
    return {
        "hue_sd": round(statistics.pstdev(hues), 1) if len(hues) > 1 else 0.0,
        "sat_mean": round(statistics.mean(s["sat"] for s in stats), 3),
        "lum_mean": round(statistics.mean(s["lum"] for s in stats), 3),
        "frame_delta_mean": round(statistics.mean(deltas), 1) if deltas else 0.0,
        "per_frame": stats,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--before", default="", help="directory of delivered frames to measure too")
    ap.add_argument("--measure-only", action="store_true")
    args = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    import explainer_pipeline as ep

    spec = json.load(open(args.spec, encoding="utf-8"))
    out_dir = os.path.join(args.out, "after")
    os.makedirs(out_dir, exist_ok=True)
    costs: list[float] = []
    paths = []
    for s in spec["scenes"]:
        path = os.path.join(out_dir, f"scene{int(s['scene']):02d}.jpg")
        paths.append(path)
        if os.path.isfile(path) or args.measure_only:
            continue
        prompt = (f"{s['subject']} "
                  f"{spec['style_base']} "
                  f"Palette for this beat: {s['palette']} "
                  f"Framing: {s['framing']}")
        ep.generate_image(prompt, path, cost_sink=costs)
        print(f"  scene {s['scene']:2d} [{s['role']:16}] {s['framing'][:40]:40} drawn")
    print(f"images ${sum(costs):.2f}")
    after = spread(paths)
    print("\nAFTER  hue SD %(hue_sd)s | sat %(sat_mean)s | lum %(lum_mean)s | frame delta %(frame_delta_mean)s" % after)
    for s, st in zip(spec["scenes"], after["per_frame"]):
        print(f"   scene {s['scene']:2d} {s['role']:16} hue {st['hue']:6.1f} sat {st['sat']:.2f} lum {st['lum']:.2f}")
    if args.before and os.path.isdir(args.before):
        bpaths = [os.path.join(args.before, f) for f in sorted(os.listdir(args.before)) if f.endswith(".jpg")]
        before = spread(bpaths)
        print("\nBEFORE hue SD %(hue_sd)s | sat %(sat_mean)s | lum %(lum_mean)s | frame delta %(frame_delta_mean)s" % before)
        print(f"\nhue spread {before['hue_sd']} -> {after['hue_sd']}; "
              f"frame delta {before['frame_delta_mean']} -> {after['frame_delta_mean']}")
    json.dump({"after": after}, open(os.path.join(args.out, "measured.json"), "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
