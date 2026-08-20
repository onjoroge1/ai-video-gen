"""Deterministic linear simulation compiler.

Only rules the code understands are accepted. Unsupported units and percentages fail
closed rather than quietly asking an LLM to invent arithmetic.
"""
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .models import Direction, QuantityKind, SimulationCheckpoint, SimulationRule, SimulationSpec


class SimulationCompileError(ValueError):
    pass


PERIOD_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
CHECKPOINTS = (("1 minute", 60), ("10 minutes", 600), ("1 hour", 3600),
               ("6 hours", 21600), ("1 day", 86400), ("1 week", 604800),
               ("1 month", 2_592_000), ("1 year", 31_536_000))
LENGTH = {"mm": Decimal("0.001"), "millimeter": Decimal("0.001"), "millimeters": Decimal("0.001"),
          "cm": Decimal("0.01"), "centimeter": Decimal("0.01"), "centimeters": Decimal("0.01"),
          "m": Decimal("1"), "meter": Decimal("1"), "meters": Decimal("1"),
          "metre": Decimal("1"), "metres": Decimal("1"),
          "km": Decimal("1000"), "kilometer": Decimal("1000"), "kilometers": Decimal("1000"),
          "kilometre": Decimal("1000"), "kilometres": Decimal("1000")}
MASS = {"g": Decimal("0.001"), "gram": Decimal("0.001"), "grams": Decimal("0.001"),
        "kg": Decimal("1"), "kilogram": Decimal("1"), "kilograms": Decimal("1"),
        "lb": Decimal("0.45359237"), "lbs": Decimal("0.45359237"),
        "pound": Decimal("0.45359237"), "pounds": Decimal("0.45359237"),
        "tonne": Decimal("1000"), "tonnes": Decimal("1000"),
        "ton": Decimal("907.18474"), "tons": Decimal("907.18474")}
COUNT_UNITS = {"point", "points", "step", "steps", "item", "items"}
DECREASE_WORDS = {"shrink", "shrinks", "shrank", "shrinking", "lose", "loses", "lost", "losing",
                  "cool", "cools", "cooled", "cooling", "colder", "decrease", "decreases",
                  "decreased", "drop", "drops", "dropped", "lighter", "smaller"}


def _direction(title: str) -> Direction:
    words = set(re.findall(r"[a-z]+", title.lower()))
    return Direction.DECREASE if words & DECREASE_WORDS else Direction.INCREASE


def _format_decimal(value: Decimal, places: str = "0.01") -> str:
    rounded = value.quantize(Decimal(places), rounding=ROUND_HALF_UP)
    return f"{rounded:,.2f}".rstrip("0").rstrip(".")


def _display(kind: QuantityKind, value: Decimal) -> str:
    if kind is QuantityKind.LENGTH:
        if value < 1:
            return f"{_format_decimal(value * 100)} cm tall"
        if value < 1000:
            return f"{_format_decimal(value)} m tall"
        return f"{_format_decimal(value / 1000)} km tall"
    if kind is QuantityKind.MASS:
        if value < 1000:
            return f"{_format_decimal(value)} kg total mass"
        return f"{_format_decimal(value / 1000)} tonnes total mass"
    if kind is QuantityKind.TEMPERATURE:
        return f"{_format_decimal(value)} °C"
    return f"{_format_decimal(value)} total"


def _duration_label(seconds: int) -> str:
    if seconds < 120:
        return f"~{seconds} seconds"
    if seconds < 7200:
        return f"~{_format_decimal(Decimal(seconds) / 60)} minutes"
    if seconds < 172800:
        return f"~{_format_decimal(Decimal(seconds) / 3600)} hours"
    return f"~{_format_decimal(Decimal(seconds) / 86400)} days"


def _decreasing_targets(kind: QuantityKind) -> tuple[Decimal, ...]:
    if kind is QuantityKind.LENGTH:
        return tuple(map(Decimal, ("1.5", "1", "0.5", "0.1", "0.01")))
    if kind is QuantityKind.MASS:
        return tuple(map(Decimal, ("60", "50", "35", "20", "5", "0")))
    if kind is QuantityKind.TEMPERATURE:
        return tuple(map(Decimal, ("35", "32", "28", "20", "0", "-40", "-196", "-273.15")))
    return ()


def compile_simulation(title: str) -> SimulationSpec:
    text = (title or "").strip().lower().replace("degrees celsius", "celsius").replace("degree celsius", "celsius")
    if "%" in text or "percent" in text:
        raise SimulationCompileError("Percentage/compound simulations are not supported yet; use a linear absolute unit.")
    match = re.search(
        r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[a-z]+)\b.*?\bevery\s+(?P<period>second|minute|hour|day)\b",
        text,
    )
    if not match:
        raise SimulationCompileError(
            "Use an explicit linear rule such as 'grow 1 cm every second' or 'lose 1 kg every minute'."
        )
    try:
        value = Decimal(match.group("value"))
    except InvalidOperation as exc:
        raise SimulationCompileError("The simulation rate is not a valid number.") from exc
    if value <= 0:
        raise SimulationCompileError("The simulation rate must be greater than zero.")
    unit = match.group("unit")
    direction = _direction(text)
    if unit in LENGTH:
        kind, factor, baseline = QuantityKind.LENGTH, LENGTH[unit], Decimal("1.70")
        # 1 cm is a narrative/model-validity stop, not a claimed fundamental quantum floor.
        floor = Decimal("0.01") if direction is Direction.DECREASE else None
    elif unit in MASS:
        kind, factor, baseline = QuantityKind.MASS, MASS[unit], Decimal("70")
        floor = Decimal("0") if direction is Direction.DECREASE else None
    elif unit in {"c", "celsius"}:
        kind, factor, baseline = QuantityKind.TEMPERATURE, Decimal("1"), Decimal("37")
        floor = Decimal("-273.15") if direction is Direction.DECREASE else None
    elif unit in COUNT_UNITS:
        if direction is Direction.DECREASE:
            raise SimulationCompileError("A decreasing count needs an explicit starting value; this title has none.")
        kind, factor, baseline, floor = QuantityKind.COUNT, Decimal("1"), Decimal("0"), None
    else:
        raise SimulationCompileError(
            f"Unsupported unit '{unit}'. Supported: mm/cm/m/km, g/kg/lb/tonne, Celsius, or explicit count units."
        )
    rate = value * factor / Decimal(PERIOD_SECONDS[match.group("period")])
    rule = SimulationRule(title.strip(), rate, kind, direction,
                          {QuantityKind.LENGTH: "m", QuantityKind.MASS: "kg",
                           QuantityKind.TEMPERATURE: "°C", QuantityKind.COUNT: "count"}[kind],
                          baseline, floor)
    rows: list[SimulationCheckpoint] = []
    if direction is Direction.DECREASE:
        for target in _decreasing_targets(kind):
            if target >= baseline:
                continue
            elapsed = max(1, int(((baseline - target) / rate).to_integral_value(rounding=ROUND_HALF_UP)))
            label = ("floor at " if target == floor else "") + _duration_label(elapsed)
            rows.append(SimulationCheckpoint(label, elapsed, target - baseline, target, _display(kind, target)))
    else:
        for label, seconds in CHECKPOINTS:
            delta = rate * Decimal(seconds)
            total = baseline + delta
            rows.append(SimulationCheckpoint(label, seconds, delta, total, _display(kind, total)))
    warnings = []
    if kind is QuantityKind.LENGTH and direction is Direction.DECREASE:
        warnings.append("Stop at 1 cm: the human-body model has failed. Do not treat quantum mechanics as a person-size floor.")
    if kind is QuantityKind.MASS and direction is Direction.DECREASE:
        warnings.append("Biological death occurs long before zero mass; zero is only the arithmetic floor.")
    if kind is QuantityKind.TEMPERATURE and direction is Direction.DECREASE:
        warnings.append("Absolute zero is a thermodynamic limit; do not say all atomic motion stops because zero-point motion remains.")
    return SimulationSpec(rule, tuple(rows), tuple(warnings))
