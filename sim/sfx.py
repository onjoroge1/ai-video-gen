"""Scene-aligned sound effects, synthesized in code. Seeded, deterministic, free.

THE EASTER EGG RULE (from the rain video's retention review): if the payoff line is "rain lands on
only two of these worlds", the mix should prove it -- impact sound exists ONLY on the worlds where
rain actually reaches the ground. A rewatcher who counts the landings hears the physics. Worlds
whose rain never lands stay silent under the bed, and the absence is the point.

Sounds are synthesized, not sourced: a rain patter is filtered noise and a Titan drop is a decaying
low-frequency thump with a splash tail -- both are textures with parameters, which per the house
layer rule belong to code. A downloaded SFX pack would be undocumented, unlicensed and unseeded.

Scenes declare what they sound like via Simulation.meta["sfx"]:

    meta["sfx"] = {"earth_rain": ["earth"], "titan_rain": ["hook", "titan", "close"]}

render.main() calls build() after prepare_durations, so spans come from MEASURED scene lengths.
"""
from __future__ import annotations
import os
import subprocess

import numpy as np

SR = 44100


def _lowpass(x, alpha):
    """One-pole lowpass; alpha in (0,1), smaller = darker."""
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc += alpha * (x[i] - acc)
        y[i] = acc
    return y


def earth_rain(dur_s, rng, gain=1.0):
    """Continuous patter: band-limited noise with a slow-breathing envelope and micro-bursts."""
    n = int(dur_s * SR)
    noise = rng.standard_normal(n).astype(np.float32)
    # band-limit: darken twice, then remove rumble by subtracting a heavier lowpass
    lo = _lowpass(noise, 0.25)
    body = lo - _lowpass(lo, 0.02)
    # slow amplitude breathing so the patter does not read as synthetic hiss
    t = np.linspace(0, dur_s, n, dtype=np.float32)
    breathe = 0.75 + 0.25 * np.sin(2 * np.pi * 0.23 * t + rng.uniform(0, 6.3))
    # sparse brighter droplet ticks on top
    ticks = np.zeros(n, dtype=np.float32)
    for _ in range(int(dur_s * 14)):
        i = rng.integers(0, max(n - 800, 1))
        L = rng.integers(220, 750)
        env = np.exp(-np.linspace(0, 6, L)).astype(np.float32)
        ticks[i:i + L] += rng.uniform(0.15, 0.4) * env * rng.standard_normal(L).astype(np.float32)
    out = (body * breathe * 0.5 + ticks * 0.35) * gain
    return out


def titan_rain(dur_s, rng, gain=1.0, rate_hz=1.4):
    """Sparse giant drops: each a deep thump plus a darkened splash tail, at a slow rate.

    The rate and weight are the PHYSICS made audible -- ~centimetre drops at ~1.5 m/s land seldom
    and heavy, nothing like Earth's patter. The two rains must be tellable apart blind.
    """
    n = int(dur_s * SR)
    out = np.zeros(n, dtype=np.float32)
    t_next = rng.uniform(0.05, 0.4)
    while t_next < dur_s - 0.3:
        i = int(t_next * SR)
        f0 = rng.uniform(85, 150)                      # deep body of the impact
        L = int(SR * rng.uniform(0.22, 0.38))
        tt = np.arange(L, dtype=np.float32) / SR
        thump = np.sin(2 * np.pi * f0 * tt * (1 - 0.25 * tt)) * np.exp(-tt * 14)
        spl = int(SR * rng.uniform(0.10, 0.2))
        splash = _lowpass(rng.standard_normal(spl).astype(np.float32), 0.12) * \
            np.exp(-np.linspace(0, 7, spl)).astype(np.float32)
        amp = rng.uniform(0.5, 1.0)
        out[i:i + L] += amp * 0.9 * thump[:max(0, min(L, n - i))]
        j = i + int(0.02 * SR)
        out[j:j + spl] += amp * 0.5 * splash[:max(0, min(spl, n - j))]
        t_next += rng.exponential(1.0 / rate_hz)
    return out * gain


SYNTHS = {"earth_rain": earth_rain, "titan_rain": titan_rain}


def build(sim, out_wav=None):
    """Assemble the full-length SFX track from meta["sfx"] and measured scene durations.
    Returns the path, or None when the sim declares no sfx. Seeded from the slug: bit-identical
    on rebuild."""
    plan = (sim.meta or {}).get("sfx")
    if not plan:
        return None
    rng = np.random.default_rng(abs(hash(sim.slug + ":sfx")) % (2 ** 31))
    total = sum(sc._dur for sc in sim.scenes)
    track = np.zeros(int(total * SR) + SR, dtype=np.float32)
    t = 0.0
    spans = {}
    for sc in sim.scenes:
        spans[sc.id] = (t, sc._dur)
        t += sc._dur
    for kind, scene_ids in plan.items():
        synth = SYNTHS[kind]
        for sid in scene_ids:
            if sid not in spans:
                continue
            t0, dur = spans[sid]
            # short fades so a segment never clicks in or out against the silence next door
            seg = synth(dur, rng)
            f = int(0.12 * SR)
            seg[:f] *= np.linspace(0, 1, f, dtype=np.float32)
            seg[-f:] *= np.linspace(1, 0, f, dtype=np.float32)
            i = int(t0 * SR)
            track[i:i + len(seg)] += seg
    peak = np.abs(track).max()
    if peak > 0:
        track *= 0.9 / max(peak, 1.0)
    out_wav = out_wav or os.path.join(sim.work, "sfx.wav")
    raw = (track * 32767).astype(np.int16).tobytes()
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", str(SR),
                          "-ac", "1", "-i", "-", out_wav], stdin=subprocess.PIPE)
    p.communicate(raw)
    return out_wav
