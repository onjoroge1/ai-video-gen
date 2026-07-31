"""Dry Oxygen V1.2 — short LOCKED-CAMERA locomotion MOTION TEST (5-6s), no captions, no collapse, no
paid video, no new image gen. Proves the motion architecture BEFORE rebuilding the full Short:
  • locked camera: the corridor+embedded-terminal plate is drawn IDENTICALLY every frame (0 pan/zoom);
  • exactly ONE wall-embedded refill terminal (part of the plate — no independent sprite);
  • Bolt provides ALL approach motion via a real hover-run locomotion cycle (cubic path, velocity-linked
    forward tilt, hover bob, squash/stretch beats, pose cycle run→strain→fail with motion-blur bridges,
    anticipation + progressive deceleration as oxygen falls, increasing droop).
Deliverables + camera/world-attachment/natural-motion gates + v1.1-vs-v1.2 comparison.
Run: python3 -m bolt_seq.dry_motion_test_v1_2"""
import os, sys, json, subprocess, math
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
from bolt_seq import compiler as C, effects as FX
from bolt_seq.providers import directed_video as DV
from PIL import Image, ImageDraw, ImageFilter

OX = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription")
OUT = os.path.join(OX, "v1_2"); os.makedirs(OUT, exist_ok=True)
PLATE = os.path.join(OX, "corridor_with_terminal.png")
POSES = {"run": os.path.join(OX, "bolt_hover_run_dry.png"), "strain": os.path.join(OX, "bolt_strain.png"),
         "fail": os.path.join(OX, "bolt_fail.png")}
W, H, FPS, DUR = 1080, 1920, 30, 5.5
TERM_X = 0.66   # fixed terminal screen position (embedded in the plate)


def _bg():
    """Locked camera: cover-fit the fixed plate to the frame ONCE (identical every frame)."""
    im = Image.open(PLATE).convert("RGB")
    tw = max(W, int(im.width * H / im.height)); im = im.resize((tw, H), Image.LANCZOS)
    x = (im.width - W) // 2
    return im.crop((x, 0, x + W, H)).convert("RGBA")


_POSE_CACHE = {k: Image.open(v).convert("RGBA") for k, v in POSES.items()}


def _bolt_img(t):
    """Pose CYCLE with motion-blur BRIDGE at swaps (cross-fade over ~0.12s → no instantaneous teleport)."""
    if t < 0.42:
        a, b, u = "run", "run", 0.0
    elif t < 0.5:
        a, b, u = "run", "strain", (t - 0.42) / 0.08
    elif t < 0.72:
        a, b, u = "strain", "strain", 0.0
    elif t < 0.8:
        a, b, u = "strain", "fail", (t - 0.72) / 0.08
    else:
        a, b, u = "fail", "fail", 0.0
    ia, ib = _POSE_CACHE[a], _POSE_CACHE[b]
    if u <= 0:
        return ia
    ib2 = ib.resize(ia.size, Image.LANCZOS)
    return Image.blend(ia, ib2, u)   # blended = motion-blur bridge across the swap


def render():
    fdir = os.path.join(OUT, "_frames"); os.makedirs(fdir, exist_ok=True)
    for f in os.listdir(fdir):
        os.remove(os.path.join(fdir, f))
    bg = _bg(); n = int(DUR * FPS); prev_cx = None; samp = []
    for i in range(n):
        t = i / (n - 1)
        oxygen = 1.0 - t                                   # drains → energy/velocity fall
        # cubic path with anticipation (tiny hold) then ease-out deceleration; Bolt provides the motion
        p = max(0.0, (t - 0.06) / 0.94)
        ease = 1 - (1 - p) ** 2                            # decelerating
        cx = 0.12 + (0.52 - 0.12) * ease                   # left → short of the fixed terminal (0.66)
        energy = 0.4 + 0.6 * oxygen                        # bob/beat amplitude weakens with oxygen
        bob = 0.022 * math.sin(2 * math.pi * 2.1 * t) * energy
        droop = 0.05 * max(0.0, t - 0.6) / 0.4             # sink slightly as it fails
        cy = 0.52 + bob + droop
        vel = (cx - prev_cx) if prev_cx is not None else 0.02
        tilt = min(16.0, vel * 620) * (0.6 + 0.4 * oxygen) - droop * 120   # forward lean ∝ velocity; nose-down as it droops
        sy = 1.0 + 0.05 * math.sin(2 * math.pi * 2.1 * t + math.pi) * energy  # squash/stretch beat (anti-phase to bob)
        sx = 1.0 / (sy ** 0.5)
        base_h = 560
        fr = bg.copy()
        # ground contact shadow under Bolt (grounds him; moves WITH Bolt, shrinks as he nears wall lighting)
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(sh).ellipse([int(cx * W - 150), int(0.80 * H), int(cx * W + 150), int(0.80 * H + 46)],
                                   fill=(0, 0, 0, 120))
        fr.alpha_composite(sh.filter(ImageFilter.GaussianBlur(16)))
        img = _bolt_img(t)
        hh = int(base_h * sy); ww = int(img.width * (base_h / img.height) * sx)
        im = img.resize((max(1, ww), max(1, hh)), Image.LANCZOS)
        if abs(tilt) > 0.2:
            im = im.rotate(tilt, expand=True, resample=Image.BICUBIC)
        px, py = int(cx * W - im.width / 2), int(cy * H - im.height / 2)
        # accumulation motion blur proportional to per-frame travel (a smear, never ghost copies)
        dpx = int(vel * W)
        if dpx > 6:
            K = 6
            for k in range(K):
                g = im.copy(); g.putalpha(g.split()[3].point(lambda q: int(q / K)))
                fr.alpha_composite(g, (px - int(dpx * k / K), py))
        else:
            fr.alpha_composite(im, (px, py))
        # optional small O2 meter (deterministic; green→amber→red)
        fr.alpha_composite(FX.resource_meter({"fill": oxygen, "amber": 0.5, "warn": 0.25, "x": 0.08,
                           "y": 0.05, "w": 0.5, "h": 0.022}, (W, H)))
        fr.convert("RGB").save(os.path.join(fdir, f"f{i:04d}.png"))
        if i % 4 == 0:
            samp.append({"t": round(t, 2), "cx": round(cx, 3), "cy": round(cy, 3), "tilt": round(tilt, 1),
                         "sy": round(sy, 3), "vel": round(vel, 4), "pose_t": round(t, 2)})
        prev_cx = cx
    out = os.path.join(OUT, "dry_motion_test_v1_2.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(fdir, "f%04d.png"),
                    "-t", f"{DUR}", "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", out], check=True)
    return out, samp


def camera_model_report(clip):
    """Verify locked camera from pixels: bg (excluding Bolt column) is near-identical first vs last frame."""
    import numpy as np
    d = C.dur(clip)
    def frame(t):
        fp = os.path.join(OUT, f"_cm_{t}.png")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", clip, "-frames:v", "1", fp], check=True)
        return np.asarray(Image.open(fp).convert("L"), float)
    a, b = frame(0.2), frame(d - 0.2)
    right = slice(int(W * 0.60), W)   # terminal wall region (Bolt stays left of 0.58)
    diff = float(np.abs(a[:, right] - b[:, right]).mean()) / 255.0
    return {"camera_mode": "locked_camera", "bg_wall_region_change_pct": round(diff * 100, 2),
            "threshold_pct": 2.0, "pass": diff * 100 <= 2.0}


def main():
    cost = []
    clip, samp = render()
    frames = DV._frames(clip, 10, OUT)
    # gates
    cm = camera_model_report(clip)
    wa = DV.environment_semantic_gate(clip, "a locked-camera dry corridor with ONE fixed wall-mounted refill terminal",
                                      ["two terminals", "multiple refill stations", "floating machine", "terminal moving toward the robot", "portal", "underwater"],
                                      ["one fixed wall terminal"], cost=cost)
    # world attachment: is the terminal immobile relative to the wall across the clip + exactly one?
    import base64, explainer_pipeline as ep
    fb = [b for i, (t, fp) in enumerate(frames) for b in DV._img_block(fp, f"frame {i} @ {t}s:")]
    fb.append({"type": "text", "text": "Return ONLY JSON {\"terminal_immobile_vs_wall\":bool,\"refill_terminal_count\":int,"
               "\"terminal_moves_toward_robot\":bool,\"terminal_grows_independently\":bool,\"looks_like_floating_hud\":bool}"})
    r = ep._claude().messages.create(model="claude-opus-4-8", max_tokens=250, system="Judge terminal attachment from pixels.",
                                     messages=[{"role": "user", "content": fb}]); cost.append(ep._msg_cost(r.usage))
    wo, _ = ep._parse_script_json(r.content[0].text); wo = wo if isinstance(wo, dict) else {}
    world_ok = (wo.get("terminal_immobile_vs_wall") and wo.get("refill_terminal_count") == 1
                and not wo.get("terminal_moves_toward_robot") and not wo.get("terminal_grows_independently")
                and not wo.get("looks_like_floating_hud"))
    nm = DV.natural_character_motion_gate(clip, frames=frames, cost=cost)

    json.dump(cm, open(os.path.join(OUT, "camera_model_report.json"), "w"), indent=2, default=str)
    json.dump({"pass": bool(world_ok), "readings": wo, "env": wa, "samples_terminal": "embedded in plate"},
              open(os.path.join(OUT, "world_attachment_report.json"), "w"), indent=2, default=str)
    json.dump({**nm, "motion_samples": samp}, open(os.path.join(OUT, "natural_motion_report.json"), "w"), indent=2, default=str)

    # contact sheet + v1.1 vs v1.2 comparison
    d = C.dur(clip); sh = Image.new("RGB", (216 * 4, 384 * 2), (16, 16, 20))
    for i in range(8):
        fp = os.path.join(OUT, f"_cs{i}.jpg")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{d*(i+0.5)/8:.2f}", "-i", clip, "-frames:v", "1", "-vf", "scale=216:384", fp], check=True)
        sh.paste(Image.open(fp), ((i % 4) * 216, (i // 4) * 384))
    sh.save(os.path.join(OUT, "dry_motion_test_v1_2_contact_sheet.jpg"), quality=88)
    v11 = os.path.join(OX, "dry_v1_1.mp4")
    def lbl(txt, w):
        p = os.path.join(OUT, f"_lb_{txt}.png"); im = Image.new("RGBA", (w, 54), (0, 0, 0, 0)); dd = ImageDraw.Draw(im)
        from PIL import ImageFont
        try: f = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 26)
        except Exception: f = ImageFont.load_default()
        tw = dd.textbbox((0, 0), txt, font=f)[2]; dd.rectangle([0, 0, w, 50], fill=(0, 0, 0, 165)); dd.text(((w - tw) // 2, 8), txt, font=f, fill=(240, 240, 240)); im.save(p); return p
    cmp = os.path.join(OUT, "v1_1_vs_v1_2_motion_comparison.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", v11, "-i", clip, "-i", lbl("V1.1 static-slide", 540), "-i", lbl("V1.2 locomotion", 540),
                    "-filter_complex", "[0:v]scale=540:960[l0];[2:v]scale=540:-1[ll];[l0][ll]overlay=0:0[l];"
                    "[1:v]scale=540:960[r0];[3:v]scale=540:-1[rr];[r0][rr]overlay=0:0[r];[l][r]hstack=inputs=2[v]",
                    "-map", "[v]", "-t", "5", cmp], check=True)

    acc = {"camera_model_coherent": cm["pass"], "terminal_immobile": bool(wo.get("terminal_immobile_vs_wall")),
           "exactly_one_destination": wo.get("refill_terminal_count") == 1,
           "no_independent_terminal_approach": not wo.get("terminal_moves_toward_robot"),
           "world_attachment": bool(world_ok), "natural_character_motion": nm.get("pass"),
           "no_static_sprite_slide": not nm.get("reject_hits") or "sticker_sliding" not in nm.get("reject_hits", []),
           "no_scale_pop": "abrupt_size_pop" not in nm.get("reject_hits", []),
           "no_pose_teleport": "pose_teleport" not in nm.get("reject_hits", [])}
    fails = [k for k, v in acc.items() if not v]
    json.dump({"acceptance": acc, "failures": fails, "test_pass": not fails, "cost_usd": round(sum(cost), 3)},
              open(os.path.join(OUT, "motion_test_acceptance.json"), "w"), indent=2, default=str)
    print("=== dry_motion_test_v1_2 acceptance ===")
    for k, v in acc.items(): print(f"  {'PASS' if v else 'FAIL'}  {k}")
    print("camera bg-wall change:", cm["bg_wall_region_change_pct"], "%")
    print("natural_motion scores:", nm.get("scores"), "rejects:", nm.get("reject_hits"))
    print("world readings:", wo)
    print(f"TEST_PASS={not fails} failures={fails} | cost ${sum(cost):.2f} (no paid video)")


if __name__ == "__main__":
    main()
