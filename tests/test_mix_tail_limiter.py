"""The mux-stage mix tail must hold the -1 dBTP ceiling the audit measures.

Killer bees V11 (2026-10-07) read +0.86 dBFS at the close: loudnorm's single-pass limiter
pins sample peaks at -1 dBFS, the intersample (true) peak of those flat tops ran to +1.0 dBTP,
and the AAC encode added another ~0.3 dB. The fix is a brick-wall limiter after loudnorm with
headroom for the codec. These tests read the exact production filter string from the source
(so a later edit cannot silently drop or loosen the limiter), run it over a quiet track with a
hot transient, encode to AAC the way the mux does, and measure the decoded true peak.
Measured on this seeded fixture: loudnorm alone decodes to +0.2 dBTP (over the audit line, the
V11 class of failure); with the limiter, -0.9.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _production_mix_tail() -> str:
    src = (ROOT / "explainer_pipeline.py").read_text()
    m = re.search(r'"-af",\s*"(loudnorm=I=-12:TP=-1[^"]*)"', src)
    assert m, "mux-stage loudnorm filter not found in explainer_pipeline.py"
    return m.group(1)


def test_mix_tail_ends_in_a_brick_wall_limiter_at_or_below_minus_one_dbtp():
    tail = _production_mix_tail()
    chain = tail.split(",")
    assert chain[0].startswith("loudnorm="), tail
    assert chain[-1].startswith("alimiter="), f"limiter must be last so nothing re-raises the peak: {tail}"
    limit = float(re.search(r"limit=([0-9.]+)", chain[-1]).group(1))
    # -1.5 dBTP: the codec adds ~0.3 dB, and the audit's drift line is -0.5 dBFS
    assert limit <= 0.842, f"limit {limit} is above -1.5 dBTP (0.841 linear)"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_production_mix_tail_decodes_under_the_audit_line_after_aac(tmp_path):
    # 20 s of quiet speech-band noise so loudnorm gains it up hard, then a full-scale click
    # burst near the end: the shape of a plosive landing on a cue at the close.
    tail = _production_mix_tail()
    quiet = "anoisesrc=d=20:c=pink:a=0.02:r=48000:s=7"
    click = "sine=f=1000:d=0.02:r=48000,volume=20dB,adelay=19500|19500"
    graph = f"{quiet}[q];{click}[c];[q][c]amix=inputs=2:normalize=0,{tail}"
    encoded = tmp_path / "mix.m4a"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-y", "-f", "lavfi", "-i", graph,
         "-c:a", "aac", "-b:a", "192k", str(encoded)],
        capture_output=True, text=True, check=True,
    )
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(encoded), "-af", "ebur128=peak=true",
         "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )
    # the summary block is the whole-file true peak; the per-frame TPK columns are noisier
    m = re.search(r"True peak:\s*\n\s*Peak:\s*(-?[0-9.]+)\s*dBFS", out.stderr)
    assert m, out.stderr[-2000:]
    worst = float(m.group(1))
    assert worst <= -0.8, f"decoded true peak {worst} dBTP; the audit flags drift above -0.5 (filter: {tail})"
