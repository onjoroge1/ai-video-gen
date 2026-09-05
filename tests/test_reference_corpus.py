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


@pytest.fixture
def runtime_guidance(monkeypatch):
    monkeypatch.setattr(rc.cs, "MECHANISM_DEADLINE_PCT", 0.20)
    return lambda duration: {row["engine_id"]: row for row in rc.runtime_fit_guidance(duration)}


@pytest.mark.parametrize("duration,deadline,compression", [(170, 34, 2), (180, 36, 0), (220, 44, 0)])
def test_cobra_observed_opening_needs_only_two_seconds_compression_at_170(
    runtime_guidance, duration, deadline, compression,
):
    """36 / .20 is 180, not 190; a reference timing is not an engine feasibility floor."""
    engine = runtime_guidance(duration)[se.BACKFIRING_SOLUTION]
    sample = next(row for row in engine["references"] if row["reference_id"] == "cobra_effect")
    assert engine["target_deadline_sec"] == deadline
    assert engine["required_milestones_through_mechanism"] == 5
    assert engine["support_count"] == 1
    assert sample["observed_opening_sec"] == 36
    assert sample["milestones_through_mechanism"] == 5
    assert sample["compression_needed_sec"] == compression
    assert sample["compression_needed_pct"] == pytest.approx(100 * compression / 36, abs=.001)
    assert sample["unchanged_opening_min_runtime_sec"] == 180


def test_reference_variation_and_optional_roles_remain_visible(runtime_guidance):
    guidance = runtime_guidance(170)
    indictment = guidance[se.ACCUMULATING_INDICTMENT]
    assert indictment["support_count"] == 2
    assert indictment["required_milestones_through_mechanism"] == 3
    assert indictment["optional_milestones_before_mechanism"] == ["false_resolution"]
    assert {sample["observed_opening_sec"] for sample in indictment["references"]} == {20, 33}
    assert all(sample["milestones_through_mechanism"] == 4 for sample in indictment["references"])

    power = guidance[se.POWER_REVERSAL]
    assert power["support_count"] == 2
    assert power["required_milestones_through_mechanism"] == 3
    assert power["optional_milestones_before_mechanism"] == ["intervention"]
    samples = {sample["reference_id"]: sample for sample in power["references"]}
    assert samples["pompeii"]["observed_opening_sec"] == 22
    assert samples["pompeii"]["milestones_through_mechanism"] == 3
    assert samples["pompeii"]["compression_needed_sec"] == 0
    assert samples["romanov_fall"]["observed_opening_sec"] == 44
    assert samples["romanov_fall"]["milestones_through_mechanism"] == 4
    assert samples["romanov_fall"]["compression_needed_sec"] == 10


def test_unmeasured_and_missing_references_do_not_supply_fake_timing_evidence(runtime_guidance):
    guidance = runtime_guidance(170)
    written = guidance[se.ALMOST_HAPPENED_PLAN]
    assert written["reference_count"] == 1
    assert written["support_count"] == 0
    sample = written["references"][0]
    assert sample["reference_id"] == "hippo_weed"
    assert sample["milestones_through_mechanism"] == 5  # An interleaved escalation is not a milestone.
    assert sample["observed_opening_sec"] is None
    assert sample["compression_needed_sec"] is None
    assert sample["unchanged_opening_min_runtime_sec"] is None
    assert written["target_deadline_sec"] == 102  # Keep the engine's existing 60% deadline.
    assert guidance[se.ACCIDENTAL_INVENTION]["reference_count"] == 0
    assert guidance[se.ACCIDENTAL_INVENTION]["support_count"] == 0


@pytest.mark.parametrize("opening", [None, "invalid", float("nan"), float("inf"), -1, 201])
def test_invalid_reference_timestamps_are_unknown_not_compression_evidence(tmp_path, opening):
    _write(tmp_path, "invalid", engine=se.BACKFIRING_SOLUTION, measured={"runtime_sec": 200})
    path = tmp_path / "invalid.json"
    payload = json.loads(path.read_text())
    payload["story"]["steps"].append({"role": "mechanism", "start_sec": opening})
    path.write_text(json.dumps(payload))
    engine = next(row for row in rc.runtime_fit_guidance(170, tmp_path)
                  if row["engine_id"] == se.BACKFIRING_SOLUTION)
    assert engine["support_count"] == 0
    assert engine["references"][0]["observed_opening_sec"] is None


@pytest.mark.parametrize("duration", [0, -1, None, "invalid", float("nan"), float("inf")])
def test_invalid_target_runtime_is_rejected(duration):
    with pytest.raises(ValueError, match="positive finite"):
        rc.runtime_fit_guidance(duration)


def test_prompt_keeps_runtime_evidence_advisory():
    block = rc.runtime_fit_block(170)
    assert "not a gate or an engine ban" in block
    assert "not minimum runtimes" in block
    assert "Zero support means timing fit is unknown" in block
    assert "factual causal fit first" in block
    assert "Do not extend the requested runtime or the validation deadline" in block
