"""Bolt's pose library for the quiz Short — five full-body cutouts, generated once and committed.

Run: SCRIPT_PROVIDER=openai python3 bolt_seq/gen_quiz_poses.py

Why not ``compiler.gen_pose``: that gate is built for the falling sequence and demands
``urgency >= 6`` with ``neutral_pose_probability <= 3``, explicitly failing anything that reads as
"calm waving/standing/presenting-to-camera". A quiz host presents to camera — every pose here
would be rejected by design. ``gen_with_preflight`` takes our own checklist instead, and its
``cutout=True`` path already does generate → audit → chroma-key, so the magenta convention and the
retry loop come for free.

``reuse=True``: poses are committed assets. Re-running must not spend on what is already good.
"""
import json
import os
import sys

PROJ = "/Users/obadiah/Documents/video"
os.chdir(PROJ)
sys.path.insert(0, PROJ)
from dotenv import load_dotenv                                    # noqa: E402
load_dotenv(dotenv_path=os.path.join(PROJ, ".env"), override=True)
from bolt_seq import compiler as C                                # noqa: E402

OUT = os.path.join(PROJ, "assets", "mascot", "quiz")
os.makedirs(OUT, exist_ok=True)


def log(m):
    print(m, flush=True)


BASE = ("A small friendly toy-robot mascot, FULL BODY, centered, on a SOLID FLAT MAGENTA (#FF00FF) "
        f"background filling the whole frame. It has {C.POSE_IDENTITY}. Premium 3D cartoon render, "
        "bright even lighting, no scenery, no ground, no shadow on the background. ")

# Shared across every pose: identity is the thing that must not drift between them, because all five
# composite into the same video and a body that changes shape round to round reads as a glitch.
IDENTITY_CHECKS = [
    "Exactly ONE small rounded white-and-mint toy robot is shown",
    "The robot's face is a glossy dark visor with exactly two glowing cyan eyes and no mouth",
    "The robot has a single rounded hover-base and NO legs, NO feet and NO boots",
    "The background is one solid flat magenta colour behind the entire robot",
    "The robot's whole body is inside the frame and is not cropped at any edge",
    "There is no text, no numbers, no logo and no watermark anywhere in the image",
]

POSES = {
    # Opens the video: an arm thrown out toward the scene the viewer is about to search.
    "point": (BASE + "POSE: leaning to one side with ONE stubby arm extended straight out, "
              "pointing off to the side at something out of frame, the other arm tucked in. "
              "Eager and inviting, as if saying 'look at that'.",
              ["One arm is clearly extended outward pointing to the side"]),
    # Held during the guess window, so it must read as searching rather than as an answer.
    "scan": (BASE + "POSE: peering forward and searching, one stubby arm raised with the hand held "
             "flat above the visor like a sun-shade while looking out into the distance, body "
             "leaning slightly forward. Curious and hunting for something.",
             ["One arm is raised up near the top of the head, shading or shielding the visor"]),
    # Easy reveal.
    "celebrate": (BASE + "POSE: mid-air celebration jump, BOTH stubby arms thrown straight up above "
                  "the head in a V, body tilted back slightly, hover-base lifted clear as if bouncing "
                  "upward. Delighted and triumphant.",
                  ["Both arms are raised up above the head"]),
    # Hard and expert reveals.
    "amazed": (BASE + "POSE: rocked backwards in astonishment, body leaning away and tilted back, both "
               "stubby arms flung wide open to the sides, antenna whipping backward. Stunned and "
               "impressed, as if seeing something incredible.",
               ["Both arms are flung out wide to the sides, away from the body"]),
    # Sits under the closing card, where the loop sends the viewer back to round one.
    "wave": (BASE + "POSE: facing the viewer square-on and waving hello with ONE stubby arm raised "
             "beside the head, palm open, the other arm relaxed at the side. Warm and friendly, "
             "inviting the viewer back.",
             ["One arm is raised beside the head in a clear waving gesture"]),
}


def main():
    costs, report = [], {}
    for name, (prompt, extra) in POSES.items():
        log(f"  {name}...")
        report[name] = C.gen_with_preflight(
            prompt, os.path.join(OUT, f"{name}.png"), IDENTITY_CHECKS + extra,
            size="1024x1536", cutout=True, tries=3, reuse=True, cost_sink=costs, log=log)
    path = os.path.join(OUT, "preflight_report.json")
    json.dump(report, open(path, "w"), indent=2)
    log("\n=== QUIZ POSE LIBRARY ===")
    for name, r in report.items():
        last = (r.get("attempts") or [{}])[-1]
        log(f"  {name:10} {'PASS' if r.get('passed') else 'BEST-EFFORT'}  "
            f"{last.get('violations') or last.get('reused') and 'reused' or ''}")
    log(f"cost ${sum(costs):.2f}  ->  {OUT}")


if __name__ == "__main__":
    main()
