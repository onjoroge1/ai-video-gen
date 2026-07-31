"""Retention gate + critic-guided repair (GENERIC). Required-role validation is not enough: a video
that scores comprehension=4 / hook=5 must NOT be reported as a success. This module scores the finished
animatic on retention axes, returns a VERDICT (PASS / REPAIRABLE / FAIL), and — when REPAIRABLE — a
per-block diagnosis (failed block, failure type, likely cause, recommended correction, and the repair
ACTION to take). `apply_fix` turns a diagnosis into a concrete, deterministic staging change on a single
block so the orchestrator can re-render just that block, not the whole video."""
from __future__ import annotations
import os, copy, subprocess, base64, json

AXES = ["frame_one_action", "two_second_premise_clarity", "early_first_payoff", "curiosity_reset",
        "semantic_state_change_frequency", "escalation_strength", "muted_comprehension",
        "climax_stronger_than_hook", "visual_causality", "ending_loop_quality", "dead_exposition_absence"]
_CRITICAL = ["frame_one_action", "two_second_premise_clarity", "muted_comprehension"]
ACTIONS = ["regenerate_asset", "revise_staging", "revise_script", "alter_caption", "rerender_motion"]


def classify(scores):
    vals = [scores.get(a) for a in AXES if isinstance(scores.get(a), (int, float))]
    if not vals:
        return "FAIL", 0.0
    mean = sum(vals) / len(vals)
    crit = [scores.get(a, 0) for a in _CRITICAL]
    if min(crit) < 3 or mean < 4.5:
        return "FAIL", round(mean, 2)
    if mean >= 7 and min(vals) >= 5:
        return "PASS", round(mean, 2)
    return "REPAIRABLE", round(mean, 2)


def _block_frames(final, blocks, lb, out_dir):
    """One representative frame per block (block midpoint) for block-attributed diagnosis."""
    frames = []
    for blk in blocks:
        s = lb[blk["lines"][0]][0]; e = lb[blk["lines"][-1]][1]; mid = (s + e) / 2
        fp = os.path.join(out_dir, f"_ret_{blk['id']}.jpg")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{mid:.2f}", "-i", final,
                        "-frames:v", "1", "-vf", "scale=360:640", fp], check=True)
        frames.append((blk, fp))
    return frames


def score(final, narration, subject, blocks, lb, out_dir, cost=None, log=print, model="claude-opus-4-8"):
    import explainer_pipeline as ep
    bf = _block_frames(final, blocks, lb, out_dir)
    content = []
    for blk, fp in bf:
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                        "data": base64.b64encode(open(fp, "rb").read()).decode()}})
        content.append({"type": "text", "text": f"block {blk['id']} (role {blk.get('role')}): "
                        + " / ".join(narration[i] for i in blk["lines"])})
    content.append({"type": "text", "text": (
        f"This is a vertical Short about {subject}; the frames above are one per block in order. Score the "
        f"WHOLE video 0-10 on each axis: {', '.join(AXES)} (dead_exposition_absence: 10=no dead exposition). "
        "Then, for the 1-2 WEAKEST blocks, give a diagnosis. Return ONLY JSON: {\"scores\":{axis:n,...},"
        "\"diagnoses\":[{\"block\":id,\"failure_type\":str,\"likely_cause\":str,\"recommended_correction\":str,"
        f"\"action\":one of {ACTIONS},\"new_caption\":str}}],\"notes\":str}}")})
    try:
        r = ep._claude().messages.create(model=model, max_tokens=900,
            system="You are a strict short-form retention critic. Judge only what the frames show; be specific per block.",
            messages=[{"role": "user", "content": content}])
        if cost is not None:
            cost.append(ep._msg_cost(r.usage))
        obj, _ = ep._parse_script_json(r.content[0].text)
        obj = obj if isinstance(obj, dict) else {}
    except Exception as e:
        return {"error": str(e), "verdict": "FAIL", "scores": {}, "diagnoses": []}
    scores = obj.get("scores", {})
    verdict, mean = classify(scores)
    out = {"scores": scores, "mean": mean, "verdict": verdict, "diagnoses": obj.get("diagnoses", []),
           "notes": obj.get("notes", "")}
    log(f"[retention] verdict={verdict} mean={mean} | " +
        " ".join(f"{a}={scores.get(a)}" for a in _CRITICAL))
    return out


def worst_block(report):
    d = report.get("diagnoses") or []
    return d[0] if d else None


def apply_fix(topic, block_id, diagnosis):
    """Turn a diagnosis into a concrete, deterministic change to ONE block. Returns (topic_copy, note).
    Generic levers: raise subject prominence, declutter background effects, and/or clarify the caption."""
    t = copy.deepcopy(topic)
    blk = next((b for b in t["blocks"] if b["id"] == block_id), None)
    if blk is None:
        return t, "block not found"
    ov = blk.setdefault("entity_overrides", {})
    action = (diagnosis or {}).get("action", "revise_staging")
    notes = []

    # subject prominence (character → prop → destination)
    subj = next((e for e in t["entities"] if e.get("kind") == "character"), None) \
        or next((e for e in t["entities"] if e.get("kind") in ("prop", "destination")), None)
    if subj and action in ("revise_staging", "rerender_motion", "regenerate_asset"):
        cur = ov.get(subj["id"], {}).get("base_h", subj.get("base_h", 500))
        ov.setdefault(subj["id"], {})["base_h"] = int(cur * 1.18)
        notes.append(f"{subj['id']} base_h→{int(cur*1.18)}")

    # declutter distracting full-frame effects/particles for this block (keep meters/HUD)
    if action in ("revise_staging",):
        from bolt_seq import scene_graph as SG
        for e in t["entities"]:
            if e.get("kind") in ("effect", "particles") and e.get("draw") not in ("resource_meter",):
                ov.setdefault(e["id"], {}).setdefault("tracks", {})["opacity"] = SG.const_track(0.35)
        for o in blk.get("overlays", []):
            if o.get("draw") in ("speed_streaks", "rising_bubbles", "fog_whiteout"):
                o.setdefault("tracks", {})["opacity"] = SG.const_track(0.3)
        notes.append("decluttered background effects")

    # caption clarity
    if action == "alter_caption" and diagnosis.get("new_caption"):
        i = blk["lines"][0]
        t["captions"][i] = diagnosis["new_caption"][:22].upper()
        notes.append(f"caption[{i}]→'{t['captions'][i]}'")

    return t, "; ".join(notes) or "no-op"
