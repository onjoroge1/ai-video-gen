"""Reusable motion-asset registry for directed hero shots. An entry becomes `accepted` (usable by the
compiler) ONLY after every authoritative gate passes — promotion is gated, never manual. Candidate 1 is
recorded as a diagnostic fixture + partial-capability success, deliberately NOT accepted."""
import os, json

REG_DIR = os.path.join(os.path.dirname(__file__), "registry")
REG_PATH = os.path.join(REG_DIR, "motion_registry.json")

# the seven authoritative gates every accepted directed-motion asset must pass (see directed_video)
REQUIRED_GATES = [
    "articulation_quality", "self_propulsion_readability", "macro_trajectory",
    "progressive_effort", "end_state", "trajectory_contract", "velocity_coupling",
]


def _load():
    if os.path.exists(REG_PATH):
        return json.load(open(REG_PATH))
    return {"version": 1, "required_gates": REQUIRED_GATES, "entries": {}}


def _save(reg):
    os.makedirs(REG_DIR, exist_ok=True)
    json.dump(reg, open(REG_PATH, "w"), indent=2, default=str)


def register(entry_id, **fields):
    reg = _load()
    reg["entries"].setdefault(entry_id, {"id": entry_id, "status": "pending_gates",
                                         "clip": None, "gates_passed": {}, "provider": None,
                                         "conditioning": None, "spec_ref": None})
    reg["entries"][entry_id].update(fields)
    _save(reg)
    return reg["entries"][entry_id]


def get(entry_id):
    return _load()["entries"].get(entry_id)


def promote(entry_id, clip, gate_results, provider=None, conditioning=None):
    """Accept an asset ONLY if every required gate passed. gate_results = {gate_name: bool}. Otherwise the
    entry stays pending and the failing gates are recorded."""
    reg = _load()
    e = reg["entries"].setdefault(entry_id, {"id": entry_id})
    passed = {g: bool(gate_results.get(g)) for g in REQUIRED_GATES}
    all_pass = all(passed.values())
    e.update({"status": "accepted" if all_pass else "pending_gates", "clip": clip if all_pass else e.get("clip"),
              "gates_passed": passed, "provider": provider, "conditioning": conditioning,
              "failing_gates": [g for g, ok in passed.items() if not ok]})
    _save(reg)
    if not all_pass:
        raise ValueError(f"{entry_id} NOT accepted — failing gates: {e['failing_gates']}")
    return e


def _seed():
    """Idempotently seed the pending target entry + the Candidate-1 diagnostic fixture."""
    register("bolt.hover_approach_strained", status="pending_gates",
             description="Bolt hover-runs urgently down a corridor toward a wall terminal, effort rising and "
                         "propulsion weakening, ending strained and airborne SHORT of the terminal.",
             required_gates=REQUIRED_GATES, gates_passed={g: None for g in REQUIRED_GATES},
             spec_ref="renders/bolt_seq/oxygen_subscription/atomic_shots/shot_A_motion_spec.json",
             blocking="awaiting a generation that passes all seven gates (first-frame-only i2v did not)")
    register("bolt.shotA.cand1.diagnostic", status="diagnostic_fixture",
             description="Partial-capability success: proves generated Bolt articulation + macro traversal are "
                         "possible; fails self_propulsion/progressive_effort/end_state + trajectory smoothness/overshoot.",
             clip="renders/bolt_seq/oxygen_subscription/atomic_shots/candidates/shotA_cand_1.mp4",
             provider="fal-ai/kling-video/v3/pro/image-to-video (first-frame-only)",
             gates_passed={"articulation_quality": True, "macro_trajectory.makes_progress": True,
                           "macro_trajectory": False, "self_propulsion_readability": False,
                           "progressive_effort": False, "end_state": False},
             not_accepted_reason="does not meet the registry bar; retained as a diagnostic reference only")


if __name__ == "__main__":
    _seed()
    reg = _load()
    for eid, e in reg["entries"].items():
        print(eid, "->", e["status"])
