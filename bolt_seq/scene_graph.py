"""Generic multi-entity scene graph (GENERIC — no topic assumptions). A scene is a list of entities;
each entity has per-block animation TRACKS on a fixed set of channels. Tracks are evaluated
analytically at any time-fraction, so the same graph drives deterministic rendering *and* motion QC.

Entities carry: kind (character|prop|equipment|destination|meter|environment|particles|camera|effect),
provider (how the pixels are made — see providers/), z (draw order), a base image OR a procedural
`draw` (an effect name), a `pose` image set, an optional `parent` for attachment, and tracks.

Channels (all optional; sensible defaults):
  x, y        center position as a fraction of (W, H)      [default 0.5, 0.5]
  scale       multiplier on the entity's base size          [default 1.0]
  rot         rotation in degrees                           [default 0]
  opacity     0..1                                          [default 1]
  pose        categorical → selects an image from `images`  [default entity['pose0']]
  visible     bool                                          [default True]
  plus arbitrary PARAM channels (e.g. `fill` for a meter) read by procedural draws.

Position is resolved with parent attachment: a child's (x, y) are offsets added to the parent's
resolved center. No I/O here — rendering lives in compiler.render_scene_block."""
from __future__ import annotations

# ── easing curves (segment parameter u in [0,1] → eased u) ────────────────────────────────────────
def _accel(u):  return u * u
def _decel(u):  return 2 * u - u * u
def _smooth(u): return u * u * (3 - 2 * u)
EASE = {"linear": lambda u: u, "accel": _accel, "decel": _decel, "smooth": _smooth}

TRANSFORM_CHANNELS = ("x", "y", "scale", "rot", "opacity")
DEFAULTS = {"x": 0.5, "y": 0.5, "scale": 1.0, "rot": 0.0, "opacity": 1.0, "visible": True}


def track(kf, curve="linear"):
    """Build a track. kf = [(t_frac, value), ...] with t_frac ascending in [0,1]."""
    return {"kf": list(kf), "curve": curve}


def const_track(value):
    return {"kf": [(0.0, value)], "curve": "linear"}


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def eval_track(tk, t):
    """Evaluate a track at time-fraction t in [0,1]. Numeric → eased interpolation; categorical/bool
    → step (value of the last keyframe whose time <= t)."""
    kf = tk["kf"]
    if not kf:
        return None
    if len(kf) == 1 or t <= kf[0][0]:
        return kf[0][1]
    if t >= kf[-1][0]:
        return kf[-1][1]
    for (t0, v0), (t1, v1) in zip(kf, kf[1:]):
        if t0 <= t <= t1:
            if _is_num(v0) and _is_num(v1):
                span = (t1 - t0) or 1e-9
                u = EASE.get(tk.get("curve", "linear"), EASE["linear"])((t - t0) / span)
                return v0 + (v1 - v0) * u
            return v0 if t < t1 else v1
    return kf[-1][1]


def chan(entity, name, t, default=None):
    """Read a channel value at time t, falling back to entity default then DEFAULTS."""
    tk = entity.get("tracks", {}).get(name)
    if tk is not None:
        return eval_track(tk, t)
    if name in entity:                       # a static value set directly on the entity
        return entity[name]
    return default if default is not None else DEFAULTS.get(name)


def image_for(entity, t):
    """Resolve which image path an entity shows at time t (via its `pose` channel + `images` map)."""
    images = entity.get("images")
    if not images:
        return entity.get("image")
    pose = chan(entity, "pose", t, entity.get("pose0") or next(iter(images)))
    return images.get(pose, entity.get("image") or next(iter(images.values())))


def by_z(entities):
    return sorted(entities, key=lambda e: e.get("z", 0))


def resolve_frame(entities, t, W, H):
    """Resolve every entity to an absolute render spec at time-fraction t. Handles parent attachment
    (child center = parent center + child offset). Returns z-ordered list of dicts:
      {id, kind, provider, draw, image, params, cx, cy, scale, rot, opacity, visible, base_h}"""
    idx = {e["id"]: e for e in entities}
    cache: dict[str, tuple[float, float]] = {}

    def center(e):
        if e["id"] in cache:
            return cache[e["id"]]
        ex, ey = chan(e, "x", t), chan(e, "y", t)
        if e.get("parent") and e["parent"] in idx:
            px, py = center(idx[e["parent"]])
            cx, cy = px + ex - 0.5, py + ey - 0.5   # child x/y are offsets around 0.5 = "on the parent"
        else:
            cx, cy = ex, ey
        cache[e["id"]] = (cx, cy)
        return cx, cy

    out = []
    for e in by_z(entities):
        cx, cy = center(e)
        params = {k: eval_track(v, t) for k, v in e.get("tracks", {}).items()
                  if k not in TRANSFORM_CHANNELS and k not in ("pose", "visible")}
        params = {k: v for k, v in params.items() if v is not None}   # None = unset → effect default applies
        out.append({
            "id": e["id"], "kind": e.get("kind"), "provider": e.get("provider"),
            "draw": e.get("draw"), "image": image_for(e, t), "params": params,
            "cx": cx * W, "cy": cy * H, "scale": chan(e, "scale", t),
            "rot": chan(e, "rot", t), "opacity": chan(e, "opacity", t),
            "visible": bool(chan(e, "visible", t, True)), "base_h": e.get("base_h", H),
            "motion_ghost": e.get("motion_ghost", False),
        })
    return out


def sample_positions(entity, n=11):
    """Analytic motion sample for QC (position/scale over the block). Returns list of dicts."""
    return [{"t": round(k / n, 3), "x": chan(entity, "x", k / n), "y": chan(entity, "y", k / n),
             "scale": chan(entity, "scale", k / n)} for k in range(n + 1)]


# ── motion-axis inference (from the entity tracks, NOT a format default) ───────────────────────────
def _varies(tk):
    if not tk:
        return False
    nums = [v for _, v in tk["kf"] if _is_num(v)]
    return len({round(v, 5) for v in nums}) > 1


def entity_axis(e):
    """The dominant motion axis of ONE entity, inferred from which transform channel actually moves."""
    t = e.get("tracks", {})
    vx, vy, vs, vr = (_varies(t.get(c)) for c in ("x", "y", "scale", "rot"))
    if vx and vy:
        return "mixed"
    if vx:
        return "horizontal"
    if vy:
        return "vertical"
    if vs:
        return "depth"
    if vr:
        return "radial"
    return "stationary"


def infer_axis(entities):
    """Infer the scene's motion axis from the resolved entity tracks. Returns
    {overall, per_entity}. overall = 'mixed' if both x and y move across entities; else the axis of the
    most-animated channel; else 'stationary'. A multi-entity scene commonly reports per-entity axes."""
    per = {e["id"]: entity_axis(e) for e in entities}
    t = [e.get("tracks", {}) for e in entities]
    nx = sum(_varies(x.get("x")) for x in t); ny = sum(_varies(x.get("y")) for x in t)
    ns = sum(_varies(x.get("scale")) for x in t); nr = sum(_varies(x.get("rot")) for x in t)
    if nx == ny == ns == nr == 0:
        overall = "stationary"
    elif nx and ny:
        overall = "mixed"
    else:
        overall = max([("horizontal", nx), ("vertical", ny), ("depth", ns), ("radial", nr)],
                      key=lambda kv: kv[1])[0]
    return {"overall": overall, "per_entity": per}
