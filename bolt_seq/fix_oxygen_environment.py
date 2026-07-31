"""Regenerate the oxygen world as a DRY dystopian oxygen-subscription district (not underwater), gated by
the environment-semantic gate. Produces: corridor.png (dry sealed corridor with pipes/vents/refill
terminals, haze, red expiration warnings) and refill_terminal.png (mechanical wall-mounted oxygen refill
terminal, green O2 icon, NOT a portal). Image-gen only, NO paid video.
Run: python3 -m bolt_seq.fix_oxygen_environment"""
import os, sys, json
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
from bolt_seq import compiler as C
from bolt_seq.providers import directed_video as DV
from PIL import Image

OXY = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription")
CORRIDOR = os.path.join(OXY, "corridor.png"); TERMINAL = os.path.join(OXY, "refill_terminal.png")

CORRIDOR_PROMPT = (
    "A dry, enclosed FUTURISTIC DYSTOPIAN corridor interior of a sealed oxygen-controlled habitat. Cold "
    "utilitarian corporate/industrial hallway with visible OXYGEN PIPES and air VENTS along the walls and "
    "ceiling, wall-mounted refill terminals in the distance, faint dry ATMOSPHERIC HAZE and dust in the "
    "air, and a few RED subscription-expiration warning lights glowing on the walls. Dry metal floor, "
    "normal gravity. Absolutely NO water, NO underwater look, NO bubbles, NO wet floor, NO submerged "
    "ruins, NO aquatic light rays, NO blue-green underwater grading. Empty of characters. Vertical "
    "cinematic composition, premium 3D render.")
CORRIDOR_CHECK = ["a DRY indoor futuristic corridor/habitat interior, NOT underwater",
                  "visible oxygen pipes, vents, or refill infrastructure",
                  "NO water, NO bubbles, NO wet or submerged look, NO aquatic light",
                  "cold industrial lighting with some red warning lights", "no characters present"]

TERMINAL_PROMPT = (
    "A wall-mounted OXYGEN REFILL TERMINAL — a mechanical wall unit with a glowing GREEN oxygen/breathing "
    "icon (an O2 / lungs symbol) on a small screen, connector nozzles, pipes and air vents, buttons and "
    "gauges, visibly industrial and mechanical, bolted to a wall panel. It is a SOLID wall device. "
    "Absolutely NO open hole, NO glowing ring, NO portal, NO teleporter, NO magic swirl. The ENTIRE "
    "background is SOLID FLAT MAGENTA (#FF00FF), nothing else. Premium 3D render.")
TERMINAL_CHECK = ["a mechanical wall-mounted oxygen refill terminal (a solid device)",
                  "a green oxygen / breathing icon on it", "pipes, vents, nozzle or connector visible",
                  "it is NOT an open ring/portal/hole and NOT a glowing teleporter", "background is solid magenta"]

CORR_PREMISE = "a dry dystopian sealed district where breathable oxygen is a paid metered subscription"
CORR_FORBID = ["underwater", "aquatic", "submerged", "ocean", "swimming pool", "scuba"]
CORR_REQ = ["dry indoor corridor/habitat", "oxygen pipes/vents or refill infrastructure"]
TERM_PREMISE = "a mechanical wall-mounted oxygen refill terminal"
TERM_FORBID = ["portal", "glowing ring", "teleporter", "magic", "open hole", "underwater"]
TERM_REQ = ["mechanical terminal/device", "green oxygen icon"]


def regen(out, prompt, checklist, premise, forbid, req, cutout, cost, tries=5):
    for i in range(tries):
        raw = out + ".raw.png"; C.gen_image(prompt, raw, size="1024x1536" if not cutout else "1024x1536")
        target = raw
        pf = C.preflight(raw, checklist, cost_sink=cost)
        eg = DV.environment_semantic_gate(raw, premise, forbid, req, cost=cost)
        ok = pf["pass"] and eg["pass"]
        print(f"    {os.path.basename(out)} try{i+1}: checklist={'PASS' if pf['pass'] else pf['violations']} | "
              f"env reading='{eg.get('reading')}' pass={eg['pass']} forbidden={eg.get('forbidden_hits')}", flush=True)
        if ok or i == tries - 1:
            if cutout:
                C.chroma_key(raw, out)
            else:
                Image.open(raw).convert("RGB").save(out)
            return {"path": out, "checklist_pass": pf["pass"], "env": eg, "attempt": i + 1, "accepted": ok}
    return {"path": out, "accepted": False}


def main():
    cost = []
    print("=== regenerating DRY oxygen-subscription environment (no paid video) ===", flush=True)
    corr = regen(CORRIDOR, CORRIDOR_PROMPT, CORRIDOR_CHECK, CORR_PREMISE, CORR_FORBID, CORR_REQ, False, cost)
    term = regen(TERMINAL, TERMINAL_PROMPT, TERMINAL_CHECK, TERM_PREMISE, TERM_FORBID, TERM_REQ, True, cost)
    rep = {"corridor": corr, "terminal": term, "cost_usd": round(sum(cost), 3), "no_paid_video": True}
    json.dump(rep, open(os.path.join(OXY, "dry_environment_report.json"), "w"), indent=2, default=str)
    # contact sheet
    try:
        c = Image.open(CORRIDOR).convert("RGB"); c.thumbnail((360, 640))
        t = Image.open(TERMINAL).convert("RGBA"); bg = Image.new("RGB", t.size, (120, 120, 120)); bg.paste(t, (0, 0), t); bg.thumbnail((320, 480))
        sheet = Image.new("RGB", (360 + 340, 640), (16, 16, 20)); sheet.paste(c, (0, 0)); sheet.paste(bg, (370, 60))
        sheet.save(os.path.join(OXY, "dry_environment_contact_sheet.jpg"), quality=90)
    except Exception as e:
        print("sheet:", e)
    print(f"corridor accepted={corr['accepted']} (reading '{corr['env'].get('reading')}') | "
          f"terminal accepted={term['accepted']} (reading '{term['env'].get('reading')}') | cost ${sum(cost):.2f}")


if __name__ == "__main__":
    main()
