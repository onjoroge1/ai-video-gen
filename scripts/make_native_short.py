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
import make_teaser_short as mts  # noqa: E402

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
    from openai import OpenAI
    reply = OpenAI().images.generate(model="gpt-image-2", prompt=prompt, size=IMAGE_SIZE, quality="high", n=1)
    with open(out, "wb") as handle:
        handle.write(base64.b64decode(reply.data[0].b64_json))
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
    pictures = [_picture(picture_prompt(spec["style"], b["image"]),
                         os.path.join(here, f"pic_{i:02d}_{_key(spec['style'], b['image'])}.png"))
                for i, b in enumerate(beats)]
    times = beat_timeline([mts._duration(p) for p in lines])
    until = times[-1]["end"]

    shots = [{"start": t["start"], "end": (times[i + 1]["start"] if i + 1 < len(times) else until),
              "image": pictures[i], "inserted": True} for i, t in enumerate(times)]
    shots = mts.assign_framing(mts.split_long(shots, mts.MAX_HOLD))
    cues = [{"start": t["start"], "end": t["end"], "text": b["text"]} for t, b in zip(times, beats)]
    phrases = mts._phrases(cues, until)
    out_path = os.path.join(here, "short.mp4")

    with tempfile.TemporaryDirectory(prefix="native_short_") as tmp:
        narration = os.path.join(tmp, "narration.mp3")
        _concat_audio(lines, BEAT_GAP_SEC, narration)
        base = os.path.join(tmp, "base.mp4")
        mts._reframe_video(shots, base, tmp)
        cta_mp3, cta_sec = "", 0.0
        if (spec.get("cta") or "").strip():
            cta_mp3 = mts._spoken_cta(spec["cta"].strip(), os.path.join(tmp, "cta.mp3"), voice=voice)
            cta_sec = mts._duration(cta_mp3)
        timeline = mts.cta_timeline(until, cta_sec)
        audio = os.path.join(tmp, "audio.m4a")
        mts._audio(narration, until, audio, cta_mp3)
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
        cap_y = mts.H - mts.SAFE_BOTTOM - 260
        end_at = timeline["end_card_at"]
        probe = mts.ImageDraw.Draw(mts.Image.new("RGBA", (mts.W, mts.H)))
        for i, ph in enumerate(p for p in phrases if p["start"] < end_at):
            png = os.path.join(tmp, f"cap_{i:03d}.png")
            wrapped = mts._wrap(probe, ph["text"].upper(), mts._font(68), mts.W - 160)
            mts._text_png(png, [[(w, mts.WHITE) for w in ln.split()] for ln in wrapped[:3]],
                          size=68, y=cap_y, stroke=7, pill=True)
            overlays.append((png, ph["start"], min(ph["end"], end_at)))
        end_png = os.path.join(tmp, "end.png")
        mts._text_png(end_png, [[(w, mts.YELLOW) for w, _ in mts.END_CARD_LINES[0]],
                                [(w, mts.WHITE) for w, _ in mts.END_CARD_LINES[1]]],
                      size=84, y=cap_y - 40, stroke=9, pill=True)
        overlays.append((end_png, end_at, timeline["total"]))
        cmd = [mts._ffmpeg_bin(), "-v", "error", "-y", "-i", base, "-i", audio]
        for png, _, _ in overlays:
            cmd += ["-i", png]
        chain, prev = [], "[0:v]"
        for k, (_, start, end) in enumerate(overlays):
            chain.append(f"{prev}[{k + 2}:v]overlay=0:0:enable='between(t,{start:.3f},{end:.3f})'[v{k}]")
            prev = f"[v{k}]"
        cmd += ["-filter_complex", ";".join(chain), "-map", prev, "-map", "1:a", "-c:v", "libx264",
                "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(mts.FPS), "-c:a", "copy",
                "-movflags", "+faststart", "-shortest", out_path]
        mts._run(cmd)

    film = spec.get("film_id")
    description = "\n\n".join(part for part in (
        f"Full film: https://youtu.be/{film}" if film else "", (spec.get("description") or "").strip(),
        "#Shorts") if part)
    package = {"short": out_path, "title": spec["title"], "description": description,
               "tags": spec.get("tags") or [], "duration": timeline["total"], "narration_sec": until,
               "lines": len(beats), "pictures": len(pictures), "shots": len(shots),
               "longest_hold": round(max(s["end"] - s["start"] for s in shots), 2),
               "end_card_at": timeline["end_card_at"], "film_id": film}
    with open(os.path.join(here, "package.json"), "w", encoding="utf-8") as handle:
        json.dump(package, handle, indent=1, ensure_ascii=False)
    return package


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("spec")
    args = ap.parse_args(argv)
    package = build(args.spec)
    print(json.dumps({k: package[k] for k in ("short", "title", "duration", "pictures", "shots", "longest_hold")},
                     indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
