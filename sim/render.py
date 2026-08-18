"""Assemble a simulation: clips + overlays + narration -> gated portrait short.

Shape of the format, and why:
  * Every scene is a hard cut. A simulation is a comparison, and a dissolve between two worlds
    blends the very thing the viewer is supposed to contrast.
  * The overlay is composited AFTER any fade, so chips and captions never blink at a cut -- the same
    ordering bug that made the previous format's rail flicker.
  * A generated clip is 5s and every scene is shorter, so clips are trimmed, never looped or frozen.
  * A scene with no narration is a real beat, not an error: it gets silence of its own length.
"""
from __future__ import annotations
import json
import os
import subprocess

from PIL import Image, ImageOps

from sim import overlay as OV


def _run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def _dur(p):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                 "-of", "csv=p=0", p], capture_output=True, text=True).stdout or 0)


def _still_bg(sim, scene, out):
    im = ImageOps.fit(Image.open(sim.asset(scene.image)).convert("RGB"),
                      (int(sim.W * 1.12), int(sim.H * 1.12)), Image.LANCZOS)
    im.save(out)


def build_shot(sim, scene, clip, frames, idx, out):
    """One scene -> one mp4 of exactly `frames` frames at sim.fps."""
    ovp = os.path.join(sim.work, f"ov_{scene.id}.png")
    OV.build(scene, sim.W, sim.H, ovp)
    if clip:
        # A generated clip is a fixed ~5.04s; a scene is as long as its narration. The old fill was
        # tpad=stop_mode=clone, which CLONES THE LAST FRAME -- so any scene longer than its clip
        # ended in a dead hold, and the gate read 6.77s of stall on an 11.4s scene. Shuffling words
        # between scenes only moved the freeze.
        # Ping-pong instead: play forward, then backward, and repeat. Ambient and hover motion
        # reverses without reading as rewind, and the shot never stops changing. A hard loop back to
        # frame 0 would read as a cut mid-shot; the reversal does not.
        src = int(round(_dur(clip) * sim.fps))
        seg = max(2 * src - 2, 2)                      # forward + reverse, endpoints not repeated
        reps = max(1, -(-frames // seg))               # ceil: enough cycles to cover the scene
        vf = (f"[0:v]scale={sim.W}:{sim.H}:force_original_aspect_ratio=increase,"
              f"crop={sim.W}:{sim.H},fps={sim.fps},split[f][b];[b]reverse,"
              f"trim=start_frame=1,setpts=PTS-STARTPTS[rv];[f][rv]concat=n=2:v=1,"
              f"loop=loop={reps}:size={seg}:start=0,"
              f"trim=end_frame={frames},setpts=PTS-STARTPTS[c];"
              # no fade-in: on a hard-cut grammar a per-shot fade reads as a black flash at every
              # boundary (measured: 1 full black frame + 3 dark ones at each of 15 cuts)
              f"[c][1:v]overlay=0:0:format=auto,format=yuv420p[v]")
        _run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip,
              "-loop", "1", "-framerate", str(sim.fps), "-i", ovp,
              "-filter_complex", vf, "-map", "[v]", "-frames:v", str(frames),
              "-r", str(sim.fps), "-c:v", "libx264", "-preset", "medium", "-crf", "19",
              "-pix_fmt", "yuv420p", out])
    else:
        bgp = os.path.join(sim.work, f"bg_{scene.id}.png")
        _still_bg(sim, scene, bgp)
        step = 0.055 / max(frames, 1)          # duration-aware: a fixed step freezes long shots
        z = f"min(1.0+{step:.7f}*on,1.055)" if idx % 2 == 0 else f"max(1.055-{step:.7f}*on,1.0)"
        vf = (f"[0:v]zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:"
              f"s={sim.W}x{sim.H}:fps={sim.fps},trim=end_frame={frames}[b];"
              f"[b][1:v]overlay=0:0:format=auto,format=yuv420p[v]")
        _run(["ffmpeg", "-y", "-loglevel", "error",
              "-loop", "1", "-framerate", str(sim.fps), "-i", bgp,
              "-loop", "1", "-framerate", str(sim.fps), "-i", ovp,
              "-filter_complex", vf, "-map", "[v]", "-frames:v", str(frames),
              "-r", str(sim.fps), "-c:v", "libx264", "-preset", "medium", "-crf", "19",
              "-pix_fmt", "yuv420p", out])
    return out


def prepare_durations(sim, progress=print):
    """Narrate, and set each scene's real on-screen duration from its audio.

    Public because anything that renders scene-length content -- the physics compositor, for one --
    needs the SAME durations main() will use. Recomputing them separately would drift.
    """
    import explainer_pipeline as epl
    os.makedirs(sim.work, exist_ok=True)
    for sc in sim.scenes:
        sc._vo, sc._dur = None, sc.seconds
        if not sc.narration.strip():
            continue
        p = os.path.join(sim.work, f"vo_{sc.id}.mp3")
        if not (os.path.exists(p) and os.path.getsize(p) > 800):
            epl.generate_tts(sc.narration, p, voice=sim.voice, speed=getattr(sim, "speed", 1.0))
        sc._vo, sc._dur = p, max(_dur(p) + sim.pad_s, 0.8)
    total = sum(s._dur for s in sim.scenes)
    progress(f"  narration: {sum(1 for s in sim.scenes if s._vo)} lines, {total:.1f}s")
    return total


def main(sim, clips=None, progress=print):
    os.makedirs(sim.work, exist_ok=True)
    clips = clips or {}
    if any(getattr(sc, "_dur", None) is None for sc in sim.scenes):
        prepare_durations(sim, progress)

    # 2. shots
    shot_files, cuts, t = [], [], 0.0
    for i, sc in enumerate(sim.scenes):
        frames = max(1, int(round(sc._dur * sim.fps)))
        out = os.path.join(sim.work, f"shot_{i:02d}_{sc.id}.mp4")
        build_shot(sim, sc, clips.get(sc.id), frames, i, out)
        shot_files.append(out)
        cuts.append({"t": round(t, 2), "seg": sc.id, "image": sc.image,
                     "animated": bool(clips.get(sc.id)), "frames": frames})
        t += frames / sim.fps
        progress(f"  [{i+1:2d}/{len(sim.scenes)}] {sc.id:16s} {sc._dur:4.1f}s "
                 f"{'clip' if clips.get(sc.id) else 'still'}")

    # 3. hard-cut concat
    lst = os.path.join(sim.work, "concat.txt")
    with open(lst, "w") as f:
        for c in shot_files:
            f.write(f"file '{os.path.abspath(c)}'\n")
    silent = os.path.join(sim.work, "silent.mp4")
    _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
          "-i", lst, "-c", "copy", silent])

    # 4. audio: every segment padded to EXACTLY its scene length.
    # Getting this wrong is silent and expensive: the video adds breathing room per scene, and if the
    # audio is concatenated raw the track ends short, `-shortest` truncates the VIDEO to match, and
    # the final scene disappears from the finished file. That cost the payoff line once already.
    parts = []
    for sc in sim.scenes:
        seg = os.path.join(sim.work, f"aud_{sc.id}.wav")
        if sc._vo:
            _run(["ffmpeg", "-y", "-loglevel", "error", "-i", sc._vo,
                  "-af", f"apad,atrim=0:{sc._dur:.3f},aformat=sample_rates=44100:channel_layouts=mono",
                  seg])
        else:
            _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                  "-i", "anullsrc=r=44100:cl=mono", "-t", f"{sc._dur:.3f}", seg])
        parts.append(seg)
    ain = []
    for p in parts:
        ain += ["-i", p]
    fg = "".join(f"[{i}:a]aformat=sample_rates=44100:channel_layouts=mono[a{i}];"
                 for i in range(len(parts)))
    fg += "".join(f"[a{i}]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1[o]"
    vo = os.path.join(sim.work, "narration.wav")
    _run(["ffmpeg", "-y", "-loglevel", "error"] + ain + ["-filter_complex", fg, "-map", "[o]", vo])

    # scene-aligned SFX (rain impacts on the worlds where rain lands, silence elsewhere) -- the
    # mix carries the physics claim, so the track is built from the same measured durations as
    # the picture. Seeded and free; see sim/sfx.py.
    from . import sfx as SFX
    sfx_wav = SFX.build(sim)

    m = subprocess.run(["ffmpeg", "-hide_banner", "-i", vo, "-af",
                        "loudnorm=I=-14:TP=-1:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    af = "loudnorm=I=-14:TP=-1"
    try:
        j = json.loads(m[m.rfind("{"):m.rfind("}") + 1])
        af = (f"loudnorm=I=-14:TP=-1:measured_I={j['input_i']}:measured_TP={j['input_tp']}"
              f":measured_LRA={j['input_lra']}:measured_thresh={j['input_thresh']}"
              f":offset={j['target_offset']}:linear=true")
    except Exception:
        pass
    final = os.path.join(sim.out, f"{sim.slug}.mp4")
    os.makedirs(sim.out, exist_ok=True)
    bed = os.path.join("static", "music", f"{getattr(sim, 'music', None) or ''}.mp3")
    if getattr(sim, "music", None) and os.path.exists(bed):
        import audio_bed as AB
        # music_gain_for returns a LINEAR multiplier, NOT decibels. Passing it as `volume=0.24dB`
        # instead of `volume=0.24` leaves the bed ~12 dB hot and buries the narration -- caught only
        # because the printed gains did not match the arithmetic. Keep it linear, and keep this note.
        g = AB.music_gain_for(sim.music)
        # sidechaincompress keyed on the voice: the bed ducks when he speaks and returns in the gaps,
        # rather than sitting at a fixed pad under everything.
        sfx_in, sfx_mix, n_mix = [], "", 2
        if sfx_wav and os.path.exists(sfx_wav):
            # -18 dB under the voice: present in the gaps, audible under speech, never competing.
            # The SFX does NOT pass through the sidechain -- the bed ducks for the voice, the rain
            # does not, because a landing you cannot hear is the easter egg deleted.
            sfx_in = ["-i", sfx_wav]
            # 0.28 (~-11 dB): at 0.125 the measured per-scene separation between rain worlds and
            # silent worlds nearly vanished under bed+voice -- an easter egg no one can hear is a
            # comment in a mix. Verified by per-span RMS after the change.
            sfx_mix = "[3:a]volume=0.28,aformat=sample_rates=44100:channel_layouts=stereo[fx];"
            n_mix = 3
        fgm = (f"[1:a]{af}[vo];"
               # the bed is highpassed at 200 Hz WHEN SFX EXIST: the tense pulse's kick lives exactly in the
               # 70-170 Hz band the Titan impacts occupy, and two things in one band is neither. The
               # music keeps its pulse; the floor belongs to the physics.
               f"[2:a]volume={g},{'highpass=f=200,' if sfx_mix else ''}"
               f"aformat=sample_rates=44100:channel_layouts=stereo[mus];"
               f"{sfx_mix}"
               f"[vo]asplit[v1][key];"
               f"[mus][key]sidechaincompress=threshold=0.02:ratio=12:attack=5:release=320[duck];"
               f"[v1][duck]" + ("[fx]" if sfx_mix else "") +
               f"amix=inputs={n_mix}:duration=first:normalize=0,"
               f"loudnorm=I=-14:TP=-1,aformat=channel_layouts=stereo[a]")
        _run(["ffmpeg", "-y", "-loglevel", "error", "-i", silent, "-i", vo,
              "-stream_loop", "-1", "-i", bed] + sfx_in + ["-filter_complex", fgm,
              "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
              "-shortest", "-movflags", "+faststart", final])
    else:
        _run(["ffmpeg", "-y", "-loglevel", "error", "-i", silent, "-i", vo, "-af", af,
              "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ac", "2",
              "-shortest", "-movflags", "+faststart", final])

    # 5. SRT
    with open(os.path.join(sim.out, f"{sim.slug}.srt"), "w", encoding="utf8") as f:
        n, tt = 1, 0.0
        for sc in sim.scenes:
            if sc.narration.strip():
                a, b = tt, tt + sc._dur
                fm = lambda x: f"{int(x//3600):02d}:{int(x%3600//60):02d}:{x%60:06.3f}".replace(".", ",")
                f.write(f"{n}\n{fm(a)} --> {fm(b)}\n{sc.narration}\n\n"); n += 1
            tt += sc._dur

    va_, aa_ = _dur(silent), _dur(vo)
    if abs(va_ - aa_) > 0.12:
        raise RuntimeError(f"A/V length mismatch: video {va_:.2f}s vs audio {aa_:.2f}s. "
                           f"-shortest would silently drop the tail of the video.")
    rep = {"video": final, "cuts": cuts, "scenes": len(sim.scenes),
           "video_track_s": round(va_, 2), "audio_track_s": round(aa_, 2),
           "animated": sum(1 for c in cuts if c["animated"]),
           "duration_s": round(_dur(final), 2)}
    json.dump(rep, open(os.path.join(sim.out, "build_report.json"), "w"), indent=2)
    return rep
