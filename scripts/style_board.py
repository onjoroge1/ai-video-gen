"""Render one story moment in several illustrated treatments, as a board to choose a look from.

The delivered films all use one treatment: naturalistic hand-drawn ink and cut-paper on ivory,
wide shots, everything mid-tone. Measured across three films the palette never moves (hue SD
8-26, saturation 0.16-0.21) and close-ups are 3-4 scenes in 25. This renders the SAME moment
under genuinely different illustrated directions so the look can be chosen by eye, not argued.

    python3 scripts/style_board.py --spec board.json --out <dir> [--contact]

Spec: {"subject": "...", "treatments": [{"key", "name", "prompt"}]}
"""
from __future__ import annotations

import argparse
import colorsys
import json
import os
import statistics
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

NO_TEXT = (" No text, letters, numbers, labels, arrows, UI, watermark or accidental writing. "
           "One single continuous scene filling the frame: never a grid, panels, borders, "
           "gutters, insets or caption strips. Composition must read instantly at phone size.")


def circular_hue_sd(hues: list) -> float:
    """Circular standard deviation of hue, in degrees.

    Hue is an angle, so a linear stdev is wrong: 350 deg and 10 deg are 20 deg apart, not 340.
    For the delivered films every frame sits near 40 deg so linear happened to be close, but a
    palette arc that crosses 0 deg (scarlet at 4 deg, rust at 23 deg) needs the circular form.
    sd = sqrt(-2 ln R), R = the mean resultant length.
    """
    import math
    if len(hues) < 2:
        return 0.0
    xs = [math.cos(math.radians(h)) for h in hues]
    ys = [math.sin(math.radians(h)) for h in hues]
    r = math.hypot(sum(xs) / len(hues), sum(ys) / len(hues))
    if r <= 1e-9:
        return 180.0
    return math.degrees(math.sqrt(max(0.0, -2.0 * math.log(min(1.0, r)))))


def hue_sectors(hues: list, n: int = 12) -> int:
    """How many of n equal hue sectors are occupied — a spread measure robust to outliers."""
    return len({int(h % 360 // (360 / n)) for h in hues})


def measure(path: str) -> dict:
    from PIL import Image
    im = Image.open(path).convert("RGB")
    small = im.resize((64, 36))
    px = list(small.getdata())
    n = len(px)
    r = sum(p[0] for p in px) / n
    g = sum(p[1] for p in px) / n
    b = sum(p[2] for p in px) / n
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    lums = [0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2] for p in px]
    return {"hue": round(h * 360, 1), "sat": round(s, 3), "lum": round(l, 3),
            "contrast": round(statistics.pstdev(lums), 1), "rgb": (r, g, b)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--contact", action="store_true")
    args = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    import explainer_pipeline as ep

    spec = json.load(open(args.spec, encoding="utf-8"))
    os.makedirs(args.out, exist_ok=True)
    costs: list[float] = []
    rows = []
    for t in spec["treatments"]:
        path = os.path.join(args.out, f"{t['key']}.jpg")
        if not os.path.isfile(path):
            subject = t.get("subject") or spec.get("subject", "")
            prompt = f"{t['prompt']} Subject: {subject}{NO_TEXT}"
            try:
                ep.generate_image(prompt, path, cost_sink=costs)
            except Exception as exc:
                print(f"  {t['key']:18} FAILED {type(exc).__name__}: {str(exc)[:90]}")
                continue
        m = measure(path)
        rows.append((t, m))
        print(f"  {t['key']:18} hue {m['hue']:6.1f} sat {m['sat']:.2f} lum {m['lum']:.2f} contrast {m['contrast']:5.1f}  {t['name']}")
    print(f"\nimages ${sum(costs):.2f}")
    if rows:
        hues = [m["hue"] for _, m in rows]
        print(f"spread across treatments: circular hue SD {circular_hue_sd(hues):.1f} | "
              f"sat {min(m['sat'] for _, m in rows):.2f}-{max(m['sat'] for _, m in rows):.2f} | "
              f"contrast {min(m['contrast'] for _, m in rows):.0f}-{max(m['contrast'] for _, m in rows):.0f} | "
              f"{hue_sectors(hues)}/12 hue sectors")
        seq = [m for _, m in rows]
        deltas = [sum(abs(a - b) for a, b in zip(seq[i]["rgb"], seq[i + 1]["rgb"])) / 3
                  for i in range(len(seq) - 1)]
        if deltas:
            print(f"cut-to-cut |dRGB| in sequence: mean {statistics.mean(deltas):.1f} "
                  f"min {min(deltas):.1f}  (delivered films measured 16.7-21.3 mean)")
    if args.contact and rows:
        files = [os.path.join(args.out, f"{t['key']}.jpg") for t, _ in rows]
        lst = os.path.join(args.out, "_list.txt")
        with open(lst, "w") as fh:
            for f in files:
                fh.write(f"file '{os.path.abspath(f)}'\n")
        cols = 2
        sheet = os.path.join(args.out, "board.jpg")
        subprocess.run([ep._ffmpeg_bin(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                        "-i", lst, "-vf", f"scale=760:-1,tile={cols}x{(len(files) + cols - 1) // cols}",
                        "-frames:v", "1", "-q:v", "3", sheet], check=True)
        print("board:", sheet)
    json.dump([{**t, **m} for t, m in rows], open(os.path.join(args.out, "measured.json"), "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
