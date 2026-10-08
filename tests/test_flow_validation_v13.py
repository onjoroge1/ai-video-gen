"""Flow validation 2026-10-07, items 1, 2, 4, 6 and 9 (FLOW_VALIDATION_2026-10-07.md).

1. The writer is asked for `explains` and `object_reference`; the readers existed, no prompt did.
2. The explanatory cutaway may carry arrows; every other plate still may not. Text stays banned.
4. The illustrated lane renders no on-screen text unless ILLUSTRATED_CAPTIONS=1.
6. The hook-only rewrite sends the frame rules under the ladder, and the end-of-run score and
   the audit score a ladder frame as a frame.
9. A structural pause precedes the hinge, mechanism, reversal and synthesis rows; the music bed
   is off unless ILLUSTRATED_MUSIC=1.
"""
import json
import os
import subprocess

import pytest

import explainer_pipeline as ep
import hook_patterns as hp
import illustrated_story as lane


# ── item 1 ──────────────────────────────────────────────────────────────────

def test_the_writer_is_asked_for_both_fields():
    rules = ep._ILLUSTRATED_BEAT_RULES
    assert '"explains"' in rules and '"object_reference"' in rules
    assert "object_reference_label" in rules
    assert 'causal_role is "mechanism"' in rules, "the cutaway is asked for on the mechanism row"
    assert "EXACTLY ONE visual_beat" in rules


# ── item 2 ──────────────────────────────────────────────────────────────────

def test_arrows_are_allowed_on_the_cutaway_plate_only():
    assert "ARROWS may show direction" in lane.EXPLAIN_CUTAWAY
    assert "nothing written on it" in lane.EXPLAIN_CUTAWAY
    assert "arrows" in lane.NO_DIAGRAM and "ARROWS may show" not in lane.NO_DIAGRAM


def test_the_evidence_prompt_drops_the_arrow_ban_for_an_explaining_state():
    base = {"include_human": False, "include_bolt": False, "pure_evidence": True,
            "anchor_phrase": "the grid", "purpose": "evidence", "state_before": "a",
            "state_after": "b", "required_objects": ["metal grid"], "forbidden_objects": []}
    pack = {"opening_object": {"label": "a hive box"}, "first_act_location": {}}
    plain = ep._evidence_state_prompt({}, dict(base), pack, "")
    cut = ep._evidence_state_prompt({}, dict(base, explains=True), pack, "")
    assert "without labels, arrows, text" in plain
    assert "without labels, text" in cut and "arrows, text" not in cut


def test_the_cast_rules_no_longer_recommend_maps():
    # The sentence lived inside the writer's cast block; it contradicted NO_DIAGRAM.
    import inspect
    src = inspect.getsource(ep)
    assert "Diagrams, animal behaviour and maps are" not in src
    assert "a map or chart never" in src


# ── item 4 and item 9 (defaults) ────────────────────────────────────────────

def test_captions_and_music_are_opt_in_on_the_illustrated_lane(monkeypatch):
    monkeypatch.delenv("ILLUSTRATED_CAPTIONS", raising=False)
    monkeypatch.delenv("ILLUSTRATED_MUSIC", raising=False)
    assert ep._illustrated_captions_wanted() is False
    assert ep._illustrated_music_wanted() is False
    monkeypatch.setenv("ILLUSTRATED_CAPTIONS", "1")
    monkeypatch.setenv("ILLUSTRATED_MUSIC", "1")
    assert ep._illustrated_captions_wanted() is True
    assert ep._illustrated_music_wanted() is True


def test_the_staging_rule_no_longer_reserves_the_lower_third_for_captions():
    assert "for captions" not in lane._STAGING


# ── item 6 ──────────────────────────────────────────────────────────────────

class _Capture:
    def __init__(self, reply):
        self.reply, self.prompts = reply, []
        outer = self

        class _M:
            def create(self, **kwargs):
                outer.prompts.append(kwargs["messages"][0]["content"])
                text = json.dumps({"hook": outer.reply})
                return type("R", (), {"content": [type("C", (), {"text": text})()],
                                      "usage": type("U", (), {"input_tokens": 1, "output_tokens": 1})()})()
        self.messages = _M()


def test_the_hook_only_rewrite_sends_frame_rules_under_the_ladder(monkeypatch):
    fake = _Capture("Imagine you're a beekeeper in Brazil, trying to fill jars.")
    monkeypatch.setattr(ep, "_claude", lambda: fake)
    monkeypatch.setattr(ep, "_msg_cost", lambda usage: 0.0)
    plan = {"hook": "Warwick Kerr imported African bees to Brazil in 1956.", "title": "t"}
    best, _ = ep._rewrite_hook_to_contract(plan, {"claims": []}, [], ladder=True)
    assert fake.prompts and hp.FRAME_RULES in fake.prompts[0]
    assert "MEASURE A NUMBER" not in fake.prompts[0], "the hook devices are not the frame's rules"
    assert best.startswith("Imagine you're a beekeeper")
    assert hp.score_hook(best, ladder=True)["score"] >= 70


def test_the_hook_only_rewrite_still_sends_hook_rules_without_the_ladder(monkeypatch):
    fake = _Capture("Your hive could face twenty-six escaped queens; nobody checked the excluders.")
    monkeypatch.setattr(ep, "_claude", lambda: fake)
    monkeypatch.setattr(ep, "_msg_cost", lambda usage: 0.0)
    ep._rewrite_hook_to_contract({"hook": "Kerr did it."}, {"claims": []}, [], ladder=False)
    assert fake.prompts and hp.HOOK_RULES in fake.prompts[0] and hp.FRAME_RULES not in fake.prompts[0]


def test_the_frame_rules_put_the_body_before_the_role():
    assert "second person" in hp.FRAME_RULES and "At most 18 words" in hp.FRAME_RULES
    assert "no institution and no researcher" in hp.FRAME_RULES
    assert "feels, risks or needs" in hp.FRAME_RULES


def test_the_end_of_run_and_the_audit_score_a_ladder_frame_as_a_frame():
    import inspect
    import importlib.util
    frame = "Imagine you're a beekeeper in Brazil, trying to fill jars from bees that struggle."
    assert hp.score_hook(frame, ladder=True)["score"] >= 70
    src = inspect.getsource(ep)
    assert 'ladder=(_s(script.get("_opening_contract")) == "ladder_v1")' in src
    audit = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "scripts", "audit_film.py")
    with open(audit) as handle:
        assert 'score_hook(hook, ladder=bool(_ladder))' in handle.read()


# ── item 9 (pauses) ─────────────────────────────────────────────────────────

def test_structural_pauses_land_on_the_four_rows_after_scene_one(monkeypatch):
    monkeypatch.setattr(ep, "STRUCTURAL_PAUSE_SECONDS", 0.7)
    assert ep._structural_pause_seconds({"causal_role": "hinge"}, 0) == 0.0, "never before scene 1"
    for role in ("hinge", "mechanism", "reversal", "synthesis"):
        assert ep._structural_pause_seconds({"causal_role": role}, 3) == 0.7
    for role in ("setup", "intervention", "escalation", "generalization", "tool", ""):
        assert ep._structural_pause_seconds({"causal_role": role}, 3) == 0.0
    assert ep._structural_pause_seconds({"story_role": "mechanism"}, 2) == 0.7
    monkeypatch.setattr(ep, "STRUCTURAL_PAUSE_SECONDS", 0.0)
    assert ep._structural_pause_seconds({"causal_role": "hinge"}, 3) == 0.0


def _has_ffmpeg() -> bool:
    try:
        subprocess.run([ep._ffmpeg_bin(), "-version"], capture_output=True, check=True)
        return True
    except Exception:          # noqa: BLE001 - absent binary skips the encode test
        return False


@pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg not available")
def test_prepend_silence_adds_exactly_the_pause(tmp_path):
    raw = str(tmp_path / "raw.mp3")
    out = str(tmp_path / "padded.mp3")
    subprocess.run([ep._ffmpeg_bin(), "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                    "-c:a", "libmp3lame", raw], capture_output=True, check=True)
    ep._prepend_silence(raw, out, 0.7)
    grown = ep._audio_dur(out) - ep._audio_dur(raw)
    assert 0.6 <= grown <= 0.85, f"expected ~0.7 s of added silence, got {grown:.2f}"
