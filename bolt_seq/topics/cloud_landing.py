"""TOPIC (config only): cloud_landing — the FROZEN vertical-motion fixture, re-expressed for the
generic orchestrator. Reuses the frozen poses/plates (provider deterministic_2d, no regeneration) so
running it through the generic build is a near-zero-cost REGRESSION of the whole pipeline on the
original fixture. Cloud-specific facts live ONLY in this data module."""
from __future__ import annotations
import os
from bolt_seq import scene_graph as SG, continuity as K

H = 1920
FIX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "cloud")
POSE = lambda n: os.path.join(FIX, "poses", n + ".png")
PLATE = lambda n: os.path.join(FIX, "assets", n + ".png")

NAR = ["Could Bolt land on a cloud?", "It looks solid enough.", "He hits the top…",
       "…and falls right through.", "Inside, he's soaked…", "…cold, and blind.",
       "But this cloud weighs a million pounds.", "So why can't it hold him?",
       "A cloud is just fog — too thin to hold anything, so he falls right through.",
       "So… could you ever land on a cloud?"]
CAP = ["LAND ON A CLOUD?", "LOOKS SOLID…", "HE HITS THE TOP", "…AND FALLS THROUGH", "SOAKED",
       "COLD • BLIND", "1,000,000 LBS", "SO WHY NOT?", "IT'S JUST FOG", "COULD YOU?"]


def _streaks(op=0.5):
    return {"id": "streaks", "kind": "effect", "provider": "deterministic_2d", "draw": "speed_streaks",
            "z": 40, "base_h": H, "tracks": {"phase": SG.track([(0, 0), (1, 1)]), "opacity": SG.const_track(op),
            "density": SG.const_track(90), "axis": SG.const_track("v"), "seed": SG.const_track(7)}}


def build():
    bolt = {"id": "bolt", "kind": "character", "provider": "deterministic_2d", "z": 50, "base_h": 560,
            "motion_ghost": True, "pose0": "dive",
            "asset": {"poses": {"dive": {"path": POSE("dive_pose")}, "tumble": {"path": POSE("tumble_pose")},
                                "exit": {"path": POSE("exit_loop_pose")}}}}
    env = {"id": "env", "kind": "environment", "provider": "deterministic_2d", "z": 0, "base_h": H,
           "authored": ["scale"],  # deliberate Ken-Burns drift (not state-driven)
           "asset": {"path": PLATE("plate_sky")}, "tracks": {"scale": SG.track([(0, 1.02), (1, 1.10)])}}

    def blk(bid, role, lines, plate, a0, a1, pose, base_h, overlays):
        return {"id": bid, "role": role, "lines": lines,
                "start_state": {"altitude": a0, "inside_cloud": a0 <= 70, "bolt_identity": "bolt_v1"},
                "end_state": {"altitude": a1, "inside_cloud": a1 <= 70, "bolt_identity": "bolt_v1",
                              **({"breakthrough": True} if bid == "A" else {})},
                "entity_overrides": {"env": {"asset": {"path": PLATE(plate)}},
                                     "bolt": {"pose0": pose, "base_h": base_h}},
                "overlays": overlays}

    rupture = {"id": "rupture", "kind": "effect", "provider": "deterministic_2d", "draw": "cloud_rupture",
               "z": 90, "base_h": H, "tracks": {"opacity": SG.track([(0.82, 0), (0.9, 0.9), (1.0, 0)]),
               "intensity": SG.const_track(1.0), "y": SG.const_track(0.55)}}
    fog = lambda inten: {"id": "fog", "kind": "effect", "provider": "deterministic_2d", "draw": "fog_whiteout",
                         "z": 60, "base_h": H, "tracks": {"opacity": SG.const_track(1.0),
                         "intensity": SG.const_track(inten)}}

    return {
        "title": "Could Bolt Land on a Cloud?", "subject": "landing on a cloud", "duration_target_s": 20,
        "formats": ["physical_experiment", "mystery_reversal"], "render": True,
        "narration_lines": NAR, "captions": CAP,
        "state_vars": {"altitude": {"kind": "numeric", "start": 100, "end": 5, "note": "height above ground"},
                       "inside_cloud": {"kind": "bool", "start": False, "end": True},
                       "bolt_identity": {"kind": "categorical", "start": "bolt_v1", "end": "bolt_v1"}},
        "constraints": [
            {"kind": K.MONO_DEC, "var": "altitude"},
            {"kind": K.IMMUTABLE, "var": "bolt_identity"},
            {"kind": K.THRESHOLD, "var": "altitude", "op": "<=", "value": 70, "event": "inside_cloud"},
            {"kind": K.MUST_OCCUR, "event": "breakthrough"},
            {"kind": K.MUST_NOT_OCCUR, "event": "bolt_stands"},
            {"kind": K.MUST_NOT_OCCUR, "event": "upward_move"},
        ],
        "entities": [env, bolt],
        "bindings": [
            {"state": "altitude", "entity": "bolt", "channel": "y", "remap": [100, 0, 0.10, 0.72], "curve": "accel"},
            {"state": "altitude", "entity": "env", "channel": "y", "remap": [100, 0, 0.15, 0.85]},
        ],
        "blocks": [
            blk("A", "hook", [0, 1, 2, 3], "plate_sky", 100, 70, "dive", 560, [_streaks(0.55), rupture]),
            blk("B", "result", [4, 5], "plate_inside", 70, 50, "tumble", 470, [_streaks(0.45), fog(0.5)]),
            blk("C1", "reveal", [6, 7], "plate_scale", 50, 38, "dive", 150, []),
            blk("C2", "mechanism", [8], "plate_droplets", 38, 20, "dive", 210, [fog(0.28)]),
            blk("D", "loop", [9], "plate_exit", 20, 5, "exit", 520, [_streaks(0.5)]),
        ],
        "acceptance": {"hard_invariants": ["altitude monotonic down", "identity immutable", "no upward_move"],
                       "perceptual": {"sticker_slide_appearance": {"max": 3}, "active_hook": {"min": 6}}},
    }
