"""Corrected validation framework (zero-spend, read-only on existing hybrid candidates):
(1) OBJECT-CENTRIC seam gate (centroid, scale/area, orientation/roll, pose-aspect, terminal-distance, local flow proxy)
    replacing whole-frame MAE -> records HYBRID_SET1's A1->A2 pop as a TRUE failure.
(2) TEMPORAL COMPOSITE weakness index (eye energy/area, chest emission, body-centroid sink, body angle, forward velocity,
    thruster intensity) replacing thresholded eye-mean -> reports the weakness-onset frame vs the A3 midpoint.
Run: python3 -m bolt_seq.validate_hybrid_v2"""
import os, sys, json
sys.path.insert(0, "/Users/obadiah/Documents/video"); os.chdir("/Users/obadiah/Documents/video")
import numpy as np
from PIL import Image
from scipy import ndimage
H, W = 1920, 1080
D = "renders/bolt_seq/oxygen_subscription/atomic_shots/a1a3_hybrid"
TP = (0.62, 0.46)
A1A2, A2A3 = 66, 142                                                   # assembly boundary indices
A3_LO, A3_MID, A3_HI = 142, 187, 231
_yy, _xx = np.mgrid[0:H, 0:W]; _termbox = (_yy > 560) & (_yy < 1000) & (_xx > 560) & (_xx < 900)


def bmask(a):
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    m = ((np.minimum(np.minimum(R, G), B) > 95) | ((B > R + 15) & (B > 95))) & (~_termbox)
    return ndimage.binary_opening(m, iterations=1)


def obj(a):                                                            # object-centric descriptors of the single Bolt
    m = bmask(a); ys, xs = np.where(m)
    if len(xs) < 50: return None
    cx, cy = xs.mean(), ys.mean(); area = float(m.sum())
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max(); aspect = (y1 - y0) / max(1, x1 - x0)
    x, y = xs - cx, ys - cy; mxx, myy, mxy = (x * x).mean(), (y * y).mean(), (x * y).mean()
    ang = float(np.degrees(0.5 * np.arctan2(2 * mxy, mxx - myy + 1e-6)))   # principal-axis angle (roll proxy)
    tdist = (((cx / W) - TP[0]) ** 2 + ((cy / H) - TP[1]) ** 2) ** 0.5
    return {"cx": cx / W, "cy": cy / H, "area": area / (H * W), "aspect": aspect, "ang": ang, "tdist": tdist}


def eye_energy(a):
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]; head = _yy < 1200
    ey = (B > R + 18) & (B > 90) & head; return float(B[ey].sum() / 1e6)
def chest_energy(a):
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]; mid = (_yy > 1150) & (_yy < 1450)
    ce = (B > R + 18) & (B > 90) & mid; return float(B[ce].sum() / 1e6)
def thruster(a):                                                      # cyan plume energy in the lower band (below the base)
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]; low = _yy > 1400
    pl = (B > R + 25) & (B > 110) & low; return float(B[pl].sum() / 1e6)


def load(name):
    FR = f"{D}/{name}/_frames"; return lambda i: np.asarray(Image.open(f"{FR}/m{i:04d}.png").convert("RGB"), float)


def seam_gate(Lf, bnd, name):
    # per-frame object deltas within each adjacent segment (normal drift) vs the single seam delta
    def d(i, j, k):
        A, B = Lf(i), Lf(j); oa, ob = obj(A), obj(B)
        return None if not (oa and ob) else abs(ob[k] - oa[k])
    keys = ["cx", "cy", "area", "aspect", "ang", "tdist"]
    normal = {k: np.median([v for v in [d(i, i + 1, k) for i in list(range(bnd - 9, bnd - 1)) + list(range(bnd + 1, bnd + 9))] if v is not None]) for k in keys}
    seam = {k: d(bnd - 1, bnd, k) for k in keys}
    # local flow proxy: mean |mask centroid displacement| ratio at seam vs normal (centroid combines cx,cy)
    ratio = {k: (seam[k] / normal[k] if normal[k] and normal[k] > 1e-6 else (999 if seam[k] and seam[k] > 1e-4 else 1)) for k in keys}
    # POP requires a MEANINGFUL absolute step (ratio alone false-positives when normal drift ~0). Distinguish position-step vs pose-flip.
    big_pos = seam["cx"] > 0.035 or seam["cy"] > 0.035
    ratio_pos = (ratio["cx"] > 6 and seam["cx"] > 0.015) or (ratio["cy"] > 6 and seam["cy"] > 0.015)
    big_scale = seam["area"] > 0.10
    pose_flip = seam["aspect"] > 0.15 or abs(seam["ang"]) > 12          # aspect / principal-axis discontinuity
    pop = bool(big_pos or ratio_pos or big_scale or pose_flip)
    sev = ("pose-flip+position" if pose_flip and (big_pos or ratio_pos) else "pose-flip" if pose_flip else "position-step" if (big_pos or ratio_pos) else "clean")
    return {"boundary": bnd, "seam_delta": {k: round(seam[k], 4) for k in keys}, "normal_drift": {k: round(float(normal[k]), 4) for k in keys},
            "seam_over_normal_ratio": {k: round(float(ratio[k]), 1) for k in keys}, "POP": pop, "severity": sev}


def weakness_index(Lf):
    idx = list(range(A3_LO, A3_HI + 1, 3))
    sig = {"eye": [], "chest": [], "sink": [], "ang": [], "vel": [], "thr": []}
    prev = None
    for i in idx:
        a = Lf(i); o = obj(a)
        sig["eye"].append(eye_energy(a)); sig["chest"].append(chest_energy(a))
        sig["sink"].append(o["cy"] if o else 0.5); sig["ang"].append(o["ang"] if o else 0.0)
        sig["thr"].append(thruster(a))
        sig["vel"].append(0.0 if prev is None or not o else (o["cx"] - prev)); prev = o["cx"] if o else prev
    def nz(v, invert=False):
        v = np.array(v, float); lo, hi = v.min(), v.max()
        n = (v - lo) / (hi - lo) if hi > lo else np.zeros_like(v); return (1 - n) if invert else n
    # weakening rises when: eyes DOWN, chest DOWN, sink UP, |angle-from-start| UP, forward velocity DOWN, thruster DOWN
    ang0 = sig["ang"][0]; angdev = [abs(a - ang0) for a in sig["ang"]]
    Wt = (nz(sig["eye"], invert=True) + nz(sig["chest"], invert=True) + nz(sig["sink"]) + nz(angdev) + nz(sig["vel"], invert=True) + nz(sig["thr"], invert=True)) / 6.0
    # weakness "readable" = W sustained above 0.5 for >=3 consecutive samples
    onset = None
    for k in range(len(Wt) - 2):
        if Wt[k] >= 0.5 and Wt[k + 1] >= 0.5 and Wt[k + 2] >= 0.5: onset = idx[k]; break
    mono = all(Wt[k] >= Wt[k - 1] - 0.12 for k in range(1, len(Wt)))   # non-decreasing (no recovery), small tolerance
    return {"onset_frame": onset, "mid_A3_frame": A3_MID, "readable_by_mid": bool(onset is not None and onset <= A3_MID),
            "monotonic_no_recovery": bool(mono), "W_curve": [round(float(x), 2) for x in Wt], "sample_frames": idx}


out = {"objective": "hybrid_validation_framework_v2", "no_spend": True, "candidates": {}}
for name in ["HYBRID_SET1", "HYBRID_SET2"]:
    Lf = load(name)
    a12 = seam_gate(Lf, A1A2, name); a23 = seam_gate(Lf, A2A3, name); wk = weakness_index(Lf)
    out["candidates"][name] = {"A1_A2_object_centric_seam": a12, "A2_A3_object_centric_seam": a23, "temporal_weakness": wk,
                               "A1_A2_pop": a12["POP"], "A2_A3_pop": a23["POP"], "weakness_readable_by_mid": wk["readable_by_mid"]}
    print(f"\n=== {name} ===")
    print(f"  A1->A2 seam POP: {a12['POP']} [{a12['severity']}]  (seam Δcx={a12['seam_delta']['cx']} Δaspect={a12['seam_delta']['aspect']} Δang={a12['seam_delta']['ang']}; cx ratio={a12['seam_over_normal_ratio']['cx']})")
    print(f"  A2->A3 seam POP: {a23['POP']} [{a23['severity']}]  (seam Δcx={a23['seam_delta']['cx']} Δcy={a23['seam_delta']['cy']} Δarea={a23['seam_delta']['area']})")
    print(f"  weakness onset frame: {wk['onset_frame']} (mid-A3={A3_MID}) -> readable_by_mid={wk['readable_by_mid']}; monotonic_no_recovery={wk['monotonic_no_recovery']}")
json.dump(out, open(f"{D}/hybrid_validation_v2.json", "w"), indent=2, default=str)
print("\nwrote hybrid_validation_v2.json"); print("DONE")
