"""The shot compiler searches the words the timing gate searched (2026-10-14).

longform_shots._timed_words kept `end > start` after audio_timing switched to `0 <= start <= end`
(a81939e, 2026-08-26), so a zero-width Whisper word resolved in the timing report and vanished
from the compiler. bees_v16b (published gCJh5oM8kwg): 'tilt', 'jar' and 'pour' were zero-width,
"You tilt the jar to pour" never resolved, its cut was spread and marked unaligned, and the
opening sat at 7/11 aligned -- 69 D on the semantic_sync cap. Fused tokens are split the same way
audio_timing splits them.
"""
import render_cache
from longform_shots import _timed_words, compile_scene_shots


def _state(number, anchor, strategy="distinct"):
    return {"state_id": f"state:s001:e{number:02d}", "asset_id": f"asset:s001:e{number:02d}",
            "anchor_phrase": anchor, "asset_strategy": strategy, "asset_status": "accepted",
            "verified_visible_information": True, "purpose": "evidence"}


def test_zero_width_words_survive_and_fused_tokens_are_split():
    timed = _timed_words("you tilt the jar two the end", [
        ["you", 0.0, 0.2], ["tilt", 0.2, 0.2], ["the", 0.2, 0.4], ["jar", 0.4, 0.4],
        ["two-the", 0.5, 0.9], ["end", 0.9, 1.1], ["bogus", 5.0, 9.0]], 2.0)
    assert [w for w, _a, _b in timed] == ["you", "tilt", "the", "jar", "two", "the", "end"]
    assert timed[1] == ("tilt", 0.2, 0.2)
    assert timed[4] == ("two", 0.5, 0.7)


def test_the_filter_is_the_one_audio_timing_applies():
    # A timestamp past the audio is still not measured speech; a negative start never was.
    timed = _timed_words("one two three", [
        ["one", -0.1, 0.2], ["two", 0.3, 0.6], ["three", 0.7, 2.4]], 2.0)
    assert [w for w, _a, _b in timed] == ["two"]
    # Within the 0.25 s allowance a word is kept and clamped to the audio's end.
    assert _timed_words("one two", [["one", 0.0, 0.5], ["two", 1.6, 2.2]], 2.0)[1] == (
        "two", 1.6, 2.0)


def test_an_anchor_through_zero_width_words_lands_on_its_phrase():
    narration = "pour the honey. you tilt the jar to pour and the honey runs out slowly"
    words = []
    for i, word in enumerate(narration.split()):
        start = round(i * 0.5, 3)
        zero = word.strip(".") in {"tilt", "jar", "pour"}
        words.append([word, start, start if zero else start + 0.45])
    shots = compile_scene_shots({"narration": narration}, 8.0, 0, word_times=words,
                                evidence_states=[_state(1, "pour the honey", "master"),
                                                 _state(2, "you tilt the jar to pour")])
    assert shots[1]["semantic_aligned"] is True
    assert shots[1]["timing_source"] == "measured" and shots[1]["start_sec"] == 1.5


def test_the_render_version_was_bumped_for_the_timing_change():
    # AGENTS.md: pixel or timing changes must update ILLUSTRATED_RENDER_VERSION, or a resumed job
    # serves MP4s cut on the old timings while the plan is recomputed by the new compiler.
    assert render_cache.ILLUSTRATED_RENDER_VERSION != "hold-split-2026-09-30-v1"
    assert "zero-width" in render_cache.ILLUSTRATED_RENDER_VERSION
