"""TOPIC (config only, render=False): train_stopping — "Why can't a train stop quickly?" This is the
ABSTRACTION TEST. It is a brand-new subject with new physics (momentum, friction, brake heat) that
shares NOTHING with cloud or oxygen, yet it is expressed purely as data: registered formats, the
generic constraint vocabulary, registered effects/providers, and state→visual bindings. If compiling
it required any train-specific Python in the core, the orchestrator's abstraction audit reports a
failure. It does not render — it emits the plan, entity graph, track spec, gates, and animatic spec."""
from __future__ import annotations
from bolt_seq import scene_graph as SG, continuity as K

H = 1920

NAR = ["Why can't a train just slam the brakes and stop?", "The driver throws it into full emergency braking…",
       "…but the speed barely drops at first.", "Steel wheels on steel rails have almost no grip.",
       "The brakes glow red-hot, dumping the energy…", "…yet all that momentum has to go somewhere: distance.",
       "The obstacle is close now.", "Still rolling, brakes maxed out…",
       "…it finally stops — a kilometre later.",
       "A train can't stop short: it can't shed its momentum fast enough."]
CAP = ["SLAM THE BRAKES?", "FULL EMERGENCY", "BARELY SLOWS", "STEEL ON STEEL", "BRAKES RED-HOT",
       "MOMENTUM → DISTANCE", "OBSTACLE AHEAD", "STILL ROLLING", "1 KM LATER", "CAN'T SHED MOMENTUM"]


def build():
    rails = {"id": "rails", "kind": "environment", "provider": "image_generator", "z": 0, "base_h": H,
             "asset": {"cutout": False, "size": "1536x1024",
                       "prompt": "A long straight railway receding to a vanishing point, side-on, motion-ready.",
                       "checklist": ["shows rails receding", "no text"]},
             "tracks": {"scale": SG.const_track(1.05)}}
    train = {"id": "train", "kind": "prop", "provider": "image_generator", "z": 50, "base_h": 520,
             "asset": {"cutout": True, "prompt": "A stylised heavy freight locomotive, side view, moving right."},
             "tracks": {"x": SG.const_track(0.35), "y": SG.const_track(0.52)}}
    # train.rot is state-driven (weight transfer under braking) → the locomotive is not visually inert
    obstacle = {"id": "obstacle", "kind": "destination", "provider": "image_generator", "z": 10, "base_h": 300,
                "asset": {"cutout": True, "prompt": "A red stop signal / barrier on the tracks ahead."},
                "tracks": {"y": SG.const_track(0.5)}}
    heat = {"id": "heat", "kind": "effect", "provider": "deterministic_2d", "draw": "heat_distortion",
            "z": 40, "base_h": H, "tracks": {"opacity": SG.const_track(1.0)}}
    streaks = {"id": "streaks", "kind": "effect", "provider": "deterministic_2d", "draw": "speed_streaks",
               "z": 20, "base_h": H, "tracks": {"opacity": SG.const_track(0.4), "axis": SG.const_track("h"),
               "density": SG.const_track(60), "seed": SG.const_track(9)}}
    beacon = {"id": "beacon", "kind": "effect", "provider": "deterministic_2d", "draw": "destination_growth",
              "z": 8, "base_h": H, "tracks": {"opacity": SG.const_track(0.8),
              "x": SG.const_track(0.74), "y": SG.const_track(0.5)}}
    speedm = {"id": "speed_meter", "kind": "meter", "provider": "deterministic_2d", "draw": "resource_meter",
              "z": 80, "base_h": H, "tracks": {"warn": SG.const_track(0.2), "x": SG.const_track(0.08),
              "y": SG.const_track(0.06), "w": SG.const_track(0.4), "h": SG.const_track(0.03)}}
    distm = {"id": "dist_meter", "kind": "meter", "provider": "deterministic_2d", "draw": "resource_meter",
             "z": 80, "base_h": H, "tracks": {"warn": SG.const_track(1.1), "x": SG.const_track(0.52),
             "y": SG.const_track(0.06), "w": SG.const_track(0.4), "h": SG.const_track(0.03)}}

    def st(spd, dist, temp, sdu, **extra):
        return {"train_speed": spd, "distance_to_obstacle": dist, "brake_temperature": temp,
                "stopping_distance_used": sdu, "train_identity": "loco_v1", **extra}

    blocks = [
        {"id": "A", "role": "hook", "lines": [0], "start_state": st(1.0, 1.0, 0.0, 0.0), "end_state": st(0.95, 0.9, 0.1, 0.08)},
        {"id": "B", "role": "drain", "lines": [1, 2], "start_state": st(0.95, 0.9, 0.1, 0.08), "end_state": st(0.85, 0.72, 0.32, 0.28, emergency_brake=True)},
        {"id": "C", "role": "action", "lines": [3], "start_state": st(0.85, 0.72, 0.32, 0.28, emergency_brake=True), "end_state": st(0.62, 0.55, 0.55, 0.5, emergency_brake=True)},
        {"id": "D", "role": "mechanism", "lines": [4, 5], "start_state": st(0.62, 0.55, 0.55, 0.5, emergency_brake=True), "end_state": st(0.4, 0.35, 0.75, 0.7, emergency_brake=True)},
        {"id": "E", "role": "climax", "lines": [6, 7], "start_state": st(0.4, 0.35, 0.75, 0.7, emergency_brake=True), "end_state": st(0.15, 0.12, 0.92, 0.9, emergency_brake=True)},
        {"id": "F", "role": "result", "lines": [8, 9], "start_state": st(0.15, 0.12, 0.92, 0.9, emergency_brake=True), "end_state": st(0.0, 0.02, 1.0, 1.0, emergency_brake=True, stopped=True)},
    ]

    return {
        "title": "Why a Train Can't Stop Quickly", "subject": "a train braking but taking a kilometre to stop",
        "duration_target_s": 22, "formats": ["physical_experiment", "countdown"], "render": False,
        "axis": "horizontal",
        "narration_lines": NAR, "captions": CAP,
        "state_vars": {
            "train_speed": {"kind": "numeric", "start": 1.0, "end": 0.0, "note": "train speed (fraction of initial)"},
            "distance_to_obstacle": {"kind": "numeric", "start": 1.0, "end": 0.02, "note": "gap ahead closing"},
            "brake_temperature": {"kind": "numeric", "start": 0.0, "end": 1.0, "note": "brake temperature rising"},
            "stopping_distance_used": {"kind": "numeric", "start": 0.0, "end": 1.0, "note": "fraction of stopping distance spent"},
            "train_identity": {"kind": "categorical", "start": "loco_v1", "end": "loco_v1"}},
        "constraints": [
            {"kind": K.MONO_DEC, "var": "train_speed"},
            {"kind": K.MONO_DEC, "var": "distance_to_obstacle"},
            {"kind": K.MONO_INC, "var": "brake_temperature"},
            {"kind": K.MONO_INC, "var": "stopping_distance_used"},
            {"kind": K.IMMUTABLE, "var": "train_identity"},
            {"kind": K.THRESHOLD, "var": "distance_to_obstacle", "op": "<=", "value": 0.1, "event": "stopped"},
            {"kind": K.MUST_OCCUR, "event": "emergency_brake"},
            {"kind": K.MUST_OCCUR, "event": "stopped"},
            {"kind": K.MUST_NOT_OCCUR, "event": "train_reverses"}],
        "entities": [rails, streaks, beacon, obstacle, train, heat, speedm, distm],
        "bindings": [
            {"state": "distance_to_obstacle", "entity": "rails", "channel": "x", "remap": [1.0, 0.02, 0.0, 0.95]},
            {"state": "train_speed", "entity": "streaks", "channel": "phase", "remap": [1.0, 0.0, 0.0, 1.0]},
            {"state": "distance_to_obstacle", "entity": "beacon", "channel": "progress", "remap": [1.0, 0.02, 0.0, 1.0]},
            {"state": "distance_to_obstacle", "entity": "obstacle", "channel": "scale", "remap": [1.0, 0.02, 0.12, 1.4]},
            {"state": "distance_to_obstacle", "entity": "obstacle", "channel": "x", "remap": [1.0, 0.02, 1.18, 0.66]},
            {"state": "brake_temperature", "entity": "heat", "channel": "intensity", "remap": [0.0, 1.0, 0.0, 1.0]},
            {"state": "brake_temperature", "entity": "train", "channel": "rot", "remap": [0.0, 1.0, 0.0, -4.0]},
            {"state": "train_speed", "entity": "speed_meter", "channel": "fill", "remap": [0.0, 1.0, 0.0, 1.0]},
            {"state": "stopping_distance_used", "entity": "dist_meter", "channel": "fill", "remap": [0.0, 1.0, 0.0, 1.0]}],
        "blocks": blocks,
        "audio": {"ambient": "room", "sfx": [{"block": "B", "when": "start", "kind": "alarm"},
                  {"block": "F", "when": "mid", "kind": "impact"}]},
        "acceptance": {"hard_invariants": ["speed monotonic down", "distance monotonic down",
                       "brake_temp monotonic up", "stopping_distance_used monotonic up", "stops within distance<=0.1",
                       "no train_reverses"],
                       "expected_states": ["speed decreases", "distance to obstacle decreases",
                                           "brake temperature increases", "stopping distance used increases"]},
    }
