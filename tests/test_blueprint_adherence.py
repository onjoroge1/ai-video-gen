"""What the corpus actually hands the generator, and the regression that made it hand over less.

For a long time no generated script was ever shown how one of these stories is told. `story_pattern`
— the field describing the beat sequence a reference walks — is gated to `balanced` and above, and
`DEFAULT_ADHERENCE` is `loose`. The model got `hook_type` and voice notes, and nothing about the
shape of the telling.

Then a 64-second reference was added to the corpus. Because `_retrieve_blueprint` picks the nearest
reference by runtime, it displaced `cobra_effect` for every 60-90s request — and it had been filled
in with `story_pattern` and `cadence` but not `narrator_tone` or `humour_and_interrupts`, so at
`loose` it supplied ONE field where `cobra_effect` supplied three. Adding a reference made the
prompt thinner. Nothing caught it, because nothing compared references to each other.
"""
import pytest

import reference_corpus as rc
import story_engines as se


def _refs():
    return {r.name: r for r in rc.load()}


def _fields(reference, level):
    return set((rc.blueprint(reference, level).get("format_rules") or {}).keys())


# --- the gate itself -----------------------------------------------------------------------------

def test_story_pattern_reaches_the_generator_for_a_well_covered_engine():
    """The single most useful field in the corpus, and it was never sent."""
    reference = _refs()["cobra_effect"]
    level = rc.adherence_for_engine(reference.engine_id)
    assert "story_pattern" in _fields(reference, level)


def test_adherence_is_raised_only_where_the_corpus_supports_it():
    """DEFAULT_ADHERENCE's own note sets the condition: widen when the corpus supports it.

    That condition is per-engine. An engine with one reference or none keeps the protection the note
    was written for — "balanced currently means imitate this single video".
    """
    for engine_id in se.ENGINES:
        count = len(rc.by_engine(engine_id))
        expected = "balanced" if count >= rc.MIN_REFERENCES_FOR_BALANCED else rc.DEFAULT_ADHERENCE
        assert rc.adherence_for_engine(engine_id) == expected, engine_id


def test_a_thin_engine_is_not_widened():
    thin = [e for e in se.ENGINES if len(rc.by_engine(e)) < rc.MIN_REFERENCES_FOR_BALANCED]
    assert thin, "this test is meaningless once every engine is well covered — delete it then"
    for engine_id in thin:
        assert rc.adherence_for_engine(engine_id) == "loose"


def test_the_global_default_is_unchanged():
    """Widening is per-engine. Flipping the default would widen the thin engines too."""
    assert rc.DEFAULT_ADHERENCE == "loose"


# --- the regression guard ------------------------------------------------------------------------

@pytest.mark.parametrize("level", ["loose", "balanced"])
def test_no_reference_is_thinner_than_the_one_it_can_displace(level):
    """Adding a reference must not reduce what the generator receives.

    Retrieval picks by nearest runtime, so any reference can displace any other within its engine.
    A reference that supplies fewer fields than its siblings is therefore a silent downgrade for
    whatever runtime range it wins. This is the check that was missing.
    """
    by_engine: dict[str, list] = {}
    for reference in rc.load():
        by_engine.setdefault(reference.engine_id, []).append(reference)

    for engine_id, references in by_engine.items():
        if len(references) < 2:
            continue
        best = max(len(_fields(r, level)) for r in references)
        for reference in references:
            supplied = _fields(reference, level)
            assert len(supplied) == best, (
                f"{reference.name} supplies {len(supplied)} fields at {level} where a sibling "
                f"supplies {best}; retrieval can pick it by runtime and quietly hand the generator "
                f"less. Missing: {sorted(set().union(*(_fields(r, level) for r in references)) - supplied)}"
            )


def test_no_field_is_silently_withheld_for_topic_leak():
    """A field dropped for naming a subject is a defect in the capture, not a filter success.

    blueprint() reports these rather than hiding them, and the fix belongs in the fixture text. One
    observation was withheld because it quoted the reference's own lines and the capitalised
    sentence-starts read as subject tokens.
    """
    for reference in rc.load():
        level = rc.adherence_for_engine(reference.engine_id)
        withheld = rc.blueprint(reference, level).get("omitted_for_topic_leak") or {}
        assert not withheld, (
            f"{reference.name} withholds {sorted(withheld)} at {level}; reword the fixture so the "
            "observation carries no subject tokens")
