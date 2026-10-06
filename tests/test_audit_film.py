"""scripts/audit_film.py measures the film that shipped: every channel of its audio, its shots in
the order they play, and the title and hook recorded by the attempt that rendered it.

Each test pins a defect measured on the delivered bees film (the comments in audit_film.py carry
the numbers): a +3 dB peak from libswresample's unnormalised mono fold, a dead-stretch locator that
walked frames in filename order, and script metrics read from a _state.json a later attempt had
overwritten. Real ffmpeg/ffprobe are used, as the rest of the suite does.
"""
import json
import os
import wave

import numpy as np
from PIL import Image

from scripts import audit_film as af


def _write_wav(path, channels, rate=32000):
    """channels: float arrays in [-1, 1], interleaved as 16-bit PCM (exact under ffmpeg's decode)."""
    data = np.stack(channels, axis=1)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(len(channels))
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes((data * 32767).astype("<i2").tobytes())


def _detail(section, label):
    return next(c["detail"] for c in section["checks"] if c["check"] == label)


def _passed(section, label):
    return next(c["pass"] for c in section["checks"] if c["check"] == label)


def _tone_with_spike(rate):
    t = np.arange(3 * rate) / rate
    tone = 0.5 * np.sin(2 * np.pi * 440 * t)  # -6.02 dBFS per channel
    spiked = tone.copy()
    spiked[rate + rate // 2] = 0.9  # one sample at t=1.5 s where the tone crosses zero: -0.92 dBFS
    return tone, spiked


def test_audio_peak_is_the_loudest_channel_sample_not_the_mono_fold(tmp_path):
    rate = 32000
    tone, left = _tone_with_spike(rate)
    _write_wav(tmp_path / "stereo.wav", [left, tone], rate)
    sec = af.audit_audio(str(tmp_path / "stereo.wav"))
    # The old "-ac 1" decode folded L+R at 0.707 each: -3.0 dBFS for the tone and -3.9 dBFS for the
    # spike (R is 0 there), both wrong. The spike sits on one channel and must read as itself.
    peak = float(_detail(sec, "no clipping").split()[1])
    assert abs(peak - (-0.92)) < 0.15, sec
    assert _passed(sec, "no clipping")
    # Loudness is read on 0.5*(L+R): a 0.5 sine on both channels is -9.03 dBFS RMS.
    rms = float(_detail(sec, "loudness in range").split()[0])
    assert abs(rms - (-9.03)) < 0.15, sec
    assert _detail(sec, "silence under 14%") == "0.0%"
    assert any("2 ch @ 32000 Hz" in line for line in sec["info"]), sec["info"]


def test_audio_handles_a_mono_stream(tmp_path):
    rate = 32000
    _, mono = _tone_with_spike(rate)
    _write_wav(tmp_path / "mono.wav", [mono], rate)
    sec = af.audit_audio(str(tmp_path / "mono.wav"))
    assert abs(float(_detail(sec, "no clipping").split()[1]) - (-0.92)) < 0.15, sec
    assert abs(float(_detail(sec, "loudness in range").split()[0]) - (-9.03)) < 0.15, sec
    assert any("1 ch @ 32000 Hz" in line for line in sec["info"]), sec["info"]


def test_mid_frames_are_ordered_by_shot_index_not_filename(tmp_path):
    for name in ("shot_10_mid.jpg", "shot_9_mid.jpg", "shot_2_mid.jpg",
                 "cut_001_before.jpg", "cut_001_after.jpg"):
        (tmp_path / name).write_bytes(b"")
    got = [os.path.basename(p) for p in af._time_ordered_mid_frames(str(tmp_path))]
    assert got == ["shot_2_mid.jpg", "shot_9_mid.jpg", "shot_10_mid.jpg"]


PALETTE = [(220, 30, 30), (30, 30, 220), (30, 200, 30), (230, 220, 40)]


def _solid(path, rgb):
    Image.new("RGB", (48, 27), rgb).save(path, quality=95)


def _make_frames(job):
    frames = job / "rendered_gate_frames_full"
    frames.mkdir()
    # Shots 4-8 hold one grey card (the dead stretch); the rest cycle a loud palette.
    for i in range(12):
        _solid(frames / f"shot_{i:03d}_mid.jpg", (128, 128, 128) if 4 <= i <= 8 else PALETTE[i % 4])
    # Cut frames are identical black cards. In filename order they sort first and would read as a
    # dead stretch at the opening; they must not enter the measurements at all.
    for c in range(1, 21):
        for side in ("before", "after"):
            _solid(frames / f"cut_{c:03d}_{side}.jpg", (0, 0, 0))
    return frames


def _write_contract(job, frames):
    # Scenes: shots 0-3, 4-8, 9-11; two seconds a shot, so the film is 24 s long.
    records = [{"frame_path": str(frames / f"shot_{i:03d}_mid.jpg"),
                "scene_index": 0 if i < 4 else 1 if i <= 8 else 2,
                "global_start_sec": 2.0 * i, "global_end_sec": 2.0 * i + 2.0} for i in range(12)]
    (job / "rendered_contract_full.json").write_text(json.dumps({"inspection": {"frames": records}}))


def test_imagery_measures_shot_mids_in_time_order_and_splits_by_scene(tmp_path):
    frames = _make_frames(tmp_path)
    _write_contract(tmp_path, frames)
    sec = af.audit_imagery(str(tmp_path), str(tmp_path / "explainer.mp4"))
    assert sec["info"][0].startswith("frames: 12 shot mid-frames"), sec["info"]
    dead = _detail(sec, "no dead stretch (flattest window >= 8)")
    # The grey hold is shots 4-8 at 2 s a shot over 24 s: the window must land inside it, reported
    # as a share of runtime and as shot indices (not as a position among 52 files by name).
    assert dead.startswith("0.0 at ") and "of runtime (shots " in dead, dead
    lo, hi = map(int, dead.split("(shots ")[1].rstrip(")").split("-"))
    assert 4 <= lo < hi <= 8, dead
    pct_lo = int(dead.split(" at ")[1].split("%")[0])
    assert 30 <= pct_lo <= 45, dead  # shot 4's midpoint is 9 s of 24: 38%
    within = next(l for l in sec["info"] if l.startswith("mean |dRGB| within-scene"))
    across = next(l for l in sec["info"] if l.startswith("mean |dRGB| across-scene"))
    assert "(n=9;" in within and "(n=2;" in across, (within, across)  # 11 cuts, 2 cross a scene
    assert float(across.split()[3]) > float(within.split()[3])


def _write_job(job, state_hook="A later hook"):
    (job / "explainer.mp4").write_bytes(b"")
    (job / "run_result.json").write_text(json.dumps(
        {"title": "Shipped Title", "hook": "Why did twenty-six swarms escape?"}))
    scenes = [{"narration": "One thing happened here.", "claim_refs": ["c1"], "shot_type": "medium"},
              {"narration": "Then another thing happened.", "claim_refs": ["c2"], "shot_type": "close"}]
    (job / "_state.json").write_text(json.dumps(
        {"script": {"title": "Later Attempt Title", "hook": state_hook, "scenes": scenes}}))


def test_title_and_hook_come_from_run_result_and_a_newer_state_file_is_flagged(tmp_path):
    _write_job(tmp_path)
    film, state = tmp_path / "explainer.mp4", tmp_path / "_state.json"
    t = os.path.getmtime(film)
    os.utime(state, (t + 120, t + 120))
    script = af.audit_script(str(tmp_path), str(film))
    assert any("_state.json is newer than the film by 120s" in line for line in script["info"]), script["info"]
    assert "hook from run_result.json" in script["info"]
    assert _detail(script, "hook within budget") == "5 words"  # the shipped hook, not the 3-word later one
    pack = af.audit_packaging(str(tmp_path))
    assert "title from run_result.json" in pack["info"]
    assert "Shipped Title" in _detail(pack, "title within 100 chars")
    # A state file older than the film is the normal case and must not warn.
    os.utime(state, (t - 120, t - 120))
    assert not any("newer than the film" in line for line in af.audit_script(str(tmp_path), str(film))["info"])


def test_script_falls_back_to_state_and_degrades_without_it(tmp_path):
    _write_job(tmp_path)
    (tmp_path / "run_result.json").write_text(json.dumps({"status": "delivered"}))  # no title or hook
    script = af.audit_script(str(tmp_path), str(tmp_path / "explainer.mp4"))
    assert "hook from _state.json" in script["info"]
    assert _detail(script, "hook within budget") == "3 words"
    assert "title from _state.json" in af.audit_packaging(str(tmp_path))["info"]
    # The frozen delivery snapshot has no _state.json at all: grade the hook on record, say what
    # was skipped, never crash.
    (tmp_path / "_state.json").unlink()
    (tmp_path / "run_result.json").write_text(json.dumps({"title": "T", "hook": "Why did the bees leave?"}))
    sec = af.audit_script(str(tmp_path), str(tmp_path / "explainer.mp4"))
    assert sec["note"].startswith("no _state.json")
    assert {c["check"] for c in sec["checks"]} == {"hook within budget", "hook carries the opening devices"}
    assert "title from run_result.json" in af.audit_packaging(str(tmp_path))["info"]
