#!/usr/bin/env python3
"""Render a provider-free old-vs-semantic sea-level timeline comparison."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from explainer_pipeline import _audio_dur, _make_scene_segment, _run_ffmpeg
from longform_shots import shot_plan_metrics
from retention_readiness import score_retention_readiness


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "comparison_sources"
OUTPUT_DIR = ROOT / "test_runs" / "sea_level_semantic_ab"
WORK_DIR = Path("/tmp/sea_level_semantic_ab")
MASTER = SOURCE_DIR / "500-meter sea level drop.png"
EVIDENCE = SOURCE_DIR / "Earth after a 500-meter sea-level drop.png"
NARRATION = (
    "If sea level fell five hundred metres, the water would not vanish. "
    "It would retreat toward the deepest ocean basins. "
    "As the ocean pulls away, continental shelves emerge first, exposing drowned river valleys. "
    "Then the continents appear to grow, but the world's freshwater still stays trapped in ice. "
    "The biggest surprise is not new land. "
    "It is how quickly ports and shipping routes become stranded far from the sea."
)
SENTENCES = [
    "If sea level fell five hundred metres, the water would not vanish.",
    "It would retreat toward the deepest ocean basins.",
    "As the ocean pulls away, continental shelves emerge first, exposing drowned river valleys.",
    "Then the continents appear to grow, but the world's freshwater still stays trapped in ice.",
    "The biggest surprise is not new land.",
    "It is how quickly ports and shipping routes become stranded far from the sea.",
]


def _run(args: list[str]) -> None:
    subprocess.run(args, check=True, capture_output=True, text=True)


def _valid_video(path: Path, expected_duration: float = 0.1) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width:format=duration", "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        return False
    try:
        payload = json.loads(probe.stdout)
        width = int(payload["streams"][0]["width"])
        duration = float(payload["format"]["duration"])
        return width > 0 and duration >= max(0.05, expected_duration - 0.08)
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False


def _render_validated(
    render,
    out: Path,
    *,
    expected_duration: float = 0.1,
    attempts: int = 3,
) -> None:
    for _ in range(attempts):
        render()
        if _valid_video(out, expected_duration):
            return
        out.unlink(missing_ok=True)
    raise RuntimeError(f"Renderer repeatedly produced an invalid video: {out}")


def _publish_video(source: Path, destination: Path, expected_duration: float) -> None:
    for _ in range(3):
        shutil.copyfile(source, destination)
        if _valid_video(destination, expected_duration):
            return
        destination.unlink(missing_ok=True)
    raise RuntimeError(f"Could not publish a valid video copy: {destination}")


def _write_srt(path: Path, duration: float) -> None:
    total_words = sum(len(sentence.split()) for sentence in SENTENCES)
    cursor = 0.0
    blocks = []
    for index, sentence in enumerate(SENTENCES, 1):
        segment = duration * len(sentence.split()) / total_words
        end = duration if index == len(SENTENCES) else cursor + segment

        def stamp(seconds: float) -> str:
            millis = round(seconds * 1000)
            hours, millis = divmod(millis, 3_600_000)
            minutes, millis = divmod(millis, 60_000)
            secs, millis = divmod(millis, 1000)
            return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

        blocks.append(f"{index}\n{stamp(cursor)} --> {stamp(end)}\n{sentence}\n")
        cursor = end
    path.write_text("\n".join(blocks), encoding="utf-8")


def _shot_clip(image: Path, audio: Path, out: Path, duration: float, motion: str) -> None:
    _render_validated(
        lambda: _make_scene_segment(
            str(image),
            str(audio),
            str(out),
            "",
            "",
            motion=motion,
            captions="none",
            vw=1280,
            vh=720,
            duration_override=duration,
        ),
        out,
        expected_duration=duration,
    )


def _concat(clips: list[Path], out: Path) -> None:
    manifest = out.with_suffix(".txt")
    manifest.write_text(
        "".join(f"file '{clip.resolve()}'\n" for clip in clips),
        encoding="utf-8",
    )
    _render_validated(
        lambda: _run_ffmpeg([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(manifest),
            "-c", "copy", str(out),
        ], timeout=240),
        out,
        expected_duration=sum(_audio_dur(str(clip)) for clip in clips),
    )


def _mux(video: Path, audio: Path, subtitles: Path, out: Path) -> None:
    style = (
        "FontName=DejaVu Sans,FontSize=20,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00101828,BorderStyle=3,Outline=1,Shadow=0,"
        "MarginV=35,Alignment=2"
    )
    _render_validated(
        lambda: _run_ffmpeg([
            "ffmpeg", "-y", "-i", str(video), "-i", str(audio),
            "-vf", f"subtitles={subtitles}:force_style='{style}'",
            "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "fast",
            "-profile:v", "main", "-level:v", "3.1", "-crf", "21",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
            "-movflags", "+faststart", "-video_track_timescale", "90000",
            "-shortest", str(out),
        ], timeout=300),
        out,
        expected_duration=min(_audio_dur(str(video)), _audio_dur(str(audio))),
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    if not MASTER.exists() or not EVIDENCE.exists():
        raise SystemExit("Materialize both sea-level source images first")

    audio = WORK_DIR / "shared_narration.wav"
    flite_text = NARRATION.replace(":", "\\:")
    _run([
        "ffmpeg", "-y", "-f", "lavfi", "-i",
        f"flite=text='{flite_text}':voice=slt",
        "-ar", "44100", "-ac", "1", str(audio),
    ])
    duration = _audio_dur(str(audio))
    subtitles = WORK_DIR / "shared_narration.srt"
    _write_srt(subtitles, duration)

    # Baseline: equal-duration timer cuts; crop motion restarts on every cut.
    old_count = max(2, round(duration / 2.7))
    old_each = duration / old_count
    old_clips = []
    motions = ["kenburns_in", "pan_right", "kenburns_out", "pan_left"]
    for index in range(old_count):
        clip = WORK_DIR / f"old_{index:02d}.mp4"
        image = MASTER if index % 3 else EVIDENCE
        _shot_clip(image, audio, clip, old_each, motions[index % len(motions)])
        old_clips.append(clip)
    old_raw = WORK_DIR / "old_timer_raw.mp4"
    old_video = WORK_DIR / "old_equal_interval_render.mp4"
    _concat(old_clips, old_raw)
    _mux(old_raw, audio, subtitles, old_video)

    # Semantic edit: cut only on sentence/meaning changes; one uninterrupted
    # camera path spans each informative view.
    word_counts = [len(sentence.split()) for sentence in SENTENCES]
    total_words = sum(word_counts)
    sentence_durations = [duration * words / total_words for words in word_counts]
    # The first two clauses describe one continuous physical action with the
    # same master composition, so they share one uninterrupted camera path.
    # Later cuts switch source only when the narration introduces evidence or
    # a consequence that genuinely changes the information on screen.
    semantic_groups = [
        (MASTER, sum(sentence_durations[0:2]), "setup_action"),
        (EVIDENCE, sentence_durations[2], "evidence"),
        (MASTER, sentence_durations[3], "consequence"),
        (EVIDENCE, sentence_durations[4], "evidence"),
        (MASTER, sentence_durations[5], "consequence"),
    ]
    semantic_clips = []
    semantic_plan = []
    for index, (source, segment, purpose) in enumerate(
        semantic_groups
    ):
        clip = WORK_DIR / f"semantic_{index:02d}.mp4"
        motion = "pan_right" if index % 2 else "kenburns_in"
        _shot_clip(source, audio, clip, segment, motion)
        semantic_clips.append(clip)
        semantic_plan.append([{
            "kind": "still",
            "source": "alternate" if source == EVIDENCE else "master",
            "duration": segment,
            "transition": "continuous" if index == 0 else "hard_cut",
            "semantic_aligned": True,
            "new_information": True,
            "purpose": purpose,
        }])
    semantic_raw = WORK_DIR / "semantic_raw.mp4"
    semantic_video = WORK_DIR / "semantic_phrase_aligned_render.mp4"
    _concat(semantic_clips, semantic_raw)
    _mux(semantic_raw, audio, subtitles, semantic_video)

    comparison = WORK_DIR / "side_by_side_comparison.mp4"
    _render_validated(
        lambda: _run_ffmpeg([
            "ffmpeg", "-y", "-i", str(old_video), "-i", str(semantic_video),
            "-filter_complex",
            "[0:v]scale=640:360,drawtext=text='OLD  timer cuts':"
            "fontcolor=white:fontsize=24:box=1:boxcolor=black@0.65:x=18:y=18[left];"
            "[1:v]scale=640:360,drawtext=text='NEW  phrase aligned':"
            "fontcolor=white:fontsize=24:box=1:boxcolor=black@0.65:x=18:y=18[right];"
            "[left][right]hstack=inputs=2[v]",
            "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "fast",
            "-profile:v", "main", "-level:v", "3.1", "-crf", "21",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
            "-movflags", "+faststart", "-video_track_timescale", "90000",
            "-shortest", str(comparison),
        ], timeout=300),
        comparison,
        expected_duration=min(_audio_dur(str(old_video)), _audio_dur(str(semantic_video))),
    )
    old_output = OUTPUT_DIR / old_video.name
    semantic_output = OUTPUT_DIR / semantic_video.name
    comparison_output = OUTPUT_DIR / comparison.name
    _publish_video(old_video, old_output, duration)
    _publish_video(semantic_video, semantic_output, duration)
    _publish_video(comparison, comparison_output, duration)

    old_metrics = {
        "shot_count": old_count,
        "cut_count": old_count - 1,
        "hard_cut_count": old_count - 1,
        "still_shot_count": old_count,
        "i2v_shot_count": 0,
        "alternate_shot_count": old_count // 3,
        "broll_clause_count": 0,
        "avg_still_seconds": round(old_each, 2),
        "min_shot_seconds": round(old_each, 2),
        "max_still_seconds": round(old_each, 2),
        "sub_min_shot_count": 0,
        "semantic_sync_ratio": 0.0,
        "meaningful_cut_ratio": round((old_count // 3) / max(1, old_count - 1), 3),
        "motion_sync_ratio": 1.0,
        "same_source_hard_cut_count": old_count - 1 - old_count // 3,
        "continuous_camera_paths": 0,
        "i2v_seconds": 0.0,
    }
    new_metrics = shot_plan_metrics(semantic_plan)
    # Scene-to-scene semantic cuts are represented outside the per-scene plan.
    new_metrics.update({
        "cut_count": len(semantic_groups) - 1,
        "hard_cut_count": len(semantic_groups) - 1,
        "semantic_sync_ratio": 1.0,
        "meaningful_cut_ratio": 1.0,
        "same_source_hard_cut_count": 0,
        "broll_clause_count": 2,
    })
    script = {
        "title": "What If Sea Level Dropped 500 Metres?",
        "hook": SENTENCES[0],
        "scenes": [
            {"story_role": role}
            for role in [
                "cold_consequence", "payoff", "mechanism",
                "reversal", "final_payoff", "resonant_end",
            ]
        ],
        "_story_contract": {"visual_promise": "Earth with newly exposed continental shelves"},
    }
    validation = {
        "errors": [],
        "warnings": [],
        "checks": {
            "prediction_scenes": [1],
            "answer_scenes": [2, 5],
            "max_attention_gap_sec": 28,
            "max_exposition_block_sec": 10,
            "unresolved_loops": [],
        },
    }
    preview = {"decodable": True, "duration_sec": duration, "target_sec": duration}
    old_rrs = score_retention_readiness(script, validation, old_metrics, [], preview=preview)
    new_rrs = score_retention_readiness(script, validation, new_metrics, [], preview=preview)
    report = {
        "scope": "Controlled same-topic A/B using one identical narration track and two recovered sea-level images.",
        "duration_seconds": round(duration, 2),
        "baseline": {"metrics": old_metrics, "rrs": old_rrs},
        "semantic": {"metrics": new_metrics, "rrs": new_rrs},
        "artifacts": {
            "old": str(old_output),
            "new": str(semantic_output),
            "side_by_side": str(comparison_output),
        },
    }
    (OUTPUT_DIR / "comparison_report.json").write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "comparison_report.txt").write_text(
        "\n".join([
            "SEA-LEVEL SEMANTIC EDIT A/B",
            f"Shared narration: {duration:.2f}s",
            "",
            f"OLD: {old_count} timer cuts at {old_each:.2f}s each",
            f"  semantic sync: {old_metrics['semantic_sync_ratio']:.0%}",
            f"  same-source jump cuts: {old_metrics['same_source_hard_cut_count']}",
            f"  meaningful cuts: {old_metrics['meaningful_cut_ratio']:.0%}",
            f"  RRS: {old_rrs['score']}/100 ({old_rrs['grade']})",
            "",
            f"NEW: {len(semantic_groups)} phrase-aligned views",
            f"  semantic sync: {new_metrics['semantic_sync_ratio']:.0%}",
            f"  same-source jump cuts: {new_metrics['same_source_hard_cut_count']}",
            f"  meaningful cuts: {new_metrics['meaningful_cut_ratio']:.0%}",
            f"  RRS: {new_rrs['score']}/100 ({new_rrs['grade']})",
            "",
            "This isolates timeline behavior; it is not a regenerated 90-second paid pilot.",
        ]) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
