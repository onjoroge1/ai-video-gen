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
    assert clamp_quiz_items(6) == 4
    assert clamp_quiz_items(4) == 4, "four rounds must survive the clamp, not be capped to three"
    assert QUIZ_V2.estimated_duration(4, reveal_sec=1.0) == 12.0
    assert QUIZ_V2.estimated_duration(6, reveal_sec=1.2, final_reveal_sec=2.4) == 13.2


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
    assert lines == ["Three animals hiding.",
                     "Round 2. Harder.",
                     "Last one. Nobody gets it."]
    assert all("what is it" not in line.lower() for line in lines)


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
            assert len(line) / 15.0 <= QUIZ_V2.guess_window_sec, (total, index, line)


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
    assert "CDN * 1000" in source and "guess_window_sec}" in source


def test_bolt_reacts_through_his_face_not_a_pose(tmp_path):
    """The badge crops to head and shoulders — his arms are outside it.

    A waving pose would be cropped away entirely, so the visor is the only surface a viewer can
    read a reaction on. Each mood must therefore actually change those pixels, and idle must
    leave the source art alone.
    """
    import numpy as np
    from PIL import Image

    import _quiz_pipeline_legacy as legacy

    def badge(mood):
        canvas = Image.new("RGBA", (190, 190), (0, 0, 0, 0))
        legacy._paste_bolt_badge(canvas, (0, 0), 190, mood=mood)
        return np.asarray(canvas.convert("RGB")).astype(float)

    idle = badge("idle")
    eyes = (slice(int(190 * 0.42), int(190 * 0.54)), slice(int(190 * 0.32), int(190 * 0.64)))
    for mood in ("focus", "alert", "happy"):
        changed = np.abs(badge(mood)[eyes] - idle[eyes]).mean()
        assert changed > 1.0, f"{mood} must be visible on the visor, changed {changed:.2f}"

    assert np.abs(badge("idle") - idle).mean() == 0, "idle must not repaint the source art"


def test_every_difficulty_maps_to_a_mood():
    # The ladder drives the face; a difficulty with no mood would silently fall back to one
    # expression and the reaction would quietly stop tracking the rounds.
    import _quiz_pipeline_legacy as legacy

    for difficulty in ("medium", "hard", "expert"):
        assert difficulty in legacy._BOLT_MOODS


# ── A/B variants ────────────────────────────────────────────────────────────────
# Rendering two quizzes and comparing them measures nothing: the animals, habitats and images all
# differ alongside the layer under test. A variant re-cuts ONE layer off assets already generated,
# over the same audio timeline, so a difference between the pair can only be that layer.

def _slot(start, end, total, cta_beat=0.0, is_final=False, rnd=1, difficulty="medium"):
    return {"start": start, "end": end, "round": rnd, "clue": "c.png", "reveal": "r.png",
            "answer": "OKAPI", "mood": "happy", "difficulty": difficulty, "is_final": is_final,
            "total": total, "dissolve": 0.42, "cta_overlay": "cta.png",
            "cta_opts": {"overlay": "cta.png"} if is_final else None, "cta_beat": cta_beat}


def test_the_control_variant_is_the_specs_untouched():
    import _quiz_pipeline_legacy as legacy

    specs = [("a.png", 0.6, False, {}), ("tr.mp4", 0.42, True), ("r.png", 0.68, False, {})]
    out, complete = legacy.apply_variant(specs, [_slot(1, 3, 1.10)], "a", "/tmp")

    assert out == specs and complete, "'a' is the control and must not be re-cut"


def test_a_variant_that_would_move_the_timeline_is_refused(tmp_path, monkeypatch):
    """One audio track serves every variant, so a re-cut that changes length desynchronises it.

    Refusing beats shipping: a pair of different lengths is not a variant pair, it is two videos,
    and the only thing it would establish is that the comparison was invalid.
    """
    import _quiz_pipeline_legacy as legacy

    monkeypatch.setattr(legacy, "performer_specs",
                        lambda slot, out_dir: [("x.mp4", slot["total"] + 0.5, True)])
    specs = [("a.png", 0.6, False, {}), ("tr.mp4", 0.42, True), ("r.png", 0.68, False, {})]
    out, complete = legacy.apply_variant(specs, [_slot(1, 3, 1.10)], "b", str(tmp_path),
                                         log=lambda _m: None)

    assert out == specs, "a length-changing re-cut must be dropped, not spliced in"
    assert not complete


def test_a_missing_pose_library_leaves_the_round_alone(tmp_path, monkeypatch):
    # The cutouts are committed assets. On a checkout without them the control must still render
    # rather than the run failing, so the variant simply does not happen.
    import _quiz_pipeline_legacy as legacy

    monkeypatch.setattr(legacy, "_mascot_pose", lambda name: None)
    assert legacy.performer_specs(_slot(1, 3, 1.10), str(tmp_path)) is None


def test_every_difficulty_has_a_reveal_pose():
    import _quiz_pipeline_legacy as legacy

    for difficulty in ("medium", "hard", "expert"):
        assert difficulty in legacy._MASCOT_REVEAL_POSES


def test_the_pose_library_is_cutouts_not_squares():
    """A pose that failed to chroma-key is a magenta rectangle pasted over the habitat.

    It would look catastrophic and nothing else in the pipeline checks for it, so the shape of the
    committed asset is the guard.
    """
    import os

    import numpy as np
    from PIL import Image

    import _quiz_pipeline_legacy as legacy

    for name in set(legacy._MASCOT_REVEAL_POSES.values()) | {"wave"}:
        path = os.path.join(legacy._MASCOT_DIR, f"{name}.png")
        if not os.path.exists(path):
            continue
        alpha = np.asarray(Image.open(path).convert("RGBA"))[..., 3]
        coverage = (alpha > 10).mean()
        assert coverage < 0.95, f"{name} is not keyed — {coverage:.0%} opaque"
        assert coverage > 0.05, f"{name} keyed away almost everything — {coverage:.0%} opaque"


def test_the_mascot_stays_out_of_the_shorts_ui_band():
    """Anchoring him to the frame bottom put him where the player draws its own furniture.

    The Shorts UI covers roughly the lowest quarter with title and handle; that is exactly why the
    answer card stops at H-475 instead of running to the bottom. A mascot below that line is a
    mascot the viewer never sees, and nothing else in the renderer would have caught it.
    """
    import math

    import _quiz_pipeline_legacy as legacy

    pose = legacy._mascot_pose("celebrate")
    if pose is None:
        return
    height = int(legacy.H * legacy._MASCOT_FRAME_FRACTION)
    lowest = max(int((legacy.H - 650) - height - 20 + math.sin(e * 6.2) * (height * 0.055))
                 for e in (0.2, 0.45, 0.7, 1.0)) + height
    assert lowest <= legacy.H - 475, (
        f"mascot reaches y={lowest}; the safe zone ends at {legacy.H - 475}")


def test_the_mascot_art_is_trimmed_before_it_is_scaled():
    """The cutouts keep the generator's 1024x1536 canvas and the robot is about a quarter of it.

    Scaling the untrimmed canvas to a fraction of the frame yields a character a third of the
    intended size, floating clear of where it was positioned. Both happened.
    """
    import _quiz_pipeline_legacy as legacy

    pose = legacy._mascot_pose("celebrate")
    if pose is None:
        return
    assert pose.size != (1024, 1536), "pose must be cropped to its alpha bounding box"
    alpha_rows = pose.split()[-1].getbbox()
    assert alpha_rows == (0, 0, pose.width, pose.height), "trimmed art must have no empty margin"


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
        "WARM-UP", "TOO EASY?", "NO HINTS", "FINAL BOSS"]
    assert [tier_label(i, 3) for i in range(1, 4)] == ["WARM-UP", "NO HINTS", "FINAL BOSS"]
    assert [tier_label(i, 2) for i in range(1, 3)] == ["WARM-UP", "FINAL BOSS"]


def test_every_card_still_fits_its_box_in_the_display_face():
    """A wider face at a bigger size would silently shrink back via _fit_text_size, or overflow
    the answer card. Both headline and the longest realistic answer are checked at the caps."""
    import _quiz_pipeline_legacy as legacy

    for headline in ("GUESS THE SHADOW!", "GOT ALL 4? · SUBSCRIBE"):
        assert legacy._font(76).getlength(headline) <= legacy.W - 240, headline
    for answer in ("AFRICAN WILD DOG!", "HIPPOPOTAMUS!"):
        assert legacy._font(88).getlength(answer) <= legacy.W - 70 - 130, answer
