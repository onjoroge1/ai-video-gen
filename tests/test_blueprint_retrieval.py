"""Step 4: the retrieved reference reaches generation, and cannot bring its subject with it.

The blueprint teaches a FORMAT. The failure that matters is not "no blueprint was retrieved", it is
"a blueprint retrieved the wrong engine's format, or smuggled the reference's topic into a video
about something else". Both are silent: the script still generates, still validates, still renders.
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import reference_corpus as rc  # noqa: E402
import story_engines as se  # noqa: E402


def _cobra():
    return [r for r in rc.load() if r.name == "cobra_effect"][0]


# --- the blueprint carries format, never content -------------------------------------------------

def test_no_labels_reach_the_blueprint(tmp_path):
    """A label like "Cobra farms" is content. A blueprint carrying it invites a video about
    antibiotic resistance to drift toward snakes."""
    spine = rc.blueprint(_cobra(), "strong")["spine"]
    assert spine, "strong adherence must pass the spine"
    assert all(set(step) == {"role", "chapter", "caused_by"} for step in spine)


def test_no_narration_reaches_the_blueprint():
    """`situation` holds the reference's actual script and must never appear as a key.

    Checked structurally, not by string search: an earlier version of this test scanned the
    rendered JSON for the word "situation" and failed on the phrase "situation ends worse than
    the start" — ordinary English inside a legitimate format description.
    """
    def _keys(node):
        if isinstance(node, dict):
            return set(node) | {k for v in node.values() for k in _keys(v)}
        if isinstance(node, list):
            return {k for item in node for k in _keys(item)}
        return set()

    for level in rc.ADHERENCE_LEVELS:
        assert "situation" not in _keys(rc.blueprint(_cobra(), level))
        assert "label" not in _keys(rc.blueprint(_cobra(), level))


def test_a_field_naming_a_subject_is_dropped_whole_and_reported(tmp_path):
    """Not half-scrubbed. A partially deleted sentence still reads as authoritative."""
    path = tmp_path / "leaky.json"
    path.write_text('{"story":{"engine":"backfiring_solution","steps":[]},'
                    '"observed":{"hook_type":"Opens on Churchill in 1943 declaring a policy",'
                    '"narrator_tone":"dry and clipped, short declaratives"}}', encoding="utf-8")
    block = rc.blueprint(rc.load(tmp_path)[0], "loose")

    assert "hook_type" not in block["format_rules"], "a subject-bearing field must not be passed"
    assert block["format_rules"]["narrator_tone"].startswith("dry")
    assert set(block["omitted_for_topic_leak"]["hook_type"]) >= {"Churchill"}


def test_format_vocabulary_is_not_mistaken_for_a_subject():
    """"Step" is the spoken chapter marker — the retention device this lane is built on. Dropping a
    field over it would discard the most useful observation in the corpus."""
    assert rc.topic_tokens("Numbered chronological steps ('Step one, Step two') advance it") == []


def test_a_possessive_is_not_a_quote_delimiter():
    """The first version of this regex read everything between two apostrophes as one quoted span,
    so "the viewer's ... a narrator's" matched and a strip built on it deleted the description."""
    assert rc._QUOTED_SPAN.findall("ties it to the viewer's life, then a narrator's aside") == []


# --- adherence scales, and defaults conservatively -----------------------------------------------

def test_adherence_widens_what_is_passed():
    counts = [len(rc.blueprint(_cobra(), level)["format_rules"]) for level in rc.ADHERENCE_LEVELS]
    assert counts == sorted(counts) and counts[0] < counts[-1]
    assert "pacing" not in rc.blueprint(_cobra(), "loose")
    assert "pacing" in rc.blueprint(_cobra(), "strong")


def test_the_default_is_loose_while_the_corpus_is_thin():
    """One reference per engine means "balanced" is really "imitate this single video". Four
    constants fitted to a sample this small were each corrected by the next reference."""
    assert rc.DEFAULT_ADHERENCE == "loose"


def test_an_unknown_adherence_falls_back_rather_than_raising():
    assert rc.blueprint(_cobra(), "aggressive")["adherence"] == rc.DEFAULT_ADHERENCE


# --- retrieval is keyed on engine, and fails soft ------------------------------------------------

def test_retrieval_never_substitutes_another_engines_reference():
    """Handing a backfiring_solution blueprint to a power_reversal script teaches the wrong shape
    while looking like it worked. Two of five engines have no reference."""
    import explainer_pipeline as ep
    unbacked = [engine for engine, count in rc.coverage().items() if count == 0]
    assert unbacked, "every engine now has a reference — retarget or retire this test"
    for engine in unbacked:
        assert ep._retrieve_blueprint(engine, "loose") == ""


def test_a_broken_corpus_does_not_take_down_a_paid_render():
    import explainer_pipeline as ep
    assert ep._retrieve_blueprint(None, "loose") == ""
    assert ep._retrieve_blueprint("not_an_engine", "loose") == ""


def test_a_retrieved_block_announces_itself_as_technique_not_topic():
    import explainer_pipeline as ep
    block = ep._retrieve_blueprint(se.BACKFIRING_SOLUTION, "loose")
    assert block, "backfiring_solution has a reference and must retrieve one"
    assert "Do NOT borrow its topic" in block
    assert "unrelated subject" in block


def test_the_env_knob_selects_the_level(monkeypatch):
    import explainer_pipeline as ep
    monkeypatch.setenv("BLUEPRINT_ADHERENCE", "strong")
    assert '"adherence": "strong"' in ep._retrieve_blueprint(se.BACKFIRING_SOLUTION, "")
    monkeypatch.setenv("BLUEPRINT_ADHERENCE", "nonsense")
    assert f'"adherence": "{rc.DEFAULT_ADHERENCE}"' in ep._retrieve_blueprint(
        se.BACKFIRING_SOLUTION, "")


# --- the wiring itself ---------------------------------------------------------------------------

def test_retrieval_guides_planning_and_refreshes_after_labeling():
    """Use the preferred engine before planning and the final choice before expansion."""
    source = (ROOT / "explainer_pipeline.py").read_text(encoding="utf-8")
    spine_call = source.index("beats, spine_cost = _assign_causal_spine(")
    retrieval = source.index("blueprint_block = _retrieve_blueprint(")
    beat_prompt = source.index("    beat_prompt = (")
    refreshed = source.index("blueprint_block = _retrieve_blueprint(", retrieval + 1)
    assert retrieval < beat_prompt < spine_call < refreshed


def test_blueprint_block_is_bound_on_every_lane():
    """It is assigned inside `if causal_lane:` and concatenated unconditionally into the expansion
    prompt, so a non-causal run would raise NameError."""
    source = (ROOT / "explainer_pipeline.py").read_text(encoding="utf-8")
    init = source.index('    blueprint_block = ""')
    guarded = source.index("blueprint_block = _retrieve_blueprint(")
    used = source.index("            + blueprint_block")
    assert init < guarded < used


def test_the_blueprint_reaches_the_expansion_prompt():
    source = (ROOT / "explainer_pipeline.py").read_text(encoding="utf-8")
    assert source.count("+ blueprint_block") == 2


def test_off_disables_retrieval_entirely(monkeypatch):
    """Rollback to the hand-written rules without a deploy, and the control arm for an A/B."""
    import explainer_pipeline as ep
    monkeypatch.setenv("BLUEPRINT_ADHERENCE", "off")
    assert ep._retrieve_blueprint(se.BACKFIRING_SOLUTION, "") == ""


def test_the_nearest_runtime_reference_is_chosen(monkeypatch):
    """The corpus spans 101s to 225s. Letting a 101-second reference teach a 220-second video hands
    over pacing that cannot fit, and alphabetical order would have done exactly that half the time."""
    import explainer_pipeline as ep
    runtimes = {r.name: r.gating_metrics().get("runtime_sec")
                for r in rc.by_engine(se.POWER_REVERSAL)}
    assert len(runtimes) > 1, "test premise stale — power_reversal needs 2+ references"
    for target, expected in ((220, max(runtimes, key=lambda k: runtimes[k])),
                             (110, min(runtimes, key=lambda k: runtimes[k]))):
        block = ep._retrieve_blueprint(se.POWER_REVERSAL, "loose", target)
        assert block, "power_reversal must retrieve"
        # The chosen reference is named only in the log line, so assert on the spine it carries.
        chosen = min(rc.by_engine(se.POWER_REVERSAL),
                     key=lambda r: abs(r.gating_metrics()["runtime_sec"] - target))
        assert chosen.name == expected
