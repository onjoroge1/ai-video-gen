"""TOPIC (config only): oxygen_subscription — DRY dystopia (V1.1). Breathable oxygen is a paid, metered
subscription in a sealed futuristic corridor; Bolt hover-RUNS toward a wall-mounted mechanical refill
terminal as his reserve (the METER) drains, then collapses just short. HORIZONTAL goal_chase + countdown.
NO underwater/portal/bubble semantics anywhere in the config, spec or motion report (hard-asserted).
Concept payoff: your body can't stockpile oxygen; it's a subscription you renew every breath."""
from __future__ import annotations
import os
from bolt_seq import scene_graph as SG, continuity as K
from bolt_seq.character import BOLT

H = 1920
OXY = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", "renders", "bolt_seq", "oxygen_subscription"))
A_ = lambda n: os.path.join(OXY, n)

# 18–20s retention structure: hook<=2.5s · terminal by 2.5s · resolution<=3.5s · climax strongest
NAR = ["What if every breath required a subscription?",
       "Bolt has one small oxygen reserve — and the refill terminal is far away.",
       "The meter drops as he pushes toward it.",
       "His vision tunnels; his motors begin to fail.",
       "He's almost there —",
       "Zero.",
       "Oxygen isn't stored — every breath renews the subscription."]
CAP = ["BREATHING: A SUBSCRIPTION?", "REFILL: FAR", "O₂ DROPPING", "MOTORS FAILING", "ALMOST —", "ZERO",
       "RENEW EVERY BREATH"]


def build():
    corridor = {"id": "corridor", "kind": "environment", "provider": "deterministic_2d", "z": 0, "base_h": H,
                "asset": {"path": A_("corridor.png")}, "authored": ["x", "scale"],  # x=parallax(bound), scale=Ken-Burns/push
                "tracks": {"scale": SG.const_track(1.05)}}

    bolt = {"id": "bolt", "kind": "character", "provider": "deterministic_2d", "z": 50, "base_h": 560,
            "pose0": "run", "authored": ["y", "rot"],   # y bob + collapse tip (rot) are deliberate authored events
            "asset": {"identity": BOLT["identity"], "poses": {
                "run": {"path": A_("bolt_hover_run_dry.png")}, "strain": {"path": A_("bolt_strain.png")},
                "fail": {"path": A_("bolt_fail.png")}, "collapse": {"path": A_("bolt_collapse.png")}}},
            "tracks": {"y": SG.track([(0, 0.52), (0.5, 0.49), (1, 0.52)])}}   # x is state-driven (progress)

    # wall-mounted mechanical refill terminal: grows via world projection, slight parallax, grounded by a shadow
    refill_terminal = {"id": "refill_terminal", "kind": "destination", "provider": "deterministic_2d", "z": 12,
                       "base_h": 340, "asset": {"path": A_("refill_terminal.png")}, "tracks": {"y": SG.const_track(0.42)}}
    terminal_shadow = {"id": "terminal_shadow", "kind": "effect", "provider": "deterministic_2d", "draw": "soft_shadow",
                       "z": 11, "base_h": 120, "parent": "refill_terminal",
                       "tracks": {"x": SG.const_track(0.5), "y": SG.const_track(0.64), "strength": SG.const_track(0.5)}}

    streaks = {"id": "streaks", "kind": "effect", "provider": "deterministic_2d", "draw": "speed_streaks",
               "z": 20, "base_h": H, "tracks": {"opacity": SG.const_track(0.26),
               "axis": SG.const_track("h"), "density": SG.const_track(40), "seed": SG.const_track(5)}}
    vignette = {"id": "vignette", "kind": "effect", "provider": "deterministic_2d", "draw": "visibility_loss",
                "z": 70, "base_h": H, "tracks": {"opacity": SG.const_track(1.0)}}
    meter = {"id": "meter", "kind": "meter", "provider": "deterministic_2d", "draw": "resource_meter",
             "z": 80, "base_h": H, "tracks": {"warn": SG.const_track(0.25), "amber": SG.const_track(0.5),
             "x": SG.const_track(0.08), "y": SG.const_track(0.07), "w": SG.const_track(0.84), "h": SG.const_track(0.03)}}

    def st(o2, dist, tsz, cond, **extra):
        return {"oxygen_reserve": o2, "distance_to_terminal": dist, "terminal_screen_size": tsz,
                "bolt_condition": cond, "bolt_identity": "bolt_v1", **extra}

    # bands (targets, ~19s): A hook 0-2.5 · B pursuit 2.5-6 · C drain 6-9.5 · D warning 9.5-12.5 ·
    # E climax/collapse 12.5-16 · F resolution 16-19. Conditions chain (end N == start N+1).
    A = {"id": "A", "role": "hook", "lines": [0],
         "start_state": st(1.0, 1.0, 0.16, "fresh"), "end_state": st(0.92, 0.86, 0.22, "fresh")}
    B = {"id": "B", "role": "pursuit", "lines": [1],
         "start_state": st(0.92, 0.86, 0.22, "fresh"), "end_state": st(0.74, 0.62, 0.30, "strained")}
    Cc = {"id": "C", "role": "drain", "lines": [2],
          "start_state": st(0.74, 0.62, 0.30, "strained"), "end_state": st(0.50, 0.42, 0.40, "strained")}
    D = {"id": "D", "role": "threshold_warning", "lines": [3],
         "start_state": st(0.50, 0.42, 0.40, "strained"), "end_state": st(0.26, 0.24, 0.48, "failing")}
    # E = CLIMAX: the strongest transition — oxygen hits zero and Bolt collapses (drop + tip + floor + hold)
    E = {"id": "E", "role": "climax", "lines": [4, 5],
         "start_state": st(0.26, 0.24, 0.48, "failing"),
         "end_state": st(0.0, 0.12, 0.48, "collapsed", collapse=True),
         "entity_overrides": {"bolt": {"base_h": 540, "tracks": {
             "y": SG.track([(0, 0.52), (0.5, 0.72), (1, 0.72)]),          # drop to floor by mid, then hold
             "rot": SG.track([(0, 0), (0.5, 58), (1, 58)])}}},            # tip forward, then hold
         "overlays": [
             {"id": "bolt_floor_shadow", "kind": "effect", "provider": "deterministic_2d", "draw": "soft_shadow",
              "z": 49, "base_h": 130, "tracks": {"x": SG.const_track(0.46), "y": SG.const_track(0.82),
              "opacity": SG.track([(0, 0), (0.55, 0.6), (1, 0.6)]), "w": SG.const_track(360), "strength": SG.const_track(0.6)}},
             {"id": "fail_wash", "kind": "effect", "provider": "deterministic_2d", "draw": "collapse",
              "z": 90, "base_h": H, "tracks": {"opacity": SG.const_track(1.0),
              "intensity": SG.track([(0, 0.0), (0.55, 0.25), (1.0, 0.7)])}},
             {"id": "stall_flash", "kind": "effect", "provider": "deterministic_2d", "draw": "impact",
              "z": 95, "base_h": H, "tracks": {"opacity": SG.track([(0.45, 0), (0.55, 0.7), (0.7, 0)]),
              "intensity": SG.const_track(0.8)}}]}
    # F = RESOLUTION: Bolt already collapsed; hold the failed state + payoff line + subtle camera push
    F = {"id": "F", "role": "resolution", "lines": [6],
         "start_state": st(0.0, 0.12, 0.48, "collapsed"),
         "end_state": st(0.0, 0.10, 0.48, "collapsed"),
         "entity_overrides": {"bolt": {"base_h": 540, "tracks": {"y": SG.const_track(0.72),
             "rot": SG.const_track(58)}}, "corridor": {"tracks": {"scale": SG.track([(0, 1.05), (1, 1.10)])}}},
         "overlays": [{"id": "fail_hold", "kind": "effect", "provider": "deterministic_2d", "draw": "collapse",
                       "z": 90, "base_h": H, "tracks": {"opacity": SG.const_track(1.0), "intensity": SG.const_track(0.7)}}]}

    return {
        "title": "Why You Can't Store Oxygen", "subject": "a robot racing to refill oxygen before it runs out",
        "duration_target_s": 19, "formats": ["goal_chase", "countdown"], "render": True, "voice": "onyx",
        "narration_lines": NAR, "captions": CAP,
        "environment": {"premise": "a DRY dystopian sealed district where breathable oxygen is a paid, "
                        "metered subscription (oxygen pipes, vents, refill terminals, red expiration warnings)",
                        "forbidden_readings": ["underwater", "aquatic", "submerged", "ocean", "scuba",
                                               "swimming pool", "portal", "teleporter"],
                        "required_readings": ["dry indoor corridor/habitat", "oxygen infrastructure"]},
        # HARD schema assertion: these must be ABSENT from the compiled plan/spec/motion report
        "forbidden_spec_tokens": ["bubble", "bubbles", "rising_bubbles", "air_bubble", "portal", "beacon",
                                  "underwater", "aquatic", "submerged", "scuba"],
        "state_vars": {
            "oxygen_reserve": {"kind": "numeric", "start": 1.0, "end": 0.0, "note": "carried air (subscription)"},
            "distance_to_terminal": {"kind": "numeric", "start": 1.0, "end": 0.05, "note": "to the refill terminal"},
            "terminal_screen_size": {"kind": "numeric", "start": 0.16, "end": 0.48, "note": "apparent size (world projection)"},
            "bolt_condition": {"kind": "categorical", "start": "fresh", "end": "collapsed"},
            "bolt_identity": {"kind": "categorical", "start": "bolt_v1", "end": "bolt_v1"}},
        "constraints": [
            {"kind": K.MONO_DEC, "var": "oxygen_reserve"},
            {"kind": K.MONO_DEC, "var": "distance_to_terminal"},
            {"kind": K.MONO_INC, "var": "terminal_screen_size"},
            {"kind": K.DEGRADE, "var": "bolt_condition", "order": ["fresh", "strained", "failing", "collapsed"]},
            {"kind": K.IMMUTABLE, "var": "bolt_identity"},
            {"kind": K.THRESHOLD, "var": "distance_to_terminal", "op": "<=", "value": 0.15, "event": "collapse"},
            {"kind": K.MUST_OCCUR, "event": "collapse"},
            {"kind": K.MUST_NOT_OCCUR, "event": "bolt_reverses"}],
        "entities": [corridor, streaks, terminal_shadow, refill_terminal, bolt, vignette, meter],
        "bindings": [
            {"state": "distance_to_terminal", "entity": "corridor", "channel": "x", "remap": [1.0, 0.05, 0.0, 0.9]},
            {"state": "distance_to_terminal", "entity": "streaks", "channel": "phase", "remap": [1.0, 0.05, 0.0, 1.0]},
            {"state": "distance_to_terminal", "entity": "bolt", "channel": "x", "remap": [1.0, 0.05, 0.22, 0.48]},
            {"state": "terminal_screen_size", "entity": "refill_terminal", "channel": "scale", "remap": [0.16, 0.48, 0.55, 1.65]},
            {"state": "distance_to_terminal", "entity": "refill_terminal", "channel": "x", "remap": [1.0, 0.05, 0.82, 0.66]},
            {"state": "bolt_condition", "entity": "bolt", "channel": "pose",
             "map": {"fresh": "run", "strained": "strain", "failing": "fail", "collapsed": "collapse"}},
            {"state": "oxygen_reserve", "entity": "vignette", "channel": "intensity", "remap": [1.0, 0.0, 0.0, 0.85]},
            {"state": "oxygen_reserve", "entity": "meter", "channel": "fill", "remap": [0.0, 1.0, 0.0, 1.0]}],
        "blocks": [A, B, Cc, D, E, F],
        "audio": {"ambient": "room", "sfx": [{"block": "D", "when": "start", "kind": "alarm"},
                  {"block": "E", "when": "start", "kind": "alarm"}, {"block": "F", "when": "mid", "kind": "impact"}]},
        "acceptance": {"hard_invariants": ["oxygen_reserve monotonic down", "distance_to_terminal monotonic down",
                       "terminal_screen_size monotonic up", "Bolt progresses toward terminal (x up)",
                       "collapse within distance<=0.15", "no bolt_reverses",
                       "environment reads DRY oxygen-district (not underwater/portal)",
                       "no forbidden aquatic/portal tokens in compiled spec"],
                       "perceptual": {"sticker_slide_appearance": {"max": 4}, "active_hook": {"min": 6},
                                      "comprehension": {"min": 6}}},
        "directed_hero": {
            "block": "final_sprint_and_collapse", "character": BOLT,
            "generated_scope": {"action": "struggling_approach", "transitions": 0,
                "deterministic": ["oxygen_reaches_zero", "propulsion_failure_and_collapse", "exit_boundary"]},
            "entities": {"hero": "the small white-and-mint robot Bolt (single rounded hover-base)",
                         "destination": "a wall-mounted mechanical oxygen refill terminal with a green O2 icon"},
            "phases": [
                {"name": "A_push", "t": [0.0, 1.0], "generated": True,
                 "predicates": ["moves_toward(hero,destination)", "anatomy_immutable",
                                "not destination_recedes", "not hero_flies_through_destination"]},
                {"name": "B_loss", "t": [0.40, 0.65], "generated": False,
                 "predicates": ["condition_worsens", "does_not_recover"]},
                {"name": "C_collapse", "t": [0.65, 1.0], "generated": False,
                 "predicates": ["collapsed_posture", "remains_near(hero,destination)", "anatomy_immutable"]}],
            "prohibited_transitions": ["destination_recedes", "hero_flies_through_destination",
                                       "instant_healthy_to_collapsed"],
            "completion": ["collapsed_posture", "remains_near(hero,destination)"],
            "prompt": (
                "A single continuous 5-second shot in a DRY dystopian sealed corridor (oxygen pipes, vents, "
                "red expiration warnings — NOT underwater). The small white-and-mint robot Bolt hover-runs "
                "toward a wall-mounted mechanical oxygen refill terminal, one hand reaching. His hover-thrust "
                "is already labored; coordination deteriorates and his push shortens as he strains toward the "
                "terminal. His oxygen runs out and he buckles and collapses, dropping to the floor just SHORT "
                "of the terminal. Keep Bolt IDENTICAL — one rounded hover-base (NO legs/feet/boots), mint "
                "accents, glossy visor with two cyan eyes, one antenna, two rounded arms. Normal gravity, dry "
                "floor, atmospheric haze (no water, no bubbles). No text or UI."),
            "prompt_prohibit": ["underwater or aquatic look", "water, bubbles or wet floor",
                                "a glowing ring portal or teleporter", "flying through the terminal",
                                "new legs or feet", "on-screen text/meter/HUD/UI", "terminal recession",
                                "instant healthy-to-collapsed jump"],
            "shot_b_atomic_collapse": {
                "character": BOLT,
                "generated_scope": {"action": "atomic_collapse", "transitions": 0,
                    "deterministic": ["O2:0% caption", "sound", "terminal indicator pulse", "final camera push"]},
                "duration_s": [1.2, 1.8], "model": "kling-v3-pro",
                "entities": {"hero": "the small white-and-mint robot Bolt (single rounded hover-base)",
                             "destination": "a wall-mounted mechanical oxygen refill terminal in the background"},
                "starting_state": {"bolt": "one anatomy-clean Bolt hovering WEAKLY just above a dry floor, "
                                   "hover-base intact, thruster nearly extinguished", "terminal": "on the wall, out of reach",
                                   "ui": "none"},
                "action": ["thruster off", "Bolt drops vertically", "body tips forward",
                           "Bolt impacts the dry floor", "small natural slide", "remains collapsed"],
                "end_state": {"bolt": "prone or deeply slumped, no recovery",
                              "terminal": "visibly beyond him", "identity": "hover-base + identity intact"},
                "prohibit": ["legs", "feet", "boots", "separate lower limbs", "walking", "crawling",
                             "flying toward or through the terminal", "relaunch", "somersaults", "terminal contact",
                             "underwater/water/bubbles", "generated text/meter/HUD/captions",
                             "scene or camera reset", "getting back up"],
                "phases": [
                    {"name": "hover_fail", "t": [0.0, 0.25], "generated": True,
                     "predicates": ["anatomy_immutable", "not flies_toward_destination"]},
                    {"name": "drop", "t": [0.25, 0.7], "generated": True,
                     "predicates": ["condition_worsens", "anatomy_immutable"]},
                    {"name": "impact_prone", "t": [0.7, 1.0], "generated": True,
                     "predicates": ["collapsed_posture", "does_not_recover", "anatomy_immutable"]}],
                "acceptance": ["technical", "anatomy", "clean_plate", "atomic_collapse_motion",
                               "terminal_proximity", "no_recovery", "start_boundary", "exit_boundary",
                               "manual_visual_review"],
            },
        },
    }
