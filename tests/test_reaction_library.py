"""The reaction library's alpha path, tested without spending anything.

Every expensive part of ``gen_quiz_reactions`` is a network call, and none of it is what breaks.
What breaks is the alpha: a keyed cutout that loses its matte still plays perfectly on its own and
only reveals itself once it is composited over a scene, by which point it is in a published video.
Two encoders in this very ffmpeg build accept ``yuva420p``, write ``yuv420p`` and exit 0.

So these cover the packing, the unpacking and the despill on synthetic frames.
"""
import json
import os
import subprocess

import numpy as np
import pytest
from PIL import Image

from bolt_seq import gen_quiz_reactions as R


def _rgba_frames(tmp_path, count=6, size=(120, 200), colour=(255, 255, 255)):
    """Frames with a known opaque disc on a fully transparent field."""
    d = tmp_path / "frames"
    d.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        im = Image.new("RGBA", size, (0, 0, 0, 0))
        from PIL import ImageDraw
        off = i * 3
        ImageDraw.Draw(im).ellipse([20, 20 + off, 100, 100 + off], fill=(*colour, 255))
        im.save(d / f"{i:04d}.png")
    return str(d)


def test_the_shipping_container_actually_carries_the_matte(tmp_path):
    """The whole reason the asset is a stacked mp4 rather than a WebM."""
    frames = _rgba_frames(tmp_path)
    out = str(tmp_path / "r.mp4")
    R.pack_rgba_frames(frames, out, (120, 200))
    assert os.path.exists(out)

    unpack, (w, h) = R.unpack_filter(out)
    assert (w, h) == (120, 200)
    rebuilt = str(tmp_path / "rebuilt.png")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", out, "-filter_complex",
                    unpack, "-map", "[rx]", "-frames:v", "1", rebuilt], check=True)
    alpha = np.array(Image.open(rebuilt).convert("RGBA"))[..., 3]
    assert alpha.min() < 10, "no transparent pixels survived — the matte was lost"
    assert alpha.max() > 245, "no opaque pixels survived — the matte was lost"
    # The disc covers well under half the field; a container that dropped alpha reports 0% here.
    assert 0.5 < (alpha < 10).mean() < 0.95


def test_the_unpack_geometry_is_read_from_the_file_not_assumed(tmp_path):
    """A consumer hardcoding "crop the top half" works until a clip is a different size, and then
    shows half an animation over half a matte with nothing raising."""
    frames = _rgba_frames(tmp_path, size=(64, 96))
    out = str(tmp_path / "small.mp4")
    R.pack_rgba_frames(frames, out, (64, 96))
    _, size = R.unpack_filter(out)
    assert size == (64, 96)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=height", "-of", "csv=p=0", out], capture_output=True, text=True, check=True)
    assert int(probe.stdout.strip()) == 96 * 2, "the asset should carry colour stacked over matte"


def test_the_crop_size_is_always_even(tmp_path):
    """yuv420p subsamples chroma 2x2 and cannot encode an odd side. The first real clip cropped to
    540x903 and would have failed on the height alone."""
    assert R.TARGET_WIDTH % 2 == 0
    for content_h in (101, 903, 1001):
        scale = R.TARGET_WIDTH / 300
        size = (R.TARGET_WIDTH, max(2, round(content_h * scale) // 2 * 2))
        assert size[1] % 2 == 0, content_h
        frames = _rgba_frames(tmp_path / f"h{content_h}", size=(R.TARGET_WIDTH, size[1]))
        out = str(tmp_path / f"even_{content_h}.mp4")
        R.pack_rgba_frames(frames, out, size)      # raises if the dimension is rejected
        assert os.path.exists(out)


def test_despill_strips_the_fringe_and_leaves_bolt_alone():
    """Magenta is R and B above G. Bolt is white (R=G=B), mint (G highest) and cyan (R lowest), so
    nothing on the character trips the rule — only the halo the key leaves behind."""
    px = np.array([[
        [255, 0, 255],      # pure magenta fringe
        [255, 200, 255],    # pale pink halo on a white edge
        [255, 255, 255],    # Bolt's white body
        [120, 230, 190],    # mint accent
        [120, 230, 255],    # cyan eye
        [14, 20, 40],       # navy visor
    ]], dtype=np.uint8)
    out = R._despill(px)
    assert out[0, 0].tolist() == [R.DESPILL_MARGIN, 0, R.DESPILL_MARGIN], "fringe not neutralised"
    assert out[0, 1][1] == 200 and out[0, 1][0] <= 208, "halo not pulled toward green"
    for i, name in ((2, "white"), (3, "mint"), (4, "cyan"), (5, "navy")):
        assert out[0, i].tolist() == px[0, i].tolist(), f"{name} was altered by the despill"


def test_a_fully_keyed_frame_is_reported_rather_than_shipped(tmp_path):
    """The characteristic i2v failure: the model replaces the flat magenta with a lit background,
    so the key removes everything. The clip still plays, and composites as nothing at all."""
    d = tmp_path / "empty"
    d.mkdir()
    for i in range(3):
        Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(d / f"{i:04d}.png")
    assert R._union_bbox([str(d / f"{i:04d}.png") for i in range(3)]) is None


def test_the_bounding_box_spans_every_frame_not_each_one(tmp_path):
    """Cropping each frame to its own content re-centres the character every frame and turns a fist
    pump into a jitter. One box for the clip keeps the motion where the animation put it."""
    frames = _rgba_frames(tmp_path, count=6)     # the disc travels 3px per frame
    paths = sorted(os.path.join(frames, f) for f in os.listdir(frames))
    box = R._union_bbox(paths)
    first = Image.open(paths[0]).getbbox()
    last = Image.open(paths[-1]).getbbox()
    assert box[1] <= first[1] and box[3] >= last[3]
    assert box[3] - box[1] > first[3] - first[1], "the union should be taller than a single frame"


def test_every_reaction_declares_a_beat_a_motion_and_its_own_check():
    """The beat length is the edit — it is where "reacts" stops and "performs" starts — and the
    extra check is what stops the audit passing a pose that is merely on-model but wrong."""
    assert len(R.REACTIONS) >= 3, "a library with fewer than three poses is not a library"
    for name, spec in R.REACTIONS.items():
        still, motion, extra, beat = spec
        assert "MAGENTA" in still, name
        assert extra and all(isinstance(c, str) for c in extra), name
        assert 0.5 <= beat <= 2.5, (name, beat)
        assert "hover-base" in still or "hover-base" in R.C.POSE_IDENTITY


def test_the_motion_rules_forbid_what_kling_does_by_default():
    """Left alone the model pushes the camera, relights the subject and dissolves the flat
    background the key depends on. Losing any one of these silently costs the cutout."""
    rules = R.MOTION_RULES.lower()
    assert "locked-off camera" in rules
    assert "flat magenta" in rules and "never relit" in rules
    assert "no morphing" in rules


@pytest.mark.skipif(not os.path.exists(os.path.join(R.OUT, "hyped.mp4")),
                    reason="reaction library not generated in this checkout")
def test_a_generated_reaction_composites_over_a_scene(tmp_path):
    """End-to-end on the committed asset: unpack, lay it over a solid plate, and require that both
    the plate and the character are visible in the result."""
    asset = os.path.join(R.OUT, "hyped.mp4")
    unpack, (w, h) = R.unpack_filter(asset, in_label="1:v")
    out = str(tmp_path / "composited.png")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", f"color=c=green:s={w}x{h}:d=0.1:r=30",
                    "-i", asset, "-filter_complex",
                    f"{unpack};[0:v][rx]overlay=0:0,format=rgb24[o]",
                    "-map", "[o]", "-frames:v", "1", out], check=True)
    arr = np.array(Image.open(out).convert("RGB"))
    green = ((arr[..., 1] > 100) & (arr[..., 0] < 60) & (arr[..., 2] < 60)).mean()
    assert green > 0.2, "the plate is not visible — the matte is opaque everywhere"
    assert green < 0.95, "only the plate is visible — nothing was composited"


def test_the_audit_extraction_terminates(tmp_path):
    """The plate the frames are flattened onto is an infinite ``color=`` source, and overlay repeats
    its last frame by default — so without ``shortest=1`` this graph never ends. It wrote 389,195
    stills and 5.9 GB before anything noticed, and nothing about it errored: ffmpeg did exactly what
    it was asked, and the clip it produced was fine.

    A frame count matching the clip is the whole assertion. Anything unbounded fails by filling a
    disk, which is a bad way to find out.
    """
    frames = _rgba_frames(tmp_path, count=8)
    asset = str(tmp_path / "a.mp4")
    R.pack_rgba_frames(frames, asset, (120, 200))
    probe = tmp_path / "probe"
    probe.mkdir()
    out = R.extract_audit_frames(asset, str(probe))
    assert 0 < len(out) <= 12, f"expected ~8 frames, got {len(out)}"
    assert len(out) < R.AUDIT_FRAME_CAP


def test_the_scratch_sweep_keeps_what_cost_money(tmp_path):
    """Re-keying is only free while the bought clip is still on disk, so the sweep has to be able to
    tell a regenerable frame dump from a purchase."""
    work = tmp_path / "w"
    for scratch in ("frames", "crop", "audit"):
        (work / scratch).mkdir(parents=True)
        (work / scratch / "0001.png").write_bytes(b"x")
    (work / "r.png.raw.png").write_bytes(b"seed")
    (work / "r.i2v.mp4").write_bytes(b"bought")
    R._sweep_scratch(str(work))
    assert not (work / "frames").exists() and not (work / "audit").exists()
    assert (work / "r.png.raw.png").exists(), "the magenta seed was swept"
    assert (work / "r.i2v.mp4").exists(), "the clip that cost money was swept"


def test_an_asset_without_a_passing_audit_is_not_treated_as_built(tmp_path, monkeypatch):
    """Keying writes the file and the audit runs after it, so a run interrupted in between leaves a
    perfectly playable clip that nothing ever graded. The reuse check tested for the file, so every
    later run skipped it — the one asset most worth grading was the one guaranteed never to be.
    """
    monkeypatch.setattr(R, "OUT", str(tmp_path))
    asset = tmp_path / "smug.mp4"
    asset.write_bytes(b"not really a clip")

    assert not R.is_built("smug"), "a file with no report entry counted as finished"

    report = tmp_path / "reaction_report.json"
    report.write_text(json.dumps({"smug": {"passed": True, "reused": True}}))
    assert not R.is_built("smug"), "a 'reused' entry is not evidence of an audit"

    report.write_text(json.dumps({"smug": {"passed": False, "audit": {"pass": False}}}))
    assert not R.is_built("smug"), "a failed audit counted as finished"

    report.write_text(json.dumps({"smug": {"passed": True, "audit": {"pass": True}}}))
    assert R.is_built("smug")


def test_a_partial_run_cannot_erase_verdicts_it_did_not_touch(tmp_path, monkeypatch):
    """The report is the record of what has been graded, not a log of one invocation. Rebuilt from
    scratch each run, generating a single reaction would drop every other reaction's audit and
    quietly mark the whole library ungraded."""
    monkeypatch.setattr(R, "OUT", str(tmp_path))
    (tmp_path / "reaction_report.json").write_text(
        json.dumps({"hyped": {"passed": True, "audit": {"pass": True}}}))
    (tmp_path / "hyped.mp4").write_bytes(b"clip")

    merged = dict(R.load_report())
    merged["dead"] = {"passed": True, "audit": {"pass": True}}
    assert set(merged) == {"hyped", "dead"}
    assert R.is_built("hyped", merged)


def test_playable_rejects_a_file_that_merely_exists(tmp_path):
    """Existence is not readability. A download truncated by a full disk leaves a plausible
    multi-megabyte mp4 with no moov atom — one of the five raw clips ended up exactly that way, and
    the only thing that reported it was ffmpeg refusing to open it."""
    assert not R.playable(str(tmp_path / "nope.mp4"))
    truncated = tmp_path / "truncated.mp4"
    truncated.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\xff" * 4096)
    assert not R.playable(str(truncated)), "a header with no moov counted as playable"

    frames = _rgba_frames(tmp_path, count=4)
    real = str(tmp_path / "real.mp4")
    R.pack_rgba_frames(frames, real, (120, 200))
    assert R.playable(real)


def test_an_asset_with_no_source_clip_is_graded_not_rebuilt(tmp_path, monkeypatch):
    """The normal state of a fresh clone: _raw/ is deliberately not committed, so every checked-out
    reaction has an asset and no source. Without this path the audit gate sends each one down the
    re-key branch and dies on a missing file; buying a new clip to grade one that already exists
    would be worse.
    """
    monkeypatch.setattr(R, "OUT", str(tmp_path))
    monkeypatch.setattr(R, "RAW", str(tmp_path / "_raw"))
    frames = _rgba_frames(tmp_path, count=4)
    R.pack_rgba_frames(frames, str(tmp_path / "clap.mp4"), (120, 200))

    calls = {}
    monkeypatch.setattr(R.ep, "_animate_one",
                        lambda *a, **k: calls.setdefault("bought", True))
    monkeypatch.setattr(R.C, "gen_with_preflight",
                        lambda *a, **k: calls.setdefault("still", True))
    monkeypatch.setattr(R, "audit_clip", lambda *a, **k: {"pass": True, "violations": []})

    costs = []
    out = R.build_reaction("clap", R.REACTIONS["clap"], costs)
    assert out.get("graded_in_place") is True
    assert out.get("passed") is True
    assert not calls, f"grading an existing asset spent money: {calls}"
    assert costs == []


def test_one_bad_reaction_does_not_abort_the_batch():
    """A corrupt clip halfway through a five-item run aborted the rest with a traceback, losing the
    work already paid for in the same invocation."""
    import inspect
    source = inspect.getsource(R.main)
    assert "except Exception" in source
    assert "FAILED" in source
    # The report is written after each reaction, not once at the end, so a later crash cannot
    # discard verdicts already earned.
    assert source.index("json.dump(report") > source.index("build_reaction(")
    assert "for name in wanted" in source


def _leaky_frames(tmp_path, count=20, leak_from=6):
    """Frames where a background progressively fills in from `leak_from` onward — the real i2v
    failure: the model honours the flat magenta for about half a second, then starts rendering the
    depth the motion implies, and depth means a background."""
    from PIL import ImageDraw
    d = tmp_path / "leak"
    d.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        im = Image.new("RGBA", (120, 200), (0, 0, 0, 0))
        dr = ImageDraw.Draw(im)
        if i >= leak_from:
            dr.rectangle([0, 0, 119, 199], fill=(30, 30, 40, 255))
        dr.ellipse([30, 60, 90, 140], fill=(255, 255, 255, 255))
        im.save(d / f"{i:04d}.png")
    return sorted(str(d / f) for f in sorted(os.listdir(d)))


def test_the_leak_gate_finds_where_the_background_starts_filling_in(tmp_path):
    """Corners are the tell. The crop is the character's bounding box plus padding, so a limb can
    reach an EDGE — a raised fist regularly does — but nothing about the character reaches all four
    CORNERS. Measured across the first five reactions, corner opacity was 0.000 on every clean frame
    and 0.5-1.0 on every leaked one, with nothing in between."""
    frames = _leaky_frames(tmp_path, count=20, leak_from=6)
    assert R.clean_prefix(frames) == 6

    clean = _rgba_frames(tmp_path / "ok", count=10)
    paths = sorted(os.path.join(clean, f) for f in os.listdir(clean))
    assert R.clean_prefix(paths) == 10, "a clean clip was trimmed"


def test_a_clip_that_leaks_immediately_is_refused_rather_than_shortened(tmp_path):
    """Trimming is the salvage, but only down to a beat that can still read. Three of the first five
    reactions leaked at 0.43-0.47s, and shipping a 0.4s 'reaction' would be shipping a flicker."""
    frames = _leaky_frames(tmp_path, count=40, leak_from=3)   # 0.1s of clean content
    assert R.clean_prefix(frames) == 3
    assert 3 / R.FPS < R.MIN_BEAT_SEC


def test_the_leak_gate_is_mechanical_not_a_vision_call():
    """The VLM audit passed all three leaked clips, and it was right to: asked whether the robot is
    on-model it correctly said yes, because it was. The halo is a pixel fact, so the gate that
    catches it has to measure pixels."""
    import inspect
    source = inspect.getsource(R.clean_prefix) + inspect.getsource(R._leak_stats)
    assert "preflight" not in source and "claude" not in source.lower()
    assert R.LEAK_CORNER_MAX < 0.25, "corners must stay essentially transparent"


def test_a_rejected_key_takes_the_superseded_asset_with_it():
    """Leaving the old file on disk keeps a clip the gate just refused in the directory a consumer
    globs — and it is committed by the same rule that commits the good ones."""
    import inspect
    source = inspect.getsource(R.build_reaction)
    # The removal has to sit inside the branch that handles a failed key, not merely somewhere in
    # the function — an unconditional remove would delete a good asset on every rebuild.
    failed_branch = source.split("if not keyed.get(\"ok\"):", 1)
    assert len(failed_branch) == 2, "the failed-key branch moved"
    tail = failed_branch[1].split("return", 1)[0]
    assert "os.remove(out_path)" in tail, "a rejected key leaves the superseded asset on disk"
    assert "os.path.exists(out_path)" in tail, "the removal is unguarded"
