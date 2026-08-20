"""
TV Review pipeline (legacy name: State Board) — pasted review narration -> an evolving story board:
an always-on code-drawn faction/status rail (board_pipeline.render_board) over ORIGINAL
per-chapter location backdrops, with voiceover. Section-snapping: the board holds, then
snaps to a new state each chapter.

run_stateboard_pipeline(topic, script_text, output_dir, voice, progress_cb) -> dict

IP: characters are TEXT chips (never actor likenesses / copyrighted character art); location art
is original and generic-by-type (never a copyrighted/proper-noun place); no footage. The narration
is the user's own text, voiced verbatim.
"""
import os, re, subprocess
import explainer_pipeline as ep       # generate_tts, generate_image
import board_pipeline as bp           # render_board, extract_state_timeline
from PIL import Image, ImageDraw
from font_utils import load_font

_SUP = "/System/Library/Fonts/Supplemental"
def _F(p, s, i=0):
    return load_font(p, s, index=i, bold="Bold" in p or p.endswith(".ttc"))

_LOC_SUFFIX = (" Cinematic matte painting, dramatic volumetric light, rich depth, moody, high detail. "
               "NO people, NO faces, NO text, NO letters, NO logos, NO watermark. Entirely ORIGINAL "
               "design that does NOT resemble any specific existing film, TV show, book, or video game.")

def _loc_prompt(desc):
    desc = (desc or "an epic dramatic landscape").strip()[:200]
    return f"An original establishing background: {desc}." + _LOC_SUFFIX

def _split_chapters(text):
    """Chapters = blank-line-separated paragraphs (verbatim). Falls back to sentence grouping."""
    text = (text or "").replace("\r\n", "\n").strip()
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(parts) < 2:
        sents = re.split(r"(?<=[.!?])\s+", text)
        n = max(2, min(8, len(sents) // 3 or 2))
        size = max(1, len(sents) // n)
        parts = [" ".join(sents[i:i+size]).strip() for i in range(0, len(sents), size)]
        parts = [p for p in parts if p]
    return parts[:16]

def _dur(p):
    r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                        "-of","default=nw=1:nk=1", p], capture_output=True, text=True)
    try: return float(r.stdout.strip())
    except Exception: return 0.0

def _cover1080(path):
    img = Image.open(path).convert("RGB"); tw, th = 1920, 1080
    s = max(tw/img.width, th/img.height)
    img = img.resize((round(img.width*s), round(img.height*s)), Image.LANCZOS)
    l = (img.width-tw)//2; t = (img.height-th)//2
    img.crop((l, t, l+tw, t+th)).save(path)

def _fallback_card(path, seed=0):
    cols = [(24,28,38),(30,24,34),(22,30,34),(34,28,22)]
    c = cols[seed % len(cols)]
    img = Image.new("RGB",(1920,1080))
    px = img.load()
    for y in range(1080):
        f = y/1080
        for x in range(0,1920,4):
            px[x,y] = (int(c[0]*(1-f*0.6)), int(c[1]*(1-f*0.6)), int(c[2]*(1-f*0.6)))
    img.save(path)

def _title_overlay(topic, subtitle, path):
    W,H = 1920,1080
    img = Image.new("RGBA",(W,H),(0,0,0,0)); d = ImageDraw.Draw(img)
    top = int(H*0.60)
    for y in range(top,H):
        a = int(220*((y-top)/(H-top))**1.4); d.line([(0,y),(W,y)], fill=(0,0,0,a))
    pad = 96; GOLD=(216,179,106); WHITE=(245,243,238); GREY=(206,206,206)
    if subtitle:
        d.text((pad, H-260), subtitle.upper(), font=_F(f"{_SUP}/Copperplate.ttc",30), fill=GOLD)
    # wrap topic to <= ~24 chars/line, 2 lines
    words = topic.split(); lines=[""]
    for w in words:
        if len(lines[-1]+" "+w) > 26 and lines[-1]: lines.append(w)
        else: lines[-1] = (lines[-1]+" "+w).strip()
    tf = _F(f"{_SUP}/Georgia Bold.ttf", 88)
    y = H-200
    for ln in lines[:2]:
        d.text((pad, y), ln, font=tf, fill=WHITE, stroke_width=1, stroke_fill=(0,0,0)); y += 96
    img.save(path)

def _pad_states(states, n):
    """Ensure exactly n states (carry-forward on shortfall, truncate on excess)."""
    if not states: return None
    out = list(states[:n])
    while len(out) < n:
        import copy; out.append(copy.deepcopy(out[-1]))
    for i, s in enumerate(out):
        s["footer"] = f"CH {i+1} / {n}" + (" · " + s.get("footer","").split("· ",1)[-1] if "·" in s.get("footer","") else "")
    return out

def run_stateboard_pipeline(topic, script_text, output_dir, voice="onyx",
                            subtitle="", progress_cb=None, review_context=None):
    log = progress_cb or (lambda m: None)
    output_dir = os.path.abspath(output_dir); os.makedirs(output_dir, exist_ok=True)

    chapters = _split_chapters(script_text)
    if len(chapters) < 2:
        raise ValueError("Need at least 2 chapters — separate sections with a blank line.")
    log(f"stage:Reading {len(chapters)} chapters…")
    blocks = [{"title": f"Chapter {i+1}", "narration": c} for i, c in enumerate(chapters)]

    log("stage:Building the state board…")
    states = bp.extract_state_timeline(blocks, topic=topic, review_context=review_context)
    degraded = []
    if not states:
        raise ValueError("Could not build a state board from this script (extraction failed).")
    if len(states) != len(chapters):
        degraded.append(f"state timeline had {len(states)} chapters for {len(chapters)} inputs — padded")
        states = _pad_states(states, len(chapters))

    log("stage:Recording voiceover…")
    mp3s = []
    for i, c in enumerate(chapters):
        p = os.path.join(output_dir, f"vo_{i:02d}.mp3")
        ep.generate_tts(c, p, voice=voice); mp3s.append(p)
        log(f"voiceover {i+1}/{len(chapters)} ✓")
    listf = os.path.join(output_dir, "_vo.txt")
    with open(listf, "w") as f:
        for p in mp3s: f.write(f"file '{p}'\n")
    narration = os.path.join(output_dir, "narration.mp3")
    subprocess.run(["ffmpeg","-y","-loglevel","error","-f","concat","-safe","0","-i",listf,
                    "-c","copy", narration], check=True)

    log("stage:Painting locations…")
    loc_cache = {}
    for st in states:
        desc = (st.get("_location_art") or topic).strip()
        key = desc.lower()
        if key not in loc_cache:
            lp = os.path.join(output_dir, f"loc_{len(loc_cache):02d}.png")
            try:
                ep.generate_image(_loc_prompt(desc), lp, size="1536x1024"); _cover1080(lp)
            except Exception:
                _fallback_card(lp, len(loc_cache)); degraded.append(f"location art failed for '{desc[:40]}'")
            loc_cache[key] = lp
        st["_loc_path"] = loc_cache[key]
    log(f"{len(loc_cache)} unique locations painted")

    log("stage:Rendering the board…")
    clips = []; clist = os.path.join(output_dir, "_clips.txt"); cf = open(clist, "w")
    for i, st in enumerate(states):
        board = os.path.join(output_dir, f"board_{i:02d}.png"); bp.render_board(st, board)
        d = _dur(mp3s[i]); fr = max(1, round(d*24))
        clip = os.path.join(output_dir, f"clip_{i:02d}.mp4")
        vf = (f"[0:v]scale=2560:1440,zoompan=z='min(1.0+0.0000042*on,1.06)':d={fr}:"
              f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1920x1080:fps=24,format=yuv420p[bg];"
              f"[bg][1:v]overlay=0:0,format=yuv420p[v]")
        subprocess.run(["ffmpeg","-y","-loglevel","error","-loop","1","-framerate","24","-i",st["_loc_path"],
                        "-loop","1","-i",board,"-filter_complex",vf,"-map","[v]","-t",f"{d:.3f}",
                        "-r","24","-c:v","libx264","-preset","medium","-crf","19","-pix_fmt","yuv420p",clip],
                       check=True)
        cf.write(f"file '{clip}'\n")
        log(f"chapter {i+1}/{len(states)} rendered ✓")
    cf.close()
    body = os.path.join(output_dir, "_body.mp4")
    subprocess.run(["ffmpeg","-y","-loglevel","error","-f","concat","-safe","0","-i",clist,"-c","copy",body], check=True)

    log("stage:Assembling final video…")
    title_png = os.path.join(output_dir, "_title.png"); _title_overlay(topic, subtitle, title_png)
    DUR = _dur(body); out_fade = max(0.1, DUR-1.5); a_fade = max(0.1, DUR-1.2)
    final = os.path.join(output_dir, "tv_review.mp4")
    vf = (f"[2:v]format=rgba,fade=t=in:st=0:d=0.6:alpha=1,fade=t=out:st=9.3:d=1.2:alpha=1[ttl];"
          f"[0:v][ttl]overlay=0:0:enable='between(t,0,10.5)',"
          f"fade=t=in:st=0:d=1.0,fade=t=out:st={out_fade:.2f}:d=1.5[v];"
          f"[1:a]afade=t=in:st=0:d=0.5,afade=t=out:st={a_fade:.2f}:d=1.2,"
          f"loudnorm=I=-13:TP=-1.5:LRA=11,aresample=48000[a]")
    subprocess.run(["ffmpeg","-y","-loglevel","error","-i",body,"-i",narration,"-loop","1","-i",title_png,
                    "-filter_complex",vf,"-map","[v]","-map","[a]","-t",f"{DUR:.2f}",
                    "-c:v","libx264","-preset","medium","-crf","20","-pix_fmt","yuv420p",
                    "-c:a","aac","-b:a","192k","-movflags","+faststart", final], check=True)

    # thumbnail: first location + board
    thumb = os.path.join(output_dir, "thumbnail.jpg")
    try:
        base = Image.open(states[0]["_loc_path"]).convert("RGBA").resize((1920,1080))
        ov = Image.open(os.path.join(output_dir,"board_00.png")).convert("RGBA")
        Image.alpha_composite(base, ov).convert("RGB").save(thumb, quality=90)
    except Exception:
        thumb = None

    log("stage:Done")
    return {"output_path": final, "title": topic, "chapters": len(chapters),
            "duration_sec": round(DUR,1), "thumbnail_path": thumb,
            "status": "degraded" if degraded else "ok", "degraded_reasons": degraded}
