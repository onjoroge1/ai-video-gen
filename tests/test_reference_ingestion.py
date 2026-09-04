"""The ingester's measurements are checked against a video whose answers are already known.

The corpus is the source of truth for this lane, so a measurement bug propagates into every
constant derived from it — silently, because a wrong number looks exactly like a right one. The
first run of this script reported 1 visual state for a video with 65: `metadata=print:file=-`
writes to stdout and it was reading stderr. Zero cuts reads as "one long static shot", which is
the exact defect the corpus exists to detect.

These values were measured independently by hand before the script existed.
"""
import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "ingest_reference.py"
# In-repo, so a missing transcript can never be the reason this skips. It previously pointed
# into a session scratchpad that no longer exists, which made the measurement assertions below
# skip silently — passing everywhere while checking nothing.
SRT = ROOT / "references" / "transcripts" / "cobra_effect.srt"

# The video is a 16 MB binary that is not in the repo, so this one legitimately may be absent.
# Overridable, because hardcoding one machine's path is what broke the transcript above.
VIDEO_DIR = Path(os.environ.get("REFERENCE_VIDEO_DIR", "/Users/obadiah/Documents/video"))
VIDEO = VIDEO_DIR / "savefromins.com  1 720P 2.MP4"


def _module():
    spec = importlib.util.spec_from_file_location("ingest_reference", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_ingester_imports():
    assert hasattr(_module(), "build_draft")


def test_srt_parsing_is_exact(tmp_path):
    srt = tmp_path / "x.srt"
    srt.write_text("1\n00:00:03,500 --> 00:00:05,000\nHello there.\n\n"
                   "2\n00:01:02,250 --> 00:01:04,000\nSecond cue.\n", encoding="utf-8")
    cues = _module().read_srt(srt)
    assert cues == [(3.5, "Hello there."), (62.25, "Second cue.")]


def test_spoken_chapter_markers_are_found():
    module = _module()
    cues = [(0.0, "A thing happened."), (6.0, "Step one, it begins."),
            (40.0, "and then more"), (42.0, "Step two. It continues.")]
    assert [start for start, _ in module.spoken_chapters(cues)] == [6.0, 42.0]


@pytest.mark.skipif(not VIDEO.exists(), reason=f"reference video not present at {VIDEO}")
def test_measurements_match_the_hand_measured_reference():
    """Hand-measured before this script existed: 65 states, 3.38s mean, 183.6 wpm, -17.3 dB."""
    module = _module()
    _, measured = module.build_draft(VIDEO, "cobra", "backfiring_solution", module.read_srt(SRT))

    assert measured["visual_states"] == 65, "cut detection regressed — this was 1 when it read the wrong stream"
    assert measured["mean_hold_sec"] == pytest.approx(3.38, abs=0.05)
    assert measured["median_hold_sec"] == pytest.approx(3.37, abs=0.05)
    assert measured["words_per_minute"] == pytest.approx(183.6, abs=0.5)
    assert measured["mean_volume_db"] == pytest.approx(-17.3, abs=0.2)
    assert measured["spoken_chapter_markers"] == 6
    assert measured["hook_words"] == 15


@pytest.mark.skipif(not VIDEO.exists(), reason=f"reference video not present at {VIDEO}")
def test_roles_are_left_blank_for_a_human():
    """Role labelling is the judgement the corpus collects; a plausible guess looks finished."""
    module = _module()
    draft, _ = module.build_draft(VIDEO, "cobra", "backfiring_solution", module.read_srt(SRT))
    assert all(step["role"] == "" for step in draft["story"]["steps"])
    assert draft["story"]["opening_object"] == ""
    assert "DRAFT" in draft["note"]


def test_the_in_repo_transcript_is_present():
    """Guards the guard. The measurement tests above skip when the video is absent, which is fair —
    it is a binary outside the repo. The transcript is not, so if it goes missing this fails loudly
    instead of quietly downgrading those tests to no-ops."""
    assert SRT.exists(), f"in-repo reference transcript missing: {SRT}"
    assert len(_module().read_srt(SRT)) == 93
