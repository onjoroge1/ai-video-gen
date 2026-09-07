"""Locally composed chamber accompaniment for illustrated stories.

Notes and instrument waveforms are synthesized here, without reference audio,
sample libraries, network calls or a music-generation provider. The same topic,
engine and score version reproduce the same theme across worker restarts.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import random
import tempfile
import wave

import numpy as np


SCORE_VERSION = "chamber_v1"
SAMPLE_RATE = 32000
_MOODS = {
    "backfiring_solution": ("wry", 96, "minor"),
    "accumulating_indictment": ("reflective", 72, "minor"),
    "almost_happened_plan": ("curious", 88, "major"),
    "accidental_invention": ("discovery", 100, "major"),
    "power_reversal": ("measured", 80, "minor"),
}


def score_spec(topic: str, engine: str, duration_sec: float) -> dict:
    duration = float(duration_sec)
    if not math.isfinite(duration) or not 1 <= duration <= 3600:
        raise ValueError("Score duration must be 1–3600 seconds")
    identity = json.dumps([SCORE_VERSION, " ".join(topic.lower().split()), engine])
    theme = hashlib.sha256(identity.encode()).hexdigest()
    mood, tempo, mode = _MOODS.get(engine, ("curious", 88, "major"))
    return {
        "version": SCORE_VERSION, "theme_id": theme[:16], "engine": engine,
        "mood": mood, "tempo_bpm": tempo + int(theme[16:18], 16) % 7 - 3,
        "tonic_midi": (48, 50, 53, 55, 57)[int(theme[18:20], 16) % 5],
        "mode": mode, "duration_sec": round(duration, 3), "sample_rate": SAMPLE_RATE,
        "source": "locally_composed", "instruments": ["synthesized felt piano", "plucked strings", "soft strings"],
        "provider_cost_usd": 0.0,
    }


def _note(midi: int, seconds: float, kind: str, sample_rate: int) -> np.ndarray:
    """Damped harmonics for plucks/piano; slow bowed envelope for the string bed."""
    t = np.arange(max(1, round(seconds * sample_rate)), dtype=np.float64) / sample_rate
    frequency = 440 * 2 ** ((midi - 69) / 12)
    signal = np.zeros(len(t), dtype=np.float64)
    if kind == "strings":
        envelope = np.minimum(t / 0.45, 1) * np.minimum((seconds - t) / 0.65, 1)
        phase = 2 * np.pi * frequency * t + 0.035 * np.sin(2 * np.pi * 4.8 * t)
        for harmonic in range(1, 7):
            if harmonic * frequency < sample_rate / 2:
                signal += np.sin(harmonic * phase) / harmonic ** 2.2
        return (signal * envelope * 0.32).astype(np.float32)
    decay = 1.1 if kind == "piano" else 0.34
    for harmonic in range(1, 8):
        if harmonic * frequency >= sample_rate / 2:
            break
        # Higher partials die first; a slight piano inharmonicity avoids a pure tone.
        stretch = math.sqrt(1 + 0.00012 * harmonic ** 2) if kind == "piano" else 1
        signal += (np.sin(2 * np.pi * frequency * harmonic * stretch * t)
                   * np.exp(-t * (1 + harmonic * 0.26) / decay) / harmonic ** 1.65)
    envelope = np.minimum(t / 0.008, 1) * np.minimum((seconds - t) / 0.09, 1)
    return (signal * envelope * 0.55).astype(np.float32)


def _compose(spec: dict) -> np.ndarray:
    rate = spec["sample_rate"]
    duration = spec["duration_sec"]
    samples = np.zeros((round(duration * rate), 2), dtype=np.float32)
    rng = random.Random(spec["theme_id"])
    beat = 60 / spec["tempo_bpm"]
    scale = (0, 2, 3, 5, 7, 8, 10) if spec["mode"] == "minor" else (0, 2, 4, 5, 7, 9, 11)
    tonic = spec["tonic_midi"]
    progression = rng.choice(((0, 5, 3, 4), (0, 3, 5, 4), (0, 5, 1, 4)))
    motif = rng.choice(((0, 2, 1, 2), (2, 1, 0, 1), (0, 1, 2, 1), (1, 0, 2, 1)))

    def pitch(degree: int, octave: int = 0) -> int:
        return tonic + scale[degree % 7] + 12 * (degree // 7 + octave)

    def add(start: float, midi: int, length: float, kind: str, gain: float, pan: float):
        offset = max(0, round(start * rate))
        end = min(len(samples), offset + round(length * rate))
        if end <= offset:
            return
        note = _note(midi, length, kind, rate)[:end - offset] * gain
        samples[offset:end, 0] += note * math.sqrt(1 - pan)
        samples[offset:end, 1] += note * math.sqrt(pan)

    bars = math.ceil(duration / (4 * beat))
    for bar in range(bars):
        start = bar * 4 * beat
        root = progression[bar % len(progression)]
        # A soft tonic ending, with the closing voice left space above it.
        closing = start >= duration - 2 * 4 * beat
        if closing:
            root = 0
        chord = (root, root + 2, root + 4)
        energy = 0.65 if closing else (0.78 + 0.15 * math.sin(math.pi * start / duration))
        add(start, pitch(root, -1), 3.8 * beat, "piano", 0.24 * energy, 0.48)
        for degree in chord:
            add(start, pitch(degree), 4.5 * beat, "strings", 0.09 * energy, 0.65)
        steps = 4 if spec["mood"] == "reflective" or closing else 8
        for step in range(steps):
            degree = chord[(step + motif[bar % 4]) % 3]
            add(start + step * (4 * beat / steps), pitch(degree, 1),
                1.8 * beat, "pluck", 0.16 * energy * rng.uniform(0.88, 1.08), 0.30)
        # A recurring, varied phrase every other bar instead of a competing melody throughout.
        if bar % 2 == 0 and not closing:
            for step, index in enumerate(motif):
                add(start + step * beat + 0.025, pitch(chord[index], 1),
                    2.1 * beat, "piano", 0.22 * energy, 0.55)

    # Quiet early reflections, no external convolution/samples. Peak headroom is deterministic.
    delay = int(rate * 0.071)
    if len(samples) > delay:
        samples[delay:] += samples[:-delay, ::-1].copy() * 0.12
    peak = float(np.max(np.abs(samples)))
    if peak:
        samples *= min(0.65 / peak, 2.0)
    fade_in = min(len(samples), int(0.6 * rate))
    fade_out = min(len(samples), int(2.0 * rate))
    samples[:fade_in] *= np.linspace(0, 1, fade_in, dtype=np.float32)[:, None]
    samples[-fade_out:] *= np.linspace(1, 0, fade_out, dtype=np.float32)[:, None]
    return samples


def render_score(output_dir: str, topic: str, engine: str, duration_sec: float) -> tuple[str, dict]:
    """Cache a complete WAV plus its composition identity and audio checksum."""
    spec = score_spec(topic, engine, duration_sec)
    key = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16]
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path, metadata_path = directory / f"score_{key}.wav", directory / f"score_{key}.json"
    try:
        metadata = json.loads(metadata_path.read_text())
        if metadata.get("spec") == spec and hashlib.sha256(path.read_bytes()).hexdigest() == metadata.get("sha256"):
            return str(path), metadata
    except (OSError, ValueError):
        pass
    samples = _compose(spec)
    with tempfile.NamedTemporaryFile(dir=directory, suffix=".wav", delete=False) as stream:
        partial = Path(stream.name)
    try:
        with wave.open(str(partial), "wb") as wav:
            wav.setnchannels(2)
            wav.setsampwidth(2)
            wav.setframerate(spec["sample_rate"])
            wav.writeframes((samples * 32767).astype("<i2").tobytes())
        digest = hashlib.sha256(partial.read_bytes()).hexdigest()
        os.replace(partial, path)
        metadata = {"status": "ready", "spec": spec, "sha256": digest}
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
        return str(path), metadata
    finally:
        partial.unlink(missing_ok=True)


def music_mix_filter(duration_sec: float, drops: list[float] | None = None) -> str:
    """FFmpeg input 0 is narration, input 1 is music; output is [mix].

    Normalize sources independently, then duck only music using the voice as the
    sidechain. Disabling amix normalization preserves the voice level.
    https://ffmpeg.org/ffmpeg-filters.html#sidechaincompress
    """
    duration = float(duration_sec)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Music mix needs a positive duration")
    volume = "1"
    for t in reversed(drops or []):
        if math.isfinite(t) and 0 <= t <= duration:
            volume = f"if(between(t\\,{max(0, t - 0.2):.3f}\\,{t + 0.8:.3f})\\,0.18\\,{volume})"
    fade = min(2.0, duration / 3)
    return (
        "[0:a]loudnorm=I=-18:TP=-2:LRA=9,"
        "aformat=sample_rates=32000:channel_layouts=stereo,asplit=2[voice][side];"
        f"[1:a]atrim=duration={duration:.3f},asetpts=PTS-STARTPTS,"
        "loudnorm=I=-29:TP=-3:LRA=9,aformat=sample_rates=32000:channel_layouts=stereo,"
        f"volume='{volume}':eval=frame,afade=t=in:d={min(0.5, fade):.3f},"
        f"afade=t=out:st={duration - fade:.3f}:d={fade:.3f}[bed];"
        "[bed][side]sidechaincompress=threshold=0.025:ratio=6:attack=12:release=300[ducked];"
        "[voice][ducked]amix=inputs=2:duration=first:normalize=0:dropout_transition=0[mix]"
    )
