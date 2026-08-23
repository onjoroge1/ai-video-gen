from pathlib import Path
from types import SimpleNamespace

import pytest

import explainer_pipeline as pipeline
from app import app as fastapi_app
from audio_timing import build_audio_timing_report


def _scene(text, anchor=""):
    return {
        "narration": text,
        "visual_beats": ([{"anchor_phrase": anchor}] if anchor else []),
    }


def _timings(text, duration):
    words = text.split()
    step = duration / len(words)
    return [(word, i * step, (i + 1) * step) for i, word in enumerate(words)]


def _report(durations, target=90.0, anchors=False):
    scenes = []
    timing = []
    paths = []
    duration_map = {}
    for i, duration in enumerate(durations):
        text = f"scene {i} shows measured evidence"
        scenes.append(_scene(text, "measured evidence" if anchors else ""))
        timing.append(_timings(text, duration))
        path = f"scene-{i}.mp3"
        paths.append(path)
        duration_map[path] = duration
    return build_audio_timing_report(
        scenes, paths, timing, target, duration_probe=duration_map.__getitem__)


@pytest.mark.parametrize("measured", [87.3, 90.0, 92.7])
def test_90_second_boundary_is_inclusive(measured):
    report = _report([measured], 90.0)
    assert report["passed"] is True
    assert report["post_stretched"] is False


@pytest.mark.parametrize("measured", [87.29, 92.71])
def test_90_second_runtime_outside_three_percent_fails(measured):
    report = _report([measured], 90.0)
    assert report["passed"] is False
    assert any(error["code"] == "measured_runtime_outside_tolerance" for error in report["errors"])


def test_phrase_timestamps_use_measured_words_and_global_offsets():
    report = _report([40.0, 50.0], 90.0, anchors=True)
    assert report["passed"] is True
    phrases = report["phrase_timestamps"]
    assert len(phrases) == 2
    assert phrases[0]["source"] == "measured_word_timestamps"
    assert phrases[1]["start_sec"] >= 40.0


def test_phrase_timestamp_allows_one_unambiguous_whisper_substitution():
    scene = _scene("the coastline cannot recover quickly", "cannot recover")
    report = build_audio_timing_report(
        [scene], ["one.mp3"],
        [[("the", 0, 1), ("coastline", 1, 2), ("can't", 2, 3),
          ("recover", 3, 4), ("quickly", 4, 5)]],
        5, duration_probe=lambda _path: 5.0)
    assert report["passed"] is True
    assert report["phrase_timestamps"][0]["source"] == "measured_word_timestamps_fuzzy"


def test_missing_word_timestamps_fail_closed():
    report = build_audio_timing_report(
        [_scene("one two three")], ["one.mp3"], [[]], 90,
        duration_probe=lambda _path: 90.0)
    codes = {error["code"] for error in report["errors"]}
    assert "word_timing_coverage" in codes


def test_scene_audio_count_mismatch_fails_closed():
    report = build_audio_timing_report(
        [_scene("one two")], [], [], 90, duration_probe=lambda _path: 90)
    assert report["passed"] is False
    assert report["errors"][0]["code"] == "audio_scene_count_mismatch"


def test_longform_audio_is_generated_and_measured_before_visuals(monkeypatch, tmp_path):
    script = {"title": "Gauge", "scenes": [
        _scene("one two three four"), _scene("five six seven eight")
    ]}
    durations = {"scene_00.mp3": 45.0, "scene_01.mp3": 45.0}
    events = []

    def fake_tts(text, path, voice="echo"):
        Path(path).write_bytes(b"audio")
        events.append(("tts", Path(path).name, voice))
        return path

    monkeypatch.setattr(pipeline, "generate_tts", fake_tts)
    monkeypatch.setattr(pipeline, "_audio_dur", lambda path: durations[Path(path).name])
    monkeypatch.setattr(pipeline, "transcribe_words", lambda path: _timings(
        script["scenes"][int(Path(path).stem.split("_")[-1])]["narration"],
        durations[Path(path).name]))

    results, report = pipeline._prepare_longform_audio(
        script, {}, str(tmp_path), "echo", 90.0, tts_costs=[], aux_costs=[])
    assert report["passed"] is True
    assert len(results) == 2
    assert [event[0] for event in events] == ["tts", "tts"]


def test_measured_audio_refits_and_rerenders_until_real_duration_passes(monkeypatch, tmp_path):
    script = {"title": "Gauge", "scenes": [_scene("one two three four")]}
    pass_number = {"value": 0}

    def fake_tts(_text, path, voice="echo"):
        Path(path).write_bytes(b"audio")
        return path

    def fake_fit(*_args, **_kwargs):
        pass_number["value"] += 1

    monkeypatch.setattr(pipeline, "generate_tts", fake_tts)
    monkeypatch.setattr(pipeline, "_audio_dur", lambda _path: 100.0 if pass_number["value"] == 0 else 90.0)
    monkeypatch.setattr(pipeline, "transcribe_words", lambda _path: _timings(
        script["scenes"][0]["narration"], 100.0 if pass_number["value"] == 0 else 90.0))
    monkeypatch.setattr(pipeline, "_fit_script_to_measured_audio", fake_fit)
    monkeypatch.setattr(pipeline, "validate_longform_story", lambda *_args: {"passed": True})
    monkeypatch.setattr(pipeline, "validate_claim_joins", lambda *_args: {"passed": True})

    _, report = pipeline._prepare_longform_audio(
        script, {}, str(tmp_path), "echo", 90.0, tts_costs=[], aux_costs=[])
    assert pass_number["value"] == 1
    assert report["measured_seconds"] == 90.0
    assert report["passed"] is True


def test_cached_audio_is_regenerated_when_narration_changes(monkeypatch, tmp_path):
    script = {"title": "Gauge", "scenes": [_scene("new narration words here")]}
    audio = tmp_path / "scene_00.mp3"
    audio.write_bytes(b"old-audio")
    (tmp_path / "scene_00.mp3.narration.sha256").write_text("stale")
    generated = []

    def fake_tts(text, path, voice="echo"):
        generated.append(text)
        Path(path).write_bytes(b"new-audio")
        return path

    monkeypatch.setattr(pipeline, "generate_tts", fake_tts)
    monkeypatch.setattr(pipeline, "_audio_dur", lambda _path: 90.0)
    monkeypatch.setattr(pipeline, "transcribe_words", lambda _path: _timings(
        script["scenes"][0]["narration"], 90.0))
    pipeline._prepare_longform_audio(
        script, {}, str(tmp_path), "echo", 90.0, tts_costs=[], aux_costs=[])
    assert generated == ["new narration words here"]


def test_transcription_retry_reopens_audio_file(monkeypatch, tmp_path):
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"complete-audio-body")
    bodies = []

    class Transcriptions:
        def create(self, *, file, **_kwargs):
            bodies.append(file.read())
            return SimpleNamespace(words=[SimpleNamespace(word="complete", start=0.0, end=0.5)])

    monkeypatch.setattr(
        pipeline, "_openai",
        lambda: SimpleNamespace(audio=SimpleNamespace(transcriptions=Transcriptions())))

    def twice(function, **_kwargs):
        function()
        return function()

    monkeypatch.setattr(pipeline, "_retry", twice)
    assert pipeline.transcribe_words(str(audio)) == [("complete", 0.0, 0.5)]
    assert bodies == [b"complete-audio-body", b"complete-audio-body"]


def test_phase_two_report_download_controls_are_exposed():
    html = Path("static/index.html").read_text()
    for control in ("expl-research-btn", "expl-claims-btn", "expl-timing-btn"):
        assert f'id="{control}"' in html
    route_paths = {getattr(route, "path", "") for route in fastapi_app.routes}
    assert {
        "/api/explainer/research/{job_id}",
        "/api/explainer/claims/{job_id}",
        "/api/explainer/audio-timing/{job_id}",
    }.issubset(route_paths)
