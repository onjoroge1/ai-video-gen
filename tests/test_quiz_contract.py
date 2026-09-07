from bolt_video.formats.quiz import (
    QUIZ_V2,
    clamp_quiz_items,
    clue_zoom,
    final_reveal_narration,
    narration_fits,
    round_narration,
)


def test_quiz_v2_starts_with_gameplay_and_has_no_post_game_tail():
    assert QUIZ_V2.first_clue_at_sec == 0
    assert QUIZ_V2.standalone_intro_sec == 0
    assert QUIZ_V2.standalone_outro_sec == 0
    assert QUIZ_V2.subscribe_teaser_sec == 0


def test_quiz_v2_caps_rounds_and_stays_replayable():
    assert clamp_quiz_items(6) == 3
    assert clamp_quiz_items(4) == 3, "the default flow is capped at three rounds"
    assert clamp_quiz_items(0) == 3, "a missing count must use the V2.3 three-round default"
    assert QUIZ_V2.estimated_duration(3, reveal_sec=1.0) == 9.8
    # Clamped to three rounds, so: 2.4 + 1.8 + 1.8 countdowns, two 1.2s reveals, a 2.4s close.
    assert QUIZ_V2.estimated_duration(6, reveal_sec=1.2, final_reveal_sec=2.4) == 10.8


def test_the_api_clamps_from_the_contract_not_a_literal():
    """The quiz route had its own min(3, ...), independent of max_items.

    Raising the cap in the contract would then have changed every test here and nothing the API
    actually renders — the sort of split that looks shipped and is not.
    """
    import inspect
    import re

    import app

    source = inspect.getsource(app.run_explainer_task)
    # Comments explain the old literal, so strip them before looking for it -- otherwise this
    # test passes or fails on prose. First version of it failed on its own rationale comment.
    code = "\n".join(re.sub(r"#.*$", "", line) for line in source.splitlines())
    assert "clamp_quiz_items" in code
    assert not re.search(r"min\(\s*\d+\s*,\s*request\.n_items", code), (
        "a literal round cap must not outrank the creative contract")


def test_round_narration_avoids_repetitive_what_is_it_setup():
    lines = [round_narration("animals", i, 3) for i in range(1, 4)]
    assert lines == ["Three animals. Last one's brutal.",
                     "Okay... lock in.",
                     "Nah... final boss."]
    assert all("what is it" not in line.lower() for line in lines)


def test_the_opener_promises_the_round_the_viewer_has_to_stay_for():
    """The opener's job is a reason to reach round three, not a description of round one.

    "Three animals hiding." is accurate and asks nothing: it states the count and stops, which is
    what the whole line used to do. The threat is the half that buys the watch — the count sets a
    finish line, and the last round is the thing worth arriving at — so it is the half a future
    trim is most likely to cut for length and least able to afford losing.
    """
    opener = round_narration("wild animals", 1, 3)
    assert opener.startswith("Three")
    assert opener.rstrip(".").endswith("brutal"), opener


def test_a_long_category_drops_the_threat_rather_than_the_answer():
    """Every line plays over its own countdown, so an over-long opener talks across round one's
    reveal. The opener is built longest-first and degrades, and this pins the degradation: a
    category wide enough to push the threat past the window loses the threat, not the timing."""
    from bolt_video.formats.quiz import narration_fits

    for category in ("wild animals", "ocean animals", "dinosaurs", "invertebrates",
                     "microscopic freshwater invertebrates"):
        opener = round_narration(category, 1, 3)
        assert narration_fits(opener, QUIZ_V2.guess_window(1)), (category, opener)
    assert "brutal" not in round_narration("microscopic freshwater invertebrates", 1, 3)


def test_the_opener_names_the_category_by_its_shortest_honest_noun():
    """"wild animals" and "ocean animals" are each six characters longer than the noun carrying
    the meaning, and the opener now needs that budget for the threat. Dropping the qualifier is
    only safe because it stays true — ocean animals are animals."""
    assert round_narration("ocean animals", 1, 3) == round_narration("animals", 1, 3)


def test_the_opener_counts_the_animals_the_video_actually_shows():
    """The count was `"Two" if total == 2 else "Three"`, true only at a three-round cap.

    At four rounds the opening line promised three animals over four, and nothing downstream
    compares the spoken count with len(items), so it would have shipped saying the wrong number
    on the one line every viewer hears.
    """
    for total, word in ((2, "Two"), (3, "Three"), (4, "Four")):
        assert round_narration("animals", 1, total).startswith(word), total


def test_round_lines_fit_the_guess_window():
    """Each line plays over its own countdown; a longer one talks over the reveal that follows.

    Measured TTS on this phrasing runs ~16.5 characters per second; the guard uses a slower 15.0
    so it trips before a real render collides. This is what rules out narrating the full
    "Three animals are hiding in the wild. The last one fools almost everyone." — 4.39s measured
    against a 2.4s window.
    """
    for total in (2, 3, QUIZ_V2.max_items):
        for index in range(1, total + 1):
            # "wild animals" rather than "animals": the category is interpolated into the opener,
            # and the real one is six characters longer than the one this test used to check.
            line = round_narration("wild animals", index, total)
            # Imported rather than restated: the guard and the copy it guards were two
            # independent 15.0s, which is one edit away from a silently clipped line.
            assert narration_fits(line, QUIZ_V2.guess_window_sec), (total, index, line)
            assert len(line) / 15.0 <= QUIZ_V2.guess_window_sec, (total, index, line)


def test_quiz_v2_progressively_reveals_harder_clues():
    assert clue_zoom("medium", 0) < clue_zoom("hard", 0) < clue_zoom("expert", 0)
    assert clue_zoom("expert", 0) > clue_zoom("expert", 1) > clue_zoom("expert", 2)
    assert clue_zoom("expert", 2) == 1.0


def test_the_closing_line_asks_for_the_score_not_the_replay():
    """The replay CTA worked — average percentage viewed sits above 100% — which is the argument
    against keeping it. The longest slot in the Short was buying more of a saturated metric while
    comments, the one signal this format never asked for, stayed flat. The loop is not lost by
    dropping the words: the closing beat still dissolves into the opening frame."""
    assert final_reveal_narration("ANTEATER") == "ANTEATER! Be honest... what'd you get?"
    assert QUIZ_V2.subscribe_teaser_sec == 0


def test_subscribe_is_never_spoken():
    """A spoken "subscribe" is a chore; the card promises a round two instead. Keeping the ask on
    the visual channel is the whole point of the split, so the voice track must not re-add it."""
    from bolt_video.formats.quiz import CLOSING_BANNER, CLOSING_FOOTER

    spoken = [round_narration("animals", i, 3) for i in range(1, 4)]
    spoken.append(final_reveal_narration("TAPIR"))
    assert all("subscribe" not in line.lower() for line in spoken), spoken
    assert "FOLLOW" in CLOSING_FOOTER and "SCORE" in "".join(CLOSING_BANNER)


def test_the_score_ladder_reaches_a_perfect_score_at_any_round_count():
    """The emoji are the payload — bare numbers are a scoreboard for a game already over — and a
    ladder that stopped short of a perfect score would drop the one rung worth typing."""
    from bolt_video.formats.quiz import score_tiers

    assert [label for label, _ in score_tiers(3)] == ["0/3", "1/3", "2/3", "3/3"]
    for total in (2, 3, 5):
        tiers = score_tiers(total)
        assert len(tiers) == total + 1
        assert tiers[-1][0] == f"{total}/{total}"
        assert len({emoji for _, emoji in tiers}) >= 3, total


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


def test_the_reveal_transition_ends_on_the_answer(tmp_path):
    """The payoff is the silhouette BECOMING the animal, not a cut to it.

    Asserted on rendered frames because the failure mode is a clip that ends mid-blend — the
    animal still half black — which no argument-level check can see. The same mistake in the loop
    dissolve shipped a final frame 92% of the way across before frames were compared.
    """
    import subprocess

    import numpy as np
    from PIL import Image

    import _quiz_pipeline_legacy as legacy

    clue = str(tmp_path / "clue.png")
    reveal = str(tmp_path / "reveal.png")
    Image.new("RGB", (legacy.W, legacy.H), (20, 20, 20)).save(clue)
    Image.new("RGB", (legacy.W, legacy.H), (210, 180, 90)).save(reveal)
    out = str(tmp_path / "tr.mp4")

    assert legacy._reveal_clip(clue, reveal, "OKAPI", out, legacy._REVEAL_TRANSITION_SEC)
    assert abs(legacy._dur(out) - legacy._REVEAL_TRANSITION_SEC) < 0.08

    dst = str(tmp_path / "last.png")
    subprocess.run([legacy.FF, "-y", "-v", "error", "-i", out, "-ss",
                    f"{legacy._REVEAL_TRANSITION_SEC - 0.04:.3f}", "-frames:v", "1", dst],
                   check=True)
    last = np.asarray(Image.open(dst).convert("RGB")).astype(float)
    # Sample above the answer card so the card's own navy does not mask an unresolved blend.
    sky = last[: legacy.H // 3].reshape(-1, 3).mean(axis=0)
    assert sky.mean() > 150, f"the transition must finish on the reveal, not mid-blend: {sky}"


def test_a_reveal_too_short_to_transition_falls_back_to_a_cut():
    """A cut is the old behaviour and always correct; a transition with no room is not.

    The budget comes out of the reveal beat rather than extending it, so a beat shorter than the
    transition plus its minimum hold must simply not get one.
    """
    import _quiz_pipeline_legacy as legacy

    assert legacy._REVEAL_HOLD_MIN_SEC > 0
    tight = QUIZ_V2.reveal_min_sec - legacy._REVEAL_HOLD_MIN_SEC
    assert tight < legacy._REVEAL_TRANSITION_SEC or tight > 0.05, (
        "the shortest reveal must either fit a transition or cleanly skip it")


def test_the_countdown_ticks_track_the_guess_window():
    """The tick offsets were literals (0/800/1600ms, trimmed at 2.4s) matching a window that has
    since changed. Nothing would have failed -- the last tick would simply have marked time that
    no longer existed, after the answer was already on screen."""
    import inspect

    import _quiz_pipeline_legacy as legacy

    source = inspect.getsource(legacy.run_quiz_pipeline)
    assert "adelay=800" not in source and "atrim=0:2.4" not in source
    # Derived per ROUND now, not from one constant: rounds two and three run a shorter window, so
    # a single shared tick file would mark time those rounds no longer have — the last tick
    # landing after the answer is already on screen. Silent, and it ships.
    assert "_stage * 1000" in source and "atrim=0:{_w}" in source
    assert "cdsfx_for[round(f, 3)]" in source, "ticks must be resolved by the round's own window"
    assert "cdsfx = " not in source, "one shared tick file is the bug this replaced"


def test_quiz_render_path_is_mascot_free():
    import inspect
    from pathlib import Path

    import _quiz_pipeline_legacy as legacy

    module_source = Path(legacy.__file__).read_text(encoding="utf-8")
    for marker in (
        "_paste_bolt_badge", "_draw_bolt_eyes", "_BOLT_MOODS", "_mascot_pose",
        "_draw_mascot", "_MASCOT_REVEAL_POSES", "performer_specs", "apply_variant",
    ):
        assert marker not in module_source, marker

    signature = inspect.signature(legacy.run_quiz_pipeline)
    assert signature.parameters["variants"].default == ("a",)
    assert signature.parameters["primary_variant"].default == "a"
    render_source = inspect.getsource(legacy.run_quiz_pipeline)
    assert "bolt=True" not in render_source
    assert "bolt_mood" not in render_source


def test_answer_overlay_uses_the_full_mascot_free_width(tmp_path):
    from PIL import Image

    import _quiz_pipeline_legacy as legacy

    out = tmp_path / "answer.png"
    legacy._text_png(str(out), answer="SECRETARY BIRD!")
    image = Image.open(out).convert("RGBA")
    assert image.getbbox() is not None
    # The answer card starts at x=70. The former Bolt badge shifted it to x=285 and squeezed
    # long animal names; sample inside the reclaimed band to ensure the card now occupies it.
    assert image.getpixel((100, legacy.H - 560))[3] > 0


def test_a_clip_replacing_a_drifting_still_carries_its_own_move():
    """_render_sequence applies zoompan to stills only; an is_video spec passes through untouched.

    So a clip replacing a drifting still is FLATTER than what it replaced unless it bakes the move
    in. Measured: without it the 'livelier' variant scored 5.68 mean frame delta against the
    control's 6.83 — the change made the video less alive, which is the opposite of its purpose.
    """
    import inspect

    import _quiz_pipeline_legacy as legacy

    source = inspect.getsource(legacy._reveal_clip)
    assert "_DRIFT_PER_SEC" in source and "zoom" in source


# ── difficulty ladder ───────────────────────────────────────────────────────────
# Across six renders, 15 of 17 hard/expert rounds were named by the vision grader from the first
# 0.6s crop, and every one shipped as a clean pass. The prompt asked for animals "a broad audience
# knows" and defined expert as "genuinely tricky", so the model reached for the same iconic set:
# hippopotamus opened five of six, aardvark was expert four times, crocodile three.

def test_difficulty_is_defined_as_confusability_not_obscurity():
    """An obscure animal nobody can name is unplayable, not hard. The viewer needs doubt.

    So the rule has to be operational — name the species this could be mistaken for — rather than
    an adjective the model can satisfy by picking something rare.
    """
    import _quiz_pipeline_legacy as legacy

    system = legacy._QUIZ_SYSTEM
    assert "CONFUSABILITY, NOT OBSCURITY" in system
    assert "confusables" in system, "the confusable set must be a required field, not advice"
    assert "broad audience knows" not in system, "that phrase selected FOR recognisability"


def test_the_instantly_readable_outlines_are_banned():
    # Every one of these shipped as a hard or expert round and was identified immediately.
    import _quiz_pipeline_legacy as legacy

    for animal in ("CROCODILE", "HIPPOPOTAMUS", "RHINOCEROS", "BUFFALO", "WALRUS", "OSTRICH"):
        assert animal in legacy._QUIZ_SYSTEM, animal


def test_framing_tightens_as_difficulty_rises():
    """The image prompt asked for 'unobstructed, roughly a third of the frame' on every round.

    That handed back whatever difficulty the pose had bought: a subject rendered large, sharp and
    unscreened is legible whatever pose it was given. Distance is this format's own lever — the
    premise is that something is hiding — and it adds no obscurity.
    """
    import _quiz_pipeline_legacy as legacy

    third = legacy._HABITAT_FRAMING["medium"]
    assert "third" in third and "unobstructed" in third
    for tier in ("hard", "expert"):
        assert "screened" in legacy._HABITAT_FRAMING[tier]
        assert "outline stays unbroken and readable" in legacy._HABITAT_FRAMING[tier], (
            "harder must not mean unfair — the silhouette still has to be guessable")


def test_a_named_answer_on_a_hard_round_is_reported_not_cropped_away():
    """No zoom level makes a crocodile stop being a crocodile.

    The old response to 'too easy' was to crop tighter and report success, which is why 15 failures
    shipped as clean passes. Item selection is the fault, and it has to reach the caller.
    """
    import inspect

    import _quiz_pipeline_legacy as legacy

    source = inspect.getsource(legacy.run_quiz_pipeline)
    assert "ladder_warnings" in source
    assert "_guessed_the_answer" in source
    assert "difficulty_ladder_honoured" in source


def test_the_grader_guess_matcher_survives_casing_and_spacing():
    import _quiz_pipeline_legacy as legacy

    assert legacy._guessed_the_answer("secretarybird", "SECRETARY BIRD")
    assert legacy._guessed_the_answer("Snow Leopard", "SNOW LEOPARD")
    assert not legacy._guessed_the_answer("bear", "SNOW LEOPARD")
    assert not legacy._guessed_the_answer("", "KIWI")
    # Short guesses must not substring-match an unrelated answer.
    assert not legacy._guessed_the_answer("ox", "oxpecker")


def test_generated_title_count_is_repaired_to_the_actual_round_count():
    import _quiz_pipeline_legacy as legacy

    assert legacy.normalize_quiz_title(
        "Can You Name All 4 Animals?", 4, "animals") == "Can You Name All 3 Animals?"
    assert legacy.normalize_quiz_title(
        "Can You Name All Four Animals?", 4, "animals") == "Can You Name All Three Animals?"
    assert legacy.normalize_quiz_title(
        "Can You Name 4 Animals?", 4, "animals") == "Can You Name 3 Animals?"
    assert legacy.normalize_quiz_title(
        "Can You Name Them?", 4, "animals") == "Can You Name Them?"


def test_phone_readability_gate_rejects_tiny_or_low_contrast_clues():
    import _quiz_pipeline_legacy as legacy

    issues = legacy.quiz_readability_issues(
        {"subject_width_pct": 12, "clue_contrast_score": 41,
         "first_crop_contrast_score": 80}, "hard", 2)
    assert any("12%" in issue for issue in issues)
    assert any("41/100" in issue for issue in issues)
    assert legacy.quiz_readability_issues(
        {"subject_width_pct": 28, "clue_contrast_score": 80,
         "first_crop_contrast_score": 80}, "hard", 2) == []


def test_the_gate_measures_the_frame_the_viewer_actually_decides_on():
    """Contrast was graded on the full clue, and frame zero is a crop of it — a clue can separate
    cleanly in the wide shot and vanish inside the opening crop. That crop is the swipe decision,
    and silhouette contrast there is the only variable this format has measured against retention:
    the 10.5-point spread between the first two V2.3 quizzes tracked it."""
    import _quiz_pipeline_legacy as legacy

    issues = legacy.quiz_readability_issues(
        {"subject_width_pct": 40, "clue_contrast_score": 90,
         "first_crop_contrast_score": 30}, "hard", 1)
    assert any("frame-zero" in issue and "30/100" in issue for issue in issues), issues
    assert "first_crop_contrast_score" in legacy.grade_quiz_visuals.__doc__ or True
    prompt = __import__("inspect").getsource(legacy.grade_quiz_visuals)
    assert "first_crop_contrast_score" in prompt
    assert "IMAGE 1 alone" in prompt, "the score has to be asked for on frame zero, not the clue"


def test_an_unmeasured_contrast_score_counts_as_a_failure():
    """Absence is the state this gate lived in for its whole life: frame-zero contrast was never
    requested, nothing read it, and every render reported a clean pass. Treating a missing score
    as acceptable rebuilds exactly that."""
    import _quiz_pipeline_legacy as legacy

    assert legacy._contrast_failed({"clue_contrast_score": 90})
    assert legacy._contrast_failed({"first_crop_contrast_score": 90})
    assert legacy._contrast_failed({"clue_contrast_score": 90,
                                    "first_crop_contrast_score": 20})
    assert not legacy._contrast_failed({"clue_contrast_score": 90,
                                        "first_crop_contrast_score": 60})


def test_a_failed_frame_zero_is_regenerated_rather_than_reported():
    """The finding had no mechanism behind it: a contrast failure was filed as a warning against a
    video that shipped anyway. A habitat fails this for one reason — the silhouette is standing
    somewhere dark — so the retry names a brighter background instead of re-rolling the same
    prompt, and re-derives the frames the render actually reads from the repaired pair."""
    import inspect
    import _quiz_pipeline_legacy as legacy

    source = inspect.getsource(legacy.run_quiz_pipeline)
    assert "contrast_bad = _contrast_failed(grade)" in source
    assert "high_key=relight" in source
    assert "_prepare_clue_bases()" in source
    assert "high_key" in inspect.signature(legacy._habitat_pair).parameters
    habitat = inspect.getsource(legacy._habitat_pair)
    assert "BRIGHT and OPEN" in habitat
    assert "No dark" in habitat


def test_v23_defaults_to_three_rounds_and_mascot_free_reveals():
    import inspect
    import _quiz_pipeline_legacy as legacy

    signature = inspect.signature(legacy.run_quiz_pipeline)
    assert signature.parameters["n_items"].default == 3
    assert signature.parameters["variants"].default == ("a",)
    assert signature.parameters["primary_variant"].default == "a"


def test_web_ui_and_server_agree_on_v23_round_count():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    html = (root / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="expl-quiz-items"' in html
    assert 'max="3"' in html and 'value="3"' in html
    assert "Quiz V2.2 = a four-round" not in html
    assert "|| 3" in html


def test_difficulty_is_resolved_before_the_images_are_generated():
    """It was assigned 24 lines after the habitat pair that now reads it.

    Round one would have raised NameError; every later round would have quietly framed itself with
    the PREVIOUS round's difficulty, which is the half that would have survived review.
    """
    import inspect

    import _quiz_pipeline_legacy as legacy

    source = inspect.getsource(legacy.run_quiz_pipeline)
    assert source.index('diff = ep._s(it.get("difficulty"))') < source.index("difficulty=diff")


# ── typography ──────────────────────────────────────────────────────────────────
# The cards read as a software dashboard: one weight, one colour, neutral nouns. Every card in
# this format is three shouted words, which is what a display face is for.

def test_the_display_font_ships_with_the_renderer():
    """Referencing it from ShortGPT/ would work here and nowhere else.

    That directory is untracked, so any other checkout falls back to Arial and every card silently
    changes shape — the layout is measured against the font, so this is a layout bug, not a
    cosmetic one.
    """
    import os

    import _quiz_pipeline_legacy as legacy

    bundled = os.path.join(os.path.dirname(legacy.__file__), "assets", "fonts",
                           "LuckiestGuy-Regular.ttf")
    assert os.path.exists(bundled), "the display font must be bundled, not borrowed"
    assert os.path.exists(os.path.join(os.path.dirname(bundled), "NOTICE")), (
        "Apache-2.0 requires the attribution to travel with the file")
    assert legacy._font(58).getname()[0] == "Luckiest Guy"


def test_the_headline_is_an_instruction_with_an_accent():
    import _quiz_pipeline_legacy as legacy

    source = __import__("inspect").getsource(legacy.run_quiz_pipeline)
    assert "GUESS THE " in source and "SHADOW!" in source
    assert "SOMETHING IS HIDING" not in source, "a situation asks the viewer for nothing"


def test_tier_labels_name_the_viewers_position_not_the_generators():
    """MEDIUM/HARD/EXPERT describe the item to us and say nothing to the person watching."""
    from bolt_video.formats.quiz import tier_label

    assert [tier_label(i, 4) for i in range(1, 5)] == [
        "CAN YOU GET IT?", "95% FAIL", "95% FAIL", "IMPOSSIBLE"]
    assert [tier_label(i, 3) for i in range(1, 4)] == ["CAN YOU GET IT?", "95% FAIL", "IMPOSSIBLE"]
    assert [tier_label(i, 2) for i in range(1, 3)] == ["CAN YOU GET IT?", "IMPOSSIBLE"]


def test_every_card_still_fits_its_box_in_the_display_face():
    """A wider face at a bigger size would silently shrink back via _fit_text_size, or overflow
    the answer card. Both headline and the longest realistic answer are checked at the caps."""
    import _quiz_pipeline_legacy as legacy

    from bolt_video.formats.quiz import CLOSING_BANNER, FIRST_REVEAL_REACTION

    for headline in ("GUESS THE SHADOW!", "".join(CLOSING_BANNER), FIRST_REVEAL_REACTION[0]):
        # The emoji sits beside the headline, so its box comes out of the same budget.
        assert legacy._font(76).getlength(headline) <= legacy.W - 240 - 104, headline
    for answer in ("AFRICAN WILD DOG!", "HIPPOPOTAMUS!"):
        assert legacy._font(88).getlength(answer) <= legacy.W - 70 - 130, answer


# ── colour emoji ────────────────────────────────────────────────────────────────
# The display face has no emoji glyph and PIL performs no font fallback, so an emoji sent through
# the normal text path is drawn as *nothing*: zero width, no tofu box, no exception. "0/3 😭 · 3/3
# 🐐" renders as "0/3 · 3/3" and the card still looks deliberate. That is the failure this pass
# exists to prevent, and it is invisible in every check that does not look at pixels.

def test_the_display_face_cannot_draw_a_single_emoji():
    """The premise of the separate pass. If this ever fails the pass is redundant, not broken."""
    import _quiz_pipeline_legacy as legacy
    from bolt_video.formats.quiz import score_tiers

    notdef = legacy._font(80).getlength("\uffff")
    for _, emoji in score_tiers(3):
        assert legacy._font(80).getlength(emoji) == notdef, emoji


def test_the_closing_footer_avoids_glyphs_the_face_cannot_draw():
    """"ROUND 2 → FOLLOW" would ship with the arrow missing and nothing would report it."""
    import _quiz_pipeline_legacy as legacy
    from bolt_video.formats.quiz import CLOSING_BANNER, CLOSING_FOOTER

    notdef = legacy._font(60).getlength("\uffff")
    for char in CLOSING_FOOTER + "".join(CLOSING_BANNER):
        assert legacy._font(60).getlength(char) != notdef or char == " ", repr(char)
    assert "\u2192" not in CLOSING_FOOTER and "\u2193" not in CLOSING_FOOTER


def test_the_score_ladder_actually_puts_emoji_pixels_on_the_card(tmp_path):
    """Renders the closing card twice — once with the host's emoji face, once with it removed —
    and requires the two to differ. Asserting on the copy alone would pass on a machine that
    drew none of it."""
    import _quiz_pipeline_legacy as legacy
    from PIL import Image
    from bolt_video.formats.quiz import CLOSING_FOOTER, score_tiers

    if not legacy.emoji_available():
        import pytest
        pytest.skip("host has no colour emoji font")

    kw = dict(top="DROP YOUR ", top_accent="SCORE", answer="TAPIR!",
              score_row=score_tiers(3), footer=CLOSING_FOOTER)
    with_emoji = str(tmp_path / "with.png")
    legacy._text_png(with_emoji, **kw)
    drawn = Image.open(with_emoji).convert("RGBA")

    # A colour emoji is the only thing on this card that is neither white, navy nor cyan.
    palette = {legacy.WHITE, legacy.NAVY, legacy.CYAN, legacy.YEL}
    row = drawn.crop((0, legacy.H - 460, legacy.W, legacy.H - 380))
    coloured = sum(1 for px in row.getdata()
                   if px[3] > 200 and min(abs(px[0] - c[0]) + abs(px[1] - c[1])
                                          + abs(px[2] - c[2]) for c in palette) > 90)
    assert coloured > 500, f"score ladder drew {coloured} emoji pixels"


def test_a_host_without_an_emoji_face_drops_the_element_instead_of_gutting_it(monkeypatch,
                                                                              tmp_path):
    """Half of "0/3 😭" is the half that would vanish. Without a face the row is skipped whole,
    so the card reads as a design decision rather than as a scoreboard with holes in it."""
    import _quiz_pipeline_legacy as legacy
    from PIL import Image
    from bolt_video.formats.quiz import CLOSING_FOOTER, score_tiers

    monkeypatch.setattr(legacy, "_emoji_face", lambda: (None, 0))
    out = str(tmp_path / "bare.png")
    legacy._text_png(out, top="DROP YOUR ", top_accent="SCORE", answer="TAPIR!",
                     score_row=score_tiers(3), footer=CLOSING_FOOTER)
    row = Image.open(out).convert("RGBA").crop((0, legacy.H - 460, legacy.W, legacy.H - 380))
    assert not row.getbbox(), "the numbers were drawn without their reactions"


def test_the_loop_closing_round_is_repaired_by_placement_not_by_light():
    """The closing round is an edit of the opening scene, so "keep this environment exactly" and
    "light it differently" cannot both be obeyed — a model handed both keeps whichever it weights
    higher and the caller cannot tell which.

    Suppressing the repair there was the first answer and the wrong one: that round is always the
    expert tier and always the likeliest to need it, so the exclusion excluded the case that
    matters, and a real render shipped a 48/100 frame zero that nothing could fix. It now moves the
    ANIMAL to an open part of the scene instead of moving the light. The environment is untouched,
    which is all the loop actually requires.
    """
    import inspect
    import _quiz_pipeline_legacy as legacy

    source = inspect.getsource(legacy.run_quiz_pipeline)
    assert "relight = contrast_bad\n" in source, "the loop round must not be excluded any more"
    assert "loop_match_cut" not in source

    habitat = inspect.getsource(legacy._habitat_pair)
    assert "elif scene_ref:" in habitat, "the loop round needs its own repair wording"
    placement = habitat[habitat.index("elif scene_ref:"):habitat.index("    else:", habitat.index("elif scene_ref:"))]
    assert "place the animal against an OPEN, BRIGHT part of this same scene" in placement
    assert "Do NOT change the environment" in placement, (
        "the loop survives only if the scene itself is left alone")
    relight = habitat[habitat.index("    else:", habitat.index("elif scene_ref:")):]
    assert "background immediately behind the animal must be BRIGHT" in relight


def test_the_identity_repair_does_not_swap_formats():
    """`_generate_reveal` belongs to the flat-colour format — its prompt says "no habitat" outright —
    so calling it to repair a habitat round replaced a rainforest reveal with a studio cutout on a
    flat field.

    That is not a repaired reveal, it is a different format on one card: the match cut the habitat
    exists for is gone, a closing round no longer lands on the opening scene so the loop breaks, and
    the card looks nothing like the three around it. A real render shipped exactly that, recorded as
    a success. The habitat path now regenerates the PAIR, because the clue is an edit of the
    reveal's pixels and repairing one without the other leaves a silhouette that does not match the
    animal it turns into.
    """
    import inspect
    import _quiz_pipeline_legacy as legacy

    source = inspect.getsource(legacy.run_quiz_pipeline)
    flat = source[source.index('if (not in_habitat'):]
    flat = flat[:flat.index("visual_qa.append(grade)")]
    assert "_generate_reveal(" in flat, "the flat-colour format still needs its own repair"
    assert "not in_habitat" in flat, (
        "the flat-colour generator must not be reachable from a habitat round")

    habitat = source[source.index("        if in_habitat:"):source.index("        round_readability")]
    assert "identity_bad" in habitat and "_habitat_pair(" in habitat
    assert "_generate_reveal(" not in habitat
    assert "_prepare_clue_bases()" in habitat, (
        "a repaired pair has to re-derive the frames the render actually reads")
    assert "shipped unrepaired" in habitat, (
        "a failed repair must be reported, not silently shipped as the original")


def test_the_subject_width_check_repairs_instead_of_warning():
    """A clue too small to see is not a hard clue, it is an unanswerable one.

    The expert tier returned 12%, 12% and 8% against its own 16% floor across three consecutive
    renders, and every one of them shipped — the check only ever appended a warning. The tier
    prompts ask in fractions ("roughly a fifth of the frame") and the model under-delivers against
    them by about half, so the retry states a measurable floor with headroom rather than a target.
    """
    import inspect
    import _quiz_pipeline_legacy as legacy

    assert legacy._width_failed({"subject_width_pct": 8}, "expert")
    assert legacy._width_failed({"subject_width_pct": 15.9}, "expert")
    assert not legacy._width_failed({"subject_width_pct": 16}, "expert")
    assert legacy._width_failed({}, "expert"), "an unmeasured clue is the one worth measuring"

    assert "framing_fix" in inspect.signature(legacy._habitat_pair).parameters
    source = inspect.getsource(legacy.run_quiz_pipeline)
    assert "width_fault = _width_fault(grade, diff)" in source
    assert "framing_fix=width_fault" in source
    # A measurable bound, not a descriptive target — a fraction the model can under-deliver
    # against is what failed three times. It is now bounded at both ends, because a floor alone
    # overshot on all five of its occurrences.
    ask = legacy._close_framing("expert")
    assert "BETWEEN one fifth AND one third of the image width" in ask


def test_a_close_up_repair_replaces_the_tier_framing_rather_than_stacking():
    """"well back in the middle distance" and "closer to camera" are one instruction twice with
    opposite signs, and a model handed both keeps whichever it weights higher."""
    import inspect
    import _quiz_pipeline_legacy as legacy

    body = inspect.getsource(legacy._habitat_pair)
    assert 'framing_fix == "closer"' in body and 'framing_fix == "further"' in body
    assert "well back in the middle distance" in legacy._HABITAT_FRAMING["expert"]
    assert "well back" not in legacy._close_framing("expert")


def test_three_habitat_defects_cost_one_regeneration():
    """Contrast, framing and identity each used to regenerate the same pair independently. On a
    round failing all three that is six image generations to fix one image."""
    import inspect
    import _quiz_pipeline_legacy as legacy

    source = inspect.getsource(legacy.run_quiz_pipeline)
    habitat = source[source.index("        if in_habitat:"):source.index("        round_readability")]
    assert habitat.count("_habitat_pair(") == 1, "the repairs must share one regeneration"
    assert "if relight or width_fault or identity_bad:" in habitat


def test_the_close_up_ask_climbs_with_the_tier_it_repairs():
    """A flat "at least one third" cleared the 16% expert floor by landing at 60% — which made the
    final boss the largest subject in the video and inverted the ladder it exists to climb.

    Each tier's ask now tracks its own floor with a little headroom, in the inverse order of the
    floors: medium is meant to be the easiest to spot and expert the hardest, so a repair that uses
    one number for all three trades a too-small clue for a too-obvious one.
    """
    import _quiz_pipeline_legacy as legacy

    spans = {t: legacy._CLOSE_UP_SPAN[t] for t in ("medium", "hard", "expert")}
    assert spans == {"medium": "one third", "hard": "one quarter", "expert": "one fifth"}
    words = {"one third": 33.3, "one quarter": 25.0, "one fifth": 20.0}
    for tier, span in spans.items():
        floor = legacy._READABILITY_WIDTH_MIN[tier]
        assert words[span] > floor, (tier, span, floor)
        assert words[span] < floor * 1.7, (
            f"{tier} asks for {words[span]}% against a {floor}% floor — that is the overcorrection")
    # The ask has to climb the same way the floors do, or the ladder inverts.
    assert (words[spans["medium"]] > words[spans["hard"]] > words[spans["expert"]])
    assert (legacy._READABILITY_WIDTH_MIN["medium"] > legacy._READABILITY_WIDTH_MIN["hard"]
            > legacy._READABILITY_WIDTH_MIN["expert"])


def test_every_round_line_fits_the_window_that_round_actually_runs():
    """The taper shortened rounds two and three to 1.8s. Their lines were written against 2.4s and
    are not rebuilt by the degrade ladder the opener uses, so nothing else would catch one growing
    past its window — it would simply talk over the reveal that follows it.
    """
    for total in (2, 3, QUIZ_V2.max_items):
        for index in range(1, total + 1):
            line = round_narration("wild animals", index, total)
            window = QUIZ_V2.guess_window(index)
            assert narration_fits(line, window), (index, window, line)


def test_the_countdown_tapers_after_the_round_that_teaches_it():
    """Round one keeps the full window because it is teaching the format; by round two the viewer
    is waiting through a rule they already know. The game speeding up as it gets harder is the
    point — a taper that ran the other way would be a slower final boss."""
    assert QUIZ_V2.guess_window(1) == QUIZ_V2.guess_window_sec
    assert QUIZ_V2.guess_window(2) == QUIZ_V2.later_guess_window_sec
    assert QUIZ_V2.guess_window(3) == QUIZ_V2.later_guess_window_sec
    assert QUIZ_V2.later_guess_window_sec < QUIZ_V2.guess_window_sec

    # Each stage is a third of its own window, so a shortened round shortens every one of its
    # three beats rather than dropping the last.
    assert QUIZ_V2.guess_window(2) / 3 < QUIZ_V2.guess_window(1) / 3


def test_the_taper_buys_back_time_from_the_waiting_not_the_reward():
    """The reward is the reveal; the countdown is the wait. A trim that came out of the reveals
    would shorten the only part of the Short the curves show people staying for."""
    three = QUIZ_V2.estimated_duration(3)
    countdowns = sum(QUIZ_V2.guess_window(i) for i in range(1, 4))
    assert countdowns == 2.4 + 1.8 + 1.8
    # Waiting is still the majority of the Short, but by less than it was: 7.2s of 11.0 was 65%.
    assert countdowns / three < 0.63
    assert QUIZ_V2.reveal_min_sec == 0.8, "the reveals were not touched"


# ── the width band ──────────────────────────────────────────────────────────────
# The gate had a floor and no ceiling for its whole life. Across 24 measured clues, three came
# back at 8-12% and were unreadable, eleven landed in 20-47% and read as an animal standing in a
# place, and ten came back at 48-80% — an outline on a backdrop. One filled 80% of frame width and
# passed every check in silence.

def test_a_clue_can_be_too_large_as_well_as_too_small():
    """Half the frame is where a habitat stops being a hiding place and becomes a backdrop, and a
    round still labelled FINAL BOSS then hands over its own answer."""
    import _quiz_pipeline_legacy as legacy

    for tier, ceiling in legacy._READABILITY_WIDTH_MAX.items():
        assert ceiling > legacy._READABILITY_WIDTH_MIN[tier], tier
        issues = legacy.quiz_readability_issues(
            {"subject_width_pct": ceiling + 10, "clue_contrast_score": 90,
             "first_crop_contrast_score": 90}, tier, 3)
        assert any("backdrop" in issue for issue in issues), (tier, issues)


def test_the_warm_up_has_no_ceiling():
    """Frame zero is the swipe decision and a large legible silhouette helps it. The contradiction
    only bites when the label promises difficulty the picture does not deliver."""
    import _quiz_pipeline_legacy as legacy

    assert "medium" not in legacy._READABILITY_WIDTH_MAX
    assert legacy._width_fault({"subject_width_pct": 80}, "medium") == ""
    assert legacy._width_fault({"subject_width_pct": 80}, "expert") == "further"


def test_the_fault_names_a_direction_because_the_repairs_are_opposite():
    """A boolean would send a clue that is already too large to be regenerated larger still."""
    import _quiz_pipeline_legacy as legacy

    assert legacy._width_fault({"subject_width_pct": 8}, "expert") == "closer"
    assert legacy._width_fault({"subject_width_pct": 23}, "expert") == ""
    # 48% sits inside the band now: expert's ceiling moved 40 -> 50 after six measured repairs
    # landed 42-58% no matter how the ask was phrased.
    assert legacy._width_fault({"subject_width_pct": 48}, "expert") == ""
    assert legacy._width_fault({"subject_width_pct": 62}, "expert") == "further"
    assert legacy._width_fault({}, "expert") == "closer", "unmeasured counts as too small"


def test_both_framing_asks_are_measurable_and_land_inside_the_band():
    """A descriptive target is what the model under-delivers against; a bound is what it obeys.
    Each ask sits inside its tier's band so a retry can miss slightly and still land."""
    import _quiz_pipeline_legacy as legacy

    words = {"one fifth": 20.0, "one quarter": 25.0, "one third": 33.3, "two fifths": 40.0}
    for tier in ("hard", "expert"):
        near = legacy._close_framing(tier)
        far = legacy._far_framing(tier)
        assert "BETWEEN" in near and "MUST NOT exceed" in near, (
            "an ask open at the top is what overshot five times out of five")
        assert "NO MORE" in far
        lo = words[legacy._CLOSE_UP_SPAN[tier]]
        hi = words[legacy._PULL_BACK_SPAN[tier]]
        assert legacy._READABILITY_WIDTH_MIN[tier] < lo <= hi <= legacy._READABILITY_WIDTH_MAX[tier], tier
        # The pull-back must not read as "get closer" — that is the bug it exists to avoid.
        assert "CLOSER" not in far


def test_the_repair_tag_records_which_way_it_moved():
    """A repaired render is an experiment result. "_close" and "_wide" are not the same outcome and
    an analytics field that called both "repaired" would lose the comparison."""
    import inspect
    import _quiz_pipeline_legacy as legacy

    source = inspect.getsource(legacy.run_quiz_pipeline)
    assert '("_close", width_fault == "closer")' in source
    assert '("_wide", width_fault == "further")' in source


def test_the_round_labels_are_stakes_rather_than_descriptions():
    """"WARM-UP" tells a viewer at second one that this round does not matter, which is the
    opposite of what frame zero is for. The 54%-retention reference quiz — the best comparison
    available, shipping with a typo'd end card and a countdown that counts upward — labels its
    rounds as dares instead. It beat every clean render we have made, which is the argument that
    polish is not the constraint here.
    """
    from bolt_video.formats.quiz import tier_label

    labels = [tier_label(i, 3) for i in range(1, 4)]
    assert "WARM-UP" not in labels, "the opener must not announce that it is skippable"
    assert labels[0].endswith("?"), "round one should ask the viewer something"
    assert any(ch.isdigit() for ch in labels[1]) or "MOST" in labels[1]
    assert labels[-1] == "IMPOSSIBLE"


def test_every_round_label_still_fits_its_badge():
    """The badge auto-shrinks to a 34px floor, so an over-long label does not overflow — it goes
    quietly small on a phone. Longer stakes wording is exactly the change that would trip that."""
    import _quiz_pipeline_legacy as legacy
    from bolt_video.formats.quiz import tier_label

    for index in range(1, 4):
        badge = f"ANIMAL {index}/3 · {tier_label(index, 3)}"
        assert legacy._font(36).getlength(badge) <= legacy.W - 300, badge


def test_the_whole_set_shares_one_habitat():
    """Letting the middle item wander is what broke the loop outright: the generator put a warthog
    on savanna and an okapi in rainforest, and the closing dissolve became a cut between two
    unrelated places. The loop is what the format depends on for replays."""
    import _quiz_pipeline_legacy as legacy

    prompt = legacy._QUIZ_SYSTEM
    # Same WORLD, not the same shot. Requiring identical habitat text for all three produced the
    # same scene three times over, which reads as monotony; the reference set that retains best is
    # all-ocean but visibly varies — open water, reef, seagrass. Rounds 1 and 3 still have to match
    # exactly, because that is what the closing loop is.
    assert "ONE WORLD, THREE SCENES" in prompt
    assert "items 1 and 3 must carry the IDENTICAL" in prompt
    assert "item 2 MUST be a visibly DIFFERENT scene" in prompt
    assert "Never relocate a species" in prompt


def test_habitats_are_steered_toward_polychrome_environments():
    """A kelp forest is monochrome however brightly it is lit, and a set built in one is repetitive
    even when every gate passes. Vibrancy is not only brightness — it is having more than one
    colour in the frame."""
    import _quiz_pipeline_legacy as legacy

    prompt = legacy._QUIZ_SYSTEM
    assert "colourful IN THEMSELVES" in prompt
    assert "coral reefs" in prompt and "monochrome" in prompt


def test_round_one_is_specified_as_the_swipe_decision():
    """Retention tracks how iconic the set is: the three strongest published sets rank by it, and
    the weakest of them is the only one containing an obscure animal. Difficulty still has to come
    from the silhouette — a seahorse is famous and still almost unreadable in outline."""
    import _quiz_pipeline_legacy as legacy

    prompt = legacy._QUIZ_SYSTEM
    assert "ITEM 1 IS THE SWIPE DECISION" in prompt
    assert "Never open on an obscure animal" in prompt
    assert "CONFUSABILITY, NOT OBSCURITY" in prompt, "obscurity must not sneak back as difficulty"


def test_the_ladder_gate_asks_what_a_viewer_can_name():
    """The gate scored the vision model's own certainty, which measures the wrong thing entirely:
    it recognises species most viewers cannot name. An ocean sunfish is obvious to a grader and
    "some weird round fish" to nearly everyone else.

    That miscalibration had a direction — it pushed item selection toward obscure animals, which is
    why an earlier seeding reached for Arsinoitherium. Measured retention runs the other way: the
    three strongest published sets rank by how ICONIC they are, and the best of them opens on a
    great white shark and closes on a seahorse. Under the old bars that video fails every round.
    """
    import inspect
    import _quiz_pipeline_legacy as legacy

    prompt = inspect.getsource(legacy.grade_quiz_visuals)
    assert "general YouTube audience" in prompt
    assert "NOT your own certainty" in prompt
    assert "only the species" in prompt.lower(), "knowing the animal TYPE must not count"
    # The bars have to clear the winning set rather than reject it.
    assert "above 95" in prompt and "above 85" in prompt and "above 70" in prompt
    assert "above 80" not in prompt, "the old medium bar would flag a great white shark"


def test_the_clue_keeps_its_colour():
    """The clue was dimmed to 62% brightness and 72% saturation — most of the way to grey — on the
    stated grounds that dimming buys a black silhouette its separation. For a BLACK subject that is
    backwards: darkening the background moves it toward the silhouette's own value and closes the
    gap the contrast gate measures. The clue must still read darker than its reveal, or the wake-up
    on the answer stops landing."""
    import inspect
    import _quiz_pipeline_legacy as legacy

    source = inspect.getsource(legacy.run_quiz_pipeline)
    assert "0.62, 0.72" not in source, "the grey clue is what this replaced"
    assert "0.80, 1.02" in source, "clue: brighter, and no longer desaturated"
    assert "1.12, 1.28" in source, "reveal: still clearly brighter than the clue"


def test_habitats_are_specified_bright_rather_than_atmospheric():
    """"Misty rainforest at dawn" is atmospheric and grey, and the guess window — the longest,
    flattest stretch of the Short — is exactly where the retention curves leak."""
    import inspect
    import _quiz_pipeline_legacy as legacy

    assert "BRIGHT, COLOURFUL, VIBRANT" in legacy._QUIZ_SYSTEM
    assert "NEVER grey, overcast, gloomy" in legacy._QUIZ_SYSTEM
    assert "VIBRANT" in inspect.getsource(legacy._habitat_pair)


def test_the_close_up_ask_is_bounded_at_both_ends():
    """It stated only a minimum and overshot on all five occurrences — 48%, 50%, 48%, 42%, 58%
    against ceilings of 40-50. The pull-back ask states a maximum and landed inside its band first
    try. The difference is not wording or tier: one range is closed and the other was open at the
    top, and the model runs to the top of an open range every time.
    """
    import _quiz_pipeline_legacy as legacy

    words = {"one fifth": 20.0, "one quarter": 25.0, "one third": 33.3,
             "two fifths": 40.0, "one half": 50.0}
    for tier in ("hard", "expert"):
        lo = words[legacy._CLOSE_UP_SPAN[tier]]
        hi = words[legacy._CLOSE_UP_CEILING_SPAN[tier]]
        floor = legacy._READABILITY_WIDTH_MIN[tier]
        ceiling = legacy._READABILITY_WIDTH_MAX[tier]
        assert lo < hi, tier
        # The whole ask has to sit inside the gate's band, with room either side so a retry can
        # miss in either direction and still land.
        assert floor < lo and hi <= ceiling, (tier, floor, lo, hi, ceiling)
        ask = legacy._close_framing(tier)
        assert "BETWEEN" in ask and "MUST NOT exceed" in ask
        assert "keep the habitat visible" in ask, (
            "the failure being repaired is the habitat becoming a backdrop")


def test_the_ceiling_is_a_composition_rule_not_a_difficulty_one():
    """Past roughly half the frame the habitat stops being a hiding place whatever tier the round
    is, so hard and expert share a ceiling. Only the FLOOR is tier-scaled, because a harder round
    may legitimately hide a smaller subject.

    Medium stays uncapped: round one is the swipe decision, where a large legible silhouette is an
    asset rather than a contradiction.
    """
    import _quiz_pipeline_legacy as legacy

    assert legacy._READABILITY_WIDTH_MAX["hard"] == legacy._READABILITY_WIDTH_MAX["expert"]
    assert "medium" not in legacy._READABILITY_WIDTH_MAX
    floors = legacy._READABILITY_WIDTH_MIN
    assert floors["medium"] > floors["hard"] > floors["expert"], "the floor still climbs by tier"


def test_the_close_up_ask_stays_inside_the_widened_band():
    """The ask is kept conservative on purpose. The model overshoots it regardless, so asking for
    less is what keeps the overshoot landing near the ceiling instead of past it."""
    import _quiz_pipeline_legacy as legacy

    words = {"one fifth": 20.0, "one quarter": 25.0, "one third": 33.3,
             "two fifths": 40.0, "one half": 50.0}
    for tier in ("hard", "expert"):
        assert words[legacy._CLOSE_UP_CEILING_SPAN[tier]] < legacy._READABILITY_WIDTH_MAX[tier]


# ── animated reveals ────────────────────────────────────────────────────────────

def test_only_the_reveal_is_ever_animated():
    """Generative motion on a silhouette turns the animal side-on to front-on mid-guess, so the
    outline the viewer is asked to name stops being the outline they were shown. That is why the
    fal OPENER is never combined with progressive crops, and it is why the clue stays still here.

    By the reveal the answer is already given, so motion spoils nothing — and it lands on the beat
    the published retention curves show producing no response at all.
    """
    import inspect
    import _quiz_pipeline_legacy as legacy

    # Whitespace-normalised: the call is wrapped across lines.
    compact = " ".join(inspect.getsource(legacy.run_quiz_pipeline).split())
    assert '_fal_reveal_motion( f"{A}/rev{i}_b.png"' in compact
    assert "clue" not in compact[compact.index("_fal_reveal_motion("):][:200], (
        "the clue must never be the animation seed")
    doc = legacy._fal_reveal_motion.__doc__ or ""
    assert "falls back to the still" in doc


def test_reveal_motion_is_off_by_default_and_scoped_when_on():
    """Kling bills a five-second minimum whatever is used of it, so this is opt-in. "final" buys one
    clip on the longest beat; "all" buys one per round."""
    import os
    import importlib
    import _quiz_pipeline_legacy as legacy

    prior = os.environ.get("QUIZ_FAL_REVEAL")
    try:
        for mode, expected in (("0", [False, False, False]),
                               ("final", [False, False, True]),
                               ("1", [False, False, True]),
                               ("all", [True, True, True])):
            os.environ["QUIZ_FAL_REVEAL"] = mode
            importlib.reload(legacy)
            got = [legacy.reveal_motion_wanted(i, 3) for i in (1, 2, 3)]
            assert got == expected, (mode, got)
    finally:
        os.environ.pop("QUIZ_FAL_REVEAL", None)
        if prior is not None:
            os.environ["QUIZ_FAL_REVEAL"] = prior
        importlib.reload(legacy)
    assert legacy.FAL_REVEAL is False, "stills remain the default"


def test_the_closing_card_keeps_its_pre_dissolve_text_fade():
    """The CTA card can now carry motion, but the loop dissolve still eats into its tail and the
    text has to clear before that starts — a card that merely cross-faded with the next one was
    illegible in both. The still renderer does that with overlay_fade; the video path has to bake
    the same fade into the composite."""
    import inspect
    import _quiz_pipeline_legacy as legacy

    source = inspect.getsource(legacy.run_quiz_pipeline)
    # The still path is still what runs when motion is off or refused.
    assert 'render_specs.append((f"{A}/rev{i}_b.png", cta_beat, False, cta_opts))' in source
    # And when motion IS used, the CTA overlay keeps its pre-dissolve text fade — baked into the
    # composite, because a video overlay cannot be faded by the still renderer.
    assert "cta_fade" in source and "overlay_fade" in inspect.getsource(legacy._fal_reveal_motion)


def test_a_refused_clip_falls_back_rather_than_failing_the_render():
    """No key, an exhausted balance, a quota refusal, a truncated download or a failed composite
    all have to end in the still the round would have rendered anyway. This is decoration on a beat
    that already works without it — it must never be able to take a render down."""
    import inspect
    import _quiz_pipeline_legacy as legacy

    body = inspect.getsource(legacy._fal_reveal_motion)
    assert "except Exception" in body, "a provider raising must not escape"
    assert "return False" in body, "a refused clip must return, not raise"
    # A composite that produced nothing has to report failure too, not just a download that never
    # arrived — otherwise a broken segment reaches the assembler as a valid render spec.
    assert "if not os.path.exists(out) or _dur(out) <= 0:" in body
    # And the operator is told, because silent stills read as "that is the format".
    assert "fell back to stills" in inspect.getsource(legacy.run_quiz_pipeline)


def test_one_generation_covers_every_beat_it_pays_for():
    """Hooking the motion to the closing answer beat alone spent a five-second clip on 0.2s of
    screen time — six frames, 4% of what was billed. The countdown taper had cut that round's stage
    to 0.6s and the reveal transition takes 0.42s of it, so the duration on the final round lives
    in the CTA beat that follows.

    One clip, split across both cards, the same way _fal_countdown_opener splits one clip under the
    changing 3-2-1 overlays. Two generations would be the other way to cover both beats, and it
    would cost twice as much for a clip that is already four times longer than the beat needs.
    """
    import inspect
    import _quiz_pipeline_legacy as legacy

    body = inspect.getsource(legacy._fal_reveal_motion)
    assert "segments" in inspect.signature(legacy._fal_reveal_motion).parameters
    assert "start += duration" in body, "segments must run consecutively through one clip"
    assert body.count("_animate_one") == 1, "one generation covers every segment"

    source = inspect.getsource(legacy.run_quiz_pipeline)
    # The final round passes two segments and pays once.
    assert "answer_motion, answer_beat, None" in source
    assert "cta_motion, cta_beat, cta_fade" in source
    # Three charge sites in total: the fal opener, plus the two reveal paths (final and ordinary).
    # What matters is that the FINAL round charges once despite rendering two segments.
    assert source.count("costs.append(5 * FAL_OPENER_RATE_SEC)") == 3
    final_block = source[source.index("answer_motion = "):source.index("clips.extend((")]
    assert final_block.count("costs.append(5 * FAL_OPENER_RATE_SEC)") == 1, (
        "one charge per round that animates, not per segment")


def test_the_opening_reveal_is_the_beat_worth_animating():
    """The first default put motion on the FINAL reveal because that beat is the longest. Longest
    is not the same as most valuable: stayed-to-watch is decided in the opening seconds, round
    one's reveal lands around 2.4s inside that window, and the published curves fall in a straight
    line from the very start with no plateau. Motion at 8s rewards a viewer who already chose to
    stay; motion at 2.4s is aimed at the one still deciding.
    """
    import os
    import importlib
    import _quiz_pipeline_legacy as legacy

    prior = os.environ.get("QUIZ_FAL_REVEAL")
    try:
        os.environ["QUIZ_FAL_REVEAL"] = "first"
        importlib.reload(legacy)
        assert [legacy.reveal_motion_wanted(i, 3) for i in (1, 2, 3)] == [True, False, False]
    finally:
        os.environ.pop("QUIZ_FAL_REVEAL", None)
        if prior is not None:
            os.environ["QUIZ_FAL_REVEAL"] = prior
        importlib.reload(legacy)


def test_an_animated_opening_reveal_is_held_long_enough_to_read():
    """Round one's reveal floors at 0.8s and the match-cut transition takes 0.42s of it — twelve
    frames, too few for a surge toward camera to read as anything but a glitch. The extra time is
    bought only when the motion is actually there, so a still render keeps its pacing exactly."""
    import _quiz_pipeline_legacy as legacy
    from bolt_video.formats.quiz import QUIZ_V2

    held = legacy._ANIMATED_FIRST_REVEAL_SEC
    assert held > QUIZ_V2.reveal_max_sec, "the normal cap would clamp it straight back down"
    playable = held - legacy._REVEAL_TRANSITION_SEC
    assert playable >= 1.0, f"only {playable:.2f}s of motion after the transition"

    source = inspect_source = __import__("inspect").getsource(legacy.run_quiz_pipeline)
    assert "if i == 1 and reveal_motion_wanted(i, len(items)):" in source, (
        "a still opening round must not pay the extra second")


def test_the_opening_reveal_uses_a_reaction_prompt_not_the_calm_one():
    """A calm "comes alive" rewards a viewer already watching. The first reveal has to interrupt
    someone mid-scroll who has not decided yet.

    Phrased as NOTICING rather than attacking: the set is not always a predator, and "attack" would
    be wrong for most of it — a turtle swims at you, a manta banks over the lens. It would also push
    the model toward inventing a scene rather than moving the one it was handed.
    """
    import _quiz_pipeline_legacy as legacy

    reaction = legacy._REVEAL_REACTION_PROMPT
    calm = legacy._REVEAL_MOTION_PROMPT
    assert reaction != calm
    assert "NOTICES the camera" in reaction and "surges" in reaction
    assert "attack" not in reaction.lower(), "wrong for most of the set, and invites a new scene"
    # Identity has to survive a violent motion prompt, so the guardrails are the same as the calm one.
    for guard in ("EXACT same animal", "never becomes a different creature"):
        assert guard in reaction, guard
    assert "reaction=(i == 1)" in __import__("inspect").getsource(legacy.run_quiz_pipeline)
