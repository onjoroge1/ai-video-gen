"""Re-cut a delivered illustrated film's opening payoff-first, outside the pipeline.

The cane toad film (2026-10-02) opened on a summary hook, the spoken format tag and 48 s of
setup; its first visible consequence landed at 52.9 s and browse viewers left at 41 s. The
job's images and audio were removed by the old cleanup, so a pipeline resume would re-buy
every picture. This tool renders a NEW opening with the pipeline's own scene renderer (same
captions, motion, music mix) and splices it onto the delivered film at a scene boundary.

    python3 scripts/recut_opening.py jobs/canetoad01 --spec jobs/canetoad01/recut_opening.json

Spec: {"splice_sec": <film time the kept part starts>, "voice": "echo",
       "scenes": [{"narration", "text_overlay", "shot_type", "image", "claim_refs"}]}
Writes <job>/recut/opening.mp4 and <job>/explainer.recut.mp4; the delivered film is untouched.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _run(cmd: list[str], timeout: float = 900.0) -> None:
    subprocess.run(cmd, check=True, timeout=timeout, capture_output=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("job")
    ap.add_argument("--spec", required=True)
    ap.add_argument("--film", default="explainer.mp4")
    args = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    import explainer_pipeline as ep
    import illustrated_story

    job = os.path.abspath(args.job)
    spec = json.load(open(args.spec, encoding="utf-8"))
    scenes = spec["scenes"]
    splice = float(spec["splice_sec"])
    voice = spec.get("voice", "echo")
    out_dir = os.path.join(job, "recut")
    os.makedirs(out_dir, exist_ok=True)
    costs: list[float] = []
    style = illustrated_story.visual_style_suffix(
        " Landscape 16:9 composition, subject in the middle third, the same hand-drawn "
        "ink-and-cut-paper look as the rest of the film.")

    videos, audios, durations = [], [], []
    for k, sc in enumerate(scenes):
        img = os.path.join(out_dir, f"scene_{k:02d}.jpg")
        aud = os.path.join(out_dir, f"scene_{k:02d}.mp3")
        seg = os.path.join(out_dir, f"segment_{k:02d}.mp4")
        if not os.path.isfile(img):
            ep.generate_image(sc["image"] + style, img, cost_sink=costs)
            print(f"  image {k}: drawn")
        if not os.path.isfile(aud):
            ep.generate_tts(sc["narration"], aud, voice=voice)
            print(f"  audio {k}: synthesised")
        dur = ep._audio_dur(aud)
        words = ep.transcribe_words(aud)
        word_times = ep.align_caption_phrases(sc["narration"], words, dur)
        ep._make_scene_segment(
            img, aud, seg, sc.get("text_overlay", ""), sc.get("text_sub", ""),
            motion=ep._pick_motion(sc.get("shot_type", "medium"), k), tail=ep.FADE_DUR,
            text_meta=None, style_mode="illustrated_ink", vw=1920, vh=1080,
            captions="headline_karaoke", word_times=word_times, bubble_side="right")
        videos.append(seg); audios.append(aud); durations.append(dur)
        print(f"  scene {k}: {dur:.2f}s  {sc['narration'][:60]}")
    total = sum(durations)
    print(f"new opening: {total:.2f}s over {len(scenes)} scenes; images ${sum(costs):.2f}")

    # Music: the film's own score, started so that it is in step with the kept part at the
    # splice. The delivered mix starts the score at 0, so the kept part at `splice` is hearing
    # score time `splice`; the opening therefore plays score time (splice - total) onward.
    score = sorted(glob.glob(os.path.join(job, "music", "score_*.wav")))
    music = ""
    if score:
        music = os.path.join(out_dir, "opening_music.wav")
        start = max(0.0, splice - total)
        _run([ep._ffmpeg_bin(), "-y", "-ss", f"{start:.3f}", "-i", score[-1],
              "-t", f"{total + 3:.3f}", music])
    opening = os.path.join(out_dir, "opening.mp4")
    ep._assemble(videos, audios, opening, out_dir, bg_music_path=music or None, audio_cues=None)
    open_len = ep._audio_dur(opening)
    print(f"opening assembled: {open_len:.2f}s")

    # The kept part of the delivered film, from the splice, re-encoded for a frame-accurate cut.
    film = os.path.join(job, args.film)
    tail = os.path.join(out_dir, "film_tail.mp4")
    _run([ep._ffmpeg_bin(), "-y", "-i", film, "-ss", f"{splice:.3f}",
          "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
          "-r", "30", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", tail])
    out = os.path.join(job, "explainer.recut.mp4")
    fade = ep.FADE_DUR
    _run([ep._ffmpeg_bin(), "-y", "-i", opening, "-i", tail, "-filter_complex",
          f"[0:v]fps=30,format=yuv420p[v0];[1:v]fps=30,format=yuv420p[v1];"
          f"[v0][v1]xfade=transition=fade:duration={fade}:offset={open_len - fade:.3f}[v];"
          f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo[a0];"
          f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo[a1];"
          f"[a0][a1]acrossfade=d={fade}[a]",
          "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
          "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out])
    print(json.dumps({"recut": out, "seconds": round(ep._audio_dur(out), 2),
                      "opening_seconds": round(open_len, 2), "splice_sec": splice,
                      "image_cost_usd": round(sum(costs), 3)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
