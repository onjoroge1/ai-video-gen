"""scripts/audit_film.py measures the film that shipped: every channel of its audio, its shots in
the order they play, the title and hook recorded by the attempt that rendered it, the runtime it
was asked for, and only the rendered contract that describes its bytes.

Each test pins a defect measured on a delivered bees film (the comments in audit_film.py carry the
numbers): a +3 dB peak from libswresample's unnormalised mono fold, a "no clipping" verdict that was
a headroom rule, a runtime target that was the literal 300, the first-minute preview's contract
graded as the film, leftover sample frames from a longer film, and script metrics read from a
_state.json a later attempt had overwritten. Real ffmpeg/ffprobe are used, as the rest of the
suite does; the tiny films are synthesised with lavfi.
"""
import hashlib
import json
import os
import subprocess
import wave

import numpy as np
from PIL import Image

from scripts import accept_v4 as av
from scripts import audit_film as af

HEADROOM = "peak headroom (sample peak <= -0.5 dBFS)"
CLIPPING = "no clipping (no run of samples >= -0.1 dBFS)"
RUNTIME = "runtime within 15% of target"
CONTRACT = "contract score >= 85 with no hard failures"
CUTS = "cut-to-cut change >= 24"
DEAD = "no dead stretch (flattest window >= 8)"


def _write_wav(path, channels, rate=32000):
    """channels: float arrays in [-1, 1], interleaved as 16-bit PCM (exact under ffmpeg's decode)."""
    data = np.stack(channels, axis=1)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(len(channels))
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes((data * 32767).astype("<i2").tobytes())


def _make_film(path, seconds=6):
    """A silent red film of `seconds`, so ffprobe has a duration and ffmpeg has frames to sample."""
    subprocess.run([af._binary("ffmpeg"), "-v", "error", "-y", "-f", "lavfi",
                    "-i", f"color=c=red:s=64x36:d={seconds}:r=10", "-c:v", "mpeg4", "-pix_fmt", "yuv420p",
                    str(path)], check=True)


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
    peak = float(_detail(sec, HEADROOM).split()[1])
    assert abs(peak - (-0.92)) < 0.15, sec
    assert _passed(sec, HEADROOM)
    assert _passed(sec, CLIPPING)
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
    assert abs(float(_detail(sec, HEADROOM).split()[1]) - (-0.92)) < 0.15, sec
    assert abs(float(_detail(sec, "loudness in range").split()[0]) - (-9.03)) < 0.15, sec
    assert any("1 ch @ 32000 Hz" in line for line in sec["info"]), sec["info"]


def test_headroom_and_clipping_are_two_checks(tmp_path):
    """killerbees02 peaks at -0.21 dBFS with zero clipped samples and failed "no clipping". The -0.5
    line is headroom against the master's -1 dBTP target; clipping is a run of pinned samples."""
    rate = 32000
    tone, _ = _tone_with_spike(rate)
    hot = tone.copy()
    hot[rate + rate // 2] = 0.999  # one sample at -0.01 dBFS: over the headroom line, not a clip
    _write_wav(tmp_path / "hot.wav", [hot, tone], rate)
    sec = af.audit_audio(str(tmp_path / "hot.wav"))
    assert not _passed(sec, HEADROOM)
    assert _detail(sec, HEADROOM).endswith("dBFS sample peak; master targets -1 dBTP"), sec
    assert _passed(sec, CLIPPING)
    assert _detail(sec, CLIPPING).startswith("0 run(s) of 2+ samples at/above -0.1 dBFS, longest 1; 1 such"), sec
    # 200 consecutive samples pinned at 0.999 is a flat top: the waveform was cut, not peaked.
    clipped = tone.copy()
    clipped[rate:rate + 200] = 0.999
    _write_wav(tmp_path / "clipped.wav", [tone, clipped], rate)
    sec = af.audit_audio(str(tmp_path / "clipped.wav"))
    assert not _passed(sec, CLIPPING)
    assert _detail(sec, CLIPPING).startswith("1 run(s) of 2+ samples at/above -0.1 dBFS, longest 200;"), sec


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


def _frame_records(frames):
    # Scenes: shots 0-3, 4-8, 9-11; two seconds a shot, so the film is 24 s long. shot_index
    # restarts at 0 in each scene, as the gate writes it (killerbees02: scene 0 shot 0, scene 1
    # shot 0, ...); only the frame path and the timing number the shots globally.
    scene = [0 if i < 4 else 1 if i <= 8 else 2 for i in range(12)]
    return [{"frame_path": str(frames / f"shot_{i:03d}_mid.jpg"), "shot_index": i - scene.index(scene[i]),
             "scene_index": scene[i], "global_start_sec": 2.0 * i, "global_end_sec": 2.0 * i + 2.0}
            for i in range(12)]


def _write_contract(job, frames, name="rendered_contract_full.json", **inspection):
    inspection["frames"] = _frame_records(frames)
    (job / name).write_text(json.dumps({"inspection": inspection}))


def test_imagery_measures_shot_mids_in_time_order_and_splits_by_scene(tmp_path):
    frames = _make_frames(tmp_path)
    _write_contract(tmp_path, frames)
    sec = af.audit_imagery(str(tmp_path), str(tmp_path / "explainer.mp4"))
    assert sec["info"][0].startswith("frames: 12 shot mid-frames"), sec["info"]
    dead = _detail(sec, DEAD)
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
    # A contract that names no video is taken to be the film's, and says so.
    assert any(l.startswith("rendered_contract_full.json names no video; assumed") for l in sec["info"])


def test_preview_contract_frames_are_not_the_films_timing(tmp_path):
    """rendered_contract.json describes first_minute_preview.mp4. Its frames must not position the
    film's dead stretch "of runtime"; without the film's own timing the detail says what it is."""
    frames = _make_frames(tmp_path)
    (tmp_path / "explainer.mp4").write_bytes(b"film")
    _write_contract(tmp_path, frames, name="rendered_contract.json",
                    video_path="/jobs/x/first_minute_preview.mp4", video_sha256="f" * 64)
    sec = af.audit_imagery(str(tmp_path), str(tmp_path / "explainer.mp4"))
    assert any(l.startswith("rendered_contract.json describes first_minute_preview.mp4") for l in sec["info"]), sec["info"]
    dead = _detail(sec, DEAD)
    assert "of runtime" not in dead and dead.endswith("positions are frame-index shares (no contract timing)"), dead
    assert "mean |dRGB| within-scene / across-scene: n/a (no scene_index on frames)" in sec["info"]
    assert _passed(sec, "shot grammar passes") is None  # no plan on disk either
    assert _detail(sec, "shot grammar passes") == "not graded: no scene plan on disk"


def test_time_positions_report_whether_they_are_timed():
    paths = ["a.jpg", "b.jpg", "c.jpg"]
    timed = {p: {"global_start_sec": 2.0 * i, "global_end_sec": 2.0 * i + 2.0} for i, p in enumerate(paths)}
    pos, flag = af._time_positions(paths, timed)
    assert flag and [round(p, 3) for p in pos] == [round(1 / 6, 3), 0.5, round(5 / 6, 3)]
    pos, flag = af._time_positions(paths, {"a.jpg": timed["a.jpg"]})  # one frame timed is not timing
    assert not flag and pos == [0.0, 0.5, 1.0]


def test_sampled_frames_dir_is_cleared_and_steps_are_not_graded_as_cuts(tmp_path):
    """ffmpeg -y overwrites f_0001.. but never deletes: a 6 s film audited after a longer one in
    the same dir inherited the longer film's frames. And a 3 s step is not a cut."""
    _make_film(tmp_path / "explainer.mp4", 6)
    old = tmp_path / "_audit_frames"
    old.mkdir()
    for i in range(1, 41):
        _solid(old / f"f_{i:04d}.jpg", PALETTE[i % 4])
    sec = af.audit_imagery(str(tmp_path), str(tmp_path / "explainer.mp4"))
    left = sorted(os.listdir(old))
    assert 1 <= len(left) <= 3, left  # 6 s at 1 per 3 s
    assert sec["info"][0].startswith(f"frames: {len(left)} sampled 1 per 3 s"), sec["info"]
    assert _passed(sec, CUTS) is None
    assert _detail(sec, CUTS).endswith("; 3 s steps, not cuts: ungraded"), sec
    assert "frame-index shares (no contract timing)" in _detail(sec, DEAD)
    assert not any(c["pass"] is False and c["check"] == CUTS for c in sec["checks"])


def _write_job(job, state_hook="A later hook"):
    (job / "explainer.mp4").write_bytes(b"")
    (job / "run_result.json").write_text(json.dumps(
        {"title": "Shipped Title", "hook": "Why did twenty-six swarms escape?"}))
    scenes = [{"narration": "One thing happened here.", "claim_refs": ["c1"], "shot_type": "medium"},
              {"narration": "Then another thing happened.", "claim_refs": ["c2"], "shot_type": "close"}]
    (job / "_state.json").write_text(json.dumps(
        {"script": {"title": "Later Attempt Title", "hook": state_hook, "scenes": scenes}}))


def _edit_json(path, fn):
    data = json.loads(path.read_text())
    fn(data)
    path.write_text(json.dumps(data))


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
    # was skipped, never crash. The film here is an empty file and run_result has no duration, so
    # there is no runtime to grade either.
    (tmp_path / "_state.json").unlink()
    (tmp_path / "run_result.json").write_text(json.dumps({"title": "T", "hook": "Why did the bees leave?"}))
    sec = af.audit_script(str(tmp_path), str(tmp_path / "explainer.mp4"))
    assert sec["note"] == "no _state.json; scene checks skipped; no film duration on disk"
    assert {c["check"] for c in sec["checks"]} == {"hook within budget", "hook carries the opening devices"}
    assert "title from run_result.json" in af.audit_packaging(str(tmp_path))["info"]


def test_runtime_target_is_read_from_the_request_on_disk_in_order(tmp_path):
    """generation_manifest.json carries no target, so the old check compared against a literal
    300. The request is on disk in five places; each is used in turn, named, and the FILM's
    duration is what is compared, with the narration estimate kept as a labelled detail."""
    _write_job(tmp_path)  # explainer.mp4 is empty, so ffprobe fails and run_result's duration is used
    state, result = tmp_path / "_state.json", tmp_path / "run_result.json"
    _edit_json(state, lambda d: d["script"].update(_runtime_plan={"target_seconds": 240},
                                                   _story_contract={"target_runtime_sec": 200}))
    _edit_json(result, lambda d: d.update(duration_sec=230.0))
    (tmp_path / "audio_timing_report.json").write_text(json.dumps({"target_seconds": 180}))
    (tmp_path / "retention_report.json").write_text(json.dumps({"contract": {"target_runtime_sec": 150}}))
    (tmp_path / "generation_manifest.json").write_text(json.dumps({"music": {"spec": {"duration_sec": 120}}}))
    film = str(tmp_path / "explainer.mp4")

    sec = af.audit_script(str(tmp_path), film)
    assert "runtime target 240s from _state.json script._runtime_plan.target_seconds" in sec["info"]
    detail = _detail(sec, RUNTIME)
    assert detail.startswith("film 230s vs 240s target (run_result.json duration_sec); narration estimate "), detail
    assert detail.endswith("(8 words)") and _passed(sec, RUNTIME), detail

    expected = [
        (lambda d: d["script"].pop("_runtime_plan"), 200, "_state.json script._story_contract.target_runtime_sec"),
        (lambda d: d["script"].pop("_story_contract"), 180, "audio_timing_report.json target_seconds"),
        (lambda d: (tmp_path / "audio_timing_report.json").unlink(), 150, "retention_report.json contract.target_runtime_sec"),
        (lambda d: (tmp_path / "retention_report.json").unlink(), 120, "generation_manifest.json music.spec.duration_sec"),
        (lambda d: (tmp_path / "generation_manifest.json").unlink(), 300, "default (no target on disk)"),
    ]
    for remove, target, source in expected:
        _edit_json(state, remove)
        sec = af.audit_script(str(tmp_path), film)
        assert f"runtime target {target}s from {source}" in sec["info"], (source, sec["info"])
        assert _detail(sec, RUNTIME).startswith(f"film 230s vs {target}s target"), _detail(sec, RUNTIME)
    assert _passed(sec, RUNTIME) is False  # 230 s against the 300 s default


def test_runtime_compares_the_film_by_ffprobe(tmp_path):
    _write_job(tmp_path)
    _make_film(tmp_path / "explainer.mp4", 6)
    _edit_json(tmp_path / "_state.json", lambda d: d["script"].update(_runtime_plan={"target_seconds": 6}))
    _edit_json(tmp_path / "run_result.json", lambda d: d.update(duration_sec=300.0))  # must lose to ffprobe
    sec = af.audit_script(str(tmp_path), str(tmp_path / "explainer.mp4"))
    assert _detail(sec, RUNTIME).startswith("film 6s vs 6s target (ffprobe); narration estimate"), _detail(sec, RUNTIME)
    assert _passed(sec, RUNTIME)


def test_runtime_is_graded_from_the_film_when_the_script_is_absent(tmp_path):
    """bees_v4_diag_wzq0m1k2yQY has no _state.json, but run_result.json says 102.6 s; the Script
    section used to skip the runtime check entirely."""
    (tmp_path / "explainer.mp4").write_bytes(b"")
    (tmp_path / "run_result.json").write_text(json.dumps(
        {"title": "T", "hook": "Why did the bees leave?", "duration_sec": 102.6}))
    sec = af.audit_script(str(tmp_path), str(tmp_path / "explainer.mp4"))
    assert sec["note"] == "no _state.json; scene checks skipped"
    assert "runtime target 300s from default (no target on disk)" in sec["info"]
    assert _detail(sec, RUNTIME) == "film 103s vs 300s target (run_result.json duration_sec)"
    assert _passed(sec, RUNTIME) is False
    # With the snapshot's own report present, the target comes from it rather than the default.
    (tmp_path / "audio_timing_report.json").write_text(json.dumps({"target_seconds": 100}))
    sec = af.audit_script(str(tmp_path), str(tmp_path / "explainer.mp4"))
    assert "runtime target 100s from audio_timing_report.json target_seconds" in sec["info"]
    assert _passed(sec, RUNTIME)


def _contract(score=87, **inspection):
    return {"score": score, "status": "AUTOMATED_PASS_AWAITING_HUMAN", "passed": False, "publishable": False,
            "hard_failures": [], "human_review": {"status": "pending", "decision": "pending"},
            "inspection": dict({"deterministic": {"long_hold_count": 0, "max_visual_state_sec": 3.06,
                                                  "average_visual_state_sec": 2.01, "shot_count": 23,
                                                  "per_cut_verification_ratio": 1.0}}, **inspection)}


def test_structure_grades_only_the_contract_that_describes_the_film(tmp_path):
    """rendered_contract.json is the first-minute preview's gate (23 shots against the film's 57
    on bees_c). Matched on video_sha256 first, basename(video_path) second."""
    film = tmp_path / "explainer.mp4"
    film.write_bytes(b"the film's bytes")
    film_sha = hashlib.sha256(b"the film's bytes").hexdigest()
    (tmp_path / "rendered_contract.json").write_text(json.dumps(
        _contract(video_path="/jobs/x/first_minute_preview.mp4", video_sha256="c" * 64)))
    sec = af.audit_structure(str(tmp_path), str(film))
    assert any(l.startswith("rendered_contract.json describes first_minute_preview.mp4 (sha cccccccccccc, film "
                            f"{film_sha[:12]}), not this explainer.mp4") for l in sec["info"]), sec["info"]
    for label in (CONTRACT, "no long visual hold", "cadence in band", "every cut verified"):
        assert _passed(sec, label) is None, label
        assert _detail(sec, label) == "no rendered contract describes this film"
    assert _passed(sec, "retention readiness at or above 80") is False  # still graded: not contract-bound
    assert sec["score"] == 0

    # The full contract carrying the film's own sha is graded, named for what it tests, and its
    # own verdict (passed:false, publishable:false, awaiting a human) travels with the PASS.
    (tmp_path / "rendered_contract_full.json").write_text(json.dumps(
        _contract(video_path="/jobs/x/explainer.mp4", video_sha256=film_sha)))
    sec = af.audit_structure(str(tmp_path), str(film))
    assert _passed(sec, CONTRACT) is True
    assert _detail(sec, CONTRACT) == ("87/100 AUTOMATED_PASS_AWAITING_HUMAN; passed=False publishable=False "
                                      "review=pending")
    assert ("contract verdict: 87/100 AUTOMATED_PASS_AWAITING_HUMAN; passed=False publishable=False "
            "review=pending (rendered_contract_full.json for explainer.mp4, matched by sha256)") in sec["info"]
    assert _passed(sec, "cadence in band") is True
    # A hard failure fails the check whatever the score, and is named in the detail.
    (tmp_path / "rendered_contract_full.json").write_text(json.dumps(dict(
        _contract(video_path="/jobs/x/explainer.mp4", video_sha256=film_sha), hard_failures=["visual_state_cadence"])))
    sec = af.audit_structure(str(tmp_path), str(film))
    assert _passed(sec, CONTRACT) is False
    assert _detail(sec, CONTRACT) == ("87/100 AUTOMATED_PASS_AWAITING_HUMAN; hard visual_state_cadence; "
                                      "passed=False publishable=False review=pending")

    # Same filename, different bytes: an earlier render of explainer.mp4 is caught by the sha.
    (tmp_path / "rendered_contract_full.json").write_text(json.dumps(
        _contract(video_path="/jobs/x/explainer.mp4", video_sha256="0" * 64)))
    sec = af.audit_structure(str(tmp_path), str(film))
    assert _passed(sec, CONTRACT) is None
    assert any("rendered_contract_full.json describes explainer.mp4 (sha 000000000000" in l for l in sec["info"])

    # No sha on either side: the basename decides.
    (tmp_path / "rendered_contract_full.json").write_text(json.dumps(_contract(video_path="/jobs/x/explainer.mp4")))
    sec = af.audit_structure(str(tmp_path), str(film))
    assert _passed(sec, CONTRACT) is True
    assert any("matched by basename" in l for l in sec["info"])


def test_shot_grammar_is_not_graded_from_a_stale_or_mismatched_state(tmp_path):
    """bees_c: a 14-scene failed attempt's _state.json was graded for a 13-scene film."""
    frames = _make_frames(tmp_path)
    _write_contract(tmp_path, frames)  # the film's contract shows 3 scenes
    scenes = [{"shot_type": t} for t in ("close", "medium", "close")]
    (tmp_path / "_state.json").write_text(json.dumps({"script": {"scenes": scenes}}))
    film = str(tmp_path / "explainer.mp4")
    sec = af.audit_imagery(str(tmp_path), film)
    assert _passed(sec, "shot grammar passes") is True, sec
    assert "shot sizes from _state.json script.scenes (3 scenes)" in sec["info"]
    # The staleness decided in main is honoured here too, warning included.
    sec = af.audit_imagery(str(tmp_path), film, stale="_state.json is newer than the film by 649s; later attempt")
    assert _passed(sec, "shot grammar passes") is None
    assert _detail(sec, "shot grammar passes").startswith("not graded: shot sizes would come from a _state.json newer")
    assert any(l.startswith("WARNING _state.json is newer than the film by 649s") for l in sec["info"])
    # Not stale by mtime, but the plan has one scene more than the film's own contract shows.
    (tmp_path / "_state.json").write_text(json.dumps({"script": {"scenes": scenes + [{"shot_type": "wide"}]}}))
    sec = af.audit_imagery(str(tmp_path), film)
    assert _detail(sec, "shot grammar passes") == "not graded: _state.json has 4 scenes but the film's contract shows 3"
    # When the contract's frames carry a shot size per shot they win, being the film's by sha.
    records = _frame_records(frames)
    for rec in records:
        rec["shot_type"] = "wide"
    (tmp_path / "rendered_contract_full.json").write_text(json.dumps({"inspection": {"frames": records}}))
    sec = af.audit_imagery(str(tmp_path), film)
    assert "shot sizes from rendered_contract_full.json inspection.frames (12 shots)" in sec["info"]
    assert _passed(sec, "shot grammar passes") is False and "consecutive wides" in _detail(sec, "shot grammar passes")


def test_sections_leave_ungraded_checks_out_of_the_total():
    sec = af._section("S", [("a", True, "", 3), ("b", None, "", 3), ("c", False, "", 1)])
    assert sec["score"] == 75 and [c["pass"] for c in sec["checks"]] == [True, None, False]


def test_accept_v4_reads_the_hook_from_run_result_at_the_audits_floor(tmp_path, monkeypatch, capsys):
    """accept_v4 read the hook from _state.json and passed it at 68 while the audit and the
    pipeline's degraded reason use 70 on run_result.json's hook. One helper, one floor."""
    _write_job(tmp_path, state_hook="Scientists at a Brazilian institute imported African bees.")
    film, state = tmp_path / "explainer.mp4", tmp_path / "_state.json"
    t = os.path.getmtime(film)
    os.utime(state, (t + 300, t + 300))
    monkeypatch.setattr(av, "_duration", lambda mp4: 300.0)
    monkeypatch.setattr(av, "_film_frames", lambda mp4, job, every=12: [])
    monkeypatch.setattr(av, "_ring_count", lambda thumb: 1)
    av.main(str(tmp_path))
    out = capsys.readouterr().out
    assert af.HOOK_FLOOR == 70
    assert "hook scores >= 70 (" in out and ">= 68" not in out, out
    assert "hook: 'Why did twenty-six swarms escape?' (from run_result.json)" in out, out
    assert "title: 'Shipped Title' (from run_result.json)" in out, out
    assert "WARNING  _state.json is newer than the film by 300s" in out, out
    # Every row that reads the scenes says where they came from.
    assert out.count("(from a _state.json newer than the film)") == 3, out
    # The normal case: state older than the film, no warning, no annotation.
    os.utime(state, (t - 300, t - 300))
    av.main(str(tmp_path))
    out = capsys.readouterr().out
    assert "WARNING" not in out and "newer than the film" not in out, out
