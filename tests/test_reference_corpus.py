"""The corpus loader, and the authority split it enforces.

Every constant derived from two references was corrected by the third — four times, each found by
a failing run rather than by reading code. The corpus exists so that sample size is countable
instead of invisible, and so the judged fields can never quietly become gates.
"""
import json

import pytest

import reference_corpus as rc
import story_engines as se


def _write(directory, name, *, engine, measured=None, observed=None, generated=False):
    payload = {
        "format": "causal_story_v1",
        "measured": measured or {},
        "observed": observed or {},
        "story": {
            "title": name, "runtime_sec": 200.0, "engine": engine,
            "hook": {"line": "A hook."},
            "steps": [{"step_id": "a", "role": "setup", "label": "L", "chapter": 1,
                       "situation": "x", "caused_by": ""}],
        },
        "expect": {"pass": True},
    }
    prefix = "generated_" if generated else ""
    (directory / f"{prefix}{name}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_generated_output_never_teaches_the_corpus(tmp_path):
    """Our own renders sit beside the references for inspection. Training on them would launder
    our mistakes into the spec that is supposed to catch them."""
    _write(tmp_path, "real", engine=se.BACKFIRING_SOLUTION)
    _write(tmp_path, "ours", engine=se.BACKFIRING_SOLUTION, generated=True)
    assert [r.name for r in rc.load(tmp_path)] == ["real"]


def test_gating_metrics_cannot_return_a_judged_field(tmp_path):
    """The split is structural. A judged field reaching a gate is the failure mode this session
    hit three times — an ending-first binding rule and two hinge trims, all of which damaged
    scripts while reporting success."""
    _write(tmp_path, "r", engine=se.BACKFIRING_SOLUTION,
           measured={"mean_hold_sec": 3.38}, observed={"narrator_tone": "dry"})
    reference = rc.load(tmp_path)[0]

    assert reference.gating_metrics() == {"mean_hold_sec": 3.38}
    assert "narrator_tone" not in reference.gating_metrics()
    assert reference.creative_context()["observed"]["narrator_tone"] == "dry"


def test_creative_context_carries_structure_not_narration(tmp_path):
    """The blueprint teaches the format; it must not license reproducing the reference's words."""
    _write(tmp_path, "r", engine=se.BACKFIRING_SOLUTION)
    context = rc.load(tmp_path)[0].creative_context()

    beat = context["spine"][0]
    assert set(beat) == {"role", "label", "chapter", "caused_by"}
    assert "situation" not in beat, "narration text must not travel in the blueprint"


def test_an_operator_written_reference_reports_having_no_measurements(tmp_path):
    """hippo_weed was written, not transcribed. Treating absent numbers as zeros would drag every
    derived band toward nothing, so callers must be able to check."""
    _write(tmp_path, "written", engine=se.ALMOST_HAPPENED_PLAN, measured=None)
    _write(tmp_path, "filmed", engine=se.BACKFIRING_SOLUTION, measured={"mean_hold_sec": 2.4})
    by_name = {r.name: r for r in rc.load(tmp_path)}

    assert by_name["written"].has_measurements is False
    assert by_name["filmed"].has_measurements is True


def test_retrieval_is_keyed_on_engine_not_topic(tmp_path):
    """Cobra and famine share no subject and the same structure; a topic embedding would rank the
    most relevant pair in the corpus as the least."""
    _write(tmp_path, "cobra", engine=se.BACKFIRING_SOLUTION)
    _write(tmp_path, "famine", engine=se.ACCUMULATING_INDICTMENT)
    assert [r.name for r in rc.by_engine(se.BACKFIRING_SOLUTION, tmp_path)] == ["cobra"]
    assert [r.name for r in rc.by_engine(se.ACCUMULATING_INDICTMENT, tmp_path)] == ["famine"]


def test_coverage_exposes_engines_no_reference_has_ever_checked():
    """Two engine sequences were written from imagination and both were wrong. Coverage is how
    that stays visible instead of being rediscovered by a failed render."""
    counts = rc.coverage()
    assert set(counts) == set(se.ENGINES)
    assert counts[se.BACKFIRING_SOLUTION] >= 1
    assert counts[se.ACCUMULATING_INDICTMENT] >= 1
    assert counts[se.ALMOST_HAPPENED_PLAN] >= 1


def test_the_real_corpus_loads_and_every_reference_declares_an_engine():
    references = rc.load()
    assert len(references) >= 3
    for reference in references:
        assert reference.engine_id in se.ENGINES
        assert reference.story.get("engine"), f"{reference.name} has no declared engine"
