"""SIMULATION "DROP" pipeline — the BoneLab-style repeated visual experiment as a Bolt Short.

Concept: ONE object, a NEW environment each scene, a DESTRUCTIVE result, and a PERSISTENT survival
meter — a competition, not a fact-list. Pilot: "What Happens If You Drop Your Phone on Every Planet?"
Every scene contradicts the obvious expectation, the meter is the engine (viewers watch to see which
planet finally destroys it), and a final scoreboard names a winner.

KEY: every scene is IMAGE-TO-VIDEO (Kling via quiz_pipeline._motion_clip) — the whole Short is animated,
not a slideshow. Portrait 9:16. Reuses quiz_pipeline primitives + explainer_pipeline TTS/i2v/mascot.
"""
import os, json, subprocess
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import explainer_pipeline as ep
import quiz_pipeline as qp

FF = qp.FF
W, H, FPS = qp.W, qp.H, qp.FPS
NAVY, WHITE, CYAN, YEL, RED = qp.NAVY, qp.WHITE, qp.CYAN, qp.YEL, qp.RED
GREEN = (72, 200, 120); AMBER = (245, 190, 60); DKRED = (210, 55, 55); GREY = (150, 155, 170)
MUSIC = qp.MUSIC
_dur, _still, _safe_image, _composite, _fit, _motion_clip = (
    qp._dur, qp._still, qp._safe_image, qp._composite, qp._fit, qp._motion_clip)

# Layered prompt formula (per the "recreate & enhance" spec): [Subject] + [Action] + [Environment] are
# per-scene (script); STY carries the SHARED [Lighting] + [Camera] + [Art Style/Quality] layer so every
# scene color-grades and renders cohesively. Keep these keywords identical across scenes.
STY = (" Epic cinematic scene, dramatic volumetric lighting, god rays and lens flare, deep atmospheric "
       "haze, rich cinematic color grade, high contrast, shallow depth of field, medium close-up framing, "
       "3D animation, Pixar-style, Unreal Engine 5 render, highly detailed, vibrant, vertical 9:16, "
       "no text, no letters, no numbers, no UI, no watermark.")
# Subject description — IDENTICAL every scene for character consistency (spec: "describe the subject
# exactly the same way in every prompt"), reinforced by the attached reference image.
BOLT_REF = ("Use the attached reference image. The subject is Bolt: a cute, small, rounded matte-white "
            "and mint-green robot with a big dark glossy visor face and glowing cyan digital eyes and a "
            "little antenna. Keep him EXACTLY consistent in every shot. ")


def _health_color(h):
    if h is None:
        return GREY
    if h >= 67:
        return GREEN
    if h >= 34:
        return AMBER
    if h >= 1:
        return RED
    return DKRED


HUD = (46, 236, 255)          # neon-cyan sci-fi HUD accent


def _mono(sz):
    for p in ("/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Monaco.ttf",
              "/System/Library/Fonts/Supplemental/Courier New Bold.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            continue
    return qp._font(sz)


def _tg(dr, xy, s, sz, fill, anchor="mm", font=None):
    dr.text(xy, s, font=(font or qp._font(sz)), fill=fill, anchor=anchor)


def _brackets(dr, box, col, L=60, w=7):
    """L-shaped corner brackets — the signature HUD frame accent."""
    x0, y0, x1, y1 = box
    for cx, cy, sx, sy in [(x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)]:
        dr.line([(cx, cy), (cx + sx * L, cy)], fill=col, width=w)
        dr.line([(cx, cy), (cx, cy + sy * L)], fill=col, width=w)


def _hud_panel(dr, box, outline=HUD, fill=(6, 14, 24, 200), radius=18, w=4, bracket=True):
    dr.rounded_rectangle(box, radius=radius, fill=fill, outline=(*outline, 255), width=w)
    if bracket:
        _brackets(dr, [box[0] - 6, box[1] - 6, box[2] + 6, box[3] + 6], (*outline, 255), L=28, w=5)


def _meter(dr, health, label="PHONE HEALTH", mode="survival"):
    """Segmented neon HUD meter across the top. health: 0-100, or None for '—'. mode='survival' colors
    by level (green→red as it drops); mode='crush' is a rising danger bar (always hot orange-red), used
    when the survival bar has bottomed out but the jeopardy is still climbing (e.g. deep-ocean pressure)."""
    x0, x1, y0, y1 = 70, W - 70, 92, 190
    _hud_panel(dr, [x0, y0, x1, y1], radius=14)
    col = (255, 110, 40) if mode == "crush" else _health_color(health)
    lab = label.upper()
    lw = qp._font(38).getlength(lab)
    _tg(dr, (x0 + 34, (y0 + y1) // 2), lab, 38, (*HUD, 255), anchor="lm", font=qp._font(38))
    tx0 = x0 + 34 + lw + 30; tx1 = x1 - 150; ty0 = y0 + 34; ty1 = y1 - 34   # segmented fill
    segs = 12; gap = 7; sw = (tx1 - tx0 - gap * (segs - 1)) / segs
    frac = 0.0 if not health else max(0.0, min(1.0, health / 100.0))
    lit = int(round(frac * segs))
    for k in range(segs):
        sx0 = tx0 + k * (sw + gap)
        c = (*col, 255) if k < lit else (34, 54, 74, 255)
        dr.rounded_rectangle([sx0, ty0, sx0 + sw, ty1], radius=4, fill=c)
    lbl = "—" if health is None else f"{health}%"
    _tg(dr, (x1 - 82, (y0 + y1) // 2), lbl, 56, (*col, 255), anchor="mm", font=qp._font(56))


def _drop_overlay(path, planet=None, cue=None, health=None, cold_text=None, score=None, meter_label="PHONE HEALTH", cta=None, meter_mode="survival", marker=None):
    """Sci-fi HUD overlay: glowing frame + corner telemetry + segmented neon meter + tech panels, with a
    bloom pass so the cyan reads as neon (matching the Veo-style reference, but with OUR Bolt + logic)."""
    sharp = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(sharp)
    if score:                                             # dark scrim behind the results board
        d.rounded_rectangle([0, 0, W, H], fill=(4, 10, 20, 160))
    # HUD frame + corner brackets + decorative telemetry (every scene)
    d.rounded_rectangle([26, 26, W - 26, H - 26], radius=6, outline=(*HUD, 110), width=3)
    _brackets(d, [26, 26, W - 26, H - 26], (*HUD, 255), L=72, w=8)
    if not score:                                         # telemetry sits where the results title goes → skip on score
        tel = _mono(25)
        _tg(d, (46, 250), "SYS.LINK //OK", 25, (*HUD, 150), anchor="lm", font=tel)
        _tg(d, (46, 286), "SCAN: ACTIVE", 25, (*HUD, 120), anchor="lm", font=tel)
        _tg(d, (W - 46, 250), "SECTOR SOL-3", 25, (*HUD, 150), anchor="rm", font=tel)
        _tg(d, (W - 46, 286), "REC ●", 25, (255, 80, 80, 210), anchor="rm", font=tel)

    if cold_text:                                         # cold-open: meter at 100% + big title
        _meter(d, 100, meter_label)
        for i, ln in enumerate(cold_text):
            target = 118 if i == 0 else 94
            sz = target                                   # auto-fit: shrink until the line clears the frame
            while sz > 44 and qp._font(sz).getlength(ln.upper()) > W - 130:
                sz -= 4
            _tg(d, (W // 2, 800 + i * 150), ln.upper(), sz,
                (255, 220, 120, 255) if i == 0 else (255, 255, 255, 255), font=qp._font(sz))
    elif score:                                           # final scoreboard
        _tg(d, (W // 2, 400), "FINAL RESULTS", 92, (*HUD, 255), font=qp._font(92))
        y = 640
        for label, val, col in score:
            _tg(d, (W // 2, y), label.upper(), 54, (255, 255, 255, 255), font=qp._font(54)); y += 84
            _hud_panel(d, [W // 2 - 380, y, W // 2 + 380, y + 128], radius=14)
            _tg(d, (W // 2, y + 64), val.upper(), 100, (*col, 255), font=qp._font(100)); y += 216
        c1, c2 = (cta or ["WHAT SHOULD BOLT", "DROP NEXT?"])[:2]
        _tg(d, (W // 2, H - 300), c1.upper(), 62, (255, 220, 120, 255), font=qp._font(62))
        _tg(d, (W // 2, H - 226), c2.upper(), 62, (255, 220, 120, 255), font=qp._font(62))
    else:                                                 # planet scene: meter + planet chip + scientific cue
        _meter(d, health, meter_label, meter_mode)
        if planet:
            pw = int(qp._font(72).getlength(planet.upper())) + 120
            _hud_panel(d, [W // 2 - pw // 2, 210, W // 2 + pw // 2, 322], radius=12)
            _tg(d, (W // 2, 266), planet.upper(), 72, (255, 255, 255, 255), font=qp._font(72))
        if marker:                                        # comparison marker, e.g. "19× YOUR LIMIT"
            mw = int(qp._font(58).getlength(marker.upper())) + 70
            d.rounded_rectangle([W // 2 - mw // 2, 350, W // 2 + mw // 2, 436], radius=16, fill=(*DKRED, 235))
            _tg(d, (W // 2, 393), marker.upper(), 58, (255, 255, 255, 255), font=qp._font(58))
        if cue:
            lines = _wrap(d, cue.upper(), qp._font(84), W - 170)
            bh = 46 + len(lines) * 96 + 40
            _hud_panel(d, [50, H - 250 - bh, W - 50, H - 250], radius=16)
            rc = (255, 110, 40) if meter_mode == "crush" else _health_color(health)
            y = H - 250 - bh + 60
            for ln in lines:
                _tg(d, (W // 2, y), ln, 84, (*rc, 255), font=qp._font(84)); y += 96

    # BLOOM: composite a blurred copy under the crisp content so the cyan glows like neon
    glow = sharp.filter(ImageFilter.GaussianBlur(9))
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.alpha_composite(glow); out.alpha_composite(glow); out.alpha_composite(sharp)
    out.save(path)


def _event_vf(event, d):
    """Footage-level motion-graphic EVENT filter (applied to the base footage BEFORE the HUD overlay, so
    the meter/cue stay clean on top). Converts a narrated consequence into a visible on-beat EVENT."""
    ev = (event or "none").split(":")[0]
    if ev == "narcosis":            # nitrogen narcosis = drunk: chromatic double-vision + woozy roll + sat
        return (f"rgbashift=rh=12:bh=-12,scale=trunc(iw*1.08/2)*2:trunc(ih*1.08/2)*2,crop={W}:{H},"
                "rotate='0.035*sin(2*PI*0.42*t)':c=black,hue=s=1.2")
    if ev == "flatline":            # body gives out = black-out: vignette closes + fade to black at the end
        return f"vignette=a=PI/4,fade=t=out:st={max(0.0, d - 0.7):.2f}:d=0.7"
    if ev == "implosion":           # steel implodes: white flash then an instant dark impact
        fl = min(d * 0.55, 1.2)
        return (f"drawbox=x=0:y=0:w=iw:h=ih:color=white@0.85:t=fill:enable='between(t,{fl:.2f},{fl + 0.07:.2f})',"
                f"eq=brightness='if(gt(t,{fl + 0.07:.2f}),-0.13,0)':eval=frame")
    if ev == "pressure_rings":      # ears burst: a sharp decaying screen-shake + a cyan pressure flash
        return (f"crop=w=iw-28:h=ih-28:x='14+12*sin(58*t)*exp(-3.2*t)':y='14+12*cos(53*t)*exp(-3.2*t)',"
                f"scale={W}:{H},drawbox=color=cyan@0.22:t=fill:enable='between(t,0.15,0.32)'")
    if ev == "lung_crush":          # lungs crush: pressure closes IN — a hard vignette + a slow zoom-in
        dd = max(d, 0.1)            # (scale UP then center-crop = zoom with NO pad bars)
        return (f"vignette=a=PI/3.5,"
                f"scale=w='trunc({W}*(1+0.16*min(t/{dd:.2f}*2\\,1))/2)*2':"
                f"h='trunc({H}*(1+0.16*min(t/{dd:.2f}*2\\,1))/2)*2':eval=frame,crop={W}:{H}")
    return ""


def _i2v_clip(clean_img, textpng, out, d, motion, event=None, provider="fal", i2v_sink=None):
    """Image-to-video for ONE scene, sized so MOTION fills the whole scene. provider='fal' (Kling: 5/10s
    ambient motion) or 'veo' (Veo 3.1: better DIRECTED action/physics, 4-8s) — use veo for hero destruction
    shots. Overlay the static text, trim/tpad to exactly d. Ken-Burns fallback if i2v is unavailable."""
    raw = out + ".raw.mp4"
    if os.path.exists(raw):
        try: os.remove(raw)
        except OSError: pass
    # Veo 3.1 accepts ONLY 4/6/8s (5 & 7 -> 400 "durationSeconds out of bound" -> silent fallback);
    # snap UP to the smallest valid >= d so the clip always covers the narration (trimmed to d below).
    seconds = (next((s for s in (4, 6, 8) if s >= d), 8) if provider == "veo"
               else (10 if d > 5.3 else 5))
    import time as _t
    ok = False
    if provider == "veo":
        # Veo model-fallback CHAIN: each variant has its OWN quota bucket, so when fast is exhausted we
        # roll to standard (higher quality) then lite. On a hard quota (429) skip to the next model; retry
        # transient failures within a model. This multiplies daily capacity across the three Veo quotas.
        chain = [m.strip() for m in os.environ.get(
            "VEO_CHAIN", "veo-3.1-fast-generate-preview,veo-3.1-generate-preview,"
            "veo-3.1-lite-generate-preview").split(",") if m.strip()]
        for _model in chain:
            ep._VEO_MODEL = _model
            for _att in range(2):
                try:
                    ok, _quota, _err = ep._animate_one("veo", clean_img, motion, raw, W, H, seconds)
                except Exception:
                    ok, _quota = False, False
                if ok or _quota:
                    break
                _t.sleep(6)
            if ok:
                print(f"    [i2v] {os.path.basename(out)} via {_model}", flush=True)
                break
    else:
        try:
            ok, _, _ = ep._animate_one(provider, clean_img, motion, raw, W, H, seconds)
        except Exception:
            ok = False
    was_i2v = bool(ok) and os.path.exists(raw)                # real provider clip vs static fallback
    if i2v_sink is not None:
        i2v_sink.append(was_i2v)
    if not was_i2v:                                           # Ken-Burns fallback keeps it "a video"
        subprocess.run([FF, "-y", "-loop", "1", "-i", clean_img, "-t", f"{d}", "-vf",
            f"scale=1300:-1,zoompan=z='min(zoom+0.0009,1.2)':d={int(d*FPS)}:s={W}x{H},fps={FPS},format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", raw], capture_output=True)
    raw_dur = _dur(raw) or d
    pad = max(0.0, d - raw_dur)                               # only pads if raw is still shorter than d
    evf = _event_vf(event, d)                                 # footage-level EVENT (applied under the HUD)
    base = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"tpad=stop_mode=clone:stop_duration={pad:.3f},fps={FPS}")
    if evf:
        base += "," + evf
    subprocess.run([FF, "-y", "-i", raw, "-i", textpng, "-filter_complex",
        base + f"[v];[v][1:v]overlay=0:0,format=yuv420p[o]", "-map", "[o]", "-an", "-t", f"{d}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", out], capture_output=True)
    return d


def _wrap(draw, text, font, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= maxw or not cur:
            cur = t
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines


# Per-planet ATMOSPHERIC SOUND DESIGN — a distinct synthesized ambient bed under each segment (filtered
# noise: hiss / rumble / gusting wind), so each planet FEELS different (Mercury hiss, Venus deep rumble,
# Neptune fierce whoosh). Subtle: sits well under the narration + music.
_AMB = {
    "earth":   ("pink",  "lowpass=f=1000,volume=0.09,tremolo=f=0.15:d=0.4"),          # gentle breeze
    "mercury": ("white", "highpass=f=5000,volume=0.09"),                              # thin airless hiss
    "venus":   ("brown", "lowpass=f=170,volume=0.24,tremolo=f=0.12:d=0.5"),           # deep oppressive rumble
    "mars":    ("pink",  "bandpass=f=800:width_type=h:w=600,volume=0.14,tremolo=f=0.35:d=0.7"),   # thin whistling wind
    "jupiter": ("brown", "lowpass=f=350,volume=0.22,tremolo=f=0.2:d=0.6"),            # deep storm
    "saturn":  ("pink",  "bandpass=f=520:width_type=h:w=500,volume=0.15,tremolo=f=0.25:d=0.6"),   # airy wind
    "uranus":  ("pink",  "bandpass=f=1400:width_type=h:w=900,volume=0.16,tremolo=f=0.5:d=0.7"),   # cold howl
    "neptune": ("pink",  "bandpass=f=1100:width_type=h:w=900,volume=0.30,tremolo=f=0.9:d=0.85"),  # fiercest whoosh
    "ocean_shallow": ("pink",  "lowpass=f=700,volume=0.13,tremolo=f=0.10:d=0.5"),     # muffled water, slow swell
    "ocean_mid":     ("brown", "lowpass=f=320,volume=0.20,tremolo=f=0.12:d=0.6"),     # deep-water rumble
    "ocean_deep":    ("brown", "lowpass=f=150,volume=0.30,tremolo=f=0.10:d=0.7"),     # crushing pressure groan (ffmpeg tremolo min f=0.1)
    "_cold":   ("brown", "lowpass=f=500,volume=0.10"),                                # low space tone
    "_score":  ("pink",  "lowpass=f=900,volume=0.09"),
}


def _planet_ambience(key, dur, out):
    """Synthesize a `dur`-second atmospheric bed for a planet (or _cold/_score). Best-effort."""
    color, chain = _AMB.get((key or "").lower(), _AMB["_cold"])
    subprocess.run([FF, "-y", "-f", "lavfi", "-i", f"anoisesrc=color={color}:d={dur:.2f}",
                    "-af", chain + f",afade=t=in:st=0:d=0.3,afade=t=out:st={max(0.0, dur-0.4):.2f}:d=0.4",
                    out], capture_output=True)
    return out


def run_drop_pipeline(obj: str, output_dir: str, script: dict, voice: str = "echo",
                      progress_cb=None) -> dict:
    """Render a 'drop {obj} on every planet' animated Short. `script` = the (audited) scene list. EVERY
    scene is image-to-video. Returns an explainer-shaped dict."""
    def log(m):
        if progress_cb:
            progress_cb(m)
    output_dir = os.path.abspath(output_dir)   # absolute so ffmpeg concat lists never double the path
    os.makedirs(output_dir, exist_ok=True)
    A = output_dir; costs = []
    scenes = script["scenes"]
    meter_label = ep._s(script.get("meter_label")) or "PHONE HEALTH"
    pad = float(script.get("scene_pad", 0.5))              # gap after each line; lower = snappier (less dead air)
    title = ep._s(script.get("title")) or f"What Happens If You Drop Your {obj} on Every Planet?"
    log(f"Drop sim: \"{title}\" — {len(scenes)} scenes (i2v ALL)")

    if script.get("fact_check", True):                    # #6: best-effort numeric fact-check (corrects in place)
        try:
            import json as _json
            payload = [{"i": i, "narration": ep._s(sc.get("narration")), "cue": ep._s(sc.get("cue"))}
                       for i, sc in enumerate(scenes) if ep._s(sc.get("narration"))]
            r = ep._claude().messages.create(
                model="claude-opus-4-8", max_tokens=1500,
                system=("Numeric fact-checker for a science short. For each item verify EVERY number, "
                        "measurement, record and quantitative comparison in the narration/cue against "
                        "well-established fact; correct any value that is wrong or misleading and recompute "
                        "any multiplier so it stays self-consistent. Return ONLY JSON "
                        "{\"fixes\":[{\"i\":int,\"narration\":\"corrected line\",\"note\":\"why\"}]} — "
                        "include an item ONLY if it needs a correction."),
                messages=[{"role": "user", "content": _json.dumps(payload)}])
            costs.append(ep._msg_cost(r.usage))
            o, _ = ep._parse_script_json(r.content[0].text)
            for f in (o.get("fixes", []) if isinstance(o, dict) else []):
                idx = f.get("i")
                if isinstance(idx, int) and 0 <= idx < len(scenes) and ep._s(f.get("narration")).strip():
                    scenes[idx]["narration"] = f["narration"]
                    log(f"  factcheck s{idx}: {ep._s(f.get('note'))[:90]}")
        except Exception as e:
            log(f"fact-check skipped: {e}")

    mascot = [ep.MASCOT_REF] if os.path.exists(ep.MASCOT_REF) else None
    clips = []; audio = []; caps = []; t = 0.0; starts = []; i2v_flags = []
    CLEAN_AUDIO = script.get("clean_audio", True)   # #4: no procedural ambience/SFX noise; narration + ducked music only

    for i, sc in enumerate(scenes):
        starts.append(t)                                  # scene i begins at offset t (for riser/boom placement)
        kind = sc.get("kind", "planet")
        narr = ep._s(sc.get("narration"))
        img = f"{A}/img{i}.png"
        refs = mascot if sc.get("bolt", True) else None
        prompt = (BOLT_REF if refs else "") + ep._s(sc.get("image_visual")) + STY
        _safe_image(prompt, img, "1024x1536", costs, fallback_label=ep._s(sc.get("planet") or "SPACE"),
                    reference_paths=refs)
        # overlay (persistent meter + planet + result, OR cold-open / scoreboard)
        otxt = f"{A}/ov{i}.png"
        if kind == "cold":
            _drop_overlay(otxt, cold_text=sc.get("cold_text") or ["PHONE VS.", "EVERY PLANET"],
                          meter_label=meter_label)
        elif kind == "score":
            _cmap = {"green": GREEN, "amber": AMBER, "red": DKRED, "cyan": CYAN, "yellow": YEL,
                     "white": WHITE, "grey": GREY}
            sco = [(ep._s(l), ep._s(v), _cmap.get(str(c).lower(), CYAN))
                   for l, v, c in (sc.get("score") or [])]
            _drop_overlay(otxt, score=sco, cta=script.get("cta"))
        else:
            hv = sc.get("health"); hv = None if hv in (None, "", "-", "—") else int(hv)
            _ev = ep._s(sc.get("event"))
            mk = _ev.split(":", 1)[1] if _ev.startswith("marker:") else None
            _drop_overlay(otxt, planet=sc.get("planet"), cue=(sc.get("cue") or sc.get("result")),
                          health=hv, meter_label=(ep._s(sc.get("meter_label")) or meter_label),
                          meter_mode=(ep._s(sc.get("meter_mode")) or "survival"), marker=mk)
        # narration + duration
        n = f"{A}/n{i}.mp3"; ep.generate_tts(narr, n, voice=voice)
        d = _dur(n) + pad
        # IMAGE-TO-VIDEO every scene (10s Kling for long scenes so motion fills them; Ken-Burns fallback)
        clip = f"{A}/c{i:02d}.mp4"
        motion = ep._s(sc.get("motion")) or "subtle dramatic motion"
        # gas/ice giants read as "static" without extra atmospheric motion — add majestic (not chaotic)
        # churn so the clouds visibly move, matching the dynamism of the wind speeds we cite
        if kind == "planet" and ep._s(sc.get("planet")).lower() in ("jupiter", "saturn", "uranus", "neptune"):
            motion += "; the vast banded clouds churn and drift with slow, majestic, cinematic atmospheric motion"
        prov = ep._s(sc.get("provider")) or ep._s(script.get("i2v_provider")) or "fal"   # 'veo' for hero shots
        _i2v_clip(img, otxt, clip, d, motion, event=ep._s(sc.get("event")), provider=prov, i2v_sink=i2v_flags)
        clips.append(clip); audio.append((n, t, "narr"))
        if kind == "planet" and not CLEAN_AUDIO:
            audio.append(("IMPACT", t, "sfx"))
        # per-segment atmospheric ambience bed — OFF in clean-audio mode (procedural noise distracts viewers)
        if not CLEAN_AUDIO:
            if ep._s(script.get("ambience")) == "ocean":
                if kind == "planet":                      # key by DESCENT position (deeper scene = deeper bed)
                    amb_key = "ocean_shallow" if i <= 2 else "ocean_mid" if i <= 4 else "ocean_deep"
                else:
                    amb_key = "ocean_shallow" if kind == "cold" else "ocean_deep"
            else:
                amb_key = sc.get("planet") if kind == "planet" else ("_cold" if kind == "cold" else "_score")
            amb = f"{A}/amb{i}.wav"; _planet_ambience(amb_key, d, amb)
            audio.append((amb, t, "amb"))
        caps.append((t, _dur(n), narr)); t += d
        log(f"  scene {i+1}/{len(scenes)} [{kind}] {sc.get('planet','')} done")
    TOTAL = t

    # ANTICIPATION sound cues: a rising whoosh INTO the climax (last planet) + a deep boom ON the climax
    # and ON the payoff reveal — non-verbal "something big is coming" tension (psychological retention).
    if script.get("anticipation", True) and not CLEAN_AUDIO:
        RISER_D = 1.3
        riser = f"{A}/riser.wav"
        subprocess.run([FF, "-y", "-f", "lavfi", "-i", f"anoisesrc=color=pink:d={RISER_D}",
                        "-f", "lavfi", "-i", f"aevalsrc=0.5*sin(2*PI*t*(180+260*t)):d={RISER_D}",
                        "-filter_complex", "[0:a]highpass=f=220,volume=1.4[w];[1:a]volume=0.5[c];"
                        "[w][c]amix=inputs=2:normalize=0,afade=t=in:st=0:d=1.2,volume=1.4,aresample=48000[o]",
                        "-map", "[o]", riser], capture_output=True)
        boom = f"{A}/boom.wav"
        subprocess.run([FF, "-y", "-f", "lavfi", "-i", "sine=f=58:d=0.7", "-f", "lavfi",
                        "-i", "anoisesrc=color=brown:d=0.7", "-filter_complex",
                        "[0:a]volume=2.0[s];[1:a]highpass=f=40,lowpass=f=200,volume=1.2[n];"
                        "[s][n]amix=inputs=2:normalize=0,afade=t=out:st=0.12:d=0.55,volume=1.6,aresample=48000[o]",
                        "-map", "[o]", boom], capture_output=True)
        planet_idx = [i for i, sc in enumerate(scenes) if sc.get("kind", "planet") == "planet"]
        score_idx = [i for i, sc in enumerate(scenes) if sc.get("kind") == "score"]
        if planet_idx:
            climax = starts[planet_idx[-1]]               # last planet = the climax reveal
            audio.append((riser, max(0.0, climax - RISER_D), "riser"))
            audio.append((boom, climax, "boom"))
        if score_idx:
            audio.append((boom, starts[score_idx[0]], "boom"))   # payoff hit

    # captions (.srt) + transcript
    def _srt_ts(s):
        s = max(0.0, s); h = int(s // 3600); m = int((s % 3600) // 60); sec = int(s % 60)
        ms = int(round((s - int(s)) * 1000))
        if ms == 1000: sec += 1; ms = 0
        return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"
    srt_path = f"{A}/captions.srt"; transcript_path = f"{A}/transcript.txt"
    try:
        cs = sorted(caps, key=lambda c: c[0])
        with open(srt_path, "w") as fsrt:
            for k, (st, du, txt) in enumerate(cs, 1):
                fsrt.write(f"{k}\n{_srt_ts(st)} --> {_srt_ts(st + max(0.7, du))}\n{txt.strip()}\n\n")
        with open(transcript_path, "w") as ftx:
            ftx.write(" ".join(c[2].strip() for c in cs) + "\n")
    except Exception as e:
        log(f"caption write skipped: {e}"); srt_path = transcript_path = None

    log("stage:Assembling final video...")
    lst = f"{A}/list.txt"; open(lst, "w").write("".join(f"file '{os.path.abspath(c)}'\n" for c in clips))
    vsil = f"{A}/video_silent.mp4"
    subprocess.run([FF, "-y", "-f", "concat", "-safe", "0", "-i", lst, "-an", "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30", vsil],
                   capture_output=True)
    # soft impact "thud" on each planet drop
    imp = f"{A}/impact.wav"
    subprocess.run([FF, "-y", "-filter_complex",
                    "sine=140:d=0.18,volume=1.1,afade=t=out:st=0.04:d=0.13[o]", "-map", "[o]", imp],
                   capture_output=True)
    ins = []; parts = []; ix = 0
    for f, off, kind in audio:
        src = imp if kind == "sfx" else f                  # riser/boom carry their own file path in `f`
        ins += ["-i", src]; ms = int(off * 1000)
        vol = {"narr": 1.0, "sfx": 0.5, "amb": 1.0, "riser": 0.55, "boom": 0.85}.get(kind, 0.5)
        parts.append(f"[{ix}:a]adelay={ms}|{ms},volume={vol}[s{ix}]"); ix += 1
    mus = ix; music_ok = os.path.exists(MUSIC)
    if music_ok:
        ins += ["-stream_loop", "-1", "-i", MUSIC]
        parts.append(f"[{mus}:a]atrim=0:{TOTAL},volume=0.10,afade=t=in:st=0:d=0.4,afade=t=out:st={max(0,TOTAL-1.3):.2f}:d=1.3[mus]")
    mix = "".join(f"[s{k}]" for k in range(ix)) + ("[mus]" if music_ok else "")
    # master to ~-14 LUFS (the pipeline previously never normalized, so sim-drop shipped conspicuously quiet)
    parts.append(f"{mix}amix=inputs={ix + (1 if music_ok else 0)}:normalize=0,alimiter=limit=0.95,loudnorm=I=-12:TP=-1.5,aresample=48000[aout]")   # target -12: single-pass undershoots ~2 LU -> lands ~-14
    faud = f"{A}/full_audio.m4a"
    subprocess.run([FF, "-y", *ins, "-filter_complex", ";".join(parts), "-map", "[aout]", "-t", f"{TOTAL}",
                    "-c:a", "aac", "-b:a", "192k", faud], capture_output=True)
    out_mp4 = os.path.join(output_dir, "drop.mp4")
    subprocess.run([FF, "-y", "-i", vsil, "-i", faud, "-c:v", "copy", "-c:a", "aac", "-shortest",
                    "-movflags", "+faststart", out_mp4], capture_output=True)

    # description (best-effort)
    description_path = ""
    try:
        desc = ep._s(script.get("description"))
        tags = script.get("tags") or []
        hashtags = script.get("hashtags") or ["#SpaceFacts", "#Planets", "#WhatIf", "#ScienceShorts", "#Astronomy"]
        parts_d = [desc or title, " ".join(hashtags)]
        if tags:
            parts_d.append("Tags: " + ", ".join(tags[:20]))
        parts_d.append(ep._DESC_DISCLOSURE)
        description_path = os.path.join(A, "description.txt")
        with open(description_path, "w") as fdesc:
            fdesc.write("\n\n".join(parts_d) + "\n")
    except Exception as e:
        log(f"description skipped: {e}")

    cost = round(sum(costs), 3)
    n_fb = i2v_flags.count(False)
    _deg = ([f"{n_fb} of {len(i2v_flags)} scenes fell back to a static Ken-Burns still "
             f"(image-to-video unavailable — no real motion)"] if n_fb else [])
    if not os.path.exists(out_mp4):
        _deg = ["final video file was not produced — assembly failed"] + _deg
    if _deg:
        log("DEGRADED: " + _deg[0])
    log(f"Complete — drop sim assembled · ${cost}" + (f" · {n_fb} static fallback(s)" if n_fb else ""))
    return {"output_path": out_mp4, "title": title, "scene_count": len(clips),
            "duration_sec": round(_dur(out_mp4), 1), "script": script, "video_format": "social",
            "srt_path": srt_path, "transcript_path": transcript_path, "description_path": description_path,
            "status": ("degraded" if _deg else "ok"), "degraded_reasons": _deg,
            "actual_cost": cost, "est_cost": cost}
