"""Bolt's ANIMATED reaction library for the quiz Short — keyed cutout clips, generated once
and committed.

    python3 bolt_seq/gen_quiz_reactions.py                # everything missing, nothing rebuilt
    python3 bolt_seq/gen_quiz_reactions.py hyped dead     # only these two
    python3 bolt_seq/gen_quiz_reactions.py --dry-run      # price the run, spend nothing
    python3 bolt_seq/gen_quiz_reactions.py hyped --force  # rebuild one that already exists

These are LIBRARY assets, not per-render generation. Kling bills a five-second minimum, so a clip
costs about $0.28 whatever we actually use of it — but it is bought once and composited into every
quiz after that, which puts the marginal cost of a reaction at zero. Generating one per render
would be the same money over and over for a character who does the same five things.

``reuse`` is therefore the default and the important behaviour: a finished ``.mov`` is never
regenerated without ``--force``. Re-running this script after adding one pose must cost the price
of that pose and nothing else.

Pipeline per reaction, all of it already in this repo except the video keying:

    still   gen_with_preflight(cutout=True)   magenta render, VLM identity audit, retry, chroma-key
    motion  ep._animate_one("fal", ...)       Kling i2v, seeded with the MAGENTA still
    key     colorkey + despill                same 0xFF00FF convention the stills use
    audit   preflight() on sampled frames     identity has to survive the animation, not just the seed

The seed handed to Kling is the magenta render, NOT the keyed cutout. The background has to be
there for the model to animate against, and it has to be the same flat magenta so the clip keys on
exactly the parameters the stills were built with.

CONTAINER: an H.264 .mp4 carrying the colour over its own matte, one stacked frame. Measured on a
real 1.4s clip:

    qtrle .mov (lossless RGBA)   20.1 MB    alpha ok
    ProRes 4444 .mov             15.0 MB    alpha ok
    PNG sequence                 12.0 MB    alpha ok
    VP8 / VP9 .webm             ~0.3 MB     ALPHA SILENTLY LOST
    stacked H.264 .mp4            0.5 MB    alpha ok

Both WebM encoders advertise ``yuva420p``, write ``yuv420p``, and exit 0 — the alpha is gone with
no error anywhere, which is the same silent-failure shape as an emoji drawn in a font that has no
glyph for it. The stacked mp4 is 39x smaller than lossless RGBA and reconstructs the matte to
within 0.08/255 mean error, so it is the only option that is both honest and committable.

Unpack it with :func:`unpack_filter`, which is the single source of truth for the geometry — a
consumer that hardcodes "crop the top half" will silently halve someone's animation the first time
a clip is generated at a different size.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image

# Derived, not hardcoded. The sibling pose script pins an absolute path, which silently writes a
# worktree's assets into the main checkout — the generated files land somewhere the branch under
# test cannot see and the run looks like it worked.
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
import explainer_pipeline as ep                                   # noqa: E402
from bolt_seq import compiler as C                                # noqa: E402

OUT = os.path.join(PROJ, "assets", "mascot", "reactions")
RAW = os.path.join(OUT, "_raw")          # seeds and untrimmed clips; not the committed artefact
W, H, FPS = 1080, 1920, 30

# Kling's floor. We pay for five seconds and keep the beat, so the prompts put the action at the
# very start of the clip rather than letting the model spend two seconds settling into it.
I2V_SECONDS = 5
FAL_RATE_SEC = float(os.environ.get("QUIZ_FAL_RATE_SEC", "0.056"))
HERO_RATE_SEC = float(os.environ.get("I2V_HERO_RATE_SEC", "0.112"))
STILL_COST_EST = 0.04                    # gpt-image medium, one attempt; the audit loop may spend more

# Composited at roughly a third of frame width, so there is no reason to carry 1080-wide masters.
# Must stay EVEN: the stacked asset is yuv420p, which cannot represent an odd dimension, and the
# first real clip cropped to 540x903 and would have failed to encode on the height alone.
TARGET_WIDTH = 540
BBOX_PAD = 12
# The matte rides in the same stream as the colour, so one quality setting covers both. 17 keeps the
# matte within a fraction of a level of the lossless original while the whole clip stays under a MB.
H264_CRF = 17
# The repo's existing despill threshold. Magenta is R and B above G; Bolt is white (R=G=B), mint
# (G highest) and cyan (G,B high, R low), so no part of the character trips this — only the fringe
# the key leaves behind does.
DESPILL_MARGIN = 8
# A belt to shortest=1's braces. A reaction is under two seconds, so anything past this is a filter
# graph that has stopped terminating rather than a long clip, and the cap turns a disk-filling run
# into a short one.
AUDIT_FRAME_CAP = 300

# The characteristic i2v failure, and the one the VLM audit does not catch: the model honours the
# flat magenta for a second or so and then progressively paints a lit background behind the
# character. The key removes the magenta it can still recognise and leaves the rest, so the cutout
# grows an opaque halo that composites as a dark rectangle over the quiz scene.
#
# Corners are the tell. The crop is the character's own bounding box plus padding, so a legitimate
# limb can reach an EDGE — a raised fist regularly does — but nothing about the character reaches
# all four CORNERS. Measured on the first five reactions, corner opacity ran 0.000 on every clean
# frame and 0.5-1.0 on every leaked one, with nothing in between.
#
# These are pixel facts and the gate is mechanical on purpose. The vision audit passed all three
# leaked clips: asked whether the robot is on-model it correctly said yes, because it was.
LEAK_CORNER_MAX = 0.10
LEAK_GROWTH_MAX = 1.35
# The mirror failure, and it keys perfectly so nothing else catches it: instead of a background
# arriving, the CHARACTER leaves — tipping out of frame or breaking up as the generation runs past
# what the pose can sustain. `shock` played surprise for half a second and then exited, leaving
# fragments. Both directions are the same measurement, so both are checked against frame one.
LEAK_SHRINK_MIN = 0.70
# Below this a reaction has no time to read as anything, so a clip whose clean prefix is shorter is
# a failure to report rather than a shorter beat to ship.
MIN_BEAT_SEC = 0.5


def log(m):
    print(m, flush=True)


def load_credentials():
    """Read .env for the CLI. Deliberately NOT at import time.

    At module scope this ran on any import, including a test collecting this file, and quietly put
    the real ``DATABASE_URL`` and API keys into that process's environment — so unrelated tests
    started talking to production storage and failed a long way from the cause. A worktree has no
    .env of its own, so the checkout the branch came from is the fallback; variables already set
    always win.
    """
    for candidate in (os.path.join(PROJ, ".env"), "/Users/obadiah/Documents/video/.env"):
        if os.path.exists(candidate):
            from dotenv import load_dotenv
            load_dotenv(dotenv_path=candidate, override=False)
            return candidate
    return ""


BASE = ("A small friendly toy-robot mascot, FULL BODY, centered, on a SOLID FLAT MAGENTA (#FF00FF) "
        f"background filling the whole frame. It has {C.POSE_IDENTITY}. Premium 3D cartoon render, "
        "bright even lighting, no scenery, no ground, no shadow on the background. ")

# Same bible as the still library. Identity is what must not drift — these clips cut against each
# other and against the committed stills, and a body that changes shape between beats reads as a
# glitch rather than as a character.
IDENTITY_CHECKS = [
    "Exactly ONE small rounded white-and-mint toy robot is shown",
    "The robot's face is a glossy dark visor with exactly two glowing cyan eyes and no mouth",
    "The robot has a single rounded hover-base and NO legs, NO feet and NO boots",
    "The robot's whole body is inside the frame and is not cropped at any edge",
    "There is no text, no numbers, no logo and no watermark anywhere in the image",
]

# Motion direction shared by every clip. Kling's default instinct is a slow cinematic push on a
# photoreal plate; left alone it drifts the camera, relights the character and dissolves the flat
# background the key depends on. All three have to be forbidden explicitly.
MOTION_RULES = (
    "LOCKED-OFF CAMERA: the camera does not move, pan, zoom or shake at all. The background stays "
    "one solid flat magenta and is never relit, shaded, blurred or replaced. Only the robot moves. "
    "Keep the robot's exact design, colours, proportions and single hover-base identical in every "
    "frame — no morphing, no extra limbs, no legs, no mouth, no new objects, no text. The action "
    "starts IMMEDIATELY on the first frame. Smooth 3D cartoon animation. ")

# beat_sec: how much of the five seconds is kept. A reaction is a punctuation mark inside a 0.8-1.2s
# reveal, so these are short on purpose — the trim is where "reacts" stops and "performs" starts.
REACTIONS = {
    # Round one's reveal, under "IF YOU MISSED THAT 💀". Unimpressed, not celebratory: the joke is
    # that the warm-up was free and Bolt is judging anyone who missed it.
    "smug": (
        BASE + "POSE: leaning back with arms folded across the chest, visor tilted slightly down "
               "and to one side, looking distinctly unimpressed and smug.",
        "The robot slowly folds its arms, tilts its head to one side and gives a single slow "
        "dismissive shake of the head, thoroughly unimpressed.",
        ["The robot's arms are folded across its chest"], 1.4),

    # Round two's reveal — the beat that replaced the spoken "let him cook".
    "hyped": (
        BASE + "POSE: fired up and cheering, both stubby arms raised and fists clenched, body "
               "leaning forward, antenna straight up, glowing cyan eyes wide with excitement.",
        "The robot pumps both fists upward twice in an energetic cheer, bouncing on its hover-base, "
        "antenna bobbing, thoroughly hyped up.",
        ["Both of the robot's arms are raised upward"], 1.4),

    # Surprise, for a reveal that lands harder than the tier promised.
    "shock": (
        BASE + "POSE: recoiling in shock, body thrown backward, both stubby arms flung up and out, "
               "antenna whipped back, glowing cyan eyes stretched wide.",
        "The robot jolts backwards in a sharp double-take, arms flying up in surprise, then holds "
        "the stunned pose.",
        ["Both arms are flung upward and outward away from the body"], 1.4),

    # The final boss. The funniest of the set and the payoff of the escalation, so it gets the
    # longest beat — a collapse needs time to land or it reads as a stumble.
    "dead": (
        BASE + "POSE: keeling over sideways, body tipped well past balance, both stubby arms limp "
               "and hanging down, antenna drooping, visor eyes reduced to two small flat cyan lines.",
        "The robot stiffens, then keels over sideways and flops limply, arms dangling and antenna "
        "drooping, completely defeated.",
        ["The robot's body is clearly tipped over off-balance to one side"], 1.8),

    # Sits under the closing card if we ever want it there — deliberately not wired in by default,
    # because the score ladder is the thing that has to be read on that frame.
    "clap": (
        BASE + "POSE: applauding, both stubby arms brought together in front of the chest mid-clap, "
               "body upright and pleased, antenna upright.",
        "The robot claps its hands together three times in steady applause, nodding approvingly.",
        ["Both arms are brought together in front of the body"], 1.6),
}


# ── keying ──────────────────────────────────────────────────────────────────────

def _frames_from(mp4, frame_dir, beat_sec):
    """Explode the kept beat into keyed RGBA frames.

    ``colorkey`` runs here rather than on the assembled clip because it is a per-frame filter and
    the alpha has to exist before anything downstream measures a bounding box or despills a fringe.
    Parameters are ``chroma_key()``'s, unchanged: the stills and the clips have to key identically
    or the character's edge changes between a still beat and a moving one.
    """
    os.makedirs(frame_dir, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp4, "-t", f"{beat_sec}",
                    "-vf", f"fps={FPS},colorkey=0xFF00FF:0.30:0.12,format=rgba",
                    os.path.join(frame_dir, "%04d.png")], check=True)
    return sorted(os.path.join(frame_dir, f) for f in os.listdir(frame_dir) if f.endswith(".png"))


def _despill(arr):
    """Pull the magenta fringe out of edge pixels the key left partly opaque.

    A white character against magenta is the hard case: the edge picks up the key colour and
    survives as a pink halo that only shows once the clip is composited over a real scene. Where R
    and B both sit above G by more than the margin the pixel is contaminated, so both are brought
    down to G — the repo's existing ``despill_magenta`` rule, applied per frame.
    """
    a = arr.astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    spill = (r > g + DESPILL_MARGIN) & (b > g + DESPILL_MARGIN)
    a[..., 0] = np.where(spill, np.minimum(r, g + DESPILL_MARGIN), r)
    a[..., 2] = np.where(spill, np.minimum(b, g + DESPILL_MARGIN), b)
    return np.clip(a, 0, 255).astype(np.uint8)


def _leak_stats(path):
    """(corner opacity, overall opacity) for one keyed frame."""
    alpha = np.array(Image.open(path).convert("RGBA"))[..., 3]
    k = max(8, min(alpha.shape) // 12)
    corners = np.concatenate([alpha[:k, :k].ravel(), alpha[:k, -k:].ravel(),
                              alpha[-k:, :k].ravel(), alpha[-k:, -k:].ravel()])
    return float((corners > 8).mean()), float((alpha > 8).mean())


def clean_prefix(frames):
    """How many leading frames still show the character alone, at roughly its original size.

    The leak grows over the clip rather than arriving at once, so the salvage is a trim: the first
    second of a five-second generation is usually honest even when the last four are not. Returning
    a count rather than a verdict is what lets the beat shorten automatically instead of throwing
    away a clip that was already paid for.
    """
    if not frames:
        return 0
    _, base_opaque = _leak_stats(frames[0])
    for index, path in enumerate(frames):
        corner, opaque = _leak_stats(path)
        if (corner > LEAK_CORNER_MAX
                or opaque > base_opaque * LEAK_GROWTH_MAX
                or opaque < base_opaque * LEAK_SHRINK_MIN):
            return index
    return len(frames)


def _union_bbox(frames):
    """The alpha bounding box across EVERY frame, not per frame.

    Cropping each frame to its own content would re-centre the character on every frame and turn a
    fist pump into a jitter. One box for the whole clip keeps the motion inside the frame where the
    animation put it.
    """
    box = None
    for path in frames:
        b = Image.open(path).getbbox()
        if not b:
            continue
        box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]),
                                     max(box[2], b[2]), max(box[3], b[3]))
    return box


def key_clip(raw_mp4, out_mov, beat_sec, work_dir):
    """Key, despill, crop and encode one raw i2v clip into a committed stacked-matte .mp4."""
    frame_dir = os.path.join(work_dir, "frames")
    shutil.rmtree(frame_dir, ignore_errors=True)
    frames = _frames_from(raw_mp4, frame_dir, beat_sec)
    if not frames:
        return {"ok": False, "error": "no frames decoded from the i2v clip"}

    for path in frames:
        im = Image.open(path).convert("RGBA")
        arr = np.array(im)
        arr[..., :3] = _despill(arr[..., :3])
        Image.fromarray(arr, "RGBA").save(path)

    # Trim to the honest part before anything measures a bounding box: a leaked frame's "content"
    # is the background, and letting it into the union would size the crop to the whole plate.
    clean = clean_prefix(frames)
    trimmed_from = None
    if clean < len(frames):
        if clean / FPS < MIN_BEAT_SEC:
            return {"ok": False, "error": (
                f"the clip stopped being usable after {clean / FPS:.2f}s, leaving less than the "
                f"{MIN_BEAT_SEC:.2f}s a reaction needs — the model either stopped honouring the "
                f"flat magenta or moved the character out of frame")}
        trimmed_from = round(len(frames) / FPS, 2)
        for path in frames[clean:]:
            os.remove(path)
        frames = frames[:clean]

    box = _union_bbox(frames)
    if not box:
        # Every pixel keyed away: the model replaced the flat magenta with a lit background, so
        # there is nothing to composite. Worth naming precisely — it is the characteristic i2v
        # failure here and it is invisible in a clip that still plays perfectly on its own.
        return {"ok": False, "error": "the whole frame keyed out — the model did not keep a flat "
                                      "magenta background"}
    w0, h0 = Image.open(frames[0]).size
    box = (max(0, box[0] - BBOX_PAD), max(0, box[1] - BBOX_PAD),
           min(w0, box[2] + BBOX_PAD), min(h0, box[3] + BBOX_PAD))
    crop_dir = os.path.join(work_dir, "crop")
    shutil.rmtree(crop_dir, ignore_errors=True)
    os.makedirs(crop_dir, exist_ok=True)
    cw = box[2] - box[0]
    scale = TARGET_WIDTH / cw
    # Rounded to even in both axes: yuv420p subsamples chroma 2x2 and cannot encode an odd side.
    size = (TARGET_WIDTH, max(2, round((box[3] - box[1]) * scale) // 2 * 2))
    for index, path in enumerate(frames):
        Image.open(path).crop(box).resize(size, Image.LANCZOS).save(
            os.path.join(crop_dir, f"{index:04d}.png"))

    pack_rgba_frames(crop_dir, out_mov, size)
    opaque = sum(int((np.array(Image.open(os.path.join(crop_dir, f)))[..., 3] > 8).mean() * 100)
                 for f in sorted(os.listdir(crop_dir))) / max(1, len(frames))
    return {"ok": os.path.exists(out_mov), "frames": len(frames), "size": size,
            "mean_opaque_pct": round(opaque, 1), "duration_sec": round(len(frames) / FPS, 2),
            "leak_trimmed_from_sec": trimmed_from}


def pack_rgba_frames(frame_dir, out_mp4, size):
    """Encode an RGBA frame directory as colour stacked over its own matte."""
    w, h = size
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
        "-i", os.path.join(frame_dir, "%04d.png"), "-filter_complex",
        f"[0:v]scale={w}:{h},format=rgba,split=2[c][m];"
        f"[c]format=yuv420p[cc];[m]alphaextract,format=yuv420p[mm];[cc][mm]vstack=inputs=2[o]",
        "-map", "[o]", "-c:v", "libx264", "-preset", "slow", "-crf", str(H264_CRF),
        "-pix_fmt", "yuv420p", out_mp4], check=True)
    return out_mp4


def unpack_filter(asset_path, in_label="0:v", out_label="rx"):
    """ffmpeg filter fragment turning a stacked reaction asset back into RGBA, plus its size.

    The geometry is read from the file rather than assumed. A consumer that hardcodes "crop the top
    half" works right up until a clip is generated at a different size, and then it silently shows
    half an animation over half a matte — so every consumer goes through here.
    """
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0", asset_path],
        capture_output=True, text=True, check=True)
    w, stacked_h = (int(x) for x in probe.stdout.strip().split(",")[:2])
    h = stacked_h // 2
    return (f"[{in_label}]crop={w}:{h}:0:0[{out_label}c];"
            f"[{in_label}]crop={w}:{h}:0:{h},format=gray[{out_label}m];"
            f"[{out_label}c][{out_label}m]alphamerge,format=rgba[{out_label}]"), (w, h)


# ── audit ───────────────────────────────────────────────────────────────────────

def extract_audit_frames(asset_path, probe_dir):
    """Flatten the reaction onto mid-grey and write one still per frame. Returns their filenames.

    ``shortest=1`` is load-bearing. ``color=`` is an INFINITE source and overlay's default
    eof_action is "repeat", so once the clip ends the graph keeps emitting its last frame against
    the endless plate — forever. Without it this wrote 389,195 stills and 5.9 GB before anything
    noticed, because ffmpeg was behaving exactly as documented and the clip itself was fine. The
    frame cap is the second line of defence: a reaction is under two seconds, so anything past it
    is a graph that has stopped terminating rather than a long clip.
    """
    unpack, (w, h) = unpack_filter(asset_path)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", asset_path, "-filter_complex",
                    f"{unpack};color=c=gray:s={w}x{h}[bg];"
                    f"[bg][rx]overlay=shortest=1,format=rgb24[o]",
                    "-map", "[o]", "-frames:v", str(AUDIT_FRAME_CAP),
                    os.path.join(probe_dir, "%04d.jpg")], check=True)
    return sorted(f for f in os.listdir(probe_dir) if f.endswith(".jpg"))


def audit_clip(out_mov, work_dir, extra_checks, cost_sink):
    """Re-run the still library's identity gate on frames sampled from the finished clip.

    The still passing its audit says nothing about the clip: Kling is free to melt the character
    across the frames it invents, and the seed is the one frame it was given. Sampling start, middle
    and end and keeping the WORST verdict is what makes the audit about the animation.

    Frames are flattened onto mid-grey first. A transparent PNG is not what the compositor will
    show a viewer, and judging identity through one invites the model to comment on the checkerboard.
    """
    probe = os.path.join(work_dir, "audit")
    shutil.rmtree(probe, ignore_errors=True)
    os.makedirs(probe, exist_ok=True)
    # Unpacked through the shipping helper and flattened onto mid-grey in one pass. Auditing the
    # colour half on its own would grade pixels the matte throws away, and grading a transparent
    # PNG invites the model to describe the checkerboard instead of the character.
    frames = extract_audit_frames(out_mov, probe)
    if not frames:
        return {"pass": False, "violations": ["no frames to audit"], "sampled": 0}
    picks = [frames[0], frames[len(frames) // 2], frames[-1]]
    results = [C.preflight(os.path.join(probe, name),
                           IDENTITY_CHECKS + list(extra_checks), cost_sink=cost_sink)
               for name in picks]
    violations = sorted({v for r in results for v in r.get("violations", [])})
    return {"pass": all(r.get("pass") for r in results), "violations": violations,
            "sampled": len(picks)}


# ── build ───────────────────────────────────────────────────────────────────────

def asset_path(name):
    return os.path.join(OUT, f"{name}.mp4")


def playable(path):
    """Whether ffmpeg can actually decode this file.

    Existence is not readability. A download truncated by a full disk or a killed process leaves a
    plausible-looking multi-megabyte mp4 with no moov atom — one of the five raw clips here ended up
    exactly that way — and the only thing that tells you is trying to open it.
    """
    if not path or not os.path.exists(path):
        return False
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        return probe.returncode == 0 and float(probe.stdout.strip().split(",")[0]) > 0
    except (ValueError, IndexError):
        return False


def report_path():
    return os.path.join(OUT, "reaction_report.json")


def load_report():
    try:
        with open(report_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def is_built(name, report=None):
    """Whether a reaction is finished — the file exists AND an audit passed against it.

    Testing for the file alone is not enough. Keying writes the asset and the audit runs after it,
    so a run interrupted in between leaves a perfectly playable clip that nothing ever graded — and
    because the reuse check saw a file, every later run skipped it. An asset that has never been
    audited is exactly the one worth auditing, so absence of a recorded verdict counts as unbuilt.

    "reused" entries carry no audit of their own and are not evidence; the verdict has to come from
    the run that actually produced the file.
    """
    if not os.path.exists(asset_path(name)):
        return False
    entry = (report if report is not None else load_report()).get(name) or {}
    return bool(entry.get("audit")) and bool(entry.get("passed"))


def build_reaction(name, spec, costs, force=False, regenerate=False, hero=False, reclip=False):
    """Build one reaction. ``force`` re-keys from the raw clip already bought; ``regenerate`` buys
    a new one.

    The split matters because the two halves of this pipeline have very different prices. The i2v
    call is the whole cost; the keying is free ffmpeg. Beat length, despill margin and crop padding
    are also exactly the parameters worth iterating on, so re-tuning them must not re-buy anything.
    """
    still_prompt, motion, extra, beat = spec
    out_path = asset_path(name)
    work = os.path.join(RAW, name)
    raw_mp4 = os.path.join(work, f"{name}.i2v.mp4")

    if is_built(name) and not (force or regenerate or reclip):
        log(f"  {name:7} reuse (built and audited)")
        prior = load_report().get(name) or {}
        return {"reused": True, "path": out_path, "passed": True,
                "audit": prior.get("audit"), "clip": prior.get("clip")}

    # A finished asset with no usable source clip can still be graded, and grading it is free. This
    # is the normal state of a fresh clone — _raw/ is deliberately not committed — so without this
    # branch the audit gate would send every checked-out reaction down the re-key path and die on a
    # missing file. Buying a new clip to grade one that already exists would be worse still.
    if os.path.exists(out_path) and not (regenerate or reclip) and not playable(raw_mp4):
        os.makedirs(work, exist_ok=True)
        log(f"  {name:7} no usable source clip — grading the committed asset in place")
        audit = audit_clip(out_path, work, extra, cost_sink=costs)
        _sweep_scratch(work)
        return {"path": out_path, "passed": bool(audit.get("pass")), "audit": audit,
                "graded_in_place": True}

    if os.path.exists(out_path) and not (force or regenerate or reclip):
        log(f"  {name:7} asset exists but carries no passing audit — re-keying and grading it")

    os.makedirs(work, exist_ok=True)
    still = os.path.join(work, f"{name}.png")

    # cutout=True writes the keyed PNG to `still` and leaves the magenta render beside it as
    # `<still>.raw.png`. Kling is seeded with the magenta one: it needs a background to animate
    # against, and it has to be the background the key expects.
    log(f"  {name:7} still...")
    pf = C.gen_with_preflight(still_prompt, still, IDENTITY_CHECKS + list(extra),
                              size="1024x1536", cutout=True, tries=3, reuse=not regenerate,
                              cost_sink=costs, log=lambda m: log("    " + m.strip()))
    seed = still + ".raw.png"
    if not os.path.exists(seed):
        return {"path": out_path, "passed": False, "error": "magenta seed was not produced",
                "still": pf}

    if playable(raw_mp4) and not (regenerate or reclip):
        log(f"  {name:7} reusing the clip already bought (no spend)")
    else:
        log(f"  {name:7} animating {I2V_SECONDS}s...")
        # The standard tier stops honouring the flat magenta partway through the generation on the
        # poses that involve leaning or receding — it starts rendering the depth the motion implies,
        # and depth means a background. The pro tier follows the constraint further for 2x the rate,
        # which is the difference between a clip that keys and one that does not.
        model = ep._FAL_MODEL_HERO if hero else None
        rate = HERO_RATE_SEC if hero else FAL_RATE_SEC
        ok, quota, err = ep._animate_one("fal", seed, MOTION_RULES + motion, raw_mp4,
                                         W, H, I2V_SECONDS, fal_model=model)
        costs.append(I2V_SECONDS * rate)
        if not ok or not os.path.exists(raw_mp4):
            return {"path": out_path, "passed": False,
                    "error": f"i2v failed{' (quota)' if quota else ''}: {err}", "still": pf}

    log(f"  {name:7} keying {beat}s beat...")
    keyed = key_clip(raw_mp4, out_path, beat, work)
    if not keyed.get("ok"):
        # A rejected key must take the previous asset with it. Leaving the old file on disk keeps a
        # clip the gate just refused in the directory a consumer globs, and it is committed by the
        # same rule that commits the good ones — rejected but still shipping.
        if os.path.exists(out_path):
            os.remove(out_path)
            log(f"  {name:7} removed the superseded asset — it did not pass the leak gate")
        return {"path": out_path, "passed": False, "error": keyed.get("error"), "still": pf}
    if keyed.get("leak_trimmed_from_sec"):
        log(f"  {name:7} clip degraded — beat trimmed "
            f"{keyed['leak_trimmed_from_sec']}s -> {keyed['duration_sec']}s")

    log(f"  {name:7} auditing...")
    audit = audit_clip(out_path, work, extra, costs)
    _sweep_scratch(work)
    return {"path": out_path, "passed": bool(audit.get("pass")), "clip": keyed,
            "audit": audit, "still": {"passed": pf.get("passed")}}


def _sweep_scratch(work_dir):
    """Drop the exploded frame directories, keep what cost money.

    ``frames``/``crop``/``audit`` are hundreds of full-size stills per reaction and regenerate from
    the clip in seconds. The magenta seed and the i2v mp4 stay: those are the purchase, and keeping
    them is what makes re-keying free.
    """
    for scratch in ("frames", "crop", "audit"):
        shutil.rmtree(os.path.join(work_dir, scratch), ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description="Build Bolt's animated quiz reaction library.")
    ap.add_argument("names", nargs="*", help=f"subset of: {', '.join(REACTIONS)}")
    ap.add_argument("--force", action="store_true",
                    help="re-key and re-audit from the clip already bought (no i2v spend)")
    ap.add_argument("--regenerate", action="store_true",
                    help="buy a new still and a new i2v clip, discarding what is there")
    ap.add_argument("--reclip", action="store_true",
                    help="buy a new i2v clip from the EXISTING still — changes one variable, so a "
                         "model or prompt change can be judged against the same seed")
    ap.add_argument("--hero", action="store_true",
                    help="generate with the pro i2v tier (2x rate) — holds the flat background "
                         "better on leaning and receding poses")
    ap.add_argument("--dry-run", action="store_true", help="price the run without spending")
    args = ap.parse_args()

    unknown = [n for n in args.names if n not in REACTIONS]
    if unknown:
        ap.error(f"unknown reaction(s): {', '.join(unknown)}. known: {', '.join(REACTIONS)}")
    wanted = args.names or list(REACTIONS)

    # Deliberately not at import time. Every path this module builds is absolute, so the chdir is
    # only a convenience for the CLI — and at module scope it would follow the import into any
    # process that merely wanted to reuse the keying helpers, moving their working directory.
    os.chdir(PROJ)
    load_credentials()
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(RAW, exist_ok=True)
    report_before = load_report()
    todo = [n for n in wanted
            if args.force or args.regenerate or args.reclip or not is_built(n, report_before)]
    skip = [n for n in wanted if n not in todo]
    # Only the reactions with no clip already bought cost anything. --force re-keys from disk.
    paid = [n for n in todo
            if args.regenerate or args.reclip
            or not (playable(os.path.join(RAW, n, f"{n}.i2v.mp4"))
                    or os.path.exists(asset_path(n)))]
    per = I2V_SECONDS * (HERO_RATE_SEC if args.hero else FAL_RATE_SEC) + STILL_COST_EST
    log(f"reactions: {len(wanted)} requested, {len(skip)} already built, {len(todo)} to build, "
        f"{len(paid)} needing generation")
    if skip:
        log(f"  reusing: {', '.join(skip)}")
    if len(todo) > len(paid):
        log(f"  re-keying free from clips already bought: "
            f"{', '.join(n for n in todo if n not in paid)}")
    tier = "pro" if args.hero else "standard"
    log(f"estimate: {len(paid)} x ~${per:.2f} = ~${len(paid) * per:.2f} "
        f"({tier} i2v ${I2V_SECONDS * (HERO_RATE_SEC if args.hero else FAL_RATE_SEC):.2f} + "
        f"still ~${STILL_COST_EST:.2f}; audit retries cost more)")
    if args.dry_run:
        log("dry run — nothing generated, nothing spent")
        return 0

    # Seeded from what is already on disk so a partial run cannot erase the verdicts of reactions
    # it did not touch — the report is the record of what has been graded, not of this invocation.
    costs, report = [], dict(report_before)
    for name in wanted:
        # One bad reaction must not take the batch down with it. A corrupt clip halfway through a
        # five-item run used to abort the rest with a traceback, losing the work already paid for
        # in the same invocation.
        try:
            report[name] = build_reaction(name, REACTIONS[name], costs,
                                          force=args.force, regenerate=args.regenerate,
                                          hero=args.hero, reclip=args.reclip)
        except Exception as exc:                                  # noqa: BLE001
            log(f"  {name:7} FAILED {type(exc).__name__}: {exc}")
            report[name] = {"path": asset_path(name), "passed": False,
                            "error": f"{type(exc).__name__}: {exc}"}
        json.dump(report, open(report_path(), "w"), indent=2, default=str)
    log("\n=== BOLT REACTION LIBRARY ===")
    for name, r in report.items():
        if r.get("reused"):
            log(f"  {name:7} REUSED")
            continue
        clip = r.get("clip") or {}
        state = "PASS" if r.get("passed") else "CHECK"
        detail = r.get("error") or ", ".join((r.get("audit") or {}).get("violations") or []) or ""
        log(f"  {name:7} {state:5} {clip.get('duration_sec', '?')}s "
            f"{clip.get('size', '')} opaque={clip.get('mean_opaque_pct', '?')}%  {detail}")
    log(f"\ncost ${sum(costs):.2f}  ->  {OUT}")
    log("raw seeds and untrimmed clips kept in _raw/ for re-trimming without re-spending")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
