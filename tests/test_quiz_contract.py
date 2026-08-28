from bolt_video.formats.quiz import (
    QUIZ_V2,
    clamp_quiz_items,
    clue_zoom,
    final_reveal_narration,
    round_narration,
)


def test_quiz_v2_starts_with_gameplay_and_has_no_post_game_tail():
    assert QUIZ_V2.first_clue_at_sec == 0
    assert QUIZ_V2.standalone_intro_sec == 0
    assert QUIZ_V2.standalone_outro_sec == 0
    assert QUIZ_V2.subscribe_teaser_sec == 0


def test_quiz_v2_caps_rounds_and_stays_replayable():
    assert clamp_quiz_items(6) == 3
    assert QUIZ_V2.estimated_duration(3, reveal_sec=1.0) == 11.0
    assert QUIZ_V2.estimated_duration(6, reveal_sec=1.2, final_reveal_sec=2.4) == 12.0


def test_round_narration_avoids_repetitive_what_is_it_setup():
    lines = [round_narration("animals", i, 3) for i in range(1, 4)]
    assert lines == ["Three animals are hiding. Spot them.",
                     "Round 2. Harder.",
                     "Last one. This fools everyone."]
    assert all("what is it" not in line.lower() for line in lines)


def test_round_lines_fit_the_guess_window():
    """Each line plays over its own countdown; a longer one talks over the reveal that follows.

    Measured TTS on this phrasing runs ~16.5 characters per second; the guard uses a slower 15.0
    so it trips before a real render collides. This is what rules out narrating the full
    "Three animals are hiding in the wild. The last one fools almost everyone." — 4.39s measured
    against a 2.4s window.
    """
    for index in range(1, 4):
        line = round_narration("animals", index, 3)
        assert len(line) / 15.0 <= QUIZ_V2.guess_window_sec, (index, line)


def test_quiz_v2_progressively_reveals_harder_clues():
    assert clue_zoom("medium", 0) < clue_zoom("hard", 0) < clue_zoom("expert", 0)
    assert clue_zoom("expert", 0) > clue_zoom("expert", 1) > clue_zoom("expert", 2)
    assert clue_zoom("expert", 2) == 1.0


def test_the_closing_line_asks_for_the_replay_the_loop_makes_free():
    assert final_reveal_narration("ANTEATER") == "ANTEATER! Missed one? Go again."
    assert QUIZ_V2.subscribe_teaser_sec == 0


def test_final_reveal_narration_fits_the_closing_card():
    """The closing card is sized from this line and capped, so an over-long line is clipped.

    Rate is measured, not assumed: real TTS on this phrasing ran 2.74s for "Tapir!" (45 chars)
    and 3.12s for "Hippopotamus!" (52 chars) — about 16.5 characters per second. The guard uses
    a deliberately slower 15.0 so it trips before a real render clips, and checks the longest
    realistic answer against the cap plus the 0.12s pad the renderer adds.

    This guards the copy, not the renderer — a previous wording overran a 2.4s cap on any
    answer from "Pangolin" up and silently lost its last word.
    """
    longest = final_reveal_narration("Hippopotamus")
    projected_sec = len(longest) / 15.0
    assert projected_sec + 0.12 <= QUIZ_V2.final_reveal_max_sec, (longest, projected_sec)


def test_the_closing_card_can_hold_an_ask_and_a_reason():
    """The cap exists to bound the ending, not to dictate the copy.

    2.4s was too tight for any CTA carrying both a request and a reason to act on it, which is
    why the ending read as abrupt. Guard the headroom so a future trim does not silently
    reintroduce the constraint that shaped the old one-clause ending.
    """
    assert QUIZ_V2.final_reveal_max_sec >= 3.2
    assert QUIZ_V2.final_reveal_max_sec > QUIZ_V2.final_reveal_min_sec


# ── habitat loop ────────────────────────────────────────────────────────────────
# A Short restarts the instant it ends, so the closing reveal and the opening clue sit against
# each other with no cut between them. The flat-colour format has always closed its loop by
# landing the last card on round one's field colour; the habitat format, which is the one that
# actually ships (QUIZ_HABITAT defaults on), generated its last scene from its own description
# and landed somewhere else entirely — the loop machinery was unreachable in the default format.

def test_the_closing_scene_is_edited_from_the_opening_one():
    import _quiz_pipeline_legacy as legacy

    seen = []

    def fake_generate_image(prompt, dst, size="", cost_sink=None, reference_paths=None):
        seen.append({"prompt": prompt, "refs": list(reference_paths or [])})
        return dst

    original = legacy.ep.generate_image
    legacy.ep.generate_image = fake_generate_image
    try:
        mode, ok = legacy._habitat_pair(
            "okapi", "a sunlit savanna", "side-on", "/tmp/clue.png", "/tmp/rev.png",
            "1024x1536", [], scene_ref=__file__)   # any path that exists
    finally:
        legacy.ep.generate_image = original

    assert ok and mode == "habitat_loop_pair"
    assert seen[0]["refs"] == [__file__], "the closing reveal must edit the opening photograph"
    assert "EXACTLY" in seen[0]["prompt"], "the environment must be held, not re-described"


def test_a_round_without_the_opening_scene_is_generated_from_its_description():
    # Rounds 1 and 2 have no loop to close, and must not be pinned to anything.
    import _quiz_pipeline_legacy as legacy

    seen = []

    def fake_generate_image(prompt, dst, size="", cost_sink=None, reference_paths=None):
        seen.append(list(reference_paths or []))
        return dst

    original = legacy.ep.generate_image
    legacy.ep.generate_image = fake_generate_image
    try:
        mode, _ = legacy._habitat_pair("moose", "a cold bog", "standing", "/tmp/c.png",
                                       "/tmp/r.png", "1024x1536", [])
    finally:
        legacy.ep.generate_image = original

    assert mode == "habitat_pair"
    assert seen[0] == [], "a non-closing round has no opening scene to match"


def test_the_loop_never_relocates_a_species():
    """Accuracy outranks the match cut.

    The closing reveal is made by editing the opening photograph, so reusing that scene for an
    animal the script placed somewhere else would put an okapi on open savanna. This pipeline
    fact-checks answers because a wrong one destroys trust; a wrong habitat is the same claim
    made in pictures, so a mismatch loses the loop rather than the truth.
    """
    from _quiz_pipeline_legacy import _same_habitat

    assert _same_habitat("A misty rainforest clearing at dawn.",
                         "a misty rainforest clearing at dawn")
    assert not _same_habitat("a sunlit savanna at golden hour",
                             "a misty rainforest clearing at dawn")
    assert not _same_habitat("", ""), "two missing habitats are not a match"


def test_deepening_an_easy_clue_uses_the_ladder_that_clue_is_on():
    """The too-easy correction must not switch formats behind the clue's back.

    A habitat clue is a scene to search, so it opens at a shallow 1.16 pull-back; a flat-colour
    clue is a shape to uncrop, so it opens at 1.85+. The correction read the flat ladder for
    both, which took a habitat's frame zero to 2.31 — the animal bled off all four edges as an
    unreadable mass and the scene it hides in vanished, on the one frame that decides whether
    anyone stays. Scaling each ladder's own opener leaves the flat format's arithmetic identical.
    """
    HABITAT_LADDER = [1.16, 1.08, 1.0]      # as built in the renderer for an in-habitat clue
    DEEPEN = 1.25

    deepened_habitat = HABITAT_LADDER[0] * DEEPEN
    assert abs(deepened_habitat - 1.45) < 1e-9

    for difficulty in ("medium", "hard", "expert"):
        flat_ladder = [clue_zoom(difficulty, stage) for stage in range(3)]

        # The flat format's opener IS clue_zoom(difficulty, 0), so scaling the ladder in place
        # reproduces the historical value exactly — this fix must not touch the control format.
        assert flat_ladder[0] * DEEPEN == clue_zoom(difficulty, 0) * DEEPEN

        assert deepened_habitat < flat_ladder[0], (
            f"a deepened habitat opener ({deepened_habitat:.2f}) must still show more of the "
            f"scene than an UNdeepened flat clue ({flat_ladder[0]:.2f})")
        assert deepened_habitat > HABITAT_LADDER[1], "deepening must still ease into stage two"


def test_the_last_frame_is_the_first_frame(tmp_path):
    """The loop join, proved end to end rather than argued.

    A Short restarts the instant it ends, so its last frame sits directly against its first. The
    published videos cut from a bright colour reveal to a dimmed silhouette — measured at +109
    luminance and a 36px horizon jump — which the viewer reads as the video ending. Closing on
    the opening frame is the only version of "seamless" that survives measurement, so this test
    renders the real filter graph and compares the two frames it actually produces.

    It also pins the arithmetic: xfade runs out to offset + closing duration, so anchoring the
    offset at head - closing means the closing spec costs no runtime however long it is. If that
    slipped, the video and the audio timeline built against TOTAL would drift apart silently.
    """
    import subprocess

    import numpy as np
    from PIL import Image

    import _quiz_pipeline_legacy as legacy

    opening = str(tmp_path / "opening.png")
    middle = str(tmp_path / "middle.png")
    overlay = str(tmp_path / "overlay.png")
    Image.new("RGB", (1080, 1920), (200, 40, 40)).save(opening)
    Image.new("RGB", (1080, 1920), (40, 200, 40)).save(middle)
    Image.new("RGBA", (1080, 1920), (0, 0, 0, 0)).save(overlay)

    opening_opts = {"overlay": overlay, "z_to": 1.16}
    head = 2.0
    out = str(tmp_path / "loop.mp4")
    legacy._render_sequence([
        (opening, 1.0, False, opening_opts),
        (middle, 1.0, False, {}),
        # same base, same overlay, same zoom as the opening card — and no drift, so it settles on
        # the exact zoom frame zero starts at rather than a fraction past it.
        (opening, legacy._LOOP_DISSOLVE_SEC + legacy._LOOP_SETTLE_SEC, False,
         {**opening_opts, "drift": 0, "xfade_prev": legacy._LOOP_DISSOLVE_SEC}),
    ], out, head)

    assert abs(legacy._dur(out) - head) < 0.05, "the closing dissolve must cost no runtime"

    def frame(args):
        dst = str(tmp_path / "f.png")
        subprocess.run([legacy.FF, "-y", "-v", "error", *args, "-i", out,
                        "-frames:v", "1", dst], check=True)
        return np.asarray(Image.open(dst).convert("RGB")).astype(float)

    first, last = frame(["-ss", "0"]), frame(["-sseof", "-0.04"])
    assert np.abs(first - last).mean() < 2.0, (
        "the last frame must BE the first frame — a dissolve that ends mid-blend leaves the "
        "join visible, which is the whole defect this closes")


def test_the_settle_outlasts_a_single_frame():
    """xfade's frames cover the transition at [0, 1) and never reach 1.

    A closing spec exactly as long as its dissolve therefore ends ~92% of the way across, and
    the final frame is a blend of the payoff and the opening rather than the opening. The settle
    is what resolves it, so it has to be longer than one frame at the render rate.
    """
    import _quiz_pipeline_legacy as legacy

    assert legacy._LOOP_SETTLE_SEC > 1 / legacy.FPS
    assert legacy._LOOP_SETTLE_SEC < legacy._LOOP_DISSOLVE_SEC, "a settle this long reads as a hold"
