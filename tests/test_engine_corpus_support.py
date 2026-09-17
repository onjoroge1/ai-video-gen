"""Corpus support for a story engine is a fact about coverage. Make it visible, not a gate.

`removed_keystone` was selected on all four live attempts of the cane-toad topic and has zero
references in `fixtures/causal/`, so `adherence_for_engine` silently drops it to loose and the
reference blueprint is withheld entirely. The engine's own declared sequence IS still shown to the
labeller through `story_engines.catalogue()`, so the model is not judged against a rule it never
saw — what it loses is every measured fact about how a story of this shape is actually told.
"""
import explainer_pipeline as ep


def test_engine_selection_states_its_corpus_support():
    """An engine at zero references is silently downgraded to loose adherence. Say so.

    `removed_keystone` was selected on all four live attempts of the cane-toad topic and has no
    reference in `fixtures/causal/` — `story_engines` names one ("macquarie-island cat
    eradication") that is not there. The downgrade is real and invisible; this makes it a line in
    the run log rather than something you find by reading two modules.

    Deliberately NOT a gate. The corpus's authority split says measured data may gate a run and
    judged data may not, and "how many references exist" is neither — it is a fact about coverage.
    """
    import reference_corpus

    note = ep._engine_support_note("removed_keystone")
    assert reference_corpus.by_engine("removed_keystone") == [], "fixture drifted"
    assert "0 corpus references" in note and "loose adherence" in note
    assert "unvalidated against any real video" in note

    supported = ep._engine_support_note("backfiring_solution")
    assert "2 corpus references" in supported and "balanced adherence" in supported
    assert "unvalidated" not in supported

    # It must never be the thing that breaks a run.
    assert ep._engine_support_note("not_an_engine") == "" or isinstance(
        ep._engine_support_note("not_an_engine"), str)
