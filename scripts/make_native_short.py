#!/usr/bin/env python3
"""Build a native 9:16 Short from a spec: its own narration and its own vertical pictures.

    python3 scripts/make_native_short.py jobs/elephants-foot/shorts/what_is_the_foot/spec.json

The companion teaser (make_teaser_short.py) cuts the film's first minute and crops its 16:9
stills to 9:16. The crops lose the subject, and every teaser opens the same way. A native Short
is written for the feed instead: an alternative version of the film's opening, or an explainer
of one thing the film names. Each line is voiced on its own in the narrator's voice, so every
picture starts on its line, and every line gets a picture drawn at 2:3 for the vertical frame.

Spec (JSON):
    {"title": "What Is Chernobyl's Elephant's Foot?", "headline": "ELEPHANT'S|FOOT",
     "film_id": "79RsZfVaxJI", "style": "<visual style for every picture>",
     "beats": [{"text": "<one or two sourced sentences>", "image": "<one picture>"}, ...],
     "cta": "The full story is in the film linked below.", "voice": "echo",
     "description": "<two or three lines>", "tags": ["..."]}

Optional keys for the opening (scripts/shorts_hook.py): "turn" is the index of the beat where the
story turns (a riser runs into it and a low hit lands on it; a hit also lands on the first word),
"music" is a music_assets mood ("tense" by default, "" for none), and "emphasis" lists extra
words to colour in the captions. Line 1 is the hook: at most ten words, no scene-setting preamble,
no year or person's name. The opening cuts every 1.3 s or faster, captions show one or two words
at a time in the middle of the frame, and the mix plays at -14 LUFS. The gate checks the rendered
file; a failed check still writes the Short but exits 2. hook_sheet.jpg (first 3 s at 2 fps) and
cover.jpg (frame 0, the picture the Shorts tab shows) are written for review.

Writes short.mp4, package.json and the pictures next to the spec. Pictures and line audio that
already exist are reused, so a re-run after an edit buys only what changed. Uploading is a
separate, explicit step (scripts/youtube_upload.py --short).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import make_teaser_short as mts  # noqa: E402
import shorts_hook as sh  # noqa: E402

BEAT_GAP_SEC = 0.12           # breath between lines
IMAGE_SIZE = "1024x1536"      # 2:3, the vertical frame's own shape before the 9:16 window

VERTICAL_RULES = ("Vertical 2:3 composition for a phone screen: ONE large subject filling the middle of the "
                  "frame, simple background, strong contrast, readable at a glance. Keep the top 15% and the "
                  "bottom 25% calm for captions. Absolutely no text, letters, numbers, logos or watermarks. "
                  "No gore. People are anonymous, never recognizable real people.")


def beat_timeline(durations: list[float], gap: float = BEAT_GAP_SEC) -> list[dict]:
    """Start and end of each line on the narration track: lines back to back with a short gap."""
    out, t = [], 0.0
    for d in durations:
        out.append({"start": round(t, 3), "end": round(t + d, 3)})
        t += d + gap
    return out


def picture_prompt(style: str, image: str) -> str:
    return f"{style.strip()} {image.strip().rstrip('.')}. {VERTICAL_RULES}"


def _key(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()[:12]


def _tts(text: str, voice: str, out: str) -> str:
    if os.path.isfile(out):
        return out
    from openai import OpenAI
    resp = OpenAI().audio.speech.create(model="tts-1-hd", voice=voice, input=text, response_format="mp3")
    with open(out, "wb") as handle:
        for chunk in resp.iter_bytes():
            handle.write(chunk)
    return out


def _picture(prompt: str, out: str) -> str:
    if os.path.isfile(out):
        return out
    # The same prompt at another line (a visual callback: the last line returns to the first
    # picture) is the same picture, not a second, slightly different drawing.
    import glob
    import shutil
    key = os.path.basename(out).split("_", 2)[-1]
    same = sorted(glob.glob(os.path.join(os.path.dirname(out), f"pic_*_{key}")))
    if same:
        shutil.copy(same[0], out)
        return out
    from openai import OpenAI
    reply = OpenAI().images.generate(model="gpt-image-2", prompt=prompt, size=IMAGE_SIZE, quality="high", n=1)
    with open(out, "wb") as handle:
        handle.write(base64.b64decode(reply.data[0].b64_json))
    try:
        import explainer_pipeline as ep
        usd = ep._image_cost_from_usage(reply)
    except Exception:  # noqa: BLE001 - the ledger line is a report, never a reason to fail a build
        usd = None
    with open(os.path.join(os.path.dirname(out), "picture_costs.jsonl"), "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"picture": os.path.basename(out), "usd": usd}) + "\n")
    return out


def _concat_audio(parts: list[str], gap: float, out: str) -> None:
    """The lines in order with a short silence between them, as one track."""
    fmt = "aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo"
    cmd, chain, labels = [mts._ffmpeg_bin(), "-v", "error", "-y"], [], []
    for p in parts:
        cmd += ["-i", p]
    for i in range(len(parts)):
        chain.append(f"[{i}:a]{fmt}[a{i}]")
        labels.append(f"[a{i}]")
        if i < len(parts) - 1:
            chain.append(f"anullsrc=r=44100:cl=stereo,atrim=0:{gap},{fmt}[g{i}]")
            labels.append(f"[g{i}]")
    chain.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[out]")
    cmd += ["-filter_complex", ";".join(chain), "-map", "[out]", "-c:a", "libmp3lame", "-q:a", "2", out]
    mts._run(cmd)


def hold_opening(shots: list[dict], sec: float, min_shot: float = 0.4) -> list[dict]:
    """Keep a moving first shot on screen for `sec` seconds (spec "open_hold_sec", 11-10 test).
    Later pictures that would open inside the hold start at its end instead; one left shorter
    than `min_shot` is dropped rather than flashed. A still first shot is left alone."""
    if not sec or not shots or not shots[0].get("motion"):
        return shots
    hold = max(shots[0]["end"], sec)
    out = [dict(shots[0], end=hold)]
    for shot in shots[1:]:
        shot = dict(shot, start=max(shot["start"], hold))
        if shot["end"] - shot["start"] >= min_shot:
            out.append(shot)
    for a, b in zip(out, out[1:]):    # a dropped flash's time goes to the picture after it
        b["start"] = a["end"]
    out[-1]["end"] = max(out[-1]["end"], shots[-1]["end"])
    return out


def build(spec_path: str) -> dict:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.expanduser("~/ai-video-gen-local"), ".env"))
    load_dotenv(os.path.join(ROOT, ".env"))
    spec = json.load(open(spec_path, encoding="utf-8"))
    here = os.path.dirname(os.path.abspath(spec_path))
    voice = spec.get("voice") or mts.CTA_VOICE
    beats = spec["beats"]

    lines = [_tts(b["text"], voice, os.path.join(here, f"line_{i:02d}_{_key(voice, b['text'])}.mp3"))
             for i, b in enumerate(beats)]
    # A line may carry several pictures: "pictures": [{"image": ...}, {"from": "word", "image": ...}],
    # each later one opening on the named word of the line (operator 10-28: a new drawing every
    # 2-2.5 s instead of re-cropping one drawing for a whole line).
    per_line = [b.get("pictures") or [{"image": b["image"]}] for b in beats]
    multi = any(len(ps) > 1 for ps in per_line)
    line_pictures = [[_picture(picture_prompt(spec["style"], pic["image"]),
                               os.path.join(here, f"pic_{i:02d}{'' if j == 0 else chr(96 + j)}_"
                                                  f"{_key(spec['style'], pic['image'])}.png"))
                      for j, pic in enumerate(ps)] for i, ps in enumerate(per_line)]
    pictures = [p for ps in line_pictures for p in ps]
    times = beat_timeline([mts._duration(p) for p in lines])
    until = times[-1]["end"]

    shots = []
    for i, t in enumerate(times):
        line_end = times[i + 1]["start"] if i + 1 < len(times) else until
        starts = [t["start"]]
        if len(per_line[i]) > 1:
            words, _ = sh.words_for_line(lines[i], beats[i]["text"], t["start"])
            starts = sh.picture_cuts(words, t["start"], [pic.get("from") for pic in per_line[i]])
        for j, img in enumerate(line_pictures[i]):
            shots.append({"start": starts[j], "end": starts[j + 1] if j + 1 < len(starts) else line_end,
                          "image": img, "beat": i, "inserted": True,
                          **({"motion": per_line[i][j]["motion"]} if per_line[i][j].get("motion") else {})})
    shots = hold_opening(shots, float(spec.get("open_hold_sec") or 0))
    # The baseline is the 10-17 renderer that made the pythons Short the operator chose (10-26):
    # clean voice, no music, three-to-four-word caption chips. The opening package is opt-in with
    # "package": "hook_v2"; its sound (compressed voice, music bed, synthetic hits) was judged worse.
    # "package": "hook" keeps the baseline sound and captions and changes only the opening: the hook
    # line rules and a new framing every 1.3 s or faster in the first five seconds.
    package = spec.get("package") or "hook"
    v2 = package == "hook_v2"
    hook = package in ("hook", "hook_v2")
    if multi:
        shots = sh.frame_drawn(shots)    # every cut is a new drawing: no re-crops of one picture
    else:
        shots = sh.frame_drawn(sh.hook_shots(shots) if hook else mts.split_long(shots, mts.MAX_HOLD))
    words, matched = [], [1.0]
    if v2:
        matched = []
        for line, t, b in zip(lines, times, beats):
            w, m = sh.words_for_line(line, b["text"], t["start"])
            words += w
            matched.append(m)
        captions = sh.word_chunks(words, until)
    else:
        cues = [{"start": t["start"], "end": t["end"], "text": b["text"]} for t, b in zip(times, beats)]
        captions = [(p["start"], p["end"], p["text"].split()) for p in mts._phrases(cues, until)]
    emphasis = {str(w).lower() for w in spec.get("emphasis") or []}
    turn = spec.get("turn")
    turn_at = times[int(turn)]["start"] if turn is not None else None
    out_path = os.path.join(here, "short.mp4")

    music, music_credit = "", ""
    if v2 and spec.get("music", "tense"):
        import music_assets
        music = music_assets.get_music_path(spec.get("music", "tense")) or ""
        music_credit = music_assets.MUSIC_CREDIT if music else ""

    with tempfile.TemporaryDirectory(prefix="native_short_") as tmp:
        narration = os.path.join(tmp, "narration.mp3")
        _concat_audio(lines, BEAT_GAP_SEC, narration)
        base = os.path.join(tmp, "base.mp4")
        (sh.render_drawn if all("path" in x for x in shots) else mts._reframe_video)(shots, base, tmp)
        for shot in shots:
            if shot.get("motion"):
                shot["motion_clip"] = sh.animate_picture(shot["image"], shot["motion"])
        base = sh.overlay_moving(base, shots, os.path.join(tmp, "base_moving.mp4"))
        cta_mp3, cta_sec = "", 0.0
        if (spec.get("cta") or "").strip():
            cta_mp3 = mts._spoken_cta(spec["cta"].strip(), os.path.join(tmp, "cta.mp3"), voice=voice)
            cta_sec = mts._duration(cta_mp3)
        timeline = mts.cta_timeline(until, cta_sec)
        # A Short with no film to point at (a topic test) says nothing after its payoff and holds
        # an on-screen card instead: "end_card": [["SUBSCRIBE"], ["MORE", "DECISIONS"], ...].
        card_lines = spec.get("end_card")
        if card_lines and not cta_sec:
            hold = float(spec.get("end_card_hold", 1.5))
            timeline = {"cta_start": until, "total": round(until + hold, 3), "end_card_at": until}
        voice_track = os.path.join(tmp, "voice.m4a")
        mts._audio(narration, until, voice_track, cta_mp3)
        if v2:
            hits = [0.0] + ([turn_at] if turn_at else [])
            audio = sh.mix(voice_track, timeline["total"], os.path.join(tmp, "mix.wav"), tmp, music=music,
                           hits=hits, risers_to=[turn_at] if turn_at else [])["path"]
        else:
            audio = voice_track
        if timeline["total"] > until:
            held = os.path.join(tmp, "base_held.mp4")
            mts._run([mts._ffmpeg_bin(), "-v", "error", "-y", "-i", base, "-vf",
                      f"tpad=stop_mode=clone:stop_duration={timeline['total'] - until + 0.1:.3f}",
                      "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", held])
            base = held

        overlays = []
        head_png = os.path.join(tmp, "headline.png")
        headline = spec.get("headline") or ""
        size = next((s for s in (92, 84, 76, 70) if len(mts._headline_lines(headline, s)) <= 2), 70)
        mts._text_png(head_png, mts._headline_lines(headline, size), size=size, y=150, stroke=10)
        overlays.append((head_png, 0.0, timeline["total"]))
        end_at = timeline["end_card_at"]
        cap_y = mts.H - mts.SAFE_BOTTOM - 260
        probe = mts.ImageDraw.Draw(mts.Image.new("RGBA", (mts.W, mts.H)))
        for i, (start, end, group) in enumerate(c for c in captions if c[0] < end_at):
            png = os.path.join(tmp, f"cap_{i:03d}.png")
            if v2:
                sh.caption_png(png, group, emphasis)
            else:
                wrapped = mts._wrap(probe, " ".join(group).upper(), mts._font(68), mts.W - 160)
                mts._text_png(png, [[(w, mts.WHITE) for w in ln.split()] for ln in wrapped[:3]],
                              size=68, y=cap_y, stroke=7, pill=True)
            overlays.append((png, start, min(end, end_at)))
        end_png = os.path.join(tmp, "end.png")
        card = card_lines or [[w for w, _ in ln] for ln in mts.END_CARD_LINES]
        mts._text_png(end_png, [[(w, mts.YELLOW if n == 0 else mts.WHITE) for w in ln]
                                for n, ln in enumerate(card)],
                      size=84, y=cap_y - 40 - 90 * (len(card) - 2), stroke=9, pill=True)
        overlays.append((end_png, end_at, timeline["total"]))
        cmd = [mts._ffmpeg_bin(), "-v", "error", "-y", "-i", base, "-i", audio]
        for png, _, _ in overlays:
            cmd += ["-i", png]
        chain, prev = [], "[0:v]"
        for k, (_, start, end) in enumerate(overlays):
            chain.append(f"{prev}[{k + 2}:v]overlay=0:0:enable='between(t,{start:.3f},{end:.3f})'[v{k}]")
            prev = f"[v{k}]"
        cmd += ["-filter_complex", ";".join(chain), "-map", prev, "-map", "1:a", "-c:v", "libx264",
                "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(mts.FPS)]
        cmd += (["-c:a", "aac", "-b:a", "192k"] if v2 else ["-c:a", "copy"])
        cmd += [ "-movflags", "+faststart", "-t", f"{timeline['total']:.3f}", out_path]
        mts._run(cmd)

    level = sh.loudness(out_path)
    checks = sh.gate(beats[0]["text"], shots, captions, level, timeline["total"], beats[-1]["text"]) if v2 else {}
    if package == "hook":
        checks = {k: v for k, v in sh.gate(beats[0]["text"], shots, captions, level, timeline["total"], beats[-1]["text"],
                                           hold_max=sh.PICTURE_HOLD if multi else sh.SHOT_HOLD,
                                           max_duration=float(spec.get("max_duration", 45.0))).items()
                  if k in ("hook_rules", "hook_warnings", "first_cut_le_1_5s", "cuts_in_first_5s_ge_3", "longest_hold_le_2s",
                           "duration_20_to_45s")}
    sh.hook_sheet(out_path, os.path.join(here, "hook_sheet.jpg"), os.path.join(here, "cover.jpg"))

    film = spec.get("film_id")
    description = "\n\n".join(part for part in (
        f"Full film: https://youtu.be/{film}" if film else "", (spec.get("description") or "").strip(),
        music_credit, "#Shorts") if part)
    package = {"short": out_path, "title": spec["title"], "description": description,
               "tags": spec.get("tags") or [], "duration": timeline["total"], "narration_sec": until,
               "lines": len(beats), "pictures": len(pictures), "shots": len(shots),
               "longest_hold": round(max(s["end"] - s["start"] for s in shots), 2),
               "end_card_at": timeline["end_card_at"], "film_id": film, "music": os.path.basename(music),
               "loudness": level, "caption_alignment": round(min(matched), 3),
               "package": package,
               "gate": {k: [v, ok] for k, (v, ok) in checks.items()}, "gate_pass": sh.gate_passed(checks)}
    with open(os.path.join(here, "package.json"), "w", encoding="utf-8") as handle:
        json.dump(package, handle, indent=1, ensure_ascii=False)
    return package


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("spec")
    args = ap.parse_args(argv)
    package = build(args.spec)
    print(json.dumps({k: package[k] for k in ("short", "title", "duration", "pictures", "shots", "longest_hold",
                                              "loudness", "gate", "gate_pass")}, indent=1, ensure_ascii=False))
    return 0 if package["gate_pass"] else 2


if __name__ == "__main__":
    sys.exit(main())
