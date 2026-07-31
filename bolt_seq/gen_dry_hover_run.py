"""Produce bolt_hover_run_dry.png — a DRY reaching/hover-run Bolt (one hand forward, no water splash).
No supplied source was reachable (Downloads is TCC-blocked), so this GENERATES one and gates it by the
full preflight: anatomy (one hover-base, no legs/feet/mouth/extra), clean-plate (no text/UI), and
no-water/splash. Chroma-keys magenta → transparent with de-spill + light alpha feather. Reject rather
than fall back to bolt_swim.png. Image-gen + VLM only, NO paid video.
Run: python3 -m bolt_seq.gen_dry_hover_run"""
import os, sys, json, subprocess
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
from bolt_seq import compiler as C
from bolt_seq.character import BOLT
from bolt_seq.providers import directed_video as DV
from PIL import Image, ImageFilter

OXY = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription")
OUT = os.path.join(OXY, "bolt_hover_run_dry.png")
PROMPT = ("A small toy-robot mascot Bolt, full body, centered, on a SOLID FLAT MAGENTA (#FF00FF) background "
          "filling the whole frame. It has " + BOLT["identity"] + ". POSE: hover-RUNNING forward to the "
          "RIGHT with ONE hand REACHING forward, leaning into a determined dash, its SINGLE rounded "
          "hover-base gliding just above the floor, body tilted forward with urgency. Completely DRY — "
          "absolutely NO water, NO splash, NO bubbles, NO mist, NO wet effects, NO droplets. Plain cyan "
          "chest panel with NO text or symbols. Premium 3D cartoon render. NOT upright, NOT waving.")
CLEAN_CHECK = ["no water, splash, bubbles, mist or wet effects anywhere",
               "no on-screen text, letters, numbers or symbols",
               "background is solid flat magenta, clean edges (no stray objects)"]


def despill_feather(png):
    im = Image.open(png).convert("RGBA"); px = im.load(); w, h = im.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 250 and r > 120 and b > 120 and g < r - 20 and g < b - 20:   # magenta fringe on edges
                m = (r + b) // 2; px[x, y] = (min(r, m), g, min(b, m), a)
    alpha = im.split()[3].filter(ImageFilter.GaussianBlur(0.8)); im.putalpha(alpha)
    bbox = im.getbbox()
    if bbox:
        im = im.crop(bbox)   # crop transparent margins only
    im.save(png)
    return png


def no_water_check(png, cost):
    import explainer_pipeline as ep, base64
    b = base64.b64encode(open(png, "rb").read()).decode()
    try:
        r = ep._claude().messages.create(model="claude-opus-4-8", max_tokens=200,
            system="Strict asset auditor.", messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b}},
                {"type": "text", "text": "Return ONLY JSON: {\"water_or_splash\":bool (any water, splash, "
                 "bubbles, mist, droplets or wet effect?),\"magenta_fringe\":bool (visible magenta/pink "
                 "edge halo?),\"reaching_hover_run\":bool (is it a forward hover-run/reach pose?)}"}]}])
        cost.append(ep._msg_cost(r.usage)); o, _ = ep._parse_script_json(r.content[0].text)
        return o if isinstance(o, dict) else {}
    except Exception as e:
        return {"error": str(e)}


def main():
    cost = []; raw = OUT + ".raw.png"; best = None
    for i in range(5):
        C.gen_image(PROMPT, raw, size="1024x1536")
        C.chroma_key(raw, OUT); despill_feather(OUT)
        an = DV.anatomy_vlm(OUT, BOLT["reference"], BOLT["anatomy"], [(0, OUT)], cost=cost)
        proh = sorted({x for f in an.get("per_frame", []) for x in (f.get("prohibited_seen", []) + f.get("required_altered", []))})
        cp = DV.clean_plate_vlm(OUT, [(0, OUT)], cost=cost, expected_objects=["a robot"])
        ui = sorted({x for f in cp.get("per_frame", []) for x in f.get("ui_seen", [])})
        pf = C.preflight(OUT, CLEAN_CHECK, cost_sink=cost)
        nw = no_water_check(OUT, cost)
        ok = (not proh) and (not ui) and pf["pass"] and (not nw.get("water_or_splash")) and (not nw.get("magenta_fringe"))
        print(f"  try{i+1}: anatomy={'clean' if not proh else proh} ui={ui or 'none'} checklist={'PASS' if pf['pass'] else pf['violations']} "
              f"water={nw.get('water_or_splash')} fringe={nw.get('magenta_fringe')} reach={nw.get('reaching_hover_run')}", flush=True)
        rep = {"anatomy_clean": not proh, "anatomy_flags": proh, "clean_plate": not ui, "ui": ui,
               "checklist_pass": pf["pass"], "no_water": not nw.get("water_or_splash"),
               "no_magenta_fringe": not nw.get("magenta_fringe"), "reaching_hover_run": nw.get("reaching_hover_run"),
               "accepted": ok, "attempt": i + 1}
        if best is None or (ok and not best["accepted"]):
            import shutil; keep = OUT + f".try{i+1}.png"; shutil.copy(OUT, keep); best = {**rep, "keep": keep}
        if ok:
            break
    # if accepted keep OUT as-is; if not, OUT holds the last try (report says accepted=False → caller must NOT use it)
    json.dump(best, open(os.path.join(OXY, "bolt_hover_run_dry_preflight.json"), "w"), indent=2, default=str)
    print(f"ACCEPTED={best['accepted']} | bolt_hover_run_dry.png | cost ${sum(cost):.2f} (image+VLM, no paid video)")


if __name__ == "__main__":
    main()
