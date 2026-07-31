"""Automated tests for the state engine — legacy invariants + the 9-kind declarative vocabulary.
Run: python3 -m bolt_seq.tests.test_state   (no pytest dependency)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from bolt_seq import continuity as K

_checks = []
def check(name, cond):
    _checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)

def tr(states):  # helper: wrap raw states as a flat trace
    return [dict(_kf=str(i), **s) for i, s in enumerate(states)]

def run():
    # ── legacy invariants (unchanged) ────────────────────────────────────────────
    dec_ok = [{"altitude":100},{"altitude":70},{"altitude":40}]
    dec_bad = [{"altitude":100},{"altitude":120}]
    check("legacy DEC accepts decreasing", K.validate_monotonic(dec_ok, {"altitude":K.DEC}) == [])
    check("legacy DEC rejects increase", len(K.validate_monotonic(dec_bad, {"altitude":K.DEC})) == 1)
    check("legacy INC rejects decrease", len(K.validate_monotonic([{"h":10},{"h":8}], {"h":K.INC})) == 1)
    check("legacy forbidden flag caught", K.validate_forbidden([{"bolt_stands":True}], ["bolt_stands"]) != [])
    check("legacy forbidden flag clean", K.validate_forbidden([{"bolt_stands":False}], ["bolt_stands"]) == [])
    good = [{"id":"A","start_state":{"altitude":100},"end_state":{"altitude":70}},
            {"id":"B","start_state":{"altitude":70},"end_state":{"altitude":50}}]
    bad  = [{"id":"A","start_state":{"altitude":100},"end_state":{"altitude":70}},
            {"id":"B","start_state":{"altitude":65},"end_state":{"altitude":50}}]
    check("chaining accepts matched states", K.validate_chaining(good) == [])
    check("chaining rejects broken chain", len(K.validate_chaining(bad)) == 1)
    plan = {"global_invariants":{"altitude":K.DEC,"forbidden_true":["bolt_stands"]},
            "blocks":[{"id":"A","start_state":{"altitude":100,"bolt_stands":False},"end_state":{"altitude":60,"bolt_stands":False}},
                      {"id":"B","start_state":{"altitude":60,"bolt_stands":False},"end_state":{"altitude":20,"bolt_stands":False}}]}
    check("validate_all ok on clean legacy plan", K.validate_all(plan)["ok"])
    check("validate_all fails on backward altitude", not K.validate_all(
        {"global_invariants":{"altitude":K.DEC},"blocks":[{"id":"A","start_state":{"altitude":50},"end_state":{"altitude":80}}]})["ok"])

    # ── declarative vocabulary (the 9 kinds) ─────────────────────────────────────
    # monotonic_increase / monotonic_decrease
    check("monotonic_decrease accepts", K.validate_constraints(
        tr([{"o2":1.0},{"o2":0.6},{"o2":0.2}]), [{"kind":K.MONO_DEC,"var":"o2"}])["ok"])
    check("monotonic_decrease rejects rise", not K.validate_constraints(
        tr([{"o2":0.6},{"o2":0.7}]), [{"kind":K.MONO_DEC,"var":"o2"}])["ok"])
    check("monotonic_increase accepts hub growth", K.validate_constraints(
        tr([{"hub":0.1},{"hub":0.5},{"hub":1.0}]), [{"kind":K.MONO_INC,"var":"hub"}])["ok"])
    # persistent (with release event)
    check("persistent bubble true throughout ok", K.validate_constraints(
        tr([{"bubble":True},{"bubble":True},{"bubble":True}]), [{"kind":K.PERSISTENT,"var":"bubble"}])["ok"])
    check("persistent bubble dropping early fails", not K.validate_constraints(
        tr([{"bubble":True},{"bubble":False},{"bubble":True}]), [{"kind":K.PERSISTENT,"var":"bubble"}])["ok"])
    check("persistent-until-collapse ok", K.validate_constraints(
        tr([{"bubble":True},{"bubble":True,"collapse":True},{"bubble":False}]),
        [{"kind":K.PERSISTENT,"var":"bubble","until":"collapse"}])["ok"])
    # immutable identity
    check("immutable identity ok", K.validate_constraints(
        tr([{"id":"bolt"},{"id":"bolt"}]), [{"kind":K.IMMUTABLE,"var":"id"}])["ok"])
    check("immutable identity change fails", not K.validate_constraints(
        tr([{"id":"bolt"},{"id":"boltX"}]), [{"kind":K.IMMUTABLE,"var":"id"}])["ok"])
    # ordered_sequence + progressive_degradation
    ORDER = ["fresh","strained","failing","collapsed"]
    check("ordered_sequence forward ok", K.validate_constraints(
        tr([{"cond":"fresh"},{"cond":"strained"},{"cond":"collapsed"}]),
        [{"kind":K.ORDERED,"var":"cond","order":ORDER}])["ok"])
    check("ordered_sequence backward fails", not K.validate_constraints(
        tr([{"cond":"failing"},{"cond":"fresh"}]), [{"kind":K.ORDERED,"var":"cond","order":ORDER}])["ok"])
    check("progressive_degradation must worsen (flat fails)", not K.validate_constraints(
        tr([{"cond":"fresh"},{"cond":"fresh"}]), [{"kind":K.DEGRADE,"var":"cond","order":ORDER}])["ok"])
    check("progressive_degradation worsening ok", K.validate_constraints(
        tr([{"cond":"fresh"},{"cond":"collapsed"}]), [{"kind":K.DEGRADE,"var":"cond","order":ORDER}])["ok"])
    # threshold_trigger
    thr = [{"kind":K.THRESHOLD,"var":"dist","op":"<=","value":0.15,"event":"collapse"}]
    check("threshold fires within band ok", K.validate_constraints(
        tr([{"dist":1.0},{"dist":0.3},{"dist":0.1,"collapse":True}]), thr)["ok"])
    check("threshold never firing fails", not K.validate_constraints(
        tr([{"dist":1.0},{"dist":0.1}]), thr)["ok"])
    check("threshold premature fire fails", not K.validate_constraints(
        tr([{"dist":1.0,"collapse":True},{"dist":0.1}]), thr)["ok"])
    # must_occur / must_not_occur
    check("must_occur satisfied", K.validate_constraints(
        tr([{"x":1},{"collapse":True}]), [{"kind":K.MUST_OCCUR,"event":"collapse"}])["ok"])
    check("must_occur missing fails", not K.validate_constraints(
        tr([{"x":1}]), [{"kind":K.MUST_OCCUR,"event":"collapse"}])["ok"])
    check("must_not_occur clean", K.validate_constraints(
        tr([{"x":1}]), [{"kind":K.MUST_NOT_OCCUR,"event":"bolt_reverses"}])["ok"])
    check("must_not_occur violated", not K.validate_constraints(
        tr([{"bolt_reverses":True}]), [{"kind":K.MUST_NOT_OCCUR,"event":"bolt_reverses"}])["ok"])

    # validate_all with declarative constraints on a mini plan
    dplan = {"constraints":[{"kind":K.MONO_DEC,"var":"o2"},{"kind":K.MUST_OCCUR,"event":"collapse"}],
             "blocks":[{"id":"A","start_state":{"o2":1.0},"end_state":{"o2":0.5}},
                       {"id":"B","start_state":{"o2":0.5},"end_state":{"o2":0.1,"collapse":True}}]}
    check("validate_all ok on clean declarative plan", K.validate_all(dplan)["ok"])

    # ── NON-VACUOUS hardening (Phase 2.5) ────────────────────────────────────────
    # a constraint on a var that never appears must FAIL (not silently pass)
    r = K.validate_constraints(tr([{"o2":1.0},{"o2":0.5}]), [{"kind":K.MONO_DEC,"var":"ghost_var"}])
    check("constraint on absent var is NOT evaluated → fail", (not r["ok"]) and r["not_evaluated"])
    # the checks ledger records every declared constraint with points
    r2 = K.validate_constraints(tr([{"o2":1.0},{"o2":0.6},{"o2":0.2}]), [{"kind":K.MONO_DEC,"var":"o2"}])
    check("checks ledger records evaluation + points", r2["checks"] and r2["checks"][0]["evaluated"] and r2["checks"][0]["points"]==3)
    # validate_all: declared state var absent from blocks → fail
    bad_sv = {"state_vars":{"speed":{"start":1,"end":0}}, "constraints":[{"kind":K.MONO_DEC,"var":"speed"}],
              "blocks":[{"id":"A","start_state":{"velocity":1},"end_state":{"velocity":0}}]}
    check("validate_all fails when declared state var absent from trace", not K.validate_all(bad_sv)["ok"])
    # validate_all: stateful topic with state_vars but no constraints → fail (vacuous)
    novac = {"state_vars":{"speed":{"start":1,"end":0}},
             "blocks":[{"id":"A","start_state":{"speed":1},"end_state":{"speed":0}}]}
    check("validate_all fails when state_vars declared but no constraints", not K.validate_all(novac)["ok"])
    # validate_all: empty state trace on a stateful topic → fail
    empty = {"constraints":[{"kind":K.MONO_DEC,"var":"x"}], "blocks":[{"id":"A","start_state":{},"end_state":{}}]}
    check("validate_all fails on empty state trace", not K.validate_all(empty)["ok"])

    failed = [n for n,ok in _checks if not ok]
    print(f"\n{len(_checks)-len(failed)}/{len(_checks)} passed")
    if failed:
        print("FAILED:", failed)
    return not failed

if __name__ == "__main__":
    sys.exit(0 if run() else 1)
