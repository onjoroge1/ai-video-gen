"""Spend must survive the failure path, because that is where it matters most.

Four Hanoi beat-sheet attempts each bought a planner call and a set of entailment judgements, and
each reported `recorded cost=$0.0000`. Not a rounding problem: `_generate_script_chunked`
accumulates a local total and publishes it in its return dict, so a raise loses all of it. With
five sampled attempts per architectural change now the plan, a change that buys stability by
tripling planning spend and one that gets it free would read identically.
"""
import json

import pytest

import cost_ledger as cl
import explainer_pipeline as ep


def test_a_ledger_can_stand_in_for_any_cost_sink_list():
    """Every sink parameter in the pipeline is typed as a list and summed with sum()."""
    ledger = cl.CostLedger()
    ledger.append(0.25)
    ledger.charge(cl.BEAT_SHEET, 0.5)
    assert round(sum(ledger), 6) == 0.75 and len(ledger) == 2
    assert ledger.by_stage() == {cl.UNATTRIBUTED: 0.25, cl.BEAT_SHEET: 0.5}


def test_an_empty_ledger_is_still_a_sink():
    """`if cost_sink:` guards a lot of call sites; an empty list is falsy and a ledger must not be."""
    assert bool(cl.CostLedger()) is True


def test_charging_is_a_no_op_on_a_plain_list_so_nothing_double_counts():
    """Callers compute `sum(cost_sink) + script['_script_cost_usd']`. Both would count a charge."""
    sink: list = []
    assert ep._charge(sink, cl.BEAT_SHEET, 0.4) == 0.4
    assert sink == [], "a plain-list sink must be left exactly as the caller expects"
    assert ep._charge(None, cl.BEAT_SHEET, 0.4) == 0.4


def test_spend_is_on_disk_before_the_attempt_finishes(tmp_path):
    path = tmp_path / "nested" / "spend.json"
    ledger = cl.CostLedger(str(path))
    ledger.charge(cl.BEAT_SHEET, 0.42, "10 beats")
    on_disk = json.loads(path.read_text())
    assert on_disk["total_usd"] == 0.42 and on_disk["by_stage"] == {cl.BEAT_SHEET: 0.42}
    ledger.charge(cl.BOUNDARY_A, 0.08)
    assert json.loads(path.read_text())["total_usd"] == 0.5, "rewritten per charge, not at the end"


def test_a_zero_charge_records_nothing_but_does_not_raise():
    ledger = cl.CostLedger()
    ledger.charge(cl.GRADE, 0)
    ledger.charge(cl.GRADE, None)
    assert ledger.total() == 0.0 and len(ledger) == 0


def test_the_beat_sheet_charges_before_the_spine_can_raise(monkeypatch):
    """The exact failure: a planner call is paid for, then the spine gate refuses the story."""
    ledger = cl.CostLedger()

    class _Usage:
        input_tokens, output_tokens = 20000, 6000

    class _Response:
        usage, stop_reason = _Usage(), "end_turn"
        content = [type("C", (), {"text": json.dumps({"beats": []})})()]

    monkeypatch.setattr(ep, "_parse_script_json", lambda text, **kwargs: ({"beats": []}, 0.0))
    expected = (_Usage.input_tokens * ep._RATE_SCRIPT_IN
                + _Usage.output_tokens * ep._RATE_SCRIPT_OUT)
    ep._charge(ledger, cl.BEAT_SHEET, expected, "10 beats")
    assert ledger.by_stage()[cl.BEAT_SHEET] == round(expected, 6)
    assert ledger.total() > 0, "an attempt that dies after this point still reports spend"


def test_stage_names_are_constants_not_literals():
    """A stage that splits under a typo reports half its spend and reads as an improvement."""
    source = open(ep.__file__, encoding="utf-8").read()
    for call in ("_charge(cost_sink, ", "cost_sink.charge("):
        for index in range(source.count(call)):
            start = source.index(call, 0 if not index else start + 1) + len(call)
            assert source[start:start + 8].startswith("_ledger."), \
                f"stage argument at offset {start} is not a cost_ledger constant"


def test_only_script_stages_are_treated_as_already_in_script_cost_usd():
    """A caller holding both figures must add exactly the part the script total does not cover."""
    ledger = cl.CostLedger()
    ledger.charge(cl.RESEARCH, 0.20)
    ledger.charge(cl.BEAT_SHEET, 0.50)
    ledger.append(0.05)                       # a judge cost nothing else reports
    assert ledger.script_stage_total() == 0.50
    assert cl.UNATTRIBUTED not in cl.SCRIPT_STAGES and cl.RESEARCH not in cl.SCRIPT_STAGES


def test_every_stage_the_generator_charges_is_declared_a_script_stage():
    """Miss one and its spend is counted twice; add one wrongly and real spend disappears."""
    source = open(ep.__file__, encoding="utf-8").read()
    inside = source[source.index("def _generate_script_chunked("):]
    inside = inside[:inside.index('"_script_cost_usd": round(cost,')]
    charged = {line.split("_ledger.")[1].split(",")[0].split(")")[0].strip()
               for line in inside.splitlines() if "_charge(cost_sink, _ledger." in line}
    declared = {name for name in dir(cl)
                if name.isupper() and getattr(cl, name) in cl.SCRIPT_STAGES}
    assert charged and charged <= declared, f"charged but not declared: {charged - declared}"
