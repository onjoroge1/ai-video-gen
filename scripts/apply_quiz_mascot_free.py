from __future__ import annotations

from pathlib import Path


def replace_exact(path: str, old: str, new: str, expected: int = 1) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(
            f"{path}: expected {expected} occurrence(s), found {count}: {old[:160]!r}"
        )
    target.write_text(text.replace(old, new), encoding="utf-8")


replace_exact(
    "_quiz_pipeline_legacy.py",
    "Standalone module; reuses explainer_pipeline for image/TTS gen + the mascot. Best-effort throughout.\n",
    "Standalone module; reuses explainer_pipeline for image/TTS generation. The shipping quiz has no mascot layer.\n",
)
replace_exact(
    "_quiz_pipeline_legacy.py",
    '''    "You are a YouTube Shorts writer for a fun 'What is it?' guessing quiz hosted by Bolt, a cute robot "
    "teacher. Given a CATEGORY, produce a quiz.\\n"
''',
    '''    "You are a YouTube Shorts writer for a fast visual 'What is it?' guessing quiz. Given a "
    "CATEGORY, produce a quiz.\\n"
''',
)
replace_exact(
    "_quiz_pipeline_legacy.py",
    '''def run_quiz_pipeline(category: str, output_dir: str, n_items: int = 3, voice: str = "echo",
                      progress_cb=None, operator_direction: str = "",
                      variants: tuple = ("a", "b"), primary_variant: str = "b") -> dict:
    """Generate + render a full quiz short. Returns {output_path,title,scene_count,...}.

    ``variants`` renders the SAME quiz more than once, changing exactly one presentation layer, so
    an A/B measures that layer and nothing else. "a" is the control and is always produced;
    V2.2 ships the full-body reveal performer ("b") when that re-cut succeeds.
    """
''',
    '''def run_quiz_pipeline(category: str, output_dir: str, n_items: int = 3, voice: str = "echo",
                      progress_cb=None, operator_direction: str = "",
                      variants: tuple = ("a",), primary_variant: str = "a") -> dict:
    """Generate + render a full quiz short. Returns {output_path,title,scene_count,...}.

    The legacy variant arguments remain for caller compatibility, but the product flow is locked
    to mascot-free control A. Reveal energy comes from the same-frame silhouette transformation,
    type-on answer, burst, and camera drift rather than a character overlay.
    """
''',
)
replace_exact(
    "_quiz_pipeline_legacy.py",
    '''    A = output_dir; costs = []
    n_items = clamp_quiz_items(n_items)
    log("stage:Writing quiz...")
''',
    '''    A = output_dir; costs = []
    n_items = clamp_quiz_items(n_items)
    # The current mascot cutouts are visually off-model. Keep the compatibility parameters but
    # fail closed to the clean gameplay render even when an older caller still requests variant B.
    variants = ("a",)
    primary_variant = "a"
    log("stage:Writing quiz...")
''',
)
replace_exact(
    "_quiz_pipeline_legacy.py",
    '''        is_final = i == len(items)
        bolt_mood = _BOLT_MOODS.get(diff, "happy")
        _text_png(f"{A}/r{i}_t.png", top=None, subscribe=False, bolt=True,
                  answer=answer.upper() + "!", bolt_mood=bolt_mood)
''',
    '''        is_final = i == len(items)
        _text_png(f"{A}/r{i}_t.png", top=None, subscribe=False,
                  answer=answer.upper() + "!")
''',
)
replace_exact(
    "_quiz_pipeline_legacy.py",
    '''        has_transition = trans_d > 0.05 and _reveal_clip(
            f"{A}/clue{i}_b.png", f"{A}/rev{i}_b.png", answer, trans_clip, trans_d,
            mood=bolt_mood)
''',
    '''        has_transition = trans_d > 0.05 and _reveal_clip(
            f"{A}/clue{i}_b.png", f"{A}/rev{i}_b.png", answer, trans_clip, trans_d,
            bolt=False)
''',
)
replace_exact(
    "_quiz_pipeline_legacy.py",
    '''            _text_png(f"{A}/r{i}_cta_t.png", subscribe=True,
                      top=f"GOT ALL {len(items)}? · ", top_accent="SUBSCRIBE",
                      bolt=True, answer=answer.upper() + "!", bolt_mood="happy")
''',
    '''            _text_png(f"{A}/r{i}_cta_t.png", subscribe=True,
                      top=f"GOT ALL {len(items)}? · ", top_accent="SUBSCRIBE",
                      answer=answer.upper() + "!")
''',
)
replace_exact(
    "_quiz_pipeline_legacy.py",
    '''            "mood": bolt_mood, "difficulty": diff, "is_final": is_final, "total": dr,
''',
    '''            "mood": "idle", "difficulty": diff, "is_final": is_final, "total": dr,
''',
)
replace_exact(
    "_quiz_pipeline_legacy.py",
    '''            "variants": {k: v for k, v in variant_outputs.items()},
            "primary_variant": selected_variant,
''',
    '''            "variants": {k: v for k, v in variant_outputs.items()},
            "primary_variant": selected_variant, "mascot_overlay": False,
''',
)

replace_exact(
    "tests/test_quiz_contract.py",
    '''def test_v23_defaults_to_three_rounds_and_the_complete_performer_variant():
    import inspect
    import _quiz_pipeline_legacy as legacy

    signature = inspect.signature(legacy.run_quiz_pipeline)
    assert signature.parameters["n_items"].default == 3
    assert signature.parameters["variants"].default == ("a", "b")
    assert signature.parameters["primary_variant"].default == "b"
''',
    '''def test_v23_defaults_to_three_rounds_and_mascot_free_control():
    import inspect
    import _quiz_pipeline_legacy as legacy

    signature = inspect.signature(legacy.run_quiz_pipeline)
    assert signature.parameters["n_items"].default == 3
    assert signature.parameters["variants"].default == ("a",)
    assert signature.parameters["primary_variant"].default == "a"
    source = inspect.getsource(legacy.run_quiz_pipeline)
    assert 'variants = ("a",)' in source
    assert 'primary_variant = "a"' in source
    assert "bolt=True" not in source, "the product quiz path must not draw a mascot badge"
''',
)
replace_exact(
    "tests/test_quiz_contract.py",
    '    for headline in ("GUESS THE SHADOW!", "GOT ALL 4? · SUBSCRIBE"):\n',
    '    for headline in ("GUESS THE SHADOW!", "GOT ALL 3? · SUBSCRIBE"):\n',
)

replace_exact(
    "static/index.html",
    '''        <span class="field-hint">Explainer = a mystery that reveals the answer. Simulation = a "you change every second" escalation. Quiz V2.3 = a three-round frame-zero guessing game with full-body Bolt reveal performances and no intro/outro tail — for Quiz, put a CATEGORY in the Question box (e.g. "animals", "planets", "musical instruments").</span>
''',
    '''        <span class="field-hint">Explainer = a mystery that reveals the answer. Simulation = a "you change every second" escalation. Quiz V2.3 = a three-round frame-zero guessing game with same-frame transformation reveals, no mascot overlay, and no intro/outro tail — for Quiz, put a CATEGORY in the Question box (e.g. "animals", "planets", "musical instruments").</span>
''',
)

replace_exact(
    "docs/QUIZ_RETENTION_V2.md",
    "## V2.2 creative contract\n",
    "## V2.3 creative contract\n",
)
replace_exact(
    "docs/QUIZ_RETENTION_V2.md",
    '''- Bolt performs as a full-body reveal layer, never as an intro or on a guess frame. The renderer also
  preserves control A from the identical generated assets so the performance layer can be compared cleanly.
''',
    '''- The shipping quiz has **no mascot overlay**. Search and reveal frames stay focused on the animal,
  timer, answer typography, and same-frame colour transformation; off-model character art cannot cover clues.
''',
)
replace_exact(
    "docs/QUIZ_RETENTION_V2.md",
    '''The viewer now receives the product before deciding whether to swipe: a large, legible mystery shape and
a moving timer. Bolt remains the channel identity, but does not occupy the scarce first-frame real estate.
The reveal is a color transformation of the same subject, so every 3–4 seconds contains a visual reward.
''',
    '''The viewer now receives the product before deciding whether to swipe: a large, legible mystery shape and
a moving timer. Typography, difficulty labels, sound, and reveal choreography carry the format identity
without a character competing for the frame. The reveal is a color transformation of the same subject,
so every 3–4 seconds contains a visual reward.
''',
)
replace_exact(
    "docs/QUIZ_RETENTION_V2.md",
    '''Do not restore a standalone host intro or post-game subscription card. The CTA belongs inside the final
answer reward; branding stays a small non-blocking reveal mark.
''',
    '''Do not restore a standalone host intro, mascot overlay, or post-game subscription card. The CTA belongs
inside the final answer reward; the animal and the game remain the visual focus.
''',
)

replace_exact(
    "quiz_pipeline.py",
    "Rapid Reveal V2.2 renderer (see ``docs/QUIZ_RETENTION_V2.md``). This facade only fixes\n",
    "Rapid Reveal V2.3 renderer (see ``docs/QUIZ_RETENTION_V2.md``). This facade only fixes\n",
)

print("Applied mascot-free Quiz V2.3 product defaults.")
