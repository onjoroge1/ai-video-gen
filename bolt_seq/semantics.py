"""Semantic abstraction audit (GENERIC). Registry compatibility (names exist) proves a topic *can*
run; it does NOT prove the topic is *meaningful*. This module adds the stronger check the train
animatic exposed as missing: state actually drives visuals, nothing is orphaned, nothing is animated
without provenance, threshold events land in the right block, motion axis matches the scene, and the
climax carries the strongest declared state transition.

`registry_compatible` = the old audit (names registered).  `semantically_valid` = these checks.
Hard checks gate `semantically_valid`; soft checks are advisory warnings."""
from __future__ import annotations
from . import formats as F, bindings as B, scene_graph as SG

_CLIMAX_ROLES = {"climax", "peak", "reveal", "result", "final_payoff"}
_AUTO_CHANNELS = {"effect", "particles", "meter"}   # decorative/procedural entities police nothing spatial
_SPATIAL = ("x", "y", "scale", "rot")


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _changing_state_vars(topic):
    """State vars that actually change somewhere (numeric Δ or categorical switch) — the 'important' ones."""
    changing = set()
    for blk in topic["blocks"]:
        s, e = blk.get("start_state", {}), blk.get("end_state", {})
        for k in set(s) | set(e):
            if s.get(k) != e.get(k):
                changing.add(k)
    return changing


def _block_magnitude(blk, ranges):
    """Normalised sum of |Δ| over numeric state vars in a block (for climax-strength check)."""
    s, e = blk.get("start_state", {}), blk.get("end_state", {})
    tot = 0.0
    for k, rng in ranges.items():
        if _num(s.get(k)) and _num(e.get(k)) and rng:
            tot += abs(e[k] - s[k]) / rng
    return tot


def audit(topic, blocks_ents, axis_info, registry_result):
    """blocks_ents = [(block, resolved_entities), ...] from the orchestrator (tracks already written)."""
    checks = []
    def add(name, ok, detail, hard=True):
        checks.append({"check": name, "ok": bool(ok), "hard": hard, "detail": detail})

    ent_ids = {e["id"] for e in topic["entities"]}
    state_vars = set(topic.get("state_vars", {}))
    constraints = topic.get("constraints", [])
    con_vars = {c["var"] for c in constraints if "var" in c}
    con_events = {c["event"] for c in constraints if "event" in c}
    bind_vars = {b["state"] for b in topic["bindings"]}
    bound_pairs = set(B.bound_channels(topic["bindings"]))
    changing = _changing_state_vars(topic)
    trace = SG_state_keys(topic)

    # 1. required state variables exist (constraint & binding sources are declared and present in states)
    missing_vars = sorted((con_vars | bind_vars) - trace)
    add("required_state_vars_exist", not missing_vars,
        f"vars referenced but absent from block states: {missing_vars}" if missing_vars else "all present")

    # 2. required entities exist (bindings + overrides + overlays target real/added entities)
    overlay_ids = {ov["id"] for blk in topic["blocks"] for ov in blk.get("overlays", [])}
    bad_ent = sorted({b["entity"] for b in topic["bindings"]} - ent_ids)
    bad_ov = sorted({eid for blk in topic["blocks"] for eid in (blk.get("entity_overrides") or {})} - ent_ids)
    add("required_entities_exist", not bad_ent and not bad_ov,
        f"bindings→missing {bad_ent}; overrides→missing {bad_ov}" if (bad_ent or bad_ov) else "all present")

    # 3. each important (changing) state has at least one visual binding
    unbound = sorted(changing - bind_vars - {"bolt_identity", "train_identity"})
    # a changing state is allowed to be unbound only if it is purely an event flag used by a constraint
    unbound = [v for v in unbound if v not in con_events and not _is_event_only(topic, v)]
    add("changing_state_is_visualised", not unbound,
        f"state(s) change but drive no visual: {unbound}" if unbound else "every changing state is bound")

    # 4. no important entity visually orphaned (character/destination must be bound or authored-animated)
    orphans = []
    for e in topic["entities"]:
        if e.get("kind") in ("character", "destination", "prop", "equipment"):
            bound = any(eid == e["id"] for eid, _ in bound_pairs)
            authored = bool(e.get("authored"))
            if not bound and not authored:
                orphans.append(e["id"])
    add("no_orphaned_entities", not orphans,
        f"entities with no state binding or authored motion: {orphans}" if orphans else "none orphaned")

    # 5. no state declared but unused (must be referenced by a constraint OR a binding)
    unused = sorted(state_vars - con_vars - bind_vars - {c.get("event") for c in constraints})
    add("no_unused_state", not unused, f"declared but unused state: {unused}" if unused else "all used")

    # 6. no spatial track animated without provenance (bound OR deliberately authored)
    no_prov = []
    for blk, ents in blocks_ents:
        for e in ents:
            if e.get("kind") in _AUTO_CHANNELS:
                continue
            authored = set(e.get("authored", []))
            for ch in _SPATIAL:
                if SG._varies(e.get("tracks", {}).get(ch)):
                    if (e["id"], ch) not in bound_pairs and ch not in authored:
                        no_prov.append(f"{blk['id']}:{e['id']}.{ch}")
    add("no_track_without_provenance", not no_prov,
        f"animated without state/authored provenance: {sorted(set(no_prov))}" if no_prov else "all spatial motion has provenance")

    # 7. threshold events appear in an appropriate block (event flagged at/after the crossing block)
    thr_issues = []
    for c in [c for c in constraints if c.get("kind") == "threshold_trigger"]:
        cross_blk = _first_cross_block(topic, c["var"], c["op"], c["value"])
        fire_blk = _first_event_block(topic, c["event"])
        if cross_blk is None:
            thr_issues.append(f"{c['event']}: threshold {c['var']}{c['op']}{c['value']} never reached")
        elif fire_blk is None:
            thr_issues.append(f"{c['event']}: never fired in any block")
        elif fire_blk < cross_blk:
            thr_issues.append(f"{c['event']}: fires in block {fire_blk} before crossing block {cross_blk}")
    add("threshold_events_in_right_block", not thr_issues,
        "; ".join(thr_issues) if thr_issues else "threshold events land at/after their crossing")

    # 8. motion axis matches the scene / formats (SOFT)
    fmt_axes = {F.REGISTRY[f]["axis"] for f in topic["formats"]}
    declared = topic.get("axis")
    axis = declared or axis_info["overall"]
    axis_ok = bool(declared) or axis == "mixed" or axis in fmt_axes or axis == "stationary"
    add("axis_matches_scene", axis_ok,
        f"scene axis '{axis_info['overall']}' vs format axes {sorted(fmt_axes)}; topic declares '{declared}'",
        hard=False)

    # 9. climax carries the strongest declared state transition (SOFT)
    ranges = {}
    for k in state_vars:
        vals = [s.get(k) for blk in topic["blocks"] for s in (blk["start_state"], blk["end_state"]) if _num(s.get(k))]
        if vals:
            ranges[k] = (max(vals) - min(vals)) or 1.0
    mags = [(blk["id"], blk.get("role"), _block_magnitude(blk, ranges)) for blk in topic["blocks"]]
    climax_blocks = [m for m in mags if m[1] in _CLIMAX_ROLES]
    if climax_blocks and mags:
        top = max(mags, key=lambda m: m[2])
        best_climax = max(climax_blocks, key=lambda m: m[2])
        strong = best_climax[2] >= 0.8 * top[2] if top[2] else True
        add("climax_is_strongest_transition", strong,
            f"strongest Δ in block {top[0]} ({round(top[2],2)}); climax {best_climax[0]} ({round(best_climax[2],2)})",
            hard=False)
    else:
        add("climax_is_strongest_transition", True, "no climax role declared", hard=False)

    hard_fail = [c for c in checks if c["hard"] and not c["ok"]]
    soft_warn = [c for c in checks if not c["hard"] and not c["ok"]]
    return {"registry_compatible": registry_result,
            "semantically_valid": not hard_fail,
            "hard_failures": [c["check"] for c in hard_fail],
            "soft_warnings": [c["check"] for c in soft_warn],
            "checks": checks, "axis": axis_info}


# ── helpers ────────────────────────────────────────────────────────────────────────────────────────
def SG_state_keys(topic):
    keys = set()
    for blk in topic["blocks"]:
        keys |= set(blk.get("start_state", {})) | set(blk.get("end_state", {}))
    return keys


def _is_event_only(topic, var):
    """True if `var` only ever appears as a boolean event flag (True/False), not a driven quantity."""
    vals = [s.get(var) for blk in topic["blocks"] for s in (blk["start_state"], blk["end_state"]) if var in s]
    return vals and all(isinstance(v, bool) for v in vals)


def _first_cross_block(topic, var, op, value):
    import operator
    ops = {"<=": operator.le, ">=": operator.ge, "<": operator.lt, ">": operator.gt, "==": operator.eq}
    f = ops[op]
    for i, blk in enumerate(topic["blocks"]):
        for s in (blk["start_state"], blk["end_state"]):
            if _num(s.get(var)) and f(s[var], value):
                return i
    return None


def _first_event_block(topic, event):
    for i, blk in enumerate(topic["blocks"]):
        if blk["start_state"].get(event) or blk["end_state"].get(event):
            return i
    return None
