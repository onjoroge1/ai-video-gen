"""Opt-in Nature Short directing. No change to legacy directed pilots.

Owns measured beat timing, directed speech, fixed screen-space captions, and a
quiet original pulse bed. Paid calls use the existing durable stage ledger.
"""
from __future__ import annotations

import difflib
import json
import math
import re
import shutil
import textwrap
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

VERSION = "nature_short_presentation_v2"
V3_VERSION = "nature_short_presentation_v3"


def _presentation_version(direction):
    if getattr(direction, "version", "") == "nature_short_v4":
        return "nature_short_presentation_v4"
    return V3_VERSION if getattr(direction, "version", "") in {"nature_short_v3", "nature_short_v4"} else VERSION


def narration_identity(text, voice, direction):
    return {"model": direction.tts_model, "voice": voice, "text": text,
            "instructions": direction.voice_instructions,
            "version": _presentation_version(direction)}


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
    def pieces(value):
        return re.findall(r"[a-z0-9]+", value.lower())
    reference, owners = [], []
    for i, token in enumerate(tokens):
        parts = pieces(token)
        reference.extend(parts); owners.extend([i] * len(parts))
    observed, observed_times = [], []
    for word, start, end in words:
        parts = pieces(str(word))
        observed.extend(parts); observed_times.extend([(start, end)] * len(parts))
    matches = {}
    for a, b, size in difflib.SequenceMatcher(None, reference, observed, autojunk=False).get_matching_blocks():
        for n in range(size):
            matches[a+n] = observed_times[b+n]
    aligned = {}
    for i in range(len(tokens)):
        indices = [j for j, owner in enumerate(owners) if owner == i]
        if indices and all(j in matches for j in indices):
            aligned[i] = (max(0., float(matches[indices[0]][0])),
                          min(duration, float(matches[indices[-1]][1])))
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


def prepare_captions(indexed_scenes, audio_paths, ep, out, direction=None):
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
    result = {"version": _presentation_version(direction), "cues": cues, "alignment": quality,
              "estimated_cost_usd": len(indexed_scenes) * .006,
              "human_timing_review_required": any(q["matched_token_fraction"] < .9 for q in quality)}
    (Path(out) / "nature_captions.json").write_text(json.dumps(result, indent=2))
    if getattr(direction, "version", "") == "nature_short_v4" and result["human_timing_review_required"]:
        raise ValueError("Nature caption alignment needs repair before image spending; see nature_captions.json")
    return result


def _font(size, *, bold=False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default()


def _wrapped(draw, xy, text, *, width, font, fill, spacing=8):
    x, y = xy
    approx = max(12, int(width / max(7, getattr(font, "size", 18) * .56)))
    for line in textwrap.wrap(str(text or "—"), width=approx):
        draw.text((x, y), line, font=font, fill=fill)
        box = draw.textbbox((x, y), line, font=font)
        y += max(20, box[3] - box[1]) + spacing
    return y


def render_storyboard_animatic(spec, shots, holds, indexed_scenes, audio_paths, out, ep):
    """Render the authoritative V3 board over final measured narration before image spend."""
    import nature_retention_storyboard as nrs
    report = nrs.score_directed_spec(spec.model_dump(mode="json"))
    report["measured_narration_sec"] = round(sum(ep._audio_dur(path) for path in audio_paths), 3)
    report["measured_shot_holds_sec"] = [round(float(value), 3) for value in holds]
    report_path = Path(out) / "nature_storyboard_gate.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if not report.get("passed"):
        raise ValueError("Nature retention storyboard failed before visual spending")

    board = spec.nature_short.retention_storyboard.model_dump(mode="json")
    row_by_id = {row["shot_id"]: row for row in board["shots"]}
    scene_by_id = {scene.scene_id: scene for _, scene in indexed_scenes}
    root = Path(out) / "nature_animatic_cards"
    root.mkdir(parents=True, exist_ok=True)
    clips = []
    mode_colors = {
        "grounded_action": "#12344b", "macro_evidence": "#41215c",
        "science_diagram": "#17433c", "time_transition": "#4a3423",
        "scale_comparison": "#3f2949", "payoff": "#69411c",
    }
    for index, (shot, hold) in enumerate(zip(shots, holds)):
        row = row_by_id[shot["shot_id"]]
        image_path = root / f"card_{index:03d}.jpg"
        clip_path = root / f"card_{index:03d}.mp4"
        image = Image.new("RGB", (540, 960), mode_colors.get(row["visual_mode"], "#182235"))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((24, 24, 516, 936), radius=24, fill="#0b1220", outline="#35d9c5", width=3)
        draw.text((48, 48), f"SHOT {index + 1:02d}  ·  {hold:.2f}s",
                  font=_font(24, bold=True), fill="#35d9c5")
        draw.text((48, 92), f"{row['visual_mode'].replace('_', ' ').upper()}  /  {row['shot_scale'].upper()}",
                  font=_font(17, bold=True), fill="#fbbf24")
        y = _wrapped(draw, (48, 146), row["dominant_action"], width=444,
                     font=_font(32, bold=True), fill="white", spacing=10)
        y = _wrapped(draw, (48, y + 20), "CHANGE: " + row["state_change"], width=444,
                     font=_font(20), fill="#cbd5e1")
        y = _wrapped(draw, (48, y + 20), "PAYOFF: " + row["mini_payoff"], width=444,
                     font=_font(20, bold=True), fill="#fbbf24")
        scene = scene_by_id.get(shot.get("scene_id"))
        _wrapped(draw, (48, min(800, y + 28)), "VO: " + (scene.narration if scene else ""),
                 width=444, font=_font(16), fill="#94a3b8", spacing=5)
        image.save(image_path, "JPEG", quality=88)
        ep._run_ffmpeg([
            ep._ffmpeg_bin(), "-nostdin", "-y", "-loop", "1", "-i", str(image_path),
            "-t", f"{float(hold):.6f}", "-vf", "fps=24,format=yuv420p",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-an", str(clip_path),
        ], timeout=120.0)
        clips.append(clip_path)

    video_list = root / "video_segments.txt"
    video_list.write_text("".join(f"file '{path.as_posix()}'\n" for path in clips), encoding="utf-8")
    audio_list = root / "audio_segments.txt"
    audio_list.write_text("".join(f"file '{Path(path).as_posix()}'\n" for path in audio_paths), encoding="utf-8")
    preview = Path(out) / "nature_animatic_preview.mp4"
    ep._run_ffmpeg([
        ep._ffmpeg_bin(), "-nostdin", "-y",
        "-f", "concat", "-safe", "0", "-i", str(video_list),
        "-f", "concat", "-safe", "0", "-i", str(audio_list),
        "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
        "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(preview),
    ], timeout=180.0)
    shutil.rmtree(root, ignore_errors=True)
    return {"report": report, "report_path": str(report_path), "preview_path": str(preview)}


def _visual_signature(path):
    with Image.open(path) as source:
        image = source.convert("RGB").resize((48, 84))
    rgb = np.asarray(image, dtype=np.float32) / 255.0
    gray = rgb.mean(axis=2)
    centered = gray - gray.mean()
    norm = float(np.linalg.norm(centered))
    structure = centered / norm if norm > 1e-8 else centered
    edge = np.concatenate((np.diff(gray, axis=0).ravel(), np.diff(gray, axis=1).ravel()))
    edge_norm = float(np.linalg.norm(edge))
    edge = edge / edge_norm if edge_norm > 1e-8 else edge
    histogram = np.concatenate([
        np.histogram(rgb[:, :, channel], bins=12, range=(0, 1), density=True)[0]
        for channel in range(3)
    ]).astype(np.float32)
    histogram /= max(1e-8, float(np.linalg.norm(histogram)))
    return rgb.ravel(), structure.ravel(), edge, histogram


def _visual_similarity(left, right):
    a_rgb, a_structure, a_edge, a_hist = left
    b_rgb, b_structure, b_edge, b_hist = right
    mean_absolute_error = float(np.mean(np.abs(a_rgb - b_rgb)))
    appearance = 1.0 - mean_absolute_error
    structure = float(np.clip(np.dot(a_structure, b_structure), -1, 1))
    edge = float(np.clip(np.dot(a_edge, b_edge), -1, 1))
    histogram = float(np.clip(np.dot(a_hist, b_hist), 0, 1))
    combined = .35 * appearance + .30 * structure + .15 * edge + .20 * histogram
    # Exact or almost exact exports may be flat diagrams, where demeaned structure/edges have no
    # energy. Pixel agreement must still identify those copies instead of scoring them as diverse.
    near_copy = 1.0 - min(1.0, mean_absolute_error * 3.0)
    return round(max(0.0, combined, near_copy), 4)


def preflight_visual_diversity(image_paths, shots, out, threshold):
    """Reject near-duplicate generated compositions before any motion provider call."""
    paths = [str(path) for path in image_paths]
    signatures = [_visual_signature(path) for path in paths]

    def continuity_group(shot):
        prefix = "continuity_group:"
        return next((str(label)[len(prefix):] for label in shot.get("labels", [])
                     if str(label).startswith(prefix) and str(label)[len(prefix):]), "")

    def intentional_pair(left, right):
        group = continuity_group(shots[left])
        return bool(group and group == continuity_group(shots[right]))

    adjacent = []
    for index in range(1, len(paths)):
        similarity = _visual_similarity(signatures[index - 1], signatures[index])
        intentional = intentional_pair(index - 1, index)
        adjacent.append({
            "left": shots[index - 1]["shot_id"], "right": shots[index]["shot_id"],
            "similarity": similarity, "intentional_continuity": intentional,
            "failed": similarity >= threshold and not intentional,
        })
    duplicate_pairs = []
    duplicate_threshold = min(.995, threshold + .02)
    for left in range(len(paths)):
        for right in range(left + 2, len(paths)):
            similarity = _visual_similarity(signatures[left], signatures[right])
            if similarity >= duplicate_threshold and not intentional_pair(left, right):
                duplicate_pairs.append({
                    "left": shots[left]["shot_id"], "right": shots[right]["shot_id"],
                    "similarity": similarity,
                })

    thumb_w, thumb_h, columns = 216, 384, 5
    rows = math.ceil(len(paths) / columns)
    sheet = Image.new("RGB", (columns * thumb_w, rows * (thumb_h + 34)), "#0b1220")
    draw = ImageDraw.Draw(sheet)
    for index, (path, shot) in enumerate(zip(paths, shots)):
        with Image.open(path) as source:
            image = source.convert("RGB")
        image.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        x, y = (index % columns) * thumb_w, (index // columns) * (thumb_h + 34)
        sheet.paste(image, (x + (thumb_w - image.width) // 2, y))
        draw.rectangle((x, y + thumb_h, x + thumb_w, y + thumb_h + 34), fill="#111827")
        draw.text((x + 8, y + thumb_h + 8), shot["shot_id"], font=_font(15, bold=True), fill="white")
    contact_path = Path(out) / "nature_preflight_contact_sheet.jpg"
    sheet.save(contact_path, "JPEG", quality=88)

    failed_adjacent = [item for item in adjacent if item["failed"]]
    # One deliberate non-adjacent callback can be valuable. Two or more near-duplicate pairs are
    # a visual system reverting to one composition and must stop before motion spend.
    report = {
        "version": "nature_visual_diversity_v1",
        "passed": not failed_adjacent and len(duplicate_pairs) <= 1,
        "threshold": threshold,
        "duplicate_threshold": duplicate_threshold,
        "adjacent_pairs": adjacent,
        "failed_adjacent_pairs": failed_adjacent,
        "nonadjacent_near_duplicates": duplicate_pairs,
        "contact_sheet_path": str(contact_path),
        "repair": ("Regenerate only the failed stills with a different composition, scale, location or visual mode."
                   if failed_adjacent or len(duplicate_pairs) > 1 else ""),
    }
    report_path = Path(out) / "nature_visual_diversity_gate.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


def _ass_time(seconds):
    ticks = max(0, round(seconds * 100))
    return f"{ticks//360000}:{ticks//6000%60:02}:{ticks//100%60:02}.{ticks%100:02}"


def _caption_text(text):
    # Authored content cannot inject ASS overrides or control characters.
    return re.sub(r"[{}\\\r\n]", " ", text).strip()


def write_ass(path, cues, tags, width, height, font_name="DejaVu Sans"):
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
Style: Speech,{font_name},{size},&H00FFFFFF,&H0000D9FF,&H00101018,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,2,{margin_l},{margin_r},{round(height*.23)},1
Style: Tag,{font_name},{round(size*.72)},&H0000D9FF,&H0000D9FF,&H00101018,&H80000000,-1,0,0,0,100,100,0,0,1,3,0,8,{margin_l},{margin_r},{round(height*.10)},1
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
    from nature_render_quality import prepare_font, ass_filter, verify_captions
    fonts, font_name = prepare_font(out)
    write_ass(ass, captions["cues"], tags, width, height, font_name=font_name)
    bed = Path(out)/"nature_pulse.wav"
    temp = str(preview)+".treated.mp4"
    args = [ep._ffmpeg_bin(),"-nostdin","-y","-i",preview]
    if spec.nature_short.sound_bed != "none":
        ends = scene_starts[1:]+[cursor]
        quiet_spans = [(a,b) for scene,a,b in zip(spec.narration,scene_starts,ends)
                       if scene.story_role == "limitation"]
        if spec.nature_short.version in {"nature_short_v3", "nature_short_v4"}:
            # V3 uses structural sound changes: a short breath before the hatch/climax and a
            # quieter final reinterpretation. Constant pulse through the emotional turn was one
            # of the octopus v1 retention failures.
            quiet_spans.extend(
                (a, min(b, a + .45))
                for scene, a, b in zip(spec.narration, scene_starts, ends)
                if scene.story_role == "consequence"
            )
            quiet_spans.extend(
                (a, b) for scene, a, b in zip(spec.narration, scene_starts, ends)
                if scene.story_role == "reinterpretation"
            )
        sound_bed(bed, cursor, scene_starts, quiet_spans)
        args += ["-i",str(bed),"-filter_complex",
                 "[0:a]loudnorm=I=-16:TP=-2:LRA=8[vo];[vo][1:a]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]",
                 "-map","0:v","-map","[a]"]
    else:
        args += ["-map","0:v","-map","0:a","-af","loudnorm=I=-16:TP=-2:LRA=8"]
    args += ["-vf",ass_filter(ass, fonts),"-c:v","libx264","-preset","veryfast","-crf","20",
             "-c:a","aac","-b:a","160k","-movflags","+faststart",temp]
    ep._run_ffmpeg(args)
    visibility = verify_captions(preview, temp, ass, fonts, captions["cues"], scene_starts, ep, out)
    if not visibility["passed"]:
        raise RuntimeError("Nature captions are absent from encoded pixels; caption visibility report saved")
    Path(temp).replace(preview)
    bed.unlink(missing_ok=True)
    return {"version":_presentation_version(spec.nature_short), "captions":"post-composition ASS",
            "sound_bed":spec.nature_short.sound_bed, "tts_model":spec.nature_short.tts_model,
            "caption_alignment":captions["alignment"],
            "human_timing_review_required":captions["human_timing_review_required"],
            "caption_visibility":visibility}
