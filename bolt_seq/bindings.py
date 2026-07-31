"""State→visual binding resolver (GENERIC). This is what makes state DRIVE rendering rather than only
being validated afterward: for each block it reads the block's start_state/end_state and writes the
corresponding animation tracks onto the entities.

A binding is pure data (so topic configs stay declarative and the train test can compile config-only):
  {"state": <var>, "entity": <id>, "channel": <chan>,
   # numeric: linear remap of the state value into the channel's range
   "remap": [in_lo, in_hi, out_lo, out_hi], "clamp": True, "curve": "linear",
   # OR categorical/bool: look the state value up in a map
   "map": {"fresh": "swim_pose", "failing": "strain_pose"}}

Examples the fixtures use:
  oxygen_reserve  -> meter.fill        (remap 0..1 -> 0..1)
  distance_to_hub -> hub.scale         (remap 1..0 -> 0.15..1.6  → closer = bigger)
  distance_to_hub -> hub.x             (remap 1..0 -> 1.15..0.60  → hub slides in from the right)
  altitude        -> bolt.y            (remap 100..0 -> 0.10..0.85 → falling)
  bolt_condition  -> bolt.pose         (map fresh->swim, failing->strain, collapsed->collapse)
  bubble_present  -> bubble.visible    (map True->1, False->0)"""
from __future__ import annotations
import copy
from . import scene_graph as SG


def _remap(v, in_lo, in_hi, out_lo, out_hi, clamp=True):
    span = (in_hi - in_lo) or 1e-9
    o = out_lo + (out_hi - out_lo) * (v - in_lo) / span
    if clamp:
        lo, hi = min(out_lo, out_hi), max(out_lo, out_hi)
        o = max(lo, min(hi, o))
    return o


def _apply_one(v, b):
    """Map a single state value through one binding's transform."""
    if "map" in b:
        return b["map"].get(v, b["map"].get(str(v)))
    if "remap" in b:
        return round(_remap(v, *b["remap"], clamp=b.get("clamp", True)), 5)
    return v


def resolve_bindings(entities, bindings, start_state, end_state):
    """Return a per-block COPY of `entities` with tracks written from the block's states.
    Authored tracks on the entity are preserved unless a binding targets the same channel."""
    ents = []
    by_id = {}
    for e in entities:
        e2 = copy.copy(e)
        e2["tracks"] = copy.deepcopy(e.get("tracks", {}))
        ents.append(e2)
        by_id[e2["id"]] = e2

    for b in bindings:
        e = by_id.get(b["entity"])
        if e is None:
            continue
        var, ch = b["state"], b["channel"]
        sv = start_state.get(var)
        ev = end_state.get(var, sv)
        if sv is None and ev is None:
            continue
        vs, ve = _apply_one(sv, b), _apply_one(ev, b)
        # categorical/bool channels or map-based → step track; numeric remaps → eased interpolation
        if "map" in b or ch in ("pose", "visible"):
            if ch == "visible":
                vs = 1.0 if vs else 0.0
                ve = 1.0 if ve else 0.0
                e["tracks"]["opacity"] = SG.track([(0.0, vs), (0.5, vs), (0.5, ve), (1.0, ve)])
                e["tracks"]["visible"] = SG.track([(0.0, bool(vs)), (0.5, bool(ve))])
            else:
                e["tracks"][ch] = SG.track([(0.0, vs), (0.999, vs), (1.0, ve)])
        else:
            e["tracks"][ch] = SG.track([(0.0, vs), (1.0, ve)], curve=b.get("curve", "linear"))
    return ents


def bound_channels(bindings):
    """Report which (entity, channel) pairs are state-driven — used by the planning report."""
    return sorted({(b["entity"], b["channel"]) for b in bindings})


def provenance(bindings, start_state, end_state, constraint_by_var=None):
    """Trace every state-driven visual change back to validated state, for one block. Returns records:
      {source_state, constraint, binding, target, state_from, state_to, visual_from, visual_to}.
    `constraint_by_var` maps a state var → its constraint kind (from continuity) so each visible change
    is tied to the invariant that governs its source."""
    constraint_by_var = constraint_by_var or {}
    recs = []
    for b in bindings:
        var, ch = b["state"], b["channel"]
        sv = start_state.get(var)
        ev = end_state.get(var, sv)
        if sv is None and ev is None:
            continue
        vs, ve = _apply_one(sv, b), _apply_one(ve if False else ev, b)
        kind = "categorical_map" if "map" in b else ("visibility" if ch == "visible" else "linear_remap")
        recs.append({"source_state": var, "constraint": constraint_by_var.get(var),
                     "binding": kind, "target": f"{b['entity']}.{ch}",
                     "state_from": sv, "state_to": ev, "visual_from": vs, "visual_to": ve,
                     "remap": b.get("remap"), "map": b.get("map")})
    return recs
