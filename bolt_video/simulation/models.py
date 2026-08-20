from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class QuantityKind(str, Enum):
    LENGTH = "length"
    MASS = "mass"
    TEMPERATURE = "temperature"
    COUNT = "count"


class Direction(str, Enum):
    INCREASE = "increase"
    DECREASE = "decrease"


@dataclass(frozen=True)
class SimulationRule:
    title: str
    rate_per_second: Decimal
    kind: QuantityKind
    direction: Direction
    canonical_unit: str
    baseline: Decimal
    floor: Decimal | None = None


@dataclass(frozen=True)
class SimulationCheckpoint:
    label: str
    elapsed_seconds: int
    delta: Decimal
    total: Decimal
    display: str


@dataclass(frozen=True)
class SimulationSpec:
    rule: SimulationRule
    checkpoints: tuple[SimulationCheckpoint, ...]
    warnings: tuple[str, ...]
