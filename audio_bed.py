"""Shared MUSIC + SFX bed for the video pipelines.

Why this exists:
  * The flagship explainer shipped with NO music at all — `bg_music_path` was a parameter that
    `app.py` never populated, so every Short was narration on silence.
  * "Ducking" elsewhere was `volume=0.10`, a static pad. ffmpeg here has `sidechaincompress`, so the
    music can actually breathe: it drops under narration and returns in the gaps.
  * SFX synthesis was copy-pasted into sim_drop/quiz/health with drifting constants, and sim_drop's
    whole library was dead by default (CLEAN_AUDIO=True). One implementation, here.

Restraint is deliberate (production spec §13): "Emphasize causes and impacts; do not attach a whoosh to
every cut." So we place a riser before the PEAK and an impact on payoff/reveal beats — nothing else.
"""
from __future__ import annotations
import os
import subprocess

import numpy as np

SR = 48000
MUSIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "music")
# Kevin MacLeod, CC-BY 4.0 — must be credited in the description when used.
MUSIC_CREDIT = "Music: Kevin MacLeod (incompetech.com), licensed under Creative Commons BY 4.0."
MOODS = ("tense", "dramatic", "energetic", "upbeat", "corporate", "nostalgic")

# MEASURED integrated loudness of each cached bed (ffmpeg loudnorm, 2026-07-31). These differ by up to
# 11 LU — `tense` is -24.9 while `dramatic` is -13.6 — so a single fixed `volume=` makes some beds
# inaudible and others intrusive. We normalize each to MUSIC_TARGET_LUFS instead.
# Re-measure with:  ffmpeg -i static/music/X.mp3 -af loudnorm=print_format=json -f null -
_MEASURED_LUFS = {"corporate": -14.46, "dramatic": -13.59, "energetic": -16.14,
                  "nostalgic": -15.03, "tense": -24.87, "upbeat": -16.55}
# Where the bed should sit. Narration lands at ~-14 LUFS after the final loudnorm pass, so a bed around
# -28 is clearly present in the gaps without ever competing with speech.
MUSIC_TARGET_LUFS = -26.0
# Several beds are SHORT (corporate 40.9s, tense 42.4s, dramatic 60.9s) and end on a fade-out, so the
# caller must loop them (-stream_loop -1) rather than assume one pass covers the video.
_TRACK_SECONDS = {"corporate": 40.9, "dramatic": 60.9, "energetic": 201.5,
                  "nostalgic": 184.8, "tense": 42.4, "upbeat": 180.1}


def music_gain_for(mood: str, target_lufs: float = MUSIC_TARGET_LUFS) -> float:
    """Linear gain that brings a known bed to `target_lufs`. Falls back to a safe mid value."""
    measured = _MEASURED_LUFS.get((mood or "").lower())
    if measured is None:
        return 0.18
    return round(min(1.0, 10 ** ((target_lufs - measured) / 20.0)), 4)


def mood_of_path(path: str | None) -> str:
    return os.path.splitext(os.path.basename(path or ""))[0].lower()

# Topic feel -> bed. Science shorts are mostly curiosity/threat, so 'tense'/'dramatic' carry most of them.
_MOOD_WORDS = {
    "tense":     ("collapse", "die", "death", "kill", "danger", "toxic", "poison", "fail", "lost",
                  "run out", "without", "stop", "suffocat", "freeze", "starv", "extinct", "disease"),
    "dramatic":  ("universe", "cosmic", "star", "black hole", "planet", "earth", "ocean", "volcano",
                  "gravity", "explosion", "asteroid", "storm", "deep"),
    "energetic": ("fast", "speed", "race", "energy", "power", "electric", "muscle", "brain", "heart"),
    "nostalgic": ("ancient", "history", "old", "evolution", "million years", "prehistoric", "fossil"),
    "upbeat":    ("why", "how", "surprising", "weird", "strange", "secret", "hidden"),
}


def pick_mood(title: str = "", scenes: list | None = None, default: str = "tense") -> str:
    """Choose a bed from the title/narration. Cheap keyword match — no LLM call for a music pick."""
    text = (title or "").lower()
    if scenes:
        text += " " + " ".join((s.get("narration") or "") for s in scenes[:6]).lower()
    best, best_hits = default, 0
    for mood, words in _MOOD_WORDS.items():
        hits = sum(1 for w in words if w in text)
        if hits > best_hits:
            best, best_hits = mood, hits
    return best


def music_for(mood: str | None = None, title: str = "", scenes: list | None = None) -> str | None:
    """Resolve a local music bed, downloading via charts_pipeline._ensure_music only if absent."""
    mood = (mood or pick_mood(title, scenes)) if (mood is None or mood == "auto") else mood
    if mood not in MOODS:
        mood = "tense"
    local = os.path.join(MUSIC_DIR, f"{mood}.mp3")
    if os.path.exists(local) and os.path.getsize(local) > 50_000:
        return local
    try:                                            # reuse the validated downloader (checks magic bytes)
        import charts_pipeline
        return charts_pipeline._ensure_music(mood)
    except Exception:
        return None


# ---------------------------------------------------------------------------------------------------
# SFX bed
def _env(n: int, a: float = 0.01, r: float = 0.05) -> np.ndarray:
    e = np.ones(n); ai, ri = int(a * SR), int(r * SR)
    if ai: e[:ai] = np.linspace(0, 1, ai)
    if ri: e[-ri:] = np.linspace(1, 0, ri)
    return e


def _sine(f: float, n: int) -> np.ndarray:
    return np.sin(2 * np.pi * f * np.arange(n) / SR)


def _sweep(f0: float, f1: float, n: int) -> np.ndarray:
    t = np.arange(n) / SR
    k = (f1 / f0) ** (1.0 / max(1e-6, n / SR))
    return np.sin(2 * np.pi * f0 * ((k ** t - 1) / np.log(k)))


def _noise(n: int, seed: int = 11) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(n)


def _lowpass(x: np.ndarray, a: float = 0.02) -> np.ndarray:
    y = np.empty_like(x); acc = 0.0
    for i in range(len(x)):
        acc += a * (x[i] - acc); y[i] = acc
    return y


def riser(dur: float = 1.6) -> np.ndarray:
    """Non-verbal 'something is coming'. Swept tone + rising noise; the psychological retention trick."""
    n = int(dur * SR)
    ramp = np.linspace(0, 1, n) ** 2
    return (0.55 * _sweep(180, 900, n) * ramp + 0.45 * _lowpass(_noise(n), 0.05) * ramp) * _env(n, 0.05, 0.10)


def impact(dur: float = 0.5) -> np.ndarray:
    """Low thud for a consequence landing."""
    n = int(dur * SR)
    dec = np.linspace(1, 0, n) ** 2.2
    return (0.7 * _sine(58, n) + 0.3 * _sine(96, n) + 0.35 * _lowpass(_noise(n, 5), 0.02)) * dec


def build_sfx_bed(beats: list, total_s: float, out_wav: str,
                  riser_gain: float = 0.30, impact_gain: float = 0.40) -> str | None:
    """Render a full-length SFX track.

    beats: [{"t": seconds, "kind": "riser"|"impact"}]  — placed at absolute offsets.
    Returns out_wav, or None when there is nothing to place (never fabricates a busy mix).
    """
    beats = [b for b in (beats or []) if b.get("kind") in ("riser", "impact")]
    if not beats or total_s <= 0:
        return None
    bed = np.zeros(int(total_s * SR) + SR, dtype=np.float64)
    for b in beats:
        clip = riser() * riser_gain if b["kind"] == "riser" else impact() * impact_gain
        s = int(max(0.0, float(b.get("t", 0))) * SR)
        # a riser should ARRIVE at its beat, so it starts before it; an impact lands ON the beat
        if b["kind"] == "riser":
            s = max(0, s - len(clip))
        e = min(len(bed), s + len(clip))
        if e > s:
            bed[s:e] += clip[: e - s]
    peak = float(np.abs(bed).max())
    if peak < 1e-6:
        return None
    bed = bed / max(1.0, peak) * 0.9
    try:
        from scipy.io import wavfile
        wavfile.write(out_wav, SR, (np.stack([bed, bed], 1) * 32767).astype(np.int16))
        return out_wav
    except Exception:
        return None


_PAYOFF_TYPES = {"payoff", "climax", "reveal", "twist", "final_payoff", "escalation"}


def sfx_beats_for_scenes(scenes: list, durations: list) -> list:
    """Derive SFX placements from the beat sheet: riser INTO the peak, impact ON payoff-ish beats.

    Restrained by design — at most one riser, and impacts only on beats that actually resolve something.
    """
    out, t = [], 0.0
    starts = []
    for d in durations:
        starts.append(t); t += float(d or 0)
    total = t
    peak_i = None
    for i, s in enumerate(scenes[: len(starts)]):
        st = (s.get("scene_type") or "").lower().strip()
        if st in ("climax", "final_payoff") and peak_i is None:
            peak_i = i
        if st in _PAYOFF_TYPES:
            out.append({"t": starts[i] + 0.10, "kind": "impact"})
    if peak_i is None and len(starts) > 2:                    # no labelled peak: assume ~70% in
        peak_i = int(len(starts) * 0.7)
    if peak_i is not None and peak_i < len(starts):
        out.append({"t": starts[peak_i], "kind": "riser"})
    # never let SFX become a machine gun: keep impacts >=1.2s apart, cap the count
    out.sort(key=lambda b: b["t"])
    kept = []
    for b in out:
        if b["kind"] == "impact" and any(k["kind"] == "impact" and abs(k["t"] - b["t"]) < 1.2 for k in kept):
            continue
        kept.append(b)
    return [b for b in kept if b["t"] < total][:8]


def music_filter_graph(has_sfx: bool, music_gain: float | None = None, sfx_gain: float = 1.0,
                       mood: str | None = None) -> str:
    """Audio graph with REAL ducking (sidechaincompress) instead of a static volume pad.

    Inputs: [0:a] narration, [1:a] music, and [2:a] sfx when has_sfx.
    The narration keys the compressor on the music, so music dips under speech and lifts in the gaps.
    music_gain defaults to a per-track normalized gain (see music_gain_for) so every bed sits at the
    same level — a fixed multiplier left `tense` inaudible and `dramatic` intrusive.
    """
    if music_gain is None:
        music_gain = music_gain_for(mood) if mood else 0.18
    g = (f"[1:a]volume={music_gain},aformat=channel_layouts=stereo[bg];"
         "[0:a]aformat=channel_layouts=stereo,asplit=2[vo][key];"
         "[bg][key]sidechaincompress=threshold=0.02:ratio=12:attack=5:release=320:makeup=1[duck];")
    if has_sfx:
        g += (f"[2:a]volume={sfx_gain},aformat=channel_layouts=stereo[sx];"
              "[vo][duck][sx]amix=inputs=3:duration=first:normalize=0[mix]")
    else:
        g += "[vo][duck]amix=inputs=2:duration=first:normalize=0[mix]"
    return g
