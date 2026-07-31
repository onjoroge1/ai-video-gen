"""Regression: locks the two evaluator corrections discovered on A2 (effortful approach) + confirms the frozen
A2 acceptance and that A1's launch-window behavior is unchanged.

  1. retention_window: LAUNCH primitives may trim the detected onset; CONTINUATION primitives (A2/A3) MUST
     retain t=0 (their start frame IS the prior clip's endpoint — trimming the onset breaks the seam).
  2. endpoint scale for tilted/reaching poses uses the rotation-invariant bright-AREA ratio, NOT the p2/p98
     bbox height (which reads ~1.7x on A2's tilted end and false-fails).
  3. A1 (launch) endpoint + retention behavior still passes after the change.
  4. A2 is frozen + accepted; the rejected diagnostics are excluded from the registry's accepted set.

Run: python3 -m bolt_seq.tests.test_continuation_eval"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"), override=True)
from bolt_seq.providers import directed_video as DV
from bolt_seq import motion_registry as MR

AT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                  "renders", "bolt_seq", "oxygen_subscription", "atomic_shots")
_checks = []
def check(name, cond):
    _checks.append((name, bool(cond))); print(("PASS " if cond else "FAIL ") + name)


def run():
    # 1. retention_window logic (pure, no fixtures)
    L = DV.retention_window("launch", {"onset_t": 0.66, "action_end_t": 2.5})
    C = DV.retention_window("continuation", {"onset_t": 0.46, "action_end_t": 2.48})
    check("launch primitive trims to the detected onset", L["start_t"] == 0.66 and L["retained_onset"] is True)
    check("continuation primitive retains t=0 (seam)", C["start_t"] == 0.0 and C["retained_onset"] is False)
    check("continuation end_t preserved", C["end_t"] == 2.48)
    try:
        DV.retention_window("bogus", {"onset_t": 0, "action_end_t": 1}); bad = False
    except ValueError:
        bad = True
    check("retention_window rejects unknown primitive kind", bad)

    # 2. endpoint scale uses bright-AREA ratio (tilted A2 end) — area passes where percentile height fails
    a2_raw = f"{AT}/a2_approach/pilot/a2_bodyonly.mp4"; a2_end = f"{AT}/a2_approach/A2_end.png"
    if os.path.exists(a2_raw) and os.path.exists(a2_end):
        ep = DV.endpoint_geometry_gate(a2_raw, a2_end)
        fv = ep["final_vs_authored"]
        check("A2 endpoint uses area_ratio as the scale metric", ep.get("scale_metric") == "area_ratio")
        check("A2 endpoint PASSES on area scale", ep["pass"] is True and 0.90 <= ep["scale_value"] <= 1.10)
        check("percentile height_ratio WOULD have false-failed (>1.10)", fv.get("height_ratio", 0) > 1.10)
    else:
        check("A2 endpoint fixtures present", False)

    # 3. A1 (launch) endpoint still passes with area scale; launch retention unchanged
    a1_win = f"{AT}/a1_accepted/A1_clean_body_window.mp4"; a1_end = f"{AT}/primitives/A1body_B1.png"
    if os.path.exists(a1_win) and os.path.exists(a1_end):
        ep1 = DV.endpoint_geometry_gate(a1_win, a1_end)
        check("A1 launch endpoint still PASSES after the change", ep1["pass"] is True)
    else:
        check("A1 launch fixtures present", False)

    # 4. A2 frozen + accepted; rejects excluded from the accepted set
    for f in ["a2_accepted/A2_production_primitive.mp4", "a2_accepted/A2_final_frame.png",
              "a2_accepted/A2_manifest.json", "a3_weakening/A3_start_frame.png"]:
        check(f"frozen fixture present: {f}", os.path.exists(os.path.join(AT, f)))
    ap = MR.get("bolt.approach")
    check("bolt.approach is accepted", ap and ap["status"] == "accepted")
    check("bolt.approach marked continuation", ap and ap.get("primitive_kind") == "continuation")
    for rid in ["bolt.A2.optB_strain", "bolt.A2.end_body"]:
        e = MR.get(rid)
        check(f"{rid} is rejected_diagnostic (excluded)", e and e["status"] == "rejected_diagnostic" and e.get("clip") is None)

    # 5. A3: structural shell scale is INVARIANT to intentional eye dimming (item 11) + sink metric + plate gate
    import numpy as np
    from PIL import Image
    a3s = f"{AT}/a3_weakening/A3_start_frame.png"; a3e = f"{AT}/a3_weakening/A3_end.png"
    if os.path.exists(a3s) and os.path.exists(a3e):
        Wd, Hd = 1080, 1920
        sa = np.asarray(Image.open(a3s).convert("RGB").resize((Wd, Hd)), float)
        ea = np.asarray(Image.open(a3e).convert("RGB").resize((Wd, Hd)), float)
        sh_s = DV._structural_shell_area(sa, Wd, Hd); sh_e = DV._structural_shell_area(ea, Wd, Hd)
        check("A3 structural shell scale stable despite eye dimming (real start->end)", 0.97 <= sh_e / sh_s <= 1.03)
        bc_s = DV._base_centroid_y(sa, Wd, Hd)[0]; bc_e = DV._base_centroid_y(ea, Wd, Hd)[0]
        check("A3 base-centroid sink >= 0.04 (pitch-robust metric)", (bc_e - bc_s) >= 0.04)
        check("plate_consistency_gate available", hasattr(DV, "plate_consistency_gate"))
        pk = json.load(open(f"{AT}/a3_weakening_package.json"))["boundary_checks"]
        check("A3 eye-edge integrity PASS (no dark line/cap, smooth ovals)", pk["eye_edge_pass"])
        check("A3 reach fails (hand-terminal distance increases)", pk["reach_fails_dist_increases"])
        check("A3 eye luminance reduced 15-25%", pk["eye_lum_reduce_0.15_0.25"])
        check("A3 base-centroid sink 0.04-0.06", pk["sink_ok_0.04_0.06"])
        check("A3 structural scale stable 0.97-1.03", pk["scale_stable_0.97_1.03"])
        check("A3 VFX clean both frames", pk["vfx_absent_both"])
    else:
        check("A3 boundary fixtures present", False)

    failed = [n for n, ok in _checks if not ok]
    print(f"\n{len(_checks)-len(failed)}/{len(_checks)} passed")
    if failed: print("FAILED:", failed)
    return not failed


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
