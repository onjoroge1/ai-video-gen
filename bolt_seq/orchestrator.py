"""Generic orchestrator (GENERIC — the ONE build flow for every topic). No per-topic renderer.

  topic load → format select → plan compile → state validate → structure validate → asset resolve
  → preflight → animatic render → captions → audio → continuity QC → perceptual QC → reporting

render=True  → produces the animatic + all reports (cloud regression, oxygen fixture).
render=False → produces the config-only PLANNING report + animatic spec (train test); no I/O to any
               paid/model API, no ffmpeg. Same code path up to rendering.

The abstraction audit at the end confirms the topic used ONLY registered generic
formats/effects/providers/constraint-kinds — any missing name is flagged as an abstraction failure."""
from __future__ import annotations
import os, sys, json, copy, re, base64, subprocess

PROJ = "/Users/obadiah/Documents/video"
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from bolt_seq import compiler as C, continuity as K, scene_graph as SG, bindings as B
from bolt_seq import formats as F, effects as FX, providers as PV, topics as T, semantics as SEM
from PIL import Image

W, H, FPS = 1080, 1920, 30


# ── timing ────────────────────────────────────────────────────────────────────────────────────────
def _line_windows(nar, vo_path=None):
    """Per-line (start,end) windows + total. Whisper-aligned if a VO exists, else word-count estimate."""
    import explainer_pipeline as ep
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    fw = [[norm(w) for w in ln.split() if norm(w)] for ln in nar]
    if vo_path and os.path.exists(vo_path):
        words = ep.transcribe_words(vo_path); D = C.dur(vo_path)
        okw = len(words) >= sum(len(f) for f in fw) - 4
        cum, ends = 0, []
        for f in fw:
            cum += len(f)
            ends.append(words[min(cum - 1, len(words) - 1)][2] if okw else round(D * cum / sum(len(x) for x in fw), 3))
    else:  # estimate: ~2.8 words/sec + 0.35s breath per line
        ends, t = [], 0.0
        for f in fw:
            t += max(0.8, len(f) / 2.8) + 0.35; ends.append(round(t, 3))
    lb, prev = [], 0.0
    for i, e in enumerate(ends):
        end = e + 0.10 + (0.5 if i == len(ends) - 1 else 0.0)
        lb.append((round(prev, 3), round(end, 3))); prev = end
    return lb, prev


def _block_window(block, lb):
    s = lb[block["lines"][0]][0]; e = lb[block["lines"][-1]][1]
    return s, e, round(e - s, 3)


# ── per-block entity assembly (overrides → bindings → overlays) ────────────────────────────────────
def _apply_overrides(entities, overrides):
    out = []
    for e in entities:
        e2 = copy.deepcopy(e)
        ov = (overrides or {}).get(e2["id"])
        if ov:
            if "asset" in ov and ov["asset"].get("path"):
                e2["image"] = ov["asset"]["path"]            # deterministic path swap (e.g. cloud plate)
            for k in ("pose0", "base_h", "provider", "draw"):
                if k in ov:
                    e2[k] = ov[k]
            if "tracks" in ov:
                e2.setdefault("tracks", {}).update(ov["tracks"])
        out.append(e2)
    return out


def _resolve_globals(topic, ctx):
    """Resolve every global entity's assets once (generation happens here, not per block)."""
    resolved = []
    for e in topic["entities"]:
        resolved.append(PV.resolve(copy.deepcopy(e), ctx))
    return resolved


# ── abstraction audit ──────────────────────────────────────────────────────────────────────────────
def _abstraction_audit(topic):
    """Confirm the topic references ONLY registered generic names. Any miss = an abstraction failure
    (i.e. the core would need topic-specific code)."""
    miss = []
    for f in topic["formats"]:
        if f not in F.REGISTRY:
            miss.append(f"format '{f}' not in generic registry")
    for c in topic.get("constraints", []):
        if c.get("kind") not in K.CONSTRAINT_KINDS:
            miss.append(f"constraint kind '{c.get('kind')}' not in generic vocabulary")
    for e in topic["entities"]:
        if e.get("provider", "deterministic_2d") not in PV.REGISTRY:
            miss.append(f"provider '{e.get('provider')}' not registered")
        if e.get("draw") and e["draw"] not in FX.REGISTRY:
            miss.append(f"effect '{e['draw']}' not registered")
    for blk in topic["blocks"]:
        for ov in blk.get("overlays", []):
            if ov.get("draw") and ov["draw"] not in FX.REGISTRY:
                miss.append(f"overlay effect '{ov['draw']}' not registered")
    return {"topic_specific_core_code_required": bool(miss), "missing_or_unregistered": miss,
            "verdict": "GENERIC (no topic-specific core code)" if not miss else "ABSTRACTION FAILURE"}


# ── reports ──────────────────────────────────────────────────────────────────────────────────────
def _motion_report(topic, blocks_ents):
    """Per-block, per-entity analytic track sample (state DROVE these). For QC + the planning spec."""
    rep = []
    for blk, ents in blocks_ents:
        erep = {}
        for e in ents:
            tracks = e.get("tracks", {})
            if not tracks:
                continue
            erep[e["id"]] = {"channels": sorted(tracks.keys()),
                             "samples": SG.sample_positions(e, n=8)}
        rep.append({"block": blk["id"], "role": blk.get("role"), "entities": erep})
    return rep


def _perceptual_qc(final, subject, cost):
    import explainer_pipeline as ep
    frames = []
    for f in (0.03, 0.2, 0.42, 0.62, 0.82, 0.97):
        fp = final + f".pq_{f}.jpg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{C.dur(final)*f:.2f}", "-i", final,
                        "-frames:v", "1", "-vf", "scale=360:640", fp], check=True); frames.append(fp)
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
               "data": base64.b64encode(open(fp, "rb").read()).decode()}} for fp in frames]
    content.append({"type": "text", "text": (
        f"These 6 frames are in time order from a vertical Short about {subject}. Score 0-10 and return "
        "ONLY JSON: {\"active_hook\":n,\"motion_realism\":n(0=sticker sliding,10=real animation),"
        "\"urgency\":n,\"escalation_between_blocks\":n,\"comprehension\":n,\"climax_stronger_than_hook\":n,"
        "\"sticker_slide_appearance\":n(0=real animation,10=sticker sliding),\"loop_quality\":n,"
        "\"notes\":\"one line\"}")})
    try:
        r = ep._claude().messages.create(model="claude-opus-4-8", max_tokens=400,
            system="You are a strict short-form retention critic. Judge only what the frames show.",
            messages=[{"role": "user", "content": content}])
        cost.append(ep._msg_cost(r.usage)); pq, _ = ep._parse_script_json(r.content[0].text)
        return pq if isinstance(pq, dict) else {"error": "parse"}
    except Exception as e:
        return {"error": str(e)}


def _srt(lb, nar, path):
    def ts(t): h=int(t//3600); m=int(t%3600//60); s=t%60; return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")
    open(path, "w").write("".join(f"{i+1}\n{ts(s)} --> {ts(e)}\n{nar[i]}\n\n" for i, (s, e) in enumerate(lb)))


def _captions(body, lb, caps, out, tmp):
    ins = ["-i", body]; fc = []; prev = "0:v"; ni = 1
    for i, (s, e) in enumerate(lb):
        cp = os.path.join(tmp, f"_cap_{i}.png"); C.caption_png(caps[i], cp); ins += ["-loop", "1", "-i", cp]
        fc.append(f"[{prev}][{ni}:v]overlay=0:0:enable='between(t,{s:.2f},{e:.2f})'[c{i}]"); prev = f"c{i}"; ni += 1
    fc.append(f"[{prev}]format=yuv420p[v]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *ins, "-filter_complex", ";".join(fc),
                    "-map", "[v]", "-t", f"{C.dur(body):.3f}", "-c:v", "libx264", "-preset", "medium",
                    "-crf", "20", "-pix_fmt", "yuv420p", out], check=True)
    return out


# ── re-renderable block assembly (shared by first render AND critic-guided repair) ─────────────────
def _block_ents(topic, globals_resolved, blk):
    merged = _apply_overrides(globals_resolved, blk.get("entity_overrides"))
    ents = B.resolve_bindings(merged, topic["bindings"], blk["start_state"], blk["end_state"])
    return ents + copy.deepcopy(blk.get("overlays", []))


def _render_block(topic, globals_resolved, blk, lb, out_dir):
    ents = _block_ents(topic, globals_resolved, blk)
    _, _, d = _block_window(blk, lb)
    clip = os.path.join(out_dir, f"blk_{blk['id']}.mp4")
    C.render_scene_block(clip, ents, d, W=W, H=H, fps=FPS, tmp_dir=out_dir, draw_fn=FX.draw)
    return clip


def _assemble(topic, topic_name, clips, narr, lb, vo, out_dir):
    body = C.concat(clips, os.path.join(out_dir, "_body.mp4"), out_dir)
    bodyc = _captions(body, lb, topic["captions"], os.path.join(out_dir, "_bodycap.mp4"), out_dir)
    audio_cfg = topic.get("audio", {}); sfx = []
    for s in audio_cfg.get("sfx", []):
        bs, be, _ = _block_window(next(b for b in topic["blocks"] if b["id"] == s["block"]), lb)
        t = {"start": bs, "end": be, "mid": (bs + be) / 2}[s.get("when", "end")]
        sfx.append((max(0.05, t + s.get("offset", 0.0)), s["kind"]))
    audio = C.build_audio(vo, C.dur(bodyc), sfx, os.path.join(out_dir, "_audio.m4a"), out_dir,
                          ambient=audio_cfg.get("ambient", "wind"))
    final = os.path.join(out_dir, f"{topic_name}_animatic.mp4"); C.mux(bodyc, audio, final)
    _srt(lb, narr, os.path.join(out_dir, f"{topic_name}_animatic.srt"))
    return final


# ── main build ──────────────────────────────────────────────────────────────────────────────────
def build(topic_name, out_dir=None, reuse=True, render=None, perceptual=True, log=print, topic_obj=None):
    topic = topic_obj if topic_obj is not None else T.load(topic_name)
    render = topic.get("render", True) if render is None else render
    out_dir = out_dir or os.path.join(PROJ, "renders", "bolt_seq", topic_name)
    os.makedirs(out_dir, exist_ok=True)
    cost = []
    structure = F.select(topic["formats"])

    # plan compilation
    lb, total = _line_windows(topic["narration_lines"], os.path.join(out_dir, "vo.mp3") if render else None)
    plan = {"topic": topic_name, "title": topic["title"], "subject": topic["subject"],
            "formats": topic["formats"], "axis": structure["axis"], "duration_s": round(total, 2),
            "global_invariants": {}, "constraints": topic["constraints"],
            "blocks": topic["blocks"], "state_vars": topic["state_vars"]}

    # state + structure validation (BEFORE any spend)
    cont = K.validate_all(plan)
    struct = F.validate_structure(topic["blocks"], structure)
    registry = _abstraction_audit(topic)

    # asset resolution (skipped in config-only planning) + per-block scene-graph assembly
    ctx = {"dir": out_dir, "cost": cost, "log": log, "reuse": reuse, "asset_reports": {}}
    if render:
        globals_resolved = _resolve_globals(topic, ctx)
    else:
        globals_resolved = topic["entities"]
    blocks_ents = []
    for blk in topic["blocks"]:
        merged = _apply_overrides(globals_resolved, blk.get("entity_overrides"))
        ents = B.resolve_bindings(merged, topic["bindings"], blk["start_state"], blk["end_state"])
        ents = ents + copy.deepcopy(blk.get("overlays", []))
        blocks_ents.append((blk, ents))

    # motion axis inferred from the SCENE GRAPH (not the format default) + semantic audit + provenance
    all_resolved = [e for _, ents in blocks_ents for e in ents]
    axis_info = SG.infer_axis(all_resolved)
    topic_axis = topic.get("axis") or axis_info["overall"]
    plan["axis"] = topic_axis; plan["axis_detail"] = axis_info
    sem = SEM.audit(topic, blocks_ents, axis_info, registry)
    con_by_var = {c.get("var"): c.get("kind") for c in topic["constraints"] if c.get("var")}
    provenance = [{"block": blk["id"], "role": blk.get("role"),
                   "bindings": B.provenance(topic["bindings"], blk["start_state"], blk["end_state"], con_by_var)}
                  for blk, _ in blocks_ents]

    json.dump(plan, open(os.path.join(out_dir, "plan.json"), "w"), indent=2, default=str)
    json.dump(cont, open(os.path.join(out_dir, "continuity_report.json"), "w"), indent=2, default=str)
    json.dump(struct, open(os.path.join(out_dir, "structure_report.json"), "w"), indent=2)
    json.dump(sem, open(os.path.join(out_dir, "abstraction_audit.json"), "w"), indent=2, default=str)
    json.dump(provenance, open(os.path.join(out_dir, "provenance_report.json"), "w"), indent=2, default=str)
    json.dump(K.state_trace(topic["blocks"]), open(os.path.join(out_dir, "state_trace.json"), "w"), indent=2, default=str)
    json.dump(_motion_report(topic, blocks_ents),
              open(os.path.join(out_dir, "motion_report.json"), "w"), indent=2, default=str)
    json.dump({"axis": topic_axis, "axis_detail": axis_info,
               "entities": [{"id": e["id"], "kind": e.get("kind"), "provider": e.get("provider"),
                             "draw": e.get("draw"), "z": e.get("z", 0)} for e in topic["entities"]],
               "bindings": topic["bindings"], "bound_channels": [list(x) for x in B.bound_channels(topic["bindings"])]},
              open(os.path.join(out_dir, "entity_graph.json"), "w"), indent=2, default=str)

    # HARD environment-semantic preflight: the resolved environment plate must match the topic premise
    # (e.g. an oxygen-subscription topic must NOT read underwater/aquatic/portal). Skipped in plan-only.
    env_gate = None
    if render and topic.get("environment"):
        envspec = topic["environment"]
        envent = next((e for e in globals_resolved if e.get("kind") == "environment"), None)
        envimg = (envent or {}).get("image")
        if envimg and os.path.exists(envimg):
            from bolt_seq.providers import directed_video as _DV
            env_gate = _DV.environment_semantic_gate(envimg, envspec["premise"], envspec["forbidden_readings"],
                                                     envspec.get("required_readings"), cost=cost)
        json.dump(env_gate or {"note": "no environment plate resolved"},
                  open(os.path.join(out_dir, "environment_report.json"), "w"), indent=2, default=str)

    # HARD schema assertion: forbidden tokens must be ABSENT from the compiled plan/spec/motion/graph
    # (not merely hidden at render). A topic declares topic['forbidden_spec_tokens'].
    forbidden = [t.lower() for t in topic.get("forbidden_spec_tokens", [])]
    if forbidden:
        blob = json.dumps([plan, _motion_report(topic, blocks_ents),
                           {"entities": topic["entities"], "bindings": topic["bindings"], "blocks": topic["blocks"]}],
                          default=str).lower()
        hits = sorted({t for t in forbidden if t in blob})
        json.dump({"forbidden_tokens": forbidden, "hits": hits, "clean": not hits},
                  open(os.path.join(out_dir, "forbidden_token_report.json"), "w"), indent=2)
        if hits:
            raise RuntimeError(f"[{topic_name}] compiled spec contains FORBIDDEN tokens {hits} — "
                               f"remove them from the topic config (not just at render).")

    gate_ok = cont["ok"] and sem["semantically_valid"] and (env_gate is None or env_gate.get("pass"))
    log(f"[{topic_name}] continuity={cont['ok']} | structure={struct['ok']} | "
        f"registry={registry['verdict']} | semantic={sem['semantically_valid']} | axis={topic_axis} | "
        f"env={(env_gate or {}).get('reading') if env_gate else 'n/a'}({(env_gate or {}).get('pass') if env_gate else '-'}) | "
        f"{len(topic['blocks'])} blocks / {round(total,1)}s")
    if env_gate and not env_gate.get("pass"):
        log(f"  ENVIRONMENT GATE FAILED: reads as '{env_gate.get('reading')}' forbidden={env_gate.get('forbidden_hits')}")
    if not cont["ok"]:
        log(f"  CONTINUITY: violations={cont.get('constraints',{}).get('violations',[])} "
            f"provenance_problems={cont.get('provenance_problems',[])}")
    if not sem["semantically_valid"]:
        log(f"  SEMANTIC HARD FAILURES: {sem['hard_failures']}")
    if sem["soft_warnings"]:
        log(f"  semantic warnings: {sem['soft_warnings']}")

    if not render:  # config-only planning: emit the animatic spec + planning report, stop before I/O
        spec = {"topic": topic_name, "note": "CONFIG-ONLY plan — no assets/render/audio produced",
                "axis": topic_axis, "axis_detail": axis_info, "structure": structure,
                "continuity": cont, "structure_check": struct, "semantic_audit": sem,
                "gate_ok": gate_ok, "blocks": []}
        for (blk, ents), prov in zip(blocks_ents, provenance):
            s, e, d = _block_window(blk, lb)
            spec["blocks"].append({"id": blk["id"], "role": blk.get("role"), "dur_est_s": d,
                "narration": [topic["narration_lines"][i] for i in blk["lines"]],
                "provenance": prov["bindings"],
                "entities": [{"id": en["id"], "provider": en.get("provider"), "draw": en.get("draw"),
                              "axis": SG.entity_axis(en),
                              "tracks": {k: v for k, v in en.get("tracks", {}).items()}} for en in ents]})
        json.dump(spec, open(os.path.join(out_dir, "animatic_spec.json"), "w"), indent=2, default=str)
        return {"topic": topic_name, "render": False, "continuity": cont, "structure": struct,
                "semantic_audit": sem, "gate_ok": gate_ok, "axis": topic_axis,
                "abstraction_audit": registry, "out_dir": out_dir, "cost": round(sum(cost), 4)}

    if not gate_ok:  # a render topic that fails a hard gate MUST NOT render (no vacuous "success")
        open(os.path.join(out_dir, "build_report.md"), "w").write(
            f"# {topic['title']} — BLOCKED before render\n\n"
            f"- continuity ok: {cont['ok']}\n- semantically valid: {sem['semantically_valid']} "
            f"(hard failures: {sem['hard_failures']})\n\nRender refused; fix the gate above.\n")
        log(f"[{topic_name}] RENDER REFUSED — gate failed (continuity {cont['ok']}, semantic {sem['semantically_valid']})")
        return {"topic": topic_name, "render": False, "blocked": True, "continuity": cont,
                "semantic_audit": sem, "out_dir": out_dir}

    # ── render path ─────────────────────────────────────────────────────────────────────────────
    import explainer_pipeline as ep
    from bolt_seq import facts as FACTS, retention as RET

    # FACT GATE (no facts gate → no render). Qualifies unsupported absolutes, then re-validates.
    frep, narr = FACTS.validate_and_resolve(topic["narration_lines"], topic["subject"], cost=cost, log=log)
    FACTS.write_reports(frep, out_dir)
    if frep.get("gate") not in ("PASS",) and not topic.get("facts_exempt"):
        open(os.path.join(out_dir, "build_report.md"), "w").write(
            f"# {topic['title']} — BLOCKED before render (fact gate)\n\n- {frep.get('gate')}\n"
            f"- unresolved: {frep.get('unsupported_or_false')}\n")
        log(f"[{topic_name}] RENDER REFUSED — fact gate {frep.get('gate')}")
        return {"topic": topic_name, "render": False, "blocked": True, "facts": frep, "out_dir": out_dir}

    vo = os.path.join(out_dir, "vo.mp3")
    vo_hash = os.path.join(out_dir, ".vo_hash")
    import hashlib
    h = hashlib.md5(" ".join(narr).encode()).hexdigest()
    if not (os.path.exists(vo) and os.path.exists(vo_hash) and open(vo_hash).read() == h):
        ep.generate_tts(" ".join(narr), vo, voice=topic.get("voice", "onyx")); open(vo_hash, "w").write(h)
    lb, total = _line_windows(narr, vo)

    clips = []
    for blk, _ in blocks_ents:
        clips.append(_render_block(topic, globals_resolved, blk, lb, out_dir))
        log(f"  rendered block {blk['id']} ({blk.get('role')})")
    final = _assemble(topic, topic_name, clips, narr, lb, vo, out_dir)

    # RETENTION GATE + critic-guided per-block repair (repair one block, not the whole video)
    ret = RET.score(final, narr, topic["subject"], topic["blocks"], lb, out_dir, cost=cost, log=log) \
        if perceptual else {"verdict": "PASS", "scores": {}, "diagnoses": []}
    repairs = []
    work_topic = topic
    for attempt in range(2 if ret.get("verdict") == "REPAIRABLE" else 0):
        diag = RET.worst_block(ret)
        if not diag:
            break
        work_topic, note = RET.apply_fix(work_topic, diag.get("block"), diag)
        blk = next((b for b in work_topic["blocks"] if b["id"] == diag.get("block")), None)
        if not blk:
            break
        log(f"  repair attempt {attempt+1} on block {diag.get('block')} [{diag.get('action')}]: {note}")
        newclip = _render_block(work_topic, globals_resolved, blk, lb, out_dir)
        clips = [newclip if os.path.basename(c) == os.path.basename(newclip) else c for c in clips]
        final = _assemble(work_topic, topic_name, clips, narr, lb, vo, out_dir)
        new = RET.score(final, narr, topic["subject"], work_topic["blocks"], lb, out_dir, cost=cost, log=log)
        repairs.append({"attempt": attempt + 1, "block": diag.get("block"), "action": diag.get("action"),
                        "note": note, "mean_before": ret.get("mean"), "mean_after": new.get("mean")})
        if new.get("mean", 0) >= ret.get("mean", 0):
            ret = new
        if ret.get("verdict") != "REPAIRABLE":
            break
    json.dump({"final_verdict": ret.get("verdict"), "mean": ret.get("mean"), "scores": ret.get("scores"),
               "diagnoses": ret.get("diagnoses"), "repairs": repairs},
              open(os.path.join(out_dir, "retention_report.json"), "w"), indent=2, default=str)

    # QC + reports
    gaps = C.silence_gaps(final, 0.3)
    li = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", final, "-af",
                         "loudnorm=print_format=json", "-f", "null", "-"], capture_output=True, text=True).stderr
    mi = re.search(r'"input_i"\s*:\s*"([-0-9.]+)"', li)
    ch = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=channels",
                         "-of", "default=nw=1:nk=1", final], capture_output=True, text=True).stdout.strip()
    json.dump({"duration_s": round(C.dur(final), 2), "integrated_lufs": mi.group(1) if mi else None,
               "channels": ch, "silence_gaps_over_0.3s": len(gaps)},
              open(os.path.join(out_dir, "audio_report.json"), "w"), indent=2)
    json.dump(ctx["asset_reports"], open(os.path.join(out_dir, "asset_report.json"), "w"), indent=2, default=str)

    pq = _perceptual_qc(final, topic["subject"], cost) if perceptual else {"skipped": True}
    json.dump(pq, open(os.path.join(out_dir, "perceptual_quality_report.json"), "w"), indent=2)

    # contact sheet
    try:
        sheet = Image.new("RGB", (360 * 4, 640), (18, 18, 22))
        for col, fr in enumerate([0.05, 0.4, 0.7, 0.95]):
            fp = os.path.join(out_dir, f"_cs_{col}.jpg")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{C.dur(final)*fr:.2f}", "-i", final,
                            "-frames:v", "1", "-vf", "scale=360:640", fp], check=True)
            sheet.paste(Image.open(fp), (col * 360, 0))
        sheet.save(os.path.join(out_dir, "contact_sheet.jpg"), quality=88)
    except Exception as e:
        log(f"contact sheet: {e}")

    delivered = ret.get("verdict") != "FAIL"          # a FAIL is reported as DEGRADED, never "success"
    summary = {"topic": topic_name, "render": True, "final": final, "duration_s": round(C.dur(final), 2),
               "lufs": mi.group(1) if mi else None, "channels": ch, "silence_gaps": len(gaps),
               "continuity_ok": cont["ok"], "structure_ok": struct["ok"],
               "registry_compatible": registry["verdict"], "semantically_valid": sem["semantically_valid"],
               "facts_gate": frep.get("gate"), "retention_verdict": ret.get("verdict"),
               "retention_mean": ret.get("mean"), "repairs": repairs, "status": "DELIVERED" if delivered else "DEGRADED",
               "axis": topic_axis, "perceptual": pq, "cost": round(sum(cost), 4), "out_dir": out_dir}
    open(os.path.join(out_dir, "build_report.md"), "w").write(
        f"# {topic['title']} — generic-orchestrator build\n\n"
        f"- topic **{topic_name}** · formats {topic['formats']} · axis **{topic_axis}** · status **{summary['status']}**\n"
        f"- runtime {summary['duration_s']}s · {ch}ch · {summary['lufs']} LUFS · silence gaps {len(gaps)}\n"
        f"- continuity ok: **{cont['ok']}** · structure ok: **{struct['ok']}** · "
        f"registry: **{registry['verdict']}** · semantically valid: **{sem['semantically_valid']}**\n"
        f"- fact gate: **{frep.get('gate')}** · retention: **{ret.get('verdict')}** (mean {ret.get('mean')}) · "
        f"repairs: {len(repairs)}\n"
        f"- cost (image+VLM, NO paid video): **${summary['cost']:.2f}**\n\n"
        f"## Retention (VLM)\n```json\n{json.dumps(ret.get('scores', {}), indent=2)}\n```\n"
        f"## Perceptual quality (VLM)\n```json\n{json.dumps(pq, indent=2)}\n```\n")
    log(f"[{topic_name}] {summary['status']} {final} | {summary['duration_s']}s | retention {ret.get('verdict')} "
        f"(mean {ret.get('mean')}) | facts {frep.get('gate')} | ${summary['cost']:.2f}")
    return summary


if __name__ == "__main__":
    from dotenv import load_dotenv
    os.chdir(PROJ); load_dotenv(dotenv_path=os.path.join(PROJ, ".env"), override=True)
    name = sys.argv[1] if len(sys.argv) > 1 else "cloud_landing"
    r = build(name)
    print(json.dumps(r if isinstance(r, dict) else {"ok": True}, indent=2, default=str))
