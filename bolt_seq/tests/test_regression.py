"""Cloud regression fixture (Generalization Validation, step 1). Cloud is frozen as the reference for
vertical motion, immutable identity, monotonic altitude, a breakthrough event, no-standing, and
perceptual sticker detection. This test re-validates the frozen plan AND re-runs the cloud topic
through the CURRENT generic stack (config-only, no spend) so a future refactor that breaks cloud fails
here. Run: python3 -m bolt_seq.tests.test_regression"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from bolt_seq import continuity as K, formats as F, topics as T, orchestrator as O

FIX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "cloud")
_checks = []
def check(name, cond):
    _checks.append((name, bool(cond))); print(("PASS " if cond else "FAIL ") + name)

def run():
    # 1. frozen inputs + reports present
    for f in ["cloud_sequence_plan.json", "creative_plan.json", "cloud_animatic_v1.mp4",
              "cloud_animatic_v2.mp4", "reports/perceptual_quality_report.json",
              "poses/dive_pose.png", "assets/plate_sky.png"]:
        check(f"fixture present: {f}", os.path.exists(os.path.join(FIX, f)))

    # 2. the FROZEN legacy plan still validates (altitude down, no forbidden, chained)
    plan = json.load(open(os.path.join(FIX, "cloud_sequence_plan.json")))
    v = K.validate_all(plan)
    check("frozen cloud plan continuity ok", v["ok"])

    # 3. the frozen perceptual report is the recorded ceiling (sticker_slide detection worked)
    pq = json.load(open(os.path.join(FIX, "reports", "perceptual_quality_report.json")))
    check("frozen perceptual report has sticker_slide_appearance", "sticker_slide_appearance" in pq)
    check("frozen ceiling recorded (sticker>=4 → deterministic ceiling)", pq.get("sticker_slide_appearance", 0) >= 4)

    # 4. the cloud TOPIC still compiles through the current generic stack (config-only, no spend)
    topic = T.load("cloud_landing")
    cont = K.validate_all({"constraints": topic["constraints"], "blocks": topic["blocks"]})
    struct = F.validate_structure(topic["blocks"], F.select(topic["formats"]))
    audit = O._abstraction_audit(topic)
    check("cloud topic continuity ok (declarative)", cont["ok"])
    check("cloud topic structure ok", struct["ok"])
    check("cloud topic stays GENERIC", not audit["topic_specific_core_code_required"])

    # 5. the frozen invariants cloud must keep testing (per the freeze contract)
    kinds = {c["kind"] for c in topic["constraints"]}
    check("cloud tests vertical monotonic altitude", K.MONO_DEC in kinds)
    check("cloud tests immutable identity", K.IMMUTABLE in kinds)
    check("cloud tests breakthrough must_occur", any(c["kind"] == K.MUST_OCCUR for c in topic["constraints"]))
    check("cloud tests no upward_move (must_not_occur)", any(c["kind"] == K.MUST_NOT_OCCUR for c in topic["constraints"]))

    # 6. GENERALIZATION: every topic compiles through the current stack with ZERO topic-specific core code
    for name in T.list_topics():
        tp = T.load(name)
        c = K.validate_all({"constraints": tp["constraints"], "state_vars": tp.get("state_vars", {}), "blocks": tp["blocks"]})
        s = F.validate_structure(tp["blocks"], F.select(tp["formats"]))
        a = O._abstraction_audit(tp)
        check(f"topic '{name}' continuity ok (non-vacuous)", c["ok"] and not c.get("provenance_problems"))
        check(f"topic '{name}' structure ok", s["ok"])
        check(f"topic '{name}' is GENERIC (no core code)", not a["topic_specific_core_code_required"])

    # 7. PHASE 2.5 HARDENING
    from bolt_seq import semantics as SEM, providers as PV
    # train axis is horizontal, NOT the format's vertical default
    tr_topic = T.load("train_stopping")
    check("train axis is horizontal (not format default 'vertical')", tr_topic.get("axis") == "horizontal")
    # semantic audit catches a changing state with no visual binding
    bad = {"title": "x", "subject": "x", "formats": ["physical_experiment"], "state_vars": {"foo": {"start": 1, "end": 0}},
           "constraints": [{"kind": K.MONO_DEC, "var": "foo"}],
           "entities": [{"id": "bolt", "kind": "character", "authored": ["y"]}], "bindings": [],
           "blocks": [{"id": "A", "role": "hook", "lines": [0], "start_state": {"foo": 1}, "end_state": {"foo": 0}},
                      {"id": "B", "role": "result", "lines": [1], "start_state": {"foo": 0}, "end_state": {"foo": 0}}]}
    be = [(b, [dict(e, tracks={}) for e in bad["entities"]]) for b in bad["blocks"]]
    sem_bad = SEM.audit(bad, be, {"overall": "stationary", "per_entity": {}}, {"topic_specific_core_code_required": False})
    check("semantic audit flags unvisualised changing state", not sem_bad["semantically_valid"])
    # directed_video refuses to spend and never falls back
    from bolt_seq.providers import directed_video as DV
    try:
        PV.resolve({"id": "h", "provider": "directed_video"}, {"dir": "."}); dv_raises = False
    except Exception:
        dv_raises = True
    check("directed_video provider refuses (no auth, no fallback)", dv_raises)
    check("directed_video ALLOW_PAID is False", DV.ALLOW_PAID is False)
    try:
        DV.generate({"budget": DV.DEFAULT_BUDGET, "block": "x"}, None, "."); gen_raises = False
    except DV.DirectedVideoFailure:
        gen_raises = True
    check("directed_video.generate raises without authorization", gen_raises)

    # PHASE 3A gate logic (deterministic, no VLM/no spend)
    from bolt_seq import scene_graph as SG2
    check("gate: zero-delta direction → stationary",
          DV._direction({"tracks": {"x": SG2.const_track(0.5)}}, "horizontal") == "stationary")
    check("gate: real delta direction → right",
          DV._direction({"tracks": {"x": SG2.track([(0, 0.2), (1, 0.8)])}}, "horizontal") == "right")
    rev = DV._trajectory([{"i": 0, "present": True, "bbox": [0.2, 0.4, 0.1, 0.2]},
                          {"i": 1, "present": True, "bbox": [0.7, 0.4, 0.1, 0.2]},
                          {"i": 2, "present": True, "bbox": [0.2, 0.4, 0.1, 0.2]}])
    check("gate: trajectory detects reversal", rev["reversals"] >= 1)
    gone = DV._trajectory([{"i": 0, "present": True, "bbox": [0.2, 0.4, 0.1, 0.2]},
                           {"i": 1, "present": False, "bbox": None}])
    check("gate: trajectory counts disappearance", gone["disappearances"] == 1)
    # scoped prohibitions: block-scoped, not every topic must_not_occur
    _topic = {"constraints": [{"kind": K.MUST_NOT_OCCUR, "event": "bolt_reverses"},
                              {"kind": K.MUST_NOT_OCCUR, "event": "some_unrelated_event"}],
              "state_window_prohibitions": []}
    _blk = {"prohibited": ["hub_recedes"], "start_state": {}, "end_state": {}}
    proh = DV.scoped_prohibitions(_topic, _blk, {})
    check("gate: scoped prohibitions include always-on + block", "bolt_reverses" in proh and "hub_recedes" in proh)
    check("gate: scoped prohibitions exclude unrelated topic rules", "some_unrelated_event" not in proh)
    # offline validation must have certified the gate safe (FP=0) before any paid enablement
    import os as _os, json as _json
    _cm = "renders/bolt_seq/_directed_gate_eval/confusion_matrix.json"
    if _os.path.exists(_cm):
        cm = _json.load(open(_cm))
        check("gate: offline confusion matrix has zero false positives", cm["false_positive"] == 0)

    # PHASE 3A.2 — declarative phase predicates (deterministic, no VLM) + anatomy/clean-plate gates exist
    dh = T.load("oxygen_subscription").get("directed_hero")
    check("oxygen has declarative directed_hero contract", bool(dh and dh.get("phases")))
    check("directed_hero carries anatomy invariants + reference",
          bool(dh and dh["character"]["anatomy"]["prohibited"] and dh["character"].get("reference")))
    for fn in ("check_anatomy", "check_clean_plate", "evaluate_phased", "production_readiness", "trace_vlm"):
        check(f"directed_video exposes {fn}", hasattr(DV, fn))
    _spec = {"phase_contract": {"entities": dh["entities"], "phases": dh["phases"],
                                "prohibited_transitions": dh["prohibited_transitions"]}}
    DV.technical_gate = lambda c, t=None, s=None: {"pass": True, "meta": {}, "reasons": []}
    DV._frames = lambda c, n, o: [(0, "x")]
    good = [{"hero_c": (0.3, 0.5), "dest_c": (0.74, 0.46), "dest_s": 0.9, "equip": True, "post": 0},
            {"hero_c": (0.5, 0.5), "dest_c": (0.74, 0.46), "dest_s": 1.0, "equip": True, "post": 1},
            {"hero_c": (0.55, 0.8), "dest_c": (0.74, 0.46), "dest_s": 1.08, "equip": False, "post": 3}]
    check("phase engine: compound push→collapse passes (no false reversal)",
          DV.evaluate_phased("x", _spec, traces=good, anatomy_bad=set())["phase_motion_pass"])
    recede = [{"hero_c": (0.3, 0.5), "dest_c": (0.74, 0.46), "dest_s": 1.0, "equip": True, "post": 0},
              {"hero_c": (0.4, 0.5), "dest_c": (0.74, 0.46), "dest_s": 0.5, "equip": True, "post": 1},
              {"hero_c": (0.45, 0.8), "dest_c": (0.74, 0.46), "dest_s": 0.4, "equip": False, "post": 3}]
    check("phase engine: destination recession fails",
          not DV.evaluate_phased("x", _spec, traces=recede, anatomy_bad=set())["phase_motion_pass"])
    check("phase engine: anatomy mutation fails a phase",
          not DV.evaluate_phased("x", _spec, traces=good, anatomy_bad={0, 1, 2})["phase_motion_pass"])
    # Candidate 1 permanently reclassified as known-bad (corrected gate must reject its anatomy)
    _rc = "renders/bolt_seq/_oxygen_pilot/candidate_1_reclassification.json"
    if _os.path.exists(_rc):
        rc = _json.load(open(_rc))
        check("cand_1 reclassified: identity_pass False + not production_ready",
              rc["identity_pass"] is False and rc["production_ready"] is False)
        check("cand_1 registered as bolt_hover_base_to_boots_mutation",
              rc.get("known_bad_id") == "bolt_hover_base_to_boots_mutation")
    _cm2 = "renders/bolt_seq/_directed_gate_v2/confusion_matrix_v2.json"
    if _os.path.exists(_cm2):
        cm2 = _json.load(open(_cm2))
        check("corrected offline: all five conditions met", cm2["all_conditions_met"])

    # PHASE 3A.3 — atomic-action rule: a paid clip = ONE action + <=1 transition
    check("directed_video exposes validate_atomic_action", hasattr(DV, "validate_atomic_action"))
    aa = DV.validate_atomic_action(dh)
    check("oxygen hero is atomic (single generated action)", aa["ok"] and aa["generated_action"] == "struggling_approach")
    over = DV.validate_atomic_action({"phases": [{"predicates": ["moves_toward(h,d)", "condition_worsens", "collapsed_posture"]}]})
    check("over-scoped generated clip is flagged not-atomic", not over["ok"])
    check("oxygen splits collapse/oxygen-zero to deterministic",
          "propulsion_failure_and_collapse" in aa["deterministic"] and "oxygen_reaches_zero" in aa["deterministic"])
    gen_phases = [p["name"] for p in dh["phases"] if p.get("generated")]
    check("only the approach phase is generated", gen_phases == ["A_push"])

    failed = [n for n, ok in _checks if not ok]
    print(f"\n{len(_checks)-len(failed)}/{len(_checks)} passed")
    if failed: print("FAILED:", failed)
    return not failed

if __name__ == "__main__":
    sys.exit(0 if run() else 1)
