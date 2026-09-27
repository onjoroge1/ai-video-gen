"""Opt-in Nature Short directing. No change to legacy directed pilots.

Owns measured beat timing, directed speech, fixed screen-space captions, and a
quiet original pulse bed. Paid calls use the existing durable stage ledger.
"""
from __future__ import annotations

import difflib
import json
import math
import re
import wave
from pathlib import Path

import numpy as np

VERSION = "nature_short_presentation_v2"


def narration_identity(text, voice, direction):
    return {"model": direction.tts_model, "voice": voice, "text": text,
            "instructions": direction.voice_instructions, "version": VERSION}


def narrate(text, output_path, voice, direction, ep):
    """Reuse only the same text, voice, model and acting direction."""
    from durable_execution import current, canonical_hash
    request = narration_identity(text, voice, direction)
    # Conservative reservation retained as the allowance in the local ledger;
    # the provider invoice remains authoritative for exact token-based billing.
    estimate = max(0.02, len(text) * 0.00003 + len(direction.voice_instructions) * 0.000001)

    def call(key=None):
        response = ep._openai().audio.speech.create(
            model=direction.tts_model, voice=voice, input=text,
            instructions=direction.voice_instructions, response_format="mp3",
            extra_headers={"Idempotency-Key": key} if key else None)
        with open(output_path, "wb") as handle:
            for chunk in response.iter_bytes():
                handle.write(chunk)
        # Use the reserved allowance in the ledger, never report unverified
        # provider invoice precision as actual token usage.
        return {"model": direction.tts_model, "accounting": "reserved_allowance"}, estimate

    runtime = current()
    if runtime:
        runtime.paid_file(stage_key="nature-tts:" + canonical_hash(request)[:32],
                          provider="openai-tts", request=request,
                          estimated_cost=estimate, output_path=output_path,
                          operation=lambda key: ep._retry(lambda: call(key), label="Nature TTS"))
    else:
        ep._retry(call, label="Nature TTS")
    return estimate


def measured_holds(shots, indexed_scenes, audio_paths, ep, maximum, minimum,
                   *, timing_notes=None):
    """Let speech own each beat; planning cadence limits are advisory after TTS."""
    durations = {s.scene_id: ep._audio_dur(p) for (_, s), p in zip(indexed_scenes, audio_paths)}
    planned = {}
    for shot in shots:
        planned[shot["scene_id"]] = planned.get(shot["scene_id"], 0) + shot["end_sec"] - shot["start_sec"]
    holds = []
    for shot in shots:
        sid = shot["scene_id"]
        if sid not in durations or planned[sid] <= 0:
            raise ValueError(f"Nature shot {shot['shot_id']} has no measured narration scene")
        hold = durations[sid] * (shot["end_sec"] - shot["start_sec"]) / planned[sid]
        if not math.isfinite(hold) or hold <= 0:
            raise ValueError(f"Nature shot {shot['shot_id']} has invalid measured narration duration")
        if not minimum <= hold <= maximum and timing_notes is not None:
            timing_notes.append({
                "shot_id": shot["shot_id"], "scene_id": sid,
                "measured_sec": round(hold, 3),
                "planning_min_sec": minimum, "planning_max_sec": maximum,
            })
        holds.append(hold)
    return holds


def caption_cues(text, words, duration):
    """Keep authored words; align matching tokens to measured speech, interpolate gaps."""
    tokens = text.split()
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    reference = [norm(w) for w in tokens]
    observed = [norm(str(w[0])) for w in words]
    aligned = {}
    for a, b, size in difflib.SequenceMatcher(None, reference, observed, autojunk=False).get_matching_blocks():
        for n in range(size):
            aligned[a+n] = (max(0., float(words[b+n][1])), min(duration, float(words[b+n][2])))
    quality = len(aligned) / max(1, len(tokens))
    cues = []
    for start in range(0, len(tokens), 3):
        end = min(start + 3, len(tokens))
        measured = [aligned[k] for k in range(start, end) if k in aligned]
        lo = measured[0][0] if measured else start / len(tokens) * duration
        hi = measured[-1][1] if measured else end / len(tokens) * duration
        # Permit a short readability tail without overlapping the next phrase.
        next_start = aligned.get(end, (end / len(tokens) * duration, 0))[0]
        hi = min(duration, max(hi, min(lo + .45, next_start)))
        if hi > lo:
            cues.append({"start": lo, "end": hi, "text": " ".join(tokens[start:end])})
    return cues, quality


def prepare_captions(indexed_scenes, audio_paths, ep, out):
    """Transcribe before image purchases, reusing durable results on continuation."""
    cues, quality, cursor = [], [], 0.
    for (_, scene), path in zip(indexed_scenes, audio_paths):
        duration = ep._audio_dur(path)
        words = ep.transcribe_words(path, strict=True)
        if not words:
            raise ValueError("Nature narration word timing unavailable; visuals not purchased")
        local, ratio = caption_cues(scene.narration, words, duration)
        cues.extend({**c, "start": c["start"]+cursor, "end": c["end"]+cursor} for c in local)
        quality.append({"scene_id": scene.scene_id, "matched_token_fraction": round(ratio, 3)})
        cursor += duration
    result = {"version": VERSION, "cues": cues, "alignment": quality,
              "estimated_cost_usd": len(indexed_scenes) * .006,
              "human_timing_review_required": any(q["matched_token_fraction"] < .9 for q in quality)}
    (Path(out) / "nature_captions.json").write_text(json.dumps(result, indent=2))
    return result


def _ass_time(seconds):
    ticks = max(0, round(seconds * 100))
    return f"{ticks//360000}:{ticks//6000%60:02}:{ticks//100%60:02}.{ticks%100:02}"


def _caption_text(text):
    # Authored content cannot inject ASS overrides or control characters.
    return re.sub(r"[{}\\\r\n]", " ", text).strip()


def write_ass(path, cues, tags, width, height):
    # Captions are rendered after all crop/zoom operations at delivery dimensions.
    # 84px is 4.4% of 1920; three words wrap inside a deliberately narrow safe box.
    size = round(height * .040)
    margin_l, margin_r = round(width*.10), round(width*.20)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Speech,DejaVu Sans,{size},&H00FFFFFF,&H0000D9FF,&H00101018,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,2,{margin_l},{margin_r},{round(height*.23)},1
Style: Tag,DejaVu Sans,{round(size*.72)},&H0000D9FF,&H0000D9FF,&H00101018,&H80000000,-1,0,0,0,100,100,0,0,1,3,0,8,{margin_l},{margin_r},{round(height*.10)},1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for style, group in [("Speech", cues), ("Tag", tags)]:
        for cue in group:
            lines.append(f"Dialogue: 0,{_ass_time(cue['start'])},{_ass_time(cue['end'])},{style},,0,0,0,,{_caption_text(cue['text'])}\n")
    # Abstract stored-energy graphic, deliberately no percentages or calibrated
    # quantities. It explains a changing resource instead of another seal pose.
    for tag in tags:
        mode = next((s for s in tag.get("labels",[]) if s.startswith("energy_")), None)
        if not mode:
            continue
        steps = 8
        for step in range(steps):
            lo = tag["start"] + (tag["end"]-tag["start"]) * step/steps
            hi = tag["start"] + (tag["end"]-tag["start"]) * (step+1)/steps
            amount = ((step+1)/steps if mode == "energy_fill" else
                      1-step/steps*.6 if mode == "energy_use" else
                      .4 if mode == "energy_low" else 1.)
            x,y,w,h = round(width*.22),round(height*.19),round(width*.45*amount),round(height*.012)
            vector = "{\\an7\\pos(%d,%d)\\p1\\bord0\\shad0\\c&H00D9FF&}m 0 0 l %d 0 %d %d 0 %d" % (x,y,w,w,h,h)
            lines.append(f"Dialogue: 1,{_ass_time(lo)},{_ass_time(hi)},Tag,,0,0,0,,{vector}\n")
    Path(path).write_text("".join(lines), encoding="utf-8")


def sound_bed(path, duration, scene_starts, quiet_spans=()):
    """Original quiet plucks/percussion, no stock music or fabricated animal calls."""
    sr = 24000
    samples = np.zeros(math.ceil(duration*sr), dtype=np.float32)
    # 116 BPM, understated major pentatonic pattern. The amplitude stays far below speech.
    for beat, start in enumerate(np.arange(0, duration, 60/116)):
        length = min(.30, duration-start)
        t = np.arange(max(0, int(length*sr))) / sr
        hz = [261.63, 329.63, 392., 440.][beat % 4]
        level = .008 if any(a <= start < b for a,b in quiet_spans) else .032
        note = level*np.sin(2*np.pi*hz*t)*np.exp(-t*16)
        idx = int(start*sr); samples[idx:idx+len(note)] += note
    # Short change accents, spaced by actual narration boundaries.
    for start in scene_starts[1:]:
        n = min(int(.12*sr), len(samples)-int(start*sr))
        if n <= 0: continue
        t = np.arange(n)/sr
        level = .01 if any(a <= start < b for a,b in quiet_spans) else .04
        samples[int(start*sr):int(start*sr)+n] += level*np.sin(2*np.pi*(500*t+900*t*t))*np.exp(-t*35)
    fade = min(sr//2, len(samples)//2)
    if fade:
        samples[:fade] *= np.linspace(0,1,fade); samples[-fade:] *= np.linspace(1,0,fade)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(sr)
        handle.writeframes((np.clip(samples,-1,1)*32767).astype('<i2').tobytes())


def final_treatment(preview, out, spec, shots, holds, captions, scene_starts, ep):
    width, height = 1080, 1920
    tags, cursor = [], 0.
    for shot, hold in zip(shots, holds):
        if shot.get("overlay_text"):
            tags.append({"start":cursor,"end":cursor+hold,"text":shot["overlay_text"],
                         "labels":shot.get("labels",[])})
        cursor += hold
    ass = Path(out)/"nature_captions.ass"
    write_ass(ass, captions["cues"], tags, width, height)
    bed = Path(out)/"nature_pulse.wav"
    temp = str(preview)+".treated.mp4"
    args = [ep._ffmpeg_bin(),"-nostdin","-y","-i",preview]
    if spec.nature_short.sound_bed != "none":
        ends = scene_starts[1:]+[cursor]
        quiet_spans = [(a,b) for scene,a,b in zip(spec.narration,scene_starts,ends)
                       if scene.story_role == "limitation"]
        sound_bed(bed, cursor, scene_starts, quiet_spans)
        args += ["-i",str(bed),"-filter_complex",
                 "[0:a]loudnorm=I=-16:TP=-2:LRA=8[vo];[vo][1:a]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]",
                 "-map","0:v","-map","[a]"]
    else:
        args += ["-map","0:v","-map","0:a","-af","loudnorm=I=-16:TP=-2:LRA=8"]
    # Escape characters significant in ffmpeg's subtitles filter path parser.
    escaped = str(ass).replace("\\", "\\\\").replace(":", "\\:").replace("'", "'\\''")
    args += ["-vf",f"ass=filename='{escaped}'","-c:v","libx264","-preset","veryfast","-crf","20",
             "-c:a","aac","-b:a","160k","-movflags","+faststart",temp]
    ep._run_ffmpeg(args)
    Path(temp).replace(preview)
    bed.unlink(missing_ok=True)
    return {"version":VERSION, "captions":"post-composition ASS",
            "sound_bed":spec.nature_short.sound_bed, "tts_model":spec.nature_short.tts_model,
            "caption_alignment":captions["alignment"],
            "human_timing_review_required":captions["human_timing_review_required"]}
