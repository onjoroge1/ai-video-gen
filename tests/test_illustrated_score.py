"""Offline waveform and real-FFmpeg checks for the illustrated soundtrack."""
import hashlib
from pathlib import Path
import subprocess
import wave

import numpy as np
import pytest

import illustrated_score as score
from media_binaries import ffmpeg as ffmpeg_binary


def _read(path):
    with wave.open(str(path)) as wav:
        data = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2") / 32768
        return data.reshape(-1, wav.getnchannels()), wav.getframerate()


def _write(path, samples, rate=32000):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes((samples * 32767).astype("<i2").tobytes())


def test_score_is_audible_bounded_repeatable_and_cached(tmp_path, monkeypatch):
    path, metadata = score.render_score(str(tmp_path), "Hanoi rat bounty", "backfiring_solution", 13.7)
    samples, rate = _read(path)
    assert len(samples) == round(13.7 * rate)
    assert samples.shape[1] == 2
    assert 0.015 < np.sqrt(np.mean(samples ** 2)) < 0.3
    assert np.max(np.abs(samples)) < 0.7
    assert np.max(np.abs(samples[[0, -1]])) < 0.001
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == metadata["sha256"]
    # Regeneration in an empty directory must produce the same audio, not just a cached label.
    fresh, _ = score.render_score(str(tmp_path / "fresh"), "Hanoi rat bounty", "backfiring_solution", 13.7)
    assert Path(fresh).read_bytes() == Path(path).read_bytes()
    monkeypatch.setattr(score, "_compose", lambda *_: pytest.fail("cache unexpectedly regenerated"))
    assert score.render_score(str(tmp_path), "Hanoi rat bounty", "backfiring_solution", 13.7) == (path, metadata)


def test_topic_and_engine_change_the_audible_theme(tmp_path):
    a, meta_a = score.render_score(str(tmp_path), "Hanoi", "backfiring_solution", 12)
    b, _ = score.render_score(str(tmp_path), "An accidental invention", "accidental_invention", 12)
    c, meta_c = score.render_score(str(tmp_path), "Hanoi", "accumulating_indictment", 12)
    assert len({Path(p).read_bytes() for p in (a, b, c)}) == 3
    assert meta_a["spec"]["tempo_bpm"] > meta_c["spec"]["tempo_bpm"]


def test_corrupt_score_is_rebuilt_before_use(tmp_path):
    path, metadata = score.render_score(str(tmp_path), "Hanoi", "backfiring_solution", 3)
    Path(path).write_bytes(b"truncated")
    assert score.render_score(str(tmp_path), "Hanoi", "backfiring_solution", 3) == (path, metadata)
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == metadata["sha256"]


def test_real_ffmpeg_ducks_music_and_preserves_voice_and_duration(tmp_path):
    rate, duration = 32000, 9
    t = np.arange(rate * duration) / rate
    # Separated frequencies let us measure music and voice independently in the mixed WAV.
    voice = 0.12 * np.sin(2 * np.pi * 997 * t) * ((t >= 3) & (t < 5))
    music = 0.2 * np.sin(2 * np.pi * 220 * t)
    voice_path, music_path, mixed_path = (tmp_path / x for x in ("voice.wav", "music.wav", "mix.wav"))
    _write(voice_path, voice)
    _write(music_path, music)
    subprocess.run([ffmpeg_binary(), "-v", "error", "-y", "-i", str(voice_path), "-i", str(music_path),
                    "-filter_complex", score.music_mix_filter(duration, [6.2]), "-map", "[mix]",
                    "-c:a", "pcm_s16le", str(mixed_path)], check=True, capture_output=True, timeout=30)
    samples, sample_rate = _read(mixed_path)
    assert abs(len(samples) / sample_rate - duration) < 0.02
    assert np.max(np.abs(samples)) < 0.99

    def amplitude(frequency, start, stop):
        segment = samples[round(start * sample_rate):round(stop * sample_rate)].mean(axis=1)
        phase = np.arange(len(segment)) / sample_rate
        return abs(np.mean(segment * np.exp(-2j * np.pi * frequency * phase))) * 2

    bed_pause = amplitude(220, 1.5, 2.5)
    bed_speech = amplitude(220, 3.5, 4.5)
    voice_speech = amplitude(997, 3.5, 4.5)
    assert bed_speech < bed_pause * 0.4
    assert voice_speech > bed_speech * 5
    assert amplitude(220, 6.3, 6.7) < bed_pause * 0.4  # story-turn music drop
