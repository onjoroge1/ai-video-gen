"""Buy the five Kling 3 Pro clips for spec/four_pests_sparrows_short_beat_sheet.md on fal.ai.

Uses the directed adapter's submit/download path (bolt_seq/providers/directed_video.py), so each
still is fitted to 1080x1920 and the request carries Kling v3's start_image_url + end_image_url
with audio off. Every downloaded candidate is conformed to 1080x1920/30fps and then gated:

  * motion   -- real change between frames (whole-frame mean |diff| OR sustained local movement),
                the same two-measure test sim/animate.py uses, so a near-still is never accepted;
  * drift    -- the camera is locked in every clip of this Short, so a global first-to-last shift
                beyond a few pixels fails the candidate;
  * arrival  -- the last frame must resemble the END still more than the START still does, or the
                end-frame conditioning did not take.

A failing candidate buys one more (max 2 per clip). A hard USD cap is checked before every submit.

Authorization: the operator asked for exactly this run in chat on 2026-09-22 with an $8.00 cap.
ALLOW_PAID is flipped for this process only; the module default stays False.

    python3 scripts/four_pests_clips.py            # buy what is missing
    python3 scripts/four_pests_clips.py --dry-run  # print the sanitized payloads and the estimate
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(usecwd=True))

import numpy as np                                             # noqa: E402
from PIL import Image                                          # noqa: E402
import fal_models                                              # noqa: E402
from bolt_seq.providers import directed_video as DV            # noqa: E402

STILLS = os.path.join(ROOT, "renders", "four_pests", "stills")
OUT = os.path.join(ROOT, "renders", "four_pests", "clips")
MODEL = "kling-v3-pro"
HARD_CAP_USD = 8.00
MAX_CANDIDATES = 2
POLL_TIMEOUT_S = 900

NEGATIVE = ("text, letters, numbers, watermark, logo, cartoon, anime, modern clothing, cars, "
            "power lines, extra limbs, deformed birds, duplicate people, camera shake, flicker, cuts")

BEATS = [
    {"id": "b1", "duration": 5,
     "prompt": "Locked camera, no camera movement. The sky full of sparrows thins out over five "
               "seconds as the birds scatter and drop, until only three remain, one falling with "
               "folded wings. The villagers on the rooftops keep their pots and poles raised and do "
               "not move. Painted documentary illustration look, film grain, no cuts."},
    {"id": "b2", "duration": 5,
     "prompt": "Locked camera, no camera movement. The single sparrow above the boy circles lower "
               "and slower, wings ragged, until it drops and lies still on the packed earth at his "
               "feet. The boy keeps beating the pot with the stick throughout. Painted documentary "
               "illustration look, film grain, no cuts."},
    {"id": "b3", "duration": 10,
     "prompt": "Locked macro camera, no camera movement. The sparrow swallows the green locust "
               "nymph, looks up, and flies out of the top of the frame. Then locusts climb the empty "
               "wheat stalk one after another until it is covered with them, and more appear in the "
               "blurred field behind. Slow and continuous. Painted documentary illustration look, "
               "film grain, no cuts."},
    {"id": "b4", "duration": 5,
     "prompt": "Locked camera, no camera movement. A dark locust swarm rolls in from the top of the "
               "frame like weather. Beneath it the green millet field turns to brown stubble. The "
               "farmer takes off his straw hat and holds it against his chest. Painted documentary "
               "illustration look, film grain, no cuts."},
    {"id": "b5", "duration": 5,
     "prompt": "Locked camera, no camera movement. The hand with the brush paints a wet red cross "
               "through the sparrow icon on the board, then paints a small bed bug beneath it, and "
               "pulls back to the edge of the frame. Above the board, the dusk sky fills with "
               "hundreds of small sparrows in flight. Painted documentary illustration look, film "
               "grain, no cuts."},
]


# ── gates ──────────────────────────────────────────────────────────────────────────────────────
def _gray_frames(path, w=192, h=340):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"scale={w}:{h}", "-f",
                          "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    n = len(raw) // (w * h)
    return np.frombuffer(raw[: n * w * h], dtype=np.uint8).reshape(n, h, w).astype(np.int16)


def clip_motion(path):
    g = _gray_frames(path)
    d = np.abs(np.diff(g, axis=0))
    peak = d.max(axis=(1, 2))
    return {"frames": int(len(g)), "per_frame_mean": round(float(d.mean(axis=(1, 2)).mean()), 2),
            "local_frac": round(float((peak > 30).mean()), 2),
            "first_vs_last": round(float(np.abs(g[0] - g[-1]).mean()), 2)}


def _shift(a, b, axis):
    pa, pb = a.mean(axis=axis), b.mean(axis=axis)
    pa, pb = pa - pa.mean(), pb - pb.mean()
    return int(np.argmax(np.correlate(pa, pb, mode="full")) - (len(pb) - 1))


def camera_drift(path, start_png, end_png):
    """Camera movement measured against the authored stills, not between the clip's own frames.

    Correlating the first frame with the last frame fails on exactly the shot this format is made
    of: clip 4's field changes texture everywhere while the camera holds, and the column profiles
    reported a 62 px pan that was not there. The stills define the intended camera, so the honest
    measure is: how does the first frame sit against the START still, how does the last frame sit
    against the END still, and do those two offsets differ. A constant offset is framing (the
    still is fitted and cropped before submission); a changing one is a moving camera.
    """
    g = _gray_frames(path, 240, 426).astype(np.float32)
    s = np.asarray(Image.open(start_png).convert("L").resize((240, 426)), dtype=np.float32)
    e = np.asarray(Image.open(end_png).convert("L").resize((240, 426)), dtype=np.float32)
    first = (_shift(g[0], s, 0), _shift(g[0], s, 1))
    last = (_shift(g[-1], e, 0), _shift(g[-1], e, 1))
    return {"dx": last[0] - first[0], "dy": last[1] - first[1],
            "first_vs_start": first, "last_vs_end": last,
            "first_vs_last_naive": _shift(g[0], g[-1], 0)}


def _still_gray(path, w=192, h=340):
    return np.asarray(Image.open(path).convert("L").resize((w, h)), dtype=np.int16)


def arrival(path, start_png, end_png):
    """Does the clip's last frame land closer to the END still than the START still does?"""
    g = _gray_frames(path)
    last = g[-1]
    s, e = _still_gray(start_png), _still_gray(end_png)
    to_end, to_start = float(np.abs(last - e).mean()), float(np.abs(last - s).mean())
    baseline = float(np.abs(s - e).mean())               # how different the stills are anyway
    return {"last_to_end": round(to_end, 2), "last_to_start": round(to_start, 2),
            "still_gap": round(baseline, 2),
            "arrived": bool(to_end < to_start) if baseline > 4 else True}


def gate(path, start_png, end_png):
    m, d, a = clip_motion(path), camera_drift(path, start_png, end_png), arrival(path, start_png, end_png)
    reasons = []
    if not (m["per_frame_mean"] >= 0.45 or m["local_frac"] >= 0.55):
        reasons.append(f"near-still: mean {m['per_frame_mean']} local {m['local_frac']}")
    if abs(d["dx"]) > 6 or abs(d["dy"]) > 6:
        reasons.append(f"camera drift dx={d['dx']} dy={d['dy']}")
    if not a["arrived"]:
        reasons.append(f"did not arrive at end frame ({a['last_to_end']} vs {a['last_to_start']})")
    return {"motion": m, "drift": d, "arrival": a, "accepted": not reasons, "reasons": reasons}


# ── run ────────────────────────────────────────────────────────────────────────────────────────
def _spec(beat):
    return {"model": MODEL, "prompt": beat["prompt"], "negative_prompt": NEGATIVE,
            "duration": beat["duration"], "generate_audio": False, "cfg_scale": 0.5,
            "seed_image": os.path.join(STILLS, f"{beat['id']}_start.png"),
            "end_image": os.path.join(STILLS, f"{beat['id']}_end.png"),
            "resolution": None, "aspect_ratio": "9:16"}


def regate():
    """Re-run the gates on every downloaded candidate, free. Used after a gate is corrected so a
    clip already paid for is judged by the fixed measure rather than bought again."""
    mpath = os.path.join(OUT, "manifest.json")
    manifest = json.load(open(mpath))
    for bid, rec in manifest["clips"].items():
        rec["accepted"] = None
        for cand in rec["candidates"]:
            if not cand.get("conformed") or not os.path.exists(cand["conformed"]):
                continue
            spec = _spec(next(b for b in BEATS if b["id"] == bid))
            cand["gate"] = gate(cand["conformed"], spec["seed_image"], spec["end_image"])
            cand["gate"]["regated_at"] = time.time()
            if cand["gate"]["accepted"] and not rec["accepted"]:
                rec["accepted"] = cand["conformed"]
            print(f"  {'PASS' if cand['gate']['accepted'] else 'FAIL'}  {bid} c{cand['n']}  "
                  f"{'; '.join(cand['gate']['reasons'] or ['ok'])}  drift={cand['gate']['drift']['dx']},{cand['gate']['drift']['dy']}")
    json.dump(manifest, open(mpath, "w"), indent=2)
    accepted = [k for k, v in manifest["clips"].items() if v["accepted"]]
    print(f"\naccepted {len(accepted)}/{len(BEATS)} after regate; spent so far ${manifest['usd_spent']:.2f}")


def main(dry_run=False):
    os.makedirs(OUT, exist_ok=True)
    mpath = os.path.join(OUT, "manifest.json")
    manifest = json.load(open(mpath)) if os.path.exists(mpath) else {"model": MODEL, "clips": {}, "usd_spent": 0.0}
    est = sum(fal_models.estimate_clip_usd(MODEL, b["duration"]) for b in BEATS)
    print(f"{len(BEATS)} clips on {fal_models.resolve(MODEL)}; first-candidate estimate ${est:.2f}; "
          f"hard cap ${HARD_CAP_USD:.2f}; already spent ${manifest['usd_spent']:.2f}")
    if dry_run:
        for b in BEATS:
            body = DV.build_fal_payload(_spec(b), fal_models.resolve(MODEL), lambda p: f"<{os.path.basename(p)}>")
            print(f"\n[{b['id']}] {json.dumps(body, indent=1)}")
        return

    DV.ALLOW_PAID = True                       # this process only; see the module docstring
    adapter = DV.FalKlingAdapter()
    pending = {}
    for b in BEATS:
        rec = manifest["clips"].setdefault(b["id"], {"candidates": [], "accepted": None})
        if rec["accepted"]:
            print(f"  skip  {b['id']} (accepted: {os.path.basename(rec['accepted'])})"); continue
        if len(rec["candidates"]) >= MAX_CANDIDATES:
            print(f"  stop  {b['id']} already has {MAX_CANDIDATES} candidates, none accepted"); continue
        cost = fal_models.estimate_clip_usd(MODEL, b["duration"])
        if manifest["usd_spent"] + cost > HARD_CAP_USD:
            print(f"  CAP   {b['id']}: ${manifest['usd_spent']:.2f} + ${cost:.2f} > ${HARD_CAP_USD:.2f}"); continue
        job = adapter.submit(_spec(b), timeout=60)
        manifest["usd_spent"] = round(manifest["usd_spent"] + cost, 4)   # billed on generation
        n = len(rec["candidates"]) + 1
        cand = {"n": n, "request_id": job["request_id"], "endpoint": job["endpoint"],
                "payload": job["submitted_payload_sanitized"], "usd": cost, "submitted_at": time.time()}
        rec["candidates"].append(cand)
        json.dump(manifest, open(mpath, "w"), indent=2)
        pending[b["id"]] = (b, job, cand)
        print(f"  sent  {b['id']} candidate {n}  request {job['request_id']}  ${cost:.2f}", flush=True)

    for bid, (b, job, cand) in pending.items():
        raw = os.path.join(OUT, f"{bid}_c{cand['n']}.raw.mp4")
        conformed = os.path.join(OUT, f"{bid}_c{cand['n']}.mp4")
        try:
            adapter.poll_and_download(job, raw, timeout=POLL_TIMEOUT_S)
            DV._normalize_media(raw, conformed)
            result = gate(conformed, _spec(b)["seed_image"], _spec(b)["end_image"])
        except Exception as exc:                         # provider failure is a failed candidate
            result = {"accepted": False, "reasons": [f"provider/gate error: {exc}"[:200]]}
        cand.update({"raw": raw, "conformed": conformed, "gate": result, "done_at": time.time()})
        if result["accepted"]:
            manifest["clips"][bid]["accepted"] = conformed
        json.dump(manifest, open(mpath, "w"), indent=2)
        tag = "PASS" if result["accepted"] else "FAIL"
        print(f"  {tag}  {bid} c{cand['n']}  {'; '.join(result.get('reasons') or ['ok'])}", flush=True)

    accepted = [k for k, v in manifest["clips"].items() if v["accepted"]]
    print(f"\naccepted {len(accepted)}/{len(BEATS)}; spent ${manifest['usd_spent']:.2f}; manifest {mpath}")
    if len(accepted) < len(BEATS):
        print("re-run to buy a second candidate for the failed clips (max 2 per clip, cap applies)")


if __name__ == "__main__":
    if "--regate" in sys.argv:
        regate()
    else:
        main(dry_run="--dry-run" in sys.argv)
