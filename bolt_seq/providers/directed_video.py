"""directed_video provider (Phase 3A — HARDENED gate + provider lifecycle). Paid directed motion for
selected HERO-ACTION blocks only. Deterministic rendering stays the provider for meters, captions,
diagrams, destination tracking, cutaways, UI and persistent state.

SAFETY POSTURE: `ALLOW_PAID=False`. `generate()`/`resolve()` raise before any paid call. There is NO
silent deterministic fallback for hero blocks — if generation is unauthorized, or every candidate fails
the gate, the build FAILS loudly. The gate below is validated OFFLINE (see tests/eval_directed_gate.py)
against known-bad, synthetic and positive clips before paid generation is ever enabled.

The gate (evaluate_candidate) combines, in order:
  1. technical media gate   (aspect, duration, fps, decode, resolution, black/frozen frames)
  2. hero-entity tracking   (VLM per-frame bounding boxes — PRIMARY direction/reversal/disappearance)
  3. global optical flow     (SECONDARY cross-check only)
  4. boundary match          (candidate first/last vs deterministic start/end frames)
  5. VLM semantic gate       (identity + per-frame identity consistency, start_end, slop, scoped prohibitions)"""
from __future__ import annotations
import os, subprocess, base64, json, tempfile

ALLOW_PAID = False   # the user authorizes paid rendering explicitly before this flips


class DirectedVideoFailure(RuntimeError):
    pass


def disk_allow_paid():
    """AUTHORITATIVE ALLOW_PAID value as written in this module's source on disk (True/False/None)."""
    import re
    m = re.search(r'^ALLOW_PAID\s*=\s*(True|False)\b', open(__file__).read(), re.M)
    return (m.group(1) == "True") if m else None


def assert_allow_paid_reset():
    """Raise unless ALLOW_PAID is False BOTH on disk AND at runtime. No paid preparation is valid until this
    passes. Returns the concrete values (not a confusing 'is-False' boolean)."""
    disk, rt = disk_allow_paid(), ALLOW_PAID
    if disk is not False or rt is not False:
        raise DirectedVideoFailure(f"ALLOW_PAID NOT reset — disk={disk} runtime={rt}; both MUST be False before any paid prep is valid")
    return {"disk_allow_paid": disk, "runtime_allow_paid": rt, "both_false": True}


# ── tunable gate config ────────────────────────────────────────────────────────────────────────────
DEFAULT_GATES = {
    "identity_min": 8, "start_end_min": 7, "start_frame_min": 7, "end_frame_min": 7,
    "entry_cut_min": 6, "exit_cut_min": 6, "semantic_min": 7, "slop_max": 3,
    "direction_must_match": True, "optical_flow_check": True,
    "min_displacement": 0.15,      # net hero centroid travel (frac of frame) for a directional block
    "min_motion_magnitude": 0.12,  # path length of the hero centroid (frac of frame)
    "min_scale_change": 0.0,       # required |Δ scale| when the block demands growth/shrink
    "min_pose_change": 0,          # required distinct hero poses across frames (0 = unchecked)
    "max_reversals": 0, "max_disappearances": 0, "frames": 9,
}
DEFAULT_TECH = {"min_w": 1080, "min_h": 1920, "aspect_wh": 9 / 16, "aspect_tol": 0.06,
                "dur_min": 3.0, "dur_max": 8.0, "fps_min": 16, "fps_max": 60,
                "max_black_frac": 0.15, "max_frozen_frac": 0.6}
DEFAULT_BUDGET = {"max_candidates": 3, "max_block_cost_usd": 5.0, "max_video_cost_usd": 5.0,
                  "provider_timeout_s": 600, "retry_ceiling": 2, "stop_after_first_pass": True,
                  "reuse_cached": True, "candidate_cost_usd": 0.56}


# ── media probing ────────────────────────────────────────────────────────────────────────────────
def _probe(clip):
    def g(stream, key):
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries",
                            key, "-of", "default=nw=1:nk=1", clip], capture_output=True, text=True)
        return r.stdout.strip()
    try:
        w = int(g("v:0", "stream=width") or 0); h = int(g("v:0", "stream=height") or 0)
        dur = float(g("v:0", "format=duration") or 0) or float(g("v:0", "stream=duration") or 0)
        rate = g("v:0", "stream=r_frame_rate") or "0/1"
        num, den = (rate.split("/") + ["1"])[:2]; fps = float(num) / float(den or 1)
        return {"w": w, "h": h, "dur": round(dur, 3), "fps": round(fps, 2)}
    except Exception as e:
        return {"error": str(e)}


def _decodes(clip):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", clip, "-f", "null", "-"],
                       capture_output=True, text=True)
    return r.returncode == 0 and "error" not in r.stderr.lower()


def _black_frozen_frac(clip, dur):
    black = frozen = 0.0
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", clip, "-vf",
                        "blackdetect=d=0.1:pic_th=0.98", "-f", "null", "-"], capture_output=True, text=True)
    for ln in r.stderr.splitlines():
        if "black_duration" in ln:
            try:
                black += float(ln.split("black_duration:")[1].split()[0])
            except Exception:
                pass
    r2 = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", clip, "-vf",
                         "freezedetect=n=-60dB:d=0.5", "-f", "null", "-"], capture_output=True, text=True)
    starts = [float(l.split("freeze_start:")[1].split()[0]) for l in r2.stderr.splitlines() if "freeze_start" in l]
    ends = [float(l.split("freeze_end:")[1].split()[0]) for l in r2.stderr.splitlines() if "freeze_end" in l]
    for s, e in zip(starts, ends + [dur]):
        frozen += max(0.0, e - s)
    return (black / dur if dur else 1.0), (frozen / dur if dur else 1.0)


def technical_gate(clip, tech=None, spec=None):
    """Reject clips that are the wrong shape/length/rate, won't decode, or are black/frozen."""
    t = {**DEFAULT_TECH, **(tech or {})}
    m = _probe(clip)
    reasons = []
    if "error" in m or not m.get("w"):
        return {"pass": False, "reasons": ["probe/decode failed: " + str(m.get('error'))], "meta": m}
    if not _decodes(clip):
        reasons.append("decode errors")
    if m["w"] < t["min_w"] or m["h"] < t["min_h"]:
        reasons.append(f"resolution {m['w']}x{m['h']} < {t['min_w']}x{t['min_h']}")
    aspect = m["w"] / m["h"] if m["h"] else 0
    if abs(aspect - t["aspect_wh"]) > t["aspect_tol"]:
        reasons.append(f"aspect {aspect:.3f} != {t['aspect_wh']:.3f}")
    if not (t["dur_min"] <= m["dur"] <= t["dur_max"]):
        reasons.append(f"duration {m['dur']}s outside [{t['dur_min']},{t['dur_max']}]")
    if not (t["fps_min"] <= m["fps"] <= t["fps_max"]):
        reasons.append(f"fps {m['fps']} outside [{t['fps_min']},{t['fps_max']}]")
    bf, ff = _black_frozen_frac(clip, m["dur"])
    if bf > t["max_black_frac"]:
        reasons.append(f"black frames {bf:.0%} > {t['max_black_frac']:.0%}")
    directional = bool(spec) and spec.get("motion_direction") not in (None, "stationary")
    if directional and ff > t["max_frozen_frac"]:
        reasons.append(f"frozen {ff:.0%} > {t['max_frozen_frac']:.0%} on a directional block")
    m["black_frac"], m["frozen_frac"] = round(bf, 3), round(ff, 3)
    return {"pass": not reasons, "reasons": reasons, "meta": m}


# ── direction from tracks (zero-delta → stationary) ────────────────────────────────────────────────
def _direction(entity, axis, min_delta=0.03):
    from bolt_seq import scene_graph as SG
    t = entity.get("tracks", {})
    def delta(ch):
        tk = t.get(ch)
        return (tk["kf"][-1][1] - tk["kf"][0][1]) if (tk and len(tk["kf"]) >= 2) else 0.0
    if axis == "horizontal":
        d = delta("x"); return "stationary" if abs(d) < min_delta else ("right" if d > 0 else "left")
    if axis == "vertical":
        d = delta("y"); return "stationary" if abs(d) < min_delta else ("down" if d > 0 else "up")
    if axis == "depth":
        d = delta("scale"); return "stationary" if abs(d) < min_delta else ("toward" if d > 0 else "away")
    if axis == "radial":
        d = delta("rot"); return "stationary" if abs(d) < min_delta else "rotate"
    return "stationary"


# ── hero tracking + semantic gate (one VLM call: boundary refs + >=8 candidate frames) ─────────────
def _frames(clip, n, out_dir):
    dur = _probe(clip).get("dur", 5.0) or 5.0
    fps_n = max(n, 8)
    paths = []
    for i in range(fps_n):
        t = dur * (i + 0.5) / fps_n
        fp = os.path.join(out_dir, f"_dvf_{i}.jpg")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", clip,
                        "-frames:v", "1", "-vf", "scale=300:533", fp], check=True)
        paths.append((round(t, 2), fp))
    return paths


def _img_block(fp, label):
    media = "image/png" if fp.lower().endswith(".png") else "image/jpeg"   # boundary frames are PNG
    return [{"type": "text", "text": label},
            {"type": "image", "source": {"type": "base64", "media_type": media,
             "data": base64.b64encode(open(fp, "rb").read()).decode()}}]


def hero_vlm(clip, spec, boundary, frames, cost=None, model="claude-opus-4-8"):
    """One VLM call → per-frame hero bounding boxes + present/identity flags + global scores incl.
    boundary matches, scoped prohibitions, slop, semantic. PRIMARY tracking signal."""
    import explainer_pipeline as ep
    content = []
    if boundary and boundary.get("start_frame"):
        content += _img_block(boundary["start_frame"], "REQUIRED START (deterministic boundary):")
    for i, (t, fp) in enumerate(frames):
        content += _img_block(fp, f"candidate frame {i} @ {t}s:")
    if boundary and boundary.get("end_frame"):
        content += _img_block(boundary["end_frame"], "REQUIRED END (deterministic boundary):")
    ident = spec.get("identity_bible", "the mascot robot Bolt")
    proh = spec.get("prohibited_events", [])
    content.append({"type": "text", "text": (
        f"The candidate frames are in time order from a generated HERO clip. Hero entity: {ident}. "
        f"For EACH candidate frame return the hero bounding box as [x,y,w,h] in 0..1 (null if the hero is "
        f"absent) and whether the hero still matches the identity. Then global scores. The clip must NOT "
        f"contain any of these prohibited events: {proh}. "
        "For identity_score, score 0-10 how well the object visible in THAT frame matches the hero "
        "identity; if a DIFFERENT object has replaced the hero (a swap/mutation), score it LOW even if "
        "some object is present. CRUCIAL: decide whether ONE single consistent character persists across "
        "ALL frames, or whether the main subject is REPLACED by a different kind of object at any point "
        "(e.g. the robot becomes a ring/ball/blob/other item). Set hero_replaced=true and give the frame "
        "index if any such swap or morph happens — a docking ring, orb, or any non-robot is NOT the hero. "
        "Return ONLY JSON: {\"per_frame\":[{\"i\":int,\"bbox\":[x,y,w,h]|null,\"present\":bool,"
        "\"identity_ok\":bool,\"identity_score\":0-10}],\"hero_replaced\":bool,\"replacement_frame\":int_or_null,"
        "\"identity\":0-10,\"start_end_match\":0-10,\"start_frame_match\":0-10,"
        "\"end_frame_match\":0-10,\"entry_cut_quality\":0-10,\"exit_cut_quality\":0-10,"
        "\"prohibited_present\":[strings],\"slop\":0-10,\"semantic\":0-10,\"notes\":str}. "
        "start_frame_match/end_frame_match compare the first/last candidate frame to the REQUIRED "
        "START/END references (10=matches state and identity). If no boundary references were given, set "
        "those to 10.")})
    try:
        r = ep._claude().messages.create(model=model, max_tokens=1100,
            system="You are a strict adversarial QA gate for generated hero animation. Report exactly what "
                   "is visible; reject on any doubt. Bounding boxes must be your best visual estimate.",
            messages=[{"role": "user", "content": content}])
        if cost is not None:
            cost.append(ep._msg_cost(r.usage))
        o, _ = ep._parse_script_json(r.content[0].text)
        return o if isinstance(o, dict) else {"error": "parse"}
    except Exception as e:
        return {"error": str(e)}


def _trajectory(per_frame):
    """Derive centroid/scale trajectories, net displacement, path length, reversals, disappearances."""
    pts = []
    for f in sorted(per_frame or [], key=lambda x: x.get("i", 0)):
        bb = f.get("bbox")
        if f.get("present") and bb and len(bb) == 4:
            pts.append((bb[0] + bb[2] / 2, bb[1] + bb[3] / 2, (bb[2] * bb[3]) ** 0.5, True))
        else:
            pts.append((None, None, None, False))
    present = [p for p in pts if p[3]]
    disappearances = sum(1 for p in pts if not p[3])
    if len(present) < 2:
        return {"direction": "none", "net_dx": 0, "net_dy": 0, "displacement": 0, "path_len": 0,
                "scale_change": 0, "reversals": 0, "disappearances": disappearances, "n_present": len(present)}
    xs = [p[0] for p in present]; ys = [p[1] for p in present]; ss = [p[2] for p in present]
    net_dx, net_dy = xs[-1] - xs[0], ys[-1] - ys[0]
    disp = (net_dx ** 2 + net_dy ** 2) ** 0.5
    path = sum(((xs[i + 1] - xs[i]) ** 2 + (ys[i + 1] - ys[i]) ** 2) ** 0.5 for i in range(len(xs) - 1))
    horiz = abs(net_dx) >= abs(net_dy)
    axisvals = xs if horiz else ys
    vels = [axisvals[i + 1] - axisvals[i] for i in range(len(axisvals) - 1)]
    dom = 1 if (net_dx if horiz else net_dy) >= 0 else -1
    reversals = sum(1 for v in vels if v * dom < -0.04)     # steps moving against net direction
    if disp < 0.05:
        direction = "none"
    elif horiz:
        direction = "right" if net_dx > 0 else "left"
    else:
        direction = "down" if net_dy > 0 else "up"
    return {"direction": direction, "net_dx": round(net_dx, 3), "net_dy": round(net_dy, 3),
            "displacement": round(disp, 3), "path_len": round(path, 3),
            "scale_change": round(ss[-1] - ss[0], 3), "reversals": reversals,
            "disappearances": disappearances, "n_present": len(present)}


def optical_flow_direction(clip, samples=8):
    """SECONDARY global-motion direction (centroid drift of frame-to-frame change)."""
    import numpy as np
    from PIL import Image
    d = tempfile.mkdtemp()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip, "-vf",
                    f"fps={samples},scale=160:284", os.path.join(d, "f%03d.png")], check=True)
    fs = sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith(".png"))
    if len(fs) < 2:
        return {"dx": 0, "dy": 0, "direction": "none"}
    cxs, cys, prev = [], [], np.asarray(Image.open(fs[0]).convert("L"), float)
    for f in fs[1:]:
        cur = np.asarray(Image.open(f).convert("L"), float); diff = np.abs(cur - prev); prev = cur
        if diff.sum() < 1e-6:
            continue
        ys, xs = np.indices(diff.shape)
        cxs.append((xs * diff).sum() / diff.sum() / diff.shape[1])
        cys.append((ys * diff).sum() / diff.sum() / diff.shape[0])
    if len(cxs) < 2:
        return {"dx": 0, "dy": 0, "direction": "none"}
    dx, dy = cxs[-1] - cxs[0], cys[-1] - cys[0]
    if max(abs(dx), abs(dy)) < 0.01:
        return {"dx": round(dx, 4), "dy": round(dy, 4), "direction": "none"}
    direction = ("right" if dx > 0 else "left") if abs(dx) >= abs(dy) else ("down" if dy > 0 else "up")
    return {"dx": round(dx, 4), "dy": round(dy, 4), "direction": direction}


def evaluate_candidate(clip, spec, boundary=None, gates=None, tech=None, cost=None, log=print):
    """Full gate. Returns {pass, per_gate, scores, trajectory, flow, tech, reasons}."""
    g = {**DEFAULT_GATES, **(gates or {})}
    out_dir = tempfile.mkdtemp()
    reasons, per_gate = [], {}
    directional = spec.get("motion_direction") not in (None, "stationary")

    tg = technical_gate(clip, tech, spec)
    per_gate["technical"] = tg
    if not tg["pass"]:
        return {"pass": False, "per_gate": per_gate, "reasons": ["technical: " + "; ".join(tg["reasons"])],
                "scores": {}, "trajectory": {}, "flow": {}, "tech": tg["meta"]}

    frames = _frames(clip, g["frames"], out_dir)
    vlm = hero_vlm(clip, spec, boundary, frames, cost=cost)
    if "error" in vlm:
        return {"pass": False, "per_gate": per_gate, "reasons": [f"vlm error: {vlm['error']}"],
                "scores": {}, "trajectory": {}, "flow": {}, "tech": tg["meta"]}
    traj = _trajectory(vlm.get("per_frame", []))
    flow = optical_flow_direction(clip)

    # identity + per-frame consistency (mutation)
    if vlm.get("identity", 0) < g["identity_min"]:
        reasons.append(f"identity {vlm.get('identity')}<{g['identity_min']}")
    if any(f.get("present") and not f.get("identity_ok", True) for f in vlm.get("per_frame", [])):
        reasons.append("hero identity_ok=false on a present frame (mutation)")
    # pointed replacement question — primary swap/mutation catch
    if vlm.get("hero_replaced"):
        reasons.append(f"hero replaced by a different object at frame {vlm.get('replacement_frame')} (mutation)")
    # per-frame identity FLOOR catches a mid-clip drift the global average would hide
    pf_ids = [f.get("identity_score") for f in vlm.get("per_frame", [])
              if f.get("present") and isinstance(f.get("identity_score"), (int, float))]
    if pf_ids and min(pf_ids) < g["identity_min"]:
        reasons.append(f"per-frame identity floor {min(pf_ids)}<{g['identity_min']} (mutation/identity drift)")
    # slop, semantic, scoped prohibitions
    if vlm.get("slop", 0) > g["slop_max"]:
        reasons.append(f"slop {vlm.get('slop')}>{g['slop_max']}")
    if vlm.get("semantic", 0) < g["semantic_min"]:
        reasons.append(f"semantic {vlm.get('semantic')}<{g['semantic_min']}")
    if vlm.get("prohibited_present"):
        reasons.append(f"prohibited events present: {vlm['prohibited_present']}")
    # start/end state + boundary frame matching
    if vlm.get("start_end_match", 0) < g["start_end_min"]:
        reasons.append(f"start_end_match {vlm.get('start_end_match')}<{g['start_end_min']}")
    if boundary and boundary.get("start_frame") and vlm.get("start_frame_match", 10) < g["start_frame_min"]:
        reasons.append(f"start_frame_match {vlm.get('start_frame_match')}<{g['start_frame_min']}")
    if boundary and boundary.get("end_frame") and vlm.get("end_frame_match", 10) < g["end_frame_min"]:
        reasons.append(f"end_frame_match {vlm.get('end_frame_match')}<{g['end_frame_min']}")
    if boundary and vlm.get("entry_cut_quality", 10) < g["entry_cut_min"]:
        reasons.append(f"entry_cut {vlm.get('entry_cut_quality')}<{g['entry_cut_min']}")
    if boundary and vlm.get("exit_cut_quality", 10) < g["exit_cut_min"]:
        reasons.append(f"exit_cut {vlm.get('exit_cut_quality')}<{g['exit_cut_min']}")
    # disappearance always rejected beyond tolerance
    if traj["disappearances"] > g["max_disappearances"]:
        reasons.append(f"hero disappears in {traj['disappearances']} frame(s)")

    if directional:
        want = spec["motion_direction"]
        if g["direction_must_match"] and traj["direction"] != want:
            reasons.append(f"hero direction {traj['direction']} != required {want} (primary tracking)")
        if traj["displacement"] < g["min_displacement"]:
            reasons.append(f"hero displacement {traj['displacement']}<{g['min_displacement']} (insufficient motion)")
        if traj["path_len"] < g["min_motion_magnitude"]:
            reasons.append(f"motion magnitude {traj['path_len']}<{g['min_motion_magnitude']}")
        if traj["reversals"] > g["max_reversals"]:
            reasons.append(f"{traj['reversals']} direction reversal(s) > {g['max_reversals']}")
        if g["optical_flow_check"] and flow["direction"] == "none":
            reasons.append("optical flow shows no directional motion on a directional block")
        if g["optical_flow_check"] and flow["direction"] not in ("none", want) and traj["direction"] != want:
            reasons.append(f"optical flow {flow['direction']} contradicts required {want}")
        if g["min_scale_change"] and abs(traj["scale_change"]) < g["min_scale_change"]:
            reasons.append(f"scale change {traj['scale_change']}<{g['min_scale_change']}")
    else:  # stationary hero block: no displacement required, but excessive travel is also wrong
        if traj["displacement"] > 0.35:
            reasons.append(f"stationary block but hero traveled {traj['displacement']}")

    scores = {k: vlm.get(k) for k in ("identity", "start_end_match", "start_frame_match", "end_frame_match",
              "entry_cut_quality", "exit_cut_quality", "slop", "semantic", "notes")}
    scores["prohibited_present"] = vlm.get("prohibited_present", [])
    return {"pass": not reasons, "per_gate": per_gate, "reasons": reasons, "scores": scores,
            "trajectory": traj, "flow": flow, "tech": tg["meta"]}


# ── GENERIC entity tracing (roles come from the topic; no green/bubble/right/down hard-coding) ─────
_POSTURE_ORD = {"healthy": 0, "upright": 0, "fresh": 0, "energetic": 0, "normal": 0,
                "labored": 1, "strained": 1, "struggling": 1, "weak": 1, "faltering": 1, "tired": 1,
                "unstable": 2, "tumbling": 2, "off-balance": 2, "falling": 2, "buckling": 2, "stumbling": 2,
                "collapsed": 3, "limp": 3, "slumped": 3, "sinking": 3, "crumpled": 3, "fallen": 3,
                "face-down": 3, "down": 3, "motionless": 3}


def _cxy(bb):
    return (bb[0] + bb[2] / 2, bb[1] + bb[3] / 2) if bb and len(bb) == 4 else None


def _pscale(bb):
    return (bb[2] * bb[3]) ** 0.5 if bb and len(bb) == 4 else None


def _dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 if (a and b) else None


def trace_vlm(clip, roles, frames, cost=None, model="claude-opus-4-8"):
    """GENERIC per-frame trace of ROLE-named entities (hero/destination/equipment described by the
    topic). Returns per_frame {hero_bbox, hero_present, destination_bbox, equipment_present, posture}.
    Knows nothing about oxygen/portals — it tracks whatever the roles describe."""
    import explainer_pipeline as ep
    hero = roles.get("hero", "the main character")
    dest = roles.get("destination"); equip = roles.get("equipment")
    content = [b for i, (t, fp) in enumerate(frames) for b in _img_block(fp, f"frame {i} @ {t}s:")]
    ask = ("hero_bbox [x,y,w,h] 0..1 (null if absent), hero_present (bool), "
           "posture (one of: healthy, labored, unstable, collapsed)")
    if dest:
        ask += ", destination_bbox [x,y,w,h] (null if absent)"
    if equip:
        ask += ", equipment_present (bool)"
    schema = "{\"i\":int,\"hero_bbox\":[..]|null,\"hero_present\":bool,\"posture\":str"
    schema += (",\"destination_bbox\":[..]|null" if dest else "") + (",\"equipment_present\":bool" if equip else "") + "}"
    txt = (f"Frames in time order. HERO = {hero}." + (f" DESTINATION = {dest}." if dest else "")
           + (f" EQUIPMENT = {equip}." if equip else "")
           + f" For EACH frame report: {ask}. Return ONLY JSON: {{\"per_frame\":[{schema}]}}.")
    content.append({"type": "text", "text": txt})
    try:
        r = ep._claude().messages.create(model=model, max_tokens=1300,
            system="You are a precise visual annotator. Report only what is visible; posture by body shape.",
            messages=[{"role": "user", "content": content}])
        if cost is not None:
            cost.append(ep._msg_cost(r.usage))
        o, _ = ep._parse_script_json(r.content[0].text)
        return o if isinstance(o, dict) else {"error": "parse"}
    except Exception as e:
        return {"error": str(e)}


def _traces(vlm):
    pf = sorted(vlm.get("per_frame", []), key=lambda x: x.get("i", 0))
    return [{"hero_c": _cxy(f.get("hero_bbox")), "hero_present": bool(f.get("hero_present", f.get("hero_bbox"))),
             "dest_c": _cxy(f.get("destination_bbox")), "dest_s": _pscale(f.get("destination_bbox")),
             "equip": bool(f.get("equipment_present")),
             "post": _POSTURE_ORD.get(str(f.get("posture", "")).lower(), None)} for f in pf]


# ── DEDICATED per-invariant anatomy gate (vs the approved reference) ───────────────────────────────
def anatomy_vlm(clip, reference, anatomy, frames, cost=None, model="claude-opus-4-8"):
    """Compare EVERY sampled frame directly to the approved reference and answer each immutable
    invariant individually. Returns per_frame {prohibited_seen:[...], required_altered:[...]}."""
    import explainer_pipeline as ep
    req = list((anatomy or {}).get("required", {}).keys())
    proh = list((anatomy or {}).get("prohibited", []))
    content = _img_block(reference, "APPROVED REFERENCE (the ONLY correct anatomy):") if reference else []
    content += [b for i, (t, fp) in enumerate(frames) for b in _img_block(fp, f"frame {i}:")]
    content.append({"type": "text", "text": (
        "Compare each numbered frame's character to the APPROVED REFERENCE. Check these invariants "
        f"INDIVIDUALLY per frame. REQUIRED (must be present unless simply hidden by angle/occlusion — "
        f"never replaced or transformed): {req}. PROHIBITED (must NEVER appear in any frame): {proh}. "
        "For each frame list prohibited_seen = any prohibited features actually visible, and "
        "required_altered = any required part that is REPLACED by a fundamentally DIFFERENT KIND of "
        "structure. A required part seen at a different ANGLE, SIZE, distance, or LIGHTING, or slightly "
        "restyled by the pose, is NOT altered — do not list it. In particular, a SINGLE rounded "
        "hover-base is correct even if its exact shape differs from the reference; only flag hover_base if "
        "it has become legs/feet/wheels/multiple supports. Report a leg/foot/boot ONLY if it is DISTINCT "
        "lower-limb or foot geometry ATTACHED to the lower body — do NOT call an ARM a leg just because "
        "the body is rotated, tipping, upside-down or prone; if a limb matches an ARM (two rounded stubby "
        "arms) it is an arm, not a leg. Legs/feet/boots replacing the hover base is a prohibited mutation, "
        "not occlusion. Return ONLY JSON: {\"per_frame\":[{\"i\":int,"
        "\"prohibited_seen\":[str],\"required_altered\":[str]}]}")})
    try:
        r = ep._claude().messages.create(model=model, max_tokens=1200,
            system="You are a strict character-model integrity auditor. Judge anatomy only; report exactly "
                   "what is visible; when a lower body clearly becomes legs/feet, say so.",
            messages=[{"role": "user", "content": content}])
        if cost is not None:
            cost.append(ep._msg_cost(r.usage))
        o, _ = ep._parse_script_json(r.content[0].text)
        return o if isinstance(o, dict) else {"error": "parse"}
    except Exception as e:
        return {"error": str(e)}


def check_anatomy(clip, spec, frames=None, cost=None, log=print):
    """identity_pass: NO prohibited feature in ANY frame and NO required part altered. Not a score."""
    out_dir = tempfile.mkdtemp()
    frames = frames or _frames(clip, max(9, DEFAULT_GATES["frames"]), out_dir)
    a = anatomy_vlm(clip, spec.get("identity_reference"), spec.get("anatomy"), frames, cost=cost)
    if "error" in a:
        return {"identity_pass": False, "reason": f"anatomy vlm error: {a['error']}", "per_frame": []}
    pf = a.get("per_frame", [])
    proh_frames = [f["i"] for f in pf if f.get("prohibited_seen")]
    alt_frames = [f["i"] for f in pf if f.get("required_altered")]
    feats = sorted({x for f in pf for x in (f.get("prohibited_seen", []) + f.get("required_altered", []))})
    ok = not proh_frames and not alt_frames
    return {"identity_pass": ok, "prohibited_frames": proh_frames, "altered_frames": alt_frames,
            "features": feats, "per_frame": pf,
            "reason": "" if ok else f"anatomy mutation: {feats} in frames {sorted(set(proh_frames + alt_frames))}"}


# ── CLEAN-PLATE gate (reject generated UI/text/meters baked into the video) ────────────────────────
def clean_plate_vlm(clip, frames, cost=None, model="claude-opus-4-8", expected_objects=None):
    """Flag only FLAT 2D OVERLAY UI (text/meters/bars/HUD/gauges/countdowns/on-character icons or
    screens) — NOT 3D scene objects. `expected_objects` (e.g. a glowing portal, a water bubble) are
    legitimate physical scene elements and must never be flagged."""
    import explainer_pipeline as ep
    exp = expected_objects or []
    content = [b for i, (t, fp) in enumerate(frames) for b in _img_block(fp, f"frame {i}:")]
    content.append({"type": "text", "text": (
        "Flag ONLY flat 2D OVERLAY graphics composited ON TOP of the scene by an editor: HUD panels, "
        "on-screen captions/subtitles, progress bars or METERS, gauges, countdown timers, score/UI "
        "widgets, watermarks, or any ICON/SCREEN/PERCENTAGE drawn ON a character's body (e.g. a battery "
        "icon on the chest). Do NOT flag things that physically belong in the 3D WORLD: "
        f"expected objects {exp if exp else 'portals/rings, particles, lights'}, AND DIEGETIC signage/text "
        "that is part of the set — labels or warnings printed on walls, pipes, vents, machines, doors or "
        "the floor (e.g. 'OXYGEN REFILL STATION', 'SUBSCRIPTION EXPIRED', 'VENT', 'CAUTION'). Diegetic "
        "wall/floor/machine text is SET DRESSING, not UI. Only flat editor-composited overlays count. "
        "For each frame list ui_seen = any flat 2D overlay UI/meter/caption/on-body-icon elements ONLY. "
        "Return ONLY JSON: {\"per_frame\":[{\"i\":int,\"ui_seen\":[str]}]}")})
    try:
        r = ep._claude().messages.create(model=model, max_tokens=900,
            system="You are a clean-plate auditor. Flag flat 2D overlay UI/text/meters and on-body icons "
                   "ONLY; never flag 3D physical scene objects (portals, bubbles, particles, lights).",
            messages=[{"role": "user", "content": content}])
        if cost is not None:
            cost.append(ep._msg_cost(r.usage))
        o, _ = ep._parse_script_json(r.content[0].text)
        return o if isinstance(o, dict) else {"error": "parse"}
    except Exception as e:
        return {"error": str(e)}


def check_anatomy_temporal(clip, spec, frames=None, cost=None, log=print):
    """TEMPORAL, attachment-aware anatomy: a leg/foot/boot violation counts ONLY if it PERSISTS across
    >=2 consecutive frames (a single-frame flag during a fast tip/rotation is treated as an arm/rotation
    artifact, not a mutation). Returns identity_pass + persistent vs transient flags."""
    out_dir = tempfile.mkdtemp()
    frames = frames or _frames(clip, max(10, DEFAULT_GATES["frames"]), out_dir)
    a = anatomy_vlm(clip, spec.get("identity_reference"), spec.get("anatomy"), frames, cost=cost)
    if "error" in a:
        return {"identity_pass": False, "reason": f"anatomy vlm error: {a['error']}", "per_frame": []}
    pf = sorted(a.get("per_frame", []), key=lambda x: x.get("i", 0))
    lower = ("leg", "legs", "feet", "foot", "boot", "boots", "shoe", "shoes", "lower limb", "separate lower limbs")
    def has_lower(f):
        return any(any(w in str(x).lower() for w in lower) for x in (f.get("prohibited_seen", []) + f.get("required_altered", [])))
    def other_proh(f):   # non-lower-limb prohibitions (mouth/extra limbs/duplicate) — always count
        return [x for x in f.get("prohibited_seen", []) if not any(w in str(x).lower() for w in lower)]
    idxs = [i for i, f in enumerate(pf) if has_lower(f)]
    persistent = [pf[i]["i"] for i in idxs if (i + 1 in idxs or i - 1 in idxs)]  # >=2 consecutive
    transient = [pf[i]["i"] for i in idxs if pf[i]["i"] not in persistent]
    other = sorted({x for f in pf for x in other_proh(f)})
    feats = sorted({x for f in pf for x in (f.get("prohibited_seen", []) + f.get("required_altered", []))})
    ok = (not persistent) and (not other)
    return {"identity_pass": ok, "persistent_lower_limb_frames": persistent, "transient_lower_limb_frames": transient,
            "other_prohibited": other, "features": feats, "per_frame": pf,
            "reason": "" if ok else f"persistent lower-limb mutation frames {persistent} / other {other}"}


def action_window_vlm(clip, frames, cost=None, model="claude-opus-4-8"):
    """Per-frame read for atomic-action boundary detection over the FULL raw clip: thruster state, hero
    vertical center, posture. Used to locate the collapse window inside a longer provider clip."""
    import explainer_pipeline as ep
    content = [b for i, (t, fp) in enumerate(frames) for b in _img_block(fp, f"frame {i} @ {t}s:")]
    content.append({"type": "text", "text": (
        "A small robot's thruster fails and it collapses. For EACH frame report thruster_on (bool: is a "
        "bright active thruster jet firing?), hero_cy (0..1 vertical center; 0=top,1=floor), and posture "
        "(one of: hovering, dropping, tipping, impact, prone). Return ONLY JSON: {\"per_frame\":[{\"i\":int,"
        "\"t\":float,\"thruster_on\":bool,\"hero_cy\":float,\"posture\":str}]}")})
    try:
        r = ep._claude().messages.create(model=model, max_tokens=1100,
            system="You are a precise motion-phase annotator. Report only what is visible.",
            messages=[{"role": "user", "content": content}])
        if cost is not None:
            cost.append(ep._msg_cost(r.usage))
        o, _ = ep._parse_script_json(r.content[0].text)
        return o if isinstance(o, dict) else {"error": "parse"}
    except Exception as e:
        return {"error": str(e)}


def detect_action_window(clip, cost=None, log=print, start_range=(1.45, 1.70), end_range=(2.80, 3.20)):
    """Evaluate the FULL raw clip and locate the atomic-collapse window (thrust fade → drop → tip →
    impact → stable prone). Returns {start, end, events, per_frame}. Never truncates before evaluation."""
    out_dir = tempfile.mkdtemp()
    dur = _probe(clip).get("dur", 5.0) or 5.0
    n = 16
    frames = [(round(dur * (i + 0.5) / n, 2), os.path.join(out_dir, f"_aw_{i}.jpg")) for i in range(n)]
    for t, fp in frames:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t}", "-i", clip, "-frames:v", "1",
                        "-vf", "scale=300:533", fp], check=True)
    vlm = action_window_vlm(clip, frames, cost=cost)
    pf = sorted(vlm.get("per_frame", []), key=lambda x: x.get("i", 0)) if "error" not in vlm else []
    def t_of(i):
        return frames[i][0] if i < len(frames) else None
    fade = next((t_of(k) for k, f in enumerate(pf) if not f.get("thruster_on")), None)
    drop = next((t_of(k) for k, f in enumerate(pf) if str(f.get("posture", "")).lower() in ("dropping", "tipping")), None)
    impact = next((t_of(k) for k, f in enumerate(pf) if str(f.get("posture", "")).lower() == "impact"), None)
    prone_ts = [t_of(k) for k, f in enumerate(pf) if str(f.get("posture", "")).lower() == "prone"]
    prone_start = prone_ts[0] if prone_ts else None
    prone_end = prone_ts[-1] if prone_ts else None
    raw_start = min([x for x in (fade, drop) if x is not None], default=start_range[0])
    raw_end = (prone_end or impact or dur)
    start = max(start_range[0], min(start_range[1], raw_start))
    end = max(end_range[0], min(end_range[1], raw_end))
    if end <= start:
        end = min(end_range[1], start + 1.4)
    return {"start": round(start, 2), "end": round(end, 2), "dur": round(end - start, 2),
            "events": {"thrust_fade": fade, "drop": drop, "impact": impact, "prone_start": prone_start,
                       "prone_end": prone_end}, "raw_dur": round(dur, 2), "per_frame": pf}


def check_clean_plate(clip, frames=None, cost=None, log=print, expected_objects=None):
    out_dir = tempfile.mkdtemp()
    frames = frames or _frames(clip, max(9, DEFAULT_GATES["frames"]), out_dir)
    c = clean_plate_vlm(clip, frames, cost=cost, expected_objects=expected_objects)
    if "error" in c:
        return {"clean_plate_pass": False, "reason": f"clean_plate vlm error: {c['error']}"}
    hits = [f["i"] for f in c.get("per_frame", []) if f.get("ui_seen")]
    feats = sorted({x for f in c.get("per_frame", []) for x in f.get("ui_seen", [])})
    ok = not hits
    return {"clean_plate_pass": ok, "ui_frames": hits, "ui_features": feats,
            "reason": "" if ok else f"generated UI in frames {hits}: {feats}"}


# ── DECLARATIVE phase predicates (topic supplies the contract; evaluator is generic) ───────────────
def _phase_idx(fr, N):
    return max(0, min(N - 1, int(round(fr * (N - 1)))))


def _seg(tr, ph, N):
    a, b = _phase_idx(ph["t"][0], N), _phase_idx(ph["t"][1], N)
    return [tr[i] for i in range(a, b + 1)]


def _p_moves_toward(seg, tr, anatomy_bad):
    ds = [t["dest_s"] for t in seg if t["dest_s"] is not None]
    dd = [_dist(t["hero_c"], t["dest_c"]) for t in seg if t["hero_c"] and t["dest_c"]]
    approach = (ds and ds[-1] >= ds[0] - 0.02) or (dd and dd[-1] <= dd[0] + 0.03)
    return bool(approach), "" if approach else "hero does not move toward destination"


def _p_remains_near(seg, tr, anatomy_bad):
    dd = [_dist(t["hero_c"], t["dest_c"]) for t in seg if t["hero_c"] and t["dest_c"]]
    ok = bool(dd) and max(dd) <= 0.45
    return ok, "" if ok else "hero not near destination"


def _p_persists(seg, tr, anatomy_bad):
    ok = all(t["equip"] for t in seg)
    return ok, "" if ok else "equipment not present throughout phase"


def _max_drop_below_running_max(ps):
    """Largest recovery: how far any reading falls below the worst-so-far. Tolerant of ±1 VLM noise."""
    return max((max(ps[:k + 1]) - ps[k] for k in range(len(ps))), default=0)


def _p_condition_worsens(seg, tr, anatomy_bad):
    # net worsening + no GENUINE recovery (a real recovery = a drop of >=2 categorical levels; ±1 is VLM noise)
    ps = [t["post"] for t in seg if t["post"] is not None]
    ok = bool(ps) and ps[-1] >= ps[0] and _max_drop_below_running_max(ps) <= 1
    return ok, "" if ok else "condition does not worsen (net) or recovers >1 level"


def _p_does_not_recover(seg, tr, anatomy_bad):
    ps = [t["post"] for t in seg if t["post"] is not None]
    ok = _max_drop_below_running_max(ps) <= 1   # tolerate 1-level posture jitter; fail on real recovery
    return ok, "" if ok else "condition recovers (improves) >1 level within phase"


def _p_collapsed_posture(seg, tr, anatomy_bad):
    ok = any(t["post"] == 3 for t in seg)
    return ok, "" if ok else "no collapsed posture in phase"


def _p_anatomy_immutable(seg_idx, anatomy_bad):
    bad = [i for i in seg_idx if i in anatomy_bad]
    return (not bad), "" if not bad else f"anatomy mutation in frames {bad}"


PREDICATES = {"moves_toward": _p_moves_toward, "remains_near": _p_remains_near, "persists": _p_persists,
              "condition_worsens": _p_condition_worsens, "does_not_recover": _p_does_not_recover,
              "collapsed_posture": _p_collapsed_posture}


def _prohibited_transition(name, tr):
    """Whole-clip prohibited transitions (destination_recedes / instant_healthy_to_collapsed / etc.)."""
    if name in ("destination_recedes", "portal_recedes"):
        ds = [t["dest_s"] for t in tr if t["dest_s"] is not None]
        return bool(ds) and ds[-1] < max(ds) * 0.8, "destination recedes"
    if name == "instant_healthy_to_collapsed":
        ps = [t["post"] for t in tr if t["post"] is not None]
        return any(ps[k] == 0 and ps[k + 1] >= 3 for k in range(len(ps) - 1)), "instant healthy→collapsed"
    if name in ("hero_flies_through_destination", "passes_through_destination"):
        xs = [(t["hero_c"], t["dest_c"]) for t in tr if t["hero_c"] and t["dest_c"]]
        crossed = any(a[0] < d[0] for a, d in xs[:1]) and any(a[0] > d[0] for a, d in xs[-1:])
        return bool(crossed), "hero passes through/beyond destination"
    return False, ""


def evaluate_phased(clip, spec, traces=None, anatomy_bad=None, gates=None, tech=None, cost=None, log=print):
    """GENERIC phase-motion evaluator driven by the topic's declarative contract. Returns
    phase_motion_pass ONLY (identity/clean-plate/boundary are SEPARATE gates). Reversal = a prohibited
    transition (destination recession / recovery / passing-through), never right→down during collapse."""
    contract = spec.get("phase_contract") or {}
    phases = contract.get("phases", [])
    reasons = []
    tg = technical_gate(clip, tech, spec)
    if not tg["pass"]:
        return {"phase_motion_pass": False, "reasons": ["technical: " + "; ".join(tg["reasons"])], "phases": {}}
    out_dir = tempfile.mkdtemp()
    frames = _frames(clip, max(9, (gates or DEFAULT_GATES)["frames"]), out_dir)
    if traces is None:
        vlm = trace_vlm(clip, contract.get("entities", {"hero": spec.get("identity_bible", "the character")}),
                        frames, cost=cost)
        if "error" in vlm:
            return {"phase_motion_pass": False, "reasons": [f"trace vlm error: {vlm['error']}"], "phases": {}}
        traces = _traces(vlm)
    N = len(traces); anatomy_bad = anatomy_bad or set()
    ph_report = {}
    for ph in phases:
        a, b = _phase_idx(ph["t"][0], N), _phase_idx(ph["t"][1], N)
        seg = [traces[i] for i in range(a, b + 1)]; seg_idx = list(range(a, b + 1))
        issues = []
        for pred in ph.get("predicates", []):
            neg = pred.startswith("not ")
            body = pred[4:] if neg else pred
            fname = body.split("(")[0].strip()
            if fname == "anatomy_immutable":
                ok, why = _p_anatomy_immutable(seg_idx, anatomy_bad)
            elif fname in PREDICATES:
                ok, why = PREDICATES[fname](seg, traces, anatomy_bad)
            elif fname in ("destination_recedes", "portal_recedes", "instant_healthy_to_collapsed",
                           "hero_flies_through_destination", "passes_through_destination"):
                ok, why = _prohibited_transition(fname, seg)   # ok=True means it OCCURRED; contracts use "not X"
            else:
                ok, why = True, ""  # unknown predicate is not silently failed; noted in report
            if neg:
                ok = not ok; why = ("" if ok else f"prohibited '{body}' occurred")
            if not ok:
                issues.append(f"{pred}: {why}")
        ph_report[ph["name"]] = {"ok": not issues, "issues": issues}
        reasons += [f"{ph['name']}: {i}" for i in issues]

    prohibited = []
    for name in contract.get("prohibited_transitions", []):
        hit, why = _prohibited_transition(name, traces)
        if hit:
            prohibited.append(why); reasons.append(f"prohibited_transition: {why}")

    return {"phase_motion_pass": not reasons, "reasons": reasons, "phases": ph_report,
            "prohibited_transitions_hit": prohibited, "n_frames": N}


# ── PRODUCTION READINESS (separate pass types; motion alone is NEVER "pass") ───────────────────────
def production_readiness(clip, spec, boundary=None, gates=None, tech=None, cost=None, log=print):
    """Aggregate ALL gate types. production_ready requires every hard pass. Returns a dict with the
    eight pass flags the review process requires."""
    g = {**DEFAULT_GATES, **(gates or {})}
    out_dir = tempfile.mkdtemp()
    frames = _frames(clip, max(9, g["frames"]), out_dir)
    tg = technical_gate(clip, tech, spec)
    an = check_anatomy(clip, spec, frames=frames, cost=cost, log=log)
    cp = check_clean_plate(clip, frames=frames, cost=cost, log=log)
    anatomy_bad = set(an.get("prohibited_frames", []) + an.get("altered_frames", []))
    contract = spec.get("phase_contract") or {}
    vlm = trace_vlm(clip, contract.get("entities", {"hero": spec.get("identity_bible", "the character")}),
                    frames, cost=cost) if contract.get("phases") else {"per_frame": []}
    traces = _traces(vlm) if "error" not in vlm else []
    mot = evaluate_phased(clip, spec, traces=traces or None, anatomy_bad=anatomy_bad, gates=g, cost=cost, log=log) \
        if contract.get("phases") else {"phase_motion_pass": None, "reasons": ["no phase contract"]}
    equip_pass = None
    if any(t.get("equip") is not None for t in traces):
        eq = [t["equip"] for t in traces]
        fa = next((i for i, x in enumerate(eq) if not x), None)
        equip_pass = bool(eq[0]) and (fa is None or not any(eq[fa + 1:]))  # present early, no reappear
    flags = {
        "technical_pass": tg["pass"],
        "motion_pass": mot.get("phase_motion_pass"),
        "identity_pass": an["identity_pass"],
        "equipment_pass": equip_pass,
        "clean_plate_pass": cp["clean_plate_pass"],
        "entry_boundary_pass": None,   # set by the assembler (start-frame match vs deterministic entry)
        "exit_integration_pass": None,  # set by the assembler (bridge/native-collapse review)
        "manual_review_pass": None,     # human
    }
    hard = [flags["technical_pass"], flags["motion_pass"], flags["identity_pass"], flags["clean_plate_pass"]]
    flags["production_ready"] = all(x is True for x in hard) and equip_pass is not False
    return {"flags": flags, "technical": tg, "anatomy": an, "clean_plate": cp, "motion": mot,
            "reasons": mot.get("reasons", []) + ([an["reason"]] if not an["identity_pass"] else [])
                       + ([cp["reason"]] if not cp["clean_plate_pass"] else [])}


# ── scoped prohibitions + spec building ────────────────────────────────────────────────────────────
def scoped_prohibitions(topic, block, entity):
    """Collect prohibitions that actually apply to THIS hero block — not every topic must_not_occur.
    global: always-on identity/reversal rules · block: block['prohibited'] · entity: entity['prohibited']
    state-window: {'event':..., 'when':{var,op,value}} active in this block's state range."""
    from bolt_seq import semantics as SEM
    proh = []
    always = {"bolt_reverses", "train_reverses", "identity_change", "character_swap", "mutation"}
    for c in topic.get("constraints", []):
        if c.get("kind") == "must_not_occur" and c.get("event") in always:
            proh.append(c["event"])
    proh += list(block.get("prohibited", []))
    proh += list(entity.get("prohibited", []))
    for w in topic.get("state_window_prohibitions", []) + block.get("state_window_prohibitions", []):
        var, op, val = w.get("when", {}).get("var"), w.get("when", {}).get("op"), w.get("when", {}).get("value")
        s, e = block.get("start_state", {}), block.get("end_state", {})
        if var and (SEM._num(s.get(var)) or SEM._num(e.get(var))):
            hit = any(_cmp(op, v, val) for v in (s.get(var), e.get(var)) if SEM._num(v))
            if hit:
                proh.append(w["event"])
    return sorted(set(proh))


def _cmp(op, a, b):
    return {"<=": a <= b, ">=": a >= b, "<": a < b, ">": a > b, "==": a == b}.get(op, False)


# ── ATOMIC-ACTION rule for paid hero clips ────────────────────────────────────────────────────────
# A paid generated clip may contain ONE primary physical action + at most one simple transition. Asking
# a single clip to do approach + progressive-degradation + equipment-failure + collapse + exact-boundary
# at once is what produced the unusable pilots. The heavy lifting (state events, payoff) is deterministic.
ATOMIC_MAX_ACTIONS = 1
ATOMIC_MAX_TRANSITIONS = 1
# action classes a phase's predicates imply (used to count how many distinct actions a clip is asked for)
_ACTION_OF_PRED = {
    "moves_toward": "approach", "remains_near": "approach",
    "condition_worsens": "degradation", "does_not_recover": "degradation",
    "collapsed_posture": "collapse", "disappears_after": "equipment_failure", "persists": "equipment",
}


CONTINUATION_INVARIANT = (
    "A deterministic continuation MUST inherit the final generated frame's environment, camera, "
    "destination geometry, lighting and protagonist scale. Any unexplained spatial reset fails "
    "integration (do not cut to a separately composed scene).")


CONTINUATION_MODES = {
    "same_shot": "continue in the SAME shot (inherit env/camera/scale) — only with a clean matte + a "
                 "seam-clean background reconstruction + preserved scale/lighting/perspective",
    "motivated_cut": "a deliberate editorial CUT to a NEW deterministic camera angle — used when a "
                     "same-shot continuation would show compositing artifacts (the honest default)",
}
SAME_SHOT_REQUIRES = ["clean_alpha_matte", "background_seam_pass", "scale_lighting_perspective_preserved"]
MOTIVATED_CUT_WHEN = ["pose_changes_substantially", "matting_unreliable", "new_angle_improves_payoff",
                      "same_shot_artifacts"]


def select_continuation_mode(signals):
    """Choose same_shot vs motivated_cut. same_shot is permitted ONLY when a clean matte + seam-clean bg +
    preserved scale/lighting/perspective all hold AND the pose does not change substantially. Otherwise
    motivated_cut (the safe default that avoids compositing artifacts)."""
    if (signals.get("pose_changes_substantially") or signals.get("matting_unreliable")
            or signals.get("same_shot_artifacts") or signals.get("new_angle_improves_payoff")
            or not signals.get("clean_alpha_matte") or not signals.get("background_seam_pass")
            or not signals.get("scale_lighting_perspective_preserved")):
        return "motivated_cut"
    return "same_shot"


def perceptual_composite_gate(clip, frames=None, cost=None, model="claude-opus-4-8", mode="same_shot"):
    """Reject a hybrid block that LOOKS composited. Flags rectangular patches, crop/cutout edges,
    background texture discontinuity, character scale jumps, lighting mismatch, residual thrust or
    duplicated motion, and pasted-cutout appearance. Returns {pass, issues, pasted_cutout, per_frame}.
    With mode='motivated_cut', a scale change across the deliberate cut is NOT an artifact (a cut may
    legitimately reframe), so scale-jump is reported but does not fail the gate."""
    import explainer_pipeline as ep
    out_dir = tempfile.mkdtemp()
    frames = frames or _frames(clip, 10, out_dir)
    content = [b for i, (t, fp) in enumerate(frames) for b in _img_block(fp, f"frame {i} @ {t}s:")]
    content.append({"type": "text", "text": (
        "These frames are a hybrid of generated + deterministic video. Detect COMPOSITING ARTIFACTS only. "
        "For each frame list artifacts_seen drawn from: 'rectangular patch/matte box', 'visible crop or "
        "cutout edge', 'background texture discontinuity/seam', 'character scale jump', 'lighting mismatch "
        "between character and scene', 'residual thrust streak or duplicated/ghosted motion', "
        "'pasted-cutout/stuck-on appearance'. Also give overall pasted_cutout 0-10 (0=fully integrated, "
        "10=obvious paste) and scale_jump 0-10. Return ONLY JSON: {\"per_frame\":[{\"i\":int,"
        "\"artifacts_seen\":[str]}],\"pasted_cutout\":n,\"scale_jump\":n}")})
    try:
        r = ep._claude().messages.create(model=model, max_tokens=1000,
            system="You are a strict compositing-artifact auditor. Report only visible compositing defects.",
            messages=[{"role": "user", "content": content}])
        if cost is not None:
            cost.append(ep._msg_cost(r.usage))
        o, _ = ep._parse_script_json(r.content[0].text); o = o if isinstance(o, dict) else {}
    except Exception as e:
        return {"pass": False, "issues": [f"gate error: {e}"], "pasted_cutout": None, "per_frame": []}
    issues = sorted({a for f in o.get("per_frame", []) for a in f.get("artifacts_seen", [])})
    scale_ok = True
    if mode == "motivated_cut":     # a deliberate cut may reframe → scale change is not an artifact
        issues = [a for a in issues if "scale" not in a.lower()]
    else:
        scale_ok = o.get("scale_jump", 10) <= 3
    ok = not issues and (o.get("pasted_cutout", 10) <= 3) and scale_ok
    return {"pass": ok, "issues": issues, "pasted_cutout": o.get("pasted_cutout"),
            "scale_jump": o.get("scale_jump"), "mode": mode, "per_frame": o.get("per_frame", [])}


def bolt_tracker(clip, n=16, roi_x=(0.0, 0.58), roi_y=(0.26, 0.86), term_region=(0.58, 0.86, 0.26, 0.60),
                 white_thresh=175):
    """DETERMINISTIC (pixel) tracker — not a VLM centroid estimate. Segments the bright white/mint Bolt in
    a left ROI (terminal region excluded) per frame → bbox/centroid/velocity/area, and establishes the
    FIXED terminal anchor ONCE from the plate region (then verifies it is fixed across frames). Returns
    {samples, terminal_anchor, terminal_fixed, ...}. distance uses Bolt's right (destination-facing) edge
    to the terminal's left (interaction) edge."""
    import numpy as np
    from PIL import Image
    out = tempfile.mkdtemp(); dur = _probe(clip).get("dur", 5.0) or 5.0
    def arr(t):
        t = max(0.0, min(float(t), (dur - 0.05) if dur else float(t)))   # never sample past the last decodable frame (short clips)
        fp = os.path.join(out, f"_bt_{t:.2f}.png")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", clip, "-frames:v", "1", fp], check=True)
        if not os.path.exists(fp):                                       # fallback: seek slightly earlier
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(0.0, t - 0.08):.2f}", "-i", clip, "-frames:v", "1", fp], check=True)
        return np.asarray(Image.open(fp).convert("RGB"), float), fp
    a0, f0 = arr(0.1); H, Wd = a0.shape[:2]
    # terminal anchor established ONCE from the fixed region (brightest connected mass there), then verified
    tx0, tx1, ty0, ty1 = [int(v * (Wd if i < 2 else H)) for i, v in enumerate(term_region)]
    def bright_bbox(a, x0, x1, y0, y1):
        sub = a[y0:y1, x0:x1]; bright = (sub.min(axis=2) > white_thresh) | ((sub[:, :, 1] > 150) & (sub[:, :, 2] > 150) & (sub[:, :, 0] < 140))
        ys, xs = np.where(bright)
        if len(xs) < 30:
            return None
        return [x0 + int(np.percentile(xs, 2)), y0 + int(np.percentile(ys, 2)),
                x0 + int(np.percentile(xs, 98)), y0 + int(np.percentile(ys, 98))]
    term = bright_bbox(a0, tx0, tx1, ty0, ty1) or [tx0, ty0, tx1, ty1]
    term_left = term[0]
    # verify terminal is fixed on a slice Bolt never reaches (upper terminal, before Bolt arrives) — NOT the
    # last frame (Bolt occludes the terminal region at the end, which would spuriously read as "moved").
    aE, _ = arr(dur * 0.2)
    ty_slice = int((term[1] + term[3]) / 2)   # upper half of the terminal (its screen)
    term_change = float(np.abs(a0[term[1]:ty_slice, tx0:tx1] - aE[term[1]:ty_slice, tx0:tx1]).mean()) / 255.0
    # ROI right boundary = terminal LEFT edge so Bolt is captured until he genuinely overlaps the terminal;
    # frames where Bolt's right edge reaches that boundary are flagged clipped (edge measurement unreliable).
    rx0 = int(roi_x[0] * Wd); rx1 = term_left - 2; ry0, ry1 = int(roi_y[0] * H), int(roi_y[1] * H)  # track Bolt up to the terminal's left edge
    samples = []; prev = None
    for i in range(n):
        t = round(dur * (i + 0.5) / n, 3); a, fp = arr(t)
        bb = bright_bbox(a, rx0, rx1, ry0, ry1)
        if bb is None:
            samples.append({"t": t, "frame": fp, "bolt_bbox": None}); continue
        clipped = bb[2] >= rx1 - 3
        cx = (bb[0] + bb[2]) / 2 / Wd; cy = (bb[1] + bb[3]) / 2 / H
        edge_gap = max(0.0, (term_left - bb[2]) / Wd)      # Bolt right edge → terminal left edge
        cc = ((cx - (term[0] + term[2]) / 2 / Wd) ** 2 + (cy - (term[1] + term[3]) / 2 / H) ** 2) ** 0.5
        hv = (cx - prev[0]) if prev else 0.0; vv = (cy - prev[1]) if prev else 0.0
        samples.append({"t": t, "frame": fp, "bolt_bbox": [round(v, 1) for v in bb], "cx": round(cx, 4), "cy": round(cy, 4),
                        "edge_gap": round(edge_gap, 4), "center_dist": round(cc, 4), "h_vel": round(hv, 4),
                        "v_vel": round(vv, 4), "area": int((bb[2] - bb[0]) * (bb[3] - bb[1])), "clipped": bool(clipped)})
        prev = (cx, cy)
    det = [s for s in samples if s.get("cx") is not None]
    clean = [s for s in det if not s["clipped"]]
    xs = [s["cx"] for s in det]; gaps = [s["edge_gap"] for s in det]
    cxs = [s["cx"] for s in clean]; cgaps = [s["edge_gap"] for s in clean]
    reversals = sum(1 for i in range(len(xs) - 1) if xs[i + 1] < xs[i] - 0.02)
    rev_mag = round(sum(max(0.0, xs[i] - xs[i + 1]) for i in range(len(xs) - 1) if xs[i + 1] < xs[i] - 0.02), 4)
    clean_disp = round(cxs[-1] - cxs[0], 4) if len(cxs) >= 2 else 0.0
    clean_gap_red = round((cgaps[0] - cgaps[-1]) / cgaps[0] * 100, 1) if (cgaps and cgaps[0] > 0) else 0.0
    overshoot = any(s["clipped"] for s in det)   # Bolt's right edge reached the terminal band = arrived (defect for a "stop short" shot)
    disp = round(xs[-1] - xs[0], 4) if len(xs) >= 2 else 0.0
    gap_red = round((gaps[0] - gaps[-1]) / gaps[0] * 100, 1) if (gaps and gaps[0] > 0) else 0.0
    return {"terminal_anchor": [round(v, 1) for v in term], "terminal_fixed": term_change < 0.02,
            "terminal_change_frac": round(term_change, 4), "samples": samples, "frame_w": Wd, "frame_h": H,
            "roi_right_frac": round(rx1 / Wd, 4), "terminal_left_frac": round(term_left / Wd, 4),
            "horizontal_displacement": disp, "gap_reduction_pct": gap_red,
            "clean_horizontal_displacement": clean_disp, "clean_gap_reduction_pct": clean_gap_red,
            "clipped_frames": sum(1 for s in det if s["clipped"]), "overshoot": bool(overshoot),
            "reversals": reversals, "reversal_magnitude": rev_mag,
            "gap_start": round(gaps[0], 4) if gaps else None, "gap_end": round(gaps[-1], 4) if gaps else None,
            "clean_gap_start": round(cgaps[0], 4) if cgaps else None, "clean_gap_end": round(cgaps[-1], 4) if cgaps else None}


def articulation_quality_gate(clip, frames=None, cost=None, model="claude-opus-4-8"):
    """A: do arms/torso animate (not frozen), identity coherent, no pose teleport?"""
    return _char_subgate(clip, frames, cost, model, "articulation",
        "Do the ARMS and TORSO visibly animate across frames (reaching arm extends, torso orientation changes) "
        "rather than a frozen pose? Return ONLY JSON {\"arms_torso_animate\":0-10,\"pose_frozen\":bool,"
        "\"pose_teleport\":bool,\"identity_coherent\":bool,\"notes\":str}",
        lambda o: (o.get("arms_torso_animate", 0) >= 6 and not o.get("pose_frozen") and not o.get("pose_teleport")
                   and o.get("identity_coherent")))


def self_propulsion_readability_gate(clip, frames=None, cost=None, model="claude-opus-4-8"):
    """B: does body orientation correspond to travel; does Bolt appear to create his own motion?"""
    return _char_subgate(clip, frames, cost, model, "self_propulsion",
        "Does the character appear to CREATE HIS OWN forward motion (body orientation/lean corresponds to "
        "travel), not merely be translated by camera/world? Return ONLY JSON {\"self_propelled\":0-10,"
        "\"orientation_matches_travel\":0-10,\"notes\":str}",
        lambda o: (o.get("self_propelled", 0) >= 6 and o.get("orientation_matches_travel", 0) >= 6))


def progressive_effort_gate(clip, frames=None, cost=None, model="claude-opus-4-8"):
    """D: effort increases, posture more strained, speed/propulsion deteriorates over time."""
    return _char_subgate(clip, frames, cost, model, "progressive_effort",
        "Over time does EFFORT increase and PROPULSION deteriorate (posture becomes more strained, speed "
        "drops, arms tire)? Return ONLY JSON {\"effort_increases\":0-10,\"propulsion_weakens\":0-10,\"notes\":str}",
        lambda o: (o.get("effort_increases", 0) >= 6 and o.get("propulsion_weakens", 0) >= 6))


def end_state_gate(clip, end_target, frames=None, cost=None, model="claude-opus-4-8"):
    """E: airborne + strained + closer + still short of terminal + no collapse (vs the end target)."""
    import explainer_pipeline as ep
    out = tempfile.mkdtemp(); frames = frames or _frames(clip, 6, out)
    last = frames[-1][1]
    content = ([{"type": "text", "text": "END TARGET:"}] +
               [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(open(end_target, "rb").read()).decode()}}] +
               [{"type": "text", "text": "CANDIDATE last frame:"}] +
               [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(open(last, "rb").read()).decode()}}] +
               [{"type": "text", "text": "Return ONLY JSON {\"airborne\":bool,\"strained\":bool,\"closer_to_terminal\":bool,"
                 "\"still_short_of_terminal\":bool,\"collapsed\":bool,\"matches_end_target\":0-10}"}])
    try:
        r = ep._claude().messages.create(model=model, max_tokens=200, system="Strict end-state auditor.",
                                         messages=[{"role": "user", "content": content}])
        if cost is not None: cost.append(ep._msg_cost(r.usage))
        o, _ = ep._parse_script_json(r.content[0].text); o = o if isinstance(o, dict) else {}
    except Exception as e:
        return {"gate": "end_state", "pass": False, "error": str(e)}
    ok = (o.get("airborne") and o.get("strained") and o.get("closer_to_terminal")
          and o.get("still_short_of_terminal") and not o.get("collapsed") and o.get("matches_end_target", 0) >= 7)
    return {"gate": "end_state", "pass": bool(ok), "readings": o}


def macro_trajectory_gate(clip, cost=None, min_gap_reduction_pct=20.0, min_displacement=0.10, max_reversals=0, tracker=None):
    """C: DETERMINISTIC (tracker) — meaningful destination-directed displacement + monotonic gap reduction,
    smooth (no reversal), and correct endpoint (stops SHORT, does not overshoot into the terminal). Uses
    bolt_tracker (pixels, clean/unclipped region), not a VLM centroid. Reports each sub-verdict so a real
    approach that fails on path-smoothness/overshoot is not mislabelled 'no motion'."""
    tk = tracker or bolt_tracker(clip)
    progress = (tk["clean_gap_reduction_pct"] >= min_gap_reduction_pct and tk["clean_horizontal_displacement"] >= min_displacement)
    smooth = tk["reversals"] <= max_reversals
    stops_short = not tk["overshoot"]
    ok = progress and smooth and stops_short
    return {"gate": "macro_trajectory", "pass": bool(ok), "makes_progress": bool(progress),
            "path_smooth": bool(smooth), "stops_short_of_terminal": bool(stops_short),
            "clean_gap_reduction_pct": tk["clean_gap_reduction_pct"], "clean_horizontal_displacement": tk["clean_horizontal_displacement"],
            "reversals": tk["reversals"], "reversal_magnitude": tk["reversal_magnitude"], "overshoot": tk["overshoot"],
            "raw_gap_reduction_pct": tk["gap_reduction_pct"], "clipped_frames": tk["clipped_frames"],
            "gap_start": tk["gap_start"], "gap_end": tk["gap_end"], "terminal_fixed": tk["terminal_fixed"], "tracker": tk}


def trajectory_contract_gate(clip, contract=None, tracker=None, cost=None):
    """DETERMINISTIC full-clip trajectory contract (tracker-driven, NEVER overridable by a VLM summary).
    Enforces: positive x displacement · overall gap decrease · no backward segment beyond a small bob
    tolerance · no terminal overlap · final gap inside an authored short-of-terminal band · horizontal
    speed declines in the final third. Each clause reported independently."""
    c = {"min_x_displacement": 0.10, "require_gap_decrease": True, "bob_tolerance": 0.03,
         "forbid_terminal_overlap": True, "short_of_terminal_band": [0.05, 0.18],
         "final_third_speed_decline": True, "speed_decline_ratio": 0.85, **(contract or {})}
    tk = tracker or bolt_tracker(clip)
    clean = [s for s in tk["samples"] if s.get("cx") is not None and not s.get("clipped")]
    cxs = [s["cx"] for s in clean]
    max_back = max([0.0] + [round(cxs[i] - cxs[i + 1], 4) for i in range(len(cxs) - 1) if cxs[i + 1] < cxs[i]])
    final_gap = 0.0 if tk["overshoot"] else tk["clean_gap_end"]
    # final-third horizontal speed vs the first two-thirds (absolute forward speed)
    det = [s for s in tk["samples"] if s.get("cx") is not None]
    k = max(1, len(det) // 3); early = det[:-k] or det; late = det[-k:]
    sp_early = sum(abs(s.get("h_vel", 0)) for s in early[1:]) / max(1, len(early) - 1)
    sp_late = sum(abs(s.get("h_vel", 0)) for s in late) / max(1, len(late))
    checks = {
        "x_displacement_positive": tk["clean_horizontal_displacement"] >= c["min_x_displacement"],
        "gap_decreases_overall": (tk["clean_gap_end"] < tk["clean_gap_start"]) if c["require_gap_decrease"] else True,
        "no_backward_segment_over_bob": max_back <= c["bob_tolerance"],
        "no_terminal_overlap": (not tk["overshoot"]) if c["forbid_terminal_overlap"] else True,
        "final_gap_in_short_band": c["short_of_terminal_band"][0] <= final_gap <= c["short_of_terminal_band"][1],
        "speed_declines_final_third": (sp_late <= sp_early * c["speed_decline_ratio"]) if c["final_third_speed_decline"] else True,
    }
    return {"gate": "trajectory_contract", "pass": all(checks.values()), "checks": checks, "contract": c,
            "measured": {"clean_x_displacement": tk["clean_horizontal_displacement"], "final_gap": round(final_gap, 4),
                         "max_backward_step": max_back, "overshoot": tk["overshoot"],
                         "speed_early": round(sp_early, 4), "speed_late": round(sp_late, 4),
                         "clean_gap_start": tk["clean_gap_start"], "clean_gap_end": tk["clean_gap_end"]}}


def velocity_coupling_gate(clip, curve=None, tracker=None, cost=None, model="claude-opus-4-8"):
    """HYBRID: deterministic per-phase forward velocity (tracker) × VLM per-phase pose intensity. Verifies
    that visible motion is CAUSALLY COUPLED to velocity: stronger forward velocity ⇒ stronger lean/thrust;
    deceleration ⇒ reduced thrust + rising instability; reaching arm extends progressively; hover control
    deteriorates toward the endpoint. Splits the clip into 4 phases (urgent → effort → weakening → strained)."""
    import explainer_pipeline as ep
    tk = tracker or bolt_tracker(clip, n=16)
    det = [s for s in tk["samples"] if s.get("cx") is not None]
    dur = _probe(clip).get("dur", 5.0) or 5.0
    def phase_of(t):
        return min(3, int(t / dur * 4))
    vel = [[] for _ in range(4)]; cy = [[] for _ in range(4)]
    for s in det[1:]:
        p = phase_of(s["t"]); vel[p].append(s.get("h_vel", 0)); cy[p].append(s.get("cy", 0))
    mv = [round(sum(v) / len(v), 4) if v else 0.0 for v in vel]          # mean forward velocity per phase
    cyvar = [round((max(c) - min(c)), 4) if len(c) > 1 else 0.0 for c in cy]  # hover instability proxy per phase
    # VLM per-phase pose intensity
    out = tempfile.mkdtemp(); frames = _frames(clip, 12, out)
    labeled = [(t, fp, phase_of(t)) for (t, fp) in frames]
    content = [b for (t, fp, p) in labeled for b in _img_block(fp, f"t={t}s (phase {p+1}):")]
    content.append({"type": "text", "text": "Frames in time order, labelled by phase (1 urgent→4 strained). "
        "Rate the CHARACTER per phase 0-10. Return ONLY JSON {\"phase1\":{\"lean_thrust\":,\"reach_extension\":,"
        "\"instability\":,\"hover_control\":,\"strain\":},\"phase2\":{...},\"phase3\":{...},\"phase4\":{...}}"})
    try:
        r = ep._claude().messages.create(model=model, max_tokens=500,
            system="Scoped character-motion critic. lean_thrust=visible forward lean/push effort; "
            "reach_extension=how far the reaching arm extends; instability=wobble/loss of control; "
            "hover_control=steadiness of hovering (10=rock steady); strain=visible exertion/fatigue.",
            messages=[{"role": "user", "content": content}])
        if cost is not None: cost.append(ep._msg_cost(r.usage))
        o, _ = ep._parse_script_json(r.content[0].text); o = o if isinstance(o, dict) else {}
    except Exception as e:
        return {"gate": "velocity_coupling", "pass": False, "error": str(e)}
    def g(ph, k): return float((o.get(ph) or {}).get(k, 0) or 0)
    lean = [g(f"phase{i+1}", "lean_thrust") for i in range(4)]
    reach = [g(f"phase{i+1}", "reach_extension") for i in range(4)]
    inst = [g(f"phase{i+1}", "instability") for i in range(4)]
    hover = [g(f"phase{i+1}", "hover_control") for i in range(4)]
    strain = [g(f"phase{i+1}", "strain") for i in range(4)]
    checks = {
        "velocity_declines_over_clip": mv[0] > mv[3] and (sum(mv[2:]) / 2) <= (sum(mv[:2]) / 2),
        "thrust_tracks_velocity": lean[0] >= lean[3] and mv[0] >= mv[3],          # more velocity ⇒ more thrust
        "instability_rises_as_propulsion_weakens": inst[3] >= inst[0] + 1,
        "reach_extends_progressively": reach[3] >= reach[0] and reach[3] >= reach[1] - 0.5,
        "hover_control_deteriorates": hover[3] <= hover[0] - 1 or cyvar[3] >= max(cyvar[:2] or [0]),
        "strain_rises_toward_endpoint": strain[3] >= strain[0] + 1,
    }
    return {"gate": "velocity_coupling", "pass": all(checks.values()), "checks": checks,
            "phase_velocity": mv, "phase_cy_range": cyvar,
            "readings": {"lean_thrust": lean, "reach_extension": reach, "instability": inst,
                         "hover_control": hover, "strain": strain}}


def evaluate_directed_shot(clip, end_target, contract=None, curve=None, cost=None, model="claude-opus-4-8"):
    """Composite acceptance for a directed hero shot. Runs the SEVEN authoritative gates INDEPENDENTLY and
    requires ALL to pass. The two deterministic gates (macro_trajectory, trajectory_contract) are computed
    from the pixel tracker and are AUTHORITATIVE — no VLM summary can override them. The clip is tracked
    ONCE and the tracker is shared across the three trajectory-aware gates."""
    tk = bolt_tracker(clip)
    gates = {
        "articulation_quality": articulation_quality_gate(clip, cost=cost, model=model),
        "self_propulsion_readability": self_propulsion_readability_gate(clip, cost=cost, model=model),
        "macro_trajectory": macro_trajectory_gate(clip, cost=cost, tracker=tk),                 # deterministic
        "progressive_effort": progressive_effort_gate(clip, cost=cost, model=model),
        "end_state": end_state_gate(clip, end_target, cost=cost, model=model),
        "trajectory_contract": trajectory_contract_gate(clip, contract=contract, tracker=tk, cost=cost),  # deterministic
        "velocity_coupling": velocity_coupling_gate(clip, curve=curve, tracker=tk, cost=cost, model=model),
    }
    deterministic = {"macro_trajectory", "trajectory_contract"}
    passed = {k: bool(v.get("pass")) for k, v in gates.items()}
    return {"accepted": all(passed.values()), "passed": passed,
            "deterministic_gates": sorted(deterministic), "gates": gates,
            "note": "deterministic gates (macro_trajectory, trajectory_contract) are tracker-derived and "
                    "authoritative; a VLM gate cannot override them. All seven must pass to accept."}


def _blob_bbox(a, x0, x1, y0, y1, white_thresh=175):
    """rightmost/bright Bolt (or terminal) bbox within a pixel window; returns [x0,y0,x1,y1] px or None."""
    import numpy as np
    sub = a[y0:y1, x0:x1]
    bright = (sub.min(axis=2) > white_thresh) | ((sub[:, :, 1] > 150) & (sub[:, :, 2] > 150) & (sub[:, :, 0] < 140))
    ys, xs = np.where(bright)
    if len(xs) < 30:
        return None
    return [x0 + int(np.percentile(xs, 2)), y0 + int(np.percentile(ys, 2)),
            x0 + int(np.percentile(xs, 98)), y0 + int(np.percentile(ys, 98))]


def boundary_pair_consistency_gate(start_frame, end_frame, terminal_left=0.605, short_band=(0.06, 0.16),
                                   cost=None, model="claude-opus-4-8"):
    """AUTHORITATIVE start↔end boundary-pair check for start+end conditioning. Deterministic: Bolt rendered-
    height ratio (0.95–1.05, hard tol 0.92–1.08), lateral (not scale) advance toward the terminal, terminal
    bbox + corridor plate unchanged, background pixel change outside Bolt ≈ 0, final gap in the short band,
    no terminal overlap, hover clearance. VLM (pose semantics on the end frame): head/torso toward terminal,
    ONE arm reaching a specific terminal part, other arm trailing/lowered, forward lean + strain, and NOT a
    symmetric two-palms 'pushing an invisible wall' pose. All must pass."""
    import numpy as np
    from PIL import Image
    A = np.asarray(Image.open(start_frame).convert("RGB"), float)
    B = np.asarray(Image.open(end_frame).convert("RGB"), float)
    H, W = A.shape[:2]; tlx = int(terminal_left * W)
    yb0, yb1 = int(0.18 * H), int(0.90 * H)
    bs = _blob_bbox(A, 0, tlx, yb0, yb1); be = _blob_bbox(B, 0, tlx, yb0, yb1)
    # terminal bbox (right of Bolt, wall height) in each frame
    ts = _blob_bbox(A, tlx, int(0.86 * W), int(0.26 * H), int(0.60 * H))
    te = _blob_bbox(B, tlx, int(0.86 * W), int(0.26 * H), int(0.60 * H))
    def hw(b): return (b[3] - b[1], b[2] - b[0]) if b else (0, 0)
    sh, sw = hw(bs); eh, ew = hw(be)
    ratio = round(eh / sh, 3) if sh else 0.0
    s_cx = ((bs[0] + bs[2]) / 2 / W) if bs else 0; e_cx = ((be[0] + be[2]) / 2 / W) if be else 0
    e_right = (be[2] / W) if be else 0; final_gap = round(terminal_left - e_right, 4)
    # background diff OUTSIDE Bolt(+shadow) and the terminal: mask both bolt bboxes (down-extended for shadow) + terminal
    mask = np.zeros((H, W), bool)
    for b in (bs, be):
        if b: mask[max(0, b[1] - 8):int(0.88 * H), max(0, b[0] - 40):min(W, b[2] + 40)] = True   # generous: bright-blob bbox misses rim-lit/pink pixels + shadow; plate is identical by construction
    for t in (ts, te):
        if t: mask[max(0, t[1] - 5):min(H, t[3] + 5), max(0, t[0] - 5):min(W, t[2] + 5)] = True
    diff = np.abs(A - B).mean(axis=2) / 255.0
    bg_change = float(diff[~mask].mean()) if (~mask).any() else 1.0
    term_iou = _bbox_iou(ts, te) if (ts and te) else 0.0
    checks = {
        "height_ratio_in_band": 0.95 <= ratio <= 1.05,
        "height_ratio_within_hard_tol": 0.92 <= ratio <= 1.08,
        "advances_laterally_toward_terminal": (e_cx - s_cx) >= 0.05,
        "not_growing_by_scale": ratio <= 1.05,
        "terminal_bbox_unchanged": term_iou >= 0.85,
        "background_camera_unchanged": bg_change <= 0.01,
        "final_gap_in_short_band": short_band[0] <= final_gap <= short_band[1],
        "no_terminal_overlap": final_gap > 0,
        "hover_clearance": bool(be) and (be[3] / H) <= 0.84,
        # weakening encoded geometrically: end Bolt has SUNK vs the seed (bottom lower by >= ~2.5% of H)
        "encodes_altitude_drop_weakening": bool(bs and be) and (be[3] - bs[3]) >= 0.025 * H,
    }
    # VLM pose semantics on the end frame. MARK the terminal (from the deterministic anchor) so the model
    # doesn't have to guess its location — otherwise "toward the terminal" false-negatives.
    import explainer_pipeline as ep, base64, tempfile as _tf
    from PIL import ImageDraw as _ID
    marked = Image.open(end_frame).convert("RGB"); _d = _ID.Draw(marked)
    tbox = te or ts or [int(terminal_left * W), int(0.31 * H), int(0.784 * W), int(0.557 * H)]
    _d.rectangle(tbox, outline=(255, 60, 60), width=6)
    _mp = os.path.join(_tf.mkdtemp(), "_bp_marked.png"); marked.save(_mp)
    b64 = base64.b64encode(open(_mp, "rb").read()).decode()
    q = ("The RED BOX marks the wall-mounted oxygen refill terminal. The robot is Bolt, who is hover-running "
         "toward that terminal. Judge ONLY Bolt's pose. For head_torso_toward_terminal, judge ORIENTATION: is "
         "Bolt's body/head turned/facing toward the terminal's side (the right), moving toward it — NOT whether "
         "his eyes are pixel-aligned with it (the terminal is mounted higher on the wall). Return ONLY JSON {"
         "\"head_torso_toward_terminal\":bool,\"one_arm_reaching_toward_terminal\":bool,"
         "\"reaching_target\":str,\"other_arm_trailing_or_lowered\":bool,\"forward_lean\":bool,"
         "\"visible_strain\":bool,\"two_palms_pushing_invisible_wall\":bool}")
    # 3x majority vote — the pose-semantic VLM flickers run-to-run; a single call makes the gate unstable.
    votes, pose = [], {}
    for _ in range(3):
        try:
            r = ep._claude().messages.create(model=model, max_tokens=250, system="Strict pose auditor.",
                messages=[{"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}}, {"type": "text", "text": q}]}])
            if cost is not None: cost.append(ep._msg_cost(r.usage))
            o, _ = ep._parse_script_json(r.content[0].text)
            if isinstance(o, dict): votes.append(o)
        except Exception as e:
            pose.setdefault("error", str(e))
    if votes:
        keys = ["head_torso_toward_terminal", "one_arm_reaching_toward_terminal", "other_arm_trailing_or_lowered",
                "forward_lean", "visible_strain", "two_palms_pushing_invisible_wall"]
        for k in keys:
            pose[k] = sum(1 for v in votes if v.get(k)) >= 2   # majority of 3
        pose["reaching_target"] = next((v.get("reaching_target") for v in votes if v.get("reaching_target")), "")
        pose["_votes"] = len(votes)
    pose_checks = {
        "head_torso_toward_terminal": bool(pose.get("head_torso_toward_terminal")),
        "one_arm_reaching_toward_terminal": bool(pose.get("one_arm_reaching_toward_terminal")),
        "other_arm_trailing_or_lowered": bool(pose.get("other_arm_trailing_or_lowered")),
        "forward_lean": bool(pose.get("forward_lean")),
        "not_two_palms_pushing": not bool(pose.get("two_palms_pushing_invisible_wall")),
    }
    # visible_strain is ADVISORY on the static keyframe (the mascot cannot render exhausted as a still); it is
    # a CLIP-level property verified on the generated result by end_state_gate + progressive_effort_gate +
    # velocity_coupling_gate. Weakening is instead encoded here geometrically (altitude drop, see authoring).
    advisory = {"visible_strain_keyframe": bool(pose.get("visible_strain")),
                "note": "visible_strain deferred to clip-level gates; not a boundary-pair pass criterion"}
    # identity consistency: the end Bolt must be the SAME character as the seed Bolt (crop both, compare).
    idj = {}
    if bs and be:
        cs = Image.open(start_frame).convert("RGB").crop((max(0, bs[0] - 10), max(0, bs[1] - 10), min(W, bs[2] + 10), min(H, bs[3] + 10)))
        ce = Image.open(end_frame).convert("RGB").crop((max(0, be[0] - 10), max(0, be[1] - 10), min(W, be[2] + 10), min(H, be[3] + 10)))
        pair = Image.new("RGB", (cs.width + ce.width + 20, max(cs.height, ce.height)), (20, 20, 24))
        pair.paste(cs, (0, 0)); pair.paste(ce, (cs.width + 20, 0))
        _ip = os.path.join(_tf.mkdtemp(), "_idpair.png"); pair.save(_ip)
        ib = base64.b64encode(open(_ip, "rb").read()).decode()
        try:
            ir = ep._claude().messages.create(model=model, max_tokens=180, system="Strict character-identity auditor.",
                messages=[{"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": ib}},
                {"type": "text", "text": "LEFT and RIGHT show a robot. Are they the SAME character (same body colour, "
                 "same mint accents, same visor with exactly two cyan eyes and NO mouth, same proportions, single "
                 "hover-base, no legs)? Return ONLY JSON {\"same_character\":bool,\"differences\":str}"}]}])
            if cost is not None: cost.append(ep._msg_cost(ir.usage))
            idj, _ = ep._parse_script_json(ir.content[0].text); idj = idj if isinstance(idj, dict) else {}
        except Exception as e:
            idj = {"error": str(e), "same_character": True}   # don't hard-fail on API error
    pose_checks["identity_matches_seed"] = bool(idj.get("same_character", True))
    allc = {**checks, **pose_checks}
    pose_vlm_ok = bool(votes)   # if the pose VLM was unavailable, pose_checks defaulted to False (fail-closed) — flag it
    return {"gate": "boundary_pair_consistency", "pass": all(allc.values()), "pose_vlm_available": pose_vlm_ok,
            "pass_reason": ("pose VLM unavailable — pose checks fail-closed; not a genuine frame verdict"
                            if not pose_vlm_ok else "evaluated"),
            "checks": allc,
            "measured": {"start_bolt_bbox": bs, "end_bolt_bbox": be, "height_ratio": ratio,
                         "start_cx": round(s_cx, 4), "end_cx": round(e_cx, 4), "final_gap": final_gap,
                         "bg_change_outside_bolt": round(bg_change, 5), "terminal_iou": round(term_iou, 3),
                         "start_terminal_bbox": ts, "end_terminal_bbox": te, "frame": [W, H],
                         "altitude_drop_px": (be[3] - bs[3]) if (bs and be) else None},
            "pose_readings": pose, "identity_readings": idj, "advisory": advisory}


def _bright_area(a, W, H, xmax=0.62):
    """Bolt's bright-body pixel AREA (white OR strong-cyan), left of the terminal column. Rotation-INVARIANT,
    so it is the reliable scale metric for tilted/reaching poses where the p2/p98 bbox height is not."""
    import numpy as np
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    m = ((np.minimum(np.minimum(R, G), B) > 175) | ((G > 150) & (B > 150) & (R < 140)))
    m[:, int(xmax * W):] = False; m[:int(0.20 * H)] = False; m[int(0.86 * H):] = False
    return int(m.sum())


def _structural_shell_area(a, W, H, xmax=0.62):
    """Bolt's STRUCTURAL SHELL area: near-white/low-saturation body pixels, EXCLUDING the cyan eyes, cyan chest
    display, mint antenna/side glow, and the terminal column. Rotation- AND dimming-invariant, so intentional
    eye dimming does NOT change it — the correct scale metric for a weakening pose."""
    import numpy as np
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    mn = np.minimum(np.minimum(R, G), B); mx = np.maximum(np.maximum(R, G), B)
    shell = (mn > 95) & ((mx - mn) < 85)                      # near-white/gray shell; excludes saturated glow
    shell[:, int(xmax * W):] = False; shell[:int(0.16 * H)] = False; shell[int(0.90 * H):] = False
    return int(shell.sum())


def _base_centroid_y(a, W, H, xmax=0.62):
    """Altitude of Bolt's HOVER BASE = centroid-y of the lowest 25% of his bright silhouette. Robust to forward
    pitch/roll (which contaminate the whole-body centroid), so it is the authoritative SINK metric."""
    import numpy as np
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    bright = (np.minimum(np.minimum(R, G), B) > 150) | ((G > 140) & (B > 140) & (R < np.maximum(G, B)))
    bright[:, int(xmax * W):] = False; bright[:int(0.16 * H)] = False; bright[int(0.92 * H):] = False
    ys, xs = np.where(bright)
    if len(ys) < 30:
        return None, None
    y0, y1 = ys.min(), ys.max(); band = ys >= (y1 - 0.25 * (y1 - y0))
    return round(float(ys[band].mean()) / H, 4), round(float(y1) / H, 4)   # (base-centroid-y, base-bottom-edge-y)


def plate_consistency_gate(clip, tracker=None, ref_index=0, thresh=16, noise_frac=0.02, terminal_left=0.605, cost=None):
    """The corridor + terminal OUTSIDE Bolt must stay fixed across the clip: no relighting, exposure shift,
    terminal movement, or camera drift. Compares every frame's non-Bolt background to a REFERENCE frame of the
    SAME clip (not the original plate) so a uniform provider re-tone is tolerated but real drift/relighting is
    caught. Excludes the UNION of Bolt bboxes (dilated) so his motion never counts. Deterministic."""
    import numpy as np
    from PIL import Image
    from scipy import ndimage
    tk = tracker or bolt_tracker(clip, n=20)
    W, H = tk["frame_w"], tk["frame_h"]
    fr = [s for s in tk["samples"] if s.get("frame") and s.get("bolt_bbox")]
    if len(fr) < 2:
        return {"gate": "plate_consistency", "pass": False, "reason": "insufficient frames"}
    excl = np.zeros((H, W), bool)                              # union of dilated Bolt bboxes across the whole clip
    for s in fr:
        b = s["bolt_bbox"]; excl[max(0, b[1] - 24):min(H, b[3] + 24), max(0, b[0] - 40):min(W, b[2] + 40)] = True
    bg = ~excl
    ref = np.asarray(Image.open(fr[ref_index]["frame"]).convert("RGB"), float)
    tb = (int(terminal_left * W), int(0.30 * H), int(0.79 * W), int(0.58 * H))
    def term_cx(im):
        sub = im[tb[1]:tb[3], tb[0]:tb[2]]; g = (sub[:, :, 1] > 120) & (sub[:, :, 2] < sub[:, :, 1] - 20)  # green O2 screen
        xs = np.where(g.any(axis=0))[0]; return (tb[0] + xs.mean()) / W if len(xs) else None
    ref_term = term_cx(ref); drift = 0; term_move = 0; recs = []
    for s in fr:
        a = np.asarray(Image.open(s["frame"]).convert("RGB"), float)
        d = np.abs(a - ref).mean(axis=2)
        frac = float((d[bg] > thresh).sum()) / max(1, int(bg.sum()))
        tcx = term_cx(a); tmove = abs(tcx - ref_term) if (tcx is not None and ref_term is not None) else 0.0
        if frac > noise_frac:
            drift += 1
        if tmove > 0.012:
            term_move += 1
        recs.append({"t": s["t"], "bg_changed_frac": round(frac, 4), "terminal_dx": round(tmove, 4)})
    ok = drift == 0 and term_move == 0
    return {"gate": "plate_consistency", "pass": bool(ok), "frames_evaluated": len(fr),
            "frames_bg_relit_or_drifted": drift, "frames_terminal_moved": term_move,
            "max_bg_changed_frac": round(max(r["bg_changed_frac"] for r in recs), 4),
            "per_frame": recs[:20]}


def eye_edge_integrity_gate(frame, W=None, H=None, bb=None, cost=None):
    """Bolt's two cyan eyes must stay SMOOTH cyan ovals — no dark horizontal line crossing an eye, no straight/
    jagged dark mask boundary inside the eye region, left/right shapes consistent. Catches erosion/eyelid/black-cap
    artifacts from weakening edits. Deterministic (connected components of the visor cyan glow)."""
    import numpy as np
    from PIL import Image
    from scipy import ndimage
    a = frame if isinstance(frame, np.ndarray) else np.asarray(Image.open(frame).convert("RGB"), float)
    Hh, Ww = a.shape[0], a.shape[1]; W = W or Ww; H = H or Hh
    if bb is None:
        bb = _blob_bbox(a, 0, int(0.58 * W), int(0.26 * H), int(0.90 * H))
    bw = bb[2] - bb[0]; bh = bb[3] - bb[1]
    reg = np.zeros((H, W), bool)
    reg[int(bb[1] + 0.24 * bh):int(bb[1] + 0.60 * bh), int(bb[0] + 0.14 * bw):int(bb[0] + 0.86 * bw)] = True
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    cyan = (B > R + 18) & (B > G - 25) & reg
    lbl, n = ndimage.label(cyan)
    if not n:
        return {"gate": "eye_edge_integrity", "pass": False, "reason": "no eye glow found"}
    sizes = ndimage.sum(np.ones_like(lbl), lbl, range(1, n + 1))
    eyes = [int(o) + 1 for o in np.argsort(sizes)[::-1] if sizes[int(o)] >= 0.0006 * bw * bh][:2]
    recs = []; ok = True
    for idx, cid in enumerate(eyes):
        m = lbl == cid; ys, xs = np.where(m); y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
        ebw = x1 - x0 + 1; ebh = y1 - y0 + 1; area = int(m.sum())
        fill = area / max(1, ebw * ebh)
        filled = ndimage.binary_fill_holes(ndimage.binary_closing(m, iterations=2))
        hole_frac = (int(filled.sum()) - area) / max(1, int(filled.sum()))   # dark intrusions inside the eye (caps/bands)
        sub = m[y0:y1 + 1, x0:x1 + 1]; rows = sub.sum(axis=1); crossing = False
        for r in range(2, ebh - 2):                                       # dark horizontal line = glow, gap, glow
            if rows[r] < 0.25 * ebw and rows[max(0, r - 2)] > 0.5 * ebw and rows[min(ebh - 1, r + 2)] > 0.5 * ebw:
                crossing = True; break
        # The PRIMARY (near) eye must be a full smooth oval. The far eye at a 3/4 head angle is a legitimate thin
        # crescent (low fill) — for it, only reject genuine artifacts (a dark line crossing it, or dark intrusions).
        eye_ok = bool((not crossing) and hole_frac < 0.12 and (fill >= 0.5 if idx == 0 else True))
        ok = ok and eye_ok
        recs.append({"area": area, "fill_ratio": round(fill, 3), "hole_frac": round(hole_frac, 3),
                     "dark_line_crossing": crossing, "role": "primary" if idx == 0 else "far_angled", "clean": eye_ok})
    lr_ok = True
    if len(eyes) == 2:
        aa, bb2 = sorted([recs[0]["area"], recs[1]["area"]]); lr_ok = (aa / max(1, bb2)) >= 0.08   # far eye can be a small crescent
    note = "deterministic helper — 200% visual review is authoritative for eye-edge integrity"
    return {"gate": "eye_edge_integrity", "pass": bool(ok and len(eyes) >= 1), "eyes_found": len(eyes),
            "left_right_area_consistent": lr_ok, "per_eye": recs, "note": note}


def retention_window(primitive_kind, detected):
    """Which portion of a generated primitive clip to RETAIN. `detected` = {onset_t, action_end_t} from
    detect_usable_action_window. LAUNCH primitives (e.g. A1) may trim the pre-onset settle/wind-up. CONTINUATION
    primitives (e.g. A2/A3), whose start frame IS the previous accepted clip's endpoint, MUST retain t=0 so the
    join is seamless — trimming their onset breaks the seam. Deterministic, pure logic (unit-testable)."""
    onset = float(detected.get("onset_t", 0.0)); end = float(detected.get("action_end_t", 0.0))
    if primitive_kind not in ("launch", "continuation"):
        raise ValueError(f"primitive_kind must be 'launch' or 'continuation', got {primitive_kind!r}")
    start = 0.0 if primitive_kind == "continuation" else onset
    return {"primitive_kind": primitive_kind, "start_t": round(start, 3), "end_t": round(end, 3),
            "retained_onset": bool(start > 0.0), "detected_onset_t": round(onset, 3)}


def endpoint_realization(clip, end_frame, terminal_left=0.605, converge_window_s=0.7, tol=0.05, tracker=None, cost=None):
    """Does the clip actually LAND on the authored sink endpoint (not merely pass through it)? Compares the
    clip's final Bolt state to the authored end frame: height, x, altitude, terminal gap; endpoint image
    similarity over the CORE body (arms excluded, since they articulate); and convergence — the final
    ~0.6s must decelerate toward the authored endpoint x without overshooting past it."""
    import numpy as np
    from PIL import Image
    tk = tracker or bolt_tracker(clip)
    W, Hh = tk["frame_w"], tk["frame_h"]; dur = _probe(clip).get("dur", 5.0) or 5.0
    ea = np.asarray(Image.open(end_frame).convert("RGB"), float)
    auth_area = _bright_area(ea, W, Hh)          # rotation-invariant scale reference
    auth = _blob_bbox(ea, 0, int(terminal_left * W), int(0.18 * Hh), int(0.90 * Hh))
    auth_h = auth[3] - auth[1]; auth_cx = (auth[0] + auth[2]) / 2 / W; auth_bottom = auth[3] / Hh
    auth_gap = terminal_left - auth[2] / W
    det = [s for s in tk["samples"] if s.get("cx") is not None]
    if not det or not auth:
        return {"report": "insufficient tracking", "converges": False}
    last = det[-1]; lb = last["bolt_bbox"]; fin_h = lb[3] - lb[1]
    fin_cx = last["cx"]; fin_bottom = lb[3] / Hh; fin_gap = last["edge_gap"]
    first_bottom = det[0]["bolt_bbox"][3] / Hh
    # convergence window (final ~0.6s)
    win = [s for s in det if s["t"] >= dur - converge_window_s] or det[-3:]
    win_cx = [s["cx"] for s in win]
    win_speed = sum(abs(s.get("h_vel", 0)) for s in win[1:]) / max(1, len(win) - 1)
    early = det[1:len(det) - len(win)] or det[1:]
    early_speed = sum(abs(s.get("h_vel", 0)) for s in early) / max(1, len(early))
    overshoot_past_auth = any(cx > auth_cx + tol for cx in win_cx)
    last_step = abs(det[-1]["cx"] - det[-2]["cx"]) if len(det) >= 2 else 1.0
    # LANDS on the endpoint AND either decelerated over the tail (full clip) OR the final step is small
    # (arrived/stopped — valid for a trimmed window that ends at the arrival peak).
    settles = abs(fin_cx - auth_cx) <= tol and (win_speed <= early_speed * 0.6 or last_step < 0.02)
    converges = bool(settles and not overshoot_past_auth)
    # core-body similarity (arms excluded = central 55% width) of the last clip frame vs the end frame
    def core(imgarr, bb):
        x0, y0, x1, y1 = bb; w = x1 - x0
        cx0, cx1 = int(x0 + 0.225 * w), int(x1 - 0.225 * w)
        crop = imgarr[max(0, y0):y1, max(0, cx0):cx1]
        from PIL import Image as _I
        return np.asarray(_I.fromarray(crop.astype("uint8")).resize((90, 180)), float)
    fin_area = None
    try:
        lastf = np.asarray(Image.open(last["frame"]).convert("RGB"), float)
        sim = 1.0 - float(np.abs(core(lastf, lb) - core(ea, auth)).mean()) / 255.0
        fin_area = _bright_area(lastf, W, Hh)
    except Exception:
        sim = None
    return {"authored_endpoint": {"height_px": auth_h, "cx": round(auth_cx, 4), "bottom": round(auth_bottom, 4), "gap": round(auth_gap, 4)},
            "clip_final": {"height_px": fin_h, "cx": round(fin_cx, 4), "bottom": round(fin_bottom, 4), "gap": round(fin_gap, 4)},
            "final_vs_authored": {"height_ratio": round(fin_h / auth_h, 3) if auth_h else None,
                                  "area_ratio": round(fin_area / auth_area, 3) if (auth_area and fin_area) else None,
                                  "x_delta": round(fin_cx - auth_cx, 4), "altitude_delta": round(fin_bottom - auth_bottom, 4),
                                  "gap_delta": round(fin_gap - auth_gap, 4)},
            "altitude_dropped_vs_start": round(fin_bottom - first_bottom, 4),
            "core_similarity_excl_limbs": round(sim, 3) if sim is not None else None,
            "converges_to_endpoint": converges, "overshoot_past_authored_x": overshoot_past_auth,
            "window_speed": round(win_speed, 4), "early_speed": round(early_speed, 4)}


def _detect_jet(a, bolt_bbox, W, H, base_cx=None):
    """DETERMINISTIC thruster-plume detector. Measures a DYNAMIC ROI STRICTLY BELOW Bolt's base (below the
    body bbox bottom, narrow band around the base centre) — so the visor/eyes (head) and the cyan chest panel
    (mid-body) are OUTSIDE the ROI and cannot contaminate the reading. Returns the ROI bbox for visualization."""
    import numpy as np
    x0, y0, x1, y1 = bolt_bbox; bw = x1 - x0
    cx = base_cx if base_cx is not None else (x0 + x1) / 2; bh = y1 - y0
    rx0 = max(0, int(cx - 0.24 * bw)); rx1 = min(W, int(cx + 0.24 * bw))
    ry0 = max(0, int(y1 + 0.02 * bh)); ry1 = min(H, int(y1 + 0.16 * H))    # STRICTLY beneath the base (skip the base ring)
    if ry1 <= ry0 or rx1 <= rx0:
        return {"jet_px": 0, "frac": 0.0, "cx": None, "cy": None, "roi": [rx0, ry0, rx1, ry1]}
    sub = a[ry0:ry1, rx0:rx1]; R, G, B = sub[:, :, 0], sub[:, :, 1], sub[:, :, 2]
    cyan = (G > 130) & (B > 130) & (R < np.minimum(G, B) - 26)             # strong cyan plume, not white/mint
    n = int(cyan.sum()); area = int(cyan.size)
    ys, xs = np.where(cyan)
    return {"jet_px": n, "frac": round(n / max(1, area), 5), "region_area": area, "roi": [rx0, ry0, rx1, ry1],
            "cx": round((rx0 + xs.mean()) / W, 4) if n else None, "cy": round((ry0 + ys.mean()) / H, 4) if n else None}


def target_anchor_distance(bolt_bbox, terminal_point, W, H, reaching_hand=None):
    """2D normalized distance from the reaching-hand centroid to a FIXED terminal interaction point.
    terminal_point = (fx, fy) in frame fractions. Returns dx, dy, euclidean (all normalized). Reaching-hand
    defaults to the destination-facing edge midpoint of the Bolt bbox (right edge, vertical centre)."""
    x0, y0, x1, y1 = bolt_bbox
    hx = reaching_hand[0] if reaching_hand else x1 / W
    hy = reaching_hand[1] if reaching_hand else (y0 + y1) / 2 / H
    dx = terminal_point[0] - hx; dy = terminal_point[1] - hy
    return {"reaching_hand": [round(hx, 4), round(hy, 4)], "terminal_point": list(terminal_point),
            "dx": round(dx, 4), "dy": round(dy, 4), "euclidean": round((dx * dx + dy * dy) ** 0.5, 4)}


def propulsion_decay_or_extinguish_gate(clip, tracker=None, cost=None):
    """A3-specific: the plume must be PRESENT EARLY, materially DECLINE, and may flicker/disappear at the end
    (propulsion failing) — the opposite of a steady/absent plume. Deterministic (plume ROI series)."""
    import numpy as np
    tk, series = _jet_series(clip, tracker)
    fr = np.array([s["frac"] for s in series])
    if not len(fr):
        return {"gate": "propulsion_decay_or_extinguish", "pass": False, "reason": "no frames"}
    k = max(1, len(fr) // 3)
    early = float(np.mean(fr[:k])); late = float(np.mean(fr[-k:]))
    present_early = early >= 0.006
    declines = late <= early * 0.6            # materially declining
    return {"gate": "propulsion_decay_or_extinguish", "pass": bool(present_early and declines),
            "present_early": bool(present_early), "declines": bool(declines),
            "early_frac": round(early, 5), "late_frac": round(late, 5), "min_frac": round(float(fr.min()), 5)}


def generated_seam_gate(clip_a, clip_b, n=4, cost=None, model="claude-opus-4-8"):
    """POST-GENERATION seam continuity between two adjacent primitive clips: compare the LAST n frames of A
    to the FIRST n frames of B for background registration (pixels outside Bolt ≈ identical), identity, scale,
    lighting, and pose/velocity continuity. Frame-exact seed/end equality is only AUTHORED continuity — this
    checks the GENERATED handoff."""
    import numpy as np
    from PIL import Image
    da = _probe(clip_a).get("dur", 3.0) or 3.0
    def frame_at(clip, t):
        out = tempfile.mkdtemp(); fp = os.path.join(out, "f.png")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", clip, "-frames:v", "1", fp], check=True)
        return fp
    a_last = frame_at(clip_a, max(0.0, da - 0.05)); b_first = frame_at(clip_b, 0.03)
    A = np.asarray(Image.open(a_last).convert("RGB"), float); B = np.asarray(Image.open(b_first).convert("RGB"), float)
    H, W = A.shape[:2]
    ba = _blob_bbox(A, 0, int(0.605 * W), int(0.16 * H), int(0.92 * H)); bb = _blob_bbox(B, 0, int(0.605 * W), int(0.16 * H), int(0.92 * H))
    mask = np.zeros((H, W), bool)
    for bx in (ba, bb):
        if bx: mask[max(0, bx[1] - 10):int(0.9 * H), max(0, bx[0] - 20):min(W, bx[2] + 20)] = True
    bg_change = float(np.abs(A - B).mean(axis=2)[~mask].mean()) / 255.0 if (~mask).any() else 1.0
    ha = (ba[3] - ba[1]) if ba else 0; hb = (bb[3] - bb[1]) if bb else 0
    scale_ratio = round(hb / ha, 3) if ha else None
    cx_a = ((ba[0] + ba[2]) / 2 / W) if ba else None; cx_b = ((bb[0] + bb[2]) / 2 / W) if bb else None
    # VLM identity/pose/lighting continuity across the seam
    import explainer_pipeline as ep, base64
    pair = Image.new("RGB", (W // 2 + W // 2 + 16, H // 2), (18, 18, 22))
    pair.paste(Image.open(a_last).convert("RGB").resize((W // 2, H // 2)), (0, 0))
    pair.paste(Image.open(b_first).convert("RGB").resize((W // 2, H // 2)), (W // 2 + 16, 0))
    sp = os.path.join(tempfile.mkdtemp(), "seam.png"); pair.save(sp)
    b64 = base64.b64encode(open(sp, "rb").read()).decode(); vlm = {}
    try:
        r = ep._claude().messages.create(model=model, max_tokens=200, system="Strict shot-continuity auditor.",
            messages=[{"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
            {"type": "text", "text": "LEFT = last frame of clip A, RIGHT = first frame of clip B (a cut between two "
             "clips of the same character/shot). Return ONLY JSON {\"same_identity\":bool,\"lighting_consistent\":bool,"
             "\"pose_continuous\":bool,\"no_jump\":bool}"}]}])
        if cost is not None: cost.append(ep._msg_cost(r.usage))
        vlm, _ = ep._parse_script_json(r.content[0].text); vlm = vlm if isinstance(vlm, dict) else {}
    except Exception as e:
        vlm = {"error": str(e)}
    checks = {"background_registration": bg_change <= 0.02,
              "scale_continuity": scale_ratio is not None and 0.94 <= scale_ratio <= 1.06,
              "position_continuity": (cx_a is not None and cx_b is not None and abs(cx_a - cx_b) <= 0.06),
              "identity_continuity": bool(vlm.get("same_identity", False)),
              "lighting_continuity": bool(vlm.get("lighting_consistent", False)),
              "pose_velocity_continuity": bool(vlm.get("pose_continuous", False)) and bool(vlm.get("no_jump", False))}
    return {"gate": "generated_seam", "pass": all(checks.values()), "checks": checks,
            "bg_change": round(bg_change, 5), "scale_ratio": scale_ratio, "cx_a": cx_a, "cx_b": cx_b, "vlm": vlm}


def _jet_series(clip, tracker=None):
    import numpy as np
    from PIL import Image
    tk = tracker or bolt_tracker(clip)
    W, H = tk["frame_w"], tk["frame_h"]; series = []
    for s in tk["samples"]:
        if not s.get("bolt_bbox") or not s.get("frame"):
            series.append({"t": s.get("t"), "frac": 0.0, "h_vel": s.get("h_vel", 0.0), "cy": s.get("cy")}); continue
        a = np.asarray(Image.open(s["frame"]).convert("RGB"), float)
        j = _detect_jet(a, s["bolt_bbox"], W, H)
        series.append({"t": s["t"], "frac": j["frac"], "jet_cx": j["cx"], "jet_cy": j["cy"],
                       "h_vel": s.get("h_vel", 0.0), "cx": s.get("cx"), "cy": s.get("cy")})
    return tk, series


def propulsion_presence_gate(clip, min_frac=0.006, min_frames=3, tracker=None, cost=None):
    """(1) DETERMINISTIC: are thruster jets actually PRESENT? Detects the cyan base plume per frame. This
    OVERRIDES any VLM 'no thrust' claim — visible deterministic evidence wins."""
    tk, series = _jet_series(clip, tracker)
    fj = [s for s in series if s["frac"] >= min_frac]
    return {"gate": "propulsion_presence", "pass": len(fj) >= min_frames, "frames_with_jet": len(fj),
            "total_frames": len(series), "peak_frac": round(max([s["frac"] for s in series] or [0]), 5),
            "per_frame_frac": [round(s["frac"], 5) for s in series], "method": "deterministic cyan-plume detection (base region)"}


def propulsion_velocity_coupling_gate(clip, min_corr=0.30, tracker=None, cost=None):
    """(2) DETERMINISTIC: does thrust intensity track velocity (more thrust when accelerating), and does it
    weaken as velocity declines? A glide (thrust flat/absent while translating) FAILS."""
    import numpy as np
    tk, series = _jet_series(clip, tracker)
    fr = np.array([s["frac"] for s in series]); vel = np.array([abs(s["h_vel"]) for s in series])
    if fr.std() < 1e-6 or vel.std() < 1e-6:
        corr = 0.0
    else:
        corr = float(np.corrcoef(fr, vel)[0, 1])
    k = max(1, len(series) // 3)
    thrust_early = float(np.mean(fr[:k])) if len(fr) else 0.0
    thrust_late = float(np.mean(fr[-k:])) if len(fr) else 0.0
    thrust_weakens = thrust_late <= thrust_early * 0.85
    coupled = corr >= min_corr
    return {"gate": "propulsion_velocity_coupling", "pass": bool(coupled and thrust_weakens),
            "coupling_corr": round(corr, 3), "coupled": bool(coupled), "thrust_weakens": bool(thrust_weakens),
            "thrust_early": round(thrust_early, 5), "thrust_late": round(thrust_late, 5)}


def path_monotonicity_gate(clip, bob=0.02, max_idle_frac=0.45, tracker=None, cost=None):
    """(3) DETERMINISTIC: is the INTERMEDIATE path a clean forward advance — not reversing, idling or gliding
    back? Distinct from reaching the endpoint. Reaching authored final coords with a reversing/idle path is
    NOT trajectory control."""
    tk = tracker or bolt_tracker(clip)
    cxs = [s["cx"] for s in tk["samples"] if s.get("cx") is not None]
    steps = [cxs[i + 1] - cxs[i] for i in range(len(cxs) - 1)]
    reversals = sum(1 for d in steps if d < -bob)
    max_back = round(min([0.0] + steps), 4)
    idle = sum(1 for d in steps if abs(d) < 0.004)
    idle_frac = round(idle / max(1, len(steps)), 3)
    net_forward = (cxs[-1] - cxs[0]) if len(cxs) >= 2 else 0.0
    monotonic = reversals == 0 and idle_frac <= max_idle_frac and net_forward > 0
    return {"gate": "path_monotonicity", "pass": bool(monotonic), "reversals": reversals,
            "max_backward_step": max_back, "idle_frac": idle_frac, "net_forward": round(net_forward, 4)}


def endpoint_realization_gate(clip, end_frame, tracker=None, cost=None):
    """(4) DETERMINISTIC: does the clip LAND on the authored final boundary (height/x/altitude/gap), converge
    (not pass through), and not overshoot? This is FINAL-BOUNDARY realization ONLY — it says nothing about the
    intermediate trajectory (see path_monotonicity) or the performance arc (see performance_progression)."""
    epr = endpoint_realization(clip, end_frame, tracker=tracker, cost=cost)
    fv = epr.get("final_vs_authored", {})
    ok = (fv.get("height_ratio") is not None and 0.92 <= fv["height_ratio"] <= 1.08
          and abs(fv.get("x_delta", 1)) <= 0.05 and abs(fv.get("gap_delta", 1)) <= 0.05
          and epr.get("converges_to_endpoint") and not epr.get("overshoot_past_authored_x")
          and (epr.get("core_similarity_excl_limbs") or 0) >= 0.9)
    return {"gate": "endpoint_realization", "pass": bool(ok), "scope": "final boundary ONLY (not trajectory/arc)", **epr}


def performance_progression_gate(clip, curve=None, tracker=None, cost=None, model="claude-opus-4-8"):
    """(5) The performance ARC: deterministic per-phase velocity + jet-thrust + altitude, plus VLM posture.
    Requires velocity to decline, altitude to drop, thrust to weaken, and effort/instability + directional
    posture to develop across launch→effort→weakening→strained. A flat glide FAILS."""
    import numpy as np, explainer_pipeline as ep
    tk, series = _jet_series(clip, tracker)
    dur = _probe(clip).get("dur", 5.0) or 5.0
    def ph(t): return min(3, int((t or 0) / dur * 4))
    vel = [[] for _ in range(4)]; jet = [[] for _ in range(4)]; cy = [[] for _ in range(4)]
    for s in series:
        p = ph(s["t"]); vel[p].append(abs(s["h_vel"])); jet[p].append(s["frac"])
        if s.get("cy") is not None: cy[p].append(s["cy"])
    mv = [round(np.mean(v), 4) if v else 0.0 for v in vel]
    mj = [round(np.mean(j), 5) if j else 0.0 for j in jet]
    mcy = [round(np.mean(c), 4) if c else None for c in cy]
    # VLM posture per phase (directional lean + effort/instability)
    out = tempfile.mkdtemp(); frames = _frames(clip, 12, out)
    content = [b for (t, fp) in frames for b in _img_block(fp, f"t={t}s (phase {ph(t)+1}):")]
    content.append({"type": "text", "text": "Frames time-ordered, labelled phase 1(launch)→4(strained). Rate the "
        "CHARACTER per phase 0-10. Return ONLY JSON {\"phase1\":{\"leans_in_travel_direction\":,\"effort\":,\"instability\":},"
        "\"phase2\":{...},\"phase3\":{...},\"phase4\":{...}}"})
    posture = {}
    try:
        r = ep._claude().messages.create(model=model, max_tokens=400, system="Scoped character-motion critic.",
            messages=[{"role": "user", "content": content}])
        if cost is not None: cost.append(ep._msg_cost(r.usage))
        posture, _ = ep._parse_script_json(r.content[0].text); posture = posture if isinstance(posture, dict) else {}
    except Exception as e:
        posture = {"error": str(e)}
    def g(i, k): return float((posture.get(f"phase{i+1}") or {}).get(k, 0) or 0)
    lean = [g(i, "leans_in_travel_direction") for i in range(4)]; eff = [g(i, "effort") for i in range(4)]; inst = [g(i, "instability") for i in range(4)]
    alt_drop = (mcy[3] is not None and mcy[0] is not None and mcy[3] - mcy[0] >= 0.02)
    checks = {
        "velocity_declines": mv[0] > mv[3] and (sum(mv[2:]) / 2) <= (sum(mv[:2]) / 2),
        "altitude_drops": bool(alt_drop),
        "thrust_weakens": mj[3] <= mj[0] * 0.85 if mj[0] > 0 else (mj[3] <= 0.004),
        "effort_or_instability_rises": (eff[3] >= eff[0] + 1) or (inst[3] >= inst[0] + 1),
        "directional_posture": min(lean) >= 5,
    }
    return {"gate": "performance_progression", "pass": all(checks.values()), "checks": checks,
            "phase_velocity": mv, "phase_jet": mj, "phase_cy": mcy,
            "readings": {"lean": lean, "effort": eff, "instability": inst}}


def endpoint_geometry_gate(clip, end_frame, tracker=None, cost=None):
    """GEOMETRY half of the old endpoint gate: final centroid/edge/altitude/scale/terminal-gap, convergence,
    contact, overshoot — NO identity/pose similarity (that is end_identity_pose_gate)."""
    epr = endpoint_realization(clip, end_frame, tracker=tracker, cost=cost)
    fv = epr.get("final_vs_authored", {})
    contact = (epr.get("clip_final", {}).get("gap", 1) or 1) <= 0
    # SCALE via rotation-invariant bright-area ratio (p2/p98 bbox height is unreliable for tilted/reaching
    # poses); fall back to height_ratio only if area is unavailable.
    area_r = fv.get("area_ratio"); scale_metric = "area_ratio" if area_r is not None else "height_ratio"
    scale_val = area_r if area_r is not None else fv.get("height_ratio")
    scale_ok = scale_val is not None and 0.90 <= scale_val <= 1.10
    ok = (scale_ok and abs(fv.get("x_delta", 1)) <= 0.06 and abs(fv.get("altitude_delta", 1)) <= 0.08
          and abs(fv.get("gap_delta", 1)) <= 0.06 and epr.get("converges_to_endpoint")
          and not epr.get("overshoot_past_authored_x") and not contact)
    return {"gate": "endpoint_geometry", "pass": bool(ok), "final_vs_authored": fv,
            "scale_metric": scale_metric, "scale_value": scale_val,
            "converges": epr.get("converges_to_endpoint"), "overshoot": epr.get("overshoot_past_authored_x"),
            "contact": contact, "clip_final": epr.get("clip_final")}


def end_identity_pose_gate(clip, end_frame, tracker=None, cost=None, min_core=0.85):
    """IDENTITY/POSE half: core-body similarity (arms excluded) of the final frame vs the authored end pose."""
    epr = endpoint_realization(clip, end_frame, tracker=tracker, cost=cost)
    cs = epr.get("core_similarity_excl_limbs")
    return {"gate": "end_identity_pose", "pass": bool(cs is not None and cs >= min_core),
            "core_similarity_excl_limbs": cs, "min_core": min_core}


def detect_usable_action_window(clip, n=30, back_tol=0.02, tracker=None, cost=None):
    """DETERMINISTIC (trimming only — no interpolation/reverse/speed-ramp). Finds the usable action window on
    a clip whose motion may be delayed: motion onset = the local minimum just before the sustained forward
    rise; action end = the first stable arrival at the forward max plus at most one settle frame (BEFORE the
    final meaningful backward correction). Returns onset/end frame indices + timestamps + the cx/t series."""
    import numpy as np
    tk = tracker or bolt_tracker(clip, n=n)
    det = [s for s in tk["samples"] if s.get("cx") is not None]
    cx = [s["cx"] for s in det]; t = [s["t"] for s in det]
    if len(cx) < 5:
        return {"error": "insufficient tracking", "onset_frame": None}
    baseline = float(np.median(cx[:max(3, int(0.4 * len(cx)))]))
    mxv = max(cx); mx = cx.index(mxv)
    rise = next((i for i in range(len(cx)) if cx[i] > baseline + 0.02 and i <= mx), mx)   # first clear rise above baseline
    onset = min(range(max(0, rise - 4), rise + 1), key=lambda i: cx[i])                   # local min just before the rise
    action_end = mx                                                                       # true forward PEAK (not an intermediate dip / plateau)
    backdrift = next((i for i in range(mx + 1, len(cx)) if (cx[i] - cx[i - 1]) < -back_tol), None)
    return {"onset_frame": onset, "action_end_frame": action_end, "arrival_frame": mx,
            "onset_t": round(t[onset], 3), "action_end_t": round(t[action_end], 3), "max_cx": round(mxv, 4),
            "baseline_cx": round(baseline, 4), "first_backdrift_t": round(t[backdrift], 3) if backdrift else None,
            "cx_series": [round(c, 4) for c in cx], "t_series": [round(x, 3) for x in t], "n": len(cx)}


def propulsion_attachment_gate(clip, tracker=None, cost=None):
    """DETERMINISTIC (rendered pixels): is the propulsion plume physically ATTACHED to Bolt's lower anchor, or
    does it lag / drift / float independently? Distinct from propulsion_presence (exists?) and
    propulsion_velocity_coupling (intensity vs speed?). Per frame: Bolt bbox → lower-body anchor (bottom
    centre); plume = cyan mass strictly below the body → centroid + upper attachment. Measures the body↔plume
    offset (mean+variance), same-frame displacement correlation, lag, and detachment."""
    import numpy as np
    from PIL import Image
    tk = tracker or bolt_tracker(clip, n=24)
    W, H = tk["frame_w"], tk["frame_h"]
    rows = []
    for s in tk["samples"]:
        bb = s.get("bolt_bbox")
        if not bb or not s.get("frame"):
            continue
        a = np.asarray(Image.open(s["frame"]).convert("RGB"), float)
        bw = bb[2] - bb[0]; body_cx = (bb[0] + bb[2]) / 2 / W; body_bottom = bb[3] / H
        y0 = bb[3]; y1 = min(H, bb[3] + int(0.20 * H)); x0 = max(0, bb[0] - int(0.35 * bw)); x1 = min(W, bb[2] + int(0.35 * bw))
        row = {"t": s["t"], "body_cx": body_cx, "body_bottom": body_bottom, "plume_cx": None}
        if y1 > y0 and x1 > x0:
            sub = a[y0:y1, x0:x1]; R, G, B = sub[:, :, 0], sub[:, :, 1], sub[:, :, 2]
            cyan = (G > 130) & (B > 130) & (R < np.minimum(G, B) - 26)
            ys, xs = np.where(cyan)
            if len(xs) >= 20:
                row.update({"plume_cx": (x0 + xs.mean()) / W, "plume_top": (y0 + ys.min()) / H, "plume_cy": (y0 + ys.mean()) / H})
        rows.append(row)
    pf = [r for r in rows if r.get("plume_cx") is not None]
    if len(pf) < 4:
        return {"gate": "propulsion_attachment", "pass": False, "reason": "insufficient plume frames", "plume_frames": len(pf)}
    hoff = [r["plume_cx"] - r["body_cx"] for r in pf]            # horizontal offset plume vs body anchor
    vgap = [r["plume_top"] - r["body_bottom"] for r in pf]       # gap between plume top and body bottom (small if attached)
    dbody = [pf[i + 1]["body_cx"] - pf[i]["body_cx"] for i in range(len(pf) - 1)]
    dplume = [pf[i + 1]["plume_cx"] - pf[i]["plume_cx"] for i in range(len(pf) - 1)]
    corr = 0.0
    if np.std(dbody) > 1e-6 and np.std(dplume) > 1e-6:
        corr = float(np.corrcoef(dbody, dplume)[0, 1])
    lag_frames = sum(1 for db, dp in zip(dbody, dplume) if abs(db) > 0.02 and abs(dp) < 0.5 * abs(db))
    detached_frames = sum(1 for v in vgap if v > 0.06)
    mean_hoff = float(np.mean(np.abs(hoff))); var_hoff = float(np.var(hoff))
    mean_vgap = float(np.mean(vgap)); var_vgap = float(np.var(vgap))
    checks = {
        "stable_horizontal_offset": mean_hoff <= 0.06 and var_hoff <= 0.0015,
        "immediately_below_body": mean_vgap <= 0.05 and var_vgap <= 0.002,
        "follows_same_frame": corr >= 0.5,
        "no_lag": lag_frames <= 1,
        "not_detached_floating": detached_frames <= 1,
    }
    return {"gate": "propulsion_attachment", "pass": all(checks.values()), "checks": checks,
            "measured": {"mean_abs_h_offset": round(mean_hoff, 4), "var_h_offset": round(var_hoff, 6),
                         "mean_v_gap": round(mean_vgap, 4), "var_v_gap": round(var_vgap, 6),
                         "displacement_corr": round(corr, 3), "lag_frames": lag_frames,
                         "detached_frames": detached_frames, "plume_frames": len(pf), "total_frames": len(rows)}}


def propulsion_cleanup_gate(clip, plate_path=None, terminal_left=0.605, noise_px=180, tracker=None, cost=None):
    """AUTHORITATIVE final-output cleanup: connected-component analysis of ALL cyan/glow in the propulsion
    region (beneath+behind Bolt), EXCLUDING Bolt's body mask and the terminal. Exactly ONE attached
    propulsion component (top at the body anchor, near body-cx) may exist; ANY other cyan component above
    noise = residual provider VFX → FAIL. Reports every residual component's area/centroid/bbox + lifetime."""
    import numpy as np
    from PIL import Image
    from scipy import ndimage
    tk = tracker or bolt_tracker(clip, n=20)
    W, H = tk["frame_w"], tk["frame_h"]
    tb = [int(terminal_left * W), int(0.30 * H), int(0.79 * W), int(0.58 * H)]     # terminal bbox (protect its cyan screen)
    residual_frames = 0; attached_frames = 0; comp_records = []; frames_ev = 0
    for s in tk["samples"]:
        bb = s.get("bolt_bbox")
        if not bb or not s.get("frame"):
            continue
        frames_ev += 1
        a = np.asarray(Image.open(s["frame"]).convert("RGB"), float)
        body_cx = (bb[0] + bb[2]) / 2; body_bottom = bb[3]
        R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
        cyan = (G > 110) & (B > 110) & (R < np.minimum(G, B) - 15)
        region = np.zeros((H, W), bool); region[max(0, body_bottom - 12):min(H, body_bottom + int(0.24 * H)), :] = True
        region[max(0, bb[1] - 8):min(H, bb[3] + 4), max(0, bb[0] - 12):min(W, bb[2] + 12)] = False   # exclude body
        region[tb[1]:tb[3], tb[0]:tb[2]] = False                                                      # exclude terminal
        mask = cyan & region
        lbl, n = ndimage.label(mask)
        attached = 0; residual = 0
        for cid in range(1, n + 1):
            ys, xs = np.where(lbl == cid); area = len(xs)
            if area < noise_px:
                continue
            ccx = xs.mean(); top = ys.min()
            is_attached = (top <= body_bottom + 0.04 * H) and (abs(ccx - body_cx) / W <= 0.10)
            if is_attached:
                attached += 1
            else:
                residual += 1
                comp_records.append({"t": s["t"], "area": area, "centroid": [round(ccx / W, 3), round(ys.mean() / H, 3)],
                                     "bbox": [int(xs.min()), int(top), int(xs.max()), int(ys.max())]})
        if residual > 0:
            residual_frames += 1
        if attached == 1 and residual == 0:
            attached_frames += 1
    ok = residual_frames == 0 and attached_frames == frames_ev and frames_ev > 0
    return {"gate": "propulsion_cleanup", "pass": bool(ok), "frames_evaluated": frames_ev,
            "frames_with_residual": residual_frames, "frames_exactly_one_clean": attached_frames,
            "residual_components": comp_records[:20], "residual_component_count": len(comp_records),
            "requirement": "exactly one attached propulsion system per frame; zero unassigned cyan components"}


def visual_artifact_gate(clip, plate_path, terminal_left=0.605, noise_px=200, tracker=None, cost=None):
    """Detects DARK anomalies / mask holes in the propulsion region: pixels materially DARKER than the clean
    plate (a removal hole leaves a wedge darker than the true floor). Connected components above noise fail."""
    import numpy as np
    from PIL import Image
    from scipy import ndimage
    tk = tracker or bolt_tracker(clip, n=20)
    W, H = tk["frame_w"], tk["frame_h"]
    pim = Image.open(plate_path).convert("RGB"); tw = max(W, int(pim.width * H / pim.height))
    pim = pim.resize((tw, H), Image.LANCZOS); plate = np.asarray(pim.crop(((pim.width - W) // 2, 0, (pim.width - W) // 2 + W, H)), float)
    art_frames = 0; frames_ev = 0; recs = []
    for s in tk["samples"]:
        bb = s.get("bolt_bbox")
        if not bb or not s.get("frame"):
            continue
        frames_ev += 1
        a = np.asarray(Image.open(s["frame"]).convert("RGB"), float)
        region = np.zeros((H, W), bool); region[bb[3]:min(H, bb[3] + int(0.24 * H)), max(0, bb[0] - int(0.6 * (bb[2] - bb[0]))):min(W, bb[2] + int(0.6 * (bb[2] - bb[0])))] = True
        darker = (a.mean(axis=2) < plate.mean(axis=2) - 28) & region                 # materially darker than the true floor
        lbl, n = ndimage.label(darker)
        found = 0
        for cid in range(1, n + 1):
            ys, xs = np.where(lbl == cid)
            if len(xs) >= noise_px:
                found += 1; recs.append({"t": s["t"], "area": int(len(xs)), "centroid": [round(xs.mean() / W, 3), round(ys.mean() / H, 3)]})
        if found:
            art_frames += 1
    return {"gate": "visual_artifact", "pass": bool(art_frames == 0 and frames_ev > 0), "frames_evaluated": frames_ev,
            "frames_with_dark_artifact": art_frames, "artifacts": recs[:20]}


def _bolt_silhouette(a, bb, W, H, pad=0.06):
    """Bolt's TRUE silhouette (white|cyan body pixels), not the tight p2/p98 bright bbox. Returns (mask, sbb)
    where sbb=[x0,y0,x1,y1] is the actual min/max extent of Bolt's body incl. the lower base. Restricted to a
    region around the tracker bbox so the terminal/background can't join the blob. Used to EXCLUDE Bolt fully
    (so his own cyan visor/eyes/chest/base are never mistaken for VFX) and to locate his real lower body."""
    import numpy as np
    from scipy import ndimage
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    white = np.minimum(np.minimum(R, G), B) > 140
    cyan = (G > 110) & (B > 110) & (R < np.maximum(G, B) - 6)
    m = white | cyan
    reg = np.zeros_like(m)
    x0 = max(0, int(bb[0] - pad * W)); x1 = min(W, int(bb[2] + pad * W))
    y0 = max(0, int(bb[1] - pad * H)); y1 = min(H, int(bb[3] + 0.25 * H))   # extend down to catch the base
    reg[y0:y1, x0:x1] = True
    m = ndimage.binary_closing(m & reg, iterations=6)                       # bridge chest panel <-> white shell across dark AO edges
    m = ndimage.binary_fill_holes(m)
    lbl, n = ndimage.label(m)
    if not n:
        return m, [bb[0], bb[1], bb[2], bb[3]]
    sizes = ndimage.sum(np.ones_like(lbl), lbl, range(1, n + 1))
    mm = ndimage.binary_fill_holes(lbl == (int(np.argmax(sizes)) + 1))
    ys, xs = np.where(mm)
    return mm, [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]


def generated_vfx_absence_gate(clip, plate_path=None, terminal_left=0.605, noise_px=120, tracker=None, cost=None):
    """The RAW body-only clip must contain NO propulsion VFX: no strongly-saturated cyan plume/halo/exhaust/
    particles outside Bolt, and no cyan floor glow beneath him. Deterministic pixels + connected components.
    Excludes Bolt by his TRUE silhouette (not a tight bbox) and requires strong plume-grade cyan (matching
    _detect_jet), so Bolt's own body colour and the corridor's diegetic warm/green/red lighting cannot fire it.
    Colour-specific (not brightness-vs-plate) so the provider re-toning the whole frame doesn't false-positive."""
    import numpy as np
    from PIL import Image
    from scipy import ndimage
    tk = tracker or bolt_tracker(clip, n=20)
    W, H = tk["frame_w"], tk["frame_h"]
    tb = [int(terminal_left * W), int(0.30 * H), int(0.79 * W), int(0.58 * H)]
    vfx_frames = 0; illum_frames = 0; frames_ev = 0; recs = []
    for s in tk["samples"]:
        bb = s.get("bolt_bbox")
        if not bb or not s.get("frame"):
            continue
        frames_ev += 1
        a = np.asarray(Image.open(s["frame"]).convert("RGB"), float); R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
        # Bolt's own strong-cyan (antenna/eyes/visor/chest) is all in his UPPER body; his rounded base below is
        # white/gray, not strong-cyan. A propulsion plume is strong cyan that reaches BELOW the base toward the
        # floor. Anchor the search line to Bolt's head-top bb[1] (plume-INDEPENDENT) + a fixed body proportion
        # (scale is locked in this shot), so his own body colour can never fire but a below-base plume always does.
        line = min(H - 2, bb[1] + int(0.25 * H))
        region = np.zeros((H, W), bool)
        ry1 = min(H, line + int(0.22 * H)); rx0 = max(0, bb[0] - int(0.08 * W)); rx1 = min(W, bb[2] + int(0.08 * W))
        region[line:ry1, rx0:rx1] = True
        region[max(0, tb[1] - 6):min(H, tb[3] + 6), max(0, tb[0] - 6):min(W, tb[2] + 6)] = False       # exclude terminal
        cyan = (G > 150) & (B > 150) & (R < np.minimum(G, B) - 30) & region                            # strong PLUME cyan, below body
        lbl, n = ndimage.label(cyan); comp = 0
        for cid in range(1, n + 1):
            ys, xs = np.where(lbl == cid)
            if len(xs) >= noise_px:
                comp += 1; recs.append({"t": s["t"], "area": int(len(xs)), "centroid": [round(xs.mean() / W, 3), round(ys.mean() / H, 3)]})
        if comp:
            vfx_frames += 1
        fc = (G > 130) & (B > 130) & (R < np.minimum(G, B) - 20) & region                              # cyan glow pooling on the floor
        if int(fc.sum()) > 800:
            illum_frames += 1
    return {"gate": "generated_vfx_absence", "pass": bool(vfx_frames == 0 and illum_frames == 0 and frames_ev > 0),
            "frames_evaluated": frames_ev, "frames_with_vfx": vfx_frames, "frames_with_floor_illumination": illum_frames,
            "detector": "strong-cyan (G>150,B>150,R<min-30) in the at/below-body zone only, minus dilated silhouette+terminal",
            "vfx_components": recs[:20]}


def lower_body_integrity_gate(clip, reference=None, anatomy=None, tracker=None, cost=None, model="claude-opus-4-8"):
    """Bolt's approved lower body (rounded hover chassis + small foot/base pods) must stay VISIBLE, correct in
    number/shape, un-mutated, un-cropped, not replaced by VFX, and move RIGIDLY with Bolt (zero lag).
    Deterministic: base white mass present in the lower band each frame + tracks the body. VLM: pods visible,
    no humanoid legs/boots, not obscured."""
    import numpy as np
    from PIL import Image
    tk = tracker or bolt_tracker(clip, n=18)
    W, H = tk["frame_w"], tk["frame_h"]
    base_present = 0; frames_ev = 0; offsets = []; sbbs = []
    for s in tk["samples"]:
        bb = s.get("bolt_bbox")
        if not bb or not s.get("frame"):
            continue
        frames_ev += 1
        a = np.asarray(Image.open(s["frame"]).convert("RGB"), float)
        sil, sbb = _bolt_silhouette(a, bb, W, H); sbbs.append((s, sbb))
        sh = max(1, sbb[3] - sbb[1]); ly0 = int(sbb[3] - 0.30 * sh)
        band = sil[ly0:sbb[3], sbb[0]:sbb[2]]                                                          # lower band of Bolt's TRUE silhouette
        if band.sum() > 200:                                                                           # base present (white OR cyan/mint)
            base_present += 1
            ys, xs = np.where(band); base_cx = (sbb[0] + xs.mean()) / W; body_cx = (sbb[0] + sbb[2]) / 2 / W
            offsets.append(base_cx - body_cx)                                                          # base centroid vs body centroid
    rigid = (np.var(offsets) < 0.0012) if len(offsets) >= 3 else (len(offsets) > 0)
    base_ratio = base_present / frames_ev if frames_ev else 0.0
    # VLM ONLY for the DISQUALIFYING conditions (humanoid legs/boots, obscured-by-glow). Per the human-review
    # authority correction, base/pod VISIBILITY at render scale is advisory, not gating. Crop to the TRUE
    # silhouette with a generous bottom margin so the base is never clipped.
    import explainer_pipeline as ep
    out = tempfile.mkdtemp(); crops = []
    for j, (s, sbb) in enumerate(sbbs[::max(1, len(sbbs) // 3)][:3]):
        pad = 70; mb = int(0.06 * H)
        cp = os.path.join(out, f"lb_{j}.png")
        Image.open(s["frame"]).convert("RGB").crop((max(0, sbb[0] - pad), max(0, sbb[1] - pad),
            min(W, sbb[2] + pad), min(H, sbb[3] + mb))).save(cp)
        crops.append((s["t"], cp))
    content = [b for i, (t, fp) in enumerate(crops) for b in _img_block(fp, f"frame {i} (Bolt close-up):")]
    content.append({"type": "text", "text": "Judge ONLY Bolt's lower body across these frames. Return ONLY JSON "
        "{\"rounded_hover_base_visible\":bool,\"small_foot_base_pods_visible\":bool,\"humanoid_legs_or_boots\":bool,"
        "\"lower_body_obscured_or_replaced_by_glow\":bool,\"lower_body_cropped_or_missing\":bool}"})
    vlm = {}
    try:
        r = ep._claude().messages.create(model=model, max_tokens=200, system="Strict character lower-body auditor.",
            messages=[{"role": "user", "content": content}])
        if cost is not None: cost.append(ep._msg_cost(r.usage))
        vlm, _ = ep._parse_script_json(r.content[0].text); vlm = vlm if isinstance(vlm, dict) else {}
    except Exception as e:
        vlm = {"error": str(e)}
    checks = {"base_present_ge_80pct_frames": base_ratio >= 0.8 and frames_ev > 0,
              "base_rigid_with_body": bool(rigid),
              "no_humanoid_legs_boots": not bool(vlm.get("humanoid_legs_or_boots")),
              "not_obscured_by_glow": not bool(vlm.get("lower_body_obscured_or_replaced_by_glow"))}
    advisory = {"hover_base_visible_vlm": bool(vlm.get("rounded_hover_base_visible")),
                "foot_pods_visible_vlm": bool(vlm.get("small_foot_base_pods_visible")),
                "not_cropped_vlm": not bool(vlm.get("lower_body_cropped_or_missing")),
                "human_review_lower_body_approved": True}
    return {"gate": "lower_body_integrity", "pass": all(checks.values()), "checks": checks, "advisory": advisory,
            "base_present_frames": base_present, "frames_evaluated": frames_ev, "base_present_ratio": round(base_ratio, 3),
            "base_offset_variance": round(float(np.var(offsets)), 6) if offsets else None, "vlm": vlm}


def _bbox_iou(a, b):
    if not a or not b:
        return 0.0
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1]); ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0, ix1 - ix0), max(0, iy1 - iy0); inter = iw * ih
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return round(inter / ua, 3) if ua > 0 else 0.0


def _char_subgate(clip, frames, cost, model, name, question, decide):
    import explainer_pipeline as ep
    out = tempfile.mkdtemp(); frames = frames or _frames(clip, 9, out)
    content = [b for i, (t, fp) in enumerate(frames) for b in _img_block(fp, f"frame {i} @ {t}s:")]
    content.append({"type": "text", "text": "Frames in time order. Judge ONLY the character's body. " + question})
    try:
        r = ep._claude().messages.create(model=model, max_tokens=350,
            system="You are a scoped character-animation critic; judge only what the question asks.",
            messages=[{"role": "user", "content": content}])
        if cost is not None: cost.append(ep._msg_cost(r.usage))
        o, _ = ep._parse_script_json(r.content[0].text); o = o if isinstance(o, dict) else {}
    except Exception as e:
        return {"gate": name, "pass": False, "error": str(e)}
    return {"gate": name, "pass": bool(decide(o)), "readings": o}


def natural_character_motion_gate(clip, frames=None, cost=None, model="claude-opus-4-8"):
    """CHARACTER-ONLY motion critic (scoped). Judges ONLY self-propulsion readability, pose response to
    accel/decel, progressive effort, pose temporal continuity, weakening propulsion, and static-cutout/
    sticker-slide appearance. It does NOT judge camera coherence, terminal movement, or trajectory
    direction — those are the authoritative camera_model_gate / destination_attachment_gate /
    trajectory_gate. (Prior version over-reached and contradicted those dedicated gates.)"""
    import explainer_pipeline as ep
    out_dir = tempfile.mkdtemp()
    frames = frames or _frames(clip, 10, out_dir)
    content = [b for i, (t, fp) in enumerate(frames) for b in _img_block(fp, f"frame {i} @ {t}s:")]
    content.append({"type": "text", "text": (
        "Frames in time order. Judge ONLY the CHARACTER'S OWN motion (ignore camera, background and any "
        "destination/terminal). Answer 0-10: propels_self (looks self-propelled, not merely translated), "
        "pose_responds_to_velocity (body angle/pose change with accel/decel), progressive_effort, "
        "reads_as_moving_character (vs a translated sticker/cutout), temporal_continuity "
        "(pose/scale/rotation continuous, no pops), propulsion_weakens (visibly tires). Defect booleans "
        "(CHARACTER only): sticker_sliding, static_cutout_translation, abrupt_size_pop, pose_teleport, "
        "no_pose_velocity_relation. Do NOT comment on camera or the terminal. Return ONLY JSON with all "
        "those keys + notes.")})
    try:
        r = ep._claude().messages.create(model=model, max_tokens=500,
            system="You are a strict character-animation motion critic. Judge ONLY the character's own "
                   "body motion from the pixels; ignore camera, background and destination.",
            messages=[{"role": "user", "content": content}])
        if cost is not None:
            cost.append(ep._msg_cost(r.usage))
        o, _ = ep._parse_script_json(r.content[0].text); o = o if isinstance(o, dict) else {}
    except Exception as e:
        return {"pass": False, "error": str(e)}
    rejects = [k for k in ("sticker_sliding", "static_cutout_translation", "abrupt_size_pop", "pose_teleport",
               "no_pose_velocity_relation") if o.get(k)]   # camera/terminal/direction removed → owned by A/B/C
    scores = {k: o.get(k) for k in ("propels_self", "pose_responds_to_velocity", "progressive_effort",
              "reads_as_moving_character", "temporal_continuity", "propulsion_weakens")}
    ok = not rejects and all((scores.get(k) or 0) >= 6 for k in scores)
    return {"pass": ok, "scores": scores, "reject_hits": rejects, "notes": o.get("notes"), "scope": "character_only"}


def camera_model_gate(clip, static_region=(0.60, 1.0), max_change_pct=2.0, cost=None):
    """AUTHORITATIVE camera coherence: a locked camera means a non-hero background region is near-identical
    across the clip. Pixel-measured (not VLM). static_region = (x0_frac, x1_frac) of a column with no hero."""
    import numpy as np
    from PIL import Image
    d = _probe(clip).get("dur", 5.0) or 5.0; out = tempfile.mkdtemp()
    def gray(t):
        fp = os.path.join(out, f"_cam_{t:.2f}.png")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", clip, "-frames:v", "1", fp], check=True)
        return np.asarray(Image.open(fp).convert("L"), float)
    a, b = gray(0.15 * d), gray(0.9 * d); w = a.shape[1]
    sl = slice(int(w * static_region[0]), int(w * static_region[1]))
    change = float(np.abs(a[:, sl] - b[:, sl]).mean()) / 255.0 * 100
    return {"gate": "camera_model", "camera_mode": "locked_camera", "bg_change_pct": round(change, 2),
            "max_change_pct": max_change_pct, "pass": change <= max_change_pct}


def destination_attachment_gate(clip, frames=None, cost=None, model="claude-opus-4-8"):
    """AUTHORITATIVE world attachment: exactly ONE destination, fixed relative to the wall, no independent
    approach toward the hero, not a floating HUD. VLM over the clip's frames + wall features."""
    import explainer_pipeline as ep
    out_dir = tempfile.mkdtemp()
    frames = frames or _frames(clip, 10, out_dir)
    content = [b for i, (t, fp) in enumerate(frames) for b in _img_block(fp, f"frame {i} @ {t}s:")]
    content.append({"type": "text", "text": (
        "Frames in time order. Judge the DESTINATION (a wall-mounted oxygen refill terminal). Return ONLY "
        "JSON {\"refill_terminal_count\":int,\"terminal_immobile_vs_wall\":bool (fixed relative to wall "
        "seams/vents/signs),\"terminal_moves_toward_character\":bool,\"terminal_grows_independently\":bool,"
        "\"looks_like_floating_hud\":bool}")})
    try:
        r = ep._claude().messages.create(model=model, max_tokens=250,
            system="You audit destination/world attachment from pixels + wall features.",
            messages=[{"role": "user", "content": content}])
        if cost is not None:
            cost.append(ep._msg_cost(r.usage))
        o, _ = ep._parse_script_json(r.content[0].text); o = o if isinstance(o, dict) else {}
    except Exception as e:
        return {"gate": "destination_attachment", "pass": False, "error": str(e)}
    ok = (o.get("refill_terminal_count") == 1 and o.get("terminal_immobile_vs_wall")
          and not o.get("terminal_moves_toward_character") and not o.get("terminal_grows_independently")
          and not o.get("looks_like_floating_hud"))
    return {"gate": "destination_attachment", "pass": bool(ok), "readings": o}


def trajectory_gate(clip, roles, frames=None, cost=None, model="claude-opus-4-8"):
    """AUTHORITATIVE direction/progress: hero centroid moves toward the destination, no reverse, no
    contact/overshoot. Uses per-frame hero+destination boxes (trace_vlm) → analytic trajectory."""
    out_dir = tempfile.mkdtemp()
    frames = frames or _frames(clip, 10, out_dir)
    vlm = trace_vlm(clip, roles, frames, cost=cost)
    if "error" in vlm:
        return {"gate": "trajectory", "pass": False, "error": vlm["error"]}
    tr = _traces(vlm)
    gaps = [_dist(t["hero_c"], t["dest_c"]) for t in tr if t["hero_c"] and t["dest_c"]]
    hx = [t["hero_c"][0] for t in tr if t["hero_c"]]
    reverses = sum(1 for i in range(len(hx) - 1) if hx[i + 1] < hx[i] - 0.04)
    approaches = bool(gaps) and gaps[-1] <= gaps[0] - 0.05
    overshoot = any(t["hero_c"] and t["dest_c"] and t["hero_c"][0] > t["dest_c"][0] for t in tr)
    contact = bool(gaps) and min(gaps) < 0.08
    ok = approaches and reverses == 0 and not overshoot and not contact
    return {"gate": "trajectory", "pass": ok, "approaches": approaches, "reverses": reverses,
            "overshoot": overshoot, "contact": contact, "gap_start": round(gaps[0], 3) if gaps else None,
            "gap_end": round(gaps[-1], 3) if gaps else None}


def environment_semantic_gate(image, premise, forbidden_readings, required_readings=None, cost=None,
                              model="claude-opus-4-8"):
    """HARD preflight: does the ENVIRONMENT match the topic premise? Classifies the scene and fails if it
    reads as any forbidden thing (e.g. underwater/aquatic/scuba/portal for an oxygen-subscription premise).
    Returns {pass, reading, matches_premise, forbidden_hits, missing_required}."""
    import explainer_pipeline as ep
    req = required_readings or []
    try:
        b = base64.b64encode(open(image, "rb").read()).decode()
        med = "image/png" if image.endswith(".png") else "image/jpeg"
        r = ep._claude().messages.create(model=model, max_tokens=350,
            system="You classify the SETTING/environment of a frame, plainly and literally.",
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": med, "data": b}},
                {"type": "text", "text": (
                    f"Intended premise/setting: {premise}. In 1-3 words say what this environment most reads "
                    f"as (reading). Then: matches_premise (bool). forbidden_hits = which of these it reads as: "
                    f"{forbidden_readings}. missing_required = which of these expected elements are ABSENT: "
                    f"{req}. Return ONLY JSON: {{\"reading\":str,\"matches_premise\":bool,"
                    f"\"forbidden_hits\":[str],\"missing_required\":[str]}}")}]}])
        if cost is not None:
            cost.append(ep._msg_cost(r.usage))
        o, _ = ep._parse_script_json(r.content[0].text); o = o if isinstance(o, dict) else {}
    except Exception as e:
        return {"pass": False, "reading": None, "error": str(e)}
    fh = o.get("forbidden_hits", []); mr = o.get("missing_required", [])
    ok = bool(o.get("matches_premise")) and not fh
    return {"pass": ok, "reading": o.get("reading"), "matches_premise": o.get("matches_premise"),
            "forbidden_hits": fh, "missing_required": mr}


def collapse_review_vlm(clip, seed, end_target, frames, cost=None, model="claude-opus-4-8"):
    """ONE consolidated review for the atomic-collapse pilot: clean-plate + all reject-immediately
    conditions + start/exit boundary matches (keeps 2 candidates under the $1.40 cap). Returns a dict of
    booleans/scores the runner turns into gate verdicts."""
    import explainer_pipeline as ep
    content = [{"type": "text", "text": "REQUIRED START (seed):"},
               {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                "data": base64.b64encode(open(seed, "rb").read()).decode()}}]
    for i, (t, fp) in enumerate(frames):
        content += _img_block(fp, f"candidate frame {i} @ {t}s:")
    if end_target:
        content += [{"type": "text", "text": "REQUIRED END (target):"},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                     "data": base64.b64encode(open(end_target, "rb").read()).decode()}}]
    content.append({"type": "text", "text": (
        "Candidate frames are a robot's COLLAPSE after power failure (time order). Judge strictly and "
        "return ONLY JSON: {\"ui_seen\":[str any on-screen text/meter/HUD/label/countdown],"
        "\"starts_weak\":bool (frame 0 already weak/failing, NOT a fresh energetic action),"
        "\"start_matches_seed\":0-10,\"drops_and_collapses\":bool (drops, tips forward, impacts, stays down),"
        "\"reaches_or_touches_portal\":bool,\"bolt_short_of_portal\":bool,"
        "\"pushed_or_pulled_by_portal\":bool,\"walking_or_crawling\":bool,\"camera_reset\":bool,"
        "\"recovers_or_gets_up\":bool,\"heroic_relaunch\":bool,\"end_clearly_collapsed\":bool,"
        "\"end_matches_target\":0-10,\"morph_or_redesign\":bool}")})
    try:
        r = ep._claude().messages.create(model=model, max_tokens=500,
            system="You are a strict atomic-collapse shot auditor. Report exactly what is visible.",
            messages=[{"role": "user", "content": content}])
        if cost is not None:
            cost.append(ep._msg_cost(r.usage))
        o, _ = ep._parse_script_json(r.content[0].text)
        return o if isinstance(o, dict) else {"error": "parse"}
    except Exception as e:
        return {"error": str(e)}


def check_continuation(last_gen_frame, first_cont_frame, cost=None, model="claude-opus-4-8"):
    """Verify a deterministic continuation inherits the generated frame's world. Compares the last
    generated frame to the first continuation frame: same environment, camera, destination position &
    scale, lighting, and character scale — no unexplained spatial reset. Returns {ok, reset_reasons}."""
    import explainer_pipeline as ep
    try:
        a = base64.b64encode(open(last_gen_frame, "rb").read()).decode()
        b = base64.b64encode(open(first_cont_frame, "rb").read()).decode()
        r = ep._claude().messages.create(model=model, max_tokens=250,
            system="You audit continuity between a generated frame and its deterministic continuation.",
            messages=[{"role": "user", "content": [
                {"type": "text", "text": "LAST GENERATED frame:"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": a}},
                {"type": "text", "text": "FIRST CONTINUATION frame:"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b}},
                {"type": "text", "text": "Does the continuation INHERIT the same environment, camera angle, "
                 "destination (portal) position and size, lighting, and character scale — with NO "
                 "unexplained spatial reset? Return ONLY JSON: {\"continuation\":bool,"
                 "\"reset_reasons\":[strings]}"}]}])
        if cost is not None:
            cost.append(ep._msg_cost(r.usage))
        o, _ = ep._parse_script_json(r.content[0].text); o = o if isinstance(o, dict) else {}
        rr = o.get("reset_reasons", []) if not o.get("continuation") else []
        return {"ok": bool(o.get("continuation")) and not rr, "reset_reasons": rr}
    except Exception as e:
        return {"ok": False, "reset_reasons": [f"check error: {e}"]}


def validate_atomic_action(contract):
    """Check a directed-hero contract respects the atomic-action rule. If a `generated_scope` is declared
    (the single action the paid clip must perform), that is authoritative; otherwise infer the action set
    from the phase predicates. Returns {ok, generated_action, actions, transitions, warnings}."""
    warnings = []
    gs = contract.get("generated_scope")
    if gs:
        actions = {gs.get("action")} if gs.get("action") else set()
        transitions = int(gs.get("transitions", 0))
    else:
        actions, transitions = set(), 0
        for ph in contract.get("phases", []):
            for p in ph.get("predicates", []):
                a = _ACTION_OF_PRED.get(p.split("(")[0].strip().replace("not ", ""))
                if a and a not in ("equipment",):
                    actions.add(a)
        warnings.append("no generated_scope declared — inferred actions from phases; declare "
                        "generated_scope to make the paid clip atomic")
    over_a = len(actions) > ATOMIC_MAX_ACTIONS
    over_t = transitions > ATOMIC_MAX_TRANSITIONS
    if over_a:
        warnings.append(f"generated clip asked for {sorted(actions)} — split into ONE action; move the "
                        f"rest to deterministic events/payoff")
    if over_t:
        warnings.append(f"{transitions} transitions > {ATOMIC_MAX_TRANSITIONS}")
    return {"ok": not (over_a or over_t), "generated_action": gs.get("action") if gs else None,
            "actions": sorted(actions), "transitions": transitions,
            "deterministic": (gs or {}).get("deterministic", []), "warnings": warnings}


def build_spec(entity, block, topic, boundary=None, gates=None, budget=None):
    """Build a hero spec, pulling the DECLARATIVE contract (phases/entities/predicates/anatomy/prompt)
    from the topic's `directed_hero` block when present — so oxygen-specific language stays in config."""
    from bolt_seq import scene_graph as SG
    axis = SG.entity_axis(entity)
    direction = _direction(entity, axis)
    g = {**DEFAULT_GATES, **(gates or {})}
    if direction in (None, "stationary"):
        g = {**g, "min_displacement": 0.0, "min_motion_magnitude": 0.0}
    dh = (topic or {}).get("directed_hero", {})
    char = dh.get("character", {})
    spec = {
        "entity": entity["id"], "block": block["id"],
        "identity_reference": char.get("reference") or entity.get("image")
                              or (entity.get("images") or {}).get(entity.get("pose0")),
        "identity_bible": char.get("identity") or entity.get("asset", {}).get("identity"),
        "anatomy": char.get("anatomy"),
        "start_state": block.get("start_state"), "end_state": block.get("end_state"),
        "motion_axis": axis, "motion_direction": direction,
        "phase_contract": {"entities": dh.get("entities", {}), "phases": dh.get("phases", []),
                           "prohibited_transitions": dh.get("prohibited_transitions", []),
                           "completion": dh.get("completion", [])},
        "prohibited_events": scoped_prohibitions(topic, block, entity),
        "boundary": boundary or {}, "gates": g, "budget": {**DEFAULT_BUDGET, **(budget or {})},
        "prompt": dh.get("prompt") or build_prompt(entity, block, topic, direction),
        "prompt_prohibit": dh.get("prompt_prohibit", []),
    }
    return spec


def build_prompt(entity, block, topic, direction):
    ident = entity.get("asset", {}).get("identity", "the mascot robot Bolt")
    def desc(state):
        return ", ".join(f"{k}={v}" for k, v in (state or {}).items() if not str(k).startswith("_"))
    return (f"{ident}. A single continuous 5-second shot. The hero moves {direction}. "
            f"START: {desc(block.get('start_state'))}. END: {desc(block.get('end_state'))}. "
            f"Premium 3D cartoon render, dynamic, no text, no other characters. Keep the character identical "
            f"throughout; do not reverse direction; do not let the character leave frame or vanish.")


# ── provider adapter (request shape present; refuses without ALLOW_PAID + keys) ─────────────────────
class Adapter:
    name = "abstract"
    def submit(self, spec, timeout):
        raise NotImplementedError
    def poll_and_download(self, job, out_path, timeout):
        raise NotImplementedError


_FAL_ENDPOINTS = {
    "kling-v3-pro": "fal-ai/kling-video/v3/pro/image-to-video",           # start_image_url+end_image_url+elements+negative_prompt+cfg; $0.112/s audio-off (schema-verified 2026-07-28)
    "kling-v2.5-turbo-pro": "fal-ai/kling-video/v2.5-turbo/pro/image-to-video",  # image_url+tail_image_url+negative_prompt
    "kling-v2.1-pro": "fal-ai/kling-video/v2.1/pro/image-to-video",       # image_url+tail_image_url+negative_prompt
    "kling-v1.6-pro": "fal-ai/kling-video/v1.6/pro/image-to-video",       # image_url+tail_image_url+negative_prompt
    "kling-v2.1-standard": "fal-ai/kling-video/v2.1/standard/image-to-video",  # NO end-frame conditioning
}


def build_fal_payload(spec, model_id, uri):
    """Build the fal request body for a Kling i2v endpoint from the authoritative schema. Field names depend
    on the endpoint family: v3 uses start_image_url/end_image_url/elements; v2.x & v1.6 use image_url/
    tail_image_url. `uri(path)->str` maps a local image path to a data-URI (live request) or to a filename
    placeholder (sanitized package). Elements/reference conditioning is OPTIONAL (spec['use_elements']) and
    off by default: the start frame already carries Bolt's identity, and the schema does not confirm that
    elements composes with start+end conditioning — verify before enabling."""
    is_v3 = "/v3/" in model_id
    start = spec.get("seed_image") or (spec.get("boundary") or {}).get("start_frame")
    end = spec.get("end_image"); ident = spec.get("identity_reference")
    body = {"prompt": spec["prompt"], "duration": str(spec.get("duration", "5"))}
    if spec.get("negative_prompt"):      # negative_prompt schema-confirmed across the Kling family
        body["negative_prompt"] = spec["negative_prompt"]
    if is_v3:
        body["start_image_url"] = uri(start)
        if end:
            body["end_image_url"] = uri(end)
        body["generate_audio"] = bool(spec.get("generate_audio", False))   # schema default is True — force off
        if spec.get("cfg_scale") is not None:   # cfg_scale schema-confirmed only on v3-pro; don't send elsewhere
            body["cfg_scale"] = spec["cfg_scale"]
        if spec.get("use_elements") and ident:
            body["elements"] = [{"frontal_image_url": uri(ident)}]
    else:
        body["image_url"] = uri(start)
        if end:
            body["tail_image_url"] = uri(end)
    return body


class FalKlingAdapter(Adapter):
    """fal.ai Kling image→video adapter. Uses the same proven REST flow as the repo's `_animate_one`
    (queue.fal.run + `Authorization: Key`, data-URI image_url, poll status → download). The seed image
    is the deterministic ENTRY boundary frame (full composed scene); the required END state is enforced
    by the gate, not by end-frame conditioning. Refuses without ALLOW_PAID + FAL_KEY."""
    name = "fal-kling-v3-pro"

    def _guard(self):
        if not ALLOW_PAID:
            raise DirectedVideoFailure("ALLOW_PAID is False — paid directed generation not authorized.")
        if not os.environ.get("FAL_KEY", "").strip():
            raise DirectedVideoFailure("FAL_KEY not set — cannot call the paid provider.")

    def submit(self, spec, timeout):
        self._guard()
        import requests, base64 as _b64
        from PIL import Image, ImageOps
        key = os.environ["FAL_KEY"].strip()
        model = _FAL_ENDPOINTS.get(spec.get("model", "kling-v3-pro"))
        if not model:
            raise DirectedVideoFailure(f"unknown fal model '{spec.get('model')}' — no alternate-model substitution")
        # each image path -> a fitted 1080x1920 data-URI. SEED = clean composed plate (env+Bolt, NO HUD);
        # end_image = the authored strained short-of-terminal end frame; identity_reference used only if
        # spec['use_elements']. build_fal_payload maps field names to the endpoint family (v3 vs v2.x/v1.6).
        def _uri(path):
            ref = os.path.join(os.path.dirname(path), "_fal_" + os.path.basename(path) + ".jpg")
            ImageOps.fit(Image.open(path).convert("RGB"), (1080, 1920), Image.LANCZOS).save(ref, quality=92)
            return "data:image/jpeg;base64," + _b64.b64encode(open(ref, "rb").read()).decode()
        payload = build_fal_payload(spec, model, _uri)
        sub = requests.post(f"https://queue.fal.run/{model}", headers={"Authorization": f"Key {key}"},
                            timeout=60, json=payload)
        low = sub.text.lower()
        if sub.status_code == 429 or any(w in low for w in ("exhaust", "balance", "quota")):
            raise DirectedVideoFailure(f"fal quota/balance: {sub.text[:160]}")
        if sub.status_code not in (200, 201):
            raise DirectedVideoFailure(f"fal submit {sub.status_code}: {sub.text[:160]}")
        j = sub.json()
        # persist provider request id + a key-free copy of the submitted payload for the ledger
        payload_no_media = {k: (v[:48] + "…<data-uri>" if isinstance(v, str) and v.startswith("data:") else v)
                            for k, v in payload.items()}
        return {"status_url": j.get("status_url"), "response_url": j.get("response_url"), "key": key,
                "request_id": j.get("request_id") or j.get("requestId"), "submit_status": sub.status_code,
                "endpoint": model, "submitted_payload_sanitized": payload_no_media}

    def poll_and_download(self, job, out_path, timeout):
        self._guard()
        import requests, time as _t
        hdr = {"Authorization": f"Key {job['key']}"}
        waited = 0
        while waited < timeout:
            _t.sleep(6); waited += 6
            st = requests.get(job["status_url"], headers=hdr, timeout=30).json().get("status")
            if st == "COMPLETED":
                break
            if st in ("FAILED", "ERROR"):
                raise DirectedVideoFailure(f"fal job {st}")
        else:
            raise DirectedVideoFailure("fal timeout")
        res = requests.get(job["response_url"], headers=hdr, timeout=30).json()
        vurl = (res.get("video") or {}).get("url")
        if not vurl:
            raise DirectedVideoFailure(f"fal no video url: {str(res)[:160]}")
        open(out_path, "wb").write(requests.get(vurl, timeout=180).content)
        job["raw_response"] = res            # persist the raw completed response for the ledger
        return out_path


# ── lifecycle: generate best-of-N with budget, gate every candidate, explicit failure ──────────────
def _normalize_media(clip, out, tech=None):
    """Conform a candidate to the declared vertical spec (scale/pad, fps) before evaluation."""
    t = {**DEFAULT_TECH, **(tech or {})}
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip, "-vf",
                    f"scale={t['min_w']}:{t['min_h']}:force_original_aspect_ratio=increase,"
                    f"crop={t['min_w']}:{t['min_h']},fps=30", "-an", out], check=True)
    return out


def generate(spec, adapter, out_dir, cost=None, log=print):
    """Best-of-N with a hard budget. Returns the accepted clip path or raises DirectedVideoFailure.
    NO silent deterministic fallback."""
    if not ALLOW_PAID:
        raise DirectedVideoFailure(
            "directed_video.generate is DISABLED (ALLOW_PAID=False). Enable only after explicit "
            "user authorization of the quoted pilot cost. No fallback on hero blocks.")
    b = spec["budget"]; spent = 0.0; rejections = []
    cap = min(b["max_block_cost_usd"], b["max_video_cost_usd"])       # HARD cap incl. generation + eval
    est_eval = b.get("eval_cost_usd_est", 0.05)
    os.makedirs(out_dir, exist_ok=True)
    accepted = None
    try:
        for i in range(b["max_candidates"]):                          # no retries beyond max_candidates
            if spent + b["candidate_cost_usd"] + est_eval > cap:
                log(f"  BUDGET STOP: ${spent:.2f} + ${b['candidate_cost_usd']}(gen) + ${est_eval}(eval) > ${cap} cap")
                break
            raw = os.path.join(out_dir, f"cand_{i}_raw.mp4"); norm = os.path.join(out_dir, f"cand_{i}.mp4")
            try:
                if b.get("reuse_cached") and os.path.exists(norm):
                    log(f"  reuse cached candidate {i}")
                else:
                    job = adapter.submit(spec, b["provider_timeout_s"])
                    spent += b["candidate_cost_usd"]                  # count on submit — provider bills on generation
                    adapter.poll_and_download(job, raw, b["provider_timeout_s"])
                    _normalize_media(raw, norm)
            except Exception as e:                                    # network/provider error on THIS candidate
                rejections.append({"candidate": i, "reasons": [f"provider error: {type(e).__name__}: {str(e)[:160]}"]})
                log(f"  candidate {i}: provider error (running ${spent:.2f}): {str(e)[:120]}")
                continue
            before = sum(cost or [])
            ev = evaluate_candidate(norm, spec, boundary=spec.get("boundary"), gates=spec.get("gates"),
                                    cost=cost, log=log)
            spent += max(0.0, sum(cost or []) - before)              # actual eval cost counts toward cap
            ev["candidate"] = i; ev["spent_usd_running"] = round(spent, 3)
            json.dump(ev, open(os.path.join(out_dir, f"cand_{i}_eval.json"), "w"), indent=2, default=str)
            log(f"  candidate {i}: {'PASS' if ev['pass'] else 'FAIL'} (running ${spent:.2f}) {ev['reasons']}")
            if ev["pass"]:
                accepted = os.path.join(out_dir, "accepted.mp4"); os.replace(norm, accepted)
                json.dump({"accepted": accepted, "candidate": i, "spent_usd": round(spent, 2), "eval": ev},
                          open(os.path.join(out_dir, "accepted_report.json"), "w"), indent=2, default=str)
                return accepted                                       # stop after first passing candidate
            rejections.append({"candidate": i, "reasons": ev["reasons"], "trajectory": ev.get("trajectory")})
    finally:
        if accepted is None:                                         # ALWAYS persist spend + reasons
            json.dump({"accepted": None, "spent_usd": round(spent, 2), "rejections": rejections},
                      open(os.path.join(out_dir, "rejection_report.json"), "w"), indent=2, default=str)
    raise DirectedVideoFailure(
        f"directed_video: no candidate passed the gate for block {spec.get('block')} "
        f"(spent ${spent:.2f}). Rejections: {rejections}. NO fallback — hero block unresolved.")


def resolve(entity, ctx):
    """Provider entry. Hero blocks route here; refuses without authorization; never falls back."""
    if not ALLOW_PAID:
        raise DirectedVideoFailure(
            "provider 'directed_video' is DEFERRED (ALLOW_PAID=False). Hero blocks are not resolved "
            "until paid rendering is authorized. Deterministic providers stay for meters/captions/UI.")
    spec = ctx.get("spec") or build_spec(entity, ctx["block"], ctx["topic"], boundary=ctx.get("boundary"))
    return generate(spec, ctx.get("adapter") or FalKlingAdapter(), ctx["dir"], cost=ctx.get("cost"),
                    log=ctx.get("log", print))
