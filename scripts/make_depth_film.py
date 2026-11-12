#!/usr/bin/env python3
"""Build a Depth-format film (or opening) from a JSON shot list. See docs/DEPTH_FILM_FORMAT.md.

  python scripts/make_depth_film.py SPEC check        # times resolve, cards only say spoken words  ($0)
  python scripts/make_depth_film.py SPEC plan         # what is missing and what it would cost      ($0)
  python scripts/make_depth_film.py SPEC stills       # buy missing stills (gpt-image-2)           (paid)
  python scripts/make_depth_film.py SPEC clips        # buy missing I2V clips (fal)                 (paid)
  python scripts/make_depth_film.py SPEC frames       # contact sheet only                          ($0)
  python scripts/make_depth_film.py SPEC render [--sbs]   # <name>.mp4 (+ side_by_side.mp4)         ($0)
  python scripts/make_depth_film.py SPEC join         # spec's "prepend" cut + <name>.mp4, full source audio ($0)

Paid steps refuse to start when ledger.jsonl spend plus the planned purchases would pass the
spec's cap_usd. Existing stills/clips are never re-bought unless named with --force.
"""
import argparse
import base64
import io
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import depth_film as df  # noqa: E402

STILL_USD = 0.21          # gpt-image-2 high, 1536x1024, measured
CLIP_MODEL = "kling-v3-pro"
CLIP_NEG = "text, letters, watermark, extra limbs, extra legs, deformed animal, visible face of the hiker, camera shake, morphing, cuts"


def env():
    from dotenv import load_dotenv
    load_dotenv(os.environ.get("REELFORGE_ENV", os.path.expanduser("~/ai-video-gen-local/.env")))


def ledger_path(r):
    return os.path.join(r.base, "ledger.jsonl")


def spent(r):
    p = ledger_path(r)
    if not os.path.exists(p):
        return 0.0
    return sum(json.loads(l).get("est_usd", 0) for l in open(p) if l.strip())


def log_spend(r, rec):
    with open(ledger_path(r), "a") as f:
        f.write(json.dumps({"t": time.time(), **rec}) + "\n")


def clip_usd(seconds=5):
    import fal_models
    return fal_models.estimate_clip_usd(fal_models.resolve(CLIP_MODEL), seconds)


def missing(r, kind, force=()):
    if kind == "stills":
        items = r.spec.get("stills", {})
        return [n for n in items if n in force or not os.path.exists(r.path("@" + n))]
    items = r.spec.get("clips", {})
    return [n for n in items if n in force or not os.path.exists(r.clip_path(n))]


def plan(r, force=()):
    ms, mc = missing(r, "stills", force), missing(r, "clips", force)
    cost = len(ms) * STILL_USD + len(mc) * clip_usd()
    cap = float(r.spec.get("cap_usd", 0))
    print(f"stills missing: {len(ms)} {ms}")
    print(f"clips missing:  {len(mc)} {mc}")
    print(f"planned ${cost:.2f} + spent ${spent(r):.2f} = ${cost + spent(r):.2f} against cap ${cap:.2f}")
    return ms, mc, cost


def guard(r, cost):
    cap = float(r.spec.get("cap_usd", 0))
    if spent(r) + cost > cap + 1e-9:
        raise SystemExit(f"refused: ${spent(r):.2f} spent + ${cost:.2f} planned passes cap ${cap:.2f}")


def fill(r, text):
    return text.format_map(r.spec.get("vars", {}))


def buy_still(r, name):
    from openai import OpenAI
    s = r.spec["stills"][name]
    prompt = fill(r, s["prompt"])
    c = OpenAI(timeout=300)
    refs = [open(r.path(x), "rb") for x in s.get("refs", [])]
    if refs:
        res = c.images.edit(model="gpt-image-2", image=refs if len(refs) > 1 else refs[0], prompt=prompt,
                            size="1536x1024", quality="high")
    else:
        res = c.images.generate(model="gpt-image-2", prompt=prompt, size="1536x1024", quality="high")
    out = r.path("@" + name)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "wb").write(base64.b64decode(res.data[0].b64_json))
    json.dump({"prompt": prompt, "refs": s.get("refs", [])}, open(out[:-4] + ".json", "w"), indent=1)
    log_spend(r, {"kind": "image", "name": name, "est_usd": STILL_USD, "usage": str(getattr(res, "usage", None))})
    return name


def buy_clip(r, name):
    import requests
    from PIL import Image
    import fal_models
    c = r.spec["clips"][name]
    im = Image.open(r.path(c["image"])).convert("RGB")
    b = io.BytesIO(); im.save(b, "JPEG", quality=92)
    uri = "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()
    ep = fal_models.resolve(c.get("model", CLIP_MODEL))
    secs = c.get("seconds", 5)
    body = fal_models.build_i2v_body(ep, prompt=fill(r, c["prompt"]), image_url=uri, seconds=secs,
                                     negative_prompt=c.get("negative", CLIP_NEG), audio=False)
    hdr = {"Authorization": f"Key {os.environ['FAL_KEY']}"}
    sub = requests.post(f"https://queue.fal.run/{ep}", headers=hdr, json=body, timeout=60)
    if sub.status_code not in (200, 201):
        raise RuntimeError(f"{name}: fal submit {sub.status_code}: {sub.text[:160]}")
    j = sub.json()
    log_spend(r, {"kind": "clip", "name": name, "model": ep, "est_usd": fal_models.estimate_clip_usd(ep, secs),
                  "request_id": j.get("request_id")})
    for _ in range(150):
        time.sleep(6)
        st = requests.get(j["status_url"], headers=hdr, timeout=30).json().get("status")
        if st == "COMPLETED":
            break
        if st in ("FAILED", "ERROR"):
            raise RuntimeError(f"{name}: fal {st}")
    else:
        raise RuntimeError(f"{name}: fal timeout")
    res = requests.get(j["response_url"], headers=hdr, timeout=30).json()
    out = r.clip_path(name)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "wb").write(requests.get(res["video"]["url"], timeout=180).content)
    return name


def buy(r, kind, names):
    """Stills that reference other stills (refs "@x") wait for them: buy in dependency waves."""
    fn = buy_still if kind == "stills" else buy_clip
    todo = list(names)
    while todo:
        if kind == "stills":
            wave = [n for n in todo if not any(x[1:] in todo for x in r.spec["stills"][n].get("refs", []) if x.startswith("@"))]
            if not wave:
                raise SystemExit(f"circular still references among {todo}")
        else:
            wave = todo
        with ThreadPoolExecutor(5) as ex:
            for fut in [ex.submit(fn, r, n) for n in wave]:
                try:
                    print("ok", fut.result(), flush=True)
                except Exception as e:  # one failed purchase must not lose the others
                    print("FAILED", e, flush=True)
        todo = [n for n in todo if n not in wave]


def join(r, name):
    """Prepend a finished opening (an accepted pilot) without re-encoding it, then lay the film's own
    unbroken audio over the joined picture, so neither cut's fade lands at the seam."""
    import subprocess
    first = os.path.normpath(os.path.join(r.base, r.spec["prepend"]))
    rest = os.path.join(r.base, name + ".mp4")
    seam = df.media_duration(first)
    if abs(seam - r.start) > 0.05:
        raise SystemExit(f"refused: {first} runs {seam:.3f}s but this cut starts at {r.start:.3f}s")
    lst = os.path.join(r.base, "join.txt")
    with open(lst, "w") as f:
        f.write(f"file '{first}'\nfile '{rest}'\n")
    out = os.path.join(r.base, name + "_full.mp4")
    src = os.path.join(r.job, r.spec["audio"]["source"])
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-i", src,
                    "-map", "0:v", "-map", "1:a", "-c", "copy", "-t", f"{r.end:.3f}", "-movflags", "+faststart", out], check=True)
    os.remove(lst)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec")
    ap.add_argument("cmd", choices=("check", "plan", "stills", "clips", "frames", "render", "join"))
    ap.add_argument("--force", nargs="*", default=[], help="re-buy these stills/clips")
    ap.add_argument("--sbs", action="store_true", help="also write side_by_side.mp4 against audio.source")
    ap.add_argument("--allow-unspoken", action="store_true", help="skip the spoken-words card rule (operator only)")
    a = ap.parse_args(argv)

    r = df.load(a.spec)
    problems = r.check_cards()
    if a.cmd == "check":
        for s in r.shots:
            print(f"{s['t0']:6.2f}-{s['t1']:6.2f}  {s['name']}")
        print("\n".join(problems) or "cards: every word is spoken nearby")
        gaps = r.check_presence()
        if not any(s["shows"] is not None for s in r.shots):
            print('presence: not checked (no shot has a "shows" list)')
        else:
            print("\n".join(gaps) or "presence: the animal and YOU stay on screen")
        return 1 if problems or gaps else 0
    if problems and not a.allow_unspoken and a.cmd in ("frames", "render"):
        print("\n".join(problems)); return 1
    if a.cmd == "plan":
        plan(r, a.force); return 0
    if a.cmd in ("stills", "clips"):
        env()
        names = missing(r, a.cmd, a.force)
        cost = len(names) * (STILL_USD if a.cmd == "stills" else clip_usd())
        guard(r, cost)
        buy(r, a.cmd, names)
        print(f"spent so far ${spent(r):.2f} of cap ${float(r.spec.get('cap_usd', 0)):.2f}")
        return 0
    name = r.spec.get("name", "depth")
    if a.cmd == "join":
        print("wrote", join(r, name)); return 0
    sheet = r.contact_sheet(os.path.join(r.base, "contact_sheet.jpg"))
    print("wrote", sheet)
    if a.cmd == "render":
        out = r.render(os.path.join(r.base, name + ".mp4"))
        print("wrote", out)
        if a.sbs:
            print("wrote", r.side_by_side(out, os.path.join(r.base, "side_by_side.mp4")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
