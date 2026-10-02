"""A motion shot longer than its clip hands off to stills; a clip is not a hold (2026-10-02)."""
import longform_shots as ls
import longform_rendered_gate as gate


def _shot(kind, duration, start=0.0):
    return {"kind": kind, "duration": duration, "start_sec": start, "end_sec": start + duration,
            "asset_id": "asset:s001:e01", "state_id": "state:s001:e01", "motion": "generated_motion"}


def test_long_motion_shot_becomes_clip_plus_still_parts():
    out = ls.split_long_holds([_shot("i2v", 11.68)])
    assert out[0]["kind"] == "i2v" and abs(out[0]["duration"] - 5.0) < 1e-6
    rest = out[1:]
    assert rest and all(p["kind"] == "still" and p["asset_strategy"] == "hold_split" for p in rest)
    assert all(p["duration"] <= 3.5 + 1e-6 for p in rest)
    assert abs(sum(p["duration"] for p in out) - 11.68) < 1e-3
    assert abs(rest[-1]["end_sec"] - 11.68) < 1e-3


def test_motion_shot_within_its_clip_is_untouched():
    shot = _shot("i2v", 4.2)
    assert ls.split_long_holds([shot]) == [shot]


def test_gate_counts_a_motion_clip_as_a_hold_only_past_its_length():
    assert gate.MOTION_HOLD_ALLOWANCE_SECONDS >= ls.MOTION_CLIP_SECONDS
