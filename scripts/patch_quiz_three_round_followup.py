from __future__ import annotations

from pathlib import Path


def replace_exact(path: str, old: str, new: str, expected: int = 1) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(
            f"{path}: expected {expected} occurrence(s), found {count}: {old[:140]!r}"
        )
    target.write_text(text.replace(old, new), encoding="utf-8")


replace_exact(
    "tests/test_quiz_contract.py",
    '''def test_generated_title_count_is_repaired_to_the_actual_round_count():
    import _quiz_pipeline_legacy as legacy

    assert legacy.normalize_quiz_title(
        "Can You Name All 3 Animals?", 4, "animals") == "Can You Name All 4 Animals?"
    assert legacy.normalize_quiz_title(
        "Can You Name All Three Animals?", 4, "animals") == "Can You Name All Four Animals?"
    assert legacy.normalize_quiz_title(
        "Can You Name 3 Animals?", 4, "animals") == "Can You Name 4 Animals?"
    assert legacy.normalize_quiz_title(
        "Can You Name Them?", 4, "animals") == "Can You Name Them?"
''',
    '''def test_generated_title_count_is_repaired_to_the_actual_round_count():
    import _quiz_pipeline_legacy as legacy

    assert legacy.normalize_quiz_title(
        "Can You Name All 4 Animals?", 4, "animals") == "Can You Name All 3 Animals?"
    assert legacy.normalize_quiz_title(
        "Can You Name All Four Animals?", 4, "animals") == "Can You Name All Three Animals?"
    assert legacy.normalize_quiz_title(
        "Can You Name 4 Animals?", 4, "animals") == "Can You Name 3 Animals?"
    assert legacy.normalize_quiz_title(
        "Can You Name Them?", 4, "animals") == "Can You Name Them?"
''',
)

replace_exact(
    "tests/test_quiz_contract.py",
    '''def test_v22_defaults_to_four_rounds_and_the_complete_performer_variant():
    import inspect
    import _quiz_pipeline_legacy as legacy

    signature = inspect.signature(legacy.run_quiz_pipeline)
    assert signature.parameters["n_items"].default == 4
    assert signature.parameters["variants"].default == ("a", "b")
    assert signature.parameters["primary_variant"].default == "b"


def test_web_ui_and_server_agree_on_v22_round_count():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    html = (root / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="expl-quiz-items"' in html
    assert 'max="4"' in html and 'value="4"' in html
    assert "V2.1 format" not in html
    assert "|| 4" in html
''',
    '''def test_v23_defaults_to_three_rounds_and_the_complete_performer_variant():
    import inspect
    import _quiz_pipeline_legacy as legacy

    signature = inspect.signature(legacy.run_quiz_pipeline)
    assert signature.parameters["n_items"].default == 3
    assert signature.parameters["variants"].default == ("a", "b")
    assert signature.parameters["primary_variant"].default == "b"


def test_web_ui_and_server_agree_on_v23_round_count():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    html = (root / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="expl-quiz-items"' in html
    assert 'max="3"' in html and 'value="3"' in html
    assert "Quiz V2.2 = a four-round" not in html
    assert "|| 3" in html
''',
)

replace_exact(
    "static/index.html",
    '''        <span class="field-hint">Explainer = a mystery that reveals the answer. Simulation = a "you change every second" escalation. Quiz V2.2 = a four-round frame-zero guessing game with full-body Bolt reveal performances and no intro/outro tail — for Quiz, put a CATEGORY in the Question box (e.g. "animals", "planets", "musical instruments").</span>
''',
    '''        <span class="field-hint">Explainer = a mystery that reveals the answer. Simulation = a "you change every second" escalation. Quiz V2.3 = a three-round frame-zero guessing game with full-body Bolt reveal performances and no intro/outro tail — for Quiz, put a CATEGORY in the Question box (e.g. "animals", "planets", "musical instruments").</span>
''',
)
replace_exact(
    "static/index.html",
    '''          <input type="number" id="expl-quiz-items" class="input-field" min="2" max="4" step="1" value="4" />
          <span class="field-hint">How many items to guess (2–4). Four is Rapid Reveal V2.2; the same generated assets also preserve control A for a clean reveal-performance comparison.</span>
''',
    '''          <input type="number" id="expl-quiz-items" class="input-field" min="2" max="3" step="1" value="3" />
          <span class="field-hint">How many items to guess (2–3). Three is Rapid Reveal V2.3; the same generated assets still preserve control A for a clean reveal-performance comparison.</span>
''',
)
replace_exact(
    "static/index.html",
    "      n_items:        parseInt(document.getElementById('expl-quiz-items').value) || 4,\n",
    "      n_items:        parseInt(document.getElementById('expl-quiz-items').value) || 3,\n",
)

print("Aligned stale quiz tests and web defaults with Quiz V2.3.")
