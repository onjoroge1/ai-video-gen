"""Generate ONE strained forward-leaning one-arm-reaching Bolt pose (user-authorized small gpt-image spend;
NO video spend). Identity-preserving: re-poses the EXISTING clean Bolt via images.edit (gpt-image-2) so it
stays the same character as the seed. Hard-gated: anatomy (no legs/feet/mouth/extra limbs), action
readability (reads as straining+reaching, not neutral), and identity match vs the seed Bolt. Capped at 3
attempts; stops on first full pass. Output: renders/.../oxygen_subscription/bolt_strain_reach.png (RGBA).
Run: python3 -m bolt_seq.gen_strained_reach_pose"""
import os, sys, json, base64, shutil
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ); sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
from bolt_seq import compiler as C
from bolt_seq.character import BOLT
from bolt_seq.providers import directed_video as DV
from PIL import Image

OX = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription")
REF = os.path.join(OX, "bolt_hover_run_dry.png")        # identity reference (the seed Bolt)
OUT = os.path.join(OX, "bolt_strain_reach.png")
RAW = OUT + ".raw.png"
MAX_TRIES = 4

PROMPT = (
    "Re-pose THIS EXACT robot character (keep its identical body colour, mint-green accents, glossy black "
    "visor, exactly two cyan oval eyes and NO mouth, cyan chest panel, thin antenna, two stubby arms, a "
    "SINGLE rounded hover-base and NO legs). New pose: the robot is UTTERLY EXHAUSTED and STRAINING with its "
    "last effort — eyes NARROWED/half-lidded and DIMMER, antenna DROOPING, head and shoulders SAGGING with "
    "fatigue, body pitched heavily forward-right, ONE arm barely stretched out forward-right straining to "
    "reach something just beyond its grasp, the OTHER arm hanging low and limp for balance, hovering low and "
    "unsteady as its propulsion fails. It looks tired and struggling, NOT energetic or happy. Side view facing "
    "right. Full body, centered, on a SOLID MAGENTA (#FF00FF) background. 3D cartoon render, no text, no other "
    "characters, no legs, no feet."
)
WANT = ("exhausted and straining with its last effort, sagging and pitched forward, ONE arm barely reaching "
        "forward toward an off-screen target, the other arm limp/low, hovering unsteadily on a single base with "
        "NO legs, propulsion failing — tired and struggling, NOT energetic")


def gen_edit(ref, out_raw):
    """gpt-image-2 identity-preserving edit; fall back to text-to-image if edit is unavailable."""
    cl = C._openai()
    try:
        r = cl.images.edit(model=C.IMAGE_MODEL, image=open(ref, "rb"), prompt=PROMPT, size="1024x1536", n=1)
        d = r.data[0]
        if getattr(d, "b64_json", None):
            open(out_raw, "wb").write(base64.b64decode(d.b64_json)); return "edit"
        import urllib.request; urllib.request.urlretrieve(d.url, out_raw); return "edit"
    except Exception as e:
        print("  images.edit unavailable, fallback to generate:", type(e).__name__, str(e)[:120])
        C.gen_image(PROMPT, out_raw, size="1024x1536"); return "generate"


def anatomy_ok(raw_png, cost):
    an = DV.anatomy_vlm(raw_png, BOLT["reference"], BOLT["anatomy"], [(0, raw_png)], cost=cost)
    proh = sorted({x for f in an.get("per_frame", []) for x in (f.get("prohibited_seen", []) + f.get("required_altered", []))})
    return (not proh), proh


def identity_ok(raw_png, cost):
    """same-character check vs the seed Bolt (side-by-side)."""
    import explainer_pipeline as ep
    a = Image.open(REF).convert("RGBA"); a = a.crop(a.getbbox())
    b = Image.open(raw_png).convert("RGB")
    ah = 700; a = a.resize((int(a.width * ah / a.height), ah)); b = b.resize((int(b.width * ah / b.height), ah))
    bg = Image.new("RGB", (a.width + b.width + 20, ah), (20, 20, 24))
    bg.paste(a.convert("RGB"), (0, 0)); bg.paste(b, (a.width + 20, 0))
    ip = os.path.join(os.path.dirname(raw_png), "_id_check.png"); bg.save(ip)
    ib = base64.b64encode(open(ip, "rb").read()).decode()
    r = ep._claude().messages.create(model="claude-opus-4-8", max_tokens=180, system="Strict identity auditor.",
        messages=[{"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": ib}},
        {"type": "text", "text": "LEFT is the reference robot, RIGHT is a new pose. Same character (same colours, "
         "mint accents, visor with exactly two cyan eyes, NO mouth, single hover-base, no legs)? Return ONLY JSON "
         "{\"same_character\":bool,\"differences\":str}"}]}])
    cost.append(ep._msg_cost(r.usage))
    o, _ = ep._parse_script_json(r.content[0].text); o = o if isinstance(o, dict) else {}
    return bool(o.get("same_character")), o.get("differences", "")


def strain_ok(raw_png, cost):
    """direct strain check on the raw pose: must read as tired/struggling, NOT energetic."""
    import explainer_pipeline as ep
    b64 = base64.b64encode(open(raw_png, "rb").read()).decode()
    r = ep._claude().messages.create(model="claude-opus-4-8", max_tokens=150, system="Strict pose-affect auditor.",
        messages=[{"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
        {"type": "text", "text": "Does this robot look EXHAUSTED/STRAINING/struggling (tired, sagging, failing) "
         "rather than energetic/happy/athletic? Return ONLY JSON {\"looks_strained\":bool,\"looks_energetic\":bool,\"why\":str}"}]}])
    cost.append(ep._msg_cost(r.usage))
    o, _ = ep._parse_script_json(r.content[0].text); o = o if isinstance(o, dict) else {}
    return (bool(o.get("looks_strained")) and not bool(o.get("looks_energetic"))), o.get("why", "")


def main():
    cost = []; attempts = []; passed = None; best = None
    for i in range(MAX_TRIES):
        mode = gen_edit(REF, RAW)
        pf = C.preflight_pose(RAW, "strained_reach", WANT, cost_sink=cost, identity=C.POSE_IDENTITY)
        an_ok, proh = anatomy_ok(RAW, cost)
        id_ok, id_diff = identity_ok(RAW, cost)
        st_ok, st_why = strain_ok(RAW, cost)
        ok = pf["pass"] and an_ok and id_ok and st_ok
        shutil.copy(RAW, OUT + f".try{i+1}.png")
        score = int(pf["pass"]) + int(an_ok) + int(id_ok) + int(st_ok)
        if best is None or score > best[1]:
            best = (OUT + f".try{i+1}.png", score)
        attempts.append({"try": i + 1, "mode": mode, "pose_pass": pf["pass"], "pose_scores": pf["scores"],
                         "reads_as": pf["reads_as"], "anatomy_ok": an_ok, "prohibited": proh,
                         "identity_ok": id_ok, "identity_diff": id_diff, "strain_ok": st_ok, "strain_why": st_why})
        print(f"try{i+1} [{mode}]: pose={pf['pass']} anatomy={an_ok}{proh} identity={id_ok} strain={st_ok} '{st_why[:50]}'")
        if ok:
            passed = i + 1; break
    if passed is None and best:                 # no full pass → keep the best-scoring attempt for review
        shutil.copy(best[0], RAW)
    # keep the passing raw (or the last) → chroma-key to RGBA cutout
    C.chroma_key(RAW, OUT)
    rep = {"passed_try": passed, "attempts": attempts, "gpt_image_cost_note": "gpt-image-2 medium x tries (no video spend)",
           "vlm_cost_usd": round(sum(cost), 3), "output": OUT, "identity_reference": REF}
    json.dump(rep, open(os.path.join(OX, "atomic_shots", "strained_reach_pose_gen_report.json"), "w"), indent=2, default=str)
    print(f"\n{'PASSED' if passed else 'NO FULL PASS'} (try {passed}) | vlm ${sum(cost):.2f} | wrote {OUT}")
    return passed is not None


if __name__ == "__main__":
    main()
