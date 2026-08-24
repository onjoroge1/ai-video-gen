"""PR 6.5 calibration-harvest tests.

The rendered gate treats an uncalibrated profile as a hard failure, so the path from real renders
to a labeled dataset is load-bearing: without it every pilot caps at 69 against an 85 bar.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from longform_rendered_gate import (
    CALIBRATION_LABEL_FIELDS,
    MIN_CALIBRATION_EXAMPLES_PER_CLASS,
    MIN_CALIBRATION_VIDEOS_PER_SLIDESHOW_CLASS,
    calibrate_threshold_profile,
    calibration_readiness,
    harvest_calibration_samples,
    load_labeled_samples,
    validate_threshold_profile,
)


ROOT = Path(__file__).resolve().parents[1]


def _inspection(video_sha: str, *, cuts: int = 25, source_change_ratio: float = 0.8,
                pixel_base: float = 0.10) -> dict:
    return {
        "video_path": f"/renders/{video_sha[:8]}.mp4",
        "video_sha256": video_sha,
        "deterministic": {"source_change_ratio": source_change_ratio},
        "boundary_deltas": [
            {
                "shot_index": index,
                "time_sec": round(1.5 * index, 3),
                "pixel_delta": round(pixel_base + index / 1000, 4),
                "declared_new_information": True,
                "source_changed": True,
            }
            for index in range(1, cuts + 1)
        ],
    }


def _label(worksheet: dict, *, meaningful, slideshow) -> dict:
    for row in worksheet["samples"]:
        row["meaningful_change"] = meaningful(row) if callable(meaningful) else meaningful
        row["slideshow"] = slideshow(row) if callable(slideshow) else slideshow
    return worksheet


# ---------------------------------------------------------------------------------------------
# Harvest
# ---------------------------------------------------------------------------------------------

def test_harvest_produces_one_labelable_row_per_cut():
    worksheet = harvest_calibration_samples([_inspection("a" * 64, cuts=5)], dataset_id="pilot-1")
    assert len(worksheet["samples"]) == 5
    assert worksheet["dataset_id"] == "pilot-1"
    assert worksheet["videos"] == [
        {"video_sha256": "a" * 64, "cut_count": 5, "source_change_ratio": 0.8}]

    row = worksheet["samples"][0]
    assert row["sample_id"] == "aaaaaaaaaaaa-cut001"
    assert row["pixel_delta"] == 0.101
    assert row["source_change_ratio"] == 0.8


def test_harvested_labels_start_empty_and_are_not_seeded_from_planner_metadata():
    # declared_new_information is exactly the field the pixel threshold exists to audit. If the
    # harvester copied it into meaningful_change, the gate would calibrate itself against the
    # planner it is supposed to check.
    worksheet = harvest_calibration_samples([_inspection("b" * 64, cuts=3)])
    for row in worksheet["samples"]:
        assert row["meaningful_change"] is None
        assert row["slideshow"] is None
        assert row["context"]["declared_new_information"] is True
    assert set(CALIBRATION_LABEL_FIELDS) == {"meaningful_change", "slideshow"}


def test_sample_ids_are_unique_across_videos_and_traceable_to_bytes():
    worksheet = harvest_calibration_samples(
        [_inspection("c" * 64, cuts=4), _inspection("d" * 64, cuts=4)])
    ids = [row["sample_id"] for row in worksheet["samples"]]
    assert len(set(ids)) == len(ids) == 8
    assert all(row["sample_id"].startswith(row["video_sha256"][:12])
               for row in worksheet["samples"])


def test_the_same_video_harvested_twice_is_rejected_rather_than_double_counted():
    with pytest.raises(ValueError, match="duplicate sample_id"):
        harvest_calibration_samples([_inspection("e" * 64, cuts=3), _inspection("e" * 64, cuts=3)])


@pytest.mark.parametrize("mutate,message", [
    (lambda item: item.pop("video_sha256"), "video_sha256"),
    (lambda item: item.__setitem__("deterministic", {}), "source_change_ratio"),
    (lambda item: item.__setitem__("boundary_deltas", []), "no boundary cuts"),
])
def test_an_untraceable_or_unmeasured_inspection_is_refused(mutate, message):
    inspection = _inspection("f" * 64, cuts=3)
    mutate(inspection)
    with pytest.raises(ValueError, match=message):
        harvest_calibration_samples([inspection])


def test_a_cut_without_a_measurement_is_refused():
    inspection = _inspection("0" * 64, cuts=3)
    del inspection["boundary_deltas"][1]["pixel_delta"]
    with pytest.raises(ValueError, match="without a measurement"):
        harvest_calibration_samples([inspection])


# ---------------------------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------------------------

def test_a_fresh_worksheet_reports_every_class_as_outstanding():
    readiness = calibration_readiness(harvest_calibration_samples([_inspection("1" * 64)]))
    assert readiness["ready"] is False
    assert readiness["labeled_rows"] == 0
    assert readiness["unlabeled_rows"] == 25
    assert any("still unlabeled" in blocker for blocker in readiness["blockers"])
    assert all(count == 0 for count in readiness["counts"].values())


def test_readiness_names_the_exact_shortfall_per_class():
    worksheet = harvest_calibration_samples([_inspection("2" * 64, cuts=25)])
    _label(worksheet, meaningful=True, slideshow=False)
    readiness = calibration_readiness(worksheet)
    assert readiness["counts"]["meaningful_change"] == 25
    assert readiness["counts"]["not_meaningful_change"] == 0
    blockers = " ".join(readiness["blockers"])
    assert f"not_meaningful_change needs {MIN_CALIBRATION_EXAMPLES_PER_CLASS} more" in blockers
    assert f"slideshow needs {MIN_CALIBRATION_EXAMPLES_PER_CLASS} more" in blockers


def test_a_partially_labeled_row_is_malformed_not_silently_dropped():
    worksheet = harvest_calibration_samples([_inspection("3" * 64, cuts=3)])
    worksheet["samples"][0]["meaningful_change"] = True  # slideshow left null
    worksheet["samples"][1]["meaningful_change"] = "yes"
    readiness = calibration_readiness(worksheet)
    assert readiness["malformed_rows"] == 2
    assert any("partial or non-boolean" in blocker for blocker in readiness["blockers"])


def test_a_slideshow_label_from_one_video_cannot_calibrate_a_video_level_threshold():
    # 40 cuts, balanced meaningful_change, but every slideshow=True row comes from one render.
    worksheet = harvest_calibration_samples(
        [_inspection("4" * 64, cuts=40, source_change_ratio=0.2)])
    _label(worksheet, meaningful=lambda row: row["shot_index"] % 2 == 0, slideshow=True)
    readiness = calibration_readiness(worksheet)
    assert readiness["distinct_videos"]["slideshow"] == 1
    assert any("more distinct real video" in blocker for blocker in readiness["blockers"])
    assert readiness["minimum_videos_per_slideshow_class"] == \
        MIN_CALIBRATION_VIDEOS_PER_SLIDESHOW_CLASS


# ---------------------------------------------------------------------------------------------
# Compile and calibrate — the full path the roadmap requires
# ---------------------------------------------------------------------------------------------

def _viable_worksheet() -> dict:
    """Two slideshow renders and two developing renders, labeled consistently with measurement."""
    slideshow_videos = [
        _inspection("5" * 64, cuts=11, source_change_ratio=0.15, pixel_base=0.002),
        _inspection("6" * 64, cuts=11, source_change_ratio=0.20, pixel_base=0.004),
    ]
    developing_videos = [
        _inspection("7" * 64, cuts=11, source_change_ratio=0.75, pixel_base=0.30),
        _inspection("8" * 64, cuts=11, source_change_ratio=0.85, pixel_base=0.40),
    ]
    worksheet = harvest_calibration_samples(slideshow_videos + developing_videos,
                                            dataset_id="pr6.5-dataset")
    for row in worksheet["samples"]:
        row["slideshow"] = row["source_change_ratio"] < 0.5
        row["meaningful_change"] = row["pixel_delta"] >= 0.05
    return worksheet


def test_a_viable_dataset_compiles_and_calibrates_end_to_end():
    worksheet = _viable_worksheet()
    readiness = calibration_readiness(worksheet)
    assert readiness["ready"] is True, readiness["blockers"]
    assert readiness["distinct_videos"] == {"slideshow": 2, "not_slideshow": 2}

    samples = load_labeled_samples(worksheet)
    assert len(samples) == 44
    assert all(set(sample) == {"sample_id", "pixel_delta", "source_change_ratio",
                               "meaningful_change", "slideshow"} for sample in samples)

    profile = calibrate_threshold_profile(samples, reviewer="Calibration Editor",
                                          dataset_id="pr6.5-dataset")
    assert profile["status"] == "calibrated"
    assert validate_threshold_profile(profile, require_calibrated=True)["passed"]


def test_a_calibrated_profile_lifts_the_uncalibrated_hard_failure():
    from longform_rendered_gate import PROVISIONAL_THRESHOLD_PROFILE

    provisional = validate_threshold_profile(
        dict(PROVISIONAL_THRESHOLD_PROFILE), require_calibrated=True)
    assert provisional["passed"] is False

    profile = calibrate_threshold_profile(
        load_labeled_samples(_viable_worksheet()), reviewer="Calibration Editor")
    assert validate_threshold_profile(profile, require_calibrated=True)["passed"] is True


def test_compiling_an_unfinished_worksheet_fails_with_the_reason():
    worksheet = harvest_calibration_samples([_inspection("9" * 64, cuts=5)])
    with pytest.raises(ValueError, match="still unlabeled"):
        load_labeled_samples(worksheet)


def test_a_non_predictive_dataset_is_rejected_rather_than_weakly_accepted():
    worksheet = _viable_worksheet()
    # Labels that ignore the measurements entirely: no threshold can separate them.
    for index, row in enumerate(worksheet["samples"]):
        row["meaningful_change"] = index % 2 == 0
    with pytest.raises(ValueError, match="do not support a viable threshold"):
        calibrate_threshold_profile(load_labeled_samples(worksheet), reviewer="Editor")


# ---------------------------------------------------------------------------------------------
# Real inspection output — the join the harvester actually has to survive
# ---------------------------------------------------------------------------------------------

def _encode_three_shot_opening(path: Path) -> Path:
    subprocess.run([
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=red:s=320x180:d=2",
        "-f", "lavfi", "-i", "color=c=green:s=320x180:d=2",
        "-f", "lavfi", "-i", "color=c=blue:s=320x180:d=2",
        "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
        "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    ], check=True)
    return path


def test_harvest_consumes_genuine_inspect_rendered_opening_output(tmp_path):
    # Synthetic fixtures elsewhere in this module could drift from the real report shape without
    # failing, so harvest a real encode end to end.
    from longform_rendered_gate import inspect_rendered_opening

    video = _encode_three_shot_opening(tmp_path / "opening.mp4")
    plan = [[
        {"duration": 2.0, "source": f"a{index}", "state_id": f"s{index}",
         "verified_visible_information": True}
        for index in range(1, 4)
    ]]
    evidence = {"scenes": [{"states": [{"state_id": f"s{index}", "verification": {}}
                                       for index in range(1, 4)]}]}
    inspection = inspect_rendered_opening(str(video), plan, str(tmp_path), evidence)

    worksheet = harvest_calibration_samples([inspection], dataset_id="real-encode")
    # Three shots produce two cut boundaries.
    assert len(worksheet["samples"]) == 2
    row = worksheet["samples"][0]
    assert row["video_sha256"] == inspection["video_sha256"]
    assert row["sample_id"] == f"{inspection['video_sha256'][:12]}-cut001"
    assert row["pixel_delta"] == inspection["boundary_deltas"][0]["pixel_delta"]
    assert row["source_change_ratio"] == inspection["deterministic"]["source_change_ratio"]
    assert row["meaningful_change"] is None and row["slideshow"] is None

    # The frames an editor labels from are real files written by the inspection.
    frames = sorted((tmp_path / "rendered_gate_frames").glob("cut_*_*.jpg"))
    assert len(frames) == 4 and all(frame.stat().st_size > 0 for frame in frames)


# ---------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------

def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "harvest_gate_samples.py"), *args],
        capture_output=True, text=True, cwd=str(ROOT))


def test_cli_harvests_reports_and_compiles(tmp_path):
    inspections = []
    for index, inspection in enumerate([
        _inspection("5" * 64, cuts=11, source_change_ratio=0.15, pixel_base=0.002),
        _inspection("6" * 64, cuts=11, source_change_ratio=0.20, pixel_base=0.004),
        _inspection("7" * 64, cuts=11, source_change_ratio=0.75, pixel_base=0.30),
        _inspection("8" * 64, cuts=11, source_change_ratio=0.85, pixel_base=0.40),
    ]):
        path = tmp_path / f"inspection_{index}.json"
        path.write_text(json.dumps(inspection), encoding="utf-8")
        inspections.append(str(path))

    worksheet_path = tmp_path / "worksheet.json"
    harvested = _run_cli("harvest", *inspections, str(worksheet_path), "--dataset-id", "cli-run")
    assert harvested.returncode == 0, harvested.stderr
    assert "44 unlabeled row(s) from 4 video(s)" in harvested.stdout
    assert "Not ready:" in harvested.stdout

    # An unlabeled worksheet cannot be compiled.
    samples_path = tmp_path / "samples.json"
    failed = _run_cli("compile", str(worksheet_path), str(samples_path))
    assert failed.returncode != 0
    assert not samples_path.exists()

    worksheet = json.loads(worksheet_path.read_text(encoding="utf-8"))
    for row in worksheet["samples"]:
        row["slideshow"] = row["source_change_ratio"] < 0.5
        row["meaningful_change"] = row["pixel_delta"] >= 0.05
    worksheet_path.write_text(json.dumps(worksheet), encoding="utf-8")

    status = _run_cli("status", str(worksheet_path))
    assert status.returncode == 0
    assert "Dataset is ready to calibrate." in status.stdout

    compiled = _run_cli("compile", str(worksheet_path), str(samples_path))
    assert compiled.returncode == 0, compiled.stderr
    assert len(json.loads(samples_path.read_text(encoding="utf-8"))["samples"]) == 44

    profile_path = tmp_path / "profile.json"
    calibrated = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "calibrate_rendered_gate.py"),
         str(samples_path), str(profile_path), "--reviewer", "Calibration Editor"],
        capture_output=True, text=True, cwd=str(ROOT))
    assert calibrated.returncode == 0, calibrated.stderr
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert validate_threshold_profile(profile, require_calibrated=True)["passed"]
