"""Render a first-45-second pilot from an operator specification document.

The spec's own section 9 calls this the paid-generation gate: build and grade 45 seconds before
committing to the full film. This wires user_directed's parsed scenes straight into the
pipeline's existing asset functions -- generate_tts, generate_image, _assemble -- rather than
through generate_graded_script, because the operator has already written the script and the
research ledger, which are the only two stages that need Anthropic.

Deliberately a separate runner, not a branch inside explainer_pipeline. That pipeline is built
around a script IT wrote: research, beat sheet, evidence plan, claim ledger, eighteen gates
tuned to its own output. Threading an operator document through all of it means either
satisfying contracts the operator never agreed to or bypassing them one flag at a time -- and
this session spent a full day on the second option. A supplied script is a different job.

Costs are reported per stage. The pipeline's own accounting was found to under-report script
spend by roughly 50x, so this counts what it actually spends rather than trusting a sink.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import explainer_pipeline as ep
import user_directed as ud


PILOT_SECONDS = 45.0
# Must match the crossfade duration _assemble builds its xfade offsets from.
XFADE_SEC = 0.5
# The tail is deliberately LONGER than the fade. _assemble computes its xfade offsets from
# cumulative NARRATION duration, while each fade shortens the actual chain by fade_dur, so the
# offsets creep past the material available -- the second fade wanted 23.108s from a 23.09s
# chain and ffmpeg exited 254 after every asset was paid for. The margin absorbs that drift and
# is held frames, not covered speech.
SEGMENT_TAIL_SEC = XFADE_SEC + 0.35


def pilot_scenes(spec: ud.ParsedSpec, seconds: float = PILOT_SECONDS) -> list:
    """Scenes whose narration falls inside the pilot window.

    Selected by the spec's OWN timestamps rather than by counting words, so the pilot covers the
    beats section 9 specifies -- the grocery reveal, the crossing sign, the historical turn --
    rather than whatever happens to fit a word budget.
    """
    chosen = [scene for scene in spec.scenes if scene.start_sec < seconds]
    return chosen or spec.scenes[:1]


def render_pilot(spec_path: str, out_dir: str, *, voice: str = "echo",
                 log=print) -> dict:
    spec = ud.parse_spec(spec_path)
    scenes = pilot_scenes(spec)
    out = Path(out_dir)
    (out / "audio").mkdir(parents=True, exist_ok=True)
    (out / "images").mkdir(parents=True, exist_ok=True)

    log(f"Spec: {spec.title}")
    log(f"Full script: {len(spec.scenes)} scenes, {spec.words} words")
    log(f"Pilot window: first {PILOT_SECONDS:.0f}s → {len(scenes)} scenes, "
        f"{sum(len(s.narration.split()) for s in scenes)} words")
    for warning in spec.warnings:
        log(f"  ⚠ {warning}")

    audio_costs: list = []
    image_costs: list = []
    audio_paths, image_paths = [], []

    for scene in scenes:
        index = scene.index
        audio_path = str(out / "audio" / f"scene_{index:02d}.mp3")
        ep.generate_tts(scene.narration, audio_path, voice=voice)
        audio_costs.append(len(scene.narration) * ep._RATE_TTS_CHAR)
        audio_paths.append(audio_path)
        measured = ep._audio_dur(audio_path)
        log(f"  scene {index + 1:>2} [{scene.world}] {measured:5.2f}s  "
            f"{len(scene.narration.split()):>3}w")

    spoken = sum(ep._audio_dur(path) for path in audio_paths)
    log(f"Measured pilot narration: {spoken:.2f}s "
        f"(spec gate wants 43-47s)")
    # Measured, never predicted. Every compression failure in this codebase came from gating on
    # an estimate; the estimate was 13% wrong on this very narration.
    if not 43.0 <= spoken <= 47.0:
        log(f"  ⚠ outside the spec's 43-47s pilot window — "
            f"{'trim' if spoken > 47 else 'extend'} the opening sections")

    for scene in scenes:
        index = scene.index
        image_path = str(out / "images" / f"scene_{index:02d}.jpg")
        ep.generate_image(scene.image_prompt, image_path, cost_sink=image_costs)
        image_paths.append(image_path)
        log(f"  image {index + 1:>2} ✓")

    # _make_scene_segment, not a hand-rolled ffmpeg call: it already handles Ken Burns motion,
    # the held tail the crossfade in _assemble expects, and the caption overlay. Rebuilding that
    # here would drift from the assembler that consumes it.
    clips = []
    for scene, image_path, audio_path in zip(scenes, image_paths, audio_paths):
        clip = str(out / "audio" / f"scene_{scene.index:02d}.mp4")
        # tail=XFADE_SEC is required, not cosmetic. _assemble crossfades each segment into the
        # next and expects every segment to be (narration + fade) long so the fade overlaps a
        # HELD tail rather than covering speech. With tail=0 the xfade offsets run past the end
        # of the input and ffmpeg exits 254 after every asset has been paid for.
        ep._make_scene_segment(image_path, audio_path, clip, "", "",
                               motion=ep._pick_motion("medium", scene.index),
                               tail=SEGMENT_TAIL_SEC)
        clips.append(clip)

    preview = str(out / "pilot_45s.mp4")
    # _assemble writes intermediates into tmp_dir and does NOT create it. Without this, ffmpeg
    # fails with "Error opening output file: No such file or directory" AFTER every image and
    # every second of narration has been paid for -- and the message names the filtergraph, so
    # it reads like a broken xfade. I lost two guesses to that before reading stderr.
    (out / "tmp").mkdir(parents=True, exist_ok=True)
    ep._assemble(clips, audio_paths, preview, str(out / "tmp"))

    report = {
        "title": spec.title,
        "pilot_scenes": len(scenes),
        "pilot_words": sum(len(s.narration.split()) for s in scenes),
        "measured_seconds": round(spoken, 2),
        "full_script_scenes": len(spec.scenes),
        "full_script_words": spec.words,
        "tts_cost_usd": round(sum(audio_costs), 4),
        "image_cost_usd": round(sum(image_costs), 4),
        "total_cost_usd": round(sum(audio_costs) + sum(image_costs), 4),
        "preview_path": preview,
    }
    log(f"Pilot cost: ${report['total_cost_usd']:.3f} "
        f"(tts ${report['tts_cost_usd']:.3f} + images ${report['image_cost_usd']:.3f})")
    return report
