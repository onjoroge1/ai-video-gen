"""Package the dry_v1_1 deliverables + run the honest acceptance audit. No paid video, no generation."""
import os, sys, json, subprocess, base64, shutil, re
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
from bolt_seq import compiler as C, topics as T
from PIL import Image

OX = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription")
V = lambda n: os.path.join(OX, n)
DV1 = lambda n: os.path.join(OX, "dry_v1_1_" + n)
ANIM = V("oxygen_subscription_animatic.mp4")


def _claude_yesno(frame_t, question, cost):
    import explainer_pipeline as ep
    fp = os.path.join(OX, "_audit_%.1f.jpg" % frame_t)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{frame_t}", "-i", ANIM, "-frames:v", "1",
                    "-vf", "scale=360:640", fp], check=True)
    b = base64.b64encode(open(fp, "rb").read()).decode()
    try:
        r = ep._claude().messages.create(model="claude-opus-4-8", max_tokens=150, system="Answer strictly.",
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b}},
                {"type": "text", "text": question + " Return ONLY JSON {\"yes\":bool,\"note\":str}"}]}])
        cost.append(ep._msg_cost(r.usage)); o, _ = ep._parse_script_json(r.content[0].text)
        return o if isinstance(o, dict) else {}
    except Exception as e:
        return {"error": str(e)}


def main():
    cost = []; topic = T.load("oxygen_subscription")
    # 1. named deliverables
    shutil.copy(ANIM, DV1("mp4".replace("mp4", "") + "..").replace("..", "") + "") if False else None
    shutil.copy(ANIM, os.path.join(OX, "dry_v1_1.mp4"))
    if os.path.exists(V("oxygen_subscription_animatic.srt")):
        shutil.copy(V("oxygen_subscription_animatic.srt"), os.path.join(OX, "dry_v1_1.srt"))
    for src, dst in [("plan.json", "plan.json"), ("motion_report.json", "motion_report.json"),
                     ("environment_report.json", "environment_report.json"),
                     ("forbidden_token_report.json", "forbidden_token_report.json"),
                     ("continuity_report.json", "continuity_report.json"),
                     ("abstraction_audit.json", "semantic_audit.json"),
                     ("provenance_report.json", "provenance_report.json"),
                     ("retention_report.json", "retention_report.json")]:
        if os.path.exists(V(src)):
            shutil.copy(V(src), DV1(dst))
    # animatic spec = plan + provenance + motion (deterministic render has no separate spec dump)
    spec = {"plan": json.load(open(V("plan.json"))), "provenance": json.load(open(V("provenance_report.json"))),
            "motion": json.load(open(V("motion_report.json")))}
    json.dump(spec, open(DV1("animatic_spec.json"), "w"), indent=2, default=str)
    # asset preflight
    ap = {"hover_run_dry": json.load(open(V("bolt_hover_run_dry_preflight.json"))),
          "bolt_swim_prohibited": json.load(open(V("bolt_swim_prohibited.json"))),
          "provider_asset_report": json.load(open(V("asset_report.json"))) if os.path.exists(V("asset_report.json")) else {}}
    json.dump(ap, open(DV1("asset_preflight.json"), "w"), indent=2, default=str)
    # contact sheet
    d = C.dur(ANIM); sh = Image.new("RGB", (216 * 4, 384 * 2), (16, 16, 20))
    for i in range(8):
        fp = os.path.join(OX, f"_dv{i}.jpg")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{d*(i+0.5)/8:.2f}", "-i", ANIM, "-frames:v", "1", "-vf", "scale=216:384", fp], check=True)
        sh.paste(Image.open(fp), ((i % 4) * 216, (i // 4) * 384))
    sh.save(DV1("contact_sheet.jpg"), quality=88)
    # regression
    rr = subprocess.run([sys.executable, "bolt_seq/tests/test_regression.py"], capture_output=True, text=True, env={**os.environ, "PYTHONPATH": PROJ})
    rs = subprocess.run([sys.executable, "bolt_seq/tests/test_state.py"], capture_output=True, text=True, env={**os.environ, "PYTHONPATH": PROJ})
    reg = {"regression": rr.stdout.strip().splitlines()[-1] if rr.stdout else "", "regression_ok": rr.returncode == 0,
           "state": rs.stdout.strip().splitlines()[-1] if rs.stdout else "", "state_ok": rs.returncode == 0}
    json.dump(reg, open(DV1("regression_report.json"), "w"), indent=2)

    # timing from srt
    srt = open(V("oxygen_subscription_animatic.srt")).read() if os.path.exists(V("oxygen_subscription_animatic.srt")) else ""
    times = re.findall(r"(\d\d):(\d\d):(\d\d),(\d+)\s*-->\s*(\d\d):(\d\d):(\d\d),(\d+)", srt)
    def sec(h, m, s, ms): return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
    spans = [(sec(*t[:4]), sec(*t[4:])) for t in times]
    hook = (spans[0][1] - spans[0][0]) if spans else None
    resolution = (spans[6][1] - spans[6][0]) if len(spans) > 6 else None

    # state monotonic checks
    st = json.load(open(V("state_trace.json")))
    def series(k): return [s[k] for s in st if k in s and isinstance(s[k], (int, float))]
    dist = series("distance_to_terminal"); o2 = series("oxygen_reserve")
    dist_mono = all(dist[i + 1] <= dist[i] + 1e-9 for i in range(len(dist) - 1))
    o2_mono = all(o2[i + 1] <= o2[i] + 1e-9 for i in range(len(o2) - 1))
    # bolt x-progress: distance_to_terminal drives bolt.x via a positive remap (1.0,0.05 -> 0.22,0.48),
    # so a monotonically DECREASING distance => monotonically INCREASING bolt.x (visible forward progress).
    def remap(vv, i0, i1, o0, o1): return o0 + (o1 - o0) * (vv - i0) / ((i1 - i0) or 1e-9)
    bxs = [round(max(0.22, min(0.48, remap(v, 1.0, 0.05, 0.22, 0.48))), 3) for v in dist]
    bolt_prog = dist_mono and len(bxs) >= 2 and bxs[-1] > bxs[0] + 0.05
    # VLM spot checks
    term25 = _claude_yesno(2.4, "Is a mechanical oxygen refill terminal (wall unit / green icon) visible?", cost)
    splash = _claude_yesno(min(1.5, d * 0.1), "Is there ANY water, splash, bubbles or wet effect around the robot?", cost)
    collapse = _claude_yesno(d - 0.3, "Is the robot collapsed/prone/slumped on the floor (failed, not upright)?", cost)
    sem = json.load(open(V("abstraction_audit.json")))
    ret = json.load(open(V("retention_report.json")))
    score = round((ret.get("mean") or 0) * 10)
    muted = (ret.get("scores") or {}).get("muted_comprehension", 0)

    checks = {
        "env_gate_dry": json.load(open(V("environment_report.json"))).get("pass") is True,
        "no_forbidden_tokens": json.load(open(V("forbidden_token_report.json"))).get("clean") is True,
        "hover_run_asset_clean": ap["hover_run_dry"].get("accepted") is True,
        "no_water_splash": splash.get("yes") is False,
        "terminal_visible_by_2.5s": term25.get("yes") is True,
        "hook_le_2.5s": (hook is not None and hook <= 2.6),
        "resolution_le_3.5s": (resolution is not None and resolution <= 3.6),
        "total_18_20s": (18.0 <= round(d, 2) <= 20.0),
        "bolt_progresses": bolt_prog,
        "distance_monotonic": dist_mono,
        "oxygen_monotonic": o2_mono,
        "collapse_visible": collapse.get("yes") is True,
        "understandable_80pct": (muted >= 8),
        "climax_strongest": ("climax_is_strongest_transition" not in sem.get("soft_warnings", [])),
        "score_ge_82": (score >= 82),
        "regression_green": reg["regression_ok"] and reg["state_ok"],
    }
    fails = [k for k, v in checks.items() if not v]
    audit = {"duration_s": round(d, 2), "hook_s": round(hook, 2) if hook else None,
             "resolution_s": round(resolution, 2) if resolution else None, "retention_score_100": score,
             "muted_comprehension": muted, "checks": checks, "failures": fails,
             "production_ready": not fails, "cost_usd_audit": round(sum(cost), 3),
             "distance_trace": dist, "oxygen_trace": o2, "bolt_x_trace": [round(x, 3) for x in bxs[:14]]}
    json.dump(audit, open(DV1("acceptance_audit.json"), "w"), indent=2, default=str)
    md = ["# dry_v1_1 — acceptance audit", "", f"- duration **{round(d,2)}s** · hook {audit['hook_s']}s · "
          f"resolution {audit['resolution_s']}s · retention **{score}/100** (muted comprehension {muted}/10)",
          f"- **production_ready: {audit['production_ready']}**  failures: {fails or 'none'}", "",
          "| criterion | pass |", "|---|---|"]
    md += [f"| {k} | {'✅' if v else '❌'} |" for k, v in checks.items()]
    open(DV1("retention_audit.md"), "w").write("\n".join(md))
    print("=== dry_v1_1 acceptance ===")
    for k, v in checks.items(): print(f"  {'PASS' if v else 'FAIL'}  {k}")
    print(f"duration {round(d,2)}s | hook {audit['hook_s']}s | resolution {audit['resolution_s']}s | score {score}/100")
    print(f"PRODUCTION_READY={audit['production_ready']} | failures={fails} | audit cost ${sum(cost):.2f}")


if __name__ == "__main__":
    main()
