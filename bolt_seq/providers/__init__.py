"""Providers layer (GENERIC). A provider resolves an entity's pixels (its `images`/`image`) before
rendering. The scene graph and orchestrator never call an image API directly — they ask the entity's
provider to resolve its assets, so swapping deterministic composites for generated frames (or, later,
paid directed motion) is a config change, not a code change.

Registry (name -> {resolve, status, note}):
  deterministic_2d  ACTIVE   pre-made cutout/plate composited by code; procedural draws need no asset
  image_generator   ACTIVE   gpt-image-2 stills + VLM preflight (poses via the perceptual gate)
  manual_asset      ACTIVE   a fixed file path supplied by a human; validated to exist
  ambient_i2v       DECLARED Kling image->video ambient motion (not used this phase)
  directed_video    DEFERRED paid directed motion (Phase 3 — gated by the perceptual critic)
  layered_rig       DECLARED segmented limb rig with squash/stretch (not built — the honest gap)"""
from __future__ import annotations
import os


def _abs(ctx, p):
    return p if os.path.isabs(p) else os.path.join(ctx["dir"], p)


def _dv():
    from bolt_seq.providers import directed_video
    return directed_video


def _resolve_paths(entity, ctx):
    """deterministic_2d / manual_asset: entity supplies existing image path(s); procedural draws pass."""
    a = entity.get("asset", {})
    if entity.get("draw"):
        return entity                                   # meters/effects have no image asset
    if a.get("poses"):
        entity["images"] = {k: _abs(ctx, v["path"]) for k, v in a["poses"].items() if v.get("path")}
        entity.setdefault("pose0", next(iter(entity["images"]), None))
        entity["image"] = next(iter(entity["images"].values()), None)
    elif a.get("path"):
        entity["image"] = _abs(ctx, a["path"])
    for p in ([entity.get("image")] + list((entity.get("images") or {}).values())):
        if p and not os.path.exists(p):
            raise FileNotFoundError(f"provider '{entity.get('provider')}' entity '{entity['id']}': missing {p}")
    return entity


def _resolve_generated(entity, ctx):
    """image_generator: gen_image + preflight. Character poses use the perceptual pose gate;
    plates/props use the yes/no checklist gate. Cutouts are chroma-keyed to alpha."""
    from bolt_seq import compiler as C
    a = entity.get("asset", {})
    cutout = a.get("cutout", entity.get("kind") in ("character", "prop", "equipment", "destination"))
    size = a.get("size", "1024x1536")
    idn = a.get("identity")
    reps = ctx.setdefault("asset_reports", {})
    # gpt-image-2 has no transparent bg → cutouts MUST render on solid magenta for chroma-key. Enforce
    # this regardless of how the prompt was authored (idea_compiler prompts may omit it).
    KEYBG = (" The ENTIRE background must be SOLID FLAT MAGENTA (#FF00FF) filling the whole frame — "
             "no scenery, no ground, no shadow, no card or panel behind the subject.")
    _key = lambda p: p if "magenta" in (p or "").lower() else (p or "") + KEYBG
    if a.get("poses"):
        entity["images"] = {}
        for name, spec in a["poses"].items():
            out = _abs(ctx, f"{entity['id']}_{name}.png")
            if ctx.get("reuse") and os.path.exists(out):
                ctx["log"](f"    reuse {os.path.basename(out)}"); entity["images"][name] = out; continue
            r = C.gen_pose(_key(spec["prompt"]) if cutout else spec["prompt"], out, name, spec.get("want", name),
                           tries=spec.get("tries", 4), cost_sink=ctx.get("cost"), log=ctx["log"])
            if idn:  # re-preflight against the topic's identity if provided (kept in report)
                r["identity_bible"] = idn
            reps[f"{entity['id']}.{name}"] = {k: r.get(k) for k in ("passed", "scores", "reads_as")}
            entity["images"][name] = out
        entity.setdefault("pose0", next(iter(entity["images"]), None))
        entity["image"] = next(iter(entity["images"].values()), None)
    elif a.get("prompt"):
        out = _abs(ctx, f"{entity['id']}.png")
        r = C.gen_with_preflight(_key(a["prompt"]) if cutout else a["prompt"], out, a.get("checklist", []), size=size, cutout=cutout,
                                 tries=a.get("tries", 3), reuse=ctx.get("reuse", True),
                                 cost_sink=ctx.get("cost"), log=ctx["log"])
        reps[entity["id"]] = {"passed": r.get("passed"), "attempts": r.get("attempts")}
        entity["image"] = out
    return entity


def _declared(status, note):
    def _r(entity, ctx):
        raise NotImplementedError(f"provider '{entity.get('provider')}' is {status} ({note}); "
                                  f"entity '{entity['id']}' cannot be resolved this phase.")
    return _r


REGISTRY = {
    "deterministic_2d": {"resolve": _resolve_paths,     "status": "ACTIVE",
                         "note": "pre-made cutout/plate composited by code"},
    "manual_asset":     {"resolve": _resolve_paths,     "status": "ACTIVE",
                         "note": "fixed human-supplied file"},
    "image_generator":  {"resolve": _resolve_generated, "status": "ACTIVE",
                         "note": "gpt-image-2 + VLM preflight"},
    "ambient_i2v":      {"resolve": _declared("DECLARED", "Kling ambient i2v"), "status": "DECLARED",
                         "note": "image->video ambient motion (unused this phase)"},
    "directed_video":   {"resolve": (lambda e, c: _dv().resolve(e, c)), "status": "DEFERRED",
                         "note": "paid directed motion (Phase 3 scaffold in providers/directed_video.py; "
                                 "gates ready, generation disabled — no silent fallback)"},
    "layered_rig":      {"resolve": _declared("DECLARED", "segmented limb rig"), "status": "DECLARED",
                         "note": "squash/stretch rig — not built (deterministic ceiling gap)"},
}


def resolve(entity, ctx):
    prov = entity.get("provider", "deterministic_2d")
    e = REGISTRY.get(prov)
    if not e:
        raise KeyError(f"unknown provider '{prov}' on entity '{entity['id']}'")
    return e["resolve"](entity, ctx)


def status_table():
    return {k: {"status": v["status"], "note": v["note"]} for k, v in REGISTRY.items()}
