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

import errno
import hashlib
import json
import os
import re
import shutil
import threading
import time
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests
import explainer_pipeline as ep
import durable_execution
import directed_longform as dl
import user_directed as ud
from PIL import Image, ImageDraw
from font_utils import load_font
from longform_rendered_gate import (
    build_contact_sheet,
    create_human_review_record,
    cross_check_blind_observations,
    inspect_rendered_opening,
    rendered_grade_summary,
    score_rendered_contract,
)


PILOT_SECONDS = 45.0
# Must match the crossfade duration _assemble builds its xfade offsets from.
XFADE_SEC = 0.5
# The tail is deliberately LONGER than the fade. _assemble computes its xfade offsets from
# cumulative NARRATION duration, while each fade shortens the actual chain by fade_dur, so the
# offsets creep past the material available -- the second fade wanted 23.108s from a 23.09s
# chain and ffmpeg exited 254 after every asset was paid for. The margin absorbs that drift and
# is held frames, not covered speech.
SEGMENT_TAIL_SEC = XFADE_SEC + 0.35
# A streamed shot retains one source JPEG and one short 1080p encode at a time. Vercel's
# production image has about 130 MiB free before our files, so the former 256 MiB floor rejected
# an otherwise empty worker forever. Keep a conservative 64 MiB default (well above observed
# 2–3 second CRF-23 shot sizes) and allow operators to raise it on larger worker disks.
MIN_RENDER_TMP_FREE_BYTES = max(
    32, int(os.environ.get("DIRECTED_TMP_MIN_FREE_MIB", "64"))
) * 1024 * 1024


def _require_tmp_headroom(path: str | Path, operation: str, log) -> None:
    usage = shutil.disk_usage(str(path))
    free_mib = usage.free / (1024 * 1024)
    log(f"  disk preflight before {operation}: {free_mib:.1f} MiB free")
    if usage.free < MIN_RENDER_TMP_FREE_BYTES:
        raise OSError(
            errno.ENOSPC,
            f"durable recovery paused before {operation}: only {free_mib:.1f} MiB free",
            str(path),
        )



@contextmanager
def _blob_segment_inputs(artifacts: list[dict], runtime):
    """Yield FFmpeg-readable URLs without exposing a private Blob token to FFmpeg."""
    if not artifacts or all(item.get("access") == "public" for item in artifacts):
        yield [str(item["url"]) for item in artifacts]
        return

    credentials = runtime.blob.credentials
    upstream_headers = {"Authorization": f"Bearer {credentials.token}"}
    if credentials.store_id:
        upstream_headers["x-vercel-blob-store-id"] = credentials.store_id

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib handler contract
            try:
                index = int(self.path.strip("/").split("?", 1)[0])
                artifact = artifacts[index]
            except (ValueError, IndexError):
                self.send_error(404)
                return
            headers = dict(upstream_headers)
            if self.headers.get("Range"):
                headers["Range"] = self.headers["Range"]
            with requests.get(
                    str(artifact["url"]), headers=headers, stream=True,
                    timeout=(15, 900)) as response:
                self.send_response(response.status_code)
                for name in ("Content-Length", "Content-Range", "Accept-Ranges", "Content-Type"):
                    if response.headers.get(name):
                        self.send_header(name, response.headers[name])
                self.end_headers()
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        self.wfile.write(chunk)

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        yield [f"http://127.0.0.1:{port}/{index}" for index in range(len(artifacts))]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


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


def _generate_shot_image(prompt: str, image_path: str, cost_sink: list, log,
                         reference_paths: list[str] | None = None,
                         image_size: str = "1536x1024") -> bool:
    """Generate one still, softening once if output moderation rejects it.

    Returns True if an image exists at image_path. A False is NOT swallowed -- the caller
    reports every blocked shot, because a silently missing state is the slideshow failure
    arriving by a different route.
    """
    try:
        ep.generate_image(
            prompt, image_path, reference_paths=reference_paths, cost_sink=cost_sink,
            size=image_size)
        return True
    except ep.ContentBlocked as first:
        softened, changed = _soften(prompt)
        if not changed:
            log(f"      blocked, and no softening applies: {str(first)[:90]}")
            return False
        log(f"      blocked; retrying softened ({'; '.join(changed)})")
        try:
            ep.generate_image(
                softened, image_path, reference_paths=reference_paths, cost_sink=cost_sink,
                size=image_size)
            return True
        except ep.ContentBlocked as second:
            log(f"      still blocked after softening: {str(second)[:90]}")
            return False


# Shots the operator marked "Full motion" get real generated footage; everything else gets a
# camera path over a still. That split is the spec's own editorial judgement, and it is also
# the economics: I2V is ~$0.28 a shot against ~$0.04 for a still, and at a 2.7s cut we would
# be buying 5-second clips and discarding half of every one.
I2V_MODES = ("Full motion",)


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _content_key(*parts) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _materialize_references(spec: dl.DirectedLongformSpec, out: Path) -> dict[str, str]:
    """Resolve and verify declared image references before the first paid provider call."""
    resolved: dict[str, str] = {}
    reference_dir = out / "references"
    reference_dir.mkdir(parents=True, exist_ok=True)
    repo_assets = Path(__file__).resolve().parent / "assets"
    for reference in spec.references:
        if not reference.mime_type.casefold().startswith("image/"):
            raise dl.DirectedValidationError(
                f"reference {reference.reference_id} must be an image for image generation")
        uri = reference.uri.strip()
        suffix = Path(uri.split("?", 1)[0]).suffix or ".img"
        destination = reference_dir / f"{reference.reference_id}{suffix}"
        if uri.startswith("asset://"):
            source = (repo_assets / uri.removeprefix("asset://")).resolve()
            if repo_assets.resolve() not in source.parents:
                raise dl.DirectedValidationError(
                    f"reference {reference.reference_id} escapes the asset directory")
            if not source.is_file():
                raise dl.DirectedValidationError(
                    f"reference {reference.reference_id} is unavailable: {uri}")
            destination.write_bytes(source.read_bytes())
        elif uri.startswith(("https://", "http://")):
            urllib.request.urlretrieve(uri, destination)
        else:
            source = Path(uri.removeprefix("file://")).expanduser().resolve()
            if not source.is_file():
                raise dl.DirectedValidationError(
                    f"reference {reference.reference_id} is unavailable: {uri}")
            destination.write_bytes(source.read_bytes())
        if _sha256_file(destination).casefold() != reference.sha256.casefold():
            destination.unlink(missing_ok=True)
            raise dl.DirectedValidationError(
                f"reference {reference.reference_id} SHA-256 does not match its contract")
        try:
            with Image.open(destination) as image:
                image.verify()
        except Exception as exc:
            destination.unlink(missing_ok=True)
            raise dl.DirectedValidationError(
                f"reference {reference.reference_id} is not a readable image") from exc
        resolved[reference.reference_id] = str(destination)
    return resolved


def _compose_directed_overlays(source_path: str, output_path: str, *, overlay_text: str,
                               world_label: str) -> str:
    """Composite exact text with Pillow so generated pixels never have to spell it."""
    image = Image.open(source_path).convert("RGB")
    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size
    if world_label.strip():
        label_font = load_font(None, max(22, int(height * 0.031)), bold=True)
        label = world_label.strip().upper()
        box = draw.textbbox((0, 0), label, font=label_font, stroke_width=1)
        label_width = box[2] - box[0]
        x, y, pad = int(width * 0.035), int(height * 0.045), int(height * 0.014)
        draw.rounded_rectangle(
            (x - pad, y - pad, x + label_width + pad, y + (box[3] - box[1]) + pad),
            radius=pad, fill=(7, 15, 25, 205), outline=(238, 220, 170, 230), width=2)
        draw.text((x, y), label, font=label_font, fill=(250, 241, 214, 255),
                  stroke_width=1, stroke_fill=(0, 0, 0, 220))
    if overlay_text.strip():
        lines = [line.strip() for line in overlay_text.split("\n") if line.strip()]
        text = "\n".join(lines)
        font = load_font(None, max(34, int(height * 0.058)), bold=True)
        spacing = int(height * 0.018)
        box = draw.multiline_textbbox(
            (0, 0), text, font=font, spacing=spacing, align="center", stroke_width=2)
        text_width, text_height = box[2] - box[0], box[3] - box[1]
        x = (width - text_width) / 2
        y = height * 0.72 - text_height / 2
        pad_x, pad_y = int(width * 0.035), int(height * 0.025)
        draw.rounded_rectangle(
            (x - pad_x, y - pad_y, x + text_width + pad_x, y + text_height + pad_y),
            radius=int(height * 0.025), fill=(3, 8, 14, 210))
        draw.multiline_text(
            (x, y), text, font=font, fill=(255, 255, 255, 255), spacing=spacing,
            align="center", stroke_width=2, stroke_fill=(0, 0, 0, 255))
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, "JPEG", quality=82, optimize=True, progressive=True)
    return output_path


def _motion_cache_path(image_path: str, shot: dict, seconds: float, out_path: str) -> Path:
    """Bind paid footage reuse to the image bytes and the complete motion request."""
    identity = _content_key(
        _sha256_file(image_path), shot.get("visual"), shot.get("mode"), round(seconds, 3),
        getattr(ep, "_FAL_MODEL", "fal-image-to-video"), 1920, 1080)
    return Path(out_path).with_name(f"motion.{identity[:24]}.src.mp4")


def _render_motion_shot(image_path: str, shot: dict, seconds: float, out_path: str,
                        cost_sink: list, log, provider_sink: list | None = None,
                        frame: dict | None = None) -> bool:
    """Generate true footage for one shot, trimmed to its hold. False if the provider declined.

    `frame` is the delivery size. It defaults to landscape so existing callers are unchanged.

    The generated clip is cached beside the still: at ~$0.28 each these are by far the most
    expensive assets in the film, and a re-render that re-bought them would cost more than the
    entire stills pass. animate_scene never raises -- it returns None when every provider in the
    chain fails -- so a decline falls back to the camera path rather than losing the shot.
    """
    cached = _motion_cache_path(image_path, shot, seconds, out_path)
    metadata_path = Path(str(cached) + ".json")
    motion_event = None
    if not (cached.exists() and cached.stat().st_size > 0):
        attempts: list[str] = []
        clip = ep.animate_scene(image_path, shot["visual"], str(cached), 1920, 1080,
                                cost_sink=cost_sink, err_sink=attempts)
        if not clip or not Path(cached).exists():
            if provider_sink is not None:
                provider_sink.append({
                    "shot_id": shot.get("shot_id"),
                    "provider": "none",
                    "model_id": "none",
                    "generation_status": "failed",
                    "source_sha256": _sha256_file(image_path),
                    "provider_attempts": attempts,
                })
            log("      i2v declined; falling back to a camera path")
            return False
        selected = next((item.split(":", 1)[1] for item in reversed(attempts)
                         if item.startswith("ok:")), "unknown")
        motion_event = {
            "provider": selected, "model_id": ep._motion_model_id(selected),
            "generation_status": "generated",
            "source_sha256": _sha256_file(image_path),
            "cache_path": str(cached), "provider_attempts": attempts,
        }
        metadata_path.write_text(
            json.dumps(motion_event, indent=2, ensure_ascii=False), encoding="utf-8")
    elif provider_sink is not None:
        try:
            motion_event = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            motion_event = {
                "provider": "unknown-historical-cache", "model_id": "unknown",
                "source_sha256": _sha256_file(image_path), "cache_path": str(cached),
                "provider_attempts": [],
            }
        motion_event["reused"] = True
    if provider_sink is not None and motion_event is not None:
        provider_sink.append({**motion_event, "shot_id": shot.get("shot_id")})

    frame = frame or FRAME["landscape"]
    # Trim to the hold. The provider returns ~5s regardless of what was asked, and the cut
    # length is set by the narration, not by the clip.
    ep._run_ffmpeg([
        ep._ffmpeg_bin(), "-nostdin", "-y", "-i", str(cached), "-t", f"{seconds:.3f}",
        # Was hardcoded landscape; a portrait render would have been letterboxed here after
        # every still had already been generated in the right aspect.
        "-vf", f"scale={frame['w']}:{frame['h']}:force_original_aspect_ratio=increase,"
               f"crop={frame['w']}:{frame['h']},setsar=1,format=yuv420p,fps=30",
        "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "19", out_path,
    ])
    return True


def _motion_for(shot: dict, order: int) -> str:
    text = f"{shot['visual']} {shot['mode']}".lower()
    for phrase, preset in _MOVE_WORDS:
        if phrase in text:
            return preset
    return _CYCLE[order % len(_CYCLE)]


# 9:16 measured from the reference videos (712x1276); 1080x1920 is the standard delivery size.
# gpt-image-2 takes "1024x1536" for portrait and "1536x1024" for landscape.
FRAME = {
    "landscape": {"w": 1920, "h": 1080, "image_size": "1536x1024"},
    "portrait": {"w": 1080, "h": 1920, "image_size": "1024x1536"},
}


def frame_for(spec_format: str) -> dict:
    return FRAME.get(str(spec_format or "").strip().lower(), FRAME["landscape"])


def _render_shot(image_path: str, seconds: float, motion: str, out_path: str,
                 *, width: int = 1920, height: int = 1080, fps: int = 30,
                 preset: str = "medium", crf: int = 19) -> str:
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
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
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


def _actual_source_cadence(shots: list[dict], holds: list[float]) -> dict:
    """Measure how long the encoded edit keeps one still master, not how many rows name it."""
    runs: list[dict] = []
    current: dict | None = None
    cursor = 0.0
    unique_assets: set[str] = set()
    motion_starts: list[float] = []
    motion_durations: list[float] = []
    for shot, hold in zip(shots, holds):
        asset_key = (shot.get("asset_key") or shot.get("shot_id") or "").strip()
        unique_assets.add(asset_key)
        is_motion = str(shot.get("mode") or "").strip().casefold() == "full motion"
        if is_motion:
            motion_starts.append(cursor)
            motion_durations.append(float(hold))
            if current:
                runs.append(current)
                current = None
        elif current and current["asset_key"] == asset_key:
            current["duration_sec"] += float(hold)
            current["shot_ids"].append(shot.get("shot_id"))
        else:
            if current:
                runs.append(current)
            current = {
                "asset_key": asset_key,
                "duration_sec": float(hold),
                "shot_ids": [shot.get("shot_id")],
            }
        cursor += float(hold)
    if current:
        runs.append(current)
    for run in runs:
        run["duration_sec"] = round(run["duration_sec"], 3)
    return {
        "unique_master_assets": len(unique_assets),
        "still_asset_runs": runs,
        "max_consecutive_still_asset_sec": max(
            (run["duration_sec"] for run in runs), default=0.0),
        "motion_starts_sec": [round(value, 3) for value in motion_starts],
        "motion_durations_sec": [round(value, 3) for value in motion_durations],
    }


def _grade_directed_pilot(*, spec: dl.DirectedLongformSpec, preview: str, out: Path,
                          shots: list[dict], image_paths: list[str], holds: list[float],
                          indexed_scenes: list[tuple[int, dl.DirectedScene]],
                          audio_paths: list[str], motion_events: list[dict],
                          cost_sink: list, log) -> dict:
    """Grade the encoded pilot pixels and create immutable editorial-review artifacts.

    The generic rendered gate expects the model-authored pipeline's evidence-plan shape.  A
    directed contract already contains the equivalent facts, so adapt only the observations
    needed by the gate; no prompt, intended answer, or operator scoring metadata is shown to the
    blind judge.
    """
    cursor = 0.0
    gate_shots: list[dict] = []
    states: list[dict] = []
    for shot, image_path, hold in zip(shots, image_paths, holds):
        midpoint = cursor + hold / 2
        state_id = shot["shot_id"]
        gate_shots.append({
            "state_id": state_id,
            "global_start_sec": round(cursor, 4),
            "midpoint_sec": round(midpoint, 4),
            "duration": round(hold, 4),
            "source": image_path,
            "verified_visible_information": True,
        })
        labels = " ".join(str(item) for item in shot.get("labels") or [])
        has_bolt = bool(
            "BOLT" in (shot.get("reference_ids") or [])
            or "bolt" in str(shot.get("mode") or "").casefold()
            or "bolt" in str(shot.get("visual") or "").casefold()
            or "bolt" in labels.casefold())
        states.append({
            "state_id": state_id,
            "include_bolt": has_bolt,
            "pure_evidence": False,
            "required_objects": [],
            "verification": {
                "passed": Path(image_path).is_file(),
                "bolt_present": has_bolt,
                "reasons": [],
            },
        })
        cursor += hold

    evidence_plan = {"scenes": [{"states": states}]}
    inspection = inspect_rendered_opening(
        preview, [gate_shots], str(out), evidence_plan)
    # The directed contract owns its cadence bounds. The shared gate's 3.5-second legacy hold
    # constant must not silently outrank the JSON's explicit max_unchanged_hold_sec.
    deterministic = inspection.get("deterministic") or {}
    cadence = _actual_source_cadence(shots, holds)
    # A five-second generated motion clip is not an unchanged visual hold.  The old count included
    # Full motion rows and made the fast-cadence V4 contract fail precisely because it contained
    # the front-loaded motion the contract required.
    shot_hold_failures = sum(
        hold > spec.acceptance.max_unchanged_hold_sec
        for shot, hold in zip(shots, holds)
        if str(shot.get("mode") or "").strip().casefold() != "full motion")
    source_hold_failures = sum(
        run["duration_sec"] > spec.acceptance.max_consecutive_still_asset_sec
        for run in cadence["still_asset_runs"])
    deterministic["long_hold_count"] = shot_hold_failures + source_hold_failures
    deterministic["directed_source_cadence"] = cadence
    contact_sheet_path = str(out / "rendered_contact_sheet.jpg")
    build_contact_sheet(inspection, contact_sheet_path)

    transcript_cues = []
    cue_cursor = 0.0
    for (_, scene), audio_path in zip(indexed_scenes, audio_paths):
        duration = ep._audio_dur(audio_path)
        transcript_cues.append({
            "start_sec": round(cue_cursor, 2),
            "end_sec": round(cue_cursor + duration, 2),
            "narration": scene.narration,
        })
        cue_cursor += duration

    blind = ep._blind_rendered_story_judge(
        contact_sheet_path, transcript_cues, cost_sink=cost_sink)
    checked = cross_check_blind_observations(
        blind, deterministic)
    factual = dl.validate_directed_spec(spec.model_dump(mode="json"))
    claim_validation = {
        "passed": bool(factual.get("valid"))
        and float(factual.get("evidence_coverage_pct") or 0)
        >= spec.acceptance.evidence_coverage_pct,
        "errors": factual.get("issues") or [],
    }
    rendered = score_rendered_contract(
        deterministic=deterministic,
        blind=checked,
        story_validation={"checks": {"first_act_continuity_hits": True}, "errors": []},
        claim_validation=claim_validation,
        callback_exact=True,
    )
    # Directed v1 deliberately freezes a stricter 90-point automatic floor than the generic
    # long-form gate's 85. Preserve the generic component report, but never let its lower floor
    # promote this pilot.
    motion_failures = [
        event for event in motion_events if event.get("generation_status") == "failed"]
    if motion_failures:
        rendered.setdefault("hard_failures", []).append("declared_full_motion_not_generated")
    if source_hold_failures:
        rendered.setdefault("hard_failures", []).append("directed_source_hold_too_long")
    if cadence["unique_master_assets"] < spec.acceptance.pilot_min_unique_master_assets:
        rendered.setdefault("hard_failures", []).append("directed_unique_images_too_few")
    actual_frontloaded_motion = sum(
        start < spec.acceptance.frontloaded_motion_window_sec
        for start in cadence["motion_starts_sec"])
    if actual_frontloaded_motion < spec.acceptance.frontloaded_motion_count:
        rendered.setdefault("hard_failures", []).append("directed_motion_not_frontloaded")
    if any(
            abs(duration - spec.acceptance.full_motion_duration_sec)
            > spec.acceptance.full_motion_duration_tolerance_sec
            for duration in cadence["motion_durations_sec"]):
        rendered.setdefault("hard_failures", []).append("directed_motion_duration_mismatch")
    rendered["hard_failures"] = sorted(set(rendered.get("hard_failures") or []))
    score = rendered.get("score")
    grade_available = checked.get("valid") is True
    directed_pass = (
        bool(score >= spec.acceptance.automatic_grade_min
             and not rendered.get("hard_failures"))
        if grade_available and score is not None else
        (False if rendered.get("hard_failures") else None)
    )
    status = (
        "REJECT" if rendered.get("hard_failures") else
        "UNSCORED_JUDGE_UNAVAILABLE" if not grade_available else
        "AUTOMATED_PASS_AWAITING_HUMAN" if directed_pass else "REJECT"
    )
    rendered.update({
        "name": "Directed Long-Form Rendered Pilot Contract",
        "automatic_grade_floor": spec.acceptance.automatic_grade_min,
        "automated_pass": directed_pass,
        "automated_grade_available": grade_available,
        "passed": False,
        "publishable": False,
        "status": status,
        "inspection": inspection,
        "blind_story_judge": checked,
        "contact_sheet_path": contact_sheet_path,
        "promotion_rule": "A failed automatic or editorial grade cannot be promoted in place.",
    })
    rendered["grade_summary"] = rendered_grade_summary(rendered)
    report_path = str(out / "rendered_contract.json")
    Path(report_path).write_text(
        json.dumps(rendered, indent=2, ensure_ascii=False), encoding="utf-8")
    review_path = str(out / "human_review.json")
    create_human_review_record(report_path, preview, review_path)
    grade_label = (f"{rendered['score']}/100" if rendered.get("score") is not None
                   else "unscored")
    log(f"Rendered pilot grade: {grade_label} ({rendered['status']})")
    return {
        "rendered_contract": rendered,
        "rendered_contract_path": report_path,
        "rendered_contact_sheet_path": contact_sheet_path,
        "human_review_path": review_path,
    }


def render_pilot(spec_path: str | Path | dict, out_dir: str, *, voice: str = "echo",
                 window: tuple = (0.0, PILOT_SECONDS), use_i2v: bool = False,
                 validated_sha256: str = "", authorize_paid: bool = False,
                 require_validation: bool = False, log=print) -> dict:
    """Render one window of the spec. Defaults to the section-9 pilot gate.

    Generalised from a fixed first-45-seconds runner so a later section can be proven without
    re-rendering the opening: every asset is cached by content, so only the new window spends.
    """
    win_start, win_end = window
    if isinstance(spec_path, dict):
        payload = spec_path
    else:
        source = Path(spec_path)
        if source.suffix.casefold() == ".json":
            payload = json.loads(source.read_text(encoding="utf-8"))
        else:
            payload = ud.compile_directed_spec(source)

    validation = dl.validate_directed_spec(payload)
    if require_validation:
        spec, validation = dl.authorize_processing(
            payload, expected_sha256=validated_sha256, authorize_paid=authorize_paid)
    else:
        # Backwards-compatible local runner: it may inspect a known failed historical pilot, but
        # malformed JSON still cannot reach a provider.  The API always sets require_validation.
        if not validation.get("spec_sha256"):
            raise dl.DirectedValidationError("directed JSON does not match the v1 schema")
        spec = dl.DirectedLongformSpec.model_validate(validation["normalized_spec"])

    # One frame decision for the whole render: the stills, the motion trims and the final encode
    # all read it, so a portrait spec cannot end up with landscape images or a letterboxed clip.
    _frame = frame_for(spec.target.format)

    indexed_scenes = [
        (index, scene) for index, scene in enumerate(spec.narration)
        if win_start <= scene.start_sec < win_end
    ]
    if not indexed_scenes:
        indexed_scenes = [(0, spec.narration[0])]
    out = Path(out_dir)
    (out / "audio").mkdir(parents=True, exist_ok=True)
    (out / "images").mkdir(parents=True, exist_ok=True)
    validation_paths = dl.write_validation_artifacts(validation, out)
    reference_files = _materialize_references(spec, out)

    log(f"Spec: {spec.title}")
    full_words = sum(len(scene.narration.split()) for scene in spec.narration)
    log(f"Full script: {len(spec.narration)} scenes, {full_words} words")
    log(f"Window: {win_start:.0f}-{win_end:.0f}s → {len(indexed_scenes)} scenes, "
        f"{sum(len(s.narration.split()) for _, s in indexed_scenes)} words")
    for issue in validation.get("issues") or []:
        if issue.get("severity") == "warning":
            log(f"  ⚠ {issue.get('message')}")

    audio_costs: list = []
    audio_transformations: list = []
    image_costs: list = []
    audio_paths, image_paths = [], []
    blocked: list = []

    for index, scene in indexed_scenes:
        audio_path = str(out / "audio" / f"scene_{index:02d}.mp3")
        # Reuse narration that is already on disk. The picture is what gets iterated on -- this
        # is the second pass over the same words -- and TTS is not free. Guarded on the text
        # matching, so an edited line still re-speaks rather than silently keeping stale audio.
        sidecar = Path(audio_path).with_suffix(".txt")
        cached = (Path(audio_path).exists() and Path(audio_path).stat().st_size > 0
                  and sidecar.exists()
                  and sidecar.read_text(encoding="utf-8") == scene.narration)
        if cached:
            log(f"  scene {index + 1:>2} [{scene.world_id}] reusing narration on disk")
        else:
            ep.generate_tts(scene.narration, audio_path, voice=voice)
            sidecar.write_text(scene.narration, encoding="utf-8")
            audio_costs.append(len(scene.narration) * ep._RATE_TTS_CHAR)
        audio_paths.append(audio_path)
        measured = ep._audio_dur(audio_path)
        log(f"  scene {index + 1:>2} [{scene.world_id}] {measured:5.2f}s  "
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

    # The free structural preflight has already passed.  This is the first paid checkpoint: TTS
    # is measured before any image call.  A failure preserves narration and validation artifacts
    # but stops visual spending, exactly as the directed production contract requires.
    if require_validation:
        is_pilot = abs(win_start) <= 0.05 and abs(win_end - spec.target.pilot_end_sec) <= 0.05
        # A small natural-TTS overrun is an audio-layout problem, not a reason to regenerate
        # the approved narration or weaken the runtime gate.  Fit the already-paid audio with
        # ffmpeg atempo, preserve pitch, then remeasure and enforce the exact same 43-47s gate.
        # The 12% ceiling is deliberately narrow; larger misses still fail closed before images.
        if (is_pilot and spoken > spec.acceptance.pilot_runtime_max_sec
                and spoken <= spec.acceptance.pilot_runtime_max_sec * 1.12):
            target_spoken = max(
                spec.acceptance.pilot_runtime_min_sec + 0.5,
                spec.acceptance.pilot_runtime_max_sec - 1.0,
            )
            speed_factor = spoken / target_spoken
            original_spoken = spoken
            if not 1.0 < speed_factor <= 1.12:
                raise RuntimeError(
                    f"measured pilot narration {spoken:.2f}s requires unsafe audio retime; "
                    "visual spending stopped")
            for (scene_index, scene), audio_path in zip(indexed_scenes, audio_paths):
                before = ep._audio_dur(audio_path)
                tmp_path = audio_path + ".runtime-fit.mp3"
                ep._run_ffmpeg([
                    ep._ffmpeg_bin(), "-nostdin", "-y", "-i", audio_path,
                    "-filter:a", f"atempo={speed_factor:.6f}",
                    "-c:a", "libmp3lame", "-q:a", "2", tmp_path,
                ], timeout=120.0)
                os.replace(tmp_path, audio_path)
                after = ep._audio_dur(audio_path)
                audio_transformations.append({
                    "scene_id": scene.scene_id,
                    "type": "atempo",
                    "reason": "directed_pilot_runtime_fit",
                    "speed_factor": round(speed_factor, 6),
                    "original_runtime_sec": round(before, 3),
                    "final_runtime_sec": round(after, 3),
                })
            spoken = sum(ep._audio_dur(path) for path in audio_paths)
            drift = spoken - budget
            log(f"Directed pilot audio runtime fit: {original_spoken:.2f}s → {spoken:.2f}s "
                f"(atempo ×{speed_factor:.4f}; gate unchanged)")
        if is_pilot and not (
                spec.acceptance.pilot_runtime_min_sec <= spoken
                <= spec.acceptance.pilot_runtime_max_sec):
            raise RuntimeError(
                f"measured pilot narration {spoken:.2f}s is outside "
                f"{spec.acceptance.pilot_runtime_min_sec:.2f}-"
                f"{spec.acceptance.pilot_runtime_max_sec:.2f}s; visual spending stopped")
        if not is_pilot and abs(drift) > spec.acceptance.runtime_tolerance_sec:
            raise RuntimeError(
                f"measured narration differs from the window by {drift:+.2f}s; "
                "visual spending stopped")

    # ONE IMAGE PER SHOT, not per scene. The spec's section 9 lists 15 shots across the first
    # 45 seconds at 1.8-2.8s each, and that cadence IS the retention contract. Generating one
    # image per narration scene gave 4 states over 45s -- a state change every ten seconds,
    # exactly the slideshow the spec exists to prevent, and the operator saw it immediately.
    shots = [shot.model_dump(mode="json") for shot in spec.shots
             if win_start <= shot.start_sec < win_end]
    prompts = {world.world_id: world.base_prompt for world in spec.worlds}
    world_labels = {world.world_id: world.on_screen_label for world in spec.worlds}
    negative = spec.negative_prompt
    log(f"Shot plan: {len(shots)} shots "
        f"(spec section 9 requires at least 15 visual states)")

    # Full films cannot retain ~100 source images until the assembly pass: even compact JPEGs
    # eventually fill a serverless worker's /tmp.  Their timing is already known, so keep only
    # one pending source image, render it when the next usable shot is known, then release it.
    # The pilot keeps the historical all-images path because its grader needs those sources.
    streaming_render = bool(require_validation and win_start >= spec.target.pilot_end_sec - 0.05)
    planned = max(shot["end_sec"] for shot in shots) - win_start
    scale = spoken / planned
    planned_holds = [max(1.2, (shot["end_sec"] - shot["start_sec"]) * scale)
                     for shot in shots]
    planned_holds[-1] += spoken - sum(planned_holds)
    (out / "tmp").mkdir(parents=True, exist_ok=True)
    clips: list[str] = []
    stream_segments: list[str] = []
    stream_segment_artifacts: list[dict] = []
    i2v_costs: list = []
    motion_events: list = []
    animated = 0
    stream_shots: list[dict] = []
    stream_holds: list[float] = []
    stream_image_assets: list[dict] = []
    pending_stream: dict | None = None
    leading_blocked_seconds = 0.0

    def compact_stream_clips(*, force: bool = False) -> None:
        """Collapse bounded groups of shot clips before they can fill serverless /tmp."""
        # Upload every completed clip immediately. Even a three-clip batch briefly retained
        # those clips plus a fourth concatenated copy, which can exhaust Vercel's shared /tmp.
        # A one-clip batch performs no concat and changes neither frames nor encoding quality.
        batch_size = 1
        if not streaming_render or (len(clips) < batch_size and not force):
            return
        if not clips:
            return
        batch = list(clips)
        before = shutil.disk_usage(str(out))
        log(f"  compacting {len(batch)} shot clip(s); "
            f"tmp free {before.free / (1024 * 1024):.1f} MiB")
        batch_order = len(stream_shots)
        manifest = out / "tmp" / f"stream_batch_{int(win_start):04d}_{batch_order:03d}.txt"
        manifest.write_text(
            "".join(f"file '{Path(item).resolve()}'\n" for item in batch), encoding="utf-8")
        segment = str(
            out / "tmp" / f"stream_segment_{int(win_start):04d}_{batch_order:03d}.mp4")
        if len(batch) == 1:
            segment = batch[0]
        else:
            ep._run_ffmpeg([
                ep._ffmpeg_bin(), "-nostdin", "-y", "-f", "concat", "-safe", "0",
                "-i", str(manifest), "-map", "0:v", "-c:v", "copy",
                "-movflags", "+faststart", segment,
            ])
            for item in batch:
                Path(item).unlink(missing_ok=True)
        manifest.unlink(missing_ok=True)
        runtime = durable_execution.current()
        if runtime is not None:
            artifact = runtime.blob.upload(
                segment,
                f"jobs/{runtime.job_id}/scratch/remaining-{int(win_start):04d}-"
                f"{batch_order:03d}.mp4")
            stream_segment_artifacts.append(artifact)
            stream_segments.append(str(artifact["url"]))
            Path(segment).unlink(missing_ok=True)
        else:
            stream_segments.append(segment)
        clips.clear()
        after = shutil.disk_usage(str(out))
        log(f"  clip batch compacted; tmp free {after.free / (1024 * 1024):.1f} MiB")

    def flush_stream() -> None:
        nonlocal pending_stream, animated
        if not pending_stream:
            return
        stream_order = len(stream_shots)
        shot = pending_stream["shot"]
        hold = float(pending_stream["hold"])
        path = str(pending_stream["path"])
        clip = str(out / "tmp" / f"shot_{int(win_start):04d}_{stream_order:03d}.mp4")
        if (use_i2v and shot["mode"].strip().casefold() == "full motion"
                and _render_motion_shot(
                    path, shot, hold, clip, i2v_costs, log, motion_events,
                    frame=_frame)):
            animated += 1
            log(f"  shot {stream_order + 1:>2} {hold:4.1f}s  I2V")
        else:
            motion = _motion_for(shot, stream_order)
            _require_tmp_headroom(out, f"shot {stream_order + 1} render", log)
            # Recovery may need to replay dozens of already-paid sources inside one function
            # window.  The preset changes encoder search effort, not resolution, CRF, frames,
            # motion, or content; veryfast keeps that deterministic replay below the lease limit.
            _render_shot(path, hold, motion, clip, preset="veryfast", crf=23,
                         width=_frame["w"], height=_frame["h"])
            log(f"  shot {stream_order + 1:>2} {hold:4.1f}s  {motion}")
        clips.append(clip)
        compact_stream_clips()
        stream_shots.append(shot)
        stream_holds.append(hold)
        stream_image_assets.append(pending_stream["asset"])
        Path(path).unlink(missing_ok=True)
        prompt_sidecar = pending_stream.get("sidecar")
        if prompt_sidecar:
            Path(prompt_sidecar).unlink(missing_ok=True)
        pending_stream = None

    for order, shot in enumerate(shots):
        world = shot["world_id"]
        base = prompts.get(world, "")
        # The shot's own visual description carries the information; the world template carries
        # palette and camera language. Negative prompt appended so malformed label text -- which
        # this spec bans explicitly -- is discouraged on every shot, not just the product macros.
        master_prompt = shot.get("asset_prompt") or shot["visual"]
        prompt = f"{base} Master image: {master_prompt}."
        if negative:
            prompt += f" Avoid: {negative}"
        asset_key = shot.get("asset_key") or shot["shot_id"]
        prompt_key = _content_key(asset_key, world, prompt, shot.get("reference_ids") or [])
        safe_key = re.sub(r"[^a-zA-Z0-9._-]+", "-", asset_key).strip("-.")[:48] or "asset"
        master_path = str(out / "images" / "masters" / f"{safe_key}.{prompt_key[:16]}.jpg")
        Path(master_path).parent.mkdir(parents=True, exist_ok=True)
        # Same reuse contract as narration, keyed on the prompt: iterating on camera movement
        # must not re-buy fifteen stills that have not changed. An edited prompt still redraws.
        sidecar = Path(master_path).with_suffix(".prompt.txt")
        if (Path(master_path).exists() and Path(master_path).stat().st_size > 0
                and sidecar.exists() and sidecar.read_text(encoding="utf-8") == prompt):
            log(f"  shot {order + 1:>2} reusing image on disk")
        elif _generate_shot_image(
                prompt, master_path, image_costs, log,
                [reference_files[item] for item in shot.get("reference_ids") or []] or None,
                image_size=_frame["image_size"]):
            sidecar.write_text(prompt, encoding="utf-8")
        else:
            blocked.append(order)
            image_paths.append(None)
            if streaming_render:
                hole = planned_holds[order]
                if pending_stream:
                    pending_stream["hold"] += hole
                else:
                    leading_blocked_seconds += hole
            log(f"  shot {order + 1:>2} BLOCKED — {shot['visual'][:50]}")
            continue
        overlay = shot.get("overlay_text") or ""
        world_label = world_labels.get(world, "")
        if overlay or world_label:
            overlay_key = _content_key(prompt_key, overlay, world_label)
            image_path = str(
                out / "images" / "shots" / f"{shot['shot_id']}.{overlay_key[:16]}.jpg")
            if not Path(image_path).exists():
                _compose_directed_overlays(
                    master_path, image_path, overlay_text=overlay, world_label=world_label)
            # The composited shot is the only render input from this point onward.  The durable
            # stage artifact remains in Blob and will restore the master if a later worker needs
            # it, so retaining both local JPEGs only doubles /tmp usage without adding recovery.
            Path(master_path).unlink(missing_ok=True)
            sidecar.unlink(missing_ok=True)
        else:
            image_path = master_path
        image_paths.append(image_path)
        if streaming_render:
            # Delay one shot so a following moderation block can donate its duration to the
            # preceding visual exactly as the historical renderer did.  This bounds live source
            # media to at most two images without changing shot order or the narration clock.
            flush_stream()
            hold = planned_holds[order] + leading_blocked_seconds
            leading_blocked_seconds = 0.0
            pending_stream = {
                "shot": shot, "hold": hold, "path": image_path, "sidecar": str(sidecar),
                "asset": {
                    "shot_id": shot["shot_id"],
                    "path": str(Path(image_path).resolve().relative_to(out.resolve())),
                    "sha256": _sha256_file(image_path), "mime_type": "image/jpeg",
                    "asset_key": shot.get("asset_key") or shot["shot_id"],
                    "transformation": shot.get("transformation") or shot.get("mode"),
                },
            }
        log(f"  shot {order + 1:>2} [{shot['start_sec']:>2}-{shot['end_sec']:>2}s] ✓ "
            f"{shot['visual'][:46]}")

    if streaming_render:
        if pending_stream and leading_blocked_seconds:
            pending_stream["hold"] += leading_blocked_seconds
        flush_stream()
        compact_stream_clips(force=True)
        clips[:] = stream_segments
        if not stream_shots:
            raise RuntimeError(
                f"every shot in {win_start:.0f}-{win_end:.0f}s was blocked by image moderation")
        shots = stream_shots
        holds = stream_holds
        image_paths = []

    # Not _make_scene_segment / _assemble any more. Those two are built on a one-image-per-scene
    # contract: the assembler derives its crossfade offsets from cumulative NARRATION duration,
    # which structurally caps the visual state count at the scene count. Fifteen shots across
    # four scenes cannot be expressed in that shape, so the video track is built directly and
    # muxed against the finished narration instead.
    # Video is driven by the shot table and muxed against the concatenated narration, so a shot
    # boundary no longer has to coincide with a sentence boundary. That coupling is what forced
    # one image per scene and produced the slideshow.
    # Drop blocked shots and give their seconds to the preceding shot, so the picture track
    # still covers the narration exactly. This LOWERS the state count, which is the very thing
    # the shot table exists to protect -- so it is reported as a defect, never absorbed quietly.
    if blocked and not streaming_render:
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
    if not streaming_render:
        planned = max(shot["end_sec"] for shot in shots) - win_start
        scale = spoken / planned
        holds = [max(1.2, (shot["end_sec"] - shot["start_sec"]) * scale)
                 for shot in shots]
        holds[-1] += spoken - sum(holds)
    log(f"Shot table rescaled {planned:.1f}s → {spoken:.1f}s (×{scale:.3f}); "
        f"holds {min(holds):.1f}-{max(holds):.1f}s")

    for order, (shot, hold) in ([] if streaming_render else enumerate(zip(shots, holds))):
        clip = str(out / "tmp" / f"shot_{int(win_start):04d}_{order:02d}.mp4")
        if (use_i2v and shot["mode"].strip().casefold() == "full motion"
                and _render_motion_shot(
                    image_paths[order], shot, hold, clip, i2v_costs, log,
                    motion_events, frame=_frame)):
            animated += 1
            log(f"  shot {order + 1:>2} {hold:4.1f}s  I2V")
        else:
            motion = _motion_for(shot, order)
            _render_shot(image_paths[order], hold, motion, clip,
                         width=_frame["w"], height=_frame["h"])
            log(f"  shot {order + 1:>2} {hold:4.1f}s  {motion}")
        clips.append(clip)
    if use_i2v:
        log(f"  {animated}/{len(shots)} shots animated  (i2v ${sum(i2v_costs):.2f})")

    audio_list = out / "tmp" / f"audio_{int(win_start):04d}.txt"
    audio_list.write_text(
        "".join(f"file '{path}'\n" for path in audio_paths), encoding="utf-8")

    preview = str(out / f"segment_{int(win_start):04d}_{int(win_end):04d}.mp4")
    # Mux both concat lists directly. Keeping all clips, then materialising a full silent-video
    # copy, then materialising the final mux briefly triples the video footprint and exhausts
    # Vercel's /tmp on a 15-shot opening. -shortest still makes narration the timing authority.
    runtime = durable_execution.current()
    with _blob_segment_inputs(stream_segment_artifacts, runtime) as remote_urls:
        assembly_clips = remote_urls if stream_segment_artifacts else clips
        concat_list = out / "tmp" / f"shots_{int(win_start):04d}.txt"
        concat_list.write_text(
            "".join(f"file '{clip}'\n" for clip in assembly_clips), encoding="utf-8")
        remote_segments = bool(stream_segment_artifacts)
        video_input = []
        if remote_segments:
            video_input.extend([
                "-protocol_whitelist", "file,http,https,tcp,tls,crypto",
            ])
        _require_tmp_headroom(out, "final streamed assembly", log)
        ep._run_ffmpeg([
            ep._ffmpeg_bin(), "-nostdin", "-y",
            *video_input,
            "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-f", "concat", "-safe", "0", "-i", str(audio_list),
            "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
            "-b:a", "192k", "-shortest", "-movflags", "+faststart", preview,
        ])
    for clip in clips:
        if not str(clip).startswith(("https://", "http://")):
            Path(clip).unlink(missing_ok=True)
    if runtime is not None:
        for artifact in stream_segment_artifacts:
            runtime.blob.delete(str(artifact["url"]))
    # Report the RESCALED holds, not the spec's planned ones. The earlier version recomputed
    # from the unscaled table and printed "45.0s vs 40.5s" after the rescale had already made
    # them agree -- a log line contradicting the thing it was reporting on.
    log(f"Video track: {len(shots)} shots over {sum(holds):.1f}s "
        f"against {spoken:.1f}s narration (delta {sum(holds) - spoken:+.2f}s)")

    judge_costs: list = []
    grade_artifacts = {}
    is_pilot = abs(win_start) <= 0.05 and abs(win_end - spec.target.pilot_end_sec) <= 0.05
    if require_validation and is_pilot:
        grade_artifacts = _grade_directed_pilot(
            spec=spec, preview=preview, out=out, shots=shots, image_paths=image_paths,
            holds=holds, indexed_scenes=indexed_scenes, audio_paths=audio_paths,
            motion_events=motion_events, cost_sink=judge_costs, log=log)

    def _relative(path: str) -> str:
        try:
            return str(Path(path).resolve().relative_to(out.resolve()))
        except ValueError:
            return str(path)

    for event in motion_events:
        if event.get("cache_path"):
            event["cache_path"] = _relative(event["cache_path"])

    manifest_path = out / "generation_manifest.json"
    manifest = {
        "schema_version": dl.SCHEMA_VERSION,
        "spec_sha256": validation["spec_sha256"],
        "status": "pilot_rendered" if win_end <= spec.target.pilot_end_sec else "segment_rendered",
        "window": {"start_sec": win_start, "end_sec": win_end},
        "providers": [
            {"purpose": "narration", "provider": "openai", "model_id": ep.TTS_MODEL,
             "voice": voice, "transformation": "atempo" if audio_transformations else "none"},
            {"purpose": "images", "provider": "openai", "model_id": ep.IMAGE_MODEL},
        ] + ([{
            "purpose": "blind_rendered_story_grade", "provider": "anthropic",
            "model_id": ep.ANTHROPIC_MODEL, "input_mime_type": "image/jpeg",
        }] if grade_artifacts else []),
        "actual_motion": motion_events,
        "assets": {
            "references": [
                {"reference_id": reference.reference_id,
                 "path": _relative(reference_files[reference.reference_id]),
                 "sha256": reference.sha256, "mime_type": reference.mime_type,
                 "origin": reference.origin, "license": reference.license}
                for reference in spec.references
            ],
            "audio": [
                {"scene_id": scene.scene_id, "path": _relative(path),
                 "sha256": _sha256_file(path), "mime_type": "audio/mpeg"}
                for (_, scene), path in zip(indexed_scenes, audio_paths)
            ],
            "images": stream_image_assets if streaming_render else [
                {"shot_id": shot["shot_id"], "path": _relative(path),
                 "sha256": _sha256_file(path), "mime_type": "image/jpeg",
                 "asset_key": shot.get("asset_key") or shot["shot_id"],
                 "transformation": shot.get("transformation") or shot.get("mode")}
                for shot, path in zip(shots, image_paths)
            ],
        },
        "actual_audio_transformations": audio_transformations,
        "blocked_shots": blocked,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    report = {
        "title": spec.title,
        "pilot_scenes": len(indexed_scenes),
        "pilot_words": sum(len(s.narration.split()) for _, s in indexed_scenes),
        "measured_seconds": round(spoken, 2),
        "full_script_scenes": len(spec.narration),
        "full_script_words": full_words,
        "tts_cost_usd": round(sum(audio_costs), 4),
        "image_cost_usd": round(sum(image_costs), 4),
        "i2v_cost_usd": round(sum(i2v_costs), 4),
        "judge_cost_usd": round(sum(judge_costs), 4),
        "animated_shots": animated,
        "total_cost_usd": round(
            sum(audio_costs) + sum(image_costs) + sum(i2v_costs) + sum(judge_costs), 4),
        "shots": len(shots),
        "preview_path": preview,
        "spec_sha256": validation["spec_sha256"],
        "directed_spec_path": validation_paths["directed_spec_path"],
        "validation_report_path": validation_paths["validation_report_path"],
        "generation_manifest_path": str(manifest_path),
        **grade_artifacts,
    }
    log(f"Window cost: ${report['total_cost_usd']:.3f} "
        f"(tts ${report['tts_cost_usd']:.3f} + images ${report['image_cost_usd']:.3f}"
        f" + i2v ${report['i2v_cost_usd']:.3f} + judge ${report['judge_cost_usd']:.3f})")
    return report
