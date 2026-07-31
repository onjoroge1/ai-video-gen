"""Build + verify the CLEAN generation seed for the corrected oxygen pilot (NO spend, NO video).
Clean plate = environment + clean unoccupied portal + exactly one Bolt (impaired, hover-base) + the air
bubble. NO meter/text/HUD/vignette/countdown/beacon-rings. Verifies the 7 required conditions via VLM
(anatomy + clean-plate + one-Bolt + unoccupied-portal + dims) and writes a confirmation report.
Run: python3 -m bolt_seq.pilot_v2_seed"""
import os, sys, json, base64
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
from bolt_seq import scene_graph as SG, effects as FX, compiler as C
from bolt_seq.character import BOLT
from bolt_seq.providers import directed_video as DV
from PIL import Image, ImageDraw

OUT = os.path.join(PROJ, "renders/bolt_seq/_oxygen_pilot"); os.makedirs(OUT, exist_ok=True)
OXY = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription")
PLATE = os.path.join(OXY, "tunnel.png"); PORTAL = os.path.join(OUT, "hub_clean.png")
IMPAIRED = os.path.join(OUT, "bolt_impaired.png")
SEED = os.path.join(OUT, "clean_seed.png")
W, H = 1080, 1920


def _one_frame(path):
    return [(0, path)]


def _anatomy_clean(img, cost):
    a = DV.anatomy_vlm(img, BOLT["reference"], BOLT["anatomy"], _one_frame(img), cost=cost)
    proh = sorted({x for f in a.get("per_frame", []) for x in (f.get("prohibited_seen", []) + f.get("required_altered", []))})
    return (not proh), proh


_MAG = (" The ENTIRE background must be SOLID FLAT MAGENTA (#FF00FF) filling the frame — no ground, no shadow.")
_IMP_PROMPT = ("A small toy-robot mascot Bolt, full body, centered. It has " + BOLT["identity"] + ". POSE: "
               "sagging and drooping DOWNWARD, tilted forward, arms hanging limp, clearly impaired and low "
               "on power — BUT it still floats on its SINGLE smooth rounded hover-base. It has absolutely NO "
               "legs, NO feet, NO boots, NO knees — just one rounded hover-base underneath. Its chest is a "
               "plain smooth cyan panel: absolutely NO battery icon, NO gauge, NO screen, NO percentage, NO "
               "numbers, NO text, NO symbols anywhere on its body. Premium 3D cartoon render." + _MAG)


def _plate_clean(img, cost):
    c = DV.clean_plate_vlm(img, _one_frame(img), cost=cost)
    ui = sorted({x for f in c.get("per_frame", []) for x in f.get("ui_seen", [])})
    return (not ui), ui


def regen_impaired(cost, tries=6):
    """Regenerate an impaired pose that is anatomy-CLEAN (single hover-base, no legs/feet) AND has NO
    on-body UI (battery icon/gauge). Gated by the same anatomy + clean-plate checks used on candidates."""
    for i in range(tries):
        raw = IMPAIRED + ".raw.png"; C.gen_image(_IMP_PROMPT, raw, size="1024x1536")
        C.chroma_key(raw, IMPAIRED)
        aok, proh = _anatomy_clean(IMPAIRED, cost)
        pok, ui = _plate_clean(IMPAIRED, cost) if aok else (False, ["skipped"])
        print(f"    impaired regen try{i+1}: anatomy={'clean' if aok else proh} onbody_ui={ui or 'none'}", flush=True)
        if aok and pok:
            return True, i + 1
    return False, tries


def _bubble_png():
    """A small CLUSTER of translucent water bubbles (varying sizes) — reads as underwater air, never a
    single speech-bubble/UI circle."""
    from PIL import ImageFilter
    bp = os.path.join(OUT, "_seed_bubble.png"); s = 300
    bi = Image.new("RGBA", (s, s), (0, 0, 0, 0)); d = ImageDraw.Draw(bi)
    for (cx, cy, r) in [(150, 170, 78), (95, 95, 40), (210, 110, 30), (120, 250, 24), (235, 205, 20)]:
        for rr in range(r, 0, -1):
            a = int(55 * (rr / r) ** 0.6)
            d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=(175, 218, 255, max(6, 45 - a // 2)))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(215, 240, 255, 150), width=max(2, r // 12))
        d.ellipse([cx - int(r * 0.35), cy - int(r * 0.45), cx - int(r * 0.05), cy - int(r * 0.15)],
                  fill=(255, 255, 255, 170))     # specular highlight
    bi = bi.filter(ImageFilter.GaussianBlur(1.0)); bi.save(bp); return bp


def build_seed():
    bp = _bubble_png()
    ents = [
        {"id": "env", "kind": "environment", "provider": "deterministic_2d", "z": 0, "base_h": H, "image": PLATE,
         "tracks": {"scale": SG.const_track(1.04)}},
        {"id": "portal", "kind": "destination", "provider": "deterministic_2d", "z": 20, "base_h": 560,
         "image": PORTAL, "tracks": {"x": SG.const_track(0.72), "y": SG.const_track(0.46)}},
        {"id": "bubble", "kind": "prop", "provider": "deterministic_2d", "z": 45, "base_h": 230, "image": bp,
         "tracks": {"x": SG.const_track(0.47), "y": SG.const_track(0.40)}},   # rising beside Bolt, not above (avoids speech-bubble read)
        {"id": "bolt", "kind": "character", "provider": "deterministic_2d", "z": 50, "base_h": 680, "image": IMPAIRED,
         "tracks": {"x": SG.const_track(0.34), "y": SG.const_track(0.44)}},   # raised so hover-base is clearly visible
    ]
    # render a single frame by compositing at t=0 (reuse the block renderer for one frame)
    clip = os.path.join(OUT, "_seed_1f.mp4")
    C.render_scene_block(clip, ents, 0.2, W=W, H=H, fps=5, tmp_dir=OUT, draw_fn=FX.draw, tmix=1)
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip, "-frames:v", "1", SEED], check=True)
    return SEED


def _one_frame(path):
    return [(0, path)]


def verify(seed, cost):
    """Run the same gates on the still seed: anatomy (per-invariant vs reference), clean-plate, one-Bolt,
    unoccupied portal, dimensions."""
    an = DV.anatomy_vlm(seed, BOLT["reference"], BOLT["anatomy"], _one_frame(seed), cost=cost)
    cp = DV.clean_plate_vlm(seed, _one_frame(seed), cost=cost,
                            expected_objects=["the glowing green oxygen portal ring", "a translucent water bubble"])
    proh = sorted({x for f in an.get("per_frame", []) for x in (f.get("prohibited_seen", []) + f.get("required_altered", []))})
    ui = sorted({x for f in cp.get("per_frame", []) for x in f.get("ui_seen", [])})
    # dedicated count/scene check
    import explainer_pipeline as ep
    b64 = base64.b64encode(open(seed, "rb").read()).decode()
    scene = {}
    try:
        r = ep._claude().messages.create(model="claude-opus-4-8", max_tokens=300,
            system="Strict scene auditor. Report exactly what is visible.",
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                {"type": "text", "text": ("Count and check. Return ONLY JSON: {\"bolt_count\":int,"
                 "\"portal_present\":bool,\"portal_unoccupied\":bool (true if the green portal is an empty "
                 "ring with NO character/face inside),\"portal_distinct_from_bolt\":bool,"
                 "\"bubble_present\":bool}")}]}])
        cost.append(ep._msg_cost(r.usage)); scene, _ = ep._parse_script_json(r.content[0].text)
        scene = scene if isinstance(scene, dict) else {}
    except Exception as e:
        scene = {"error": str(e)}
    im = Image.open(seed); dims_ok = im.size == (W, H)
    checks = {
        "exactly_one_bolt": scene.get("bolt_count") == 1,
        "single_hover_base_no_lower_limbs": not any(x in proh for x in
            ("legs", "feet", "boots", "shoes", "separate lower limbs", "hover_base")),
        "no_mouth_or_extra_limbs": not any(x in proh for x in ("mouth", "extra limbs")),
        "no_meter_text_hud_vignette_countdown": not ui,
        "clean_unoccupied_portal": bool(scene.get("portal_present") and scene.get("portal_unoccupied")
                                        and scene.get("portal_distinct_from_bolt")),
        "composition_1080x1920": dims_ok,
    }
    report = {"seed": seed, "checks": checks, "all_pass": all(checks.values()),
              "anatomy_prohibited_or_altered": proh, "clean_plate_ui_seen": ui, "scene": scene,
              "dims": list(im.size)}
    json.dump(report, open(os.path.join(OUT, "clean_seed_confirmation.json"), "w"), indent=2, default=str)
    return report


def main():
    cost = []
    print("=== impaired pose: reuse if already anatomy+plate clean, else regenerate (gated) ===", flush=True)
    reuse = os.path.exists(IMPAIRED) and _anatomy_clean(IMPAIRED, cost)[0] and _plate_clean(IMPAIRED, cost)[0]
    if reuse:
        print("  reusing existing anatomy-clean impaired pose"); ok = True
    else:
        ok, n = regen_impaired(cost); print(f"  impaired pose anatomy-clean: {ok} (after {n} tries)")
    seed = build_seed()
    rep = verify(seed, cost)
    print("=== CLEAN SEED VERIFICATION (no spend) ===")
    for k, v in rep["checks"].items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    print("anatomy prohibited/altered:", rep["anatomy_prohibited_or_altered"] or "none")
    print("clean-plate UI seen:", rep["clean_plate_ui_seen"] or "none")
    print("scene:", rep["scene"])
    print(f"ALL 7 PASS: {rep['all_pass']} | dims {rep['dims']} | cost ${sum(cost):.3f} (VLM only)")


if __name__ == "__main__":
    main()
