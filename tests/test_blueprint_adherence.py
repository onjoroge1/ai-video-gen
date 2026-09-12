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


def test_voice_is_measured_from_the_transcript_not_hand_labelled():
    """A field nobody fills never reaches the generator, which is what happened to story_pattern.

    Both were found by comparing a generated script against the two references that perform best:
    the corpus speaks in the present and hits in five words, ours reported in the past at nearly
    twice the length, and the generator had never been told either property existed.
    """
    import reference_corpus as rc

    haiti = ("In 1791, Haiti is called Saint-Domingue. It belongs to France. They defeat the "
             "French. They defeat the British. Haiti has no navy. Haiti has no allies. It pays. "
             "It pays for 122 years.")
    ours = ("Cats were eradicated on Macquarie Island to save the seabirds, and afterwards the "
            "rabbits stripped the plants bare across the slopes and the hillsides beyond them.")

    corpus, generated = rc.measure_voice(haiti), rc.measure_voice(ours)
    assert corpus["narration_tense"].startswith("present")
    assert generated["narration_tense"].startswith("past")
    assert "five words or fewer" in corpus["sentence_length"]
    assert rc.measure_voice("") == {}, "an empty transcript measures nothing"


def test_the_two_voice_fields_reach_even_a_single_reference_engine():
    """Withholding them until `balanced` means an engine with one reference never learns them."""
    import reference_corpus as rc

    for field in ("narration_tense", "sentence_length"):
        assert field in rc.OBSERVED_FIELDS
    # They belong at loose once every reference carries them: they are voice, they carry no
    # subject, and the engines that need them most have a single reference.
    assert "cobra_effect" in {p.stem for p in __import__("pathlib").Path("fixtures/causal").glob("*.json")}


def test_every_retrievable_reference_carries_the_voice_fields():
    """They are sent at loose, so any reference retrieval can pick must supply them.

    Held back for a day because three references had no source video: sending a field half the
    corpus lacks lets retrieval pick a thinner one by runtime and hand the generator less, which
    `test_no_reference_is_thinner_than_the_one_it_can_displace` caught when it shipped early.
    """
    import json
    from pathlib import Path
    import explainer_pipeline as ep
    import reference_corpus as rc

    for field in ("narration_tense", "sentence_length"):
        for level in ("loose", "balanced", "strong"):
            assert field in rc._ADHERENCE_FIELDS[level], f"{field} missing at {level}"

    # Only where an engine has SIBLINGS. The harm this guards is asymmetry -- retrieval choosing
    # by runtime between two references and picking the thinner one. An engine with a single
    # reference cannot be inconsistent with itself: almost_happened_plan's hippo_weed has no
    # source video to measure and simply omits the fields, which is the status quo for that engine
    # rather than a regression.
    by_engine = {}
    for path in Path("fixtures/causal").glob("*.json"):
        payload = json.loads(path.read_text())
        engine = (payload.get("story") or {}).get("engine")
        if engine:
            synthetic = (str(payload.get("reference_origin") or "").strip().casefold()
                         == "ai_authored_researched_candidate")
            by_engine.setdefault(engine, []).append(
                (path.stem, payload.get("observed") or {}, synthetic))
    # Partition by origin. An AI-authored candidate is barred from supplying voice by policy
    # (reference_corpus._VOICE_FIELDS), so it is not "thin" in the sense this guard means -- it is
    # structure-only on purpose, the same way hippo_weed omits fields it never measured. The
    # asymmetry that hurts is still real, though, and it lives entirely among the references that
    # ARE allowed to supply voice: two measured siblings where retrieval can pick the poorer one.
    for engine, refs in by_engine.items():
        measured = [(name, observed) for name, observed, synthetic in refs if not synthetic]
        if len(measured) < 2:
            continue
        for name, observed in measured:
            assert "sentence_length" in observed, \
                f"{name} cannot supply what loose sends, and a sibling can"

    # The unguarded case: an engine holding BOTH a measured and a synthetic reference.
    # `_retrieve_blueprint` picks by nearest runtime and knows nothing about origin, so it could
    # hand the generator a structure-only candidate where a measured sibling would have carried
    # voice -- exactly the asymmetry above, reintroduced through the back door. No engine mixes
    # origins today. Fail here the moment one does, rather than in a render whose narration
    # quietly lost its tense and sentence-length guidance.
    for engine, refs in by_engine.items():
        origins = {synthetic for _, _, synthetic in refs}
        assert len(origins) < 2, (
            f"{engine} mixes measured and synthetic references; retrieval picks by runtime and "
            "would silently drop voice guidance. Teach _retrieve_blueprint to prefer a measured "
            "reference before allowing this.")

    for engine, runtime in (("backfiring_solution", 90), ("backfiring_solution", 220),
                            ("accumulating_indictment", 170), ("power_reversal", 220)):
        block = ep._retrieve_blueprint(engine, "loose", runtime)
        assert "narration_tense" in block and "sentence_length" in block, f"{engine}@{runtime}"


def test_voice_is_measured_from_narration_not_from_beat_summaries():
    """A fixture's `situation` is the labeller's summary of a beat, not the spoken narration.

    Measuring those gave medians of 17-22 words against the 5-6 the real transcripts show, which
    would have taught the generator that the corpus writes long -- the reverse of the truth.
    Only fixtures whose text IS the narration carry these fields.
    """
    import json
    from pathlib import Path

    measured, summarised = [], []
    for path in sorted(Path("fixtures/causal").glob("*.json")):
        observed = json.loads(path.read_text()).get("observed") or {}
        (measured if "sentence_length" in observed else summarised).append(path.stem)
    assert measured, "at least the transcript-derived references carry it"
    for name in measured:
        observed = json.loads(Path(f"fixtures/causal/{name}.json").read_text())["observed"]
        median = int(observed["sentence_length"].split()[1])
        assert median <= 12, f"{name}: median {median} words looks like beat summaries, not speech"
