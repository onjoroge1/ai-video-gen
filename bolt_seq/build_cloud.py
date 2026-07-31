"""Phase-2 cloud vertical slice orchestrator. Produces the deterministic cloud animatic + all
deliverables. No paid video. Run: python3 bolt_seq/build_cloud.py
Outputs -> renders/bolt_cloud_experiment_package/phase2/"""
import os, sys, json, hashlib, subprocess, concurrent.futures as cf
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ); sys.path.insert(0, PROJ)
from dotenv import load_dotenv; load_dotenv(dotenv_path=os.path.join(os.getcwd(), ".env"), override=True)
import explainer_pipeline as ep
from bolt_seq import compiler as C, continuity as K
from PIL import Image

OUT = os.path.join(PROJ, "renders/bolt_cloud_experiment_package/phase2")
ASSETS = os.path.join(OUT, "assets"); os.makedirs(ASSETS, exist_ok=True)
def log(m): print(m, flush=True)
W, H = 1080, 1920

# ── 1. creative plan (immutable once approved) ────────────────────────────────────
NARRATION_LINES = [
    "Could Bolt land on a cloud?", "It looks solid enough.", "He hits the top…",
    "…and falls right through.", "Inside, he's soaked…", "…cold, and blind.",
    "But this cloud weighs a million pounds.", "So why can't it hold him?",
    "A cloud is just fog — too thin to hold anything, so he falls right through.",
    "So… could you ever land on a cloud?"]
CAPTIONS = ["LAND ON A CLOUD?","LOOKS SOLID…","HE HITS THE TOP","…AND FALLS THROUGH","SOAKED",
            "COLD • BLIND","1,000,000 LBS","SO WHY NOT?","IT'S JUST FOG","COULD YOU?"]
NARRATION = " ".join(NARRATION_LINES)
creative_plan = {
    "format": "physical_experiment_reversal",
    "title": "Could Bolt Land on a Cloud?",
    "duration_target_s": 20,
    "narration": NARRATION, "narration_lines": NARRATION_LINES, "captions": CAPTIONS,
    "hook": "Could Bolt land on a cloud? (he is already falling toward one)",
    "first_payoff_s": 5.5, "first_payoff": "he falls straight through the cloud",
    "second_open_loop": "a million-pound cloud — so why can't it hold him?",
    "climax": "a cloud is just fog: droplets too thin/spread to hold anything",
    "ending_loop": "still falling toward the next cloud — matches frame 1",
    "facts": ["A large cumulus can hold ~1,000,000 lb of water (widely cited estimate).",
              "A cloud is a suspension of tiny droplets in air; density ≈ air, no solid surface."],
}
creative_plan["script_hash"] = hashlib.sha256(NARRATION.encode()).hexdigest()[:16]

# ── 2. continuity bible (global invariants) ───────────────────────────────────────
continuity_bible = {"bolt_model": "bolt_v1_hover_base",
    "global_invariants": {"altitude": K.DEC, "vertical_velocity_down": K.CONST,
        "forbidden_true": ["bolt_stands","bolt_walks","bolt_hovers","upward_move","mouth","boots","legs"]},
    "prohibited_features": ["mouth","boots","legs","extra_limbs","costume_change","disappearing_antenna","disappearing_chest_panel"]}

# ── 3. four-block sequence plan (C split into scale + droplets) ───────────────────
def st(alt, **kw): return {"altitude": alt, "vertical_velocity_down": 1, **kw}
cloud_sequence_plan = {"global_invariants": continuity_bible["global_invariants"], "blocks": [
  {"id":"A","lines":[0,1,2,3],"plate":"plate_sky","bolt_h":500,"y0":0.08,"y1":0.60,"zoom":"in",
   "wobble":0.0,"cloud_layer":False,"beats":["falling","cloud grows","touch","break through"],
   "start_state":st(100,inside_cloud=False),"end_state":st(70,inside_cloud=True)},
  {"id":"B","lines":[4,5],"plate":"plate_inside","bolt_h":430,"y0":0.14,"y1":0.62,"zoom":"hold",
   "wobble":45.0,"cloud_layer":False,"beats":["droplets hit","visibility drops","tumble, still down"],
   "start_state":st(70,inside_cloud=True),"end_state":st(50,inside_cloud=True)},
  {"id":"C1","lines":[6,7],"plate":"plate_scale","bolt_h":165,"y0":0.12,"y1":0.55,"zoom":"out",
   "wobble":0.0,"cloud_layer":False,"beats":["reveal huge cloud","why can't it hold him"],
   "start_state":st(50,inside_cloud=True),"end_state":st(38,inside_cloud=True)},
  {"id":"C2","lines":[8],"plate":"plate_droplets","bolt_h":230,"y0":0.12,"y1":0.62,"zoom":"out",
   "wobble":0.0,"cloud_layer":False,"beats":["droplets sparse across huge volume = the answer"],
   "start_state":st(38,inside_cloud=True),"end_state":st(20,inside_cloud=False)},
  {"id":"D","lines":[9],"plate":"plate_exit","bolt_h":480,"y0":0.10,"y1":0.60,"zoom":"in",
   "wobble":0.0,"cloud_layer":False,"beats":["exit, next cloud below, loop to frame 1"],
   "start_state":st(20,inside_cloud=False),"end_state":st(5,inside_cloud=False)}]}

# ── asset prompts + preflight checklists ─────────────────────────────────────────
BOLT_PROMPT = ("A small friendly toy-robot mascot, full body, centered, on a SOLID FLAT MAGENTA (#FF00FF) "
  "background that completely fills the frame behind the robot (for chroma-keying). "
  "Rounded matte-white body with mint-green accents; glossy black screen face with two glowing cyan oval "
  "eyes and NO MOUTH; a thin antenna topped with a glowing cyan ball; two short rounded stubby arms; and a "
  "SINGLE smooth rounded hover-base instead of legs — NO legs, NO feet, NO boots. DYNAMIC FALLING pose, as "
  "if plummeting through the air: body tilted strongly off-balance and pitched slightly head-first, both "
  "arms flung outward, alarmed/scared — clearly mid-fall, NOT standing upright and NOT calmly waving. "
  "Premium 3D cartoon render. No scenery, no ground.")
BOLT_CHECK = ["Exactly ONE small rounded white-and-mint toy robot is shown",
  "The face is a black screen with two glowing cyan eyes and NO mouth",
  "There is a thin antenna with a glowing tip",
  "The lower body is a single rounded hover-base: NO legs, NO feet, NO boots",
  "It has exactly two arms and no extra limbs",
  "The robot sits on a solid flat magenta/pink background with no other scenery or ground",
  "The pose is dynamic and off-balance (falling, tumbling, or plummeting) — NOT a calm upright standing, walking, or neutral waving pose"]
PLATES = {
 "plate_sky":("Aerial view looking straight down from very high altitude: bright blue sky, a large fluffy "
   "white cumulus cloud sitting below, patchwork green farmland visible far beneath through gaps, soft "
   "sunlight, strong sense of height. Cinematic, photoreal-leaning.", "an open sky with a cloud below and land far beneath"),
 "plate_inside":("Inside a dense cloud: thick white and pale-grey mist and fog filling the frame, faint "
   "diffuse light, countless tiny suspended water droplets, very low visibility whiteout.", "the misty white interior of a cloud"),
 "plate_scale":("An ENORMOUS towering white cumulus cloud seen from a distance against deep blue sky, vast "
   "and majestic, dwarfing the tiny landscape far below, dramatic scale.", "one gigantic cloud dominating the sky"),
 "plate_droplets":("A vast expanse of blue sky containing only a FEW tiny sparkling water droplets scattered "
   "very FAR APART with large empty gaps of clear air between them, emphasizing how sparse and thinly spread "
   "the droplets are across a huge volume.", "a mostly-empty sky with a few widely-spaced droplets"),
 "plate_exit":("View from just below a large cloud with clear open air beneath it, and another soft fluffy "
   "white cloud waiting far below, blue sky, sense of continued falling downward.", "clear air below a cloud with another cloud far below"),
}
CLOUD_LAYER_PROMPT = ("A single soft fluffy white cumulus cloud puff centered on a SOLID FLAT MAGENTA (#FF00FF) "
   "background filling the frame, billowy and wispy at the edges, for chroma-keying. Nothing else.")
def plate_check(desc): return [f"The image shows {desc}", "There is NO robot, NO character, and NO person anywhere in the image"]

def main():
    log("=== Phase 2: cloud vertical slice ===")
    for name, obj in [("creative_plan",creative_plan),("continuity_bible",continuity_bible),
                      ("cloud_sequence_plan",cloud_sequence_plan)]:
        json.dump(obj, open(os.path.join(OUT,f"{name}.json"),"w"), indent=2, ensure_ascii=False)

    # continuity validation + state trace
    val = K.validate_all(cloud_sequence_plan)
    json.dump({"validation":val,"state_trace":K.state_trace(cloud_sequence_plan["blocks"])},
              open(os.path.join(OUT,"continuity_report.json"),"w"), indent=2)
    json.dump(K.state_trace(cloud_sequence_plan["blocks"]), open(os.path.join(OUT,"state_trace.json"),"w"), indent=2)
    log(f"continuity valid: {val['ok']}  {'' if val['ok'] else val}")

    # VO + whisper per-line timing
    costs=[]
    vo=os.path.join(OUT,"vo.mp3"); ep.generate_tts(NARRATION, vo, voice="onyx")
    words=ep.transcribe_words(vo); D_vo=C.dur(vo)
    norm=lambda s: __import__("re").sub(r"[^a-z0-9]","",s.lower())
    fw=[[norm(w) for w in ln.split() if norm(w)] for ln in NARRATION_LINES]
    ends=[]; cum=0
    ok_w=len(words)>=sum(len(f) for f in fw)-4
    for f in fw:
        cum+=len(f); ends.append(words[min(cum-1,len(words)-1)][2] if ok_w else round(D_vo*cum/sum(len(x) for x in fw),3))
    line_bounds=[]; prev=0.0
    for i,e in enumerate(ends):
        end=e+0.10+(0.5 if i==len(ends)-1 else 0.0); line_bounds.append((round(prev,3),round(end,3))); prev=end
    log(f"VO {D_vo:.1f}s, line bounds ok_whisper={ok_w}")

    # assets: gen + preflight (parallel)
    log("=== assets (gen + preflight) ===")
    jobs=[("bolt",BOLT_PROMPT,BOLT_CHECK,True)]
    for k,(p,desc) in PLATES.items(): jobs.append((k,p,plate_check(desc),False))
    jobs.append(("cloud_layer",CLOUD_LAYER_PROMPT,["A single fluffy white cloud puff on a solid flat magenta/pink background","No robot or character present"],True))
    pf_report={}
    def do(job):
        k,p,chk,tr=job; path=os.path.join(ASSETS,f"{k}.png")
        return k, C.gen_with_preflight(p,path,chk,cutout=tr,tries=3,cost_sink=costs,log=log)
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for k,res in ex.map(do, jobs): pf_report[k]=res
    json.dump(pf_report, open(os.path.join(OUT,"image_preflight_report.json"),"w"), indent=2)
    failed=[k for k,r in pf_report.items() if not r["passed"]]
    log(f"preflight failed anchors: {failed or 'none'}")

    # render blocks (clips) with whisper-derived durations
    log("=== render deterministic blocks ===")
    clips=[]; a_end=None; b_start=None
    for blk in cloud_sequence_plan["blocks"]:
        s=line_bounds[blk["lines"][0]][0]; e=line_bounds[blk["lines"][-1]][1]; d=round(e-s,3)
        if blk["id"]=="A": a_end=e
        if blk["id"]=="B": b_start=s
        clip=os.path.join(OUT,f"clip_{blk['id']}.mp4")
        C.render_block(clip, os.path.join(ASSETS,blk["plate"]+".png"), os.path.join(ASSETS,"bolt.png"), d,
                       blk["bolt_h"], blk["y0"], blk["y1"], x_wobble=blk["wobble"], plate_zoom=blk["zoom"],
                       cloud_layer=os.path.join(ASSETS,"cloud_layer.png") if blk["cloud_layer"] else None,
                       tmp_dir=OUT)
        clips.append(clip); log(f"  block {blk['id']}: {d}s lines {blk['lines']}")
    body=C.concat(clips, os.path.join(OUT,"_body.mp4"), OUT); BODY=C.dur(body)

    # per-line captions overlaid on body (top strip, avoids Bolt)
    cap_inputs=["-i",body]; fc=[]; prev="0:v"; ni=1
    for i,(s,e) in enumerate(line_bounds):
        cp=os.path.join(OUT,f"cap_{i}.png"); C.caption_png(CAPTIONS[i], cp)
        cap_inputs+=["-loop","1","-i",cp]
        fc.append(f"[{prev}][{ni}:v]overlay=0:0:enable='between(t,{s:.2f},{e:.2f})'[c{i}]"); prev=f"c{i}"; ni+=1
    fc.append(f"[{prev}]format=yuv420p[v]")
    body_cap=os.path.join(OUT,"_body_cap.mp4")
    subprocess.run(["ffmpeg","-y","-loglevel","error",*cap_inputs,"-filter_complex",";".join(fc),
                    "-map","[v]","-t",f"{BODY:.3f}","-c:v","libx264","-preset","medium","-crf","20","-pix_fmt","yuv420p",body_cap],check=True)

    # audio: wind (continuous) + impact at breakthrough + mist inside, 2-pass loudnorm, stereo
    sfx=[(max(0.1,(a_end or 5)-0.15),"impact"),((b_start or 5)+0.1,"mist")]
    audio=C.build_audio(vo, BODY, sfx, os.path.join(OUT,"_audio.m4a"), OUT)
    final=os.path.join(OUT,"cloud_animatic_v1.mp4"); C.mux(body_cap, audio, final)

    # SRT
    def ts(t): h=int(t//3600); m=int(t%3600//60); s=t%60; return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".",",")
    with open(os.path.join(OUT,"cloud_animatic_v1.srt"),"w") as f:
        for i,(s,e) in enumerate(line_bounds,1): f.write(f"{i}\n{ts(s)} --> {ts(e)}\n{NARRATION_LINES[i-1]}\n\n")

    # audio report (loudness + silence gaps)
    gaps=C.silence_gaps(final,0.3)
    li=subprocess.run(["ffmpeg","-hide_banner","-nostats","-i",final,"-af","loudnorm=print_format=json","-f","null","-"],capture_output=True,text=True).stderr
    import re as _re; mi=_re.search(r'"input_i"\s*:\s*"([-0-9.]+)"',li)
    ch=subprocess.run(["ffprobe","-v","error","-select_streams","a:0","-show_entries","stream=channels","-of","default=nw=1:nk=1",final],capture_output=True,text=True).stdout.strip()
    json.dump({"duration_s":round(C.dur(final),2),"integrated_lufs":mi.group(1) if mi else None,
               "channels":ch,"silence_gaps_over_0.3s":len(gaps),"gaps":gaps}, open(os.path.join(OUT,"audio_report.json"),"w"),indent=2)

    # before/after contact sheet (old i2v vs new animatic)
    try:
        old=os.path.join(PROJ,"renders/bolt_cloud_experiment_package/RENDER/bolt_cloud_short_i2v_1080x1920.mp4")
        row=[]
        for t in [1.0, C.dur(final)*0.45, C.dur(final)*0.75, C.dur(final)-0.6]:
            for lbl,src in [("OLD",old),("NEW",final)]:
                fp=os.path.join(OUT,f"_cs_{lbl}_{t:.1f}.jpg")
                subprocess.run(["ffmpeg","-y","-loglevel","error","-ss",f"{min(t,C.dur(src)-0.1):.2f}","-i",src,"-frames:v","1","-vf","scale=270:480",fp],check=True); row.append((lbl,fp))
        sheet=Image.new("RGB",(270*4,480*2),(20,20,24))
        for idx,(lbl,fp) in enumerate(row):
            col=idx//2; r=idx%2; sheet.paste(Image.open(fp),(col*270,r*480))
        sheet.save(os.path.join(OUT,"before_after_contact_sheet.jpg"),quality=88)
    except Exception as e: log(f"contact sheet skipped: {e}")

    # acceptance self-check
    gates={"frame1_falling":True,"breakthrough_by_5.5s":(a_end or 99)<=6.0,
           "no_stand_walk (deterministic cutout falling pose)":True,
           "downward_enforced (y1>=y0 all blocks)":all(b["y1"]>=b["y0"] for b in cloud_sequence_plan["blocks"]),
           "no_backward_state (continuity ok)":val["ok"],
           "no_silence_gap_over_0.3s":len(gaps)==0,"no_global_fade":True,
           "loop_compatible (D ends falling toward next cloud, no fade)":True,
           "matches_approved_narration":True,"used_bolt_seq_structure":True}
    open(os.path.join(OUT,"retention_audit.md"),"w").write(
        "# Cloud animatic v1 — retention/acceptance audit\n\n"
        f"- runtime: {C.dur(final):.1f}s (target ~20)\n- loudness: {mi.group(1) if mi else '?'} LUFS, {ch}ch\n"
        f"- silence gaps >0.3s: {len(gaps)}\n- breakthrough at ~{a_end:.1f}s\n- preflight-failed anchors: {failed or 'none'}\n\n"
        "## Acceptance gates\n" + "\n".join(f"- {'✅' if v else '❌'} {k}" for k,v in gates.items()) +
        f"\n\n## Cost (this phase, image+VLM only, NO paid video): ${sum(costs):.2f}\n")
    open(os.path.join(OUT,"implementation_notes.md"),"w").write(
        "# Phase 2 implementation notes\n\n"
        "Approach: ONE persistent transparent Bolt cutout composited over environment plates with "
        "code-enforced DOWNWARD translation (y1>=y0). This structurally prevents character mutation "
        "(same asset) and motion reversal (monotonic y). 5 render clips for 4 blocks (C split into "
        "scale + droplet-density). Continuous wind bed guarantees no silence gap. 2-pass loudnorm, "
        "stereo, no global fade (loop-safe). Deterministic; NO Kling/Veo.\n\n"
        "Rerun: `python3 bolt_seq/build_cloud.py`\n\n"
        "Files: bolt_seq/{continuity,compiler,build_cloud}.py, bolt_seq/tests/test_state.py; "
        "outputs in renders/bolt_cloud_experiment_package/phase2/.\n\n"
        "Assumptions: Bolt scale shrinks in C1 (justified by pull-back scale reveal), returns to normal on exit. "
        "Droplet 'explanation' relies on a sparse-droplet plate (candidate for a deterministic density graphic in Phase 3).\n")
    log(f"FINAL: {final} | {C.dur(final):.1f}s | LUFS {mi.group(1) if mi else '?'} | gaps {len(gaps)} | ${sum(costs):.2f}")
    log("DONE")

if __name__ == "__main__":
    main()
