"""Emit the full environment of a simulation as one table: scene, transcript, and every prompt.

Why this is worth having: the inputs that produce a shot are scattered across four places -- the
narration and on-screen text in SCENES, the picture description in PLATE_JOBS, the continuity block
that is prepended to every plate prompt, and the i2v motion prompt. Nobody can hold that in their
head, which is how a beat's narration and its picture drifted apart repeatedly.

Run: /opt/homebrew/bin/python3 tools/scene_table.py <sim_module> [out.md]
     e.g. tools/scene_table.py simulations.water_every_world.data
"""
from __future__ import annotations
import importlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def collect(mod_name):
    m = importlib.import_module(mod_name)
    sim = m.SIM
    jobs = {j[0]: j for j in getattr(m, "PLATE_JOBS", [])}
    cont = getattr(m, "CONTINUITY", sim.locked)
    from sim import plates as P

    # measured durations, if the sim has been rendered
    cuts = {}
    rep_path = os.path.join(sim.out, "build_report.json")
    if os.path.exists(rep_path):
        for c in json.load(open(rep_path)).get("cuts", []):
            cuts[c["seg"]] = c

    rows, t = [], 0.0
    for sc in sim.scenes:
        c = cuts.get(sc.id)
        dur = (c["frames"] / sim.fps) if c else sc.seconds
        start = c["t"] if c else t
        job = jobs.get(sc.image)
        # the ACTUAL i2v ask, from the sidecar written at generation time
        side = os.path.join(sim.work, "clips", f"{sc.image}.json")
        i2v = {}
        if os.path.exists(side):
            try:
                i2v = json.load(open(side))
            except Exception:
                i2v = {}
        rows.append({
            "id": sc.id, "image": sc.image,
            "start": start, "dur": dur,
            "chips": " · ".join(sc.chips) if sc.chips else "",
            "onscreen": sc.onscreen,
            "narration": sc.narration,
            "plate_action": job[1] if job else "(no plate job)",
            "plate_shot": job[2] if job else "",
            "plate_prompt": P.build_prompt(cont, job[1], job[2]) if job else "",
            "motion": sc.motion,
            "i2v_prompt": i2v.get("prompt", ""), "i2v_negative": i2v.get("negative", ""),
            "i2v_model": i2v.get("model", ""), "motion_style": i2v.get("motion_style", ""),
            "motion_measured": (i2v.get("measured_motion") or {}).get("per_frame_mean"),
            "cost_usd": i2v.get("price_usd"), "provenance": i2v.get("provenance", "logged at generation"),
            "animated": bool(c and c.get("animated")),
            "words": len(sc.narration.split()),
        })
        t += dur
    return sim, cont, rows


def rejected(sim):
    """Clips that were billed and thrown away, with the ask that produced them."""
    import glob
    out = []
    for f in sorted(glob.glob(os.path.join(sim.work, "clips", "*.rejected.json"))):
        try:
            out.append(json.load(open(f)))
        except Exception:
            pass
    return out


def markdown(sim, cont, rows, rej=()):
    total = sum(r["dur"] for r in rows)
    words = sum(r["words"] for r in rows)
    L = [f"# {sim.title}", "",
         f"`{sim.slug}` · {len(rows)} scenes · {total:.1f}s · {words} words · "
         f"{words/(total/60):.0f} wpm · {sum(r['animated'] for r in rows)}/{len(rows)} animated", "",
         "## Continuity block (prepended to EVERY plate prompt)", "",
         "```", (cont if isinstance(cont, str) else
                 "\n".join(f"{k}: {v}" for k, v in cont.items())), "```", "",
         "## Scenes", ""]
    for i, r in enumerate(rows, 1):
        L += [f"### {i}. `{r['id']}`  —  {r['start']:.2f}s → {r['start']+r['dur']:.2f}s "
              f"({r['dur']:.2f}s, {r['words']}w){'  · ANIMATED' if r['animated'] else '  · STILL'}",
              "",
              f"| | |", "|---|---|",
              f"| **plate** | `{r['image']}` |",
              f"| **chips** | {r['chips'] or '—'} |",
              f"| **on-screen** | {r['onscreen'] or '—'} |",
              f"| **transcript** | {r['narration']} |",
              f"| **picture (plate action)** | {r['plate_action']} |",
              f"| **framing** | {r['plate_shot'] or '—'} |",
              f"| **motion / i2v intent** | {r['motion'] or '—'} |",
              f"| **i2v prompt SENT** | {r['i2v_prompt'] or '— not recorded —'} |",
              f"| **i2v negative** | {r['i2v_negative'] or '—'} |",
              f"| **measured motion / cost** | {r['motion_measured'] or '—'} · ${r['cost_usd'] or 0:.2f} |",
              f"| **provenance** | {r['provenance']} |",
              ""]
    if rej:
        spent = sum(r.get("price_usd") or 0 for r in rej)
        L += ["## Rejected clips", "",
              f"{len(rej)} clip(s) billed and discarded (${spent:.2f}). These are the more useful "
              f"rows for learning: they record an ask that did not work.", "",
              "| asset | measured | floor | reason | prompt |", "|---|---|---|---|---|"]
        for r in rej:
            L.append(f"| `{r.get('asset')}` | {(r.get('measured_motion') or {}).get('per_frame_mean')} "
                     f"| {r.get('min_motion')} | {r.get('reason','')} | {(r.get('prompt') or '')[:160]} |")
        L.append("")
    recon = [r["id"] for r in rows if "RECONSTRUCTED" in (r.get("provenance") or "")]
    if recon:
        L += ["## Provenance warning", "",
              f"These scenes' i2v prompts were RECONSTRUCTED from `Scene.motion`, not captured at "
              f"generation: **{', '.join(recon)}**. They predate prompt persistence, so the exact "
              f"string sent to the provider is lost and these rows must not be treated as ground "
              f"truth when learning what works.", ""]
    return "\n".join(L)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    mod = args[0] if args else "simulations.water_every_world.data"
    sim, cont, rows = collect(mod)
    out = args[1] if len(args) > 1 else os.path.join(sim.out, "scene_table.md")
    rej = rejected(sim)
    open(out, "w", encoding="utf8").write(markdown(sim, cont, rows, rej))
    json.dump(rows, open(os.path.splitext(out)[0] + ".json", "w"), indent=2, default=str)
    if "--db" in sys.argv:
        import hotd  # loads .env
        import db as DB
        rid = f"{sim.slug}@{int(os.path.getmtime(os.path.join(sim.out, sim.slug + '.mp4')))}" \
            if os.path.exists(os.path.join(sim.out, sim.slug + ".mp4")) else sim.slug
        payload = [{"render_id": rid, "slug": sim.slug, "title": sim.title,
                    "format": (sim.meta or {}).get("kind", ""), "scene_idx": i,
                    "scene_id": r["id"], "image_stem": r["image"], "start_s": r["start"],
                    "dur_s": r["dur"], "words": r["words"], "chips": r["chips"],
                    "onscreen": r["onscreen"], "narration": r["narration"],
                    "plate_action": r["plate_action"], "plate_shot": r["plate_shot"],
                    "plate_prompt": r["plate_prompt"], "motion_intent": r["motion"],
                    "i2v_prompt": r["i2v_prompt"], "i2v_negative": r["i2v_negative"],
                    "i2v_model": r["i2v_model"], "motion_style": r["motion_style"],
                    "motion_measured": r["motion_measured"], "animated": r["animated"],
                    "cost_usd": r["cost_usd"]}
                   for i, r in enumerate(rows)]
        print(f"db: wrote {DB.scenes_upsert(payload)} scene rows as render {rid}")
    print(f"{len(rows)} scenes -> {out}")
    if rej:
        print(f"{len(rej)} rejected clip(s), ${sum(r.get('price_usd') or 0 for r in rej):.2f} wasted")
    print(f"{sum(r['dur'] for r in rows):.1f}s  {sum(r['words'] for r in rows)} words  "
          f"{sum(r['animated'] for r in rows)}/{len(rows)} animated")
