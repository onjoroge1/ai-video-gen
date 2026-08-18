"""Simulation format: data model + inventory check.

A SIMULATION is a portrait short in which one controlled experiment is repeated across many worlds
and the VARIABLE is what changes. That is the whole retention mechanism: the viewer holds a constant
in their head and watches it break. It only works if the constants really are constant, so this
module makes the locked parameters data rather than prose, and refuses to build when a scene is
missing its image.

Reusable by construction: a new simulation is a folder under simulations/<slug>/ holding images, the
spec markdown, and a data module listing scenes. Nothing here knows about bullets or planets.
"""
from __future__ import annotations
import glob
import os
from dataclasses import dataclass, field


@dataclass
class Scene:
    id: str
    image: str                      # stem under the simulation's images/ dir
    narration: str
    seconds: float                  # from the spec's timestamped storyboard
    chips: tuple = ()               # ("EARTH", "1.00g · AIR") -> code-drawn overlay
    onscreen: str = ""              # large burned-in text, e.g. "IT COMES BACK?"
    motion: str = ""                # what MOVES; becomes the i2v action prompt
    prohibited: tuple = ()          # scene-specific negatives from the spec
    animate: bool = True            # False for scenes that should stay still
    # True ONLY for scenes whose plate is genuinely empty of subjects (dust settling, haze). It arms
    # the invented-subject gate. It must NOT be inferred from wildlife negatives: every rain scene
    # carried a no-animals negative, the gate inferred "empty" from it, and rejected seven clips of
    # rain for containing rain -- $2.45 of correct output refused by a wrong premise.
    empty_frame: bool = False
    # Named ambient (sim/figure.AMBIENTS) this scene's light belongs to. Used to grade the character
    # reference BEFORE generation -- prompt language does not beat a studio-lit reference; the
    # pixels win. Empty means inherit meta["ambient"], or neutral if that is absent too.
    ambient: str = ""
    # Deterministic hero subject composited by sim/drop.py AFTER the provider clip returns:
    # {"d_m": 0.012, "v_ms": 1.5, "px_per_m": 1400, ...}. Declaring it does two things at once:
    # the provider's prompt gains "background rain only, no large foreground drop" (it must not
    # draw the subject we own), and the build post-passes the clip through the compositor. One
    # flag, both halves -- because the failure mode of doing them separately is a frame with TWO
    # hero drops, ours and the model's cartoon one.
    hero: dict = None
    # Where this beat sits on the escalation axis named by meta["datum_axis"] (metres, m/s, ...).
    # Only escalation formats need it: a parallel comparison holds magnitude fixed by definition and
    # declares meta["datum"] instead. direction.datum_check reads it to pick the right datum band.
    magnitude: float = None


@dataclass
class Simulation:
    slug: str
    title: str
    root: str                       # simulations/<slug>
    scenes: list
    locked: dict                    # §6 locked experiment parameters -> every i2v prompt
    style: str                      # house look, one sentence, every prompt
    voice: str = "echo"
    # Source plates are rarely the delivery aspect: gpt-image-2 has no 9:16 size. Declaring it makes
    # the centre-crop explicit in inventory instead of silently eating the edges of every shot.
    source_aspect: float = 0.0
    speed: float = 1.0        # TTS delivery rate; specs state wpm, this is how we hit it
    pad_s: float = 0.10       # breathing room after each line. Counts against the runtime band, so
                              # it is configurable rather than a buried constant.
    W: int = 1080
    H: int = 1920
    fps: int = 30
    target_s: tuple = (39.0, 43.0)
    max_gap_s: float = 3.3          # spec gate: seconds allowed between visible outcomes
    # Bed under the narration. "tense" adds pulse without editorialising -- trailer-intensity music
    # asserts drama the visuals deliberately do not, which is the register this format exists to
    # avoid. None disables. The bed is sidechained to the voice, not laid at a fixed level.
    music: str = "tense"
    meta: dict = field(default_factory=dict)

    @property
    def images(self):
        return os.path.join(self.root, "images")

    @property
    def out(self):
        return os.path.join("renders", self.slug)

    @property
    def work(self):
        return os.path.join(self.out, "work")

    def index(self):
        ix = {}
        for p in sorted(glob.glob(os.path.join(self.images, "*.png")) +
                        glob.glob(os.path.join(self.images, "*.jpg"))):
            ix[os.path.splitext(os.path.basename(p))[0]] = p
        return ix

    def asset(self, stem):
        ix = self.index()
        if stem not in ix:
            raise KeyError(f"no image '{stem}' in {self.images}")
        return ix[stem]


class InventoryError(Exception):
    pass


def inventory(sim, verbose=True):
    """Refuse to build on a missing or mismatched asset. Runs BEFORE any spend.

    This is the check that makes dropping new art into a folder safe: every scene must resolve, every
    image must be the declared aspect, and anything present but unused is reported so a forgotten
    asset is visible rather than silently ignored.
    """
    ix = sim.index()
    missing = [s.id for s in sim.scenes if s.image not in ix]
    if missing:
        raise InventoryError(
            f"{len(missing)} scene(s) have no image in {sim.images}: {missing}\n"
            f"available: {sorted(ix)}")

    from PIL import Image
    want = sim.W / sim.H
    wrong = []
    for s in sim.scenes:
        w, h = Image.open(ix[s.image]).size
        if abs(w / h - want) > 0.02:
            wrong.append(f"{s.image} is {w}x{h} ({w/h:.3f}), expected {want:.3f}")
    # gpt-image-2 offers 1024x1536 (2:3) and 1536x1024 -- there is no 9:16 size. The renderer fills
    # and centre-crops, so a 2:3 plate silently loses 15.6% of its WIDTH, 7.8% off each side. Failing
    # here would reject the only aspect the generator can produce; saying nothing is how shots got
    # framed against a picture the viewer never sees. So: report the crop, and require it be declared.
    if wrong:
        if getattr(sim, "source_aspect", None):
            src = sim.source_aspect
            undeclared = [w for w in wrong if f"({src:.3f})" not in w]
            if undeclared:
                raise InventoryError("aspect mismatch beyond the declared source:\n  "
                                     + "\n  ".join(undeclared))
            lost = 1.0 - (want / src) if src > want else 1.0 - (src / want)
            crop_note = {"source_aspect": round(src, 3), "target_aspect": round(want, 3),
                           "width_lost_pct": round(lost * 100, 1),
                           "safe_area_x": [round(lost / 2, 3), round(1 - lost / 2, 3)],
                           "note": "compose inside safe_area_x; the rest is cropped at render"}
        else:
            raise InventoryError(
                "aspect mismatch (set Simulation.source_aspect to declare it deliberately):\n  "
                + "\n  ".join(wrong))

    crop_note = locals().get("crop_note")
    used = {s.image for s in sim.scenes}
    unused = sorted(set(ix) - used)
    total = sum(s.seconds for s in sim.scenes)
    lo, hi = sim.target_s
    info = {"scenes": len(sim.scenes), "images_available": len(ix), "unused": unused,
            "runtime_planned_s": round(total, 2), "in_band": lo <= total <= hi,
            "passed": True}
    if crop_note:
        info["crop"] = crop_note
    if verbose:
        print(f"  scenes            {info['scenes']}")
        print(f"  images resolved   {len(used)}/{len(ix)} in the folder")
        if unused:
            print(f"  UNUSED images     {unused}  <- present but no scene uses them")
        print(f"  planned runtime   {total:.1f}s  (spec band {lo}-{hi}s) "
              f"{'ok' if info['in_band'] else '<-- OUT OF BAND'}")
        if crop_note:
            print(f"  CROP AT RENDER    {crop_note['width_lost_pct']}% of width lost "
                  f"({crop_note['source_aspect']} -> {crop_note['target_aspect']}); "
                  f"compose inside x {crop_note['safe_area_x']}")
    return info


def gap_gate(sim, video, cuts=None, max_gap_s=None, peak=30):
    """The spec's rule -- no more than max_gap_s between VISIBLE OUTCOMES -- measured on the finished
    video.

    The first version of this gate measured SHOT LENGTH, which is only a proxy for stall time when a
    shot is a still image. Against animated clips it flagged six scenes as violations while the
    picture was in fact changing continuously; the longest genuinely static stretch in that render
    was 0.63s. A long shot of a bullet crossing a frame is not a stall.

    So: decode the finished video and find the longest run of frames in which nothing on screen
    changes. That is the quantity the spec is actually about.
    """
    import numpy as np

    import video_audit as va
    cap = max_gap_s or sim.max_gap_s
    # 480x854, not 192x340: at the coarse decode, thin structures -- rain streaks, a soft dust
    # column -- average into the background and a shot the viewer plainly sees moving measures as
    # still (Mars with a spinning dust devil measured 6.7s of "stall" at 192px and 1.3s at 480px).
    # The gate must see what the viewer sees, and the viewer watches at 1080.
    g = va._decode_gray(video, 480, 854).astype(np.int16)
    if len(g) < 2:
        return {"passed": False, "cap_s": cap, "longest_still_s": 0.0, "reason": "no frames"}
    still = np.abs(np.diff(g, axis=0)).max(axis=(1, 2)) <= peak
    best = run = 0
    start = best_start = 0
    for i, x in enumerate(still):
        if x:
            if run == 0:
                start = i
            run += 1
            if run > best:
                best, best_start = run, start
        else:
            run = 0
    longest = best / sim.fps
    where = None
    if cuts and longest > 0:
        t = 0
        for c in cuts:
            if t <= best_start < t + c["frames"]:
                where = c["seg"]; break
            t += c["frames"]
    return {"passed": longest <= cap, "cap_s": cap,
            "longest_still_s": round(longest, 2),
            "at_frame": int(best_start), "in_scene": where,
            "measures": "longest run of frames with no visible change, on the finished video"}


# ---------------------------------------------------------------------------------- layer gates
BG_MOTION_FLOOR = 0.030   # measured: living Kling plates 0.081-0.238; frozen composites 0.001-0.002


def background_motion_gate(video, floor=BG_MOTION_FLOOR, still_span=12):
    """Assert the WORLD is alive, not just the subject.

    This gate exists because every other motion gate passed a render whose backgrounds were dead.
    `shot_motion_gate` measures first-vs-last displacement, and one bullet crossing the frame
    generates plenty of that -- so it certified motion while the planet stood still. Measured on that
    render: background-only motion was 0.002 against 0.081-0.238 for the generated plates, about
    100x less, and nothing caught it but the viewer.

    Background = pixels the subject never crosses, found as those whose luma spans less than
    `still_span` over the whole clip. Their mean frame-to-frame change is the world's own motion.
    """
    import numpy as np

    import video_audit as va
    # 480x854, not 192x340: at the coarse decode, thin structures -- rain streaks, a soft dust
    # column -- average into the background and a shot the viewer plainly sees moving measures as
    # still (Mars with a spinning dust devil measured 6.7s of "stall" at 192px and 1.3s at 480px).
    # The gate must see what the viewer sees, and the viewer watches at 1080.
    g = va._decode_gray(video, 480, 854).astype(np.int16)
    if len(g) < 3:
        return {"passed": False, "reason": "too few frames", "bg_motion": 0.0, "floor": floor}
    d = np.abs(np.diff(g, axis=0))
    span = g.max(axis=0) - g.min(axis=0)
    bg = span < still_span
    if bg.sum() < 500:                       # subject covers nearly everything: nothing to judge
        return {"passed": True, "bg_motion": None, "floor": floor,
                "note": "no stable background region; gate not applicable"}
    bgm = float(d[:, bg].mean())
    return {"passed": bgm >= floor, "bg_motion": round(bgm, 4), "floor": floor,
            "bg_pixels_frac": round(float(bg.mean()), 3),
            "measures": "mean frame-to-frame change of pixels the subject never crosses"}


def subject_identity_sheet(plate_paths, out_png, box=(0.02, 0.28, 0.98, 0.80)):
    """Crop the subject band from every plate into one comparison sheet, for a VISION check.

    THIS IS DELIBERATELY NOT A PIXEL HEURISTIC, after two failed attempts in one sitting:

      attempt 1 -- compare a colour signature of the region Bolt stands in. It flagged EARTH as the
                   worst outlier, because that region is mostly sky and Earth's sky is blue while
                   Venus is orange and Mercury is black. It was measuring the planet.
      attempt 2 -- key on Bolt's cyan-teal accent palette instead. Earth scored 0.59, i.e. 59% of
                   pixels "Bolt", because a clear blue sky IS green-and-blue-above-red and saturated.
                   It was measuring the planet again.

    "Is this the same character" is a perceptual judgement, and the check that actually worked took
    ten seconds: crop the subject from each plate, put them side by side, and LOOK. So that is what
    this returns -- a sheet for a human or a vision model. It never auto-passes, because a gate that
    guesses is worse than no gate: it launders an unchecked assumption into a green tick.
    """
    from PIL import Image, ImageDraw
    import os as _os

    crops = []
    for p in plate_paths:
        im = Image.open(p).convert("RGB")
        w, h = im.size
        c = im.crop((int(box[0] * w), int(box[1] * h), int(box[2] * w), int(box[3] * h)))
        c = c.resize((520, int(520 * c.height / c.width)))
        d = ImageDraw.Draw(c)
        lab = _os.path.basename(p)[:26]
        d.rectangle([0, 0, 520, 26], fill=(0, 0, 0))
        d.text((6, 6), lab, fill=(255, 236, 150))
        crops.append(c)
    hh = max(c.height for c in crops)
    sh = Image.new("RGB", (520 * len(crops), hh), (10, 10, 12))
    for i, c in enumerate(crops):
        sh.paste(c, (520 * i, 0))
    sh.save(out_png)
    return {"passed": None, "requires_review": True, "sheet": out_png,
            "n_plates": len(plate_paths),
            "measures": "nothing automatically -- this is a human/vision comparison sheet",
            "look_for": "same body proportions, same head-to-body ratio, subject present at all, "
                        "launcher attached to its base, consistent scale relative to the launcher"}
