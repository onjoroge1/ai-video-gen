"""AUTHORIZED Shot-A pilot (oxygen_dry_approach_A). Kling v3-pro, <=3 candidates, $2.00 all-in hard cap,
stop after first automated complete pass. Uses the prepared preflight-approved package (no asset/prompt
redesign). Re-checks preflight before the paid call — if it fails, STOP with no spend. ALLOW_PAID is
enabled only around the call and reset to False in finally (covers timeout/exception/rejection). No
fallback, no alternate model, no deterministic substitution, no auto-insertion. Full-raw-first evaluation
with the four separate authoritative gates. Run: python3 -m bolt_seq.run_shot_A_pilot"""
import os, sys, json, subprocess, base64, traceback
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
from bolt_seq import compiler as C
from bolt_seq.character import BOLT
from bolt_seq.providers import directed_video as DV
from PIL import Image

AT = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription/atomic_shots")
CAND = os.path.join(AT, "candidates"); os.makedirs(CAND, exist_ok=True)
SEED = os.path.join(AT, "shot_A_seed.png"); ENDT = os.path.join(AT, "shot_A_end_target.png")
PROMPT = open(os.path.join(AT, "shot_A_prompt.txt")).read().strip()
CAP, VCOST, EVAL_EST = 2.00, 0.56, 0.16
ROLES = {"hero": BOLT["identity"], "destination": "the wall-mounted mechanical oxygen refill terminal"}
FULL_TECH = {"min_w": 1080, "min_h": 1920, "aspect_wh": 9 / 16, "aspect_tol": 0.06, "dur_min": 4.5, "dur_max": 5.6,
             "fps_min": 16, "fps_max": 60, "max_black_frac": 0.15, "max_frozen_frac": 0.6}
WIN_TECH = {**FULL_TECH, "dur_min": 2.2, "dur_max": 3.7}


def preflight_ok(cost, log):
    """Re-verify seed + end target on the 6 gates BEFORE spending. Any failure => stop, no spend."""
    def chk(img, tag):
        an = DV.anatomy_vlm(img, BOLT["reference"], BOLT["anatomy"], [(0, img)], cost=cost)
        proh = [x for f in an.get("per_frame", []) for x in (f.get("prohibited_seen", []) + f.get("required_altered", []))]
        cp = DV.clean_plate_vlm(img, [(0, img)], cost=cost, expected_objects=["a robot", "a wall-mounted refill terminal"])
        ui = [x for f in cp.get("per_frame", []) for x in f.get("ui_seen", [])]
        env = DV.environment_semantic_gate(img, "a dry oxygen corridor with ONE wall refill terminal",
                                           ["underwater", "aquatic", "portal", "two terminals", "floating terminal"],
                                           ["dry corridor", "one mechanical refill terminal"], cost=cost)
        da = DV.destination_attachment_gate(img, frames=[(0, img)], cost=cost)
        ok = (not proh) and (not ui) and env.get("pass") and da.get("pass") \
            and da.get("readings", {}).get("refill_terminal_count") == 1
        log(f"  preflight {tag}: {'PASS' if ok else 'FAIL'} anat={proh or '-'} ui={ui or '-'} env={env.get('reading')} dest={da.get('readings')}")
        return ok
    return chk(SEED, "seed") and chk(ENDT, "end_target")


def detect_window(clip, cost):
    """Approach window: hero-present + moving toward terminal, trimmed to <=3.5s BEFORE any contact/collapse."""
    dur = DV._probe(clip).get("dur", 5.0) or 5.0
    frames = DV._frames(clip, 12, CAND)
    tv = DV.trace_vlm(clip, ROLES, frames, cost=cost); tr = DV._traces(tv) if "error" not in tv else []
    n = len(tr); ts = [dur * (i + 0.5) / n for i in range(n)]
    contact_i = next((i for i, t in enumerate(tr) if t["hero_c"] and t["dest_c"] and
                      (t["hero_c"][0] > t["dest_c"][0] or DV._dist(t["hero_c"], t["dest_c"]) < 0.08)), None)
    collapse_i = next((i for i, t in enumerate(tr) if t["post"] == 3), None)
    end_i = min([x for x in (contact_i, collapse_i, n - 1) if x is not None])
    start = max(0.15, ts[0]); end = min(ts[end_i] if end_i < n else dur, start + 3.5, dur - 0.05)
    if end - start < 2.2:
        end = min(start + 2.6, dur - 0.05)
    return {"start": round(start, 2), "end": round(end, 2), "dur": round(end - start, 2),
            "contact_frame": contact_i, "collapse_frame": collapse_i, "raw_dur": round(dur, 2)}


def excluded_and_boundaries(full_frames, win_first, win_last, cost):
    import explainer_pipeline as ep
    content = [{"type": "text", "text": "SEED (required start):"},
               {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(open(SEED, "rb").read()).decode()}},
               {"type": "text", "text": "END TARGET (required end):"},
               {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(open(ENDT, "rb").read()).decode()}},
               {"type": "text", "text": "CANDIDATE window first frame:"}, {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(open(win_first, "rb").read()).decode()}},
               {"type": "text", "text": "CANDIDATE window last frame:"}, {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(open(win_last, "rb").read()).decode()}}]
    content += [b for i, (t, fp) in enumerate(full_frames) for b in DV._img_block(fp, f"FULL raw frame {i} @ {t}s:")]
    content.append({"type": "text", "text": (
        "Shot A = a struggling hover-approach only. Return ONLY JSON: {\"start_matches_seed\":0-10,"
        "\"end_matches_target\":0-10,\"collapse\":bool,\"terminal_contact\":bool,\"overshoot\":bool,"
        "\"tumble_or_somersault\":bool,\"legs_or_feet\":bool,\"heroic_acceleration_near_end\":bool,"
        "\"recovers_or_speeds_up\":bool,\"terminal_moved\":bool,\"camera_reset\":bool,\"ui_overlay\":bool} "
        "(judge collapse/contact/overshoot/etc across the FULL raw, not just the window).")})
    try:
        r = ep._claude().messages.create(model="claude-opus-4-8", max_tokens=350, system="Strict Shot-A auditor.",
                                         messages=[{"role": "user", "content": content}])
        cost.append(ep._msg_cost(r.usage)); o, _ = ep._parse_script_json(r.content[0].text)
        return o if isinstance(o, dict) else {"error": "parse"}
    except Exception as e:
        return {"error": str(e)}


def evaluate(raw, norm, cost, log):
    """Full-raw-first, then windowed. Four authoritative gates kept separate."""
    win = detect_window(norm, cost)
    wclip = os.path.join(CAND, os.path.basename(norm).replace(".mp4", "_win.mp4"))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{win['start']}", "-i", norm, "-t", f"{win['dur']}",
                    "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30", "-an", wclip], check=True)
    full_frames = DV._frames(norm, 10, CAND); win_frames = DV._frames(wclip, 9, CAND)
    tech_full = DV.technical_gate(norm, FULL_TECH, {"motion_direction": "right"})
    tech_win = DV.technical_gate(wclip, WIN_TECH, {"motion_direction": "right"})
    an = DV.check_anatomy_temporal(norm, {"identity_reference": BOLT["reference"], "anatomy": BOLT["anatomy"]}, frames=full_frames, cost=cost)
    cp = DV.check_clean_plate(norm, frames=full_frames, cost=cost, expected_objects=["a robot", "a wall-mounted refill terminal"])
    cam = DV.camera_model_gate(wclip, cost=cost)
    dest = DV.destination_attachment_gate(wclip, frames=win_frames, cost=cost)
    traj = DV.trajectory_gate(wclip, ROLES, frames=win_frames, cost=cost)
    nm = DV.natural_character_motion_gate(wclip, frames=win_frames, cost=cost)
    rv = excluded_and_boundaries(full_frames, win_frames[0][1], win_frames[-1][1], cost)
    G = {
        "technical": tech_full["pass"] and tech_win["pass"],
        "environment_semantic": DV.environment_semantic_gate(win_frames[len(win_frames)//2][1],
            "a dry oxygen corridor with ONE wall refill terminal",
            ["underwater", "aquatic", "portal", "two terminals", "floating terminal"], ["dry corridor"], cost=cost).get("pass"),
        "exactly_one_destination": dest.get("readings", {}).get("refill_terminal_count") == 1,
        "camera_coherence": cam["pass"],
        "terminal_world_attachment": dest["pass"],
        "terminal_immobility": bool(dest.get("readings", {}).get("terminal_immobile_vs_wall")),
        "trajectory_toward_terminal": traj.get("approaches"),
        "no_reversal": traj.get("reverses") == 0,
        "no_terminal_contact": (not traj.get("contact")) and (not rv.get("terminal_contact")),
        "no_overshoot": (not traj.get("overshoot")) and (not rv.get("overshoot")),
        "temporal_anatomy": an["identity_pass"] and (not rv.get("legs_or_feet")),
        "identity_continuity": an["identity_pass"],
        "clean_plate": cp["clean_plate_pass"] and (not rv.get("ui_overlay")),
        "natural_character_motion": nm.get("pass"),
        "progressive_effort": (nm.get("scores", {}).get("progressive_effort") or 0) >= 6,
        "propulsion_weakens": (nm.get("scores", {}).get("propulsion_weakens") or 0) >= 6,
        "no_recovery": (not rv.get("recovers_or_speeds_up")) and (not rv.get("heroic_acceleration_near_end")) and (not rv.get("collapse")),
        "start_boundary": (rv.get("start_matches_seed", 0) >= 7),
        "end_boundary": (rv.get("end_matches_target", 0) >= 7),
    }
    reports = {"window": win, "technical_full": tech_full, "technical_window": tech_win, "anatomy": an,
               "clean_plate": cp, "camera": cam, "destination": dest, "trajectory": traj, "natural_motion": nm,
               "review": rv, "wclip": wclip}
    return all(G.values()), G, reports


def contact_sheet(clip, out, n=8):
    d = C.dur(clip) or 5.0; sh = Image.new("RGB", (216 * 4, 384 * 2), (16, 16, 20))
    for i in range(n):
        fp = out + f".{i}.jpg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{d*(i+0.5)/n:.2f}", "-i", clip, "-frames:v", "1", "-vf", "scale=216:384", fp], check=True)
        sh.paste(Image.open(fp), ((i % 4) * 216, (i // 4) * 384))
    sh.save(out, quality=88); return out


def main():
    cost = []; log = print
    print("=== SHOT-A PILOT (v3-pro, <=3 cand, $2.00 cap, stop-after-first-pass) ===", flush=True)
    print("preflight re-check (no spend)...", flush=True)
    if not preflight_ok(cost, log):
        print("PREFLIGHT FAILED — stopping, NO spend. eval cost $%.2f" % sum(cost)); return
    print("preflight PASS — proceeding to authorized paid calls", flush=True)

    spec = {"model": "kling-v3-pro", "seed_image": SEED, "prompt": PROMPT, "budget": {"provider_timeout_s": 600}}
    confirmed = 0.0; potential = 0.0; results = []; accepted = None; err = None
    DV.ALLOW_PAID = True
    try:
        adapter = DV.FalKlingAdapter()
        for i in range(3):
            spent = confirmed + sum(cost)
            if spent + VCOST + EVAL_EST > CAP:
                print(f"  BUDGET STOP before cand {i}: ${spent:.2f}+${VCOST}+${EVAL_EST} would exceed cap ${CAP}"); break
            raw = os.path.join(CAND, f"shotA_cand_{i}_raw.mp4"); norm = os.path.join(CAND, f"shotA_cand_{i}.mp4")
            print(f"  submitting candidate {i}...", flush=True)
            potential += VCOST                      # count as potential spend at submit (may bill even if unretrieved)
            job = adapter.submit(spec, 600)
            adapter.poll_and_download(job, raw, 600)
            confirmed += VCOST; potential -= VCOST  # retrieved => confirmed
            DV._normalize_media(raw, norm)
            ok, G, reports = evaluate(raw, norm, cost, log)
            cs_raw = contact_sheet(norm, os.path.join(CAND, f"shotA_cand_{i}_raw_contact.jpg"))
            cs_win = contact_sheet(reports["wclip"], os.path.join(CAND, f"shotA_cand_{i}_win_contact.jpg"))
            fails = [k for k, v in G.items() if not v]
            results.append({"i": i, "raw": raw, "norm": norm, "window": reports["window"], "wclip": reports["wclip"],
                            "raw_contact": cs_raw, "win_contact": cs_win, "gate_matrix": G, "fails": fails,
                            "automated_pass": ok, "reports": reports})
            print(f"  cand {i}: automated_pass={ok} fails={fails}", flush=True)
            if ok:
                accepted = i; break
    except DV.DirectedVideoFailure as e:
        err = str(e)
    except Exception as e:
        err = f"{type(e).__name__}: {e}\n{traceback.format_exc()[:500]}"
    finally:
        DV.ALLOW_PAID = False                       # ALWAYS reset — timeout/exception/rejection/interrupt

    eval_spend = round(sum(cost), 2)
    ledger = {"confirmed_video_usd": round(confirmed, 2), "potential_unretrieved_video_usd": round(potential, 2),
              "evaluation_usd": eval_spend, "max_possible_total_usd": round(confirmed + potential + eval_spend, 2),
              "hard_cap_usd": CAP, "within_cap": (confirmed + potential + eval_spend) <= CAP}
    rr = subprocess.run([sys.executable, "bolt_seq/tests/test_regression.py"], capture_output=True, text=True, env={**os.environ, "PYTHONPATH": PROJ})
    out = {"shot": "oxygen_dry_approach_A", "model": "kling-v3-pro", "accepted_candidate": accepted, "error": err,
           "candidates_evaluated": len(results), "spend_ledger": ledger,
           "allow_paid_on_disk_after": _disk_allow_paid(), "allow_paid_runtime_after": DV.ALLOW_PAID,
           "inserted_or_published": False, "regression": rr.stdout.strip().splitlines()[-1] if rr.stdout else "",
           "candidates": [{k: v for k, v in r.items() if k != "reports"} for r in results],
           "detail": [r["reports"] for r in results],
           "outcome": ("ACCEPTED pending manual review" if accepted is not None else
                       "NO candidate passed — no salvage, no respend, no substitution")}
    json.dump(out, open(os.path.join(AT, "shot_A_pilot_result.json"), "w"), indent=2, default=str)
    print(f"\n=== DONE === accepted={accepted} | evaluated={len(results)} | confirmed ${confirmed:.2f} + "
          f"potential ${potential:.2f} + eval ${eval_spend:.2f} = max ${ledger['max_possible_total_usd']:.2f} (cap ${CAP})")
    for r in results:
        print(f"  cand {r['i']}: pass={r['automated_pass']} fails={r['fails']}")
    print("regression:", out["regression"], "| ALLOW_PAID on disk:", out["allow_paid_on_disk_after"],
          "| runtime:", DV.ALLOW_PAID, "| inserted:", out["inserted_or_published"])


def _disk_allow_paid():
    import re
    src = open(os.path.join(PROJ, "bolt_seq/providers/directed_video.py")).read()
    m = re.search(r"^ALLOW_PAID\s*=\s*(\w+)", src, re.M)
    return m.group(1) if m else "?"


if __name__ == "__main__":
    main()
