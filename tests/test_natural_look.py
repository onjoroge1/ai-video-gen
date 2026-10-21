"""World look (operator, 2026-10-21): natural colour instead of single-hue paper stocks, and a low
steady ambient-pad music bed instead of the ducked score. Both are opt-in; defaults unchanged."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import illustrated_score  # noqa: E402
import illustrated_story  # noqa: E402


def test_default_keeps_the_coloured_stocks(monkeypatch):
    monkeypatch.delenv("ILLUSTRATED_PALETTE", raising=False)
    s = illustrated_story.visual_style_suffix(role="mechanism")
    assert "blueprint-blue" in s and "clean ivory stock" in s and "a little paper grain" in s


def test_natural_palette_drops_single_hue_plates(monkeypatch):
    monkeypatch.setenv("ILLUSTRATED_PALETTE", "natural")
    for role in ("setup", "mechanism", "escalation", "reversal", "hinge", ""):
        s = illustrated_story.visual_style_suffix(role=role)
        assert "Natural full colour" in s and "never a single-hue tint" in s
        assert "blueprint" not in s and "magenta" not in s and "ivory stock" not in s
        assert "never mottled" in s


def test_default_mix_ducks_and_pad_does_not(monkeypatch):
    monkeypatch.delenv("MUSIC_MIX", raising=False)
    assert "sidechaincompress" in illustrated_score.music_mix_filter(60, [10.0])
    monkeypatch.setenv("MUSIC_MIX", "ambient_pad")
    pad = illustrated_score.music_mix_filter(60, [10.0])
    assert "sidechaincompress" not in pad and "between(t" not in pad, "no ducking, no turn drops"
    assert "lowpass=f=1600" in pad and "loudnorm=I=-34" in pad and pad.endswith("[mix]")


def test_rescue_resume_keeps_the_look(tmp_path):
    import rescue_script as rs
    (tmp_path / "run_command.txt").write_text(
        "python3 scripts/run_illustrated_local.py --question 'Q?' --out jobs/x --palette natural "
        "--music-mix ambient_pad --music\n")
    env = rs.launch_flags(str(tmp_path))
    assert env["ILLUSTRATED_PALETTE"] == "natural" and env["MUSIC_MIX"] == "ambient_pad"
