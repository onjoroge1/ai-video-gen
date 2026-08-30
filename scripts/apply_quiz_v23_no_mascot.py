from __future__ import annotations

from pathlib import Path


def replace_exact(text: str, old: str, new: str, *, label: str, expected: int = 1) -> str:
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{label}: expected {expected} occurrence(s), found {count}")
    return text.replace(old, new)


def remove_between(text: str, start: str, end: str, *, label: str) -> str:
    start_at = text.find(start)
    if start_at < 0:
        raise SystemExit(f"{label}: start marker not found")
    end_at = text.find(end, start_at)
    if end_at < 0:
        raise SystemExit(f"{label}: end marker not found")
    return text[:start_at] + text[end_at:]


pipeline_path = Path("_quiz_pipeline_legacy.py")
text = pipeline_path.read_text(encoding="utf-8")

text = replace_exact(
    text,
    'Bolt hosts a rapid "What is it?" quiz: the first clue is frame zero, then three rounds of\n',
    'A rapid "What is it?" quiz starts on the first clue and runs through three rounds of\n',
    label="module description",
)
text = replace_exact(
    text,
    "Standalone module; reuses explainer_pipeline for image/TTS gen + the mascot. Best-effort throughout.\n",
    "Standalone module; reuses explainer_pipeline for image and TTS generation. Best-effort throughout.\n",
    label="module dependency description",
)
text = replace_exact(
    text,
    '    "You are a YouTube Shorts writer for a fun \'What is it?\' guessing quiz hosted by Bolt, a cute robot "\n'
    '    "teacher. Given a CATEGORY, produce a quiz.\\n"\n',
    '    "You are a YouTube Shorts writer for a fast, visual \'What is it?\' guessing quiz. Given a "\n'
    '    "CATEGORY, produce a quiz. The rendered quiz is mascot-free: the clue, timer, difficulty label, "\n'
    '    "answer transformation, and loop carry the experience.\\n"\n',
    label="quiz system identity",
)

# Remove the cropped Bolt badge implementation and its difficulty-to-expression map.
text = remove_between(
    text,
    "# Measured off the badge crop, as fractions of its size, so they hold at any badge dimension.\n",
    "def _text_png",
    label="Bolt badge block",
)
text = replace_exact(
    text,
    '''def _text_png(path, top=None, answer=None, score=None, difficulty=None, cd_left=None,
              subscribe=False, round_label=None, bolt=False, answer_size=None,
              bolt_mood="idle", top_accent="", difficulty_label=""):
''',
    '''def _text_png(path, top=None, answer=None, score=None, difficulty=None, cd_left=None,
              subscribe=False, round_label=None, answer_size=None,
              top_accent="", difficulty_label=""):
''',
    label="text overlay signature",
)
text = replace_exact(
    text,
    '''    if answer:
        if bolt:
            _paste_bolt_badge(im, mood=bolt_mood)
        x0 = 285 if bolt else 70
''',
    '''    if answer:
        x0 = 70
''',
    label="answer card layout",
)

# Remove the full-body mascot asset loader and procedural animation, retaining the reveal clip.
text = remove_between(
    text,
    '_MASCOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "mascot", "quiz")\n',
    "def _reveal_clip",
    label="full-body mascot loader",
)
text = replace_exact(
    text,
    '''def _reveal_clip(clue_png, reveal_png, answer, out, duration, dissolve=None, bolt=True,
                 mood="idle", pose_name="", side="right"):
''',
    '''def _reveal_clip(clue_png, reveal_png, answer, out, duration, dissolve=None):
''',
    label="reveal clip signature",
)
text = replace_exact(
    text,
    '    pose = _mascot_pose(pose_name) if pose_name else None\n',
    "",
    label="reveal mascot pose",
)
text = replace_exact(
    text,
    '        full_size = _fit_text_size(label, 88, W - (285 if bolt else 70) - 130)\n',
    '        full_size = _fit_text_size(label, 88, W - 200)\n',
    label="reveal answer width",
)
text = replace_exact(
    text,
    '''                _text_png(card, answer=label[:shown], bolt=bolt, answer_size=full_size,
                          bolt_mood=mood)
''',
    '''                _text_png(card, answer=label[:shown], answer_size=full_size)
''',
    label="reveal answer overlay",
)
text = replace_exact(
    text,
    '            _draw_mascot(base, pose, elapsed, duration, side)\n',
    "",
    label="reveal mascot composite",
)

# Remove the reveal-performer A/B implementation. The public result shape retains control A only.
text = remove_between(
    text,
    "# Which pose greets which reveal. The ladder already escalates on screen; the mascot escalates\n",
    "def _fit",
    label="performer variant block",
)
text = replace_exact(
    text,
    '''def run_quiz_pipeline(category: str, output_dir: str, n_items: int = 3, voice: str = "echo",
                      progress_cb=None, operator_direction: str = "",
                      variants: tuple = ("a", "b"), primary_variant: str = "b") -> dict:
''',
    '''def run_quiz_pipeline(category: str, output_dir: str, n_items: int = 3, voice: str = "echo",
                      progress_cb=None, operator_direction: str = "",
                      variants: tuple = ("a",), primary_variant: str = "a") -> dict:
''',
    label="quiz pipeline defaults",
)
text = replace_exact(
    text,
    '''    ``variants`` renders the SAME quiz more than once, changing exactly one presentation layer, so
    an A/B measures that layer and nothing else. "a" is the control and is always produced;
    V2.2 ships the full-body reveal performer ("b") when that re-cut succeeds.
''',
    '''    ``variants`` and ``primary_variant`` remain accepted for compatibility with older callers, but
    Quiz V2.3 deliberately renders one mascot-free presentation. The visual reward is the clue turning
    into the answer, with typography and the difficulty ladder providing the format identity.
''',
    label="quiz pipeline variant documentation",
)
text = replace_exact(
    text,
    '    timing_warnings = []; loop_warnings = []; opening_frame = None; reveal_slots = []\n',
    '    timing_warnings = []; loop_warnings = []; opening_frame = None\n',
    label="reveal slot state",
)
text = replace_exact(
    text,
    '''        bolt_mood = _BOLT_MOODS.get(diff, "happy")
        _text_png(f"{A}/r{i}_t.png", top=None, subscribe=False, bolt=True,
                  answer=answer.upper() + "!", bolt_mood=bolt_mood)
''',
    '''        _text_png(f"{A}/r{i}_t.png", top=None, subscribe=False,
                  answer=answer.upper() + "!")
''',
    label="standard answer card mascot",
)
text = replace_exact(
    text,
    '''        has_transition = trans_d > 0.05 and _reveal_clip(
            f"{A}/clue{i}_b.png", f"{A}/rev{i}_b.png", answer, trans_clip, trans_d,
            mood=bolt_mood)
''',
    '''        has_transition = trans_d > 0.05 and _reveal_clip(
            f"{A}/clue{i}_b.png", f"{A}/rev{i}_b.png", answer, trans_clip, trans_d)
''',
    label="transition mascot",
)
text = replace_exact(
    text,
    '''            _text_png(f"{A}/r{i}_cta_t.png", subscribe=True,
                      top=f"GOT ALL {len(items)}? · ", top_accent="SUBSCRIBE",
                      bolt=True, answer=answer.upper() + "!", bolt_mood="happy")
''',
    '''            _text_png(f"{A}/r{i}_cta_t.png", subscribe=True,
                      top=f"GOT ALL {len(items)}? · ", top_accent="SUBSCRIBE",
                      answer=answer.upper() + "!")
''',
    label="final CTA mascot",
)
text = remove_between(
    text,
    "        # Everything a variant needs to re-cut THIS reveal, captured while the numbers are in\n",
    '        audio.append((f"{A}/n_r{i}.mp3", t, "narr"))',
    label="reveal slot capture",
)
text = remove_between(
    text,
    "    # Extra variants re-cut ONE layer off the assets already paid for and reuse this exact audio\n",
    "    # Ready-to-paste YouTube description + tags (best-effort). Runs BEFORE the cost sum so its cost is\n",
    label="variant render loop",
)
variant_anchor = "    # Ready-to-paste YouTube description + tags (best-effort). Runs BEFORE the cost sum so its cost is\n"
text = replace_exact(
    text,
    variant_anchor,
    '''    # Preserve the historical variants/primary_variant result shape without compositing a mascot.
    # Any legacy caller requesting performer B receives the same single V2.3 output rather than a
    # visually different or partially animated render.
    variant_outputs = {"a": out_mp4}
    selected_variant = "a"
    primary_output = out_mp4

''' + variant_anchor,
    label="mascot-free variant result",
)

for forbidden in (
    "_paste_bolt_badge", "_draw_bolt_eyes", "_BOLT_MOODS", "_MASCOT_DIR",
    "_mascot_pose", "_draw_mascot", "_MASCOT_REVEAL_POSES", "performer_specs",
    "apply_variant", "bolt=True", "bolt_mood=",
):
    if forbidden in text:
        raise SystemExit(f"mascot removal incomplete: {forbidden} remains")

pipeline_path.write_text(text, encoding="utf-8")

# Keep the compatibility facade's version description accurate.
facade_path = Path("quiz_pipeline.py")
facade = facade_path.read_text(encoding="utf-8")
facade = replace_exact(
    facade,
    "Rapid Reveal V2.2 renderer (see ``docs/QUIZ_RETENTION_V2.md``).",
    "Rapid Reveal V2.3 mascot-free renderer (see ``docs/QUIZ_RETENTION_V2.md``).",
    label="quiz facade version",
)
facade_path.write_text(facade, encoding="utf-8")

# Update the operator-facing description without changing the retained font, difficulty, or timing controls.
ui_path = Path("static/index.html")
ui = ui_path.read_text(encoding="utf-8")
ui = replace_exact(
    ui,
    "Quiz V2.3 = a three-round frame-zero guessing game with full-body Bolt reveal performances and no intro/outro tail",
    "Quiz V2.3 = a three-round frame-zero guessing game with clean mascot-free answer reveals and no intro/outro tail",
    label="quiz UI description",
)
ui_path.write_text(ui, encoding="utf-8")

# Document the deliberate choice: the mascot is not merely hidden on frame zero; it is absent from every quiz frame.
docs_path = Path("docs/QUIZ_RETENTION_V2.md")
docs = docs_path.read_text(encoding="utf-8")
docs = replace_exact(docs, "## V2.2 creative contract\n", "## V2.3 creative contract\n",
                     label="creative contract heading")
docs = replace_exact(
    docs,
    "- Bolt performs as a full-body reveal layer, never as an intro or on a guess frame. The renderer also\n"
    "  preserves control A from the identical generated assets so the performance layer can be compared cleanly.\n",
    "- No mascot is composited on clue, reveal, answer, CTA, or loop frames. The animal transformation,\n"
    "  display typography, difficulty ladder, timer, and sound design carry the complete quiz experience.\n",
    label="mascot contract",
)
docs = replace_exact(
    docs,
    "a moving timer. Bolt remains the channel identity, but does not occupy the scarce first-frame real estate.\n"
    "The reveal is a color transformation of the same subject, so every 3–4 seconds contains a visual reward.\n",
    "a moving timer. The retained display font and difficulty system provide a consistent channel identity\n"
    "without placing a character over the habitat. The reveal is a color transformation of the same subject,\n"
    "so every 3–4 seconds contains a visual reward.\n",
    label="creative rationale",
)
docs = replace_exact(
    docs,
    "answer reward; branding stays a small non-blocking reveal mark.\n",
    "answer reward; branding stays in the typography and repeatable game structure.\n",
    label="branding guidance",
)
docs_path.write_text(docs, encoding="utf-8")

# Replace performer-specific tests with a fail-closed mascot-free contract.
tests_path = Path("tests/test_quiz_contract.py")
tests = tests_path.read_text(encoding="utf-8")
tests = remove_between(
    tests,
    "def test_bolt_reacts_through_his_face_not_a_pose(tmp_path):\n",
    "def test_a_clip_replacing_a_drifting_still_carries_its_own_move():\n",
    label="performer tests",
)
no_mascot_tests = '''def test_quiz_render_path_is_mascot_free():
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


'''
tests = tests.replace(
    "def test_a_clip_replacing_a_drifting_still_carries_its_own_move():\n",
    no_mascot_tests + "def test_a_clip_replacing_a_drifting_still_carries_its_own_move():\n",
    1,
)
tests = replace_exact(
    tests,
    "def test_v23_defaults_to_three_rounds_and_the_complete_performer_variant():\n",
    "def test_v23_defaults_to_three_rounds_and_mascot_free_reveals():\n",
    label="default test name",
)
tests = replace_exact(
    tests,
    '    assert signature.parameters["variants"].default == ("a", "b")\n'
    '    assert signature.parameters["primary_variant"].default == "b"\n',
    '    assert signature.parameters["variants"].default == ("a",)\n'
    '    assert signature.parameters["primary_variant"].default == "a"\n',
    label="default variant assertions",
)
tests_path.write_text(tests, encoding="utf-8")

three_path = Path("tests/test_quiz_three_round_default.py")
three = three_path.read_text(encoding="utf-8")
three = replace_exact(
    three,
    "def test_v22_visual_identity_and_generation_quality_are_preserved():\n",
    "def test_v23_visual_identity_and_generation_quality_are_preserved():\n",
    label="three-round test name",
)
three_path.write_text(three, encoding="utf-8")

print("Applied Quiz V2.3 three-round mascot-free renderer changes.")
