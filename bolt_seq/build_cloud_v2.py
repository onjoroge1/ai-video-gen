"""Phase 2.1: cloud_animatic_v2 — deterministic ANIMATION (multi-pose + accelerated physical motion +
parallax + tumble rotation + motion-blur + breakthrough flash), reusing the GENERIC core
(render_motion_block, continuity, preflight, audio). Cloud is config here; oxygen will reuse the same
functions. Run: python3 bolt_seq/build_cloud_v2.py"""
import os, sys, json, subprocess, re
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ); sys.path.insert(0, PROJ)
from dotenv import load_dotenv; load_dotenv(dotenv_path=os.path.join(os.getcwd(),".env"), override=True)
import explainer_pipeline as ep
from bolt_seq import compiler as C, continuity as K
from PIL import Image

P = os.path.join(PROJ,"renders/bolt_cloud_experiment_package/phase2")
LIB=os.path.join(P,"bolt_pose_library"); AS=os.path.join(P,"assets")
def log(m): print(m, flush=True)
W,H=1080,1920
NAR=["Could Bolt land on a cloud?","It looks solid enough.","He hits the top…","…and falls right through.",
 "Inside, he's soaked…","…cold, and blind.","But this cloud weighs a million pounds.","So why can't it hold him?",
 "A cloud is just fog — too thin to hold anything, so he falls right through.","So… could you ever land on a cloud?"]
CAP=["LAND ON A CLOUD?","LOOKS SOLID…","HE HITS THE TOP","…AND FALLS THROUGH","SOAKED","COLD • BLIND",
 "1,000,000 LBS","SO WHY NOT?","IT'S JUST FOG","COULD YOU?"]
# per-block motion config (CLOUD fixture — cloud=config, not core logic). pose from the locked library.
BLK=[
 dict(id="A",lines=[0,1,2,3],plate="plate_sky",pose="dive_pose",axis="vertical",p0=0.04,p1=0.66,curve="accel",
      zoom="in",pose_h=560,part="streak",rot=0),
 dict(id="B",lines=[4,5],plate="plate_inside",pose="tumble_pose",axis="vertical",p0=0.10,p1=0.66,curve="linear",
      zoom="hold",pose_h=470,part="streak",rot=40),
 dict(id="C1",lines=[6,7],plate="plate_scale",pose="dive_pose",axis="vertical",p0=0.14,p1=0.52,curve="linear",
      zoom="out",pose_h=150,part=None,rot=0),
 dict(id="C2",lines=[8],plate="plate_droplets",pose="dive_pose",axis="vertical",p0=0.12,p1=0.62,curve="linear",
      zoom="out",pose_h=210,part="droplet",rot=0),
 dict(id="D",lines=[9],plate="plate_exit",pose="exit_loop_pose",axis="vertical",p0=0.05,p1=0.62,curve="accel",
      zoom="in",pose_h=520,part="streak",rot=0)]

def main():
    costs=[]
    vo=os.path.join(P,"vo.mp3")
    if not os.path.exists(vo): ep.generate_tts(" ".join(NAR),vo,voice="onyx")
    words=ep.transcribe_words(vo); D_vo=C.dur(vo)
    norm=lambda s: re.sub(r"[^a-z0-9]","",s.lower())
    fw=[[norm(w) for w in ln.split() if norm(w)] for ln in NAR]; cum=0; ends=[]
    okw=len(words)>=sum(len(f) for f in fw)-4
    for f in fw: cum+=len(f); ends.append(words[min(cum-1,len(words)-1)][2] if okw else round(D_vo*cum/sum(len(x) for x in fw),3))
    lb=[]; prev=0.0
    for i,e in enumerate(ends): end=e+0.10+(0.5 if i==len(ends)-1 else 0); lb.append((round(prev,3),round(end,3))); prev=end

    # particles (deterministic PIL)
    C.draw_particles(os.path.join(P,"_streak.png"),W,3840,"streak",90,7)
    C.draw_particles(os.path.join(P,"_droplet.png"),W,3840,"droplet",70,11)

    # render blocks with generic motion renderer; collect motion-curve data
    clips=[]; mrep=[]; a_end=None
    for b in BLK:
        s=lb[b["lines"][0]][0]; e=lb[b["lines"][-1]][1]; d=round(e-s,3)
        if b["id"]=="A": a_end=e
        clip=os.path.join(P,f"v2_{b['id']}.mp4")
        C.render_motion_block(clip, os.path.join(AS,b["plate"]+".png"), os.path.join(LIB,b["pose"]+".png"), d,
            axis=b["axis"],p0=b["p0"],p1=b["p1"],curve=b["curve"],rot_deg=b["rot"],plate_zoom=b["zoom"],
            pose_h=b["pose_h"], particles=os.path.join(P,f"_{b['part']}.png") if b["part"] else None,
            part_scroll="up", tmp_dir=P)
        clips.append(clip)
        # motion-curve: sampled vertical position (accel = quadratic) → velocity/altitude
        n=10; ys=[b["p0"]+(b["p1"]-b["p0"])*((k/n)**2 if b["curve"]=="accel" else k/n) for k in range(n+1)]
        vels=[round(ys[k+1]-ys[k],4) for k in range(n)]
        mrep.append({"block":b["id"],"pose":b["pose"],"axis":b["axis"],"curve":b["curve"],"dur":d,
                     "y_frac":[round(y,3) for y in ys],"vel_step":vels,
                     "altitude_monotonic_down":all(ys[k+1]>=ys[k] for k in range(n)),
                     "velocity_increases":(b["curve"]!="accel") or all(vels[k+1]>=vels[k]-1e-9 for k in range(n-1))})
        log(f"  v2 block {b['id']}: {d}s pose={b['pose']} curve={b['curve']}")
    body=C.concat(clips, os.path.join(P,"_v2body.mp4"), P); BODY=C.dur(body)

    # captions (per line, top strip) + breakthrough WHITE FLASH at A→B rupture
    flash=os.path.join(P,"_flash.png"); Image.new("RGBA",(W,H),(255,255,255,255)).save(flash)
    ins=["-i",body]; fc=[]; prev="0:v"; ni=1
    ins+=["-loop","1","-i",flash]; fc.append(f"[{prev}][{ni}:v]format=rgba,fade=t=out:st={a_end:.2f}:d=0.22:alpha=1[fl]" if False else f"[{ni}:v]format=yuva420p,fade=t=in:st={max(0,a_end-0.05):.2f}:d=0.05:alpha=1,fade=t=out:st={a_end:.2f}:d=0.20:alpha=1[flh]")
    fc.append(f"[{prev}][flh]overlay=0:0:enable='between(t,{max(0,a_end-0.05):.2f},{a_end+0.22:.2f})'[fb]"); prev="fb"; ni+=1
    for i,(s,e) in enumerate(lb):
        cp=os.path.join(P,f"_v2cap_{i}.png"); C.caption_png(CAP[i],cp); ins+=["-loop","1","-i",cp]
        fc.append(f"[{prev}][{ni}:v]overlay=0:0:enable='between(t,{s:.2f},{e:.2f})'[c{i}]"); prev=f"c{i}"; ni+=1
    fc.append(f"[{prev}]format=yuv420p[v]")
    bodyc=os.path.join(P,"_v2bodycap.mp4")
    subprocess.run(["ffmpeg","-y","-loglevel","error",*ins,"-filter_complex",";".join(fc),"-map","[v]",
        "-t",f"{BODY:.3f}","-c:v","libx264","-preset","medium","-crf","20","-pix_fmt","yuv420p",bodyc],check=True)

    # audio (wind continuous + impact at rupture + mist inside), 2-pass loudnorm, stereo
    sfx=[(max(0.1,a_end-0.1),"impact"),(a_end+0.15,"mist")]
    audio=C.build_audio(vo,BODY,sfx,os.path.join(P,"_v2audio.m4a"),P)
    final=os.path.join(P,"cloud_animatic_v2.mp4"); C.mux(bodyc,audio,final)

    # srt
    def ts(t): h=int(t//3600);m=int(t%3600//60);s=t%60;return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".",",")
    open(os.path.join(P,"cloud_animatic_v2.srt"),"w").write(
        "".join(f"{i+1}\n{ts(s)} --> {ts(e)}\n{NAR[i]}\n\n" for i,(s,e) in enumerate(lb)))

    # reports
    json.dump(mrep, open(os.path.join(P,"motion_curve_report.json"),"w"), indent=2)
    gaps=C.silence_gaps(final,0.3)
    li=subprocess.run(["ffmpeg","-hide_banner","-nostats","-i",final,"-af","loudnorm=print_format=json","-f","null","-"],capture_output=True,text=True).stderr
    mi=re.search(r'"input_i"\s*:\s*"([-0-9.]+)"',li)
    ch=subprocess.run(["ffprobe","-v","error","-select_streams","a:0","-show_entries","stream=channels","-of","default=nw=1:nk=1",final],capture_output=True,text=True).stdout.strip()
    json.dump({"duration_s":round(C.dur(final),2),"integrated_lufs":mi.group(1) if mi else None,"channels":ch,
               "silence_gaps_over_0.3s":len(gaps)},open(os.path.join(P,"audio_report.json"),"w"),indent=2)

    # perceptual quality gate (VLM on sampled frames of the FINAL)
    frames=[]
    for f in (0.03,0.18,0.4,0.62,0.82,0.97):
        fp=os.path.join(P,f"_pq_{f}.jpg"); subprocess.run(["ffmpeg","-y","-loglevel","error","-ss",f"{C.dur(final)*f:.2f}","-i",final,"-frames:v","1","-vf","scale=360:640",fp],check=True); frames.append(fp)
    import base64
    content=[]
    for fp in frames: content.append({"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":base64.b64encode(open(fp,'rb').read()).decode()}})
    content.append({"type":"text","text":"These 6 frames are in time order from a vertical Short about a robot falling through a cloud. Score 0-10 and return ONLY JSON: {\"active_hook\":n,\"acceleration_readability\":n,\"urgency\":n,\"impact_clarity\":n,\"escalation_between_blocks\":n,\"muted_explanation_comprehension\":n,\"climax_stronger_than_hook\":n,\"sticker_slide_appearance\":n(0=looks like real animation,10=looks like a sticker sliding),\"loop_quality\":n,\"notes\":\"one line\"}"})
    try:
        r=ep._claude().messages.create(model="claude-opus-4-8",max_tokens=400,
            system="You are a strict short-form retention critic. Judge only what the frames show.",
            messages=[{"role":"user","content":content}])
        costs.append(ep._msg_cost(r.usage)); pq,_=ep._parse_script_json(r.content[0].text); pq=pq if isinstance(pq,dict) else {}
    except Exception as e: pq={"error":str(e)}
    json.dump(pq,open(os.path.join(P,"perceptual_quality_report.json"),"w"),indent=2)

    # continuity report (declarative) + v1/v2 + muted-comprehension contact sheets
    json.dump({"note":"cloud continuity invariants (altitude down, no reverse) enforced by monotonic p0<p1 + accel curves","motion":mrep},open(os.path.join(P,"continuity_report.json"),"w"),indent=2)
    try:
        v1=os.path.join(P,"cloud_animatic_v1.mp4")
        sheet=Image.new("RGB",(360*4,640*2),(18,18,22))
        for col,fr in enumerate([0.08,0.4,0.7,0.95]):
            for row,src in enumerate([v1,final]):
                fp=os.path.join(P,f"_cs_{row}_{col}.jpg"); subprocess.run(["ffmpeg","-y","-loglevel","error","-ss",f"{C.dur(src)*fr:.2f}","-i",src,"-frames:v","1","-vf","scale=360:640",fp],check=True); sheet.paste(Image.open(fp),(col*360,row*640))
        sheet.save(os.path.join(P,"v1_vs_v2_contact_sheet.jpg"),quality=88)
        msheet=Image.new("RGB",(360*3,640),(18,18,22))
        for col,fr in enumerate([0.03,0.5,0.9]):
            fp=os.path.join(P,f"_mc_{col}.jpg"); subprocess.run(["ffmpeg","-y","-loglevel","error","-ss",f"{C.dur(final)*fr:.2f}","-i",final,"-frames:v","1","-vf","scale=360:640",fp],check=True); msheet.paste(Image.open(fp),(col*360,0))
        msheet.save(os.path.join(P,"muted_comprehension_contact_sheet.jpg"),quality=88)
    except Exception as e: log(f"contact sheets: {e}")

    sticker=pq.get("sticker_slide_appearance",99)
    open(os.path.join(P,"retention_audit_v2.md"),"w").write(
        f"# cloud_animatic_v2 — retention audit\n\n- runtime {C.dur(final):.1f}s · {ch}ch · {mi.group(1) if mi else '?'} LUFS · silence gaps {len(gaps)}\n"
        f"- poses: dive/tumble/exit (impact skipped — text2img gave a calm pose)\n- motion: accelerated (quadratic) fall + parallax streaks + tumble rotation + motion-blur + breakthrough flash\n\n"
        f"## Perceptual quality gate (VLM)\n```json\n{json.dumps(pq,indent=2)}\n```\n"
        f"- sticker_slide_appearance = {sticker} (target ≤3)\n\n"
        f"## Cost this phase (image+VLM only, NO paid video): ${sum(costs):.2f}\n")
    log(f"FINAL v2: {final} | {C.dur(final):.1f}s | LUFS {mi.group(1) if mi else '?'} | gaps {len(gaps)} | sticker {sticker} | ${sum(costs):.2f}")
    log("DONE")

if __name__=="__main__": main()
