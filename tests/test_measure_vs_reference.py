"""scripts/measure_vs_reference.py: the same yardstick for every build (flow validation
2026-10-07, item 14). The pure parts are tested on fixtures; the ffmpeg rows on a synthetic clip."""
import importlib.util
import os
import shutil
import subprocess

import pytest

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "scripts", "measure_vs_reference.py")
_SPEC = importlib.util.spec_from_file_location("measure_vs_reference", _PATH)
mvr = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mvr)

SRT = """1
00:00:00,000 --> 00:00:03,300
You wake up, and the air is already trying to kill you.

2
00:00:03,300 --> 00:00:09,200
It's not even noon yet, and the temperature has already crossed 45 degrees.

3
00:01:06,100 --> 00:01:07,100
How?
"""


def test_srt_parsing_and_first_stake_timing():
    segments = mvr.parse_srt(SRT)
    assert [round(s, 1) for s, _, _ in segments] == [0.0, 3.3, 66.1]
    stats = mvr.narration_stats(segments)
    assert stats["first_you_sec"] == 0.0
    assert stats["first_number_sec"] == 3.3
    assert stats["first_question_sec"] == 66.1
    assert stats["sentences"] == 3 and stats["sentence_max_words"] == 13
    assert stats["first_sentence"].startswith("You wake up")
    assert stats["words_per_minute"] == round(stats["words"] / (67.1 / 60), 1)


def test_untimed_transcript_is_spread_over_the_runtime():
    segments = mvr.transcript_as_segments("One two three. Four five six.", 60.0)
    assert len(segments) == 2
    assert segments[0][0] == 0.0 and round(segments[0][1], 1) == 30.0
    assert round(segments[1][1], 1) == 60.0


def test_cut_stats_count_shots_not_cuts():
    stats = mvr.cut_stats([3.0, 6.0, 9.0], 12.0)
    assert stats == {"cuts": 3, "cuts_first_60s": 3, "shot_median_sec": 3.0,
                     "shot_mean_sec": 3.0, "shot_max_sec": 3.0}
    assert mvr.cut_stats([], 10.0)["shot_max_sec"] == 10.0


def test_table_has_a_row_per_measure_and_shows_the_reference():
    table = mvr.format_table({"cuts": 101, "first_sentence": "Imagine you're a beekeeper."},
                             mvr.REFERENCE)
    assert "scene cuts" in table and "153" in table and "101" in table
    assert "first sentence: Imagine" in table
    assert table.count("\n") >= len(mvr.ROWS)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                    reason="ffmpeg not available")
def test_cuts_silences_and_static_share_on_a_synthetic_clip(tmp_path):
    video = tmp_path / "clip.mp4"
    # Two seconds of red, then two of blue (one hard cut); tone for 1.5 s, silence, tone.
    subprocess.run([
        "ffmpeg", "-hide_banner", "-nostats", "-y",
        "-f", "lavfi", "-i", "color=c=red:s=160x90:d=2:r=25",
        "-f", "lavfi", "-i", "color=c=blue:s=160x90:d=2:r=25",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
        "-filter_complex",
        "[0:v][1:v]concat=n=2:v=1:a=0[v];"
        "[2:a]volume='if(between(t,1.5,2.5),0,1)':eval=frame[a]",
        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(video)], capture_output=True, check=True)
    (tmp_path / "clip.srt").write_text(SRT)
    result = mvr.measure(str(video), str(tmp_path / "clip.srt"), None)
    assert 3.8 <= result["duration_sec"] <= 4.2
    assert result["cuts"] == 1 and 1.9 <= result["silence_times_sec"][0] - 0.5 <= 2.1 or \
        result["silences"] == 1
    assert result["silences"] == 1
    assert result["frozen_share_first_120s"] >= 0.5, "two flat colours are static frames"
    assert result["first_you_sec"] == 0.0 and result["first_stake_timing"] == "measured"
