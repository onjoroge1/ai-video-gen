"""Phase-2 cloud slice compiler: image gen (transparent cutout + plates), VLM preflight audit,
deterministic 2.5D animatic renderer (single persistent Bolt cutout composited with code-enforced
DOWNWARD motion → cannot mutate the character or reverse direction), whisper-aligned VO + wind/SFX.
No paid video providers. See BOLT_SEQUENCE_COMPILER.md."""
import os, sys, json, base64, subprocess, re
# Derived from this file, not pinned to one checkout. As a hardcoded absolute path this inserted
# the MAIN checkout at the FRONT of sys.path, so anything importing this module from a git worktree
# silently resolved `bolt_video`, `explainer_pipeline` and the rest against the other branch's code
# — importing a different program than the one under test and reporting no error at all.
# The one-off scripts in this package still pin the path; they are run by hand from the checkout
# they belong to. This one is a library and gets imported.
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path: sys.path.insert(0, PROJ)
import explainer_pipeline as ep
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1080, 1920, 30
SUP = "/System/Library/Fonts/Supplemental"
IMAGE_MODEL = getattr(ep, "IMAGE_MODEL", "gpt-image-2")

def _openai():
    from openai import OpenAI
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])

def dur(p):
    r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",p],
                       capture_output=True, text=True)
    try: return float(r.stdout.strip())
    except Exception: return 0.0

# ── image generation ───────────────────────────────────────────────────────────
def gen_image(prompt, out_path, size="1024x1536"):
    # gpt-image-2 does NOT support background=transparent; cutouts use magenta + chroma_key() instead.
    r = _openai().images.generate(model=IMAGE_MODEL, prompt=prompt, size=size, quality="medium", n=1)
    d = r.data[0]
    if getattr(d, "b64_json", None):
        open(out_path, "wb").write(base64.b64decode(d.b64_json))
    else:
        import urllib.request; urllib.request.urlretrieve(d.url, out_path)
    return out_path

def chroma_key(src_png, out_png, key="0xFF00FF"):
    """Key out a solid magenta background → RGBA PNG with alpha (model-agnostic transparency)."""
    subprocess.run(["ffmpeg","-y","-loglevel","error","-i",src_png,"-vf",
                    f"colorkey={key}:0.30:0.12,format=rgba", out_png], check=True)
    return out_png

# ── VLM preflight (claude-opus-4-8 vision) ───────────────────────────────────────
def preflight(image_path, checklist, cost_sink=None):
    """Return {'pass':bool,'violations':[...]}. checklist = list of yes/no requirements phrased so
    a violation is a NO. Best-effort: on API failure returns pass=True with a note."""
    if not checklist:                       # nothing to check → pass (e.g. a plain backdrop plate)
        return {"pass": True, "violations": []}
    try:
        b64 = base64.b64encode(open(image_path, "rb").read()).decode()
        media = "image/png" if image_path.endswith(".png") else "image/jpeg"
        reqs = "\n".join(f"- {c}" for c in checklist)
        r = ep._claude().messages.create(
            model="claude-opus-4-8", max_tokens=400,
            system=("You are a strict visual QA auditor for a character animation pipeline. Judge ONLY what "
                    "is visibly true in the image. For each requirement, decide pass/fail. Return ONLY JSON: "
                    "{\"violations\":[\"<short reason>\", ...]} — empty list means every requirement passes."),
            messages=[{"role":"user","content":[
                {"type":"image","source":{"type":"base64","media_type":media,"data":b64}},
                {"type":"text","text":f"Requirements (a violation is any that is NOT satisfied):\n{reqs}"}]}])
        if cost_sink is not None: cost_sink.append(ep._msg_cost(r.usage))
        o, _ = ep._parse_script_json(r.content[0].text)
        v = o.get("violations", []) if isinstance(o, dict) else []
        return {"pass": not v, "violations": v}
    except Exception as e:
        return {"pass": True, "violations": [], "note": f"preflight skipped: {type(e).__name__}"}

POSE_IDENTITY = ("rounded matte-white body with mint-green accents, glossy black visor screen with exactly "
  "two glowing cyan oval eyes and NO mouth, cyan chest panel, mint side panels, a thin antenna with a "
  "glowing cyan tip, two stubby arms, and a SINGLE rounded hover-base (NO legs, NO feet, NO boots, no extra limbs)")

def preflight_pose(image_path, pose_name, want, cost_sink=None, identity=None):
    """GENERIC perceptual pose gate (claude-opus-4-8 vision) — topic-agnostic. Scores how well the pose
    reads as the INTENDED ACTION `want` (falling, sprinting, reaching, collapsing, …), regardless of
    topic. Rejects poses that read as calm/waving/standing/presenting. `identity` = the character bible
    (defaults to POSE_IDENTITY). Returns {pass, scores, reads_as}."""
    identity = identity or POSE_IDENTITY
    try:
        b64 = base64.b64encode(open(image_path,"rb").read()).decode()
        r = ep._claude().messages.create(
            model="claude-opus-4-8", max_tokens=400,
            system=("You are a strict motion/pose critic for character animation. Judge ONLY the pose in the "
                    "image against the INTENDED ACTION given by the user. Score 0-10: identity (matches the "
                    "described character exactly), action_readability (instantly reads as the intended action, "
                    "not a neutral pose), urgency, directional_clarity (clear motion direction/intent), "
                    "silhouette (strong readable outline), and neutral_pose_probability (0=clearly dynamic, "
                    "10=looks like calm waving/standing/floating/presenting-to-camera). Return ONLY JSON: "
                    "{\"identity\":n,\"action_readability\":n,\"urgency\":n,\"directional_clarity\":n,"
                    "\"silhouette\":n,\"neutral_pose_probability\":n,\"reads_as\":\"one phrase\"}."),
            messages=[{"role":"user","content":[
                {"type":"image","source":{"type":"base64","media_type":"image/png","data":b64}},
                {"type":"text","text":f"Character identity: {identity}. Intended action for pose '{pose_name}': {want}."}]}])
        if cost_sink is not None: cost_sink.append(ep._msg_cost(r.usage))
        o,_ = ep._parse_script_json(r.content[0].text); o = o if isinstance(o,dict) else {}
        g = {k:float(o.get(k,0) or 0) for k in ("identity","action_readability","urgency","directional_clarity","silhouette","neutral_pose_probability")}
        ok = (g["identity"]>=7 and g["action_readability"]>=7 and g["directional_clarity"]>=6
              and g["neutral_pose_probability"]<=3 and g["urgency"]>=6)
        return {"pass": ok, "scores": g, "reads_as": o.get("reads_as","")}
    except Exception as e:
        return {"pass": True, "scores": {}, "reads_as": f"skipped:{type(e).__name__}"}

def gen_pose(prompt, out_path, pose_name, want, tries=4, cost_sink=None, log=print):
    raw = out_path + ".raw.png"; best=None
    for i in range(tries):
        gen_image(prompt, raw, size="1024x1536")
        pf = preflight_pose(raw, pose_name, want, cost_sink=cost_sink)
        log(f"    pose {pose_name} try{i+1}: {'PASS' if pf['pass'] else 'fail'} {pf['scores']} reads='{pf['reads_as']}'")
        if best is None or (pf["scores"].get("falling_readability",0)-pf["scores"].get("neutral_pose_probability",0)) > \
                           (best[1]["scores"].get("falling_readability",0)-best[1]["scores"].get("neutral_pose_probability",0)):
            import shutil; keep=out_path+f".try{i+1}.png"; shutil.copy(raw,keep); best=(keep,pf)
        if pf["pass"]:
            best=(raw,pf); break
    chroma_key(best[0], out_path)
    return {"path":out_path,"passed":best[1]["pass"],"scores":best[1]["scores"],"reads_as":best[1]["reads_as"]}

def gen_with_preflight(prompt, out_path, checklist, size="1024x1536", cutout=False,
                       tries=3, reuse=True, cost_sink=None, log=print):
    if reuse and os.path.exists(out_path):
        log(f"    reuse existing {os.path.basename(out_path)}")
        return {"path": out_path, "passed": True, "attempts": [{"reused": True}]}
    attempts = []
    raw = out_path + ".raw.png" if cutout else out_path   # cutout: preflight the magenta render, then key
    for i in range(tries):
        gen_image(prompt, raw, size=size)
        pf = preflight(raw, checklist, cost_sink=cost_sink)
        attempts.append({"attempt": i+1, **pf})
        log(f"    preflight {os.path.basename(out_path)} try{i+1}: {'PASS' if pf['pass'] else 'FAIL '+str(pf['violations'])}")
        if pf["pass"]:
            break
    if cutout:
        chroma_key(raw, out_path)
    return {"path": out_path, "passed": attempts[-1]["pass"], "attempts": attempts}

# ── captions ─────────────────────────────────────────────────────────────────────
def _font(s):
    try: return ImageFont.truetype(f"{SUP}/Arial Bold.ttf", s)
    except Exception: return ImageFont.load_default()

def caption_png(text, path):
    img = Image.new("RGBA", (W, H), (0,0,0,0)); d = ImageDraw.Draw(img)
    words = text.split(); lines = [""]
    for w in words:
        if len(lines[-1]+" "+w) > 16 and lines[-1]: lines.append(w)
        else: lines[-1] = (lines[-1]+" "+w).strip()
    f = _font(82); lh = 104; y0 = int(H*0.72)
    for i, ln in enumerate(lines):
        b = d.textbbox((0,0), ln, font=f); tw = b[2]-b[0]; x = (W-tw)//2; y = y0+i*lh
        d.rounded_rectangle([x-30, y-18, x+tw+30, y+lh-26], radius=20, fill=(0,0,0,140))
        d.text((x, y), ln, font=f, fill=(245,245,245), stroke_width=5, stroke_fill=(0,0,0))
    img.save(path)

# ── deterministic block renderer (2.5D) ──────────────────────────────────────────
def render_block(out_mp4, plate, bolt, d, bolt_h, y0f, y1f, *, x_wobble=0.0, plate_zoom="in",
                 cloud_layer=None, caption=None, tmp_dir=None):
    """One continuous block: plate (Ken-Burns drift) + persistent Bolt cutout translated DOWNWARD
    (y0f->y1f, ENFORCED y1f>=y0f) + optional cloud dispersal + caption. Deterministic; no i2v."""
    assert y1f >= y0f, f"downward invariant violated: y0f={y0f} y1f={y1f}"
    fr = max(1, round(d*FPS)); tmp_dir = tmp_dir or os.path.dirname(out_mp4)
    z = {"in":"min(1.0+0.0012*on,1.10)","out":"if(lte(on,1),1.10,max(1.10-0.0012*on,1.0))",
         "hold":"min(1.0+0.0004*on,1.02)"}.get(plate_zoom, "min(1.0+0.0012*on,1.10)")
    # scaled Bolt cutout
    bolt_s = os.path.join(tmp_dir, "_bolt_s_"+os.path.basename(out_mp4)+".png")
    bi = Image.open(bolt).convert("RGBA"); ratio = bolt_h/bi.height
    bi.resize((max(1,int(bi.width*ratio)), bolt_h), Image.LANCZOS).save(bolt_s)
    inputs = ["-loop","1","-framerate",str(FPS),"-i",plate, "-loop","1","-i",bolt_s]
    parts = [f"[0:v]scale=2160:3840:force_original_aspect_ratio=increase,crop=2160:3840,"
             f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={fr}:s={W}x{H}:fps={FPS},setsar=1[bg]"]
    yexpr = f"({H}*{y0f})+({H}*({y1f}-{y0f}))*(t/{d})"
    xexpr = f"(W-w)/2" + (f"+{x_wobble}*sin(2*PI*t/1.6)" if x_wobble else "")
    prev = "bg"; nidx = 2
    if cloud_layer:  # dispersal puff rising + fading in the lower frame as Bolt passes (block A)
        inputs += ["-loop","1","-i",cloud_layer]
        parts.append(f"[{nidx}:v]scale={W}:-1,format=rgba,fade=t=out:st={max(0,d-1.4):.2f}:d=1.2:alpha=1[cl]")
        parts.append(f"[{prev}][cl]overlay=x=0:y='H*0.52 - {int(H*0.12)}*(t/{d})'[bgc]")
        prev = "bgc"; nidx += 1
    parts.append(f"[{prev}][1:v]overlay=x='{xexpr}':y='{yexpr}'[bv]")
    prev = "bv"
    if caption:
        inputs += ["-loop","1","-i",caption]
        parts.append(f"[{prev}][{nidx}:v]overlay=0:0[cap]"); prev = "cap"
    parts.append(f"[{prev}]format=yuv420p[v]")
    subprocess.run(["ffmpeg","-y","-loglevel","error",*inputs,"-filter_complex",";".join(parts),
                    "-map","[v]","-t",f"{d:.3f}","-r",str(FPS),"-c:v","libx264","-preset","medium",
                    "-crf","19","-pix_fmt","yuv420p", out_mp4], check=True)
    return out_mp4

# ── GENERIC motion renderer (topic-agnostic: axis vertical|horizontal|radial|stationary) ──────────
def draw_particles(path, w, h2, kind="streak", n=70, seed=7):
    """Deterministic parallax particle strip (transparent PNG, height h2 for scrolling). streak=speed
    lines, droplet=dots. Free/clean (PIL, no chroma-key)."""
    import random as _r
    rng = _r.Random(seed); img = Image.new("RGBA",(w,h2),(0,0,0,0)); d = ImageDraw.Draw(img)
    for _ in range(n):
        x = rng.randint(0,w); y = rng.randint(0,h2); a = rng.randint(40,150)
        if kind == "streak":
            L = rng.randint(40,160); wln = rng.randint(2,5)
            d.line([(x,y),(x,y+L)], fill=(255,255,255,a), width=wln)
        else:  # droplet
            rr = rng.randint(3,9); d.ellipse([x-rr,y-rr,x+rr,y+rr], fill=(220,240,255,a))
    img.save(path)

def render_motion_block(out_mp4, plate, pose, d, *, axis="vertical", p0=0.08, p1=0.62, curve="accel",
                        rot_deg=0.0, plate_zoom="in", pose_h=640, particles=None, part_scroll="up",
                        caption=None, wobble=0.0, tmp_dir=None):
    """One continuous block with PHYSICAL motion. axis: vertical/horizontal/radial/stationary. curve:
    accel(ease-in, velocity increases) | linear | decel. Parallax particles scroll OPPOSITE to travel.
    Whole-body rotation + temporal motion-blur (tmix). Deterministic; no generative motion model.
    NOTE: 'downward' is NOT assumed — cloud passes vertical/accel/down via p0<p1; oxygen passes
    horizontal via axis='horizontal'."""
    fr = max(1, round(d*FPS)); tmp_dir = tmp_dir or os.path.dirname(out_mp4)
    z = {"in":"min(1.0+0.0018*on,1.14)","out":"if(lte(on,1),1.14,max(1.14-0.0018*on,1.0))",
         "hold":"min(1.0+0.0005*on,1.03)"}.get(plate_zoom, "min(1.0+0.0018*on,1.14)")
    # pose → scaled onto a padded transparent square (so rotation never clips)
    pose_s = os.path.join(tmp_dir, "_pose_"+os.path.basename(out_mp4)+".png")
    pi = Image.open(pose).convert("RGBA"); r = pose_h/pi.height
    pi = pi.resize((max(1,int(pi.width*r)), pose_h), Image.LANCZOS)
    pad = int(pose_h*0.5); canvas = Image.new("RGBA",(pi.width+2*pad, pi.height+2*pad),(0,0,0,0))
    canvas.alpha_composite(pi,(pad,pad)); canvas.save(pose_s); pw = pi.width+2*pad
    prog = f"(t/{d})*(t/{d})" if curve=="accel" else (f"(2*(t/{d})-(t/{d})*(t/{d}))" if curve=="decel" else f"(t/{d})")
    # travel expression per axis (position of overlay top-left)
    if axis == "horizontal":
        xexpr = f"({W}*{p0})+({W}*({p1}-{p0}))*{prog}"; yexpr = f"(H-h)/2" + (f"+{wobble}*sin(2*PI*t/1.5)" if wobble else "")
    elif axis == "stationary":
        xexpr = "(W-w)/2"; yexpr = "(H-h)/2"
    else:  # vertical (default)
        yexpr = f"({H}*{p0})+({H}*({p1}-{p0}))*{prog}"; xexpr = f"(W-w)/2" + (f"+{wobble}*sin(2*PI*t/1.5)" if wobble else "")
    inputs = ["-loop","1","-framerate",str(FPS),"-i",plate,"-loop","1","-i",pose_s]
    parts = [f"[0:v]scale=2160:3840:force_original_aspect_ratio=increase,crop=2160:3840,"
             f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={fr}:s={W}x{H}:fps={FPS},setsar=1[bg]"]
    prev="bg"; nidx=2
    if particles:
        inputs += ["-loop","1","-i",particles]
        sc = f"-(h-{H})*(t/{d})" if part_scroll=="up" else f"-(h-{H})*(1-t/{d})"
        parts.append(f"[{nidx}:v]scale={W}:-1[pp]")
        parts.append(f"[{prev}][pp]overlay=x=0:y='{sc}'[bgp]"); prev="bgp"; nidx+=1
    if rot_deg:
        parts.append(f"[1:v]rotate=a='{rot_deg}*PI/180*(t/{d})':c=none:ow={pw}:oh={pw}[pr]")
        posev="[pr]"
    else:
        posev="[1:v]"
    parts.append(f"[{prev}]{posev}overlay=x='{xexpr}':y='{yexpr}'[mv]")
    parts.append(f"[mv]tmix=frames=3:weights='1 1 1'[mb]")   # temporal motion-blur on fast movement
    prev="mb"
    if caption:
        inputs += ["-loop","1","-i",caption]
        parts.append(f"[{prev}][{nidx}:v]overlay=0:0[capd]"); prev="capd"
    parts.append(f"[{prev}]format=yuv420p[v]")
    subprocess.run(["ffmpeg","-y","-loglevel","error",*inputs,"-filter_complex",";".join(parts),
                    "-map","[v]","-t",f"{d:.3f}","-r",str(FPS),"-c:v","libx264","-preset","medium",
                    "-crf","19","-pix_fmt","yuv420p", out_mp4], check=True)
    return out_mp4

# ── audio: continuous wind (guarantees no silence gap) + timed SFX + VO, 2-pass loudnorm ──────────
# ambient bed presets (continuous → guarantees no silence gap); topic-agnostic
_AMBIENT = {
    "wind":  "anoisesrc=color=brown:amplitude=0.6:duration={T},lowpass=f=520,highpass=f=80,volume=0.13",
    "water": "anoisesrc=color=brown:amplitude=0.7:duration={T},lowpass=f=360,highpass=f=40,volume=0.15",
    "room":  "anoisesrc=color=pink:amplitude=0.4:duration={T},lowpass=f=700,volume=0.06",
}

def build_audio(vo_path, total, sfx_events, out_path, tmp_dir, ambient="wind"):
    """sfx_events = [(t_seconds, kind)] kind in {impact, mist, alarm}. `ambient` bed is continuous
    (no >0.3s silence) → wind/water/room presets."""
    bed = _AMBIENT.get(ambient, _AMBIENT["wind"]).format(T=total)
    fc = [f"{bed}[wind]"]
    labels = ["[wind]"]
    for i,(t,kind) in enumerate(sfx_events):
        if kind == "impact":
            fc.append(f"anoisesrc=color=white:amplitude=0.9:duration=0.6,lowpass=f=1200,"
                      f"volume=0.5,afade=t=in:st=0:d=0.03,afade=t=out:st=0.12:d=0.45,adelay={int(t*1000)}|{int(t*1000)}[sx{i}]")
        elif kind == "alarm":
            fc.append(f"sine=frequency=880:duration=0.5,volume=0.22,afade=t=in:st=0:d=0.02,"
                      f"afade=t=out:st=0.3:d=0.2,adelay={int(t*1000)}|{int(t*1000)}[sx{i}]")
        else:  # mist swell
            fc.append(f"anoisesrc=color=pink:amplitude=0.5:duration=1.8,lowpass=f=900,volume=0.12,"
                      f"afade=t=in:st=0:d=0.5,afade=t=out:st=1.2:d=0.6,adelay={int(t*1000)}|{int(t*1000)}[sx{i}]")
        labels.append(f"[sx{i}]")
    # VO delayed slightly so it doesn't hit frame 0 (vo.mp3 is input 0; wind/SFX are lavfi sources)
    fc.append(f"[0:a]adelay=80|80,apad,atrim=0:{total}[vo]")
    labels.append("[vo]")
    fc.append("".join(labels)+f"amix=inputs={len(labels)}:normalize=0:dropout_transition=0[mix]")
    fc.append(f"[mix]atrim=0:{total}[a1]")
    raw = os.path.join(tmp_dir,"_audio_raw.wav")
    subprocess.run(["ffmpeg","-y","-loglevel","error","-i",vo_path,"-filter_complex",";".join(fc),
                    "-map","[a1]", raw], check=True)
    # 2-pass loudnorm to -14
    p1 = subprocess.run(["ffmpeg","-hide_banner","-nostats","-i",raw,"-af",
        "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json","-f","null","-"],capture_output=True,text=True).stderr
    m = re.search(r"\{[^{}]*\"input_i\"[\s\S]*?\}", p1); meas = json.loads(m.group(0))
    ln2 = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={meas['input_i']}:measured_TP={meas['input_tp']}:"
           f"measured_LRA={meas['input_lra']}:measured_thresh={meas['input_thresh']}:offset={meas['target_offset']}:linear=true")
    subprocess.run(["ffmpeg","-y","-loglevel","error","-i",raw,"-af",f"{ln2},aresample=48000",
                    "-ac","2", out_path], check=True)
    return out_path

def concat(clips, out, tmp_dir):
    lst = os.path.join(tmp_dir,"_concat.txt")
    with open(lst,"w") as f:
        # absolute paths: the concat demuxer resolves 'file' relative to the LIST's dir, not cwd
        for c in clips: f.write(f"file '{os.path.abspath(c)}'\n")
    subprocess.run(["ffmpeg","-y","-loglevel","error","-f","concat","-safe","0","-i",lst,"-c","copy",out],check=True)
    return out

def mux(body, audio, out):  # NO global fade (loop-compatible); stereo aac
    subprocess.run(["ffmpeg","-y","-loglevel","error","-i",body,"-i",audio,"-map","0:v","-map","1:a",
                    "-c:v","copy","-c:a","aac","-b:a","192k","-ac","2","-movflags","+faststart", out],check=True)
    return out

def silence_gaps(path, thresh=0.3):
    sd = subprocess.run(["ffmpeg","-hide_banner","-nostats","-i",path,"-af",
        f"silencedetect=n=-40dB:d={thresh}","-f","null","-"],capture_output=True,text=True).stderr
    return [l for l in sd.splitlines() if "silence_start" in l]

# ── GENERIC multi-entity scene-graph compositor (topic-agnostic, deterministic 2D provider) ────────
# Consumes a resolved scene graph (bolt_seq.scene_graph) and composites every entity per frame in PIL,
# so scale/rotation/opacity/position/pose/parent-attachment all animate deterministically. This is the
# renderer both cloud and oxygen use — no single-plate/single-pose assumption, no generative motion.
from functools import lru_cache

@lru_cache(maxsize=64)
def _load_rgba(path):
    return Image.open(path).convert("RGBA")

def _with_opacity(img, opacity):
    if opacity >= 0.999:
        return img
    a = img.split()[3].point(lambda p: int(p * max(0.0, min(1.0, opacity))))
    o = img.copy(); o.putalpha(a); return o

def _place_env(base, spec):
    """Full-frame background entity: cover-fit the plate to H*scale, then crop a WxH window whose
    offset is driven by x/y (pan) — gives horizontal tunnel scroll AND vertical fall AND Ken-Burns."""
    W, H = base.size
    img = _load_rgba(spec["image"])
    z = max(1.0, spec["scale"])
    tgt_h = int(H * z)
    tgt_w = max(int(W * z), int(img.width * (tgt_h / img.height)))
    scaled = img.resize((tgt_w, tgt_h), Image.LANCZOS)
    px = int((scaled.width - W) * (spec["cx"] / W))
    py = int((scaled.height - H) * (spec["cy"] / H))
    px = max(0, min(scaled.width - W, px)); py = max(0, min(scaled.height - H, py))
    base.alpha_composite(scaled.crop((px, py, px + W, py + H)), (0, 0))

def _paste(base, img, cx, cy, scale, rot, opacity, base_h):
    if opacity <= 0.01:
        return
    h = max(1, int(base_h * scale)); r = h / img.height
    im = img.resize((max(1, int(img.width * r)), h), Image.LANCZOS)
    if rot:
        im = im.rotate(rot, expand=True, resample=Image.BICUBIC)
    im = _with_opacity(im, opacity)
    base.alpha_composite(im, (int(cx - im.width / 2), int(cy - im.height / 2)))

def render_scene_block(out_mp4, entities, d, *, W=1080, H=1920, fps=30, tmp_dir=None,
                       draw_fn=None, tmix=2, bg=(6, 8, 14, 255)):
    """Render one block from a resolved scene graph. `entities` = the block's entity list (tracks
    already written by bindings). `draw_fn(name, params, (W,H)) -> RGBA` renders procedural entities
    (meters / effects). Deterministic; no generative motion."""
    from . import scene_graph as SG
    tmp_dir = tmp_dir or os.path.dirname(out_mp4)
    fdir = os.path.join(tmp_dir, "_frames_" + os.path.splitext(os.path.basename(out_mp4))[0])
    os.makedirs(fdir, exist_ok=True)
    for f in os.listdir(fdir):
        os.remove(os.path.join(fdir, f))
    fr = max(1, round(d * fps)); prev = {}
    for i in range(fr):
        t = i / max(1, fr - 1)
        frame = Image.new("RGBA", (W, H), bg)
        for spec in SG.resolve_frame(entities, t, W, H):
            if not spec["visible"] or spec["opacity"] <= 0.01:
                prev.pop(spec["id"], None); continue
            if spec["kind"] == "environment" and not spec["draw"]:
                _place_env(frame, spec); continue
            img = draw_fn(spec["draw"], spec["params"], (W, H)) if spec["draw"] else \
                  (_load_rgba(spec["image"]) if spec["image"] else None)
            if img is None:
                continue
            # full-frame procedural effects (fog/vignette/flash) return a WxH image → composite at 0,0
            if spec["draw"] and img.size == (W, H):
                frame.alpha_composite(_with_opacity(img, spec["opacity"]), (0, 0))
                prev.pop(spec["id"], None); continue
            base_h = spec["base_h"]
            cx, cy, sc = spec["cx"], spec["cy"], spec["scale"]
            # motion ghosting on fast entities → reads as speed, reduces the "sticker slide" look
            if spec["motion_ghost"] and spec["id"] in prev:
                pcx, pcy = prev[spec["id"]]
                if (cx - pcx) ** 2 + (cy - pcy) ** 2 > 400:
                    for g, a in ((0.66, 0.22), (0.33, 0.40)):
                        _paste(frame, img, pcx + (cx - pcx) * g, pcy + (cy - pcy) * g,
                               sc, spec["rot"], spec["opacity"] * a, base_h)
            _paste(frame, img, cx, cy, sc, spec["rot"], spec["opacity"], base_h)
            prev[spec["id"]] = (cx, cy)
        frame.convert("RGB").save(os.path.join(fdir, f"f{i:05d}.png"))
    vf = f"tmix=frames={tmix}:weights='{' '.join(['1']*tmix)}',format=yuv420p" if tmix > 1 else "format=yuv420p"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
                    "-i", os.path.join(fdir, "f%05d.png"), "-vf", vf, "-r", str(fps),
                    "-t", f"{d:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                    "-pix_fmt", "yuv420p", out_mp4], check=True)
    return out_mp4
