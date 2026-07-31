"""Idea compiler (GENERIC). Accepts a PLAIN-LANGUAGE idea and compiles it into a validated topic config
the generic orchestrator can render — with no topic-specific core Python. Pipeline:

  idea → research questions → fact validation → format selection → retention plan → state graph
  → entity graph → sequence blocks → bindings → asset plan → topic_config

The generator (an LLM) emits a topic JSON against the fixed registries and schema; the orchestrator's
OWN gates (continuity + structure + semantic audit, run in config-only mode) are the validation oracle
in a bounded compile→validate→repair loop. Facts are then validated and unsupported absolutes qualified.
Writes: facts.md, sources.json, creative_plan.json, retention_plan.json, topic_config.json,
state_graph.json, entity_graph.json, asset_plan.json, acceptance_gates.json."""
from __future__ import annotations
import os, json, copy
from bolt_seq import formats as F, effects as FX, providers as PV, continuity as K, compiler as C
from bolt_seq import facts as FACTS

MODEL = "claude-opus-4-8"


def _registries_doc():
    fm = "; ".join(f"{n}(axis={v['axis']}, roles={v['roles']}, required={v['required']})"
                   for n, v in F.REGISTRY.items())
    return (
        f"FORMATS (pick 1-2, compose their role palettes): {fm}\n"
        f"CONSTRAINT KINDS (declarative, the only ones allowed): {sorted(K.CONSTRAINT_KINDS)}\n"
        f"EFFECTS (procedural draws, deterministic_2d provider): {list(FX.REGISTRY)}\n"
        f"PROVIDERS: image_generator (Bolt poses / plates / destination stills), deterministic_2d "
        f"(meters/effects/particles via a `draw`; or a fixed image path), manual_asset. "
        f"directed_video is DEFERRED — do NOT use it.\n"
        f"ENTITY KINDS: character, prop, equipment, destination, meter, environment, particles, camera, effect\n"
        f"CHANNELS bindable: x,y (0..1 frac of frame), scale, rot(deg), opacity, pose(categorical→image), "
        f"visible(bool), and effect PARAMS: fill, intensity, progress, phase, warn.")


_SCHEMA = """Return ONLY a JSON object with EXACTLY this shape (no prose):
{
 "title": str, "subject": str (a concrete scenario w/ conditions), "duration_target_s": 18-24,
 "formats": [format_name,...], "axis": "horizontal|vertical|radial|depth|stationary|mixed",
 "narration_lines": [8-11 short spoken lines], "captions": [same count, <=3 UPPERCASE words each],
 "voice": "onyx",
 "state_vars": { var: {"kind":"numeric|categorical|bool","start":v,"end":v,"note":str}, ... },
 "constraints": [ {"kind": <one of the constraint kinds>, "var": str}  // monotonic/immutable/persistent/ordered/degrade
                  | {"kind":"threshold_trigger","var":str,"op":"<=|>=|<|>","value":num,"event":str}
                  | {"kind":"must_occur"|"must_not_occur","event":str}, ... ],
 "entities": [ { "id":str, "kind":<entity kind>, "provider":"image_generator|deterministic_2d",
                 "z":int, "base_h":int, "authored":[channels animated on purpose, not by state],
                 "draw": <effect name if procedural>,           // meters/effects/particles only
                 "asset": { "cutout":bool, "size":"1024x1536|1536x1024",
                            "prompt":str,                        // single image (plate/destination)
                            "poses": { pose_name: {"want":str,"prompt":str}, ... } }, // character
                 "parent": id (optional), "tracks": { channel: {"kf":[[t,v],...],"curve":"linear|accel|decel"} } }, ...],
 "bindings": [ {"state":var,"entity":id,"channel":chan,"remap":[in0,in1,out0,out1]}   // numeric
               | {"state":var,"entity":id,"channel":"pose|visible","map":{state_val:target}}, ... ],
 "blocks": [ {"id":str,"role":<role from the composed palette>,"lines":[int,...],
              "start_state":{var:val,...},"end_state":{var:val,...},
              "entity_overrides":{id:{...}} (optional), "overlays":[effect-entity dicts] (optional)}, ...],
 "audio": {"ambient":"wind|water|room","sfx":[{"block":id,"when":"start|mid|end","kind":"impact|alarm|mist"}]},
 "acceptance": {"hard_invariants":[str], "perceptual":{axis:{"min|max":n}}}
}"""

_RULES = """HARD RULES (a violation makes the topic invalid):
1. CHAINING: end_state of block N must EXACTLY equal start_state of block N+1 for every shared key.
2. MONOTONIC: numeric values for a monotonic_decrease var must never rise across the whole trace
   (start/end of every block in order); monotonic_increase must never fall. Make the change real.
3. Every state var that CHANGES must be bound to >=1 visual channel (else the mechanic is invisible).
4. Every declared state var must be used by a constraint OR a binding (no dead state).
5. threshold_trigger: set the event flag True in the block where the var first crosses the threshold.
6. Give the character an IMMUTABLE identity var (constant) + a must_not_occur for reversing direction.
7. Roles: every block role must be in the composed format palette; include all required roles.
8. Character is Bolt: use provider image_generator with a `poses` map; poses must read as the intended
   ACTION (dynamic, not waving). Plates/destination use image_generator single prompt. Meters/effects/
   particles use deterministic_2d with a `draw` from the effects registry. Bind each changing state.
9. captions: <=3 UPPERCASE words; same count as narration_lines; blocks cover all line indices in order.
10. Keep numbers/claims defensible and tied to the scenario conditions (a fact gate will check)."""

BOLT = ("Bolt: " + C.POSE_IDENTITY)


def _gen_topic(idea, log, cost, feedback=None):
    import explainer_pipeline as ep
    sys_prompt = ("You are a compiler from a plain-language video idea to a STRICT topic configuration for a "
                  "deterministic high-retention Short engine. " + BOLT + "\n\n" + _registries_doc() + "\n\n"
                  + _SCHEMA + "\n\n" + _RULES)
    user = (f"IDEA: {json.dumps(idea)}\n\nFirst reason briefly (research questions, chosen formats, the state "
            "graph that must monotonically evolve, the entity graph, and the retention beat order). Then output "
            "the JSON topic. Output ONLY the JSON as the final content.")
    if feedback:
        user += ("\n\nYOUR PREVIOUS ATTEMPT FAILED VALIDATION. Fix EXACTLY these problems and re-output the "
                 "full corrected JSON:\n" + feedback)
    r = ep._claude().messages.create(model=MODEL, max_tokens=4500, system=sys_prompt,
                                     messages=[{"role": "user", "content": user}])
    if cost is not None:
        cost.append(ep._msg_cost(r.usage))
    obj, _ = ep._parse_script_json(r.content[0].text)
    if not isinstance(obj, dict):
        raise ValueError("idea_compiler: model did not return a JSON object")
    return _normalize(obj)


def _normalize(t):
    """Coerce the generated JSON into a runtime topic dict (defaults, render flag, caption length)."""
    t.setdefault("render", True)
    t.setdefault("voice", "onyx")
    t.setdefault("bindings", [])
    t.setdefault("audio", {"ambient": "room", "sfx": []})
    nar = t.get("narration_lines", [])
    caps = t.get("captions", [])
    if len(caps) < len(nar):
        caps = caps + [w.upper()[:20] for w in [ln.split(",")[0][:20] for ln in nar[len(caps):]]]
    t["captions"] = [str(c).upper()[:22] for c in caps][:len(nar)]
    for b in t.get("blocks", []):
        b.setdefault("lines", [])
        b.setdefault("start_state", {}); b.setdefault("end_state", {})
    return t


def _feedback(res):
    parts = []
    cont = res.get("continuity", {})
    if cont.get("provenance_problems"):
        parts.append("continuity provenance_problems: " + "; ".join(cont["provenance_problems"]))
    cons = cont.get("constraints", {})
    if cons.get("violations"):
        parts.append("continuity violations: " + "; ".join(cons["violations"][:8]))
    if cons.get("not_evaluated"):
        parts.append("constraints NOT EVALUATED (var/event absent or too few points): "
                     + "; ".join(f"{n['kind']}:{n['target']}" for n in cons["not_evaluated"]))
    if res.get("chaining") or cont.get("chaining"):
        parts.append("chaining breaks: " + "; ".join(cont.get("chaining", [])))
    struct = res.get("structure", {})
    if not struct.get("ok", True):
        parts.append("structure: " + "; ".join(struct.get("errors", [])))
    sem = res.get("semantic_audit", {})
    for c in sem.get("checks", []):
        if c["hard"] and not c["ok"]:
            parts.append(f"semantic FAIL [{c['check']}]: {c['detail']}")
    return "\n".join(f"- {p}" for p in parts) or "- unknown validation failure"


def compile(idea, out_dir, cost=None, log=print, max_repair=3, validate_facts=True):
    """Compile a plain-language idea → validated topic dict + the 9 planning files. Returns
    {topic, gate_ok, attempts, facts, out_dir}."""
    from bolt_seq import orchestrator as O
    os.makedirs(out_dir, exist_ok=True)
    tmp = os.path.join(out_dir, "_validate")
    topic, res, feedback = None, None, None
    for attempt in range(max_repair):
        topic = _gen_topic(idea, log, cost, feedback)
        res = O.build("idea_candidate", topic_obj=copy.deepcopy(topic), render=False, out_dir=tmp,
                      log=lambda *_: None)
        ok = res.get("gate_ok") and res["continuity"]["ok"] and res["structure"]["ok"]
        log(f"[idea_compiler] attempt {attempt+1}: continuity={res['continuity']['ok']} "
            f"structure={res['structure']['ok']} semantic={res['semantic_audit']['semantically_valid']} → gate_ok={ok}")
        if ok:
            break
        feedback = _feedback(res)
    gate_ok = bool(res and res.get("gate_ok") and res["continuity"]["ok"] and res["structure"]["ok"])

    # fact gate on the (best) narration; qualify unsupported absolutes, then re-validate the result
    frep = {"gate": "SKIPPED"}
    if validate_facts:
        frep, narr = FACTS.validate_and_resolve(topic["narration_lines"], topic["subject"], cost=cost, log=log)
        topic["narration_lines"] = narr
        FACTS.write_reports(frep, out_dir)

    _write_plan_files(idea, topic, res, frep, out_dir)
    log(f"[idea_compiler] DONE gate_ok={gate_ok} facts={frep.get('gate')} → {out_dir}")
    return {"topic": topic, "gate_ok": gate_ok, "attempts": attempt + 1, "facts": frep,
            "validation": res, "out_dir": out_dir}


def _write_plan_files(idea, topic, res, frep, out_dir):
    w = lambda name, obj: json.dump(obj, open(os.path.join(out_dir, name), "w"), indent=2, default=str)
    w("topic_config.json", topic)
    w("creative_plan.json", {"idea": idea, "title": topic.get("title"), "subject": topic.get("subject"),
      "formats": topic.get("formats"), "axis": topic.get("axis"),
      "narration_lines": topic.get("narration_lines"), "captions": topic.get("captions")})
    w("retention_plan.json", {"formats": topic.get("formats"),
      "roles": [{"block": b["id"], "role": b.get("role"), "lines": b.get("lines")} for b in topic["blocks"]],
      "acceptance": topic.get("acceptance")})
    w("state_graph.json", {"state_vars": topic.get("state_vars"), "constraints": topic.get("constraints"),
      "trace": K.state_trace(topic["blocks"])})
    w("entity_graph.json", {"entities": [{k: e.get(k) for k in ("id", "kind", "provider", "draw", "z", "parent")}
      for e in topic["entities"]], "bindings": topic.get("bindings")})
    w("asset_plan.json", {"assets": [{"id": e["id"], "provider": e.get("provider"),
      "poses": list((e.get("asset", {}).get("poses") or {}).keys()),
      "prompt": e.get("asset", {}).get("prompt"), "draw": e.get("draw")} for e in topic["entities"]]})
    w("acceptance_gates.json", {"continuity_ok": (res or {}).get("continuity", {}).get("ok"),
      "semantically_valid": (res or {}).get("semantic_audit", {}).get("semantically_valid"),
      "facts_gate": frep.get("gate"), "acceptance": topic.get("acceptance")})
    # sources.json + facts.md already written by FACTS.write_reports
