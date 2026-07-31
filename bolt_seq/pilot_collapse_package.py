"""PREPARE (do not execute) the Shot-B atomic-collapse paid pilot package. Builds + verifies the clean
generation SEED (weak-hovering Bolt, sputtering thruster, portal beyond, no UI) and the clean END-STATE
TARGET (prone Bolt, portal beyond, no UI), runs anatomy + clean-plate preflight on both, and writes the
entry/exit specs, acceptance gates and spend estimate. NO video generation, NO spend.
Run: python3 -m bolt_seq.pilot_collapse_package"""
import os, sys, json, base64, math
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
from bolt_seq import topics as T
from bolt_seq.character import BOLT
from bolt_seq.providers import directed_video as DV
from PIL import Image, ImageDraw, ImageFilter

P = os.path.join(PROJ, "renders/bolt_seq/_oxygen_pilot"); OUT = os.path.join(P, "collapse_pilot"); os.makedirs(OUT, exist_ok=True)
IMPAIRED = os.path.join(P, "bolt_impaired.png"); COL = os.path.join(P, "bolt_collapsed.png")
PORTAL = os.path.join(P, "hub_clean.png"); PLATE = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription/tunnel.png")
SEED = os.path.join(OUT, "collapse_seed.png"); ENDT = os.path.join(OUT, "collapse_end_target.png")
W, H = 1080, 1920
PRICES = {"kling-v3-pro": 0.56}


def floor_bg():
    plate = Image.open(PLATE).convert("RGB"); z = 1.45
    cov = plate.resize((max(int(W * z), int(plate.width * (H * z) / plate.height)), int(H * z)), Image.LANCZOS)
    x = max(0, min(cov.width - W, int((cov.width - W) * 0.35))); y = max(0, min(cov.height - H, int((cov.height - H) * 0.78)))
    return cov.crop((x, y, x + W, y + H)).convert("RGBA")


def _paste(base, img_path, cx, cy, base_h, grade=True):
    im = Image.open(img_path).convert("RGBA")
    if grade:
        from PIL import ImageEnhance
        a = im.split()[3]; rgb = ImageEnhance.Brightness(im.convert("RGB")).enhance(0.66)
        rgb = Image.blend(rgb, Image.new("RGB", im.size, (32, 100, 108)), 0.24); im = rgb.convert("RGBA"); im.putalpha(a)
    h = base_h; w = int(im.width * h / im.height); im = im.resize((w, h), Image.LANCZOS)
    base.alpha_composite(im, (int(cx - w / 2), int(cy - h / 2)))


def portal_bg(base):
    im = Image.open(PORTAL).convert("RGBA"); h = 230; im = im.resize((int(im.width * h / im.height), h), Image.LANCZOS)
    base.alpha_composite(im, (int(0.74 * W - im.width / 2), int(0.30 * H - im.height / 2)))


def thruster(base, cx, cy):
    tg = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(tg)
    for rr, aa in ((46, 60), (26, 120), (12, 180)):     # weak, sputtering glow
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=(120, 220, 255, aa))
    base.alpha_composite(tg.filter(ImageFilter.GaussianBlur(7)))


def contact_shadow(base, cx, cy, w):
    sh = Image.new("RGBA", base.size, (0, 0, 0, 0)); ImageDraw.Draw(sh).ellipse(
        [cx - w * 0.55, cy - w * 0.12, cx + w * 0.55, cy + w * 0.12], fill=(0, 0, 0, 120))
    base.alpha_composite(sh.filter(ImageFilter.GaussianBlur(18)))


def build_seed():
    fr = floor_bg(); portal_bg(fr)
    thruster(fr, int(0.40 * W), int(0.60 * H))                     # sputtering base glow
    _paste(fr, IMPAIRED, 0.40 * W, 0.50 * H, 600)                  # weak hover above floor
    fr.convert("RGB").save(SEED); return SEED


PRONE = os.path.join(OUT, "bolt_prone.png")
_MAG = (" The ENTIRE background must be SOLID FLAT MAGENTA (#FF00FF) filling the frame — no ground, no shadow.")
_PRONE_PROMPT = ("A small toy-robot mascot Bolt, full body. It has " + BOLT["identity"] + ". POSE: COLLAPSED "
                 "and lying LOW on the ground — face-down / deeply slumped over, body limp and powered-out, "
                 "its SINGLE rounded hover-base still intact underneath. Absolutely NO legs, NO feet, NO "
                 "boots. Its chest is a plain smooth cyan panel: NO text, NO 'BOLT' label, NO letters, NO "
                 "icon, NO gauge, NO symbols anywhere on its body. Premium 3D cartoon render." + _MAG)


def regen_prone(cost, tries=6):
    """Clean prone/collapsed pose: anatomy-clean (hover-base, no legs) AND no on-body text/UI (the old
    bolt_collapsed.png carried a 'BOLT' chest label). Gated by anatomy + clean-plate."""
    from bolt_seq import compiler as CC
    if os.path.exists(PRONE):
        a = DV.anatomy_vlm(PRONE, BOLT["reference"], BOLT["anatomy"], [(0, PRONE)], cost=cost)
        aok = not any(f.get("prohibited_seen") or f.get("required_altered") for f in a.get("per_frame", []))
        c = DV.clean_plate_vlm(PRONE, [(0, PRONE)], cost=cost, expected_objects=["a robot"])
        cok = not any(f.get("ui_seen") for f in c.get("per_frame", []))
        if aok and cok:
            print("  reuse existing clean prone pose"); return PRONE
    for i in range(tries):
        raw = PRONE + ".raw.png"; CC.gen_image(_PRONE_PROMPT, raw, size="1024x1536"); CC.chroma_key(raw, PRONE)
        a = DV.anatomy_vlm(PRONE, BOLT["reference"], BOLT["anatomy"], [(0, PRONE)], cost=cost)
        aok = not any(f.get("prohibited_seen") or f.get("required_altered") for f in a.get("per_frame", []))
        c = DV.clean_plate_vlm(PRONE, [(0, PRONE)], cost=cost, expected_objects=["a robot"])
        ui = sorted({x for f in c.get("per_frame", []) for x in f.get("ui_seen", [])})
        print(f"    prone regen try{i+1}: anatomy={'clean' if aok else 'bad'} onbody_ui={ui or 'none'}", flush=True)
        if aok and not ui:
            return PRONE
    return PRONE


def build_end_target(prone):
    fr = floor_bg(); portal_bg(fr)
    contact_shadow(fr, 0.41 * W, 0.82 * H, 620)
    _paste(fr, prone, 0.41 * W, 0.73 * H, 600)                     # prone on floor, short of portal
    fr.convert("RGB").save(ENDT); return ENDT


def verify(img, want_prone, cost):
    an = DV.anatomy_vlm(img, BOLT["reference"], BOLT["anatomy"], [(0, img)], cost=cost)
    proh = sorted({x for f in an.get("per_frame", []) for x in (f.get("prohibited_seen", []) + f.get("required_altered", []))})
    cp = DV.clean_plate_vlm(img, [(0, img)], cost=cost, expected_objects=["a glowing green portal ring", "a robot"])
    ui = sorted({x for f in cp.get("per_frame", []) for x in f.get("ui_seen", [])})
    import explainer_pipeline as ep
    b = base64.b64encode(open(img, "rb").read()).decode(); scene = {}
    q = ("Return ONLY JSON: {\"bolt_count\":int,\"single_hover_base\":bool,\"portal_present\":bool,"
         "\"portal_beyond_and_distinct_from_bolt\":bool,\"bolt_short_of_portal\":bool,"
         + ("\"bolt_prone_or_slumped\":bool" if want_prone else "\"bolt_weakly_hovering\":bool") + "}")
    try:
        r = ep._claude().messages.create(model="claude-opus-4-8", max_tokens=250, system="Strict scene auditor.",
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b}},
                {"type": "text", "text": q}]}])
        cost.append(ep._msg_cost(r.usage)); scene, _ = ep._parse_script_json(r.content[0].text); scene = scene if isinstance(scene, dict) else {}
    except Exception as e:
        scene = {"error": str(e)}
    dims_ok = Image.open(img).size == (W, H)
    checks = {"anatomy_clean": not proh, "clean_plate_no_ui": not ui, "exactly_one_bolt": scene.get("bolt_count") == 1,
              "portal_beyond_distinct": bool(scene.get("portal_present") and scene.get("portal_beyond_and_distinct_from_bolt")),
              "bolt_short_of_portal": bool(scene.get("bolt_short_of_portal")), "dims_1080x1920": dims_ok}
    if not want_prone:   # hover-base must be VISIBLE only when upright; prone naturally occludes it
        checks["single_hover_base"] = bool(scene.get("single_hover_base"))
    checks[("bolt_prone_or_slumped" if want_prone else "bolt_weakly_hovering")] = bool(
        scene.get("bolt_prone_or_slumped") if want_prone else scene.get("bolt_weakly_hovering"))
    return {"all_pass": all(checks.values()), "checks": checks, "anatomy_flags": proh, "clean_plate_ui": ui, "scene": scene}


def main():
    cost = []
    dh = T.load("oxygen_subscription")["directed_hero"]["shot_b_atomic_collapse"]
    seed = build_seed(); prone = regen_prone(cost); endt = build_end_target(prone)
    vs = verify(seed, want_prone=False, cost=cost)
    ve = verify(endt, want_prone=True, cost=cost)
    atomic = DV.validate_atomic_action(dh)
    est = {m: {"per_candidate_usd": p, "max_candidates": 2, "worst_case_video_usd": round(p * 2, 2),
               "expected_first_pass_usd": p, "vlm_eval_usd_est": 0.24, "total_worst_case_usd": round(p * 2 + 0.24, 2),
               "cap_usd": 1.40} for m, p in PRICES.items()}
    pkg = {
        "shot": "B — atomic collapse (motivated cut from Shot A)", "no_spend": True, "allow_paid_on_disk": DV.ALLOW_PAID,
        "atomic_action_ok": atomic["ok"], "atomic_action": atomic["generated_action"],
        "contract": {k: dh[k] for k in ("duration_s", "starting_state", "action", "end_state", "prohibit", "acceptance")},
        "clean_seed": {"path": seed, "preflight": vs},
        "clean_end_state_target": {"path": endt, "preflight": ve},
        "entry_spec": {"seed_image": seed, "start_state": dh["starting_state"],
                       "gates": ["technical", "anatomy", "clean_plate", "start_boundary(match seed)"]},
        "exit_spec": {"end_target": endt, "end_state": dh["end_state"],
                      "gates": ["exit_boundary(match end target)", "portal_proximity(short of portal)", "no_recovery"]},
        "acceptance_gates": dh["acceptance"],
        "phases": dh["phases"], "entities": dh["entities"],
        "pilot_limits": {"model": "kling-v3-pro", "max_candidates": 2, "hard_cap_usd": 1.40,
                         "stop_after_first_pass": True, "no_other_blocks": True, "no_alternate_model": True,
                         "no_automatic_insertion": True},
        "spend_estimate": est,
        "ready_for_authorization": vs["all_pass"] and ve["all_pass"],
    }
    json.dump(pkg, open(os.path.join(OUT, "pilot_collapse_package.json"), "w"), indent=2, default=str)
    # review contact sheet: seed | end-state target
    def thumb(p):
        im = Image.open(p).convert("RGB"); im.thumbnail((360, 640)); return im
    sheet = Image.new("RGB", (360 * 2 + 30, 664), (16, 16, 20)); d = ImageDraw.Draw(sheet)
    sheet.paste(thumb(seed), (0, 24)); sheet.paste(thumb(endt), (390, 24))
    d.text((8, 4), "SEED (start of collapse)", fill=(240, 240, 240)); d.text((398, 4), "END-STATE TARGET", fill=(240, 240, 240))
    sheet.save(os.path.join(OUT, "collapse_pilot_contact_sheet.jpg"), quality=90)

    print("=== SHOT-B ATOMIC COLLAPSE PILOT PACKAGE (no spend) ===")
    print("atomic-action:", atomic["ok"], atomic["generated_action"])
    print("SEED preflight:", "ALL PASS" if vs["all_pass"] else "FAIL", vs["checks"])
    if vs["anatomy_flags"] or vs["clean_plate_ui"]: print("  seed issues:", vs["anatomy_flags"], vs["clean_plate_ui"])
    print("END-TARGET preflight:", "ALL PASS" if ve["all_pass"] else "FAIL", ve["checks"])
    if ve["anatomy_flags"] or ve["clean_plate_ui"]: print("  end issues:", ve["anatomy_flags"], ve["clean_plate_ui"])
    print("spend: v3-pro first-pass ~$0.56 · worst-case 2×$0.56+~$0.24 = ~$1.36 · cap $1.40")
    print("READY FOR AUTHORIZATION:", pkg["ready_for_authorization"], "| cost so far $%.3f (VLM only)" % sum(cost))
    print("package:", OUT)


if __name__ == "__main__":
    main()
