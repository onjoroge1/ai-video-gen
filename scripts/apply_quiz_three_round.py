from __future__ import annotations

from pathlib import Path


def replace_exact(path: str, old: str, new: str, expected: int = 1) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(
            f"{path}: expected {expected} occurrence(s), found {count}: {old[:120]!r}"
        )
    target.write_text(text.replace(old, new), encoding="utf-8")


replace_exact(
    "bolt_video/formats/quiz.py",
    '''    version: str = "rapid_reveal_v2_2"
    # Four rounds at a shorter window. A generated take on this format fitted four payoffs into
    # ten seconds against our three, on a ~1.4s guess window, and read as markedly faster for it.
    # Reward frequency is what the viewer feels; 1.8s keeps the clue lookable while adding a
    # fourth payoff, and every line below had to shrink to stay inside it.
    max_items: int = 4
    first_clue_at_sec: float = 0.0
    guess_window_sec: float = 1.8
''',
    '''    version: str = "rapid_reveal_v2_3"
    # Audience data favored the three-payoff arc: removing the fourth round restores a clean
    # warm-up -> hard -> final-boss escalation. The 2.4-second search window is the proven
    # three-round pace and keeps the default Short near eleven seconds without rushing play.
    max_items: int = 3
    first_clue_at_sec: float = 0.0
    guess_window_sec: float = 2.4
''',
)
replace_exact(
    "bolt_video/formats/quiz.py",
    '''    The count was ``"Two" if total == 2 else "Three"``, which was true only while the format was
    capped at three rounds. At four it made the narration contradict the video on the opening
    line — the voice promising three animals over four — and it would have done so silently,
    because nothing downstream compares the spoken count against ``len(items)``.

    Every line then had to shrink for the 1.8s window: at the measured ~16.5 characters/sec the
    old opener needed 2.4s and would have talked over the first answer. "are hiding" lost its
    verb and the final round lost "This fools", which cost the lines nothing they were carrying.
''',
    '''    The count stays data-driven rather than hardcoded, so a future experimental item count cannot
    make the opening narration contradict the number of rounds actually rendered.

    The retained lines fit comfortably inside the restored 2.4-second search window. That gives
    the viewer time to inspect the clue without reintroducing a separate setup card or dead air.
''',
)

replace_exact(
    "app.py",
    '    n_items: int = 4                  # rapid quiz round count; the cap lives in the quiz contract\n',
    '    n_items: int = 3                  # rapid quiz default: three rounds; capped by the quiz contract\n',
)

replace_exact(
    "_quiz_pipeline_legacy.py",
    'Bolt hosts a rapid "What is it?" quiz: the first clue is frame zero, then up to four rounds of\n',
    'Bolt hosts a rapid "What is it?" quiz: the first clue is frame zero, then three rounds of\n',
)
replace_exact(
    "_quiz_pipeline_legacy.py",
    'def generate_quiz(category: str, n_items: int = 4, cost_sink: list | None = None, operator_direction: str = "") -> dict:\n',
    'def generate_quiz(category: str, n_items: int = 3, cost_sink: list | None = None, operator_direction: str = "") -> dict:\n',
)
replace_exact(
    "_quiz_pipeline_legacy.py",
    'def run_quiz_pipeline(category: str, output_dir: str, n_items: int = 4, voice: str = "echo",\n',
    'def run_quiz_pipeline(category: str, output_dir: str, n_items: int = 3, voice: str = "echo",\n',
)
replace_exact(
    "_quiz_pipeline_legacy.py",
    '''    "The title must either OMIT a numeric item count or match the exact requested item count; never "
    "promise three when four items were requested. Return ONLY JSON: {\\"title\\":\\"clickable title, "
''',
    '''    "The title must either OMIT a numeric item count or match the exact requested item count; never "
    "promise a count that differs from the rendered rounds. Return ONLY JSON: {\\"title\\":\\"clickable title, "
''',
)

replace_exact(
    "tests/test_quiz_contract.py",
    '''def test_quiz_v2_caps_rounds_and_stays_replayable():
    assert clamp_quiz_items(6) == 4
    assert clamp_quiz_items(4) == 4, "four rounds must survive the clamp, not be capped to three"
    assert clamp_quiz_items(0) == 4, "a missing count must use the V2.2 default"
    assert QUIZ_V2.estimated_duration(4, reveal_sec=1.0) == 12.0
    assert QUIZ_V2.estimated_duration(6, reveal_sec=1.2, final_reveal_sec=2.4) == 13.2
''',
    '''def test_quiz_v2_caps_rounds_and_stays_replayable():
    assert clamp_quiz_items(6) == 3
    assert clamp_quiz_items(4) == 3, "the default flow is capped at three rounds"
    assert clamp_quiz_items(0) == 3, "a missing count must use the V2.3 three-round default"
    assert QUIZ_V2.estimated_duration(3, reveal_sec=1.0) == 11.0
    assert QUIZ_V2.estimated_duration(6, reveal_sec=1.2, final_reveal_sec=2.4) == 12.0
''',
)

replace_exact(
    "docs/QUIZ_RETENTION_V2.md",
    "# Quiz Short Retention V2.2 — Four-Payoff Rapid Reveal\n",
    "# Quiz Short Retention V2.3 — Three-Round Rapid Reveal\n",
)
replace_exact(
    "docs/QUIZ_RETENTION_V2.md",
    "- Four rounds maximum: **warm-up → too easy? → no hints → final boss**. The opener cannot be trivial.\n",
    "- Three rounds maximum: **warm-up → no hints → final boss**. The opener cannot be trivial.\n",
)
replace_exact(
    "docs/QUIZ_RETENTION_V2.md",
    "- Each 1.8-second guess progressively widens from a tight detail to the complete clue every 0.6 seconds.\n",
    "- Each 2.4-second guess progressively widens from a tight detail to the complete clue every 0.8 seconds.\n",
)
replace_exact(
    "docs/QUIZ_RETENTION_V2.md",
    "- The final answer carries “GOT ALL 4? · SUBSCRIBE” on screen. The spoken line asks for the replay\n",
    "- The final answer carries “GOT ALL 3? · SUBSCRIBE” on screen. The spoken line asks for the replay\n",
)

Path("tests/test_quiz_three_round_default.py").write_text(
    '''from pathlib import Path

from bolt_video.formats.quiz import QUIZ_V2, clamp_quiz_items, tier_label


def test_three_round_default_restores_playable_pacing():
    assert QUIZ_V2.version == "rapid_reveal_v2_3"
    assert QUIZ_V2.max_items == 3
    assert QUIZ_V2.guess_window_sec == 2.4
    assert clamp_quiz_items(4) == 3
    assert QUIZ_V2.estimated_duration(3) == 11.0


def test_three_round_story_keeps_the_difficulty_ladder():
    assert [tier_label(i, 3) for i in range(1, 4)] == [
        "WARM-UP", "NO HINTS", "FINAL BOSS"
    ]


def test_v22_visual_identity_and_generation_quality_are_preserved():
    import _quiz_pipeline_legacy as legacy

    assert Path(legacy.DISPLAY_FONT).name == "LuckiestGuy-Regular.ttf"
    assert "DIFFICULTY IS CONFUSABILITY, NOT OBSCURITY" in legacy._QUIZ_SYSTEM
    assert "Order items MEDIUM -> HARD -> EXPERT" in legacy._QUIZ_SYSTEM
    assert legacy.HABITAT is True
''',
    encoding="utf-8",
)

print("Applied Quiz V2.3 three-round default and pacing changes.")
