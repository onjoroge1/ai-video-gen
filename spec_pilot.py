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
import re
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


# The spec names a camera intent per shot ("Macro glide", "Rack focus reveals", "Freeze and
# pull back", "Fast push"). Honour that language rather than alternating presets blindly --
# the operator wrote the move into the document and it carries the meaning of the beat.
_MOVE_WORDS = (
    ("pull back", "kenburns_out"), ("pulls back", "kenburns_out"),
    ("push", "kenburns_in"), ("macro", "kenburns_in"), ("rack focus", "kenburns_in"),
    ("glide", "pan_right"), ("crosses", "pan_right"), ("drops", "pan_down"),
    ("opens toward", "kenburns_in"), ("collapse", "kenburns_out"),
    ("split screen", "pan_left"), ("freeze", "locked"),
)
# Fallback cycle for shots whose description names no move. Adjacent shots must not repeat a
# direction or the cut reads as a stutter rather than a change of view.
_CYCLE = ("kenburns_in", "pan_right", "kenburns_out", "pan_left", "zoom_br", "pan_up")


# A documentary about the price of meat will generate butcher-counter imagery, and the image
# model's OUTPUT-stage moderation rejects some of it as violence -- the block that killed the
# first 0:45-1:32 render on shot 13 of 16, after twelve images were already paid for. The
# subject is inherent to the film, so the renderer has to survive it rather than abort.
#
# These softenings change how a thing is DEPICTED, never what it depicts: a market display of
# wrapped goods still carries "beef was expensive". If a substitution would change the meaning
# of a beat, it belongs in the operator's document as a rewritten row, not here.
_SOFTEN = (
    ("beef cuts", "wrapped parcels of beef"),
    ("beef counter", "market display of wrapped beef parcels"),
    ("butcher counter", "market counter with wrapped goods"),
    ("meat counter", "market display of wrapped goods"),
    ("meatpacking floor", "large industrial workroom"),
    ("meatpacking machinery", "industrial processing equipment"),
    ("meatpacking operation", "large industrial facility"),
    ("empty hooks", "empty display rails"),
    ("a small beef cut", "a small wrapped parcel"),
    ("portion of beef", "wrapped parcel from the market"),
)


def _soften(prompt: str) -> tuple[str, list]:
    """Rephrase depiction-level triggers. Returns (prompt, what_changed)."""
    changed = []
    for harsh, gentle in _SOFTEN:
        if harsh in prompt.lower():
            pattern = re.compile(re.escape(harsh), re.I)
            prompt = pattern.sub(gentle, prompt)
            changed.append(f"{harsh} -> {gentle}")
    return prompt, changed


def _generate_shot_image(prompt: str, image_path: str, cost_sink: list, log) -> bool:
    """Generate one still, softening once if output moderation rejects it.

    Returns True if an image exists at image_path. A False is NOT swallowed -- the caller
    reports every blocked shot, because a silently missing state is the slideshow failure
    arriving by a different route.
    """
    try:
        ep.generate_image(prompt, image_path, cost_sink=cost_sink)
        return True
    except ep.ContentBlocked as first:
        softened, changed = _soften(prompt)
        if not changed:
            log(f"      blocked, and no softening applies: {str(first)[:90]}")
            return False
        log(f"      blocked; retrying softened ({'; '.join(changed)})")
        try:
            ep.generate_image(softened, image_path, cost_sink=cost_sink)
            return True
        except ep.ContentBlocked as second:
            log(f"      still blocked after softening: {str(second)[:90]}")
            return False


def _motion_for(shot: dict, order: int) -> str:
    text = f"{shot['visual']} {shot['mode']}".lower()
    for phrase, preset in _MOVE_WORDS:
        if phrase in text:
            return preset
    return _CYCLE[order % len(_CYCLE)]


def _render_shot(image_path: str, seconds: float, motion: str, out_path: str,
                 *, width: int = 1920, height: int = 1080, fps: int = 30) -> str:
    """One still + one camera move, encoded to a clip of exactly `seconds`.

    Uses the pipeline's own _motion presets and its 2x supersample trick: zoompan rounds its
    crop origin to whole INPUT pixels each frame, so running it at output size makes a slow pan
    jump a pixel at a time -- visible shake. Feeding a 2x frame makes that rounding sub-pixel.
    """
    frames = max(1, int(round(seconds * fps)))
    z_expr, x_expr, y_expr = ep._motion(motion, frames)
    ss_w, ss_h = width * 2, height * 2
    chain = (
        f"scale={ss_w}:{ss_h}:force_original_aspect_ratio=increase,crop={ss_w}:{ss_h},"
        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':d={frames}:s={width}x{height}:fps={fps},"
        f"setsar=1,format=yuv420p"
    )
    ep._run_ffmpeg([
        ep._ffmpeg_bin(), "-nostdin", "-y", "-loop", "1", "-i", image_path,
        "-vf", chain, "-frames:v", str(frames),
        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
        "-r", str(fps), out_path,
    ])
    return out_path


def pilot_scenes(spec: ud.ParsedSpec, seconds: float = PILOT_SECONDS,
                 start: float = 0.0) -> list:
    """Scenes whose narration falls inside the requested window.

    Selected by the spec's OWN timestamps rather than by counting words, so a segment covers the
    beats the document specifies -- the grocery reveal, the crossing sign, the historical turn --
    rather than whatever happens to fit a word budget.
    """
    chosen = [scene for scene in spec.scenes
              if start <= scene.start_sec < seconds]
    return chosen or spec.scenes[:1]


def render_pilot(spec_path: str, out_dir: str, *, voice: str = "echo",
                 window: tuple = (0.0, PILOT_SECONDS), log=print) -> dict:
    """Render one window of the spec. Defaults to the section-9 pilot gate.

    Generalised from a fixed first-45-seconds runner so a later section can be proven without
    re-rendering the opening: every asset is cached by content, so only the new window spends.
    """
    win_start, win_end = window
    spec = ud.parse_spec(spec_path)
    scenes = pilot_scenes(spec, win_end, win_start)
    out = Path(out_dir)
    (out / "audio").mkdir(parents=True, exist_ok=True)
    (out / "images").mkdir(parents=True, exist_ok=True)

    log(f"Spec: {spec.title}")
    log(f"Full script: {len(spec.scenes)} scenes, {spec.words} words")
    log(f"Window: {win_start:.0f}-{win_end:.0f}s → {len(scenes)} scenes, "
        f"{sum(len(s.narration.split()) for s in scenes)} words")
    for warning in spec.warnings:
        log(f"  ⚠ {warning}")

    audio_costs: list = []
    image_costs: list = []
    audio_paths, image_paths = [], []
    blocked: list = []

    for scene in scenes:
        index = scene.index
        audio_path = str(out / "audio" / f"scene_{index:02d}.mp3")
        # Reuse narration that is already on disk. The picture is what gets iterated on -- this
        # is the second pass over the same words -- and TTS is not free. Guarded on the text
        # matching, so an edited line still re-speaks rather than silently keeping stale audio.
        sidecar = Path(audio_path).with_suffix(".txt")
        cached = (Path(audio_path).exists() and Path(audio_path).stat().st_size > 0
                  and sidecar.exists()
                  and sidecar.read_text(encoding="utf-8") == scene.narration)
        if cached:
            log(f"  scene {index + 1:>2} [{scene.world}] reusing narration on disk")
        else:
            ep.generate_tts(scene.narration, audio_path, voice=voice)
            sidecar.write_text(scene.narration, encoding="utf-8")
            audio_costs.append(len(scene.narration) * ep._RATE_TTS_CHAR)
        audio_paths.append(audio_path)
        measured = ep._audio_dur(audio_path)
        log(f"  scene {index + 1:>2} [{scene.world}] {measured:5.2f}s  "
            f"{len(scene.narration.split()):>3}w")

    spoken = sum(ep._audio_dur(path) for path in audio_paths)
    # Measured, never predicted. Every compression failure in this codebase came from gating on
    # an estimate; the estimate was 13% wrong on this very narration.
    #
    # Compared against the WINDOW the spec allots, not a hardcoded 43-47s. That constant was the
    # pilot's own budget; applied to a later section it would report every segment as broken.
    budget = win_end - win_start
    drift = spoken - budget
    log(f"Measured narration: {spoken:.2f}s against a {budget:.0f}s window "
        f"({drift:+.2f}s)")
    if abs(drift) > budget * 0.10:
        log(f"  ⚠ {abs(drift):.1f}s {'over' if drift > 0 else 'under'} the spec's own timing — "
            f"the picture is rescaled to fit, but the film will drift from the document")

    # ONE IMAGE PER SHOT, not per scene. The spec's section 9 lists 15 shots across the first
    # 45 seconds at 1.8-2.8s each, and that cadence IS the retention contract. Generating one
    # image per narration scene gave 4 states over 45s -- a state change every ten seconds,
    # exactly the slideshow the spec exists to prevent, and the operator saw it immediately.
    shots = [shot for shot in ud.load_shot_plan(spec_path)
             if win_start <= shot["start_sec"] < win_end]
    prompts = ud.extract_base_prompts(Path(spec_path).read_text(encoding="utf-8"))
    negative = prompts.get("negative", "")
    log(f"Shot plan: {len(shots)} shots "
        f"(spec section 9 requires at least 15 visual states)")

    for order, shot in enumerate(shots):
        world = "alternate_2026" if shot["start_sec"] < 18 else "historical_1910"
        base = prompts.get(world, "")
        # The shot's own visual description carries the information; the world template carries
        # palette and camera language. Negative prompt appended so malformed label text -- which
        # this spec bans explicitly -- is discouraged on every shot, not just the product macros.
        prompt = f"{base} Shot: {shot['visual']}."
        if negative:
            prompt += f" Avoid: {negative}"
        image_path = str(out / "images" / f"shot_{int(win_start):04d}_{order:02d}.jpg")
        # Same reuse contract as narration, keyed on the prompt: iterating on camera movement
        # must not re-buy fifteen stills that have not changed. An edited prompt still redraws.
        sidecar = Path(image_path).with_suffix(".prompt.txt")
        if (Path(image_path).exists() and Path(image_path).stat().st_size > 0
                and sidecar.exists() and sidecar.read_text(encoding="utf-8") == prompt):
            log(f"  shot {order + 1:>2} reusing image on disk")
        elif _generate_shot_image(prompt, image_path, image_costs, log):
            sidecar.write_text(prompt, encoding="utf-8")
        else:
            blocked.append(order)
            image_paths.append(None)
            log(f"  shot {order + 1:>2} BLOCKED — {shot['visual'][:50]}")
            continue
        image_paths.append(image_path)
        log(f"  shot {order + 1:>2} [{shot['start_sec']:>2}-{shot['end_sec']:>2}s] ✓ "
            f"{shot['visual'][:46]}")

    # Not _make_scene_segment / _assemble any more. Those two are built on a one-image-per-scene
    # contract: the assembler derives its crossfade offsets from cumulative NARRATION duration,
    # which structurally caps the visual state count at the scene count. Fifteen shots across
    # four scenes cannot be expressed in that shape, so the video track is built directly and
    # muxed against the finished narration instead.
    # Video is driven by the shot table and muxed against the concatenated narration, so a shot
    # boundary no longer has to coincide with a sentence boundary. That coupling is what forced
    # one image per scene and produced the slideshow.
    (out / "tmp").mkdir(parents=True, exist_ok=True)

    # Drop blocked shots and give their seconds to the preceding shot, so the picture track
    # still covers the narration exactly. This LOWERS the state count, which is the very thing
    # the shot table exists to protect -- so it is reported as a defect, never absorbed quietly.
    if blocked:
        kept = [(shot, path) for shot, path in zip(shots, image_paths) if path]
        if not kept:
            raise RuntimeError(
                f"every shot in {win_start:.0f}-{win_end:.0f}s was blocked by image moderation")
        for order in blocked:
            hole = shots[order]["end_sec"] - shots[order]["start_sec"]
            earlier = [i for i, (sh, _) in enumerate(kept)
                       if sh["start_sec"] < shots[order]["start_sec"]]
            target = earlier[-1] if earlier else 0
            kept[target][0]["end_sec"] += hole
        shots = [shot for shot, _ in kept]
        image_paths = [path for _, path in kept]
        log(f"  ⚠ {len(blocked)} shot(s) blocked by image moderation; "
            f"{len(shots)} states remain over this window instead of "
            f"{len(shots) + len(blocked)} — neighbouring shots absorbed the time")

    # Rescale the shot table onto the narration that actually exists. The spec's table spans
    # 45.0s while the measured narration is shorter, and muxing with -shortest simply amputated
    # the closing shot. Scaling proportionally keeps all fifteen states and the operator's
    # relative pacing, costs nothing, and needs no rewrite of their words.
    planned = max(shot["end_sec"] for shot in shots) - win_start
    scale = spoken / planned
    holds = [max(1.2, (shot["end_sec"] - shot["start_sec"]) * scale) for shot in shots]
    # Absorb rounding into the final shot so the picture track matches the audio exactly.
    holds[-1] += spoken - sum(holds)
    log(f"Shot table rescaled {planned:.1f}s → {spoken:.1f}s (×{scale:.3f}); "
        f"holds {min(holds):.1f}-{max(holds):.1f}s")

    clips = []
    for order, (shot, hold) in enumerate(zip(shots, holds)):
        motion = _motion_for(shot, order)
        clip = str(out / "tmp" / f"shot_{int(win_start):04d}_{order:02d}.mp4")
        _render_shot(image_paths[order], hold, motion, clip)
        clips.append(clip)
        log(f"  shot {order + 1:>2} {hold:4.1f}s  {motion}")

    concat_list = out / "tmp" / f"shots_{int(win_start):04d}.txt"
    concat_list.write_text(
        "".join(f"file '{clip}'\n" for clip in clips), encoding="utf-8")
    silent_video = str(out / "tmp" / f"video_{int(win_start):04d}.mp4")
    ep._run_ffmpeg([ep._ffmpeg_bin(), "-nostdin", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(concat_list), "-c", "copy", silent_video])

    audio_list = out / "tmp" / f"audio_{int(win_start):04d}.txt"
    audio_list.write_text(
        "".join(f"file '{path}'\n" for path in audio_paths), encoding="utf-8")
    narration = str(out / "tmp" / f"narration_{int(win_start):04d}.mp3")
    ep._run_ffmpeg([ep._ffmpeg_bin(), "-nostdin", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(audio_list), "-c", "copy", narration])

    preview = str(out / f"segment_{int(win_start):04d}_{int(win_end):04d}.mp4")
    # -shortest so the film ends with the narration rather than on a held frame if the shot
    # table and the measured audio disagree, which they will until the opening is lengthened.
    ep._run_ffmpeg([
        ep._ffmpeg_bin(), "-nostdin", "-y", "-i", silent_video, "-i", narration,
        "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", preview,
    ])
    # Report the RESCALED holds, not the spec's planned ones. The earlier version recomputed
    # from the unscaled table and printed "45.0s vs 40.5s" after the rescale had already made
    # them agree -- a log line contradicting the thing it was reporting on.
    log(f"Video track: {len(shots)} shots over {sum(holds):.1f}s "
        f"against {spoken:.1f}s narration (delta {sum(holds) - spoken:+.2f}s)")

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
        "shots": len(shots),
        "preview_path": preview,
    }
    log(f"Pilot cost: ${report['total_cost_usd']:.3f} "
        f"(tts ${report['tts_cost_usd']:.3f} + images ${report['image_cost_usd']:.3f})")
    return report
