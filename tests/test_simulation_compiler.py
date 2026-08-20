from decimal import Decimal

import pytest

from bolt_video.simulation import SimulationCompileError, build_simulation_prompt_block, compile_simulation
from bolt_video.simulation.models import Direction, QuantityKind


def test_growth_uses_total_height_not_only_delta():
    spec = compile_simulation("What if you grew 1 cm every second?")
    first = spec.checkpoints[0]
    assert spec.rule.kind is QuantityKind.LENGTH
    assert first.delta == Decimal("0.60")
    assert first.total == Decimal("2.30")
    assert first.display == "2.3 m tall"
    prompt = build_simulation_prompt_block(spec.rule.title)
    assert "delta +315360" in prompt
    assert "3.1536E" not in prompt


def test_mass_rate_converts_minutes_and_pounds_exactly():
    spec = compile_simulation("What if you gained 2 pounds every minute?")
    assert spec.checkpoints[0].total == Decimal("70.907184740")


def test_shrinking_stops_at_model_floor_without_quantum_claim():
    spec = compile_simulation("What if you shrank 1 cm every second?")
    assert spec.rule.direction is Direction.DECREASE
    assert spec.checkpoints[-1].total == Decimal("0.01")
    prompt = build_simulation_prompt_block(spec.rule.title)
    assert "quantum minimum" not in prompt.lower()
    assert "human-body model" in prompt


def test_cooling_uses_real_absolute_zero_and_zero_point_warning():
    spec = compile_simulation("What if you cooled 1 degree Celsius every second?")
    assert spec.checkpoints[-1].total == Decimal("-273.15")
    assert "zero-point motion" in " ".join(spec.warnings)


@pytest.mark.parametrize("title", [
    "What if you grew every second?",
    "What if you grew 1 banana every second?",
    "What if you grew 1 percent every second?",
    "What if you lost 1 point every second?",
])
def test_ambiguous_or_unsupported_rules_fail_closed(title):
    with pytest.raises(SimulationCompileError):
        compile_simulation(title)
