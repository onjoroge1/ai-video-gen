"""Declarative state engine (GENERIC — no topic assumptions). Validates that a chained per-block
state trace obeys a declared set of constraints. Two APIs coexist:

  • legacy: global_invariants {var: DEC/INC/CONST, forbidden_true:[...]}  (used by cloud fixture + tests)
  • declarative: constraints:[{kind, ...}]  — the full 9-kind vocabulary the generalization requires.

State drives rendering elsewhere; this module only *validates* the trace. Pure, no I/O.
See BOLT_SEQUENCE_COMPILER.md §3.2/§15."""
from __future__ import annotations

# ── legacy invariant kinds (kept for back-compat with the cloud fixture + test_state.py) ──────────
DEC = "monotonically_decreasing"
INC = "monotonically_increasing"
CONST = "constant"

# ── declarative constraint vocabulary (topic-agnostic) ────────────────────────────────────────────
MONO_INC = "monotonic_increase"
MONO_DEC = "monotonic_decrease"
PERSISTENT = "persistent"
IMMUTABLE = "immutable"
ORDERED = "ordered_sequence"
DEGRADE = "progressive_degradation"
THRESHOLD = "threshold_trigger"
MUST_OCCUR = "must_occur"
MUST_NOT_OCCUR = "must_not_occur"
CONSTRAINT_KINDS = {MONO_INC, MONO_DEC, PERSISTENT, IMMUTABLE, ORDERED, DEGRADE,
                    THRESHOLD, MUST_OCCUR, MUST_NOT_OCCUR}


# ── legacy validators (unchanged behaviour) ───────────────────────────────────────────────────────
def validate_monotonic(states: list[dict], invariants: dict) -> list[str]:
    """states = ordered per-keyframe dicts. Returns violation strings (empty = OK). Numeric keys only."""
    errs: list[str] = []
    for var, kind in invariants.items():
        seq = [(i, s[var]) for i, s in enumerate(states) if var in s and isinstance(s[var], (int, float)) and not isinstance(s[var], bool)]
        for (ia, a), (ib, b) in zip(seq, seq[1:]):
            if kind == DEC and b > a:
                errs.append(f"{var}: increased {a}->{b} at step {ia}->{ib} (must be {DEC})")
            elif kind == INC and b < a:
                errs.append(f"{var}: decreased {a}->{b} at step {ia}->{ib} (must be {INC})")
            elif kind == CONST and b != a:
                errs.append(f"{var}: changed {a}->{b} at step {ia}->{ib} (must be {CONST})")
    return errs


def validate_forbidden(states: list[dict], forbidden_flags: list[str]) -> list[str]:
    """Any forbidden flag that is truthy in any state is a violation (e.g. bolt_stands=True)."""
    errs: list[str] = []
    for i, s in enumerate(states):
        for f in forbidden_flags:
            if s.get(f):
                errs.append(f"forbidden '{f}' true at step {i}")
    return errs


def validate_chaining(blocks: list[dict]) -> list[str]:
    """end_state of block N must equal start_state of block N+1 (state carries across cuts)."""
    errs: list[str] = []
    for a, b in zip(blocks, blocks[1:]):
        ae, bs = a.get("end_state", {}), b.get("start_state", {})
        for k in set(ae) & set(bs):
            if ae[k] != bs[k]:
                errs.append(f"chain break {a['id']}->{b['id']}: {k} {ae[k]} != {bs[k]}")
    return errs


def state_trace(blocks: list[dict]) -> list[dict]:
    """Flatten blocks into the ordered [start, end, start, end, ...] keyframe trace."""
    trace: list[dict] = []
    for b in blocks:
        trace.append({"_block": b["id"], "_kf": "start", **b.get("start_state", {})})
        trace.append({"_block": b["id"], "_kf": "end", **b.get("end_state", {})})
    return trace


# ── declarative validators (the 9-kind vocabulary) ────────────────────────────────────────────────
def _num_seq(trace, var):
    return [(i, s[var]) for i, s in enumerate(trace)
            if var in s and isinstance(s[var], (int, float)) and not isinstance(s[var], bool)]


def _c_monotonic(trace, var, direction):
    errs = []
    seq = _num_seq(trace, var)
    for (ia, a), (ib, b) in zip(seq, seq[1:]):
        if direction == MONO_INC and b < a - 1e-9:
            errs.append(f"{var}: decreased {a}->{b} at step {ia}->{ib} (must {MONO_INC})")
        elif direction == MONO_DEC and b > a + 1e-9:
            errs.append(f"{var}: increased {a}->{b} at step {ia}->{ib} (must {MONO_DEC})")
    return errs


def _c_persistent(trace, var, until=None):
    """Boolean var must stay truthy until the `until` event first fires; once released it must not
    resurrect. With no `until`, it must be truthy in every state."""
    errs = []
    released = False
    for i, s in enumerate(trace):
        if until and s.get(until):        # the release event fired in/at this state
            released = True
        val = s.get(var)
        if not released and not val:
            errs.append(f"persistent '{var}' false at step {i} before release" + (f" ({until})" if until else ""))
        if released and val:              # resurrection after release is a continuity break
            # allow it to be true in the same state the event fires (attachment breaks *at* collapse)
            if not (until and s.get(until)):
                errs.append(f"persistent '{var}' resurrected at step {i} after release")
    return errs


def _c_immutable(trace, var):
    vals = [(i, s[var]) for i, s in enumerate(trace) if var in s]
    errs = []
    if vals:
        first = vals[0][1]
        for i, v in vals[1:]:
            if v != first:
                errs.append(f"immutable '{var}' changed {first}->{v} at step {i}")
    return errs


def _c_ordered(trace, var, order, strict=False):
    """Categorical var must move forward through `order` (index never decreases; no unknown value).
    strict=True (progressive_degradation) additionally requires it to end worse than it started."""
    errs = []
    idx = {v: k for k, v in enumerate(order)}
    seq = [(i, s[var]) for i, s in enumerate(trace) if var in s]
    last = -1
    for i, v in seq:
        if v not in idx:
            errs.append(f"'{var}' unknown state '{v}' at step {i} (not in order {order})")
            continue
        if idx[v] < last:
            errs.append(f"'{var}' moved backward to '{v}' at step {i} (order {order})")
        last = max(last, idx[v])
    if strict and seq:
        known = [idx[v] for _, v in seq if v in idx]
        if known and known[-1] <= known[0]:
            errs.append(f"'{var}' did not progressively degrade (start '{seq[0][1]}' end '{seq[-1][1]}')")
    return errs


def _cmp(op, a, b):
    return {"<=": a <= b, ">=": a >= b, "<": a < b, ">": a > b, "==": a == b}[op]


def _c_threshold(trace, var, op, value, event):
    """When `var` first satisfies op/value, `event` must fire at that state or later; and `event`
    must not fire before the threshold is ever met (no premature trigger)."""
    errs = []
    first_cross = next((i for i, s in enumerate(trace)
                        if var in s and isinstance(s[var], (int, float)) and _cmp(op, s[var], value)), None)
    fired = [i for i, s in enumerate(trace) if s.get(event)]
    if first_cross is None:
        if fired:
            errs.append(f"threshold '{event}' fired at step {fired[0]} but '{var}{op}{value}' never met")
        return errs
    if not any(i >= first_cross for i in fired):
        errs.append(f"threshold '{event}' never fired though '{var}{op}{value}' met at step {first_cross}")
    if any(i < first_cross for i in fired):
        errs.append(f"threshold '{event}' fired at step {min(fired)} before '{var}{op}{value}' (premature)")
    return errs


def _c_must_occur(trace, event, negate=False):
    fired = any(s.get(event) for s in trace)
    if not negate and not fired:
        return [f"must_occur '{event}' never true"]
    if negate and fired:
        return [f"must_not_occur '{event}' true at step " + str(next(i for i, s in enumerate(trace) if s.get(event)))]
    return []


def _present_count(trace, var):
    return sum(1 for s in trace if var in s)


def _evaluable(trace, c):
    """Was this constraint actually EXERCISED by the trace? Returns (evaluated, points, target).
    A declared constraint that the trace cannot exercise is a vacuous pass → treated as a failure."""
    k = c.get("kind")
    if k in (MONO_INC, MONO_DEC):
        n = len(_num_seq(trace, c["var"])); return n >= 2, n, c.get("var")
    if k == IMMUTABLE:
        n = _present_count(trace, c["var"]); return n >= 2, n, c.get("var")
    if k in (PERSISTENT, ORDERED, DEGRADE):
        n = _present_count(trace, c["var"]); return n >= 2, n, c.get("var")
    if k == THRESHOLD:
        n = len(_num_seq(trace, c["var"])); return n >= 2, n, f"{c.get('var')}→{c.get('event')}"
    if k in (MUST_OCCUR, MUST_NOT_OCCUR):
        return True, len(trace), c.get("event")
    return False, 0, str(c.get("kind"))


def _dispatch(trace, c):
    k = c.get("kind")
    if k in (MONO_INC, MONO_DEC):
        return _c_monotonic(trace, c["var"], k)
    if k == PERSISTENT:
        return _c_persistent(trace, c["var"], c.get("until"))
    if k == IMMUTABLE:
        return _c_immutable(trace, c["var"])
    if k == ORDERED:
        return _c_ordered(trace, c["var"], c["order"], strict=False)
    if k == DEGRADE:
        return _c_ordered(trace, c["var"], c["order"], strict=True)
    if k == THRESHOLD:
        return _c_threshold(trace, c["var"], c["op"], c["value"], c["event"])
    if k == MUST_OCCUR:
        return _c_must_occur(trace, c["event"], negate=False)
    if k == MUST_NOT_OCCUR:
        return _c_must_occur(trace, c["event"], negate=True)
    return [f"unknown constraint kind '{k}'"]


def validate_constraints(trace: list[dict], constraints: list[dict]) -> dict:
    """Dispatch the declarative vocabulary over a flattened state trace, NON-VACUOUSLY: every declared
    constraint must actually be exercised by the trace, and each records an explicit evaluation. A
    constraint the trace can't exercise (var/event never present, <2 points) is a FAILURE, not a pass.
    Returns {ok, checks:[per-constraint ledger], by_kind, violations, not_evaluated}."""
    by_kind: dict[str, list[str]] = {}
    checks, not_eval = [], []
    for c in constraints:
        k = c.get("kind")
        evaluated, points, target = _evaluable(trace, c)
        errs = _dispatch(trace, c) if evaluated else []
        if not evaluated:
            errs = [f"NOT EVALUATED: constraint {k} on '{target}' has {points} usable points in the trace "
                    f"(var/event absent or too few states) — declared but never exercised"]
            not_eval.append({"kind": k, "target": target, "points": points})
        if errs:
            by_kind.setdefault(k, []).extend(errs)
        checks.append({"kind": k, "target": target, "evaluated": evaluated, "points": points,
                       "result": "ok" if not errs else "violation", "violations": errs})
    allv = [v for vs in by_kind.values() for v in vs]
    return {"ok": not allv, "checks": checks, "by_kind": by_kind, "violations": allv,
            "not_evaluated": not_eval}


# ── unified entry point (accepts legacy global_invariants and/or declarative constraints) ──────────
def validate_all(plan: dict) -> dict:
    """Validate a sequence plan NON-VACUOUSLY. A topic that declares stateful behaviour (constraints,
    state_vars, or legacy invariants) must actually EXERCISE it: the trace must be non-empty, declared
    state variables must appear in it, and there must be constraints to evaluate. Any of those missing
    is a failure, not a silent ok. Returns a merged report with a `provenance_problems` list."""
    blocks = plan["blocks"]
    tr = state_trace(blocks)
    out = {"chaining": validate_chaining(blocks)}
    inv = plan.get("global_invariants", {})
    cons = plan.get("constraints", [])
    sv = plan.get("state_vars", {})
    declares_state = bool(cons or sv or inv)

    problems = []
    real_states = [{k: v for k, v in s.items() if not str(k).startswith("_")} for s in tr]
    nonempty = any(real_states)
    if declares_state and not nonempty:
        problems.append("declares stateful behaviour but produced no non-empty state trace")
    present_keys = set().union(*[set(s.keys()) for s in real_states]) if real_states else set()
    for v in sv:
        if v not in present_keys:
            problems.append(f"declared state var '{v}' never appears in any block start/end state")
    if (sv or inv) and not cons and not inv:
        problems.append("stateful topic declares state_vars but no constraints to evaluate them")

    if inv:
        monos = {k: v for k, v in inv.items() if v in (DEC, INC, CONST)}
        out["monotonic"] = validate_monotonic(tr, monos)
        out["forbidden"] = validate_forbidden(tr, inv.get("forbidden_true", []))
    if cons:
        out["constraints"] = validate_constraints(tr, cons)

    out["provenance_problems"] = problems
    legacy_bad = out.get("monotonic") or out.get("forbidden") or out["chaining"]
    decl = out.get("constraints", {})
    decl_bad = (not decl.get("ok", True)) if cons else False
    out["ok"] = not (legacy_bad or decl_bad or problems)
    return out
